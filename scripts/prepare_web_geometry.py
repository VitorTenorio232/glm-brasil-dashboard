#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import geopandas as gpd


def main():
    p = argparse.ArgumentParser(
        description="Cria uma malha municipal leve para visualização no Streamlit/Folium."
    )
    p.add_argument(
        "--input",
        default="data/municipalities/municipios_brasil.gpkg",
        help="Malha completa usada no processamento espacial.",
    )
    p.add_argument(
        "--output",
        default="data/municipalities/municipios_brasil_web.geojson",
        help="Arquivo simplificado usado somente no dashboard.",
    )
    p.add_argument(
        "--tolerance-m",
        type=float,
        default=1000.0,
        help="Tolerância de simplificação em metros. Padrão: 1000.",
    )
    args = p.parse_args()

    src = Path(args.input)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)

    print(f"Lendo: {src}")
    gdf = gpd.read_file(src)

    keep = [
        c for c in
        ["code_muni", "name_muni", "abbrev_state", "area_muni_km2", "geometry"]
        if c in gdf.columns
    ]
    gdf = gdf[keep].copy()

    print(f"Municípios: {len(gdf):,}")
    print(f"CRS original: {gdf.crs}")
    print(f"Simplificação: {args.tolerance_m:,.0f} m")

    projected = gdf.to_crs(5880)
    projected["geometry"] = projected.geometry.simplify(
        args.tolerance_m,
        preserve_topology=True,
    )

    projected = projected[
        projected.geometry.notna()
        & (~projected.geometry.is_empty)
    ].copy()

    web = projected.to_crs(4326)
    web.to_file(dst, driver="GeoJSON")

    mb = dst.stat().st_size / (1024 ** 2)
    print(f"Arquivo web: {dst}")
    print(f"Tamanho: {mb:.1f} MB")
    print(f"Geometrias: {len(web):,}")

    if mb > 120:
        print(
            "\nAVISO: o arquivo ainda ficou grande para o navegador. "
            "Rode novamente com --tolerance-m 2000."
        )


if __name__ == "__main__":
    main()
