"""#4 Forecast error by hour-of-day, v3-MOS vs v4-MOS, held-out 2023.
For v4 (single 18Z DAM) hour-of-day H == lead time H+6, so the x-axis doubles
as forecast lead. Panel A = MAE by hour; Panel B = bias by hour (did MOS remove
the diurnal bias?)."""
import sys; from pathlib import Path
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import numpy as np, pandas as pd
import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from et_plot import to_et, HOUR_ET
REPO=Path(__file__).resolve().parents[2]; W=REPO/"PGscen-2nd/data/NYISO_real/wind"; FIG=REPO/"docs/figures/wind_v3"
def fc(suf):
    d=pd.read_csv(W/f"wind_day_ahead_forecast_site_2023_utc.pluswind_{suf}.rolling.csv",parse_dates=["Forecast_time"])
    d["Forecast_time"]=pd.to_datetime(d["Forecast_time"],utc=True); s=[c for c in d.columns if c.startswith("wind_")]
    return to_et(d.drop_duplicates("Forecast_time").set_index("Forecast_time")[s].sum(axis=1,min_count=1))
def act(suf):
    d=pd.read_csv(W/f"wind_actual_1h_site_2023_utc.pluswind_{suf}.csv",parse_dates=["Time"],index_col="Time")
    d.index=pd.to_datetime(d.index,utc=True); s=[c for c in d.columns if c.startswith("wind_")]
    return to_et(d[s].sum(axis=1,min_count=1))
j3=pd.concat([fc("v3").rename("f"),act("v3").rename("a")],axis=1).dropna()
j4=pd.concat([fc("v4").rename("f"),act("v4").rename("a")],axis=1).dropna()
for j in (j3,j4):
    j["H"]=j.index.hour; j["e"]=j.f-j.a
g3=j3.groupby("H"); g4=j4.groupby("H")
fig,ax=plt.subplots(1,2,figsize=(15,5.5))
ax[0].plot(range(24),g3.apply(lambda x:x.e.abs().mean()),"o-",color="#e67e22",label="v3-MOS")
ax[0].plot(range(24),g4.apply(lambda x:x.e.abs().mean()),"^-",color="#2471a3",label="v4-MOS")
ax[0].set_xlabel("forecast hour of day (ET)"); ax[0].set_ylabel("fleet MAE (MW)")
ax[0].set_title("A) Forecast error by hour-of-day / lead (held-out 2023)\nv4-MOS below v3-MOS at every hour"); ax[0].legend(); ax[0].grid(alpha=0.3)
ax[1].axhline(0,color="k",lw=0.6)
ax[1].plot(range(24),g3.apply(lambda x:x.e.mean()),"o-",color="#e67e22",label="v3-MOS")
ax[1].plot(range(24),g4.apply(lambda x:x.e.mean()),"^-",color="#2471a3",label="v4-MOS")
ax[1].set_xlabel("forecast hour of day (ET)"); ax[1].set_ylabel("fleet bias (forecast-actual, MW)")
ax[1].set_title("B) Residual bias by hour-of-day (post-MOS)\nflatter/closer to 0 = MOS removed the diurnal bias"); ax[1].legend(); ax[1].grid(alpha=0.3)
fig.suptitle("#4 Where the day-ahead forecast improved (2023 held-out)",fontsize=13,y=1.02); fig.tight_layout()
fig.savefig(FIG/"v4_forecast_by_hour.png",dpi=130,bbox_inches="tight"); print(f"wrote {FIG/'v4_forecast_by_hour.png'}")
