#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.historical_glm import HistoricalGLMRepository, SourceConfig


def main():
    parser = argparse.ArgumentParser(description="Valida a estrutura histórica do Flash View.")
    parser.add_argument("data_root", help="Caminho para GLM_Process/OUTPUT")
    args = parser.parse_args()

    repo = HistoricalGLMRepository(SourceConfig(local_root=str(Path(args.data_root).expanduser())))
    items = repo.scan()
    print(f"Arquivos reconhecidos: {len(items)}")
    for scale in ("hourly", "daily", "monthly", "yearly"):
        subset = repo.items(scale)
        print(f"  {scale:7s}: {len(subset)}")

    print("\nAnos mensais:", repo.monthly_years())
    print("Anos mensais completos:", repo.complete_monthly_years())
    print("Anos anuais:", repo.yearly_years())
    print("\nResumo:")
    print(repo.completeness_summary().to_string(index=False))

    if repo.items("monthly"):
        item = repo.items("monthly")[0]
        lat, lon, data, count = repo.read_grid(item, "flash_count")
        print("\nLeitura de teste OK:", item.relpath)
        print("Grade:", data.shape, "lat:", (lat[0], lat[-1]), "lon:", (lon[0], lon[-1]))
        print("Soma flash_count:", float(data[~__import__('numpy').isnan(data)].sum()))


if __name__ == "__main__":
    main()
