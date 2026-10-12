#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
from shapely import make_valid

UF_INFO = {
    "AC": (12, "Acre"), "AL": (27, "Alagoas"), "AP": (16, "Amapá"),
    "AM": (13, "Amazonas"), "BA": (29, "Bahia"), "CE": (23, "Ceará"),
    "DF": (53, "Distrito Federal"), "ES": (32, "Espírito Santo"),
    "GO": (52, "Goiás"), "MA": (21, "Maranhão"), "MT": (51, "Mato Grosso"),
    "MS": (50, "Mato Grosso do Sul"), "MG": (31, "Minas Gerais"),
    "PA": (15, "Pará"), "PB": (25, "Paraíba"), "PR": (41, "Paraná"),
    "PE": (26, "Pernambuco"), "PI": (22, "Piauí"), "RJ": (33, "Rio de Janeiro"),
    "RN": (24, "Rio Grande do Norte"), "RS": (43, "Rio Grande do Sul"),
    "RO": (11, "Rondônia"), "RR": (14, "Roraima"), "SC": (42, "Santa Catarina"),
    "SP": (35, "São Paulo"), "SE": (28, "Sergipe"), "TO": (17, "Tocantins"),
}


def find_col(columns, *candidates):
    lower = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--municipalities", default="../GLM_Process/AUX/municipios_brasil_2022.gpkg")
    parser.add_argument("--output-dir", default="data/admin")
    parser.add_argument("--simplify", type=float, default=0.0025)
    args = parser.parse_args()

    src = Path(args.municipalities).expanduser().resolve()
    outdir = Path(args.output_dir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"Arquivo municipal não encontrado: {src}")

    print(f"Lendo: {src}")
    gdf = gpd.read_file(src)
    if gdf.crs is None:
        raise ValueError("A malha municipal não possui CRS.")
    gdf = gdf.to_crs(4326)

    code_col = find_col(gdf.columns, "code_muni", "cod_mun", "codigo_municipio", "cd_mun", "geocode", "ibge_code")
    name_col = find_col(gdf.columns, "name_muni", "nome_muni", "municipio", "nm_mun", "name")
    uf_col = find_col(gdf.columns, "abbrev_state", "sigla_uf", "uf", "state_abbrev")
    state_name_col = find_col(gdf.columns, "name_state", "nome_uf", "estado", "state_name", "nm_uf")
    state_code_col = find_col(gdf.columns, "code_state", "code_uf", "cod_uf", "cd_uf")

    if code_col is None or name_col is None or uf_col is None:
        raise KeyError(f"Não encontrei código/nome do município e sigla da UF. Colunas: {list(gdf.columns)}")

    muni = gdf[[code_col, name_col, uf_col, "geometry"]].copy()
    muni = muni.rename(columns={code_col: "code_muni", name_col: "name_muni", uf_col: "abbrev_state"})
    muni["code_muni"] = muni["code_muni"].astype(str).str.replace(r"\.0$", "", regex=True)
    muni["name_muni"] = muni["name_muni"].astype(str)
    muni["abbrev_state"] = muni["abbrev_state"].astype(str).str.upper()
    muni["geometry"] = muni.geometry.apply(make_valid)
    if args.simplify > 0:
        muni["geometry"] = muni.geometry.simplify(args.simplify, preserve_topology=True)
    muni = muni[muni.geometry.notna() & ~muni.geometry.is_empty].copy()
    muni = muni.drop_duplicates("code_muni").sort_values(["abbrev_state", "name_muni"]).reset_index(drop=True)

    rows = []
    for uf, group in muni.groupby("abbrev_state", sort=True):
        if uf not in UF_INFO:
            print(f"Aviso: UF não reconhecida: {uf}")
            continue
        code_state, default_name = UF_INFO[uf]
        original = gdf[gdf[uf_col].astype(str).str.upper() == uf]
        if state_name_col is not None and not original.empty:
            name_state = str(original.iloc[0][state_name_col])
        else:
            name_state = default_name
        if state_code_col is not None and not original.empty:
            try:
                code_state = int(float(original.iloc[0][state_code_col]))
            except Exception:
                pass
        geom = group.geometry.union_all() if hasattr(group.geometry, "union_all") else group.geometry.unary_union
        rows.append({"code_state": str(code_state), "abbrev_state": uf, "name_state": name_state, "geometry": make_valid(geom)})

    states = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").sort_values("name_state").reset_index(drop=True)
    country_geom = states.geometry.union_all() if hasattr(states.geometry, "union_all") else states.geometry.unary_union
    country = gpd.GeoDataFrame([{"name_country": "Brasil", "geometry": make_valid(country_geom)}], geometry="geometry", crs="EPSG:4326")

    outputs = {
        "municipalities": outdir / "municipalities_2022.parquet",
        "states": outdir / "states_2022.parquet",
        "country": outdir / "country_2022.parquet",
    }
    muni.to_parquet(outputs["municipalities"], index=False, compression="zstd")
    states.to_parquet(outputs["states"], index=False, compression="zstd")
    country.to_parquet(outputs["country"], index=False, compression="zstd")

    print("\nArquivos criados:")
    for key, path in outputs.items():
        print(f"  {key:14s}: {path} ({path.stat().st_size / 1024**2:.2f} MiB)")
    print(f"\nMunicípios: {len(muni)}")
    print(f"Estados:    {len(states)}")
    print("CRS:        EPSG:4326")


if __name__ == "__main__":
    main()
