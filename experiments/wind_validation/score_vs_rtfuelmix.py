"""R1.2 — fleet-sum regression detector: in-house wind model vs NYISO rtfuelmix.

rtfuelmix Wind is the NYISO **statewide system total** AFTER transmission /
economic curtailment, observed ~31% below the modeled potential fleet-sum
(2023 loss_scalar≈0.69). Level comparison is therefore invalid
(``level_validatable=False``): raw nMAE/bias of potential vs rtfuelmix is NOT
reported. Only (a) Pearson r and (b) ramp correlation are valid directly;
(c) scaled-nMAE is reported only after dividing out a single per-year fleet
loss_scalar. rtfuelmix has no zonal breakdown, so only the fleet-sum is
comparable — no per-zone validation against rtfuelmix is possible.

What this harness CAN validate: fleet-aggregate shape + ramp fidelity, and
per-year loss-scalar stability across 2018-2024 — a regression tripwire for
systematic fleet-wide model drift (e.g. a bad curve rollout that shifts the
whole fleet).

What it CANNOT validate (stated honestly): Steel Wind (wind_323596, 20 MW) +
Erie Wind (wind_323693, 15 MW) are jointly ~35 MW / ~1.35% of fleet energy,
while the fleet-vs-rtfuelmix hourly residual std is ~178 MW (≈17× their total
output). Removing both plants changes the fleet correlation by ~0.0003.
rtfuelmix therefore CANNOT detect a regression in any individual sub-150-MW
plant — those need a per-plant metered/LPI anchor, not rtfuelmix.

Default model = v3 actuals; pass --suffix .pluswind_v4 once the v4 rebuild
(R2.1) exists to re-freeze the comparison on v4.

Output: docs/figures/wind_v3/rtfuelmix_fleet_scorecard{suffix}.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
WIND_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FUELMIX   = REPO_ROOT / "data" / "nyiso_cache"
OUT_DIR   = REPO_ROOT / "docs" / "figures" / "wind_v3"
YEARS = list(range(2018, 2025))

I3_NOTE = ("rtfuelmix Wind = NYISO statewide system total, post-curtailment "
           "(~31% below modeled potential). level_validatable=False: only "
           "pearson_r + ramp_r valid directly; scaled_nmae after a single "
           "fleet loss_scalar. No zonal breakdown -> fleet-sum only.")


def load_model_fleet(year: int, suffix: str) -> pd.Series:
    """Hourly fleet-sum (MW) of the model actuals, UTC tz-naive index."""
    f = WIND_DIR / f"wind_actual_1h_site_{year}_utc{suffix}.csv"
    if not f.exists():
        return pd.Series(dtype=float), 0
    df = pd.read_csv(f, parse_dates=["Time"])
    ts = pd.to_datetime(df["Time"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    plant_cols = [c for c in df.columns if c.startswith("wind_")]
    fleet = df[plant_cols].sum(axis=1, min_count=1)
    return pd.Series(fleet.to_numpy(), index=ts, name="model").sort_index(), len(plant_cols)


def load_rtfuelmix_wind(year: int) -> pd.Series:
    """Hourly-mean NYISO statewide Wind (MW), UTC tz-naive index.

    rtfuelmix is 5-min, columns: Time Stamp, Time Zone, Fuel Category, Gen MW.
    Time Stamp is local wall clock; Time Zone (EST/EDT) gives the UTC offset
    explicitly (EST=+5h, EDT=+4h) — this disambiguates the duplicated fall-back
    hour and the missing spring-forward hour without tz_localize ambiguity.
    """
    ydir = FUELMIX / str(year) / "fuel_mix"
    if not ydir.is_dir():
        return pd.Series(dtype=float)
    frames = []
    for mdir in sorted(ydir.iterdir()):
        if not mdir.is_dir():
            continue
        for f in sorted(mdir.glob("*rtfuelmix.csv")):
            d = pd.read_csv(f)
            d = d[d["Fuel Category"] == "Wind"]
            if d.empty:
                continue
            frames.append(d[["Time Stamp", "Time Zone", "Gen MW"]])
    if not frames:
        return pd.Series(dtype=float)
    raw = pd.concat(frames, ignore_index=True)
    naive = pd.to_datetime(raw["Time Stamp"])
    off = raw["Time Zone"].map({"EST": 5, "EDT": 4})
    utc = naive + pd.to_timedelta(off, unit="h")
    s = pd.Series(pd.to_numeric(raw["Gen MW"], errors="coerce").to_numpy(),
                  index=utc, name="rt").dropna()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s.resample("1h").mean()


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def metrics(model: pd.Series, rt: pd.Series, year, n_plants: int) -> dict:
    j = pd.concat([model.rename("m"), rt.rename("r")], axis=1).dropna()
    if j.empty:
        return {"year": year, "n_hours": 0}
    m = j["m"].to_numpy(); r = j["r"].to_numpy()
    loss_scalar = float(r.mean() / m.mean()) if m.mean() > 0 else float("nan")
    m_scaled = m * loss_scalar
    scaled_mae = float(np.abs(r - m_scaled).mean())
    scaled_rmse = float(np.sqrt(((r - m_scaled) ** 2).mean()))
    rm = r.mean()
    # ramps on consecutive hours
    idx = j.index
    dt = pd.Series(idx).diff().dt.total_seconds().to_numpy()
    ok = (dt == 3600.0)[1:]
    dm = np.diff(m); dr = np.diff(r)
    ramp_r = _pearson(dm[ok], dr[ok]) if ok.any() else float("nan")
    return {
        "year": year, "n_hours": int(len(j)), "fleet_plants_n": n_plants,
        "mean_model_mw": float(m.mean()), "mean_rtfuelmix_mw": float(rm),
        "loss_scalar": loss_scalar,
        "pearson_r": _pearson(m, r),
        "ramp_pearson_r": ramp_r,
        "ramp_std_model": float(dm[ok].std()) if ok.any() else float("nan"),
        "ramp_std_rt": float(dr[ok].std()) if ok.any() else float("nan"),
        "scaled_nmae_pct": 100 * scaled_mae / rm if rm > 0 else float("nan"),
        "scaled_nrmse_pct": 100 * scaled_rmse / rm if rm > 0 else float("nan"),
        "level_validatable": False,
        "notes": I3_NOTE,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default=".pluswind_v3",
                    help="model actuals suffix (.pluswind_v3 default; .pluswind_v4 after R2.1)")
    args = ap.parse_args()

    print("=" * 90)
    print(f"rtfuelmix fleet-sum regression detector — model suffix '{args.suffix}'")
    print("=" * 90)

    rows = []
    pooled_m, pooled_r = [], []
    for y in YEARS:
        model, n_plants = load_model_fleet(y, args.suffix)
        rt = load_rtfuelmix_wind(y)
        if model.empty or rt.empty:
            print(f"  {y}: missing data (model {len(model)}, rt {len(rt)}) — skip")
            continue
        mt = metrics(model, rt, y, n_plants)
        rows.append(mt)
        j = pd.concat([model.rename("m"), rt.rename("r")], axis=1).dropna()
        pooled_m.append(j["m"]); pooled_r.append(j["r"])
        print(f"  {y}: n={mt['n_hours']:5d} plants={n_plants} "
              f"model={mt['mean_model_mw']:6.1f}MW rt={mt['mean_rtfuelmix_mw']:6.1f}MW "
              f"loss_scalar={mt['loss_scalar']:.3f} r={mt['pearson_r']:.3f} "
              f"ramp_r={mt['ramp_pearson_r']:.3f} scaled_nMAE={mt['scaled_nmae_pct']:.1f}%")

    if pooled_m:
        pm = pd.concat(pooled_m); pr = pd.concat(pooled_r)
        mt = metrics(pm, pr, "all", -1)
        rows.append(mt)
        print(f"  ALL: n={mt['n_hours']:5d} loss_scalar={mt['loss_scalar']:.3f} "
              f"r={mt['pearson_r']:.3f} ramp_r={mt['ramp_pearson_r']:.3f} "
              f"scaled_nMAE={mt['scaled_nmae_pct']:.1f}%")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = args.suffix.replace(".pluswind", "")  # _v3 / _v4
    out = OUT_DIR / f"rtfuelmix_fleet_scorecard{tag}.csv"
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.4f")
    print(f"\nWrote {out.relative_to(REPO_ROOT)}")
    print("\nCAVEAT: cannot detect regressions in individual sub-150-MW plants "
          "(Steel/Erie are ~1.35% of fleet energy, ~17x below the residual "
          "noise floor). Fleet-drift tripwire only.")


if __name__ == "__main__":
    main()
