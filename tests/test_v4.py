from pathlib import Path
import sys
import pandas as pd
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.v4_repository import FlashesRepository
from src.v4_analysis import calculate_analysis, filter_by_geometry

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo" / "processed"


def test_v4_repository_demo_range_and_city_filter():
    repo = FlashesRepository(processed=DEMO, partitioned=ROOT / "data" / "does_not_exist")
    tmin, tmax = repo.available_range()
    assert tmin.year == 2024
    assert tmax.year == 2025
    df = repo.load(code_muni="9990001")
    assert not df.empty
    assert df["code_muni"].astype(str).eq("9990001").all()


def test_v4_monthly_climatology_has_all_12_months_and_profile():
    repo = FlashesRepository(processed=DEMO, partitioned=ROOT / "data" / "does_not_exist")
    df = repo.load(code_muni="9990001")
    start, end = repo.available_range()
    p = calculate_analysis(df, start=start, end=end, selection_area_km2=1100.0, utc_offset_hours=-3)
    assert len(p.monthly_climatology) == 12
    assert len(p.municipality_months) == 12
    assert set(p.municipality_months["month"]) == set(range(1, 13))
    assert p.summary["flash_count"] == df.loc[df["time_start"].notna(), "flash_uid"].nunique()


def test_v4_state_and_municipal_rankings():
    repo = FlashesRepository(processed=DEMO, partitioned=ROOT / "data" / "does_not_exist")
    df = repo.load()
    start, end = repo.available_range()
    p = calculate_analysis(df, start=start, end=end, selection_area_km2=3300.0, utc_offset_hours=0)
    assert not p.ranking_states.empty
    assert not p.ranking_municipalities.empty
    assert p.ranking_municipalities["flash_count"].sum() == df.loc[df["time_start"].notna(), "flash_uid"].nunique()


def test_v4_custom_polygon_filters_points():
    repo = FlashesRepository(processed=DEMO, partitioned=ROOT / "data" / "does_not_exist")
    df = repo.load()
    # A caixa cobre a região dos municípios sintéticos, mas não pontos externos distantes.
    geom = box(-47.0, -22.0, -42.0, -18.0)
    sub = filter_by_geometry(df, geom)
    assert 0 < len(sub) <= len(df)
    assert sub["lon"].between(-47.0, -42.0).all()
    assert sub["lat"].between(-22.0, -18.0).all()
