import numpy as np
import pandas as pd
import panel as pn
import holoviews as hv

hv.extension("bokeh")


RISK_CATEGORY_ORDER = ["No data", "Low", "Half", "High", "Very high"]
RISK_CATEGORY_CODE = {"No data": -1, "Low": 0, "Half": 1, "High": 2, "Very high": 3}
RISK_CATEGORY_COLORS = {
    "No data": "#d1d5db",
    "Low": "#7fbf00",
    "Half": "#fff200",
    "High": "#ffcc00",
    "Very high": "#ff1a1a",
}


def classify_risk_category(value: float) -> str | None:
    """
    Classify risk into categories using inclusive thresholds.

    Internal classification:
    - Low: <= 0.25
    - Half: <= 0.5
    - High: <= 0.75
    - Very high: > 0.75
    """
    if pd.isna(value):
        return None
    if value <= 0.25:
        return "Low"
    if value <= 0.5:
        return "Half"
    if value <= 0.75:
        return "High"
    return "Very high"


def add_risk_category_columns(df: pd.DataFrame, risk_col: str = "Riesgo") -> pd.DataFrame:
    """Add RiskCategory and RiskCategoryCode columns derived from risk_col."""
    out = df.copy()
    out["COMID"] = pd.to_numeric(out["COMID"], errors="coerce").astype("Int64")
    out[risk_col] = pd.to_numeric(out[risk_col], errors="coerce")
    out["RiskCategory"] = out[risk_col].apply(classify_risk_category)
    out["RiskCategory"] = out["RiskCategory"].fillna("No data")
    out["RiskCategoryCode"] = out["RiskCategory"].map(RISK_CATEGORY_CODE).astype(float)
    return out


def _to_polygon_records(
    gdf: pd.DataFrame,
    value_cols: list[str] | None = None,
) -> list[dict]:
    """Convert polygon/multipolygon geometry rows to HoloViews path records."""
    value_cols = value_cols or []
    records: list[dict] = []

    for _, row in gdf.iterrows():
        geom = row.get("geometry")
        if geom is None or geom.is_empty:
            continue

        attrs = {"COMID": row.get("COMID")}
        for col in value_cols:
            attrs[col] = row.get(col)

        if geom.geom_type == "Polygon":
            polys = [geom]
        elif geom.geom_type == "MultiPolygon":
            polys = list(geom.geoms)
        else:
            continue

        for poly in polys:
            x, y = poly.exterior.xy
            rec = {
                "x": np.asarray(x, dtype=float),
                "y": np.asarray(y, dtype=float),
            }
            rec.update(attrs)
            records.append(rec)

    return records


def _prepare_map_frame(
    basin_gdf: pd.DataFrame,
    values_df: pd.DataFrame,
    value_col: str,
) -> pd.DataFrame:
    """Merge basin geometry with COMID-level values used by map layers."""
    return basin_gdf.merge(values_df[["COMID", value_col]], on="COMID", how="left")


def _build_selected_outline(
    basin_gdf: pd.DataFrame,
    selected_comids: list[int] | None,
    line_color: str = "#0b3d91",
    line_width: int = 3,
) -> hv.Polygons:
    """Create a bold outline layer for selected COMIDs."""
    selected_comids = selected_comids or []
    if not selected_comids:
        return hv.Polygons([]).opts(fill_alpha=0, line_alpha=0)

    selected_set = set(selected_comids)
    selected = basin_gdf[basin_gdf["COMID"].isin(selected_set)]

    if selected.empty:
        return hv.Polygons([]).opts(fill_alpha=0, line_alpha=0)

    selected_records = _to_polygon_records(selected)

    return hv.Polygons(selected_records, kdims=["x", "y"], vdims=["COMID"]).opts(
        fill_alpha=0,
        line_color=line_color,
        line_width=line_width,
        line_alpha=1.0,
    )


def build_risk_map(
    basin_gdf: pd.DataFrame,
    risk_df: pd.DataFrame,
    selected_comids: list[int] | None = None,
    risk_col: str = "Riesgo",
    title: str = "Risk",
) -> hv.Overlay:
    """
    Build a basin choropleth colored green(low)-to-red(high) for risk.

    Expects COMID in both inputs and risk column in risk_df.
    """
    merged = _prepare_map_frame(basin_gdf, risk_df, value_col=risk_col)
    records = _to_polygon_records(merged, value_cols=[risk_col])

    layer = hv.Polygons(records, kdims=["x", "y"], vdims=["COMID", risk_col]).opts(
        color=risk_col,
        cmap="RdYlGn_r",
        colorbar=True,
        line_color="white",
        line_width=0.3,
        tools=["hover"],
        hover_tooltips=[("COMID", "@COMID"), (risk_col, f"@{risk_col}{{0.000}}")],
        title=title,
        width=700,
        height=500,
        xaxis=None,
        yaxis=None,
        framewise=True,
    )

    return layer * _build_selected_outline(basin_gdf, selected_comids=selected_comids)


def build_percent_change_map(
    basin_gdf: pd.DataFrame,
    change_df: pd.DataFrame,
    selected_comids: list[int] | None = None,
    pct_col: str = "Riesgo_PctChange",
    title: str = "Risk Percent Change (%)",
) -> hv.Overlay:
    """
    Build a diverging choropleth for COMID-level percent change.

    Negative values are blue and positive values are red.
    """
    merged = _prepare_map_frame(basin_gdf, change_df, value_col=pct_col)
    records = _to_polygon_records(merged, value_cols=[pct_col])

    finite_vals = merged[pct_col].replace([np.inf, -np.inf], np.nan)
    max_abs = float(np.nanmax(np.abs(finite_vals))) if finite_vals.notna().any() else 1.0
    max_abs = max(max_abs, 1e-6)

    layer = hv.Polygons(records, kdims=["x", "y"], vdims=["COMID", pct_col]).opts(
        color=pct_col,
        cmap="RdBu_r",
        colorbar=True,
        clim=(-max_abs, max_abs),
        line_color="white",
        line_width=0.3,
        tools=["hover"],
        hover_tooltips=[("COMID", "@COMID"), ("Pct Change", f"@{pct_col}{{0.00}}%")],
        title=title,
        width=700,
        height=500,
        xaxis=None,
        yaxis=None,
        framewise=True,
    )

    return layer * _build_selected_outline(basin_gdf, selected_comids=selected_comids)


def build_risk_category_map(
    basin_gdf: pd.DataFrame,
    scores_df: pd.DataFrame,
    selected_comids: list[int] | None = None,
    risk_col: str = "Riesgo",
    title: str = "Risk Categories",
) -> hv.Overlay:
    """Build categorical risk map using fixed Low/Half/High/Very high bins."""
    categorized = add_risk_category_columns(scores_df, risk_col=risk_col)
    gdf = basin_gdf.copy()
    gdf["COMID"] = pd.to_numeric(gdf["COMID"], errors="coerce").astype("Int64")

    merged = gdf.merge(
        categorized[["COMID", risk_col, "RiskCategory", "RiskCategoryCode"]],
        on="COMID",
        how="left",
    )
    merged["RiskCategory"] = merged["RiskCategory"].fillna("No data")
    merged["RiskCategoryCode"] = (
        pd.to_numeric(merged["RiskCategoryCode"], errors="coerce")
        .fillna(RISK_CATEGORY_CODE["No data"])
        .astype(float)
    )

    records = _to_polygon_records(
        merged,
        value_cols=[risk_col, "RiskCategory", "RiskCategoryCode"],
    )

    # Integer category codes with fixed color mapping in ordinal order.
    layer = hv.Polygons(
        records,
        kdims=["x", "y"],
        vdims=["COMID", risk_col, "RiskCategory", "RiskCategoryCode"],
    ).opts(
        color="RiskCategoryCode",
        cmap=[RISK_CATEGORY_COLORS[k] for k in RISK_CATEGORY_ORDER],
        clim=(-1.5, 3.5),
        colorbar=False,
        line_color="white",
        line_width=0.3,
        tools=["hover"],
        hover_tooltips=[
            ("COMID", "@COMID"),
            ("Risk", f"@{risk_col}{{0.000}}"),
            ("Category", "@RiskCategory"),
        ],
        title=title,
        width=700,
        height=500,
        xaxis=None,
        yaxis=None,
        framewise=True,
    )

    return layer * _build_selected_outline(basin_gdf, selected_comids=selected_comids)


def build_category_transition_summary(
    baseline_scores: pd.DataFrame,
    perturbed_scores: pd.DataFrame,
    risk_col: str = "Riesgo",
) -> pn.pane.Markdown:
    """Summarize category movement counts between baseline and perturbed risk."""
    base = add_risk_category_columns(baseline_scores, risk_col=risk_col).rename(
        columns={
            "RiskCategory": "RiskCategory_Baseline",
            "RiskCategoryCode": "RiskCategoryCode_Baseline",
        }
    )
    pert = add_risk_category_columns(perturbed_scores, risk_col=risk_col).rename(
        columns={
            "RiskCategory": "RiskCategory_Perturbed",
            "RiskCategoryCode": "RiskCategoryCode_Perturbed",
        }
    )

    merged = base[["COMID", "RiskCategory_Baseline", "RiskCategoryCode_Baseline"]].merge(
        pert[["COMID", "RiskCategory_Perturbed", "RiskCategoryCode_Perturbed"]],
        on="COMID",
        how="inner",
    )

    if merged.empty:
        return pn.pane.Markdown("### Category Movement\nNo COMID category data available.")

    diff = merged["RiskCategoryCode_Perturbed"] - merged["RiskCategoryCode_Baseline"]
    increased = int((diff > 0).sum())
    decreased = int((diff < 0).sum())
    unchanged = int((diff == 0).sum())

    base_counts = (
        merged["RiskCategory_Baseline"]
        .value_counts()
        .reindex(RISK_CATEGORY_ORDER, fill_value=0)
    )
    pert_counts = (
        merged["RiskCategory_Perturbed"]
        .value_counts()
        .reindex(RISK_CATEGORY_ORDER, fill_value=0)
    )

    rows = "".join(
        f"<tr><td>{cat}</td><td>{int(base_counts[cat])}</td><td>{int(pert_counts[cat])}</td></tr>"
        for cat in RISK_CATEGORY_ORDER
    )

    markdown = f"""
### Category Movement

<div style="font-size: 1rem; line-height: 1.7;">
  <strong>Increased category:</strong> {increased}<br>
  <strong>Decreased category:</strong> {decreased}<br>
  <strong>Unchanged category:</strong> {unchanged}
</div>

<div style="margin-top: 10px; font-size: 0.95rem;">
  <table style="border-collapse: collapse; width: 100%;">
    <thead>
      <tr>
        <th style="text-align:left; padding:4px;">Category</th>
        <th style="text-align:right; padding:4px;">Baseline</th>
        <th style="text-align:right; padding:4px;">Perturbed</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</div>

<div style="margin-top:10px; font-size:0.85rem; color:#4b5563;">
  Category display ranges: Low (0-0.25), Half (0.2501-0.5), High (0.501-0.75), Very high (0.7501-1).
</div>
"""
    return pn.pane.Markdown(markdown, sizing_mode="stretch_width")


def build_basin_summary_pane(summary: dict[str, float]) -> pn.pane.Markdown:
    """
    Render one compact large-text basin summary widget.

    Expected keys: BaselineScore, PerturbedScore, PctChange.
    """

    def fmt_num(val: float) -> str:
        if pd.isna(val):
            return "N/A"
        return f"{val:.5g}"

    def fmt_pct(val: float) -> str:
        if pd.isna(val):
            return "N/A"
        return f"{val:+.2f}%"

    baseline = fmt_num(summary.get("BaselineScore", np.nan))
    perturbed = fmt_num(summary.get("PerturbedScore", np.nan))
    pct = fmt_pct(summary.get("PctChange", np.nan))

    markdown = f"""
### Basin Summary

<div style="font-size: 1.1rem; line-height: 1.8;">
  <strong>Baseline Basin Risk:</strong> {baseline}<br>
  <strong>With-Change Basin Risk:</strong> {perturbed}<br>
  <strong>Percent Change:</strong> {pct}
</div>
"""
    return pn.pane.Markdown(markdown, sizing_mode="stretch_width")


def build_selected_comid_table(
    comid_change_df: pd.DataFrame,
    selected_comids: list[int] | None,
) -> pn.pane.DataFrame:
    """Return a compact selected-COMID summary table pane."""
    selected_comids = selected_comids or []
    if not selected_comids:
        empty = pd.DataFrame(
            columns=["COMID", "Riesgo_Baseline", "Riesgo_Perturbed", "Riesgo_PctChange"]
        )
        return pn.pane.DataFrame(empty, index=False, sizing_mode="stretch_width", height=180)

    selected_set = {int(c) for c in selected_comids}
    out = comid_change_df[comid_change_df["COMID"].isin(selected_set)].copy()

    keep_cols = ["COMID", "Riesgo_Baseline", "Riesgo_Perturbed", "Riesgo_PctChange"]
    for col in keep_cols:
        if col not in out.columns:
            out[col] = np.nan

    out = out[keep_cols].sort_values("COMID")
    return pn.pane.DataFrame(out, index=False, sizing_mode="stretch_width", height=180)
