from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd


_MUNI_COLS = ["code_muni", "name_muni", "abbrev_state", "area_muni_km2"]


def _one_match_per_flash(joined: gpd.GeoDataFrame, row_id: str = "_flash_row_id") -> gpd.GeoDataFrame:
    """Collapse spatial-join duplicates so each input flash appears at most once.

    A point can intersect more than one polygon because of shared boundaries or
    tiny topology overlaps in a municipal layer. Prefer a matched municipality
    and use the municipal code as a deterministic tie-breaker.
    """
    if joined.empty:
        return joined

    out = joined.copy()
    out["_matched"] = out["code_muni"].notna().astype("int8")
    out["_code_sort"] = out["code_muni"].astype("string").fillna("~")
    out = (
        out.sort_values([row_id, "_matched", "_code_sort"], ascending=[True, False, True])
        .drop_duplicates(subset=[row_id], keep="first")
        .drop(columns=["_matched", "_code_sort"], errors="ignore")
    )
    return out


def assign_flashes_to_municipalities(
    flashes: pd.DataFrame,
    municipalities: gpd.GeoDataFrame,
) -> pd.DataFrame:
    if flashes.empty:
        return flashes.copy()

    base = flashes.reset_index(drop=True).copy()
    base["_flash_row_id"] = np.arange(len(base), dtype="int64")

    pts = gpd.GeoDataFrame(
        base,
        geometry=gpd.points_from_xy(base["lon"], base["lat"]),
        crs="EPSG:4326",
    )

    muni = municipalities.to_crs("EPSG:4326")[
        _MUNI_COLS + ["geometry"]
    ].copy()

    # Primeiro, associação estrita: o ponto deve estar dentro do município.
    joined = gpd.sjoin(pts, muni, how="left", predicate="within")
    joined = _one_match_per_flash(joined)

    # Pontos exatamente sobre limites municipais não satisfazem "within".
    # Refazemos somente esses pontos com "intersects". O filtro usa IDs das
    # linhas originais, nunca uma máscara criada sobre o resultado do sjoin.
    missing_ids = joined.loc[joined["code_muni"].isna(), "_flash_row_id"].to_numpy()

    if len(missing_ids):
        retry_pts = pts[pts["_flash_row_id"].isin(missing_ids)].copy()
        retry = gpd.sjoin(retry_pts, muni, how="left", predicate="intersects")
        retry = _one_match_per_flash(retry)
        retry = retry.set_index("_flash_row_id")

        joined = joined.set_index("_flash_row_id")
        for col in _MUNI_COLS:
            joined.loc[missing_ids, col] = retry[col].reindex(missing_ids).to_numpy()
        joined = joined.reset_index()

    # Restaura exatamente a ordem e o número de flashes da entrada.
    joined = joined.sort_values("_flash_row_id")
    if len(joined) != len(base):
        raise RuntimeError(
            "Spatial join alterou o número de flashes: "
            f"entrada={len(base):,}, saída={len(joined):,}."
        )

    return pd.DataFrame(
        joined.drop(
            columns=["geometry", "index_right", "_flash_row_id"],
            errors="ignore",
        )
    ).reset_index(drop=True)
