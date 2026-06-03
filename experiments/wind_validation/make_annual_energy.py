"""#3 Annual energy v3 -> v4, per plant + fleet (GWh/yr equivalent = mean MW x 8.766).
Shows the absolute energy the freeze added and where (by hub tier)."""
import sys; from pathlib import Path
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import numpy as np, pandas as pd
REPO=Path(__file__).resolve().parents[2]; W=REPO/"PGscen-2nd/data/NYISO_real/wind"; FIG=REPO/"docs/figures/wind_v3"
YEARS=range(2018,2025)
def meanmw(suf):
    fr=[]
    for y in YEARS:
        f=W/f"wind_actual_1h_site_{y}_utc.pluswind_{suf}.csv"
        if f.exists():
            d=pd.read_csv(f,parse_dates=["Time"],index_col="Time"); fr.append(d)
    a=pd.concat(fr); a=a[~a.index.duplicated()]
    return a[[c for c in a.columns if c.startswith("wind_")]].mean()
m3,m4=meanmw("v3"),meanmw("v4")
hub=pd.read_csv(FIG/"fleet_hub_lift_clip025.csv").set_index("site_id")
common=[s for s in m4.index if s in m3.index]
df=pd.DataFrame({"v3":m3[common]*8.766,"v4":m4[common]*8.766})  # GWh/yr
df["hub"]=[hub.hub_h_m.get(s,80) for s in df.index]
df["name"]=[hub.name.get(s,s)[:14] for s in df.index]
df=df.sort_values("hub")
fig,ax=plt.subplots(figsize=(15,6)); x=np.arange(len(df)); w=0.4
col=["#c0392b" if h<79 else ("#95a5a6" if h<=81 else "#2471a3") for h in df.hub]
ax.bar(x-w/2,df.v3,w,color="#dfe6e9",edgecolor="#b2bec3",label="v3 GWh/yr")
ax.bar(x+w/2,df.v4,w,color=col,label="v4 GWh/yr (color=hub tier)")
ax.set_xticks(x); ax.set_xticklabels([f"{n}\n{h:.0f}m" for n,h in zip(df.name,df.hub)],fontsize=6,rotation=90)
ax.set_ylabel("annual energy (GWh/yr equiv = mean MW x 8.766)")
ft3,ft4=df.v3.sum(),df.v4.sum()
ax.set_title(f"#3 Annual potential energy per plant, v3 -> v4 (sorted by hub height)\n"
             f"FLEET total: {ft3:.0f} -> {ft4:.0f} GWh/yr ({100*(ft4/ft3-1):+.1f}%); red=sub-80m down, grey=80m, blue=tall up")
ax.legend(); ax.grid(axis="y",alpha=0.3); fig.tight_layout()
fig.savefig(FIG/"v4_annual_energy.png",dpi=130,bbox_inches="tight")
print(f"wrote {FIG/'v4_annual_energy.png'}; fleet {ft3:.0f}->{ft4:.0f} GWh/yr ({100*(ft4/ft3-1):+.1f}%)")
