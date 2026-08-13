from __future__ import annotations

from pathlib import Path
import os
import pandas as pd

from .config import PROCESSED_DIR, DATA_DIR


def _normalize_code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def processed_dir() -> Path:
    custom = os.getenv("GLM_PROCESSED_DIR")
    if custom:
        return Path(custom)
    if (PROCESSED_DIR / "flashes_enriched.parquet").exists() or (PROCESSED_DIR / "flashes_enriched.csv").exists():
        return PROCESSED_DIR
    return Path(__file__).resolve().parents[1] / "data" / "demo" / "processed"


def flashes_dir() -> Path:
    return Path(os.getenv("GLM_FLASHES_DIR", DATA_DIR / "flashes"))


class FlashesRepository:
    """Consulta a base primária de flashes individuais.

    Prioridade:
      1. processed/flashes_enriched.parquet
      2. processed/flashes_enriched.csv
      3. data/flashes/**/*.parquet (histórico particionado)

    Para bases Parquet, DuckDB é usado para aplicar filtros antes de materializar
    o DataFrame em memória.
    """

    def __init__(self, processed: str | Path | None = None, partitioned: str | Path | None = None):
        self.processed = Path(processed) if processed else processed_dir()
        self.partitioned = Path(partitioned) if partitioned else flashes_dir()

    @property
    def parquet_file(self) -> Path:
        return self.processed / "flashes_enriched.parquet"

    @property
    def csv_file(self) -> Path:
        return self.processed / "flashes_enriched.csv"

    def source_description(self) -> str:
        if self.parquet_file.exists():
            return str(self.parquet_file)
        if self.csv_file.exists():
            return str(self.csv_file)
        if self.partitioned.exists() and any(self.partitioned.rglob("*.parquet")):
            return str(self.partitioned / "**" / "*.parquet")
        return "indisponível"

    def exists(self) -> bool:
        return (
            self.parquet_file.exists()
            or self.csv_file.exists()
            or (self.partitioned.exists() and any(self.partitioned.rglob("*.parquet")))
        )

    def _read_parquet_duckdb(
        self,
        path_or_glob: str,
        *,
        start=None,
        end=None,
        code_muni: str | None = None,
        state: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        columns: list[str] | None = None,
        hive_partitioning: bool = False,
    ) -> pd.DataFrame:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("DuckDB é necessário para consultar Parquet no V4.") from exc

        select = "*" if not columns else ", ".join(f'"{c}"' for c in columns)
        source = "read_parquet(?, hive_partitioning=true)" if hive_partitioning else "read_parquet(?)"
        where = []
        params: list[object] = [path_or_glob]

        if start is not None:
            where.append("time_start >= ?")
            params.append(pd.Timestamp(start).to_pydatetime())
        if end is not None:
            # inclusive no dashboard: acrescenta microssegundo se necessário fora daqui.
            where.append("time_start <= ?")
            params.append(pd.Timestamp(end).to_pydatetime())
        if code_muni:
            where.append("regexp_replace(CAST(code_muni AS VARCHAR), '\\.0$', '') = ?")
            params.append(str(code_muni).replace(".0", ""))
        if state:
            where.append("CAST(abbrev_state AS VARCHAR) = ?")
            params.append(str(state))
        if bbox is not None:
            minx, miny, maxx, maxy = bbox
            where.extend(["lon >= ?", "lon <= ?", "lat >= ?", "lat <= ?"])
            params.extend([float(minx), float(maxx), float(miny), float(maxy)])

        sql = f"SELECT {select} FROM {source}"
        if where:
            sql += " WHERE " + " AND ".join(where)

        con = duckdb.connect(database=":memory:")
        try:
            return con.execute(sql, params).df()
        finally:
            con.close()

    def load(
        self,
        *,
        start=None,
        end=None,
        code_muni: str | None = None,
        state: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        if self.parquet_file.exists():
            df = self._read_parquet_duckdb(
                str(self.parquet_file), start=start, end=end, code_muni=code_muni,
                state=state, bbox=bbox, columns=columns,
            )
        elif self.csv_file.exists():
            df = pd.read_csv(self.csv_file, usecols=columns)
            df["time_start"] = pd.to_datetime(df["time_start"], utc=True, errors="coerce")
            if start is not None:
                df = df[df["time_start"] >= pd.Timestamp(start)]
            if end is not None:
                df = df[df["time_start"] <= pd.Timestamp(end)]
            if code_muni and "code_muni" in df:
                df = df[_normalize_code(df["code_muni"]) == str(code_muni).replace(".0", "")]
            if state and "abbrev_state" in df:
                df = df[df["abbrev_state"].astype(str) == str(state)]
            if bbox is not None:
                minx, miny, maxx, maxy = bbox
                df = df[df["lon"].between(minx, maxx) & df["lat"].between(miny, maxy)]
        elif self.partitioned.exists() and any(self.partitioned.rglob("*.parquet")):
            df = self._read_parquet_duckdb(
                str(self.partitioned / "**" / "*.parquet"), start=start, end=end,
                code_muni=code_muni, state=state, bbox=bbox, columns=columns,
                hive_partitioning=True,
            )
        else:
            raise FileNotFoundError(
                "Flashes individuais não encontrados. Rode process_glm.py com --save-flashes "
                "ou use o pipeline particionado em data/flashes/."
            )

        if df.empty:
            return df
        if "time_start" in df:
            df["time_start"] = pd.to_datetime(df["time_start"], utc=True, errors="coerce")
        if "time_end" in df:
            df["time_end"] = pd.to_datetime(df["time_end"], utc=True, errors="coerce")
        if "code_muni" in df:
            df["code_muni"] = _normalize_code(df["code_muni"])
        return df.reset_index(drop=True)

    def available_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Retorna min/max sem materializar todos os timestamps de Parquet."""
        if self.parquet_file.exists():
            import duckdb
            con = duckdb.connect(database=":memory:")
            try:
                row = con.execute(
                    "SELECT min(time_start), max(time_start) FROM read_parquet(?)",
                    [str(self.parquet_file)],
                ).fetchone()
            finally:
                con.close()
            tmin, tmax = row
        elif self.csv_file.exists():
            df = pd.read_csv(self.csv_file, usecols=["time_start"])
            t = pd.to_datetime(df["time_start"], utc=True, errors="coerce").dropna()
            if t.empty:
                raise ValueError("A base não contém horários GLM válidos.")
            return t.min(), t.max()
        elif self.partitioned.exists() and any(self.partitioned.rglob("*.parquet")):
            import duckdb
            con = duckdb.connect(database=":memory:")
            try:
                row = con.execute(
                    "SELECT min(time_start), max(time_start) FROM read_parquet(?, hive_partitioning=true)",
                    [str(self.partitioned / "**" / "*.parquet")],
                ).fetchone()
            finally:
                con.close()
            tmin, tmax = row
        else:
            raise FileNotFoundError("Nenhuma base de flashes individuais disponível.")

        if tmin is None or tmax is None:
            raise ValueError("A base não contém horários GLM válidos.")
        return (
            pd.Timestamp(tmin).tz_localize("UTC") if pd.Timestamp(tmin).tzinfo is None else pd.Timestamp(tmin).tz_convert("UTC"),
            pd.Timestamp(tmax).tz_localize("UTC") if pd.Timestamp(tmax).tzinfo is None else pd.Timestamp(tmax).tz_convert("UTC"),
        )
