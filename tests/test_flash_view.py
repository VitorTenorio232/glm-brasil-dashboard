from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import h5py
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.alertas_flash import analyze_glm_activity
from src.glm_reader import read_glm_file
from src.historical_glm import anomaly_range


def _write_fake_lcfa(path: Path) -> None:
    """Arquivo no formato do GLM-L2-LCFA: int16 '_Unsigned', _FillValue e scale/offset."""
    raw_time = np.array([13107, 26214, -1], dtype=np.int16)  # -1 = 65535 sem sinal
    time_attrs = {
        "scale_factor": np.array([0.00038147560553625226], dtype=np.float32),
        "add_offset": np.array([-5.0], dtype=np.float32),
        "_Unsigned": b"true",
        "units": b"seconds since 2026-10-26 20:57:00.000",
    }
    with h5py.File(path, "w") as h:
        h["flash_lat"] = np.array([-15.0, -20.5, -3.25], dtype=np.float32)
        h["flash_lon"] = np.array([-47.9, -43.2, -60.0], dtype=np.float32)
        h["flash_id"] = np.array([1, 2, -1], dtype=np.int16)
        h["flash_id"].attrs["_Unsigned"] = b"true"
        for name in ("flash_time_offset_of_first_event", "flash_time_offset_of_last_event"):
            h[name] = raw_time
            h[name].attrs.update(time_attrs)
        h["flash_area"] = np.array([10, -1, 20], dtype=np.int16)
        h["flash_area"].attrs.update({"_FillValue": np.array([-1], dtype=np.int16),
                                      "scale_factor": np.array([152601.859375], dtype=np.float32),
                                      "_Unsigned": b"true", "units": b"m2"})
        h["flash_quality_flag"] = np.array([0, 0, 1], dtype=np.int16)
        h["flash_quality_flag"].attrs.update({"_FillValue": np.array([-1], dtype=np.int16),
                                              "_Unsigned": b"true"})


def test_h5py_reader_decodes_cf_packing(tmp_path):
    path = tmp_path / "OR_GLM-L2-LCFA_fake.nc"
    _write_fake_lcfa(path)
    df = read_glm_file(path, quality="all")

    assert list(df["flash_id"]) == [1, 2, 65535]  # _Unsigned aplicado
    assert np.isnan(df.loc[1, "area_km2"])  # _FillValue vira NaN
    assert np.isclose(df.loc[0, "area_km2"], 152601.859375 * 10 / 1e6)
    base = pd.Timestamp("2026-10-26 20:57:00", tz="UTC")
    expected = base + pd.to_timedelta(13107 * np.float32(0.00038147560553625226) - 5.0, unit="s")
    assert abs(df.loc[0, "time_start"] - expected) < pd.Timedelta("1us")
    # 65535 sem sinal: offset positivo (~20 s), não negativo
    assert df.loc[2, "time_start"] > base + pd.Timedelta(seconds=19)

    assert len(read_glm_file(path, quality="zero_only")) == 2


def test_anomaly_range_is_symmetric():
    lo, hi = anomaly_range(np.array([-3.0, 1.0, 2.0, np.nan]))
    assert lo == -hi and hi > 0
    assert anomaly_range(np.zeros(4)) == (-1.0, 1.0)


def test_activity_trend_windows():
    end = datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc)
    times = ([end - timedelta(minutes=2)] * 12 + [end - timedelta(minutes=15)] * 4)
    summary = analyze_glm_activity(pd.DataFrame({"time_start": times}), end, latency_minutes=1)
    assert (summary.latest_10min, summary.previous_10min) == (12, 4)
    assert summary.trend.startswith("Intensificação")
    assert summary.delta_percent == 200
