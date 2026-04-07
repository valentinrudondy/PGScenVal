"""Utility functions for working with distributions and models created in R."""

import warnings
from typing import Any, Union, Tuple

import numpy as np
import pandas as pd

from scipy.stats import norm
from sklearn.covariance import graphical_lasso as sklearn_graphical_lasso

try:
    import rpy2.robjects as robjects
    from rpy2.robjects.packages import importr
    from rpy2.robjects.methods import RS4 as GPD
    import rpy2.robjects.numpy2ri as numpy2ri

    numpy2ri.activate()

    base = importr('base')
    Rsafd = importr('Rsafd')
    glasso = importr('glasso')
    stats = importr('stats')
    HAS_R_BACKEND = True
except ModuleNotFoundError:
    robjects = None
    importr = None
    GPD = Any
    base = None
    Rsafd = None
    glasso = None
    stats = None
    HAS_R_BACKEND = False


class PGscenECDF:
    """Store an empirical CDF with a quantile helper."""

    def __init__(self, data: np.array, n: int = 1000) -> None:
        self.rclass = ['ecdf']
        self.data = np.sort(np.asarray(data, dtype=float))
        self.n = len(self.data)

        if HAS_R_BACKEND:
            self.ecdf = stats.ecdf(robjects.FloatVector(self.data))
            quants = robjects.FloatVector(np.linspace(0, 1, n + 1))
            self.approxfun = stats.approxfun(
                quants, stats.quantile(self.ecdf, quants)
            )
        else:
            self.ecdf = None
            self.approxfun = None

    def cdf(self, values: np.array) -> np.array:
        values = np.asarray(values, dtype=float)
        if self.n == 0:
            return np.zeros_like(values, dtype=float)

        return np.searchsorted(self.data, values, side='right') / self.n

    def quantfun(self, values: np.array) -> np.array:
        values = np.clip(np.asarray(values, dtype=float), 1e-5, 0.99999)
        if HAS_R_BACKEND:
            return np.asarray(self.approxfun(values), dtype=float)
        return np.quantile(self.data, values, method='linear')


def _coerce_alpha(rho: Union[float, np.ndarray]) -> float:
    """Reduce matrix-valued penalties to a scalar for sklearn fallbacks."""
    if np.isscalar(rho):
        return float(rho)

    rho = np.asarray(rho, dtype=float)
    if rho.size == 0:
        return 0.0

    off_diag = rho[~np.eye(rho.shape[0], dtype=bool)]
    finite = off_diag[np.isfinite(off_diag)]
    if finite.size == 0:
        finite = rho[np.isfinite(rho)]
    if finite.size == 0:
        return 0.0
    return float(np.mean(np.abs(finite)))


def qgpd(dist: GPD, x: np.array) -> np.array:
    """Wrapper for Rsafd qgpd; falls back to ECDF when R is unavailable."""
    if not HAS_R_BACKEND:
        return dist.quantfun(x)

    try:
        return np.array(Rsafd.qgpd(dist, robjects.FloatVector(x)))
    except Exception:
        ll = min(dist.slots['data'])
        rr = max(dist.slots['data'])
        xx = np.linspace(ll, rr, 1001)
        ff = stats.approxfun(Rsafd.pgpd(dist, xx), xx, rule=2)
        return ff(x)


def fit_gpd(data: np.array) -> Union[GPD, PGscenECDF]:
    """Fit a GPD if possible, otherwise fall back to the empirical CDF."""
    if not HAS_R_BACKEND:
        warnings.warn(
            'rpy2/R packages unavailable; using ECDF fallback instead of GPD.',
            RuntimeWarning,
            stacklevel=2,
        )
        return PGscenECDF(data)

    try:
        dist = Rsafd.fit_gpd(robjects.FloatVector(data), tail='two', plot=False)

        upper = dist.slots['upper.converged'][0]
        lower = dist.slots['lower.converged'][0]

        if upper and lower:
            return dist
        if upper:
            return Rsafd.fit_gpd(robjects.FloatVector(data), tail='left', plot=False)
        if lower:
            return Rsafd.fit_gpd(robjects.FloatVector(data), tail='right', plot=False)

        warnings.warn('no tail has been detected, using ECDF instead', RuntimeWarning)
        return PGscenECDF(data)
    except Exception:
        warnings.warn('unable to fit GPD, using ECDF instead', RuntimeWarning)
        return PGscenECDF(data)


def qdist(dist: Union[GPD, PGscenECDF], x: np.array,
          gpd_max_extension: float = 0.15) -> np.array:
    """Compute quantiles from either a fitted GPD or an empirical CDF."""
    rclass = tuple(dist.rclass)[0]

    if rclass[0:3] == 'gpd':
        data_min = np.min(dist.slots['data'])
        data_max = np.max(dist.slots['data'])
        clip_min = data_min - gpd_max_extension * (data_max - data_min)
        clip_max = data_max + gpd_max_extension * (data_max - data_min)
        return np.clip(qgpd(dist, x), clip_min, clip_max)

    if rclass == 'ecdf':
        if HAS_R_BACKEND:
            return np.asarray(
                stats.quantile(dist.ecdf, robjects.FloatVector(x)),
                dtype=float,
            )
        return dist.quantfun(x)

    raise RuntimeError(f'Unrecognized distribution class {tuple(dist.rclass)}')


def standardize(table: pd.DataFrame,
                ignore_pointmass: bool = True) -> Tuple[pd.Series, pd.Series,
                                                        pd.DataFrame]:
    avg, std = table.mean(), table.std()

    if ignore_pointmass:
        std[std < 1e-2] = 1.
    elif (std < 1e-2).any():
        raise RuntimeError(
            f'encountered point masses in columns {std[std < 1e-2].index.tolist()}'
        )

    return avg, std, (table - avg) / std


def gaussianize(df: pd.DataFrame, gpd: bool = False) -> Tuple[dict, pd.DataFrame]:
    """Transform each column to approximately Gaussian marginals."""
    unif_df = pd.DataFrame(columns=df.columns, index=df.index, dtype=float)
    dist_dict = dict()

    for col in df.columns:
        data = np.ascontiguousarray(df[col].values, dtype=float)

        if gpd:
            dist_dict[col] = fit_gpd(data)
        else:
            dist_dict[col] = PGscenECDF(data)

        if HAS_R_BACKEND and hasattr(dist_dict[col], 'rclass') and tuple(dist_dict[col].rclass)[0][0:3] == 'gpd':
            unif_df[col] = np.array(
                Rsafd.pgpd(dist_dict[col], robjects.FloatVector(data))
            )
        else:
            unif_df[col] = dist_dict[col].cdf(data)

    unif_df.clip(lower=1e-5, upper=0.99999, inplace=True)
    gauss_df = unif_df.apply(norm.ppf)
    return dist_dict, gauss_df


def graphical_lasso(df: pd.DataFrame, m: int, rho: float):
    """Fit a graphical lasso precision matrix from a dataframe."""
    assert df.shape[1] == m, (
        f"Expected a DataFrame with {m} columns, got {df.shape[1]}"
    )

    cov = df.cov().values

    if HAS_R_BACKEND:
        rcov = robjects.r.matrix(cov, nrow=m, ncol=m)
        res = glasso.glasso(rcov, rho=rho, penalize_diagonal=False)
        return dict(zip(res.names, list(res)))['wi']

    _, precision = sklearn_graphical_lasso(emp_cov=cov, alpha=_coerce_alpha(rho))
    return precision


def gemini(df: pd.DataFrame,
           m: int, f: int, pA: float, pB: float) -> Tuple[np.array, np.array]:
    """Fit the separable GEMINI precision matrices."""
    assert df.shape[1] == m * f, (
        f"Expected a DataFrame with {f * m} columns, found {df.shape[1]} columns instead!"
    )

    n = len(df)
    XTX = np.zeros((m, m))
    XXT = np.zeros((f, f))

    for _, row in df.iterrows():
        X = np.reshape(row.values, (f, m), order='F')
        XTX += X.T @ X
        XXT += X @ X.T

    WA = np.diag(XTX)
    WB = np.diag(XXT)
    WA = np.where(np.abs(WA) < 1e-10, 1e-10, WA)
    WB = np.where(np.abs(WB) < 1e-10, 1e-10, WB)

    GA = XTX / np.sqrt(np.outer(WA, WA))
    GB = XXT / np.sqrt(np.outer(WB, WB))

    if HAS_R_BACKEND:
        GAr = robjects.r.matrix(GA, nrow=m, ncol=m)
        GBr = robjects.r.matrix(GB, nrow=f, ncol=f)
        rA = glasso.glasso(GAr, rho=pA, penalize_diagonal=False)
        rB = glasso.glasso(GBr, rho=pB, penalize_diagonal=False)
        Arho = dict(zip(rA.names, list(rA)))['wi']
        Brho = dict(zip(rB.names, list(rB)))['wi']
    else:
        _, Arho = sklearn_graphical_lasso(emp_cov=GA, alpha=_coerce_alpha(pA))
        _, Brho = sklearn_graphical_lasso(emp_cov=GB, alpha=_coerce_alpha(pB))

    fact = np.sum(np.multiply(df.values, df.values)) / n

    WA = np.diag(np.sqrt(n / WA))
    WB = np.diag(np.sqrt(n / WB))
    A = np.sqrt(fact) * WA @ Arho @ WA
    B = np.sqrt(fact) * WB @ Brho @ WB

    return A, B
