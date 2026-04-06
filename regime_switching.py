"""
Regime-switching extension of GeminiEngine.

Replaces the single static GEMINI covariance structure with K regime-specific
covariance matrices (one Σ_spatial ⊗ Σ_temporal per regime). Regimes are
identified by fitting a Gaussian Mixture Model (GMM) on a PCA-reduced
representation of the gaussianized historical deviations — i.e., directly in
the same space on which GEMINI operates.

Usage
-----
    engine = RegimeSwitchingGeminiEngine(
        hist_actual_df, hist_forecast_df, scen_start_time, asset_type='load'
    )

    # 1. Fit regimes (BIC selects the number of regimes automatically)
    engine.fit_regimes(
        max_regimes=5,          # upper bound for BIC search
        pca_components=5,       # PCA dims used for GMM embedding
        nearest_days=50,        # same seasonal window as standard PGscen
    )

    # 2. Print a summary of what was learned
    engine.regime_summary()

    # 3. Generate scenarios exactly like the standard engine
    engine.create_scenario(nscen=1000, forecast_df=forecast_df)

    # The active regime for the target day is exposed as:
    engine.active_regime   # int
"""

from __future__ import annotations

import warnings
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from scipy.linalg import sqrtm
from scipy.stats import norm

from pgscen.engine import GeminiEngine
from pgscen.model import GeminiModel, GeminiError
from pgscen.utils.r_utils import gaussianize, gemini, graphical_lasso, standardize


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_gauss_df(engine: GeminiEngine,
                    dev_index: Optional[Iterable[pd.Timestamp]],
                    use_gpd: bool) -> pd.DataFrame:
    """
    Build the gaussianized deviation matrix the same way GeminiModel does,
    but return it as a plain DataFrame so we can work with it before
    fitting GEMINI.

    Returns
    -------
    gauss_df : DataFrame  shape (n_days, n_assets * n_horizons)
        Each row is one historical day; each column is (asset, horizon).
    """
    tmp = GeminiModel(
        engine.scen_start_time,
        engine.get_hist_df_dict(),
        None,
        dev_index,
        engine.forecast_resolution_in_minute,
        engine.num_of_horizons,
        engine.forecast_lead_hours,
        use_gpd=use_gpd,
    )
    # GeminiModel.__init__ already computes gauss_df
    return tmp.gauss_df.copy(), tmp


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class RegimeSwitchingGeminiEngine(GeminiEngine):
    """
    GeminiEngine whose covariance structure is regime-dependent.

    For a given target day the engine:
      1. Identifies the regime k via a pre-fitted GMM.
      2. Selects the GEMINI model trained on the historical days assigned
         to regime k.
      3. Generates scenarios exactly as the standard engine would.

    Attributes added on top of GeminiEngine
    ----------------------------------------
    n_regimes : int
        Number of regimes actually used (chosen by BIC or set explicitly).
    regime_labels : pd.Series
        Regime assignment for every historical day (index = issue dates).
    regime_models : Dict[int, GeminiModel]
        One fitted GeminiModel per regime.
    gmm : GaussianMixture
        The fitted GMM used for regime detection.
    pca_embed : PCA
        The PCA fitted on the full gaussianized history, used to project
        any new day into the embedding space for detection.
    active_regime : Optional[int]
        The regime assigned to the target day after `create_scenario` is
        called.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.n_regimes: Optional[int] = None
        self.regime_labels: Optional[pd.Series] = None
        self.regime_models: Dict[int, GeminiModel] = {}
        self.gmm: Optional[GaussianMixture] = None
        self.pca_embed: Optional[PCA] = None
        self._base_model: Optional[GeminiModel] = None  # holds gaussianization
        self.active_regime: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit_regimes(
        self,
        max_regimes: int = 5,
        pca_components: int = 5,
        asset_rho: float = 0.05,
        horizon_rho: float = 0.05,
        nearest_days: Optional[int] = None,
        random_state: int = 0,
    ) -> None:
        """
        Fit the regime-switching model.

        Steps
        -----
        1. Gaussianize all historical deviations (same pipeline as GEMINI).
        2. PCA-reduce to `pca_components` dimensions.
        3. Fit GMMs for k = 1 … max_regimes; pick k* by BIC.
        4. Assign a regime to every historical day.
        5. For each regime k, fit a GeminiModel on days labelled k.

        Parameters
        ----------
        max_regimes : int
            Upper bound for the BIC search (inclusive).
        pca_components : int
            Number of PCA components used to embed days before GMM clustering.
            Should be much smaller than n_assets * n_horizons.
        asset_rho, horizon_rho : float
            GEMINI regularisation hyper-parameters, passed to each per-regime
            GeminiModel.fit().
        nearest_days : int, optional
            Seasonal window (same meaning as in GeminiEngine.fit()).
        random_state : int
            Seed for GMM initialisation (reproducibility).
        """
        use_gpd = self.asset_type == 'load'

        # --- seasonal window (mirrors GeminiEngine.fit logic) ---
        dev_index = None
        if nearest_days is not None:
            dev_index = self.get_yearly_date_range(
                use_date=self.scen_start_time,
                num_of_days=nearest_days,
            )

        # --- step 1: build full gaussianized matrix ---
        print("[RegimeSwitching] Gaussianizing historical deviations...")
        gauss_df, base_model = _build_gauss_df(self, dev_index, use_gpd)
        self._base_model = base_model

        # gauss_df rows = historical days, cols = (asset, horizon) MultiIndex
        X = gauss_df.values  # shape (n_days, n_features)
        n_days, n_features = X.shape
        print(f"  → {n_days} historical days × {n_features} features")

        # --- step 2: PCA embedding ---
        n_comp = min(pca_components, n_days - 1, n_features)
        self.pca_embed = PCA(n_components=n_comp, random_state=random_state)
        X_pca = self.pca_embed.fit_transform(X)
        explained = self.pca_embed.explained_variance_ratio_.sum()
        print(f"  → PCA: {n_comp} components explain "
              f"{explained:.1%} of variance")

        # --- step 3: BIC-based GMM selection ---
        print(f"[RegimeSwitching] Selecting number of regimes "
              f"(BIC, k=1..{max_regimes})...")
        bic_scores: List[float] = []
        gmms: List[GaussianMixture] = []

        for k in range(1, max_regimes + 1):
            gm = GaussianMixture(
                n_components=k,
                covariance_type='full',
                n_init=5,
                random_state=random_state,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gm.fit(X_pca)
            bic_scores.append(gm.bic(X_pca))
            gmms.append(gm)
            print(f"  k={k}  BIC={gm.bic(X_pca):.1f}")

        best_k = int(np.argmin(bic_scores)) + 1
        self.n_regimes = best_k
        self.gmm = gmms[best_k - 1]
        print(f"  → Best k = {best_k} (lowest BIC = {bic_scores[best_k-1]:.1f})")

        # --- step 4: assign labels to historical days ---
        labels = self.gmm.predict(X_pca)
        self.regime_labels = pd.Series(labels, index=gauss_df.index,
                                       name='regime')

        # --- step 5: fit one GeminiModel per regime ---
        print("[RegimeSwitching] Fitting per-regime GEMINI models...")
        for k in range(best_k):
            days_k = self.regime_labels[self.regime_labels == k].index
            n_k = len(days_k)
            print(f"  Regime {k}: {n_k} days", end='')

            if n_k < 2:
                print("  ← too few days, skipping (will fall back to k=0)")
                continue

            # sub-select gaussianized rows for this regime
            gauss_k = gauss_df[gauss_df.index.isin(days_k)]

            # instantiate model with pre-computed gauss_df
            model_k = GeminiModel(
                self.scen_start_time,
                hist_dfs=None,
                gauss_df=gauss_k,
                dev_index=None,
                forecast_resolution_in_minute=self.forecast_resolution_in_minute,
                num_of_horizons=self.num_of_horizons,
                forecast_lead_time_in_hour=self.forecast_lead_hours,
            )
            model_k.fit(asset_rho, horizon_rho)
            self.regime_models[k] = model_k
            print(f"  ✓")

        # keep asset_rho / horizon_rho for create_scenario
        self._asset_rho = asset_rho
        self._horizon_rho = horizon_rho

        print("[RegimeSwitching] fit_regimes() complete.\n")

    # ------------------------------------------------------------------

    def detect_regime(self, date: Optional[pd.Timestamp] = None) -> int:
        """
        Predict the regime for a given date (defaults to scen_start_time).

        The method embeds the gaussianized deviations of *historical* days
        that share the same issue date into the PCA space and asks the GMM.
        If the date is not in the training history (out-of-sample), it falls
        back to the nearest training day.

        Returns
        -------
        regime : int
        """
        if self.gmm is None:
            raise GeminiError("Call fit_regimes() before detect_regime().")

        if date is None:
            date = self.scen_start_time

        target = pd.Timestamp(date).normalize()

        if target in self.regime_labels.index:
            return int(self.regime_labels.loc[target])

        # out-of-sample: find nearest labelled day
        diffs = (self.regime_labels.index - target).days
        nearest = self.regime_labels.index[np.argmin(np.abs(diffs))]
        regime = int(self.regime_labels.loc[nearest])
        warnings.warn(
            f"Date {target.date()} not in training history; "
            f"using nearest day {nearest.date()} (regime {regime}).",
            UserWarning,
        )
        return regime

    # ------------------------------------------------------------------

    def create_scenario(
        self,
        nscen: int,
        forecast_df: pd.DataFrame,
        **gpd_args,
    ) -> None:
        """
        Generate scenarios using the covariance of the detected regime.

        Mirrors GeminiEngine.create_scenario() but swaps in the per-regime
        asset_cov and horizon_cov before drawing Monte Carlo samples.
        """
        if not self.regime_models:
            raise GeminiError("Call fit_regimes() before create_scenario().")

        # --- detect regime for target day ---
        k = self.detect_regime(self.scen_start_time)
        self.active_regime = k

        # fall back to regime 0 if k is unavailable (< 2 training days)
        if k not in self.regime_models:
            warnings.warn(
                f"Regime {k} has no fitted model; falling back to regime 0.",
                UserWarning,
            )
            k = 0

        print(f"[RegimeSwitching] Using regime {k} "
              f"({(self.regime_labels == k).sum()} training days)")

        # --- borrow the regime model's covariances into _base_model ---
        active_model = self.regime_models[k]

        # We re-use _base_model for GPD / marginal transforms (fitted on all
        # history), but override its covariance matrices with regime-specific
        # ones so that generate_gauss_scenarios() draws from the right Σ.
        self._base_model.asset_cov   = active_model.asset_cov
        self._base_model.horizon_cov = active_model.horizon_cov
        self._base_model.asset_list  = active_model.asset_list

        # provide forecasts to the model
        self._base_model.get_forecast(forecast_df)

        # conditional marginals for wind (same as standard engine)
        if self.asset_type == 'wind':
            self._base_model.fit_conditional_marginal_dist(**gpd_args)

        upper_dict = None if self.meta_df is None else self.meta_df.Capacity

        self._base_model.generate_gauss_scenarios(nscen, upper_dict=upper_dict)

        # expose results through standard engine interface
        self.model = self._base_model
        self.scenarios[self.asset_type] = self._base_model.scen_df
        self.forecasts[self.asset_type] = self.get_forecast(forecast_df)

    # ------------------------------------------------------------------

    def regime_summary(self) -> None:
        """Print a readable summary of the fitted regimes."""
        if self.regime_labels is None:
            print("No regimes fitted yet. Call fit_regimes() first.")
            return

        print(f"\n{'='*50}")
        print(f"  Regime-Switching Summary  ({self.n_regimes} regimes)")
        print(f"{'='*50}")
        for k in range(self.n_regimes):
            days_k = self.regime_labels[self.regime_labels == k]
            n_k = len(days_k)

            # day-of-week distribution
            dow = days_k.index.day_name().value_counts()

            # month distribution
            months = days_k.index.month_name().value_counts().head(3)

            print(f"\n  Regime {k}  —  {n_k} days "
                  f"({100*n_k/len(self.regime_labels):.0f}%)")
            print(f"    Top weekdays : "
                  f"{', '.join(f'{d}({c})' for d,c in dow.head(3).items())}")
            print(f"    Top months   : "
                  f"{', '.join(f'{m}({c})' for m,c in months.items())}")

            if k in self.regime_models:
                mdl = self.regime_models[k]
                sp_diag = np.diag(mdl.asset_cov.values)
                hz_diag = np.diag(mdl.horizon_cov.values)
                print(f"    Asset cov  (diag mean) : {sp_diag.mean():.4f}")
                print(f"    Horizon cov (diag mean): {hz_diag.mean():.4f}")
            else:
                print("    [No model fitted — too few days]")

        print(f"\n{'='*50}\n")
