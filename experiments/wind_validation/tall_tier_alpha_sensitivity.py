"""Task 3 — tall-tier (>95 m hub) hub-lift alpha sensitivity.

The hub lift is validated only up to Copenhagen's 95 m anchor. Plants above
that extrapolate the power law beyond clean ground truth, in the stable night
hours where alpha is most inflated. Bound the risk by re-scoring each tall
plant's annual energy under three alpha treatments (post-processing on the
already-fetched npzs — no re-fetch):

  clip0.25   — current adopted (SHEAR_ALPHA_MAX=0.25)
  clip0.20   — tighter flat clip
  daynight   — daytime alpha clipped at 0.25 (trustworthy, ~0.143 anyway),
               night-hour alpha capped at climatology 0.15 (the inflation lives
               in the night tail). Day/night by EST local hour, per analyze_alpha.

Reports per tall plant: energy under each treatment, the spread (max-min)/clip25,
and per-year exposure (fraction of the plant's lift-affected energy in 2023-2024
— most tall plants are recent commissions, so this bounds how much of the v4
series the unvalidated lift actually touches).

Decision rule (work order): spread <~10% -> keep clip0.25; >~10% -> switch THAT
plant to daynight (never a flat cap). Output:
docs/figures/wind_v3/tall_tier_alpha_sensitivity.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "PGscen-2nd"))
from pgscen.utils.wind_physics import (  # noqa: E402
    build_sam_curves, pluswind_v5_power_multicell_A_hubshear,
)
PM = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
RAW = REPO / "docs" / "figures" / "wind_v3"
YEARS = list(range(2018, 2025))
HUB_TALL_M = 95.0
NIGHT_CLIP = {"alpha_max": 0.15}
DAY_CLIP   = {"alpha_max": 0.25}
CLIP25 = {"alpha_max": 0.25}
CLIP20 = {"alpha_max": 0.20}


def night_mask(times: pd.DatetimeIndex) -> np.ndarray:
    """Stable-BL night hours (EST local 22:00-04:00), per analyze_alpha."""
    lh = (times.hour - 5) % 24
    return (lh >= 22) | (lh <= 4)


def energy_for_treatment(ws80, ws10, pres, t2m, W, hub, nameplate,
                         cws, ccf, crs, times, treatment) -> np.ndarray:
    """Annual energy (MWh) per plant under a treatment. daynight uses a
    per-hour clip; clip0.25/clip0.20 use a fixed clip."""
    n_h = ws80.shape[0]
    nights = night_mask(times)
    total = np.zeros(W.shape[0])
    for h in range(n_h):
        if np.isnan(ws80[h]).all():
            continue
        if treatment == "daynight":
            akw = NIGHT_CLIP if nights[h] else DAY_CLIP
        elif treatment == "clip0.20":
            akw = CLIP20
        else:
            akw = CLIP25
        total += np.nan_to_num(pluswind_v5_power_multicell_A_hubshear(
            ws80[h], ws10[h], pres[h], t2m[h], W, hub, nameplate,
            cws, ccf, crs, alpha_kwargs=akw))
    return total   # MW summed over hours == MWh


def main():
    meta = pd.read_csv(PM / "wind_meta.csv")
    turbines = pd.read_csv(PM / "uswtdb_ny_turbines.csv")

    # Per-year energy by treatment for the tall plants.
    per_year = {}     # (treatment) -> DataFrame year x site
    tall_sites = None
    for y in YEARS:
        npz = RAW / f"alpha_raw_{y}.npz"
        if not npz.exists():
            print(f"  {y}: npz missing — skip"); continue
        d = np.load(npz, allow_pickle=True)
        site_ids = [str(s) for s in d["site_ids"]]
        hub = d["hub_h"]
        if tall_sites is None:
            tall_idx = [i for i in range(len(site_ids)) if hub[i] > HUB_TALL_M]
            tall_sites = [site_ids[i] for i in tall_idx]
        else:
            tall_idx = [site_ids.index(s) for s in tall_sites]
        meta_ord = meta.set_index("site_id").loc[site_ids].reset_index()
        cws, ccf, crs = build_sam_curves(meta_ord, turbines, year=y)
        nameplate = meta_ord["nameplate_mw"].to_numpy(float)
        # subset to tall plants
        W_t = d["W"][tall_idx, :]; hub_t = hub[tall_idx]
        np_t = nameplate[tall_idx]; cf_t = ccf[tall_idx]; rs_t = crs[tall_idx]
        times = pd.to_datetime(d["times"], unit="s", utc=True)
        # only score years the plant is active (op_year <= y); else its energy=0
        opy = meta_ord.set_index("site_id")["operating_year"].astype(int)
        active_t = np.array([opy[s] <= y for s in tall_sites])
        for tr in ["clip0.25", "clip0.20", "daynight"]:
            e = energy_for_treatment(d["ws80"], d["ws10"], d["pres"], d["t2m"],
                                     W_t, hub_t, np_t, cws, cf_t, rs_t, times, tr)
            e = np.where(active_t, e, 0.0)
            per_year.setdefault(tr, {})[y] = dict(zip(tall_sites, e))
        print(f"  {y}: scored {len(tall_sites)} tall plants x 3 treatments")

    # Assemble per-plant totals + spread + exposure.
    hub_map = dict(zip([str(s) for s in np.load(RAW/f'alpha_raw_{YEARS[-1]}.npz',
                                                allow_pickle=True)["site_ids"]],
                       np.load(RAW/f'alpha_raw_{YEARS[-1]}.npz',
                               allow_pickle=True)["hub_h"]))
    name_map = meta.set_index("site_id")["site_name"].to_dict()
    rows = []
    for s in tall_sites:
        tot = {tr: sum(per_year[tr][y].get(s, 0.0) for y in per_year[tr]) for tr in per_year}
        e25, e20, edn = tot["clip0.25"], tot["clip0.20"], tot["daynight"]
        spread = (max(e25, e20, edn) - min(e25, e20, edn)) / e25 * 100 if e25 > 0 else float("nan")
        # exposure: fraction of clip0.25 energy in 2023-2024
        e_recent = sum(per_year["clip0.25"][y].get(s, 0.0) for y in (2023, 2024) if y in per_year["clip0.25"])
        exposure = 100 * e_recent / e25 if e25 > 0 else float("nan")
        rows.append({
            "site_id": s, "name": name_map.get(s, s)[:30],
            "hub_m": round(float(hub_map[s]), 0),
            "GWh_clip0.25": round(e25 / 1000, 1),
            "GWh_clip0.20": round(e20 / 1000, 1),
            "GWh_daynight": round(edn / 1000, 1),
            "spread_pct": round(spread, 1),
            "pct_energy_2023_24": round(exposure, 1),
            "rec": "keep clip0.25" if spread <= 10 else "-> daynight",
        })
    df = pd.DataFrame(rows).sort_values("hub_m")
    df.to_csv(RAW / "tall_tier_alpha_sensitivity.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 100)
    print(f"Tall-tier (>{HUB_TALL_M:.0f} m hub) alpha sensitivity — {len(df)} plants, pooled 2018-2024")
    print("=" * 100)
    print(df.to_string(index=False))
    print(f"\nDecision rule: spread <=10% -> keep clip0.25; >10% -> day/night-split (that plant).")
    print(f"Wrote {(RAW/'tall_tier_alpha_sensitivity.csv').relative_to(REPO)}")


if __name__ == "__main__":
    main()
