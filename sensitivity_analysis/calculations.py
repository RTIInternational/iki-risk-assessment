import numpy as np
import pandas as pd


def min_max_normalize(df: pd.DataFrame) -> pd.DataFrame:
	"""
	Apply min-max scaling and ASC/DESC direction handling.

	Adds/overwrites column ValueNorm.
	"""

	def scale(row: pd.Series) -> float:
		value = row.get("Value")
		ind_min = row.get("IndMin")
		ind_max = row.get("IndMax")

		if pd.isna(value):
			return np.nan

		denom = ind_max - ind_min
		if denom == 0:
			return 0.0

		norm = (value - ind_min) / denom
		norm = np.clip(norm, 0, 1)

		order_val = str(row.get("IndOrder", "ASC")).strip().upper()
		if order_val == "DESC":
			norm = 1 - norm

		return float(norm)

	df["ValueNorm"] = df.apply(scale, axis=1)
	return df


def compute_weighted_index(df: pd.DataFrame, factor_name: str, value_col: str = "ValueNorm") -> float:
	"""
	Compute weighted average for factor P or E.
	"""
	df_factor = df[df["Factor"] == factor_name]
	if df_factor.empty:
		return 0.0

	vals = pd.to_numeric(df_factor[value_col], errors="coerce")
	ws = pd.to_numeric(df_factor["WeightValue"], errors="coerce")

	mask = ~vals.isna()
	if not mask.any():
		return 0.0

	vals = vals[mask]
	ws = ws[mask]

	denom = ws.sum()
	if denom == 0:
		return 0.0

	return float((vals * ws).sum() / denom)


def compute_vulnerability(df: pd.DataFrame, value_col: str = "ValueNorm") -> tuple[float, float, float, float]:
	"""
	Compute vulnerability and components (VSS, VSB, VCA).
	"""
	df_v = df[df["Factor"] == "V"]
	if df_v.empty:
		return 0.0, 0.0, 0.0, 0.0

	categories = ["VSB", "VSS", "VCA"]
	results: dict[str, dict[str, float]] = {}

	textid_series = df_v["TextID"].fillna("").astype(str).str.strip().str.upper()

	for cat in categories:
		sub = df_v[textid_series.str.startswith(cat)]
		if sub.empty:
			results[cat] = {"avg": 0.0, "w_sum": 0.0}
			continue

		vals = pd.to_numeric(sub[value_col], errors="coerce")
		ws = pd.to_numeric(sub["WeightValue"], errors="coerce")

		mask = ~vals.isna()
		if not mask.any():
			results[cat] = {"avg": 0.0, "w_sum": 0.0}
			continue

		vals = vals[mask]
		ws = ws[mask]
		w_sum = ws.sum()
		avg = (vals * ws).sum() / w_sum if w_sum != 0 else 0.0

		results[cat] = {"avg": float(avg), "w_sum": float(w_sum)}

	vsb, w_vsb = results["VSB"]["avg"], results["VSB"]["w_sum"]
	vss, w_vss = results["VSS"]["avg"], results["VSS"]["w_sum"]
	vca, w_vca = results["VCA"]["avg"], results["VCA"]["w_sum"]

	denom = w_vsb + w_vss + w_vca
	if denom == 0:
		return 0.0, vss, vsb, vca

	vulnerabilidad = (vsb * w_vsb + vss * w_vss + vca * w_vca) / denom
	return float(vulnerabilidad), float(vss), float(vsb), float(vca)


def get_default_factor_weights() -> dict[str, float]:
	"""Return equal default factor weights for P, V, and E."""
	return {"P": 1 / 3, "V": 1 / 3, "E": 1 / 3}


def compute_risk(p: float, v: float, e: float, factor_weights: dict[str, float] | None = None) -> float:
	"""
	Aggregate final risk from P, V, and E using factor weights.
	"""
	fw = factor_weights or get_default_factor_weights()
	denom = fw["P"] + fw["V"] + fw["E"]
	if denom == 0:
		return float(np.mean([p, v, e]))
	return float((p * fw["P"] + v * fw["V"] + e * fw["E"]) / denom)


def compute_comid_scores(
	df: pd.DataFrame,
	factor_weights: dict[str, float] | None = None,
	value_col: str = "ValueNorm",
) -> pd.DataFrame:
	"""
	Compute P, E, VSS, VSB, VCA, Vulnerabilidad, and Riesgo by COMID.
	"""
	rows = []
	for comid, g in df.groupby("COMID"):
		p = compute_weighted_index(g, "P", value_col=value_col)
		e = compute_weighted_index(g, "E", value_col=value_col)
		v, vss, vsb, vca = compute_vulnerability(g, value_col=value_col)
		r = compute_risk(p, v, e, factor_weights=factor_weights)

		rows.append(
			{
				"COMID": comid,
				"Peligro": p,
				"Exposicion": e,
				"VSS": vss,
				"VSB": vsb,
				"VCA": vca,
				"Vulnerabilidad": v,
				"Riesgo": r,
			}
		)

	if not rows:
		return pd.DataFrame(
			columns=["COMID", "Peligro", "Exposicion", "VSS", "VSB", "VCA", "Vulnerabilidad", "Riesgo"]
		)

	out = pd.DataFrame(rows)
	out["COMID"] = pd.to_numeric(out["COMID"], errors="coerce")
	out = out.dropna(subset=["COMID"])
	out["COMID"] = out["COMID"].astype(int)
	return out


def list_missing_indicators(df: pd.DataFrame, expected_indids: list[int]) -> list[int]:
	"""
	Return expected IndIDs that are missing from the pulled dataset.
	"""
	present_indids = set(pd.to_numeric(df["IndID"], errors="coerce").dropna().astype(int).tolist())
	expected = set(expected_indids)
	return sorted(expected - present_indids)


def apply_multipliers(
    df: pd.DataFrame, 
	selected_comids: list[int],
	multipliers_by_textid: dict[str, float]
) -> pd.DataFrame:
	"""
	Apply multipliers to the Value column for selected COMIDs and TextIDs.
    """
	# check if anything needs to be perturbed
	if not selected_comids:
		return df
	if all(v == 1 for v in multipliers_by_textid.values()):
		return df
	
	mask = df["COMID"].isin(selected_comids)
	multipliers = df.loc[mask, "TextID"].map(multipliers_by_textid).fillna(1.0)
	df.loc[mask, "Value"] = pd.to_numeric(df.loc[mask, "Value"], errors="coerce") * multipliers

	return df


def add_percent_change(
    baseline_df: pd.DataFrame,
    perturbed_df: pd.DataFrame,
    value_col: str = "Riesgo",
    cap_if_baseline_zero: float = 100.0,
) -> pd.DataFrame:
	"""Add percent change column to a merged baseline/perturbed DataFrame."""
	base_col = f"{value_col}_Baseline"
	pert_col = f"{value_col}_Perturbed"
	pct_col = f"{value_col}_PctChange"
	left = baseline_df.rename(columns={value_col: base_col})
	right = perturbed_df.rename(columns={value_col: pert_col})
	out = left.merge(right, on="COMID", how="inner")

	baseline = pd.to_numeric(out[base_col], errors="coerce")
	perturbed = pd.to_numeric(out[pert_col], errors="coerce")
	out[pct_col] = np.nan

	nonzero_mask = baseline != 0
	out.loc[nonzero_mask, pct_col] = (
        (perturbed[nonzero_mask] - baseline[nonzero_mask]) / baseline[nonzero_mask]
    ) * 100.0
	zero_mask = baseline == 0

	out.loc[zero_mask & (perturbed > 0), pct_col] = cap_if_baseline_zero
	out.loc[zero_mask & (perturbed < 0), pct_col] = -cap_if_baseline_zero
	out.loc[zero_mask & (perturbed == 0), pct_col] = 0.0
	return out
	

def compute_basin_score(
	scores_df: pd.DataFrame,
	area_lookup_df: pd.DataFrame,
	risk_col: str = "Riesgo",
) -> float:
	"""
	Compute basin-level risk score.
	"""
	# merge scores iwth area weights by COMID
	merged = scores_df[["COMID", risk_col]].merge(
		area_lookup_df[["COMID", "AreaWeight"]],
		on="COMID",
		how="inner"
	)

	total_area = merged["AreaWeight"].sum()
	if total_area == 0:
		return float(np.nan)

	return float(merged[risk_col].multiply(merged["AreaWeight"]).sum() / total_area)


def compute_basin_summary(
	baseline_df: pd.DataFrame,
	perturbed_df: pd.DataFrame,
	area_lookup_df: pd.DataFrame,
	risk_col: str = "Riesgo",
	cap_if_baseline_zero: float = 100.0,
) -> dict[str, float]:
    """
    Compute basin-level summary statistics for baseline and perturbed scenarios.
    """
    baseline_score = compute_basin_score(baseline_df, area_lookup_df, risk_col=risk_col)
    perturbed_score = compute_basin_score(perturbed_df, area_lookup_df, risk_col=risk_col)

    if pd.isna(baseline_score) or pd.isna(perturbed_score):
        pct_change = float(np.nan)
    elif baseline_score == 0:
        if perturbed_score > 0:
            pct_change = cap_if_baseline_zero
        elif perturbed_score < 0:
            pct_change = -cap_if_baseline_zero
        else:
            pct_change = 0.0
    else:
        pct_change = ((perturbed_score - baseline_score) / baseline_score) * 100.0

    return {
        "BaselineScore": float(baseline_score),
        "PerturbedScore": float(perturbed_score),
        "PctChange": float(pct_change),
    }


def compute_baseline_and_perturbed(
    df_raw: pd.DataFrame,
	baseline_scores_df: pd.DataFrame,
    selected_comids: list[int],
    multipliers_by_textid: dict[str, float],
    area_lookup_df: pd.DataFrame,
    factor_weights: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, float]]:
    """
    Run full in-memory pipeline for baseline vs perturbed results.

	Returns:
	1) baseline_scores_by_comid (from DB)
    2) perturbed_scores_by_comid
    3) comid_change_df (includes percent change columns from add_percent_change)
    4) basin_summary dict (baseline, perturbed, pct change)
    """
    fw = factor_weights or get_default_factor_weights()

    # Baseline comes from DB; limit to COMIDs available in current raw dataset (current basin).
    basin_comids = set(pd.to_numeric(df_raw["COMID"], errors="coerce").dropna().astype(int).tolist())
    baseline_scores = baseline_scores_df.copy()
    baseline_scores["COMID"] = pd.to_numeric(baseline_scores["COMID"], errors="coerce")
    baseline_scores = baseline_scores.dropna(subset=["COMID"])
    baseline_scores["COMID"] = baseline_scores["COMID"].astype(int)
    baseline_scores = baseline_scores[baseline_scores["COMID"].isin(basin_comids)]

    # Perturbed path
    perturbed_raw = apply_multipliers(
        df_raw.copy(),
        selected_comids=selected_comids,
        multipliers_by_textid=multipliers_by_textid,
    )
    perturbed_df = min_max_normalize(perturbed_raw)
    perturbed_scores = compute_comid_scores(perturbed_df, factor_weights=fw, value_col="ValueNorm")

    # COMID-level percent change
    comid_change = add_percent_change(
        baseline_df=baseline_scores,
        perturbed_df=perturbed_scores,
        value_col="Riesgo",
        cap_if_baseline_zero=100.0,
    )

    # Basin-level summary
    basin_summary = compute_basin_summary(
        baseline_df=baseline_scores,
        perturbed_df=perturbed_scores,
        area_lookup_df=area_lookup_df,
        risk_col="Riesgo",
        cap_if_baseline_zero=100.0,
    )

    return baseline_scores, perturbed_scores, comid_change, basin_summary