"""Score the in-house HRRR pipelines (legacy + physics_v1) against PLUSWIND
on the 2018-2021 overlap window. PLUSWIND is treated as the target because
it represents the quality bar for potential generation that we want PGScen
to consume.

To make the comparison apples-to-apples we restrict the fleet sum to the
*intersection* of plants present in both series — the 22 NY sites covered
by PLUSWIND. That isolates the physics gap from the coverage gap.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WIND = Path(__file__).resolve().parents[2] / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
YEARS = [2018, 2019, 2020, 2021]


def load_actual(suffix: str) -> pd.DataFrame:
    frames = []
    for y in YEARS:
        f = WIND / f"wind_actual_1h_site_{y}_utc{suffix}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


def load_forecast(suffix: str) -> pd.DataFrame:
    frames = []
    for y in YEARS:
        f = WIND / f"wind_day_ahead_forecast_site_{y}_utc{suffix}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Issue_time", "Forecast_time"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def metrics(actual: pd.Series, predicted: pd.Series) -> dict:
    df = pd.concat([actual, predicted], axis=1).dropna()
    a = df.iloc[:, 0]; p = df.iloc[:, 1]
    e = p - a
    bias = float(e.mean())
    mae = float(e.abs().mean())
    rmse = float(np.sqrt((e**2).mean()))
    am = float(a.mean()) if a.mean() > 0 else float("nan")
    bc_mae = float((e - bias).abs().mean())
    return {
        "n": int(len(df)),
        "bias_mw": bias,
        "mae_mw": mae,
        "rmse_mw": rmse,
        "nbias_pct": 100 * bias / am,
        "nmae_pct":  100 * mae / am,
        "bc_nmae_pct": 100 * bc_mae / am,
    }


legacy_act = load_actual("")
v1_act     = load_actual(".pluswind_v1")
v2_act     = load_actual(".pluswind_v2")
plus_act   = load_actual(".pluswind")

# Restrict to the intersection of plants (PLUSWIND coverage)
plus_cols = set(plus_act.columns)
sets_to_intersect = [plus_cols, set(legacy_act.columns), set(v1_act.columns)]
have_v2 = not v2_act.empty
if have_v2:
    sets_to_intersect.append(set(v2_act.columns))
common = sorted(set.intersection(*sets_to_intersect))
print(f"Common plants (intersection): {len(common)}; have v2: {have_v2}")
print(f"  PLUSWIND only: {sorted(plus_cols)}")
print()

legacy_sum = legacy_act[common].sum(axis=1).rename("legacy")
v1_sum     = v1_act[common].sum(axis=1).rename("physv1")
plus_sum   = plus_act[common].sum(axis=1).rename("pluswind")
v2_sum     = (v2_act[common].sum(axis=1).rename("physv2")
              if have_v2 else None)

# Forecasts (legacy + physv1 are MOS-corrected; PLUSWIND has none)
legacy_fc_df = load_forecast("")
v1_fc_df     = load_forecast(".pluswind_v1")

def fc_to_series(df, common):
    site_cols = [c for c in df.columns if c.startswith("wind_") and c in common]
    df["sys_mw"] = df[site_cols].sum(axis=1)
    s = df.set_index("Forecast_time")["sys_mw"].sort_index()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s

legacy_fc = fc_to_series(legacy_fc_df, common).rename("legacy_fc")
v1_fc     = fc_to_series(v1_fc_df, common).rename("physv1_fc")
v2_fc_df  = load_forecast(".pluswind_v2") if have_v2 else None
v2_fc     = (fc_to_series(v2_fc_df, common).rename("physv2_fc")
             if v2_fc_df is not None and not v2_fc_df.empty else None)

# Score against PLUSWIND
parts = [legacy_sum, v1_sum, legacy_fc, v1_fc, plus_sum]
if v2_sum is not None:
    parts.append(v2_sum)
if v2_fc is not None:
    parts.append(v2_fc)
allf = pd.concat(parts, axis=1)

print("=" * 92)
print("Score against PLUSWIND on the 22-plant overlap, 2018-2021")
print("=" * 92)
header = (f"{'year':>4}  {'series':>12} | {'n':>5} {'bias%':>7} {'nMAE%':>7} "
          f"{'BC nMAE%':>9} {'mean_MW':>8}")
print(header)
print("-" * len(header))

rows = []
for y in YEARS:
    sub = allf.loc[str(y)]
    target = sub["pluswind"]
    target_mean = target.mean()
    series_to_score = [("legacy_act",  "legacy"),
                       ("physv1_act",  "physv1"),
                       ("legacy_fcst", "legacy_fc"),
                       ("physv1_fcst", "physv1_fc")]
    if have_v2 and "physv2" in sub.columns:
        series_to_score.append(("physv2_act", "physv2"))
    if v2_fc is not None and "physv2_fc" in sub.columns:
        series_to_score.append(("physv2_fcst", "physv2_fc"))
    for label, col in series_to_score:
        if sub[col].dropna().empty:
            continue
        m = metrics(target, sub[col])
        rows.append({"year": y, "series": label, **m})
        print(f"{y:>4}  {label:>12} | {m['n']:>5} {m['nbias_pct']:>6.1f}% "
              f"{m['nmae_pct']:>6.1f}% {m['bc_nmae_pct']:>8.1f}% {target_mean:>7.0f}")

# Pooled across all 4 years
print("-" * len(header))
pooled = allf.loc["2018":"2021"]
target = pooled["pluswind"]
pool_series = [("legacy_act",  "legacy"),
               ("physv1_act",  "physv1"),
               ("legacy_fcst", "legacy_fc"),
               ("physv1_fcst", "physv1_fc")]
if have_v2 and "physv2" in pooled.columns:
    pool_series.append(("physv2_act", "physv2"))
if v2_fc is not None and "physv2_fc" in pooled.columns:
    pool_series.append(("physv2_fcst", "physv2_fc"))
for label, col in pool_series:
    if pooled[col].dropna().empty:
        continue
    m = metrics(target, pooled[col])
    print(f"pool  {label:>12} | {m['n']:>5} {m['nbias_pct']:>6.1f}% "
          f"{m['nmae_pct']:>6.1f}% {m['bc_nmae_pct']:>8.1f}%")
