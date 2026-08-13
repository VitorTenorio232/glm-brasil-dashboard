from __future__ import annotations

from pathlib import Path
import pandas as pd


def parquet_available() -> bool:
    try:
        import pyarrow  # noqa
        return True
    except Exception:
        return False


def save_table(df: pd.DataFrame, base: str | Path) -> Path:
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    if parquet_available():
        path = base.with_suffix(".parquet")
        df.to_parquet(path, index=False)
    else:
        path = base.with_suffix(".csv")
        df.to_csv(path, index=False)
    return path


def load_table(base: str | Path) -> pd.DataFrame:
    base = Path(base)
    p = base if base.suffix else base.with_suffix(".parquet")
    if p.exists() and p.suffix == ".parquet":
        return pd.read_parquet(p)
    if not base.suffix:
        csv = base.with_suffix(".csv")
        if csv.exists():
            return pd.read_csv(csv)
    if base.exists() and base.suffix == ".csv":
        return pd.read_csv(base)
    raise FileNotFoundError(f"Tabela não encontrada: {base}")


def save_products(products: dict[str, pd.DataFrame], out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {name: save_table(df, out_dir / name) for name, df in products.items()}
