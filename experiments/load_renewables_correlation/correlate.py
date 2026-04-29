"""
Correlations between NYISO load, utility-scale solar, BTM solar, and wind.

Aggregates each series to NYCA totals at hourly resolution, restricts to the
overlap window 2021-2024, and produces:
  - aligned time-series snapshots,
  - diurnal and monthly profiles,
  - a Pearson correlation heatmap (overall and by season),
  - a pairplot/scatter matrix.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real")
OUT = Path("/Users/val/Desktop/Princeton/experiments/load_renewables_correlation")
YEARS = [2021, 2022, 2023, 2024]


def load_zone_csv(path: Path, value_name: str) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Time"], index_col="Time")
    df.index = pd.to_datetime(df.index, utc=True)
    if "NYCA" in df.columns:
        s = df["NYCA"]
    else:
        s = df.sum(axis=1)
    s.name = value_name
    return s


def load_site_csvs(folder: Path, prefix: str, value_name: str) -> pd.Series:
    parts = []
    for y in YEARS:
        p = folder / f"{prefix}_actual_1h_site_{y}_utc.csv"
        df = pd.read_csv(p, parse_dates=["Time"], index_col="Time")
        df.index = pd.to_datetime(df.index, utc=True)
        parts.append(df.sum(axis=1))
    s = pd.concat(parts).sort_index()
    s.name = value_name
    return s


def main() -> None:
    load = load_zone_csv(
        ROOT
        / "load_actual_1h_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv",
        "Load",
    )
    btm = load_zone_csv(
        ROOT / "btm_solar_actual_1h_zone_2021_2022_2023_2024_2025_utc.csv",
        "BTM solar",
    )
    solar = load_site_csvs(ROOT / "solar", "solar", "Solar (utility)")
    wind = load_site_csvs(ROOT / "wind", "wind", "Wind")

    df = pd.concat([load, solar, btm, wind], axis=1).dropna()
    df = df.loc[
        (df.index >= pd.Timestamp(f"{YEARS[0]}-01-01", tz="UTC"))
        & (df.index < pd.Timestamp(f"{YEARS[-1] + 1}-01-01", tz="UTC"))
    ]
    df_local = df.tz_convert("US/Eastern")
    print(f"Aligned {len(df)} hourly samples from {df.index.min()} to {df.index.max()}")
    print("Means (MW):")
    print(df.mean().round(0))

    # ----- 1. Time-series snapshots -----------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=False)
    week = df_local.loc["2023-07-10":"2023-07-16"]
    week_norm = week / week.max()
    for c in week_norm.columns:
        axes[0].plot(week_norm.index, week_norm[c], label=c, lw=1.5)
    axes[0].set_title(
        "One summer week (Jul 10-16, 2023, US/Eastern) — normalized to series max"
    )
    axes[0].set_ylabel("Fraction of period max")
    axes[0].legend(loc="upper right", ncol=4, fontsize=9)
    axes[0].grid(alpha=0.3)

    week2 = df_local.loc["2023-01-09":"2023-01-15"]
    week2_norm = week2 / week2.max()
    for c in week2_norm.columns:
        axes[1].plot(week2_norm.index, week2_norm[c], label=c, lw=1.5)
    axes[1].set_title(
        "One winter week (Jan 9-15, 2023, US/Eastern) — normalized to series max"
    )
    axes[1].set_ylabel("Fraction of period max")
    axes[1].legend(loc="upper right", ncol=4, fontsize=9)
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "01_timeseries_weeks.png", dpi=140)
    plt.close(fig)

    # ----- 2. Diurnal profile (mean by hour of day, local) ------------------
    diurnal = df_local.groupby(df_local.index.hour).mean()
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.5), sharex=True)
    for ax, c in zip(axes, df.columns):
        ax.plot(diurnal.index, diurnal[c], lw=2, color="C0")
        ax.fill_between(
            diurnal.index,
            df_local.groupby(df_local.index.hour)[c].quantile(0.1),
            df_local.groupby(df_local.index.hour)[c].quantile(0.9),
            alpha=0.2,
        )
        ax.set_title(c)
        ax.set_xlabel("Hour of day (US/Eastern)")
        ax.set_xticks([0, 6, 12, 18])
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("MW (mean ± 10/90 pct)")
    fig.suptitle("Mean diurnal profile, 2021-2024", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "02_diurnal_profile.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    # ----- 3. Monthly mean profile ------------------------------------------
    monthly = df_local.groupby(df_local.index.month).mean()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    monthly_norm = monthly / monthly.max()
    for c in monthly_norm.columns:
        ax.plot(monthly_norm.index, monthly_norm[c], marker="o", label=c)
    ax.set_xticks(range(1, 13))
    ax.set_xlabel("Month")
    ax.set_ylabel("Mean / yearly max")
    ax.set_title("Seasonal profile (monthly means, normalized), 2021-2024")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "03_monthly_profile.png", dpi=140)
    plt.close(fig)

    # ----- 4. Correlation heatmap -------------------------------------------
    corr_overall = df.corr(method="pearson")
    print("\nOverall Pearson correlation:")
    print(corr_overall.round(3))

    seasons = {
        "Winter (DJF)": [12, 1, 2],
        "Spring (MAM)": [3, 4, 5],
        "Summer (JJA)": [6, 7, 8],
        "Fall (SON)": [9, 10, 11],
    }
    corrs = {"Overall": corr_overall}
    for label, months in seasons.items():
        mask = df_local.index.month.isin(months)
        corrs[label] = df.loc[mask].corr()

    fig, axes = plt.subplots(1, 5, figsize=(20, 4.2))
    for ax, (label, c) in zip(axes, corrs.items()):
        sns.heatmap(
            c,
            annot=True,
            fmt=".2f",
            cmap="RdBu_r",
            vmin=-1,
            vmax=1,
            cbar=False,
            square=True,
            ax=ax,
            annot_kws={"size": 9},
        )
        ax.set_title(label)
        ax.tick_params(axis="x", rotation=30)
    fig.suptitle(
        "Pearson correlation of hourly NYCA totals (2021-2024)", y=1.05, fontsize=13
    )
    fig.tight_layout()
    fig.savefig(OUT / "04_correlation_heatmap.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    # ----- 5. Daytime-only correlation (sun is up) --------------------------
    daytime_mask = (df_local.index.hour >= 9) & (df_local.index.hour <= 17)
    corr_day = df.loc[daytime_mask].corr()
    print("\nDaytime (9-17 local) Pearson correlation:")
    print(corr_day.round(3))

    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    sns.heatmap(
        corr_day,
        annot=True,
        fmt=".2f",
        cmap="RdBu_r",
        vmin=-1,
        vmax=1,
        square=True,
        ax=ax,
    )
    ax.set_title("Pearson correlation, daytime hours (9-17 local)")
    fig.tight_layout()
    fig.savefig(OUT / "05_correlation_daytime.png", dpi=140)
    plt.close(fig)

    # ----- 6. Pairplot / scatter matrix -------------------------------------
    sample = df.sample(n=min(8000, len(df)), random_state=0)
    sample = sample.assign(
        season=pd.Categorical(
            df_local.loc[sample.index].index.month.map(
                lambda m: next(k for k, v in seasons.items() if m in v)
            )
        )
    )
    g = sns.pairplot(
        sample,
        vars=list(df.columns),
        hue="season",
        diag_kind="hist",
        plot_kws={"s": 6, "alpha": 0.4},
        height=2.0,
    )
    g.fig.suptitle("Pairwise scatter (hourly NYCA, 8 000-sample), by season", y=1.02)
    g.fig.savefig(OUT / "06_pairplot.png", dpi=130, bbox_inches="tight")
    plt.close(g.fig)

    # Persist the aligned dataframe for reuse
    df.to_csv(OUT / "aligned_hourly_nyca.csv")
    corr_overall.to_csv(OUT / "correlation_overall.csv")
    print(f"\nWrote outputs to {OUT}")


if __name__ == "__main__":
    main()
