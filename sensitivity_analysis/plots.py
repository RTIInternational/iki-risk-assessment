import numpy as np
import pandas as pd
import panel as pn
import holoviews as hv

hv.extension("bokeh")


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
