# 🛑 Task 5 — Stage A repoint to v4 (production flip — awaiting sign-off)

## Tasks 1–4 are all green

| Task | Result | Commit |
|---|---|---|
| 1 — v4 actuals candidate | committed | `ea652b2` |
| 2 — metadata audit | bug class closed, 0 new errors | `f1b6548` |
| 3 — tall-tier α | clip-0.25 robust (1–3% spread), no rebuilds | `5a86281` |
| 4 — forecast + MOS | held-out 2023 **17.05% vs v3 20.79%**, all 28 plants improved | `416a2bc` |

Both series are on v4 footing (actuals = v4 potential; forecast = v4-MOS-corrected),
`.raw_backup` preserved, v3 untouched.

## The repoint is exactly 2 lines

In `experiments/stage_a_joint_load_wind/build_joint_inputs.py:94-96` — atomic by
construction (both series flip in the same `_wind_files` function, never one
without the other):

```python
# actual:   wind_actual_1h_site_{y}_utc.pluswind_v3.csv          ->  .pluswind_v4.csv
# forecast: wind_day_ahead_forecast_site_{y}_utc.pluswind_v3.csv ->  .pluswind_v4.csv
```

Verified `run_stage_a.py` consumes wind **only** through this function — so
changing these two patterns flips Stage A completely and atomically.

**Fully reversible:** v3 files are untouched on disk; reverting is the same
2-line change back.

## One related item for your call

`PGscen-2nd/scripts/10_run_pgscen_wind.py` is a *separate* PGScen scenario runner
with `--variant` defaulting to `pluswind_v3` (CLI-overridable). It's not in the
Stage A path, but for consistency you may want its default bumped to v4 too.

- (a) flip Stage A only (strict work-order scope), or
- (b) flip Stage A + bump the runner's default.

## This is the production flip reserved for explicit human sign-off

I won't touch it until you say go. Decision requested:

1. **Flip Stage A → v4** (the 2-line `build_joint_inputs.py` change) and commit, and
2. also bump `10_run_pgscen_wind.py`'s default to v4, or leave it?
