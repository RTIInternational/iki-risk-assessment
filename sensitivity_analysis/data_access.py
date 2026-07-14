import sqlite3
from pathlib import Path

import geopandas as gpd
import pandas as pd

from config import INDICATOR_DB, SHAPEFILE_PATH


def _sqlite_readonly_uri(db_path: Path) -> str:
    """Build a read-only SQLite URI for a local file path."""
    # Using URI mode keeps us from accidentally writing to the DB.
    return f"file:{db_path.as_posix()}?mode=ro"


def get_indicator_connection(db_path: Path = INDICATOR_DB) -> sqlite3.Connection:
    """Open the indicator DB in strict read-only mode."""
    conn = sqlite3.connect(_sqlite_readonly_uri(db_path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_shapefile(shapefile_path: Path = SHAPEFILE_PATH) -> gpd.GeoDataFrame:
    """Load shapefile once for map geometry and basin/COMID lookup."""
    gdf = gpd.read_file(shapefile_path)

    required_cols = {"Cuenca", "COMID"}
    missing = required_cols - set(gdf.columns)
    if missing:
        raise ValueError(f"Shapefile missing required columns: {sorted(missing)}")

    return gdf


def list_basins(gdf: gpd.GeoDataFrame) -> list[str]:
    """Return sorted basin names for dropdown options."""
    basins = gdf["Cuenca"].dropna().astype(str).unique().tolist()
    return sorted(basins)


def list_comids_for_basin(gdf: gpd.GeoDataFrame, basin: str) -> list[int]:
    """Return sorted COMIDs for one basin."""
    subset = get_basin_gdf(gdf, basin)
    comids = pd.to_numeric(subset["COMID"], errors="coerce").dropna().astype(int).tolist()
    return sorted(set(comids))


def get_basin_gdf(gdf: gpd.GeoDataFrame, basin: str) -> gpd.GeoDataFrame:
    """Return a basin-filtered GeoDataFrame."""
    return gdf.loc[gdf["Cuenca"].astype(str) == str(basin)]


def get_comid_area_lookup(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Build COMID->Area lookup used for basin area-weighted score.
    """
    out = pd.DataFrame(
        {
            "COMID": pd.to_numeric(gdf["COMID"], errors="coerce"),
            "AreaWeight": pd.to_numeric(gdf["AREASQKM"], errors="coerce"),
        }
    )
    out = out.dropna(subset=["COMID", "AreaWeight"])
    out["COMID"] = out["COMID"].astype(int)
    return out[["COMID", "AreaWeight"]].drop_duplicates("COMID")


def get_scenarios(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load available WaterALLOC scenarios for scenario selector."""
    query = """
    SELECT WaScnID, WaScnName, Description, ScnID
    FROM WaScenarios
    ORDER BY WaScnID
    """
    return pd.read_sql_query(query, conn)


def get_impact_chains(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load impact chain metadata for impact chain selector and sector display."""
    query = """
    SELECT IcID, Name AS ImpactChain, Sector
    FROM ImpactChains
    ORDER BY IcID
    """
    return pd.read_sql_query(query, conn)


def get_impact_chain_indicator_textids(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load IcID/TextID pairs used to mark relevant multipliers by impact chain."""
    query = """
    SELECT DISTINCT
        ici.IcID,
        i.TextID
    FROM ImpactChain_Indicators ici
    JOIN Indicators i ON ici.IndID = i.IndID
    ORDER BY ici.IcID, i.TextID
    """
    return pd.read_sql_query(query, conn)


def get_wateralloc_indicators(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Load unique indicators present in IndValues_WaALLOC for multiplier widgets.
    """
    query = """
    SELECT DISTINCT
        i.IndID,
        i.TextID,
        i.Name,
        i."Order" AS IndOrder
    FROM IndValues_WaALLOC wa
    JOIN Indicators i ON wa.IndID = i.IndID
    ORDER BY i.TextID
    """
    return pd.read_sql_query(query, conn)


def get_wateralloc_values_for_scenario(
    conn: sqlite3.Connection,
    wascn_id: int,
) -> pd.DataFrame:
    """Load COMID/TextID/value rows from WaterALLOC for one scenario."""
    query = """
    SELECT
        wa.COMID,
        i.TextID,
        i.Name,
        wa.Value
    FROM IndValues_WaALLOC wa
    JOIN Indicators i ON wa.IndID = i.IndID
    WHERE wa.WaScnID = ?
    """
    return pd.read_sql_query(query, conn, params=(wascn_id,))


def get_indicator_data_for_ic_scenario(
    conn: sqlite3.Connection,
    wascn_id: int,
    ic_id: int,
    user_id: int = 1,
) -> pd.DataFrame:
    """
    Return indicator values + weights for one (WaScnID, IcID, UserID).

    This mirrors the core query structure in Calculate_ImpactChains.ipynb
    and is the main input to calculations.py.
    """
    query = """
    WITH
    ScnMap AS (
        SELECT WaScnID, ScnID
        FROM WaScenarios
        WHERE WaScnID = ?
    ),
    WaVals AS (
        SELECT IndID, COMID, Value, WaScnID
        FROM IndValues_WaALLOC
        WHERE WaScnID = ?
    ),
    DynVals AS (
        SELECT ivd.IndID, ivd.COMID, ivd.Value, sm.WaScnID
        FROM IndValues_Dyn ivd
        JOIN ScnMap sm ON ivd.ScnID = sm.ScnID
    ),
    StaticVals AS (
        SELECT ivs.IndID, ivs.COMID, ivs.Value, sm.WaScnID
        FROM IndValues_Static ivs
        JOIN ScnMap sm ON 1 = 1
    ),
    AllVals AS (
        SELECT * FROM WaVals
        UNION ALL
        SELECT * FROM DynVals
        UNION ALL
        SELECT * FROM StaticVals
    )
    SELECT
        av.WaScnID,
        sm.ScnID,
        ? AS UserID,
        ici.IcID,
        ici.IndID,
        av.COMID,
        av.Value,
        iw.Factor,
        ind.TextID,
        iw.WeightValue,
        ind.Min AS IndMin,
        ind.Max AS IndMax,
        ind."Order" AS IndOrder
    FROM ImpactChain_Indicators ici
    JOIN AllVals av ON ici.IndID = av.IndID
    JOIN ScnMap sm ON av.WaScnID = sm.WaScnID
    LEFT JOIN IndicatorWeights iw
        ON ici.IndID = iw.IndID AND iw.UserID = ?
    JOIN Indicators ind
        ON ici.IndID = ind.IndID
    WHERE ici.IcID = ?
    """

    params = (wascn_id, wascn_id, user_id, user_id, ic_id)
    return pd.read_sql_query(query, conn, params=params)


def get_baseline_scores_for_ic_scenario(
    conn: sqlite3.Connection,
    wascn_id: int,
    ic_id: int,
    user_id: int = 1,
) -> pd.DataFrame:
    """
    Read baseline COMID scores from ImpactChain_Results for one scenario/impact chain/user.
    """
    query = """
    SELECT
        COMID,
        Peligro,
        Exposicion,
        VSS,
        VSB,
        VCA,
        Vulnerabilidad,
        Riesgo
    FROM ImpactChain_Results
    WHERE WaScnID = ?
      AND IcID = ?
      AND UserID = ?
    """
    return pd.read_sql_query(query, conn, params=(wascn_id, ic_id, user_id))
