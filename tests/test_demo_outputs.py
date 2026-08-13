from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]/"data"/"demo"/"processed"

def read(name):
    p=ROOT/f"{name}.parquet"
    if p.exists(): return pd.read_parquet(p)
    return pd.read_csv(ROOT/f"{name}.csv")


def test_demo_monthly_shape():
    df=read("monthly")
    assert df.code_muni.nunique()==3
    assert len(df)==72
    assert (df.flash_density_km2>0).all()


def test_demo_climatology_and_anomalies():
    clim=read("monthly_climatology")
    anom=read("monthly_anomalies")
    assert len(clim)==36
    assert "flash_count_z" in anom.columns
