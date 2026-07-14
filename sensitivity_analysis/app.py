from functools import lru_cache

import panel as pn

from calculations import compute_baseline_and_perturbed
from config import (
    PERTURBATION_LEVELS_HIGHER_BETTER,
    PERTURBATION_LEVELS_LOWER_BETTER,
    WATER_ALLOC_SCENARIO_ID,
)
from data_access import (
    get_baseline_scores_for_ic_scenario,
    get_basin_gdf,
    get_comid_area_lookup,
    get_impact_chain_indicator_textids,
    get_impact_chains,
    get_indicator_connection,
    get_indicator_data_for_ic_scenario,
    get_scenarios,
    get_wateralloc_indicators,
    list_basins,
    list_comids_for_basin,
    load_shapefile,
)
from plots import (
    build_basin_summary_pane,
    build_category_transition_summary,
    build_percent_change_map,
    build_risk_category_map,
    build_risk_map,
    build_selected_comid_table,
)

pn.extension("tabulator")

USER_ID = 1


def _ic_label(row) -> str:
    return f"{int(row['IcID'])}: {row['ImpactChain']}"


def _scenario_label(row) -> str:
    return f"{int(row['WaScnID'])}: {row['WaScnName']}"


def _multiplier_label_html(label: str, enabled: bool) -> str:
    color = "#111827" if enabled else "#9CA3AF"
    return f'<div style="font-size:12px; color:{color}; margin-bottom:2px;">{label}</div>'


def _build_multiplier_widgets(indicators_df):
    widgets = {}
    labels = {}
    label_text = {}
    for _, row in indicators_df.iterrows():
        text_id = str(row["TextID"])
        name = str(row.get("Name", "")).strip()
        label = f"{text_id} - {name}" if name else text_id
        order = str(row["IndOrder"]).upper()

        # User-requested direction mapping:
        # ASC indicators perturb from 1 down to 0.5; DESC indicators perturb from 1 up to 2.
        if order == "ASC":
            start = min(PERTURBATION_LEVELS_LOWER_BETTER)
            end = max(PERTURBATION_LEVELS_LOWER_BETTER)
        else:
            start = min(PERTURBATION_LEVELS_HIGHER_BETTER)
            end = max(PERTURBATION_LEVELS_HIGHER_BETTER)

        widgets[text_id] = pn.widgets.FloatSlider(
            name="",
            start=float(start),
            end=float(end),
            step=0.05,
            value=1.0,
            width=220,
        )
        labels[text_id] = pn.pane.HTML(_multiplier_label_html(label, enabled=True), width=260)
        label_text[text_id] = label

    return widgets, labels, label_text


def _build_controls_column(
    multiplier_widgets,
    multiplier_labels,
    basin_select,
    comid_select,
    scenario_select,
    sector_select,
    ic_select,
):
    multiplier_items = []
    for text_id in sorted(multiplier_widgets):
        multiplier_items.append(
            pn.Column(
                multiplier_labels[text_id],
                multiplier_widgets[text_id],
                sizing_mode="stretch_width",
                margin=(0, 0, 6, 0),
            )
        )

    multiplier_box = pn.Column(
        *multiplier_items,
        sizing_mode="stretch_width",
        scroll=True,
        max_height=480,
    )

    return pn.Column(
        "## Controls",
        scenario_select,
        sector_select,
        ic_select,
        basin_select,
        comid_select,
        pn.pane.Markdown("### WaterALLOC Multipliers"),
        multiplier_box,
        sizing_mode="stretch_height",
        width=360,
    )


def main():
    full_gdf = load_shapefile()

    conn = get_indicator_connection()
    try:
        scenarios_df = get_scenarios(conn)
        impact_chains_df = get_impact_chains(conn)
        impact_chain_indicators_df = get_impact_chain_indicator_textids(conn)
        wa_indicators_df = get_wateralloc_indicators(conn)
    finally:
        conn.close()

    basin_options = list_basins(full_gdf)
    default_basin = basin_options[0] if basin_options else None

    scenario_options = {
        _scenario_label(row): int(row["WaScnID"])
        for _, row in scenarios_df.iterrows()
    }
    default_scenario = WATER_ALLOC_SCENARIO_ID
    if default_scenario not in scenario_options.values() and scenario_options:
        default_scenario = next(iter(scenario_options.values()))

    ic_options = {_ic_label(row): int(row["IcID"]) for _, row in impact_chains_df.iterrows()}
    default_ic = next(iter(ic_options.values())) if ic_options else None

    sector_values = sorted(impact_chains_df["Sector"].dropna().astype(str).unique().tolist())
    default_sector = sector_values[0] if sector_values else None

    basin_select = pn.widgets.Select(name="Basin", options=basin_options, value=default_basin)
    comid_select = pn.widgets.MultiChoice(name="COMID(s)", options=[], value=[], max_items=20)
    scenario_select = pn.widgets.Select(
        name="WaterALLOC Scenario",
        options=scenario_options,
        value=default_scenario,
    )
    sector_select = pn.widgets.Select(name="Sector", options=sector_values, value=default_sector)
    ic_select = pn.widgets.Select(name="Impact Chain", options=ic_options, value=default_ic)

    multiplier_widgets, multiplier_labels, multiplier_label_text = _build_multiplier_widgets(wa_indicators_df)

    @pn.depends(basin_select.param.value, watch=True)
    def _sync_comids(_):
        basin = basin_select.value
        if basin is None:
            comid_select.options = []
            comid_select.value = []
            return
        valid = list_comids_for_basin(full_gdf, basin)
        comid_select.options = valid
        comid_select.value = [c for c in comid_select.value if c in set(valid)]

    _sync_comids(None)

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

    @pn.depends(ic_select.param.value, watch=True)
    def _sync_multiplier_relevance(_):
        ic_id = ic_select.value
        if ic_id is None:
            for text_id, w in multiplier_widgets.items():
                w.disabled = True
                multiplier_labels[text_id].object = _multiplier_label_html(
                    multiplier_label_text[text_id],
                    enabled=False,
                )
            return

        relevant = set(
            impact_chain_indicators_df.loc[
                impact_chain_indicators_df["IcID"] == ic_id,
                "TextID",
            ]
            .astype(str)
            .tolist()
        )
        for text_id, w in multiplier_widgets.items():
            enabled = text_id in relevant
            w.disabled = not enabled
            multiplier_labels[text_id].object = _multiplier_label_html(
                multiplier_label_text[text_id],
                enabled=enabled,
            )

    _sync_multiplier_relevance(None)

    @lru_cache(maxsize=128)
    def _load_baseline_inputs(wascn_id: int, ic_id: int, basin: str):
        conn = get_indicator_connection()
        try:
            raw_df = get_indicator_data_for_ic_scenario(
                conn=conn,
                wascn_id=wascn_id,
                ic_id=ic_id,
                user_id=USER_ID,
            )
            baseline_scores_df = get_baseline_scores_for_ic_scenario(
                conn=conn,
                wascn_id=wascn_id,
                ic_id=ic_id,
                user_id=USER_ID,
            )
        finally:
            conn.close()

        basin_gdf = get_basin_gdf(full_gdf, basin)
        basin_comids = set(basin_gdf["COMID"].tolist())

        raw_basin_df = raw_df[raw_df["COMID"].isin(basin_comids)].copy()
        area_lookup_df = get_comid_area_lookup(basin_gdf)

        return basin_gdf, raw_basin_df, baseline_scores_df, area_lookup_df

    def _current_multipliers() -> dict[str, float]:
        return {text_id: float(w.value) for text_id, w in multiplier_widgets.items()}

    @pn.depends(
        basin_select.param.value,
        comid_select.param.value,
        scenario_select.param.value,
        ic_select.param.value,
        *[w.param.value for w in multiplier_widgets.values()],
    )
    def _build_outputs(_basin, _comids, _wascn, _ic, *_mult_values):
        basin = basin_select.value
        wascn_id = int(scenario_select.value)
        ic_id = int(ic_select.value)
        selected_comids = list(comid_select.value or [])
        multipliers = _current_multipliers()

        if basin is None:
            return pn.pane.Alert("No basin available.", alert_type="warning")

        basin_gdf, raw_basin_df, baseline_scores_df, area_lookup_df = _load_baseline_inputs(
            wascn_id,
            ic_id,
            basin,
        )

        if raw_basin_df.empty:
            return pn.pane.Alert(
                "No indicator data found for the current basin / scenario / impact chain selection.",
                alert_type="warning",
            )

        baseline_scores, perturbed_scores, comid_change, basin_summary = compute_baseline_and_perturbed(
            df_raw=raw_basin_df,
            baseline_scores_df=baseline_scores_df,
            selected_comids=selected_comids,
            multipliers_by_textid=multipliers,
            area_lookup_df=area_lookup_df,
        )

        risk_map = build_risk_map(
            basin_gdf=basin_gdf,
            risk_df=perturbed_scores,
            selected_comids=selected_comids,
            risk_col="Riesgo",
            title="Perturbed Risk",
        )
        pct_map = build_percent_change_map(
            basin_gdf=basin_gdf,
            change_df=comid_change,
            selected_comids=selected_comids,
            pct_col="Riesgo_PctChange",
            title="Percent Change from Baseline",
        )
        baseline_cat_map = build_risk_category_map(
            basin_gdf=basin_gdf,
            scores_df=baseline_scores,
            selected_comids=selected_comids,
            risk_col="Riesgo",
            title="Baseline Risk Categories",
        )
        perturbed_cat_map = build_risk_category_map(
            basin_gdf=basin_gdf,
            scores_df=perturbed_scores,
            selected_comids=selected_comids,
            risk_col="Riesgo",
            title="Perturbed Risk Categories",
        )

        summary_pane = build_basin_summary_pane(basin_summary)
        comid_table = build_selected_comid_table(comid_change, selected_comids)
        category_summary = build_category_transition_summary(
            baseline_scores=baseline_scores,
            perturbed_scores=perturbed_scores,
            risk_col="Riesgo",
        )

        return pn.Column(
            pn.pane.Markdown("### Absolute Risk Views"),
            pn.Row(risk_map, pct_map, sizing_mode="stretch_width"),
            pn.Row(summary_pane, sizing_mode="stretch_width"),
            pn.pane.Markdown("### Selected COMID Summary"),
            comid_table,
            pn.pane.Markdown("### Category Views"),
            pn.Row(baseline_cat_map, perturbed_cat_map, sizing_mode="stretch_width"),
            pn.Row(category_summary, sizing_mode="stretch_width"),
            sizing_mode="stretch_both",
        )

    controls = _build_controls_column(
        multiplier_widgets=multiplier_widgets,
        multiplier_labels=multiplier_labels,
        basin_select=basin_select,
        comid_select=comid_select,
        scenario_select=scenario_select,
        sector_select=sector_select,
        ic_select=ic_select,
    )

    template = pn.template.FastListTemplate(
        title="IKI Risk Sensitivity Dashboard",
        sidebar=[controls],
        main=[_build_outputs],
        accent_base_color="#146b3a",
        header_background="#146b3a",
    )
    return template


app = main()
app.servable()
