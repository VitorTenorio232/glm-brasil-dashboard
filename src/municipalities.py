from __future__ import annotations

from pathlib import Path
import geopandas as gpd
import pandas as pd

AREA_CRS = 5880  # SIRGAS 2000 / Brazil Polyconic


def normalize_municipalities(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rename = {}
    candidates = {
        "code_muni": ["code_muni", "CD_MUN", "codigo_ibge"],
        "name_muni": ["name_muni", "NM_MUN", "municipio"],
        "abbrev_state": ["abbrev_state", "SIGLA_UF", "uf"],
    }
    for dst, opts in candidates.items():
        for src in opts:
            if src in gdf.columns:
                rename[src] = dst
                break
    gdf = gdf.rename(columns=rename).copy()
    required = {"code_muni", "name_muni", "abbrev_state", "geometry"}
    missing = required - set(gdf.columns)
    if missing:
        raise KeyError(f"Geometrias sem colunas necessárias: {sorted(missing)}")
    gdf["code_muni"] = gdf["code_muni"].astype(str).str.replace(r"\.0$", "", regex=True)
    if gdf.crs is None:
        gdf = gdf.set_crs(4674)
    gdf = gdf.to_crs(4326)
    area = gdf.to_crs(AREA_CRS).geometry.area / 1_000_000.0
    gdf["area_muni_km2"] = area.values
    return gdf[["code_muni", "name_muni", "abbrev_state", "area_muni_km2", "geometry"]]


def download_municipalities(year: int = 2025, simplified: bool = True) -> gpd.GeoDataFrame:
    from geobr import read_municipality
    gdf = read_municipality(code_muni="all", year=year, simplified=simplified, show_progress=True)
    return normalize_municipalities(gdf)


def save_municipalities(gdf: gpd.GeoDataFrame, out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = normalize_municipalities(gdf)
    gpkg = out_dir / "municipios_brasil.gpkg"
    geojson = out_dir / "municipios_brasil.geojson"
    shp_dir = out_dir / "municipios_shp"
    shp_dir.mkdir(exist_ok=True)
    shp = shp_dir / "municipios_brasil.shp"
    gdf.to_file(gpkg, layer="municipios", driver="GPKG")
    gdf.to_file(geojson, driver="GeoJSON")
    # nomes curtos para DBF/Shapefile
    shp_gdf = gdf.rename(columns={
        "code_muni": "code_muni",
        "name_muni": "name_muni",
        "abbrev_state": "uf",
        "area_muni_km2": "area_km2",
    })
    shp_gdf.to_file(shp, driver="ESRI Shapefile")
    import shutil
    zip_base = out_dir / "municipios_brasil_shapefile"
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=shp_dir))
    return {"gpkg": gpkg, "geojson": geojson, "shp": shp, "shp_zip": zip_path}


def load_municipalities(path: str | Path) -> gpd.GeoDataFrame:
    return normalize_municipalities(gpd.read_file(path))
