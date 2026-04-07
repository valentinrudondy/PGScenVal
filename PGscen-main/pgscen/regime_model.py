"""
Regime-switching GEMINI models for power grid scenario generation.

This module extends the base GeminiModel and GeminiEngine classes with a
Hidden Markov Model (HMM) regime-switching layer. Instead of fitting a single
static GEMINI precision matrix to all historical data, it identifies K latent
weather regimes and fits a separate separable covariance structure per regime.

The key mathematical contribution is the soft-assignment weighted GEMINI
estimation in the EM M-step, which reuses the existing GEMINI algorithm with
a reweighted empirical covariance matrix — keeping the Kronecker-separable
structure intact within each regime and thus preserving tractability at high
dimensionality.

Architecture
------------
RegimeGeminiModel  : extends GeminiModel
    Adds regime-specific asset_cov/horizon_cov lists and EM fitting.

RegimeGeminiEngine : extends GeminiEngine
    Wraps RegimeGeminiModel, handles HMM forward pass for regime prediction
    at generation time, and implements mixture sampling over regimes.

RegimePCAGeminiEngine : extends PCAGeminiEngine
    Same regime logic applied to the solar PCA pipeline.
"""

import numpy as np
import pandas as pd

from copy import deepcopy
from scipy.linalg import sqrtm
from scipy.stats import norm, multivariate_normal
from sklearn.cluster import KMeans
from typing import List, Dict, Tuple, Optional, Union, Iterable

from .model import GeminiModel, GeminiError, get_asset_list
from .engine import GeminiEngine
from .pca import PCAGeminiEngine, PCAGeminiModel
from .utils.r_utils import (gemini, graphical_lasso, gaussianize,
                             standardize, qdist, PGscenECDF)


# ---------------------------------------------------------------------------
# Helper: weighted GEMINI
# ---------------------------------------------------------------------------

def _weighted_gemini(df: pd.DataFrame,
                     weights: np.ndarray,
                     m: int, f: int,
                     pA: float, pB: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Weighted variant of the GEMINI algorithm.

    Instead of using a uniform empirical covariance, each historical day d
    is weighted by its posterior regime probability gamma_k^d. This is the
    core innovation of the EM M-step: the standard GEMINI call is reused
    almost unchanged, but with a soft-weighted covariance matrix as input.

    Parameters
    ----------
    df : pd.DataFrame
        Gaussianized historical deviations, shape (N_days, m * f).
    weights : np.ndarray
        Posterior regime probabilities for each day, shape (N_days,).
        Should sum to approximately 1 across days (will be renormalized).
    m : int
        Number of spatial components (assets or zones).
    f : int
        Number of temporal components (horizons or PCA components).
    pA, pB : float
        Spatial and temporal LASSO regularization penalties.

    Returns
    -------
    A, B : np.ndarray
        Spatial and temporal precision matrices.
    """
    from .utils.r_utils import glasso, robjects

    # renormalize weights
    w = np.array(weights, dtype=float)
    w = w / w.sum()

    n_eff = 1.0 / np.sum(w ** 2)   # effective sample size

    # build weighted cross-product matrices (analogues of XTX, XXT in GEMINI)
    XTX = np.zeros((m, m))
    XXT = np.zeros((f, f))

    for i, (_, row) in enumerate(df.iterrows()):
        X = np.reshape(row.values, (f, m), order='F')
        XTX += w[i] * X.T @ X
        XXT += w[i] * X @ X.T

    WA = np.diag(XTX)
    WB = np.diag(XXT)

    # guard against near-zero diagonals (can happen in sparse regimes)
    WA = np.where(np.abs(WA) < 1e-10, 1e-10, WA)
    WB = np.where(np.abs(WB) < 1e-10, 1e-10, WB)

    GA = XTX / np.sqrt(np.outer(WA, WA))
    GB = XXT / np.sqrt(np.outer(WB, WB))

    GAr = robjects.r.matrix(GA, nrow=m, ncol=m)
    GBr = robjects.r.matrix(GB, nrow=f, ncol=f)

    rA = glasso.glasso(GAr, rho=pA, penalize_diagonal=False)
    rB = glasso.glasso(GBr, rho=pB, penalize_diagonal=False)

    Arho = dict(zip(rA.names, list(rA)))['wi']
    Brho = dict(zip(rB.names, list(rB)))['wi']

    fact = np.sum(w[:, None] * df.values ** 2)

    WA_mat = np.diag(np.sqrt(n_eff / WA))
    WB_mat = np.diag(np.sqrt(n_eff / WB))

    A = np.sqrt(fact) * WA_mat @ Arho @ WA_mat
    B = np.sqrt(fact) * WB_mat @ Brho @ WB_mat

    return A, B


def _weighted_graphical_lasso(df: pd.DataFrame,
                               weights: np.ndarray,
                               m: int,
                               rho: float) -> np.ndarray:
    """
    Weighted graphical LASSO (used for single-asset or single-horizon cases).

    Parameters
    ----------
    df : pd.DataFrame
        Input data, shape (N_days, m).
    weights : np.ndarray
        Posterior regime probabilities, shape (N_days,).
    m : int
        Number of variables.
    rho : float
        LASSO regularization penalty.

    Returns
    -------
    prec : np.ndarray
        Estimated precision matrix, shape (m, m).
    """
    from .utils.r_utils import glasso, robjects

    w = np.array(weights, dtype=float)
    w = w / w.sum()

    # weighted covariance
    vals = df.values
    mean = np.average(vals, weights=w, axis=0)
    cov = np.zeros((m, m))
    for i in range(len(w)):
        diff = vals[i] - mean
        cov += w[i] * np.outer(diff, diff)

    rcov = robjects.r.matrix(cov, nrow=m, ncol=m)
    res = glasso.glasso(rcov, rho=rho, penalize_diagonal=False)

    return dict(zip(res.names, list(res)))['wi']


# ---------------------------------------------------------------------------
# RegimeGeminiModel
# ---------------------------------------------------------------------------

class RegimeGeminiModel(GeminiModel):
    """
    A GEMINI model augmented with HMM-based regime switching.

    After Gaussianization (inherited from GeminiModel.__init__), the EM
    algorithm identifies K latent regimes and fits a separate pair of
    (asset_cov^(k), horizon_cov^(k)) for each regime k.

    Key attributes added beyond GeminiModel
    ----------------------------------------
    n_regimes : int
        Number of latent regimes K.
    regime_asset_covs : List[pd.DataFrame]
        List of K asset covariance matrices.
    regime_horizon_covs : List[pd.DataFrame]
        List of K horizon covariance matrices.
    trans_matrix : np.ndarray, shape (K, K)
        HMM transition probability matrix A.
    init_probs : np.ndarray, shape (K,)
        HMM initial regime probabilities pi.
    gamma : np.ndarray, shape (N_days, K)
        Posterior regime probabilities from the last EM E-step.
    regime_weights : np.ndarray, shape (K,)
        Predictive regime probabilities for the scenario generation day,
        computed by the forward HMM pass in RegimeGeminiEngine.
    """

    def __init__(self,
                 scen_start_time: pd.Timestamp,
                 hist_dfs: Optional[Dict[str, pd.DataFrame]] = None,
                 gauss_df: Optional[pd.DataFrame] = None,
                 dev_index: Optional[Iterable[pd.Timestamp]] = None,
                 forecast_resolution_in_minute: int = 60,
                 num_of_horizons: int = 24,
                 forecast_lead_time_in_hour: int = 12,
                 use_gpd: bool = False,
                 n_regimes: int = 3) -> None:

        # delegate all Gaussianization to the parent
        super().__init__(
            scen_start_time, hist_dfs, gauss_df, dev_index,
            forecast_resolution_in_minute, num_of_horizons,
            forecast_lead_time_in_hour, use_gpd
        )

        self.n_regimes = n_regimes

        # regime-specific model parameters (populated by fit_regimes)
        self.regime_asset_covs: List[pd.DataFrame] = []
        self.regime_horizon_covs: List[pd.DataFrame] = []
        self.trans_matrix: Optional[np.ndarray] = None
        self.init_probs: Optional[np.ndarray] = None
        self.gamma: Optional[np.ndarray] = None

        # predictive weights set by the engine before generate_gauss_scenarios
        self.regime_weights: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # EM algorithm
    # ------------------------------------------------------------------

    def fit_regimes(self,
                    asset_rho: float, horizon_rho: float,
                    shrinkage_rho: float = 0.1,
                    max_iter: int = 50,
                    tol: float = 1e-4,
                    init: str = 'kmeans') -> None:
        """
        Fit K regime-specific GEMINI models via the EM algorithm.

        Parameters
        ----------
        asset_rho, horizon_rho : float
            LASSO penalties passed to (weighted) GEMINI at each M-step.
        shrinkage_rho : float
            Strength of hierarchical shrinkage pulling each regime's precision
            matrix toward the common mean. rho=0 → fully independent regimes;
            rho→∞ → single static model. Default 0.1.
        max_iter : int
            Maximum number of EM iterations.
        tol : float
            Convergence threshold on the relative change in log-likelihood.
        init : str
            Initialization strategy: 'kmeans' (default) clusters the
            Gaussianized data to obtain starting hard assignments, or
            'random' for random soft initialization.
        """

        N = len(self.gauss_df)
        K = self.n_regimes

        if N < K:
            raise GeminiError(
                f"Not enough historical data ({N} days) to fit "
                f"{K} regimes. Reduce n_regimes or increase history."
            )

        # ---- Initialization ----
        gamma = self._initialize_gamma(N, K, init)

        # initialize HMM parameters
        trans_matrix = np.full((K, K), 1.0 / K)
        init_probs = np.full(K, 1.0 / K)

        # initial M-step to get starting covariance matrices
        asset_covs, horizon_covs = self._mstep_gemini(
            gamma, asset_rho, horizon_rho, shrinkage_rho
        )

        prev_log_lik = -np.inf

        # ---- EM loop ----
        for iteration in range(max_iter):

            # E-step: forward-backward to get gamma and xi
            gamma, xi, log_lik = self._estep(
                asset_covs, horizon_covs, trans_matrix, init_probs
            )

            # M-step: update transition matrix and covariance matrices
            trans_matrix = self._mstep_transition(xi, gamma)
            init_probs = gamma[0] / gamma[0].sum()
            asset_covs, horizon_covs = self._mstep_gemini(
                gamma, asset_rho, horizon_rho, shrinkage_rho
            )

            # convergence check
            rel_change = abs(log_lik - prev_log_lik) / (abs(prev_log_lik) + 1e-10)
            if rel_change < tol and iteration > 0:
                break

            prev_log_lik = log_lik

        # store results
        self.gamma = gamma
        self.trans_matrix = trans_matrix
        self.init_probs = init_probs
        self.regime_asset_covs = asset_covs
        self.regime_horizon_covs = horizon_covs

        # also set the parent's asset_cov/horizon_cov to the weighted average
        # so the inherited generate_gauss_scenarios still works as fallback
        avg_asset_cov = sum(
            gamma[:, k].mean() * asset_covs[k].values
            for k in range(K)
        )
        avg_horizon_cov = sum(
            gamma[:, k].mean() * horizon_covs[k].values
            for k in range(K)
        )

        self.asset_cov = pd.DataFrame(
            data=avg_asset_cov,
            index=self.asset_list, columns=self.asset_list
        )

        horizon_indx = ['_'.join(['lag', str(hz)])
                        for hz in range(self.num_of_horizons)]
        self.horizon_cov = pd.DataFrame(
            data=avg_horizon_cov,
            index=horizon_indx, columns=horizon_indx
        )

    def _initialize_gamma(self,
                          N: int, K: int, init: str) -> np.ndarray:
        """Initialize soft regime assignments gamma, shape (N, K)."""

        if init == 'kmeans':
            km = KMeans(n_clusters=K, n_init=10, random_state=42)
            labels = km.fit_predict(self.gauss_df.values)

            # convert hard labels to soft assignments with small regularization
            gamma = np.full((N, K), 0.05 / (K - 1))
            for i, lab in enumerate(labels):
                gamma[i, :] = 0.05 / (K - 1)
                gamma[i, lab] = 0.95

        elif init == 'random':
            gamma = np.random.dirichlet(np.ones(K), size=N)

        else:
            raise ValueError(f"Unknown init strategy '{init}'. "
                             "Use 'kmeans' or 'random'.")

        return gamma / gamma.sum(axis=1, keepdims=True)

    def _emission_log_prob(self,
                           asset_covs: List[pd.DataFrame],
                           horizon_covs: List[pd.DataFrame]
                           ) -> np.ndarray:
        """
        Compute log emission probabilities log p(x_d | Z_d = k) for all
        days d and regimes k.

        Uses the Kronecker structure:
            log p(x_d | k) = -n/2 log(2π) + 1/2 log det(Θ^(k))
                             - 1/2 x_d^T Θ^(k) x_d
        where Θ^(k) = A^(k) ⊗ B^(k) (precision = inv of Kronecker cov).

        Returns
        -------
        log_emit : np.ndarray, shape (N_days, K)
        """
        N = len(self.gauss_df)
        K = self.n_regimes
        log_emit = np.zeros((N, K))

        for k in range(K):
            A_cov = asset_covs[k].values           # (m, m)
            B_cov = horizon_covs[k].values          # (f, f)
            m = A_cov.shape[0]
            f = B_cov.shape[0]

            try:
                A_prec = np.linalg.inv(A_cov)
                B_prec = np.linalg.inv(B_cov)

                # log det of Kronecker product: f*log det(A) + m*log det(B)
                sign_A, logdet_A = np.linalg.slogdet(A_prec)
                sign_B, logdet_B = np.linalg.slogdet(B_prec)

                if sign_A <= 0 or sign_B <= 0:
                    log_emit[:, k] = -1e10
                    continue

                log_det_prec = f * logdet_A + m * logdet_B

                for d, (_, row) in enumerate(self.gauss_df.iterrows()):
                    x = row.values   # shape (m*f,)
                    X = np.reshape(x, (f, m), order='F')
                    # quadratic form using Kronecker structure:
                    # x^T (A⊗B) x = tr(B^T X A X^T) when Θ = A_prec⊗B_prec
                    quad = np.trace(B_prec.T @ X @ A_prec @ X.T)
                    log_emit[d, k] = (0.5 * log_det_prec
                                      - 0.5 * quad
                                      - 0.5 * m * f * np.log(2 * np.pi))

            except np.linalg.LinAlgError:
                log_emit[:, k] = -1e10

        return log_emit

    def _estep(self,
               asset_covs: List[pd.DataFrame],
               horizon_covs: List[pd.DataFrame],
               trans_matrix: np.ndarray,
               init_probs: np.ndarray
               ) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        HMM E-step: forward-backward algorithm.

        Returns
        -------
        gamma : np.ndarray, shape (N, K)
            Posterior marginal regime probabilities.
        xi : np.ndarray, shape (N-1, K, K)
            Posterior pairwise transition probabilities.
        log_lik : float
            Log-likelihood of the observed sequence.
        """
        N = len(self.gauss_df)
        K = self.n_regimes

        log_emit = self._emission_log_prob(asset_covs, horizon_covs)

        # ---- Forward pass ----
        log_alpha = np.zeros((N, K))
        log_alpha[0] = np.log(init_probs + 1e-300) + log_emit[0]

        for t in range(1, N):
            for k in range(K):
                log_alpha[t, k] = (
                    np.logaddexp.reduce(
                        log_alpha[t - 1] + np.log(trans_matrix[:, k] + 1e-300)
                    ) + log_emit[t, k]
                )

        log_lik = np.logaddexp.reduce(log_alpha[-1])

        # ---- Backward pass ----
        log_beta = np.zeros((N, K))  # log_beta[-1] = 0 (i.e. beta=1)

        for t in range(N - 2, -1, -1):
            for j in range(K):
                log_beta[t, j] = np.logaddexp.reduce(
                    np.log(trans_matrix[j, :] + 1e-300)
                    + log_emit[t + 1]
                    + log_beta[t + 1]
                )

        # ---- Posterior marginals gamma ----
        log_gamma = log_alpha + log_beta
        log_gamma -= np.logaddexp.reduce(log_gamma, axis=1, keepdims=True)
        gamma = np.exp(log_gamma)

        # ---- Posterior pairwise xi ----
        xi = np.zeros((N - 1, K, K))
        for t in range(N - 1):
            for j in range(K):
                for k in range(K):
                    xi[t, j, k] = (
                        log_alpha[t, j]
                        + np.log(trans_matrix[j, k] + 1e-300)
                        + log_emit[t + 1, k]
                        + log_beta[t + 1, k]
                    )
            # normalize
            xi[t] = np.exp(xi[t] - np.logaddexp.reduce(
                xi[t].ravel()))

        return gamma, xi, log_lik

    def _mstep_transition(self,
                          xi: np.ndarray,
                          gamma: np.ndarray) -> np.ndarray:
        """
        M-step update for the HMM transition matrix.

            A_jk = sum_t xi_t(j,k) / sum_t gamma_t(j)
        """
        K = self.n_regimes
        trans = np.zeros((K, K))

        for j in range(K):
            denom = gamma[:-1, j].sum()
            for k in range(K):
                trans[j, k] = xi[:, j, k].sum() / (denom + 1e-300)

        # normalize rows
        row_sums = trans.sum(axis=1, keepdims=True)
        trans = trans / np.where(row_sums > 0, row_sums, 1)

        return trans

    def _mstep_gemini(self,
                      gamma: np.ndarray,
                      asset_rho: float, horizon_rho: float,
                      shrinkage_rho: float
                      ) -> Tuple[List[pd.DataFrame], List[pd.DataFrame]]:
        """
        M-step update for regime-specific GEMINI covariance matrices.

        For each regime k, calls _weighted_gemini with weights = gamma[:, k],
        producing a soft-assignment weighted GEMINI estimate. Then applies
        hierarchical shrinkage toward the common mean precision matrix.

        Parameters
        ----------
        gamma : np.ndarray, shape (N, K)
        asset_rho, horizon_rho : float
        shrinkage_rho : float
            Shrinkage strength ρ. The regime-specific precision is blended
            with the common mean precision:
                Θ^(k)_shrunk = (1 - s) * Θ^(k) + s * Θ_bar
            where s = ρ / (1 + ρ).

        Returns
        -------
        asset_covs, horizon_covs : List[pd.DataFrame], each of length K
        """
        K = self.n_regimes
        m = self.num_of_assets
        f = self.num_of_horizons
        horizon_indx = ['_'.join(['lag', str(hz)]) for hz in range(f)]

        asset_precs = []
        horizon_precs = []

        for k in range(K):
            weights = gamma[:, k]
            eff_n = weights.sum()

            if eff_n < 2:
                # insufficient weight: fall back to identity
                asset_precs.append(np.eye(m))
                horizon_precs.append(np.eye(f))
                continue

            try:
                if m == 1:
                    hp = _weighted_graphical_lasso(
                        self.gauss_df, weights, f, horizon_rho)
                    ap = np.array([[1.0]])
                elif f == 1:
                    ap = _weighted_graphical_lasso(
                        self.gauss_df, weights, m, asset_rho)
                    hp = np.array([[1.0]])
                else:
                    ap, hp = _weighted_gemini(
                        self.gauss_df, weights, m, f, asset_rho, horizon_rho)

                asset_precs.append(ap)
                horizon_precs.append(hp)

            except Exception:
                asset_precs.append(np.eye(m))
                horizon_precs.append(np.eye(f))

        # ---- Hierarchical shrinkage ----
        if shrinkage_rho > 0 and K > 1:
            # mean precision across regimes (weighted by average gamma)
            regime_weights = gamma.mean(axis=0)  # shape (K,)
            mean_asset_prec = sum(
                regime_weights[k] * asset_precs[k] for k in range(K))
            mean_horizon_prec = sum(
                regime_weights[k] * horizon_precs[k] for k in range(K))

            s = shrinkage_rho / (1.0 + shrinkage_rho)

            asset_precs = [
                (1 - s) * asset_precs[k] + s * mean_asset_prec
                for k in range(K)
            ]
            horizon_precs = [
                (1 - s) * horizon_precs[k] + s * mean_horizon_prec
                for k in range(K)
            ]

        # convert to covariance matrices
        asset_covs = []
        horizon_covs = []

        for k in range(K):
            ac = np.linalg.inv(asset_precs[k])
            ac = (ac + ac.T) / 2
            asset_covs.append(pd.DataFrame(
                data=ac, index=self.asset_list, columns=self.asset_list))

            hc = np.linalg.inv(horizon_precs[k])
            hc = (hc + hc.T) / 2
            horizon_covs.append(pd.DataFrame(
                data=hc, index=horizon_indx, columns=horizon_indx))

        return asset_covs, horizon_covs

    # ------------------------------------------------------------------
    # Regime-aware scenario generation
    # ------------------------------------------------------------------

    def generate_regime_scenarios(self,
                                  nscen: int,
                                  regime_weights: Optional[np.ndarray] = None,
                                  lower_dict=None,
                                  upper_dict=None,
                                  sampling: str = 'mixture') -> None:
        """
        Generate scenarios using the regime-switching model.

        Two sampling strategies are available:

        'mixture' (recommended)
            For each of the nscen scenarios, draw a regime k with probability
            regime_weights[k], then sample from N(0, Σ^(k)). This produces a
            Gaussian mixture distribution and naturally captures heavier tails
            and multi-modal dependency structures.

        'hard'
            Assign all scenarios to the most probable regime k* = argmax
            regime_weights, then sample purely from N(0, Σ^(k*)). Simpler but
            discards regime uncertainty.

        Parameters
        ----------
        nscen : int
        regime_weights : np.ndarray, shape (K,), optional
            Predictive regime probabilities for the target day.
            If None, uses uniform weights.
        lower_dict, upper_dict : optional
            Clipping bounds for asset values (passed to parent logic).
        sampling : str
            'mixture' or 'hard'.
        """
        K = self.n_regimes

        if regime_weights is None:
            regime_weights = np.ones(K) / K

        if len(self.regime_asset_covs) == 0:
            raise GeminiError(
                "Regime models have not been fitted yet. "
                "Call fit_regimes() first."
            )

        if self.asset_cov is None:
            raise GeminiError(
                "Cannot generate scenarios with an unfitted model."
            )

        # ---- Allocate scenarios to regimes ----
        if sampling == 'mixture':
            regime_assignments = np.random.choice(
                K, size=nscen, p=regime_weights / regime_weights.sum()
            )
        elif sampling == 'hard':
            k_star = int(np.argmax(regime_weights))
            regime_assignments = np.full(nscen, k_star, dtype=int)
        else:
            raise ValueError(f"Unknown sampling strategy '{sampling}'.")

        n_dim = self.num_of_assets * self.num_of_horizons
        arr = np.zeros((n_dim, nscen))

        # ---- Draw samples regime by regime ----
        for k in range(K):
            mask = regime_assignments == k
            n_k = mask.sum()
            if n_k == 0:
                continue

            sqrt_cov_k = np.kron(
                sqrtm(self.regime_asset_covs[k].values).real,
                sqrtm(self.regime_horizon_covs[k].values).real
            )
            arr[:, mask] = sqrt_cov_k @ np.random.randn(n_dim, n_k)

        # ---- Reuse parent post-processing logic ----
        # Temporarily override asset_cov/horizon_cov so the parent's
        # generate_gauss_scenarios would give the same post-processing;
        # instead we directly build scen_gauss_df and apply the inversion.

        scen_df = pd.DataFrame(
            data=arr.T,
            columns=pd.MultiIndex.from_tuples(
                [(asset, horizon)
                 for asset in self.asset_list
                 for horizon in range(self.num_of_horizons)]
            )
        )

        self.scen_gauss_df = scen_df.copy()

        # add back mean and standard deviation
        if not self.gauss:
            scen_df = scen_df * self.gauss_std + self.gauss_mean

        scen_df.columns = pd.MultiIndex.from_tuples(
            scen_df.columns).set_levels(self.scen_timesteps, level=1)

        # invert the Gaussian scenario deviations by the marginal distributions
        if not self.gauss:
            scen_means, scen_vars = scen_df.mean(), scen_df.std()
            u_mat = norm.cdf(
                ((scen_df - scen_means) / scen_vars).fillna(0.0))

            if self.marginal_ecdfs:
                scen_df = pd.DataFrame({
                    col: qdist(self.marginal_ecdfs[col], u_mat[:, i])
                    for i, col in enumerate(scen_df.columns)
                })
            else:
                scen_df = pd.DataFrame({
                    col: qdist(self.gpd_dict[col], u_mat[:, i])
                    for i, col in enumerate(scen_df.columns)
                })

        self.scen_deviation_df = scen_df.copy()

        if self.forecasts is not None:
            scen_df = self.scen_deviation_df + self.forecasts

            if lower_dict is None:
                lower_dict = {site: 0. for site in self.asset_list}

            if upper_dict is None:
                upper_dict = {site: None for site in self.asset_list}

            for site in self.asset_list:
                scen_df[site] = scen_df[site].clip(
                    lower=lower_dict[site], upper=upper_dict[site])

            self.scen_df = scen_df
        else:
            self.scen_df = None

    def predict_regime(self,
                       horizon: int = 1) -> np.ndarray:
        """
        Predict regime probabilities for a day `horizon` steps ahead of the
        last observed day, using the HMM transition matrix.

        This is the non-anticipative forward pass: we use only the posterior
        at the last historical day and propagate forward via the transition
        matrix.

        Parameters
        ----------
        horizon : int
            How many steps ahead to predict. Default 1 (next day).

        Returns
        -------
        pred_probs : np.ndarray, shape (K,)
            Predictive regime probabilities P(Z_{T+horizon} | x_{1:T}).
        """
        if self.gamma is None or self.trans_matrix is None:
            raise GeminiError("Model has not been fitted yet.")

        # start from the last day's posterior
        pred = self.gamma[-1].copy()

        # propagate through transition matrix
        for _ in range(horizon):
            pred = self.trans_matrix.T @ pred

        return pred / pred.sum()


# ---------------------------------------------------------------------------
# RegimeGeminiEngine
# ---------------------------------------------------------------------------

class RegimeGeminiEngine(GeminiEngine):
    """
    A scenario generation engine using regime-switching GEMINI models.

    Inherits all data management from GeminiEngine. The fit() method now
    runs the EM algorithm to identify regimes, and create_scenario() uses
    mixture sampling over regimes instead of a single Gaussian draw.

    Parameters
    ----------
    n_regimes : int
        Number of latent regimes K (default 3).
    shrinkage_rho : float
        Hierarchical shrinkage strength (default 0.1).
    sampling : str
        'mixture' or 'hard' regime sampling at generation time.
    """

    def __init__(self,
                 hist_actual_df: pd.DataFrame,
                 hist_forecast_df: pd.DataFrame,
                 scen_start_time: pd.Timestamp,
                 meta_df: Optional[pd.DataFrame] = None,
                 asset_type: Optional[str] = None,
                 forecast_resolution_in_minute: int = 60,
                 num_of_horizons: int = 24,
                 forecast_lead_time_in_hour: int = 12,
                 n_regimes: int = 3,
                 shrinkage_rho: float = 0.1,
                 sampling: str = 'mixture') -> None:

        super().__init__(
            hist_actual_df, hist_forecast_df, scen_start_time,
            meta_df, asset_type,
            forecast_resolution_in_minute, num_of_horizons,
            forecast_lead_time_in_hour
        )

        self.n_regimes = n_regimes
        self.shrinkage_rho = shrinkage_rho
        self.sampling = sampling

    def fit(self,
            asset_rho: float, horizon_rho: float,
            nearest_days: Optional[int] = None,
            shrinkage_rho: Optional[float] = None,
            max_iter: int = 50,
            tol: float = 1e-4,
            init: str = 'kmeans') -> None:
        """
        Fit regime-switching GEMINI model to historical data.

        Parameters
        ----------
        asset_rho, horizon_rho : float
            LASSO penalties for spatial and temporal precision matrices.
        nearest_days : int, optional
            Use only historical dates within this window (solar seasonality).
        shrinkage_rho : float, optional
            Override the engine-level shrinkage_rho.
        max_iter, tol : EM convergence settings.
        init : str
            Regime initialization: 'kmeans' or 'random'.
        """
        if shrinkage_rho is None:
            shrinkage_rho = self.shrinkage_rho

        if nearest_days:
            dev_index = self.get_yearly_date_range(
                use_date=self.scen_start_time, num_of_days=nearest_days)
        else:
            dev_index = None

        use_gpd = (self.asset_type == 'load')

        self.model = RegimeGeminiModel(
            self.scen_start_time,
            self.get_hist_df_dict(),
            None, dev_index,
            self.forecast_resolution_in_minute,
            self.num_of_horizons,
            self.forecast_lead_hours,
            use_gpd=use_gpd,
            n_regimes=self.n_regimes
        )

        self.model.fit_regimes(
            asset_rho, horizon_rho,
            shrinkage_rho=shrinkage_rho,
            max_iter=max_iter,
            tol=tol,
            init=init
        )

    def create_scenario(self,
                        nscen: int,
                        forecast_df: pd.DataFrame,
                        sampling: Optional[str] = None,
                        **gpd_args) -> None:
        """
        Generate scenarios using the fitted regime-switching model.

        The predictive regime distribution is computed by the non-anticipative
        HMM forward pass (predict_regime), which uses only data up to the last
        historical day. Scenarios are then drawn by mixture or hard sampling
        over the K regime-specific Gaussian distributions.

        Parameters
        ----------
        nscen : int
        forecast_df : pd.DataFrame
        sampling : str, optional
            Override engine-level sampling strategy ('mixture' or 'hard').
        gpd_args : passed to fit_conditional_marginal_dist for wind.
        """
        if self.model is None:
            raise GeminiError(
                "Cannot generate scenarios until a model has been fitted!"
            )

        if sampling is None:
            sampling = self.sampling

        self.model.get_forecast(forecast_df)

        # conditional marginals for wind (same as base engine)
        if self.asset_type == 'wind':
            self.model.fit_conditional_marginal_dist(**gpd_args)

        # predict regime probabilities for the scenario day
        regime_weights = self.model.predict_regime(horizon=1)

        # set capacity upper bounds
        if self.meta_df is None:
            upper_dict = None
        else:
            upper_dict = self.meta_df.Capacity

        self.model.generate_regime_scenarios(
            nscen,
            regime_weights=regime_weights,
            upper_dict=upper_dict,
            sampling=sampling
        )

        self.scenarios[self.asset_type] = self.model.scen_df
        self.forecasts[self.asset_type] = self.get_forecast(forecast_df)


# ---------------------------------------------------------------------------
# RegimePCAGeminiEngine  (solar)
# ---------------------------------------------------------------------------

class RegimePCAGeminiModel(PCAGeminiModel):
    """
    PCA-based solar GEMINI model with regime switching.

    After PCA transformation, the EM algorithm identifies K regimes in the
    PCA component space. Each regime gets its own (asset_cov^(k), horizon_cov^(k))
    where horizon_cov now operates on the PCA components rather than raw hours.
    """

    def __init__(self,
                 scen_start_time: pd.Timestamp,
                 hist_dfs: Optional[Dict[str, pd.DataFrame]] = None,
                 gauss_df: Optional[pd.DataFrame] = None,
                 dev_index: Optional[Iterable[pd.Timestamp]] = None,
                 forecast_resolution_in_minute: int = 60,
                 num_of_horizons: int = 24,
                 forecast_lead_time_in_hour: int = 12,
                 n_regimes: int = 3) -> None:

        super().__init__(
            scen_start_time, hist_dfs, gauss_df, dev_index,
            forecast_resolution_in_minute, num_of_horizons,
            forecast_lead_time_in_hour
        )

        self.n_regimes = n_regimes
        self.regime_asset_covs: List[pd.DataFrame] = []
        self.regime_horizon_covs: List[pd.DataFrame] = []
        self.trans_matrix: Optional[np.ndarray] = None
        self.init_probs: Optional[np.ndarray] = None
        self.gamma: Optional[np.ndarray] = None

    def fit_regimes(self,
                    asset_rho: float, pca_comp_rho: float,
                    shrinkage_rho: float = 0.1,
                    max_iter: int = 50,
                    tol: float = 1e-4,
                    init: str = 'kmeans') -> None:
        """
        Fit regime-specific GEMINI models in PCA component space.

        Must be called after pca_transform().
        """
        if self.pca_gauss_df is None:
            raise GeminiError(
                "pca_transform() must be called before fit_regimes()."
            )

        N = len(self.pca_gauss_df)
        K = self.n_regimes
        m = self.num_of_assets
        f = self.num_of_components

        if N < K:
            raise GeminiError(
                f"Not enough historical data ({N} days) for {K} regimes."
            )

        # Borrow the EM logic from RegimeGeminiModel by creating a temporary
        # helper instance that operates on pca_gauss_df instead of gauss_df
        helper = _EMHelper(
            gauss_df=self.pca_gauss_df,
            asset_list=self.asset_list,
            n_regimes=K,
            num_of_assets=m,
            num_of_horizons=f   # horizons = PCA components here
        )

        gamma, trans_matrix, init_probs, asset_covs, horizon_covs = \
            helper.run_em(asset_rho, pca_comp_rho,
                          shrinkage_rho, max_iter, tol, init)

        self.gamma = gamma
        self.trans_matrix = trans_matrix
        self.init_probs = init_probs
        self.regime_asset_covs = asset_covs
        self.regime_horizon_covs = horizon_covs

        # set average cov on parent for fallback
        regime_weights = gamma.mean(axis=0)
        avg_asset_cov = sum(
            regime_weights[k] * asset_covs[k].values for k in range(K))
        avg_horizon_cov = sum(
            regime_weights[k] * horizon_covs[k].values for k in range(K))

        self.asset_cov = pd.DataFrame(
            data=avg_asset_cov,
            index=self.asset_list, columns=self.asset_list
        )
        pca_indx = ['_'.join(['lag', str(c)]) for c in range(f)]
        self.horizon_cov = pd.DataFrame(
            data=avg_horizon_cov, index=pca_indx, columns=pca_indx
        )

    def predict_regime(self, horizon: int = 1) -> np.ndarray:
        """Forward HMM prediction (same logic as RegimeGeminiModel)."""
        if self.gamma is None or self.trans_matrix is None:
            raise GeminiError("Model has not been fitted yet.")
        pred = self.gamma[-1].copy()
        for _ in range(horizon):
            pred = self.trans_matrix.T @ pred
        return pred / pred.sum()

    def generate_regime_pca_scenarios(self,
                                      trans_timesteps: dict,
                                      hist_sun_info: dict,
                                      nscen: int,
                                      regime_weights: Optional[np.ndarray] = None,
                                      sqrtcov: Optional[np.ndarray] = None,
                                      mu: Optional[np.ndarray] = None,
                                      lower_dict=None,
                                      upper_dict=None,
                                      sampling: str = 'mixture') -> None:
        """
        Generate solar PCA scenarios with regime-switching.

        Combines regime sampling in PCA space with the inverse PCA transform
        and solar conditional marginal fitting from PCAGeminiModel.
        """
        K = self.n_regimes
        if regime_weights is None:
            regime_weights = np.ones(K) / K

        n_dim = self.num_of_assets * self.num_of_components

        if sqrtcov is not None:
            # joint model override: use provided sqrt_cov (no regime sampling)
            arr = sqrtcov @ np.random.randn(n_dim, nscen)
            if mu is not None:
                arr += mu
        else:
            # regime mixture sampling in PCA space
            if sampling == 'mixture':
                regime_assignments = np.random.choice(
                    K, size=nscen,
                    p=regime_weights / regime_weights.sum()
                )
            else:
                k_star = int(np.argmax(regime_weights))
                regime_assignments = np.full(nscen, k_star, dtype=int)

            arr = np.zeros((n_dim, nscen))
            for k in range(K):
                mask = regime_assignments == k
                n_k = mask.sum()
                if n_k == 0:
                    continue
                sqrt_cov_k = np.kron(
                    sqrtm(self.regime_asset_covs[k].values).real,
                    sqrtm(self.regime_horizon_covs[k].values).real
                )
                arr[:, mask] = sqrt_cov_k @ np.random.randn(n_dim, n_k)

        # delegate remaining PCA inversion and solar logic to parent
        # by temporarily setting pca_scen_gauss_unbias_df
        pca_scen_gauss_df = pd.DataFrame(
            data=arr.T,
            columns=pd.MultiIndex.from_product(
                [self.asset_list, range(self.num_of_components)])
        )
        self.pca_scen_gauss_unbias_df = pca_scen_gauss_df.copy()
        self.pca_scen_gauss_df = (pca_scen_gauss_df
                                  * self.pca_gauss_std + self.pca_gauss_mean)

        asset_days = self.pca.inverse_transform(self.pca_scen_gauss_df[[
            (asset, c) for c in range(self.num_of_components)
            for asset in self.asset_list
        ]].unstack().unstack(1).values)

        self.scen_gauss_df = pd.DataFrame(
            data=np.concatenate(
                [asset_days[(i * nscen):((i + 1) * nscen), :]
                 for i in range(self.num_of_assets)], axis=1),
            columns=pd.MultiIndex.from_product(
                [self.asset_list, range(self.num_of_horizons)])
        )

        scen_df = self.scen_gauss_df * self.gauss_std + self.gauss_mean
        scen_df.columns = scen_df.columns.set_levels(
            self.scen_timesteps, level=1)

        # fit solar conditional marginal distributions
        self.fit_solar_conditional_marginal_dist(
            trans_timesteps['sunrise'], trans_timesteps['sunset'], hist_sun_info)

        # invert Gaussian via conditional marginals
        if not self.gauss:
            scen_means, scen_vars = scen_df.mean(), scen_df.std()
            scen_means[scen_vars < 1e-2] = 999999.
            scen_vars[scen_vars < 1e-2] = 1.
            u_mat = norm.cdf((scen_df - scen_means) / scen_vars)

            scen_df = pd.DataFrame({
                col: self.marginal_ecdfs[col].quantfun(u_mat[:, i])
                for i, col in enumerate(scen_df.columns)
            })

        self.scen_deviation_df = scen_df.copy()

        if self.forecasts is not None:
            scen_df = self.scen_deviation_df + self.forecasts

            if lower_dict is None:
                lower_dict = {site: 0. for site in self.asset_list}
            if upper_dict is None:
                upper_dict = {site: None for site in self.asset_list}

            for site in self.asset_list:
                scen_df[site] = scen_df[site].clip(
                    lower=lower_dict[site], upper=upper_dict[site])

            self.scen_df = scen_df
        else:
            self.scen_df = None


class RegimePCAGeminiEngine(PCAGeminiEngine):
    """
    Solar scenario engine with regime-switching PCA GEMINI model.

    Inherits all solar sunrise/sunset logic from PCAGeminiEngine.
    Replaces fit() and create_scenario() with regime-aware versions.
    """

    def __init__(self,
                 solar_hist_actual_df: pd.DataFrame,
                 solar_hist_forecast_df: pd.DataFrame,
                 scen_start_time: pd.Timestamp,
                 solar_meta_df: pd.DataFrame,
                 forecast_resolution_in_minute: int = 60,
                 num_of_horizons: int = 24,
                 forecast_lead_time_in_hour: int = 12,
                 us_state: str = 'Texas',
                 n_regimes: int = 3,
                 shrinkage_rho: float = 0.1,
                 sampling: str = 'mixture') -> None:

        super().__init__(
            solar_hist_actual_df, solar_hist_forecast_df,
            scen_start_time, solar_meta_df,
            forecast_resolution_in_minute, num_of_horizons,
            forecast_lead_time_in_hour, us_state
        )

        self.n_regimes = n_regimes
        self.shrinkage_rho = shrinkage_rho
        self.sampling = sampling

    def fit(self,
            asset_rho: float, pca_comp_rho: float,
            num_of_components: Union[int, float, str] = 0.9,
            nearest_days: int = 50,
            shrinkage_rho: Optional[float] = None,
            max_iter: int = 50,
            tol: float = 1e-4,
            init: str = 'kmeans') -> None:
        """Fit regime-switching PCA GEMINI model for solar scenarios."""

        if shrinkage_rho is None:
            shrinkage_rho = self.shrinkage_rho

        if nearest_days:
            dev_index = self.get_yearly_date_range(
                use_date=self.scen_start_time, num_of_days=nearest_days)
        else:
            dev_index = None

        self.model = RegimePCAGeminiModel(
            self.scen_start_time,
            self.get_hist_df_dict(),
            None, dev_index,
            self.forecast_resolution_in_minute,
            self.num_of_horizons,
            self.forecast_lead_hours,
            n_regimes=self.n_regimes
        )

        self.model.pca_transform(num_of_components)
        self.model.fit_regimes(
            asset_rho, pca_comp_rho,
            shrinkage_rho=shrinkage_rho,
            max_iter=max_iter,
            tol=tol,
            init=init
        )

    def create_scenario(self,
                        nscen: int,
                        forecast_df: pd.DataFrame,
                        sampling: Optional[str] = None) -> None:
        """Generate solar scenarios using regime-switching PCA model."""

        if sampling is None:
            sampling = self.sampling

        self.model.get_forecast(forecast_df)

        regime_weights = self.model.predict_regime(horizon=1)

        self.model.generate_regime_pca_scenarios(
            self.trans_horizons, self.hist_sun_info,
            nscen,
            regime_weights=regime_weights,
            upper_dict=self.meta_df.Capacity,
            sampling=sampling
        )

        self.scenarios[self.asset_type] = self.model.scen_df
        self.forecasts[self.asset_type] = self.get_forecast(forecast_df)


# ---------------------------------------------------------------------------
# Internal EM helper (shared between RegimeGeminiModel and RegimePCAGeminiModel)
# ---------------------------------------------------------------------------

class _EMHelper:
    """
    Internal helper encapsulating the EM algorithm so it can be reused
    by both RegimeGeminiModel and RegimePCAGeminiModel without duplication.
    """

    def __init__(self,
                 gauss_df: pd.DataFrame,
                 asset_list: List[str],
                 n_regimes: int,
                 num_of_assets: int,
                 num_of_horizons: int) -> None:
        self.gauss_df = gauss_df
        self.asset_list = asset_list
        self.n_regimes = n_regimes
        self.num_of_assets = num_of_assets
        self.num_of_horizons = num_of_horizons

    def run_em(self,
               asset_rho: float, horizon_rho: float,
               shrinkage_rho: float = 0.1,
               max_iter: int = 50,
               tol: float = 1e-4,
               init: str = 'kmeans'):
        """Run EM and return (gamma, trans_matrix, init_probs,
                               asset_covs, horizon_covs)."""

        # Delegate to a temporary RegimeGeminiModel-like object
        tmp = RegimeGeminiModel.__new__(RegimeGeminiModel)
        tmp.gauss_df = self.gauss_df
        tmp.asset_list = self.asset_list
        tmp.n_regimes = self.n_regimes
        tmp.num_of_assets = self.num_of_assets
        tmp.num_of_horizons = self.num_of_horizons
        tmp.gauss = False
        tmp.gamma = None
        tmp.trans_matrix = None
        tmp.init_probs = None
        tmp.regime_asset_covs = []
        tmp.regime_horizon_covs = []

        tmp.fit_regimes(asset_rho, horizon_rho,
                        shrinkage_rho=shrinkage_rho,
                        max_iter=max_iter, tol=tol, init=init)

        return (tmp.gamma, tmp.trans_matrix, tmp.init_probs,
                tmp.regime_asset_covs, tmp.regime_horizon_covs)
