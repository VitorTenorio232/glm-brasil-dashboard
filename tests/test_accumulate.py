"""scripts/accumulate_glm.py: soma das contagens e média ponderada pelo número de flashes."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr

_SPEC = importlib.util.spec_from_file_location(
    "accumulate_glm", Path(__file__).resolve().parents[1] / "scripts" / "accumulate_glm.py"
)
acc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(acc)


def _daily(path: Path, day: datetime, count, energy):
    count = np.array(count, dtype="float32")[None, None, :]
    energy = np.array(energy, dtype="float32")[None, None, :]
    nan = np.full_like(count, np.nan)
    ds = xr.Dataset(
        {"flash_count": (("time", "lat", "lon"), count),
         "flash_energy": (("time", "lat", "lon"), energy),
         "flash_area": (("time", "lat", "lon"), np.where(count > 0, 1.0e8, nan)),
         "flash_duration": (("time", "lat", "lon"), np.where(count > 0, 0.5, nan))},
        coords={"time": [np.datetime64(day, "ns")], "lat": [-20.0], "lon": [-50.0, -49.92, -49.84]},
    )
    ds.to_netcdf(path)
    return path


def test_soma_e_media_ponderada(tmp_path):
    files = [
        _daily(tmp_path / "G16_GLM_FLASH_DAILY_20250406.nc", datetime(2025, 4, 6), [1, 0, 3], [10.0, np.nan, 2.0]),
        _daily(tmp_path / "G19_GLM_FLASH_DAILY_20250407.nc", datetime(2025, 4, 7), [3, 0, 0], [2.0, np.nan, np.nan]),
        _daily(tmp_path / "G19_GLM_FLASH_DAILY_20250408.nc", datetime(2025, 4, 8), [0, 0, 1], [np.nan, np.nan, 6.0]),
    ]
    arrays, template = acc.accumulate(files)
    np.testing.assert_array_equal(arrays["flash_count"][0], [4, 0, 4])
    # (1×10 + 3×2) / 4 = 4 ; célula sem flash = NaN ; (3×2 + 1×6) / 4 = 3
    np.testing.assert_allclose(arrays["flash_energy"][0], [4.0, np.nan, 3.0])
    assert acc.satellite_prefix(files) == "G19"  # 2 arquivos G19 contra 1 G16

    target = tmp_path / "out" / "G19_GLM_FLASH_MONTHLY_202504.nc"
    acc.write_product(arrays, template, files, "monthly", datetime(2025, 4, 1), target)
    with xr.open_dataset(target) as ds:
        assert ds.flash_count.attrs["units"] == "count/month/64km2"
        assert ds.attrs["satellites"] == "G16, G19"
        assert str(ds.time.values[0])[:10] == "2025-04-01"
