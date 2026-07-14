from pathlib import Path

# hard code configuration
WATER_ALLOC_SCENARIO_ID = 3
PERTURBATION_LEVELS_HIGHER_BETTER = [1.0, 1.5, 2.0]
PERTURBATION_LEVELS_LOWER_BETTER = [1.0, 0.75, 0.5]

# Path configuration for the water allocation database files
user_home = Path.home()
possible_onedrive_names = [
    "Research Triangle Institute",
    "OneDrive - Research Triangle Institute",
]

one_drive_name = None
for name in possible_onedrive_names:
    if (user_home / name).exists():
        one_drive_name = name
        print("Using OneDrive path:", user_home / name)
        break

WATER_ALLOC_DB_PATH = user_home / one_drive_name / "IKI Peru Project - Interno" / "AI2b_Modelacion" / "Grupos_Modelacion" / "Resultados"
WATER_ALLOC_DBS = [
    WATER_ALLOC_DB_PATH / "BalanceHidrico.sqlite",
    WATER_ALLOC_DB_PATH / "BalanceHidrico_2.sqlite"
]
INDICATOR_DB = user_home / one_drive_name / "IKI Peru Project - Externo" / "PACA_Peru" / "Indicadores" / "BD_RiesgoClimatico_IKI.db"
SHAPEFILE_PATH = user_home / one_drive_name / "IKI Peru Project - Interno" / "AI2b_Modelacion" / "Grupos_Modelacion" / "GIS_WaterALLOC_General" / "Peru_AHD_with_districts.shp"
