## Initial Notes on Desired Workflow

The goal of this is to create a sensitivity analysis interactive dashboard using Panel and Holoviews. Some details:
* In `sensitivity_analysis`: use the `config.py` starter for path information to use. 
* Absolutely do not modify any of the database files linked in config.py. 

Overall plan for this:

* Efficient, concise, not over-engineered.
* Read in indicator values from WaterALLOC directly from INDICATOR_DB (table: IndValues_WaAlloc)
* Reproduce calculations in Calculate_ImpactChains.ipynb (store results in memory, DO NOT WRITE BACK TO THE DATABASE)


What will the dashboard do? 
1. User will select a basin (column Cuenca in the SHAPEFILE_PATH) from a dropdown
2. User will pick a COMID or multiple COMIDs from a dropdown (column COMID in the SHAPEFILE_PATH)
3. There will be sliders for each Water ALLOC indicator for multilier adjustmnets to the base values. These will be incremental values set by PERTURBATION_LEVELS_HIGHER_BETTER and PERTURBATION_LEVELS_LOWER_BETTER (depending on whether they are ASC or DESC). Default value will be 1. Users can adjust as many of these as they'd like (all start at 1, but can toggle as many to different values as they want).
4. The changes (multipliers for each indicator) will be applied ONLY to the selected COMIDs from step 2.
5. Full impact chain risk values are re-calculated with new values as described above.
6. User selects impact chain and sector to plot
7. The selected basin and all COMIDs will be plotted with risk for that impact chain colored from low risk (green) to high risk (red) in one map and a percent change in risk from the baseline scenario (default values, pulled directly from database) in another. The selected COMID(s) from Step 2 are outlined in a color that stands out and with a bolder outline. 
8. Also provide one compact basin summary widget in large text only (no table/bar) showing: baseline overall basin score, with-change overall basin score, and percent change from baseline.

Notes:
It'd be cool to have some kind of cache or something so that combinations of information that are already run would be loaded more quickly, but let's wait to see how performant it is. 

---

## Fleshed-out implementation notes (simple, not over-engineered)

### Core calculation behavior to mirror from `Calculate_ImpactChains.ipynb`

1. Build a single indicator dataset per selected impact chain (`IcID`) and water allocation scenario (`WaScnID`) by combining:
	- `IndValues_WaALLOC` filtered by `WaScnID`
	- `IndValues_Dyn` mapped through `WaScnID -> ScnID` via `WaScenarios`
	- `IndValues_Static` mapped to the same `WaScnID`
2. Join with:
	- `ImpactChain_Indicators` (which indicators belong to each impact chain)
	- `IndicatorWeights` (indicator-level weights)
	- `Indicators` (`Min`, `Max`, `Order`)
3. Normalize each indicator value with min-max scaling:
	- `norm = (Value - Min) / (Max - Min)` clipped to `[0, 1]`
	- If `Order == DESC`, invert with `1 - norm`
4. Compute factor indices by COMID:
	- `Peligro (P)` = weighted average of normalized `P` indicators
	- `Exposicion (E)` = weighted average of normalized `E` indicators
	- `Vulnerabilidad (V)` = weighted combination of subgroup averages (`VSS`, `VSB`, `VCA`)
5. Compute risk by COMID:
	- `Riesgo = weighted average of P, V, E` using factor weights (or equal fallback)
6. Keep everything in memory only (no writes to DB).

### Sensitivity behavior

1. Load baseline values once from DB for the selected scenario.
2. When user changes multipliers:
	- Apply multiplier only to selected COMID(s)
	- Apply only to WaterALLOC indicators (source = WaterALLOC)
	- Leave all other indicators unchanged
3. Recalculate P/V/E/R for all COMIDs in selected basin (baseline + perturbed).
4. Compute percent change map:
	- `pct_change = ((risk_perturbed - risk_baseline) / risk_baseline) * 100`
	- Handle divide-by-zero safely.
5. Compute basin-level area-weighted risk summary for the selected impact chain:
	- Use basin COMIDs only
	- Use COMID area from shapefile as weights
	- `basin_risk = sum(risk_i * area_i) / sum(area_i)`
	- Compute both baseline and perturbed basin risk
	- `basin_pct_change = ((basin_risk_perturbed - basin_risk_baseline) / basin_risk_baseline) * 100`
	- If baseline basin risk is 0, cap displayed percent change to `+/-100%`
	- Display these 3 values in a single large-text summary widget

---

## Proposed additions to `sensitivity_analysis` (lean structure)

Goal: avoid one giant script, but keep code compact and readable.

1. `sensitivity_analysis/app.py`
	- Panel app layout and widgets
	- Wiring callbacks and plotting
2. `sensitivity_analysis/data_access.py`
	- DB reads only
	- Shapefile read and basin/COMID filtering
3. `sensitivity_analysis/calculations.py`
	- Normalization and impact-chain math
	- Baseline + perturbed recomputation functions
4. `sensitivity_analysis/plots.py`
	- HoloViews map builders for risk and percent-change maps
	- Basin summary large-text metric widget (baseline, with-change, percent change)
5. `sensitivity_analysis/models.py` (optional)
	- Small dataclasses for clean argument passing
	- Example: selected basin, selected COMIDs, multiplier dictionary

### Classes vs functions

- Prefer functions for most logic.
- Use at most one lightweight class/dataclass for app state if needed.
- Avoid a heavy OOP hierarchy.

---

## Step-by-step execution plan

1. Confirm schema names and case sensitivity for these tables in the live DB:
	- `IndValues_WaALLOC` vs `IndValues_WaAlloc`
	- `ImpactChains`, `ImpactChain_Indicators`, `IndicatorWeights`, `FactorWeights`, `Indicators`, `WaScenarios`
2. Implement `data_access.py`:
	- Open read-only DB connection(s)
	- Query impact chains + sectors for dropdowns
	- Query full indicator dataset needed for one `(WaScnID, IcID)`
	- Load shapefile and expose basin/COMID lookup tables
3. Implement `calculations.py`:
	- Port min-max + ASC/DESC logic exactly
	- Port weighted P/E/V/R logic exactly
	- Add function to apply user multipliers to selected COMIDs only
	- Add function returning baseline + perturbed risk + percent change
	- Add function returning basin-level area-weighted baseline risk, perturbed risk, and percent change
4. Implement `plots.py`:
	- Risk choropleth (green low -> red high)
	- Percent-change choropleth (diverging scale)
	- Overlay selected COMIDs with bold, high-contrast outline
	- Add one basin score output widget in large text only: baseline, with-change, and percent change
5. Implement `app.py` widgets:
	- Basin select
	- Multi-select COMID list (filtered by basin)
	- Impact chain select
	- Sector select (or derived from selected impact chain)
	- Dynamic multiplier controls for WaterALLOC indicators (default 1)
6. Connect reactivity:
	- On any widget update, recompute in memory
	- Refresh both maps, COMID summary table, and basin area-weighted summary
7. Add basic performance guardrails:
	- Cache baseline per `(WaScnID, IcID, basin)`
	- Optionally cache perturbed outputs by a hash of selections/multipliers
8. Add minimal validation/QC:
	- Warn for missing indicator values
	- Warn for indicators with `Min == Max`
	- Safe handling for nulls and zero denominators
9. Add run instructions:
	- `panel serve sensitivity_analysis/app.py --show`

---

## Decisions captured

1. Scenario will be selectable in the UI.
2. Multiplier controls will be per `TextID` (example: `VSS6`).
3. Multiplier controls should include all WaterALLOC indicators (not only those in selected impact chain).
4. `UserID` is fixed to `1`.
5. Sector is auto-derived from selected impact chain.
6. Percent change when baseline risk is 0 should be capped to `+/-100%`.
7. Dashboard should update live on control changes (no required Apply button).
8. Include a summary table for selected COMIDs (baseline, perturbed, percent change).

## Remaining clarifications

1. If selected COMIDs become invalid after basin change, should COMIDs be auto-cleared to only basin-valid values?
2. Confirm DB interaction is strictly read-only for this dashboard (no inserts/updates/deletes).
