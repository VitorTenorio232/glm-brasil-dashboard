"""Base histórica sintética (pequena) no formato do GLM_Process/OUTPUT, para testes sem rede nem token.

Grade de 0,08° sobre parte do Sudeste. Cada mês tem um valor fixo por célula; ``ZERO`` é um mês
observado sem relâmpagos (contagem 0) e ``AUSENTE`` não tem arquivo (sem observação).
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

LAT = np.round(np.arange(-24.0, -17.96, 0.08), 4)
LON = np.round(np.arange(-49.0, -40.96, 0.08), 4)
# Valor por célula em cada mês de 2024: março observado sem flashes, abril sem arquivo.
MESES_2024 = {1: 5.0, 2: 3.0, 3: 0.0, 5: 2.0, 6: 1.0}
ZERO, AUSENTE = 3, 4


def write_monthly(root: Path, year: int, month: int, value: float) -> Path:
    path = root / "03_MONTHLY" / f"{year}" / f"G16_GLM_FLASH_MONTHLY_{year}{month:02d}.nc"
    path.parent.mkdir(parents=True, exist_ok=True)
    shape = (1, LAT.size, LON.size)
    count = np.full(shape, value, dtype=np.float32)
    mean = np.where(count > 0, 1.0, np.nan).astype(np.float32)  # médias só onde houve flash
    with h5py.File(path, "w") as h:
        h["time"] = np.array([0], dtype=np.int32)
        h["lat"] = LAT.astype(np.float32)
        h["lon"] = LON.astype(np.float32)
        h["flash_count"] = count
        h["flash_energy"] = mean * 1e-14
        h["flash_area"] = mean * 1e8  # m²; o app converte para km²
        h["flash_duration"] = mean * 300
    return path


def build_base(root: Path) -> Path:
    for month, value in MESES_2024.items():
        write_monthly(root, 2024, month, value)
    return root
