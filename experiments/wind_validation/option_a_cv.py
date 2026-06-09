"""Cross-validation for the Option A per-(month, hour) calibration.

Tells us whether the 8.6 → 7.5 % BC nMAE lift is real generalization or
in-sample overfitting. Two tests:

  1. **Leave-one-year-out** (4 folds). For each year y in 2018-2021, fit the
     288 offsets on the OTHER three years and score y. Average across folds
     gives an honest out-of-sample BC nMAE.

  2. **Single split** (2018-2020 train / 2021 test). Sanity-check the LOYO
     numbers and tell us whether 2021 is special (post-2020 fleet growth,
     possible wind regime shift).

If LOYO and in-sample BC nMAE differ by more than ~0.5 pp, the per-bin
offsets are noisy and we should regularise (shrink each bin toward the
fleet mean).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
WIND = OUT_DIR.parents[1] / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
YEARS = [2018, 2019, 2020, 2021]


def load_actual(suffix: str) -> pd.DataFrame:
    fr = []
    for y in YEARS:
        f = WIND / f"wind_actual_1h_site_{y}_utc{suffix}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        fr.append(df)
    return pd.concat(fr).sort_index()


print("Loading 22-plant overlap actuals 2018-2021...")
v1 = load_actual(".pluswind_v1")
pl = load_actual(".pluswind")
common = sorted(set(v1.columns) & set(pl.columns))
print(f"  common plants: {len(common)}")

v1_sys = v1[common].sum(axis=1).rename("v1")
pl_sys = pl[common].sum(axis=1).rename("pl")
df = pd.concat([v1_sys, pl_sys], axis=1).dropna()
df["month"] = df.index.month
df["hour"]  = df.index.hour
df["year"]  = df.index.year
print(f"  joined: {len(df):,} h "
      f"(per-bin sample size ≈ {len(df) // 288:.0f})")


def fit_offsets(train: pd.DataFrame) -> pd.Series:
    """288-row table indexed by (month, hour). Constants are means in MW."""
    return (train.groupby(["month", "hour"])
                 .apply(lambda g: g["pl"].mean() - g["v1"].mean()))


def apply_calibration(test: pd.DataFrame, offsets: pd.Series) -> pd.Series:
    keys = list(zip(test["month"].to_numpy(), test["hour"].to_numpy()))
    off = pd.Series([offsets.get((int(m), int(h)), 0.0) for m, h in keys],
                    index=test.index)
    return (test["v1"] + off).clip(lower=0)


def score(target: pd.Series, predicted: pd.Series) -> dict:
    e = predicted - target
    bias = float(e.mean()); mae = float(e.abs().mean())
    am = float(target.mean())
    bc_mae = float((e - bias).abs().mean())
    return {
        "n": len(target), "bias_mw": bias, "mae_mw": mae,
        "nbias_pct": 100 * bias / am, "nmae_pct": 100 * mae / am,
        "bc_nmae_pct": 100 * bc_mae / am,
        "amean_mw": am,
    }


# ---------------------------------------------------------------------------
# 1. In-sample baseline (for reference)
# ---------------------------------------------------------------------------
print("\n=== In-sample (fit + score on all 2018-2021) ===")
offsets_all = fit_offsets(df)
in_sample_pred = apply_calibration(df, offsets_all)
m = score(df["pl"], in_sample_pred)
print(f"  bias = {m['nbias_pct']:+.2f}%   nMAE = {m['nmae_pct']:.2f}%   "
      f"BC nMAE = {m['bc_nmae_pct']:.2f}%")

raw = score(df["pl"], df["v1"])
print(f"  raw physics_v1 baseline:  bias = {raw['nbias_pct']:+.2f}%   "
      f"nMAE = {raw['nmae_pct']:.2f}%   BC nMAE = {raw['bc_nmae_pct']:.2f}%")


# ---------------------------------------------------------------------------
# 2. Leave-one-year-out
# ---------------------------------------------------------------------------
print("\n=== Leave-one-year-out (fit on 3 years, test on 1) ===")
loyo_rows = []
for y in YEARS:
    train = df[df["year"] != y]
    test  = df[df["year"] == y]
    offs  = fit_offsets(train)
    pred  = apply_calibration(test, offs)
    m_test = score(test["pl"], pred)
    raw_y  = score(test["pl"], test["v1"])
    print(f"  test {y}: raw BC nMAE = {raw_y['bc_nmae_pct']:.2f}%   "
          f"calA BC nMAE = {m_test['bc_nmae_pct']:.2f}%   "
          f"(bias {m_test['nbias_pct']:+.2f}%)")
    loyo_rows.append({
        "test_year": y,
        "raw_bc_nmae": raw_y['bc_nmae_pct'],
        "calA_bc_nmae": m_test['bc_nmae_pct'],
        "calA_nmae": m_test['nmae_pct'],
        "calA_bias_pct": m_test['nbias_pct'],
        "n": m_test['n'],
    })

loyo = pd.DataFrame(loyo_rows)
# Sample-weighted means
n_total = loyo["n"].sum()
mean_raw_bc = (loyo["raw_bc_nmae"] * loyo["n"]).sum() / n_total
mean_calA_bc = (loyo["calA_bc_nmae"] * loyo["n"]).sum() / n_total
mean_calA_nmae = (loyo["calA_nmae"] * loyo["n"]).sum() / n_total
print(f"\n  weighted across folds: raw BC nMAE = {mean_raw_bc:.2f}%   "
      f"calA BC nMAE = {mean_calA_bc:.2f}%   calA nMAE = {mean_calA_nmae:.2f}%")
print(f"  in-sample BC nMAE was {m['bc_nmae_pct']:.2f}% — "
      f"gap to LOYO = {mean_calA_bc - m['bc_nmae_pct']:+.2f} pp")


# ---------------------------------------------------------------------------
# 3. Single split: fit 2018-2020, test 2021
# ---------------------------------------------------------------------------
print("\n=== Single split (fit 2018-2020, test 2021) ===")
train = df[df["year"].isin([2018, 2019, 2020])]
test  = df[df["year"] == 2021]
offs_train = fit_offsets(train)
pred_test = apply_calibration(test, offs_train)
m_test = score(test["pl"], pred_test)
m_train = score(train["pl"], apply_calibration(train, offs_train))
raw_test = score(test["pl"], test["v1"])
print(f"  train (2018-2020): bias = {m_train['nbias_pct']:+.2f}%   "
      f"nMAE = {m_train['nmae_pct']:.2f}%   BC nMAE = {m_train['bc_nmae_pct']:.2f}%")
print(f"  test  (2021     ): bias = {m_test['nbias_pct']:+.2f}%   "
      f"nMAE = {m_test['nmae_pct']:.2f}%   BC nMAE = {m_test['bc_nmae_pct']:.2f}%")
print(f"  raw 2021 baseline: BC nMAE = {raw_test['bc_nmae_pct']:.2f}%")


# ---------------------------------------------------------------------------
# 4. Stability of fitted offsets across folds
# ---------------------------------------------------------------------------
print("\n=== Offset stability across LOYO folds ===")
offset_table = pd.DataFrame()
for y in YEARS:
    fold = fit_offsets(df[df["year"] != y])
    offset_table[f"fold_{y}"] = fold
offset_table["all_4yr"] = offsets_all
offset_table["std_across_folds"] = offset_table[[f"fold_{y}" for y in YEARS]].std(axis=1)
offset_table["mean_across_folds"] = offset_table[[f"fold_{y}" for y in YEARS]].mean(axis=1)
print(f"  per-bin offset variability (std across 4 LOYO folds):")
print(f"    mean of stds   = {offset_table['std_across_folds'].mean():.2f} MW")
print(f"    median of stds = {offset_table['std_across_folds'].median():.2f} MW")
print(f"    max of stds    = {offset_table['std_across_folds'].max():.2f} MW")
print(f"  per-bin offset mean = {offset_table['mean_across_folds'].mean():.1f} MW")
print(f"  → offsets are stable if std/mean is small.")
