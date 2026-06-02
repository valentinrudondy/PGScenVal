"""Wind power physics — PLUSWIND-style power conversion for the HRRR pipeline.

Implements the full PLUSWIND recipe end-to-end: per-plant NREL SAM smooth
empirical power curve, IEC density correction from HRRR surface pressure
and 2 m temperature, and the 7 % wake/availability loss with the
above-rated taper.

The entry point is `pluswind_v3_power_all_plants`. It expects a per-plant
SAM curve library (built once at startup via `build_sam_curves`) along
with HRRR-derived wind speeds, surface pressure, and 2 m temperature.

Reference: Millstein et al., Sci. Data 10, 883 (2023),
https://doi.org/10.1038/s41597-023-02804-w
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CUT_IN_MS = 3.0
CUT_OUT_MS = 25.0
RHO_REF = 1.225            # Reference air density (kg/m^3, sea-level)
LOSS_FRAC = 0.07           # Base wake + availability loss
LOSS_TAPER_WIDTH = 2.5     # m/s — taper width near rated WS
R_D = 287.058              # Specific gas constant for dry air (J/(kg·K))


# ---------------------------------------------------------------------------
# Loss model
# ---------------------------------------------------------------------------

def loss_fraction(ws: np.ndarray, rated_ws: np.ndarray) -> np.ndarray:
    """PLUSWIND wake + availability loss with the ramp-up-to-rated taper.

    Below RS - 0.5: full LOSS_FRAC.
    Between RS - 0.5 and RS + 2.0: linearly tapers from LOSS_FRAC to 0.
    Above RS + 2.0: 0 (every turbine is at nameplate, no headroom for wake
    derate).
    """
    rs_star = rated_ws - 0.5
    L = np.full_like(ws, LOSS_FRAC, dtype=float)
    taper = (ws >= rs_star) & (ws <= rated_ws + 2.0)
    L[taper] = LOSS_FRAC * (1.0 - (ws[taper] - rs_star[taper]) / LOSS_TAPER_WIDTH)
    L[ws > rated_ws + 2.0] = 0.0
    return np.clip(L, 0.0, LOSS_FRAC)


# ---------------------------------------------------------------------------
# Density correction (IEC 61400-12-1)
# ---------------------------------------------------------------------------

def density_correct_wind_speed(
    ws: np.ndarray, pres_pa: np.ndarray, t2m_k: np.ndarray,
    rho_ref: float = RHO_REF,
) -> np.ndarray:
    """Density-corrected wind speed per IEC 61400-12-1.

    rho = pres / (R_d * t2m)
    WS_corrected = WS * (rho / rho_ref) ** (1/3)

    All inputs and outputs are 1-D arrays of length N (per plant per hour).
    Pressure in Pa, temperature in K, wind speed in m/s.

    Cold dense air (winter): rho > rho_ref → WS_corrected > WS  → more power.
    Warm thin air (summer):  rho < rho_ref → WS_corrected < WS  → less power.
    The cube-root keeps the wind-speed correction modest (a 10% density
    swing yields a 3.3% WS shift, which becomes ~10% in power via the
    cubic curve).
    """
    rho = pres_pa / (R_D * t2m_k)
    return ws * (rho / rho_ref) ** (1.0 / 3.0)


# ---------------------------------------------------------------------------
# SAM curve construction
# ---------------------------------------------------------------------------

# Per-EIA-plant turbine-spec overrides, gated by year. USWTDB reflects the
# current fleet, so a repowered plant shows up with its new turbines — wrong
# for validation against pre-repowering years. Each entry maps an EIA plant
# ID to (start_year, end_year_inclusive, cap_kw, rd_m): the override fires
# only when build_sam_curves is called with ``year`` inside that window.
# Callers that don't pass ``year`` get USWTDB-only specs (current fleet).
TURBINE_SPEC_OVERRIDES: dict[int, tuple[int, int, float, float]] = {
    # Steel Winds I (Lackawanna, NY): 8 × Clipper Liberty C93 (2500 kW,
    # 93 m rotor) from 2007. Repowered to GE2.5-116 in the NextEra 2019
    # campaign, completed Dec 2019. Override fires through 2019.
    56575: (2007, 2019, 2500.0, 93.0),
    # Steel Winds II / Erie Wind (Lackawanna, NY): 6 × Clipper Liberty C93
    # from 2012, repowered in the same Dec 2019 campaign.
    57078: (2012, 2019, 2500.0, 93.0),
}


def _representative_turbine_per_plant(
    meta: pd.DataFrame, uswtdb_turbines: pd.DataFrame,
    year: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-plant representative-turbine specs: mean per-turbine nameplate
    (kW) and rotor diameter (m). Both arrays aligned to *meta* rows.

    Aggregating per-turbine instead of per-fleet matters when several
    PGScen sites share an EIA plant ID (e.g. Maple Ridge 1 + 2): each
    site has the same turbine model, so the right SAM curve is the
    single-turbine curve, then the plant just scales by its nameplate.

    Plants without USWTDB matches get the fleet median spec so SAM still
    has a sensible curve to work with.

    EIA IDs listed in ``TURBINE_SPEC_OVERRIDES`` bypass USWTDB and use the
    hard-coded historical specs — but only when ``year`` falls inside the
    override's ``[start_year, end_year]`` window. ``year=None`` disables
    all overrides (callers that aren't year-aware get current USWTDB).
    """
    t = uswtdb_turbines[["eia_id", "t_cap", "t_rd"]].copy()
    t = t[(t["t_rd"].notna()) & (t["t_rd"] > 0)
          & (t["t_cap"].notna()) & (t["t_cap"] > 0)]
    by_eia = t.groupby("eia_id").agg(
        cap_kw=("t_cap", "mean"), rd_m=("t_rd", "mean"),
    )
    cap_lookup = by_eia["cap_kw"].to_dict()
    rd_lookup = by_eia["rd_m"].to_dict()

    def look(d, eia):
        if pd.isna(eia):
            return np.nan
        return d.get(float(eia), np.nan)

    cap = np.array([look(cap_lookup, row.get("eia_plant_id"))
                    for _, row in meta.iterrows()], dtype=float)
    rd = np.array([look(rd_lookup, row.get("eia_plant_id"))
                   for _, row in meta.iterrows()], dtype=float)
    if np.isnan(cap).any():
        cap = np.where(np.isnan(cap), float(np.nanmedian(cap)), cap)
    if np.isnan(rd).any():
        rd = np.where(np.isnan(rd), float(np.nanmedian(rd)), rd)

    if year is not None:
        for i, (_, row) in enumerate(meta.iterrows()):
            eia = row.get("eia_plant_id")
            if pd.notna(eia) and int(eia) in TURBINE_SPEC_OVERRIDES:
                start, end, cap_kw, rd_m = TURBINE_SPEC_OVERRIDES[int(eia)]
                if start <= year <= end:
                    cap[i], rd[i] = cap_kw, rd_m
    return cap, rd


def build_sam_curves(
    meta: pd.DataFrame, uswtdb_turbines: pd.DataFrame,
    max_cp: float = 0.45, max_tip_speed: float = 80.0,
    max_tip_sp_ratio: float = 8.0, drive_train: int = 0,
    year: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build NREL SAM smooth empirical power curves per plant.

    Returns three arrays:
      curve_ws    — 1-D array of wind speeds (m/s), shared across plants
      curve_cf    — 2-D array of capacity factors, shape (n_plants, n_ws)
      rated_ws    — 1-D array of SAM-derived rated wind speeds per plant

    Each plant's curve is generated by SAM via Windpower.Turbine
    .calculate_powercurve, using the plant's aggregated rotor diameter
    (sqrt of total swept area) and aggregated nameplate. Curve is
    normalised to capacity factor [0, 1] and clipped at cut-out (25 m/s).

    ``year`` is forwarded to ``_representative_turbine_per_plant`` so that
    year-gated entries in ``TURBINE_SPEC_OVERRIDES`` only fire for the
    matching calendar year. Pass ``year`` whenever the curves will be used
    to compute power for a specific year; omit it for year-agnostic plots.
    """
    import PySAM.Windpower as wp  # imported lazily to avoid hard dependency

    # Per-plant representative *single-turbine* specs (mean over USWTDB
    # rows for the plant's EIA ID). The CF curve we get from SAM is then
    # already plant-shape agnostic; scale by total plant nameplate at apply.
    cap_kw_per_t, rd_m_per_t = _representative_turbine_per_plant(
        meta, uswtdb_turbines, year=year,
    )

    m = wp.default("WindPowerNone")
    turbine = m.Turbine

    curves = []
    rs_list = []
    common_ws = None
    for i in range(len(meta)):
        rs = turbine.calculate_powercurve(
            float(cap_kw_per_t[i]),
            int(round(rd_m_per_t[i])),
            0.0, max_cp, max_tip_speed, max_tip_sp_ratio,
            CUT_IN_MS, CUT_OUT_MS, drive_train,
        )
        ws_i = np.array(turbine.wind_turbine_powercurve_windspeeds)
        pw_i = np.array(turbine.wind_turbine_powercurve_powerout)
        cf_i = pw_i / float(cap_kw_per_t[i])
        if common_ws is None:
            common_ws = ws_i
        elif not np.array_equal(common_ws, ws_i):
            cf_i = np.interp(common_ws, ws_i, cf_i, left=0.0, right=0.0)
        curves.append(np.clip(cf_i, 0.0, 1.0))
        rs_list.append(rs)
    return common_ws, np.vstack(curves), np.array(rs_list)


def sam_power_all_plants(
    ws: np.ndarray,
    nameplate_mw: np.ndarray,
    curve_ws: np.ndarray,
    curve_cf: np.ndarray,
) -> np.ndarray:
    """Apply per-plant SAM power curves via interpolation.

    Inputs:
      ws            — length-N array of wind speeds (m/s) per plant
      nameplate_mw  — length-N
      curve_ws      — length-K shared wind-speed grid for the SAM curves
      curve_cf      — shape (N, K) per-plant capacity factor curves

    Returns: length-N power output in MW.
    """
    n = len(ws)
    cf = np.empty(n, dtype=float)
    for i in range(n):
        cf[i] = np.interp(ws[i], curve_ws, curve_cf[i], left=0.0, right=0.0)
    return cf * nameplate_mw


def pluswind_v3_power_all_plants(
    ws: np.ndarray, pres_pa: np.ndarray, t2m_k: np.ndarray,
    nameplate_mw: np.ndarray,
    curve_ws: np.ndarray, curve_cf: np.ndarray, rated_ws: np.ndarray,
) -> np.ndarray:
    """Full PLUSWIND recipe: density correction + per-plant SAM curve + 7% loss.

    Differences from v2:
      v2 uses a parametric cubic curve `((WS-3)/(RS-3))^3` for the partial-
      load region. v3 replaces it with NREL SAM's smooth empirical curve,
      which produces ~1.5–4× more power at WS in the 5–9 m/s band — the
      band where NY plants spend most of their operating hours.

    The 7% loss model from v1/v2 is unchanged. Loss tapers near each plant's
    SAM-derived rated wind speed.
    """
    ws_corrected = density_correct_wind_speed(ws, pres_pa, t2m_k)
    p = sam_power_all_plants(ws_corrected, nameplate_mw, curve_ws, curve_cf)
    L = loss_fraction(ws_corrected, rated_ws)
    return p * (1.0 - L)


# ---------------------------------------------------------------------------
# Multi-cell aggregation (Task 1.1)
#
# v3 evaluates the power curve at one HRRR cell (plant centroid). Real wind
# farms span multiple 3 km cells — median 7, max 17 for the NY fleet (see
# experiments/wind_validation probe). Two ways to aggregate:
#
#   A. Per-cell curve eval, then sum. Each turbine sees its own cell's WS;
#      cell power = nameplate-weight × curve(WS_cell, ...). Plant = Σ cells.
#      Right when turbines span cells with materially different WS.
#
#   B. Weighted-average WS over cells first, then one curve eval. Cheaper.
#      Identical to A only when the curve is locally linear in WS — i.e.
#      far from cut-in (3 m/s) and far from rated (~10 m/s). In the cubic
#      partial-load band both differ measurably.
#
# Both take a *plant→cell* mapping as a dense 2D weight matrix (zero where
# a plant doesn't touch a cell). Pres/T2m are sampled per cell too (cold air
# raises power; ignoring spatial pressure variation would mask the gain).
# ---------------------------------------------------------------------------

def pluswind_v4_power_multicell_A(
    ws_cells: np.ndarray, pres_pa_cells: np.ndarray, t2m_k_cells: np.ndarray,
    plant_cell_weights: np.ndarray,
    nameplate_mw: np.ndarray,
    curve_ws: np.ndarray, curve_cf: np.ndarray, rated_ws: np.ndarray,
) -> np.ndarray:
    """Method A — per-cell curve evaluation, then weighted sum to plant.

    Inputs:
      ws_cells, pres_pa_cells, t2m_k_cells  — length-C arrays of cell-level
        wind speed, surface pressure, 2 m temperature (one per unique HRRR
        cell across the fleet). C is much less than N_plants × N_cells_per_plant
        because plants share cells.
      plant_cell_weights — shape (N, C). Row p, col c = fraction of plant p's
        nameplate located in cell c. Rows must sum to 1 for plants with any
        weight; rows of all-zero are allowed but the plant will get power=0.
      nameplate_mw       — length-N total plant nameplate.
      curve_ws, curve_cf — per-plant SAM curves (length-K and (N, K)).
      rated_ws           — per-plant rated WS for the loss taper.

    Returns: length-N power in MW.

    Note on density: density correction is cell-local (uses cell pres + t2m).
    The loss taper is evaluated at each cell's corrected WS and weighted in
    the same way as the curve output, so a plant straddling rated/below-rated
    cells gets a continuous loss across cells, not a step at the plant mean.
    """
    n_plants = len(nameplate_mw)
    n_cells = len(ws_cells)
    assert plant_cell_weights.shape == (n_plants, n_cells), (
        f"weights shape {plant_cell_weights.shape} != ({n_plants},{n_cells})")

    # 1. Density-correct WS at each cell (vector op — same fn, cell-level).
    ws_corr_cells = density_correct_wind_speed(
        ws_cells, pres_pa_cells, t2m_k_cells)

    # 2. For each (plant, cell) pair with non-zero weight, evaluate that
    # plant's curve at the cell's corrected WS. Result is shape (N, C).
    # Loop on plants (small N=31) but vectorise over cells.
    cf_pc = np.zeros((n_plants, n_cells), dtype=float)
    for p in range(n_plants):
        cf_pc[p, :] = np.interp(
            ws_corr_cells, curve_ws, curve_cf[p], left=0.0, right=0.0)

    # 3. Loss fraction at each (plant, cell): rated WS is per-plant, WS is
    # per-cell. Broadcast: (N, 1) for rated_ws, (1, C) for ws_corr → (N, C).
    rs = rated_ws[:, None]
    ws_grid = ws_corr_cells[None, :]
    rs_star = rs - 0.5
    L = np.full((n_plants, n_cells), LOSS_FRAC, dtype=float)
    taper = (ws_grid >= rs_star) & (ws_grid <= rs + 2.0)
    L = np.where(
        taper,
        LOSS_FRAC * (1.0 - (ws_grid - rs_star) / LOSS_TAPER_WIDTH),
        L,
    )
    L = np.where(ws_grid > rs + 2.0, 0.0, L)
    L = np.clip(L, 0.0, LOSS_FRAC)

    # 4. Per-(plant, cell) power = nameplate × weight × CF × (1-L). Sum over
    # cells to get plant total. weight already accounts for the share of
    # nameplate in each cell, so plant power = nameplate × Σ_c w_pc × CF_pc × (1-L_pc).
    return (nameplate_mw * (plant_cell_weights * cf_pc * (1.0 - L)).sum(axis=1))


def pluswind_v4_power_multicell_B(
    ws_cells: np.ndarray, pres_pa_cells: np.ndarray, t2m_k_cells: np.ndarray,
    plant_cell_weights: np.ndarray,
    nameplate_mw: np.ndarray,
    curve_ws: np.ndarray, curve_cf: np.ndarray, rated_ws: np.ndarray,
) -> np.ndarray:
    """Method B — weighted-average WS over cells first, then one curve eval.

    Cheaper than Method A (single curve eval per plant). Differs from A
    wherever the curve is non-linear at the plant's cell-WS spread — i.e.
    the steep partial-load band 5–9 m/s, which is where most NY operating
    hours fall.

    Density correction is applied at the plant level using weight-averaged
    pres/T2m. This is a deliberate simplification of B; if it ever becomes
    the chosen method we may want to revisit (the density swing across
    cells in a 14 km plant footprint is small).
    """
    # 1. Weighted-average ws/pres/t2m per plant.
    ws_p   = plant_cell_weights @ ws_cells           # (N,)
    pres_p = plant_cell_weights @ pres_pa_cells      # (N,)
    t2m_p  = plant_cell_weights @ t2m_k_cells        # (N,)

    # 2. Apply the existing v3 single-cell pipeline at the plant level.
    return pluswind_v3_power_all_plants(
        ws_p, pres_p, t2m_p, nameplate_mw,
        curve_ws, curve_cf, rated_ws,
    )
