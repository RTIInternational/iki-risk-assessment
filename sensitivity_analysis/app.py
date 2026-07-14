from functools import lru_cache

import pandas as pd
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
    get_wateralloc_values_for_scenario,
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


def _multiplier_value_html(baseline_value: float | None, enabled: bool) -> str:
    color = "#111827" if enabled else "#9CA3AF"
    if baseline_value is None or pd.isna(baseline_value):
        value_text = "baseline: N/A"
    else:
        value_text = f"baseline: {baseline_value:.5g}"

    return (
        f'<div style="font-size:12px; color:{color}; min-width:120px; text-align:right; line-height:1.2;">'
        f"{value_text}"
        "</div>"
    )


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
            width=300,
        )
        labels[text_id] = pn.pane.HTML(_multiplier_label_html(label, enabled=True), width=260)
        label_text[text_id] = label

    return widgets, labels, label_text


def _build_controls_column(
    multiplier_widgets,
    multiplier_labels,
    apply_changes_button,
    reset_multipliers_button,
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
        apply_changes_button,
        reset_multipliers_button,
        multiplier_box,
        sizing_mode="stretch_height",
        width=360,
    )


def _build_indicator_summary_table(
    wateralloc_df: pd.DataFrame,
    selected_comid: int | None,
    multipliers: dict[str, float],
    indicator_name_by_textid: dict[str, str],
    relevant_textids: set[str],
) -> pn.pane.DataFrame:
    cols = ["Indicator", "Multiplier", "BaseValue", "UpdatedValue"]
    if selected_comid is None:
        return pn.pane.DataFrame(pd.DataFrame(columns=cols), index=False, sizing_mode="stretch_width", height=220)

    subset = wateralloc_df[wateralloc_df["COMID"] == selected_comid].copy()
    if subset.empty:
        return pn.pane.DataFrame(pd.DataFrame(columns=cols), index=False, sizing_mode="stretch_width", height=220)

    subset["Value"] = pd.to_numeric(subset["Value"], errors="coerce")
    base_by_textid = subset.groupby("TextID")["Value"].mean()

    rows = []
    for text_id in sorted(relevant_textids):
        if text_id not in multipliers:
            continue
        mult = float(multipliers[text_id])
        base_val = base_by_textid.get(text_id, pd.NA)
        if pd.isna(base_val):
            updated = pd.NA
        else:
            updated = float(base_val) * mult

        name = indicator_name_by_textid.get(text_id, "")
        indicator_label = f"{text_id} - {name}" if name else text_id
        rows.append(
            {
                "Indicator": indicator_label,
                "Multiplier": mult,
                "BaseValue": base_val,
                "UpdatedValue": updated,
            }
        )

    out = pd.DataFrame(rows, columns=cols)
    return pn.pane.DataFrame(out, index=False, sizing_mode="stretch_width", height=220)


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
    table_comid_select = pn.widgets.Select(name="Table COMID", options=[], value=None)

    multiplier_widgets, multiplier_labels, multiplier_label_text = _build_multiplier_widgets(wa_indicators_df)
    apply_changes_button = pn.widgets.Button(
        name="Apply Changes",
        button_type="primary",
        width=180,
    )
    reset_multipliers_button = pn.widgets.Button(
        name="Reset All Multipliers",
        button_type="default",
        width=180,
    )

    indicator_name_by_textid = {
        str(row["TextID"]): str(row.get("Name", "")).strip()
        for _, row in wa_indicators_df.iterrows()
    }

    applied_multipliers = {text_id: 1.0 for text_id in multiplier_widgets}

    def _capture_applied_multipliers(_event=None):
        for text_id, slider in multiplier_widgets.items():
            applied_multipliers[text_id] = float(slider.value)

    apply_changes_button.on_click(_capture_applied_multipliers)

    def _reset_all_multipliers(_event):
        for slider in multiplier_widgets.values():
            slider.value = 1.0
        _capture_applied_multipliers()
        apply_changes_button.param.trigger("clicks")

    reset_multipliers_button.on_click(_reset_all_multipliers)

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

        selected = list(comid_select.value)
        if selected:
            table_comid_select.options = selected
            if table_comid_select.value not in selected:
                table_comid_select.value = selected[0]
            table_comid_select.disabled = len(selected) <= 1
        else:
            table_comid_select.options = []
            table_comid_select.value = None
            table_comid_select.disabled = True

    _sync_comids(None)

    @pn.depends(comid_select.param.value, watch=True)
    def _sync_table_comid(_):
        selected = list(comid_select.value or [])
        if selected:
            table_comid_select.options = selected
            if table_comid_select.value not in selected:
                table_comid_select.value = selected[0]
            table_comid_select.disabled = len(selected) <= 1
        else:
            table_comid_select.options = []
            table_comid_select.value = None
            table_comid_select.disabled = True

    _sync_table_comid(None)

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
                w.visible = False
                multiplier_labels[text_id].visible = False
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
            w.visible = enabled
            multiplier_labels[text_id].visible = enabled
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
            wateralloc_df = get_wateralloc_values_for_scenario(
                conn=conn,
                wascn_id=wascn_id,
            )
        finally:
            conn.close()

        basin_gdf = get_basin_gdf(full_gdf, basin)
        basin_comids = set(basin_gdf["COMID"].tolist())

        raw_basin_df = raw_df[raw_df["COMID"].isin(basin_comids)].copy()
        wateralloc_basin_df = wateralloc_df[wateralloc_df["COMID"].isin(basin_comids)].copy()
        area_lookup_df = get_comid_area_lookup(basin_gdf)

        return basin_gdf, raw_basin_df, baseline_scores_df, area_lookup_df, wateralloc_basin_df

    def _current_multipliers() -> dict[str, float]:
        return applied_multipliers.copy()

    @pn.depends(
        basin_select.param.value,
        comid_select.param.value,
        scenario_select.param.value,
        ic_select.param.value,
        table_comid_select.param.value,
        apply_changes_button.param.clicks,
    )
    def _build_outputs(_basin, _comids, _wascn, _ic, _table_comid, _apply_clicks):
        basin = basin_select.value
        wascn_id = int(scenario_select.value)
        ic_id = int(ic_select.value)
        selected_comids = list(comid_select.value or [])
        selected_table_comid = table_comid_select.value
        multipliers = _current_multipliers()
        relevant_textids = set(
            impact_chain_indicators_df.loc[
                impact_chain_indicators_df["IcID"] == ic_id,
                "TextID",
            ]
            .astype(str)
            .tolist()
        )

        if basin is None:
            return pn.pane.Alert("No basin available.", alert_type="warning")

        basin_gdf, raw_basin_df, baseline_scores_df, area_lookup_df, wateralloc_basin_df = _load_baseline_inputs(
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
        indicator_summary_table = _build_indicator_summary_table(
            wateralloc_df=wateralloc_basin_df,
            selected_comid=selected_table_comid,
            multipliers=multipliers,
            indicator_name_by_textid=indicator_name_by_textid,
            relevant_textids=relevant_textids,
        )
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
            pn.pane.Markdown("### Indicator Multiplier Summary"),
            table_comid_select,
            indicator_summary_table,
            pn.pane.Markdown("### Category Views"),
            pn.Row(baseline_cat_map, perturbed_cat_map, sizing_mode="stretch_width"),
            pn.Row(category_summary, sizing_mode="stretch_width"),
            sizing_mode="stretch_both",
        )

    controls = _build_controls_column(
        multiplier_widgets=multiplier_widgets,
        multiplier_labels=multiplier_labels,
        apply_changes_button=apply_changes_button,
        reset_multipliers_button=reset_multipliers_button,
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
