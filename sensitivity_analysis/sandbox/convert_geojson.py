from pathlib import Path

import geopandas as gpd


def main() -> None:
	input_shp = Path(
		r"C:\Users\sarahjordan\Research Triangle Institute\IKI Peru Project - Interno\AI2b_Modelacion\Grupos_Modelacion\GIS_WaterALLOC_General\Peru_AHD_with_districts.shp"
	)
	output_geojson = Path(__file__).resolve().parent / "Peru_AHD_with_districts.geojson"

	if not input_shp.exists():
		raise FileNotFoundError(f"Shapefile not found: {input_shp}")

	gdf = gpd.read_file(input_shp)

	# GeoJSON is typically expected in WGS84 coordinates.
	if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
		gdf = gdf.to_crs(epsg=4326)

	gdf.to_file(output_geojson, driver="GeoJSON")
	print(f"GeoJSON saved to: {output_geojson}")


if __name__ == "__main__":
	main()
