# NYISO Grid — VATIC Input Package

Grid : New York ISO, 679 bus, 792 branches, 1 373 générateurs, 44 BESS, zones A–K.

---

## Charge horaire — à télécharger avant de lancer

Le fichier de charge n'est pas inclus. Il vient du portail public NYISO MIS :

```
http://mis.nyiso.com/public/csv/palIntegrated/
```

URL directe pour un mois donné :
```
http://mis.nyiso.com/public/csv/palIntegrated/YYYYMMDD01pal_csv.zip
```

Exemple pour juillet 2025 :
```
http://mis.nyiso.com/public/csv/palIntegrated/2025070101pal_csv.zip
```

Le ZIP contient un CSV avec la charge réelle intégrée par zone (A–K) au pas de 5 min.
Utiliser le script fourni pour le convertir en horaire et l'extraire pour une date précise :

```bash
python fetch_nyiso_load.py --year 2025 --month 7
```

Cela génère `grid_data/hourly_load_YYYYMMDD.csv`. Passer ensuite ce chemin au script :

```bash
HOURLY_LOAD_CSV=grid_data/hourly_load_20250720.csv EXPERIMENT_TAG=montest python run_sced.py
```

> **Note :** si `HOURLY_LOAD_CSV` n'est pas défini, le script utilise des totaux zonaux
> hardcodés (pointe estivale 2025, ~31 500 MW) et répartit la charge sur 24h de façon
> uniforme — acceptable pour tester, pas pour reproduire une journée réelle.

---

## Lancer la simulation

```bash
cd Grid/
HOURLY_LOAD_CSV=grid_data/hourly_load_<date>.csv EXPERIMENT_TAG=montest python run_sced.py
```

Les résultats s'écrivent dans `grid_data/sced_inputs/results_<tag>/`.

**Solver :** Gurobi par défaut (`USE_GUROBI = True` ligne 69). Passer à `False` pour CBC si pas de licence.

Variables d'environnement utiles :
| Variable | Défaut | Rôle |
|---|---|---|
| `EXPERIMENT_TAG` | `baseline` | Nom du dossier de résultats |
| `SCED_DATE` | `2025-07-20` | Date de simulation |
| `HOURLY_LOAD_CSV` | *(vide)* | Chemin vers le CSV de charge horaire |
| `BRANCH_SCALE` | `1.0` | Multiplicateur des limites thermiques (0 = non-contraint) |
| `STORAGE_AGGREGATE` | `zone` | Agrégation BESS : `zone`, `bus`, ou `none` |

---

## Description des fichiers

### `run_sced.py`
Script principal. Charge le grid, distribue la charge zonale sur les bus, construit les timeseries renouvelables, puis lance le simulateur DC-SCED de VATIC.

Injections DC-ties hardcodées (lignes ~99–113) :
- Chateauguay (Zone D, Hydro-Québec) : 1 000 MW
- Massena (Zone D, Hydro-Québec) : 200 MW
- Niagara (Zone A, Ontario) : 500 MW
- Ramapo (Zone G, PJM) : 600 MW
- Linden (Zone J, PJM) : 300 MW
- Northport (Zone K, ISO-NE) : 100 MW

### `grid_data/sced_inputs/SourceData/bus.csv`
**679 bus.** Substations New York State dérivées d'OpenStreetMap, zones A–K.
Colonnes clés : `Bus ID`, `Bus Name`, `BaseKV`, `Zone`, `Sub Name`, `Lat`, `Lon`.

### `grid_data/sced_inputs/SourceData/branch.csv`
**792 branches.** Lignes de transmission ≥ 69 kV (HIFLD + OSM).
Colonnes clés : `UID`, `From Bus`, `To Bus`, `Resistance`, `Reactance`, `Rating`.
Les limites thermiques ont été calibrées pour correspondre aux interfaces NYISO. Les branches dont l'UID commence par `DRAFT_` ont une topologie non confirmée (réseau souterrain Con Edison, zones J/K).

### `grid_data/sced_inputs/SourceData/gen.csv`
**1 373 générateurs.** Parc EIA-860 (thermique, hydraulique, éolien, solaire).
Colonnes clés : `GEN UID`, `Bus ID`, `Fuel`, `Pmax MW`, `Pmin MW`, `Ramp Rate`, `No Load Cost`, `Start Up Cost`, `Marginal Cost`.

### `grid_data/sced_inputs/SourceData/init_state.csv`
**État initial des générateurs** pour la date de simulation.
Colonnes : `GEN`, `UnitOnT0`, `UnitOnT0State`, `PgT0`.

### `grid_data/sced_inputs/SourceData/storage.csv`
**44 unités BESS** (EIA-860).
Colonnes clés : `StorageUID`, `Bus ID`, `Discharge Rate MW`, `Charge Rate MW`, `Energy Capacity MWh`, `Efficiency`, `Initial SOC`.

### `grid_data/bus_county_weights.csv`
**Poids de distribution de charge par bus**, calculés à partir de l'EIA-861 (consommation par comté).
Utilisé pour distribuer les totaux zonaux sur les bus individuels. Si absent, le script utilise BaseKV^1.5 comme proxy.

### `grid_data/binding_constraints_2025.csv`
**Contraintes de transmission NYISO 2025** (flowgates DAM, prix d'ombre).
Les limites de branches dans `branch.csv` ont été calibrées à partir de ce fichier — il est inclus pour référence et analyse post-hoc, il n'est pas lu au runtime par `run_sced.py`.

---

## Limites connues du grid

- **Zones J (NYC) et K (Long Island) :** topologie partielle. Le réseau souterrain Con Edison (CEII) n'est pas public. ~3 bus isolés et ~8 branches `DRAFT_` avec connexions non confirmées.
- **Charges hardcodées :** les totaux zonaux MW sont dans `run_sced.py` lignes ~82–92. Pour changer la date de simulation, mettre à jour `SCED_DATE` et fournir le `HOURLY_LOAD_CSV` correspondant.
- **Pas de contingences N-1 :** simulation DC-SCED en régime normal uniquement.
