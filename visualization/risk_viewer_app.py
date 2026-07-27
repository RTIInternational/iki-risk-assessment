from functools import lru_cache
from pathlib import Path
import sys

import panel as pn
import pandas as pd
from holoviews.element import tiles as hv_tiles

# Reuse existing data and plotting modules from sensitivity_analysis.
SENSITIVITY_DIR = Path(__file__).resolve().parents[1] / "sensitivity_analysis"
if str(SENSITIVITY_DIR) not in sys.path:
    sys.path.insert(0, str(SENSITIVITY_DIR))

from data_access import (  # noqa: E402
    get_baseline_scores_for_ic_scenario,
    get_basin_gdf,
    get_impact_chains,
    get_indicator_connection,
    get_scenarios,
    list_basins,
    load_shapefile,
)
from plots import build_risk_category_map  # noqa: E402

pn.extension("tabulator")

USER_ID = 1
BASEMAP_FACTORIES = {
    "None": None,
    "Carto Light": "CartoLight",
    "OpenStreetMap": "OSM",
    "Esri Street": "EsriStreet",
    "Esri Imagery": "EsriImagery",
    "Esri Terrain": "EsriTerrain",
    "OpenTopoMap": "OpenTopoMap",
}


def _ic_label(row) -> str:
    return f"{int(row['IcID'])}: {row['ImpactChain']}"


def _normalize_scenario_name(name: str) -> str:
    return " ".join(str(name).strip().lower().replace("_", " ").replace("-", " ").split())


def _resolve_fixed_scenarios(scenarios_df: pd.DataFrame):
    """Resolve scenario IDs for the three fixed maps shown in the viewer."""
    desired = [
        ("Base", ["base", "baseline"]),
        ("CMIP6 85 2050", ["cmip6 85 2050", "rcp85 2050", "ssp585 2050"]),
        ("CMIP6 45 2050", ["cmip6 45 2050", "rcp45 2050", "ssp245 2050"]),
    ]

    normalized_rows = [
        (_normalize_scenario_name(row["WaScnName"]), int(row["WaScnID"]))
        for _, row in scenarios_df.iterrows()
    ]

    resolved = []
    missing = []
    for label, aliases in desired:
        scenario_id = None
        for alias in aliases:
            for normalized_name, candidate_id in normalized_rows:
                if normalized_name == alias or alias in normalized_name:
                    scenario_id = candidate_id
                    break
            if scenario_id is not None:
                break
        if scenario_id is None:
            missing.append(label)
        else:
            resolved.append((label, scenario_id))

    return resolved, missing


def _to_web_mercator(gdf):
    """Project geometry to EPSG:3857 so web tile basemaps align correctly."""
    if getattr(gdf, "crs", None) is None:
        return gdf
    try:
        return gdf.to_crs(epsg=3857)
    except Exception:
        return gdf


def _normalize_comid(df):
    out = df.copy()
    out["COMID"] = pd.to_numeric(out["COMID"], errors="coerce")
    out = out.dropna(subset=["COMID"])
    out["COMID"] = out["COMID"].astype(int)
    return out


@lru_cache(maxsize=16)
def _cached_tile_layer(basemap_label: str):
    tile_name = BASEMAP_FACTORIES.get(basemap_label)
    if not tile_name:
        return None
    tile_factory = hv_tiles.tile_sources.get(tile_name)
    if tile_factory is None:
        return None
    return tile_factory().opts(alpha=0.9)


def _apply_basemap(layer, basemap_label: str):
    tile_layer = _cached_tile_layer(basemap_label)
    if tile_layer is None:
        return layer
    return tile_layer * layer


def main():
    full_gdf = load_shapefile()
    full_gdf = _normalize_comid(full_gdf)

    conn = get_indicator_connection()
    try:
        scenarios_df = get_scenarios(conn)
        impact_chains_df = get_impact_chains(conn)
    finally:
        conn.close()

    fixed_scenarios, missing_scenarios = _resolve_fixed_scenarios(scenarios_df)

    basin_options = list_basins(full_gdf)
    default_basin = basin_options[0] if basin_options else None

    sector_values = sorted(impact_chains_df["Sector"].dropna().astype(str).unique().tolist())
    default_sector = sector_values[0] if sector_values else None

    basin_select = pn.widgets.Select(name="Basin", options=basin_options, value=default_basin)
    sector_select = pn.widgets.Select(name="Sector", options=sector_values, value=default_sector)
    ic_select = pn.widgets.Select(name="Impact Chain", options={}, value=None)
    basemap_select = pn.widgets.Select(
        name="Basemap",
        options=list(BASEMAP_FACTORIES.keys()),
        value="Carto Light",
    )

    @pn.depends(sector_select.param.value, watch=True)
    def _sync_impact_chains(_):
        sector = sector_select.value
        if sector is None:
            ic_select.options = {}
            ic_select.value = None
            return

        filtered = impact_chains_df[impact_chains_df["Sector"].astype(str) == str(sector)]
        options = {_ic_label(row): int(row["IcID"]) for _, row in filtered.iterrows()}
        ic_select.options = options
        if ic_select.value not in options.values():
            ic_select.value = next(iter(options.values())) if options else None

    _sync_impact_chains(None)

    @lru_cache(maxsize=128)
    def _load_baseline_scores(wascn_id: int, ic_id: int):
        conn = get_indicator_connection()
        try:
            out = get_baseline_scores_for_ic_scenario(
                conn=conn,
                wascn_id=wascn_id,
                ic_id=ic_id,
                user_id=USER_ID,
            )
            return _normalize_comid(out)
        finally:
            conn.close()

    @lru_cache(maxsize=128)
    def _load_basin_geometry(basin: str):
        basin_gdf = get_basin_gdf(full_gdf, basin)
        basin_gdf = _normalize_comid(basin_gdf)
        basin_gdf = _to_web_mercator(basin_gdf)
        basin_comids = tuple(sorted(basin_gdf["COMID"].unique().tolist()))
        return basin_gdf, basin_comids

    @lru_cache(maxsize=256)
    def _load_baseline_scores_for_basin(wascn_id: int, ic_id: int, basin: str):
        baseline_scores_df = _load_baseline_scores(wascn_id, ic_id)
        _, basin_comids = _load_basin_geometry(basin)
        if not basin_comids:
            return baseline_scores_df.iloc[0:0].copy()
        return baseline_scores_df[baseline_scores_df["COMID"].isin(basin_comids)].copy()

    @pn.depends(
        basin_select.param.value,
        sector_select.param.value,
        ic_select.param.value,
        basemap_select.param.value,
    )
    def _build_outputs(_basin, _sector, _ic, _basemap):
        basin = basin_select.value
        ic_id = ic_select.value
        basemap = basemap_select.value

        if basin is None or ic_id is None:
            return pn.pane.Alert("Please choose basin, sector, and impact chain.", alert_type="warning")

        if missing_scenarios:
            available_names = ", ".join(sorted(scenarios_df["WaScnName"].astype(str).tolist()))
            return pn.pane.Alert(
                "Missing required scenarios: "
                + ", ".join(missing_scenarios)
                + ". Available scenarios are: "
                + available_names,
                alert_type="danger",
            )

        basin_gdf, _ = _load_basin_geometry(str(basin))
        map_panels = []
        empty_scenarios = []

        for scenario_label, wascn_id in fixed_scenarios:
            baseline_scores_df = _load_baseline_scores_for_basin(int(wascn_id), int(ic_id), str(basin))
            if baseline_scores_df.empty:
                empty_scenarios.append(scenario_label)
                continue

            categorical_map = build_risk_category_map(
                basin_gdf=basin_gdf,
                scores_df=baseline_scores_df,
                selected_comids=None,
                risk_col="Riesgo",
                title=scenario_label,
            )
            categorical_map = _apply_basemap(categorical_map, basemap)
            map_panels.append(categorical_map)

        if not map_panels:
            return pn.pane.Alert(
                "No baseline results found for the selected basin and impact chain across the fixed scenarios.",
                alert_type="warning",
            )

        warnings = []
        if empty_scenarios:
            warnings.append(
                pn.pane.Alert(
                    "No data found for scenarios: " + ", ".join(empty_scenarios),
                    alert_type="warning",
                )
            )

        return pn.Column(
            pn.pane.Markdown("### Basin Results Viewer"),
            *warnings,
            pn.Row(*map_panels, sizing_mode="stretch_width"),
            sizing_mode="stretch_both",
        )

    controls = pn.Column(
        "## Controls",
        sector_select,
        ic_select,
        basin_select,
        basemap_select,
        sizing_mode="stretch_height",
        width=320,
    )

    template = pn.template.FastListTemplate(
        title="IKI Risk Results Viewer",
        sidebar=[controls],
        main=[_build_outputs],
        accent_base_color="#0f766e",
        header_background="#0f766e",
    )
    return template


app = main()
app.servable()
