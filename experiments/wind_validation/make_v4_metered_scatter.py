"""#5 v4 potential vs LPI metered hourly scatter + loss slope, per group (2024).
Slope of delivered-on-potential (through origin) = mean delivered/potential =
1 - loss. 1:1 line shown; points below it = real-world loss."""
import sys; from pathlib import Path
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import numpy as np, pandas as pd
REPO=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(Path(__file__).resolve().parent))
from score_per_plant_hourly import load_lpi_long, LPI_GROUPS
W=REPO/"PGscen-2nd/data/NYISO_real/wind"; FIG=REPO/"docs/figures/wind_v3"
GROUPS=["copenhagen","maple_ridge","marble_agg","noble_agg"]
v4=pd.read_csv(W/"wind_actual_1h_site_2024_utc.pluswind_v4.csv",parse_dates=["Time"],index_col="Time"); v4.index=pd.to_datetime(v4.index,utc=True)
lpi=load_lpi_long(); lpi["ts"]=pd.to_datetime(lpi.ts_utc,utc=True)
fig,ax=plt.subplots(1,4,figsize=(19,4.8))
for k,gk in enumerate(GROUPS):
    g=LPI_GROUPS[gk]; sites=[s for s in g["site_ids"] if s in v4.columns]
    mod=v4[sites].sum(axis=1,min_count=1).rename("v4")
    met=lpi[lpi.group==gk].set_index("ts")["delivered_mw"].rename("met")
    j=pd.concat([mod,met],axis=1).dropna(); j=j[j.index.year==2024]
    a=ax[k]; a.scatter(j.v4,j.met,s=4,alpha=0.10,color="#2471a3")
    lim=[0,max(j.v4.max(),j.met.max())*1.02]
    a.plot(lim,lim,"k--",lw=1,label="1:1 (no loss)")
    slope=(j.v4*j.met).sum()/(j.v4**2).sum()   # least-squares through origin
    a.plot(lim,[slope*lim[0],slope*lim[1]],color="#c0392b",lw=2,label=f"fit slope {slope:.2f} (loss {100*(1-slope):.0f}%)")
    r=np.corrcoef(j.v4,j.met)[0,1]
    a.set_title(f"{gk}\nr={r:.2f}, n={len(j)}",fontsize=10); a.set_xlim(lim); a.set_ylim(lim)
    a.set_xlabel("v4 potential (MW)"); 
    if k==0: a.set_ylabel("LPI metered (MW)")
    a.legend(fontsize=8,loc="upper left"); a.grid(alpha=0.3)
fig.suptitle("#5 v4 potential vs LPI metered, hourly 2024 — loss slope per group "
             "(below 1:1 = real-world availability+wake+curtailment)",fontsize=12,y=1.04)
fig.tight_layout(); fig.savefig(FIG/"v4_metered_scatter.png",dpi=130,bbox_inches="tight")
print(f"wrote {FIG/'v4_metered_scatter.png'}")
