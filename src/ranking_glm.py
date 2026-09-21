from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os
import re

import pandas as pd

from .historical_glm import SourceConfig


_RANK_RE = re.compile(
    r"(?:^|/)05_RANKINGS/GLM_RANKING_(MUNICIPAL|STATE)_(MONTHLY|YEARLY)_.*\.parquet$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RankingFile:
    level: str
    scale: str
    relpath: str


class RankingRepository:
    """Consulta produtos administrativos pré-processados do Flash View."""

    def __init__(self, config: SourceConfig):
        if config.mode == "none":
            raise ValueError("Fonte histórica não configurada.")
        self.config = config
        self._files: list[str] | None = None

    def _list_files(self) -> list[str]:
        if self._files is not None:
            return list(self._files)

        if self.config.mode == "local":
            root = Path(self.config.local_root).expanduser().resolve()
            self._files = [p.relative_to(root).as_posix() for p in root.rglob("*.parquet")]
        else:
            from huggingface_hub import HfApi

            token = os.getenv(self.config.hf_token_env) or None
            api = HfApi(token=token)
            files = api.list_repo_files(self.config.hf_repo, repo_type="dataset")
            prefix = self.config.hf_prefix.strip("/")
            if prefix:
                ps = prefix + "/"
                files = [f[len(ps):] for f in files if f.startswith(ps)]
            self._files = list(files)
        return list(self._files)

    def scan(self) -> list[RankingFile]:
        out = []
        for rel in self._list_files():
            rel = PurePosixPath(rel).as_posix()
            m = _RANK_RE.search(rel)
            if not m:
                continue
            level = "municipality" if m.group(1).upper() == "MUNICIPAL" else "state"
            scale = m.group(2).lower()
            out.append(RankingFile(level, scale, rel))
        return out

    def available(self, level: str, scale: str) -> bool:
        return any(x.level == level and x.scale == scale for x in self.scan())

    def _select(self, level: str, scale: str) -> RankingFile:
        matches = [x for x in self.scan() if x.level == level and x.scale == scale]
        if not matches:
            raise FileNotFoundError(
                f"Produto de ranking {level}/{scale} não encontrado em 05_RANKINGS."
            )
        # Se houver mais de um, usa o nome lexicograficamente mais recente.
        return sorted(matches, key=lambda x: x.relpath)[-1]

    def materialize(self, relpath: str) -> Path:
        if self.config.mode == "local":
            path = Path(self.config.local_root).expanduser().resolve() / relpath
            if not path.exists():
                raise FileNotFoundError(path)
            return path

        from huggingface_hub import hf_hub_download

        prefix = self.config.hf_prefix.strip("/")
        remote = f"{prefix}/{relpath}" if prefix else relpath
        token = os.getenv(self.config.hf_token_env) or None
        return Path(hf_hub_download(
            repo_id=self.config.hf_repo,
            repo_type="dataset",
            filename=remote,
            token=token,
        ))

    def load(self, level: str, scale: str) -> pd.DataFrame:
        item = self._select(level, scale)
        return pd.read_parquet(self.materialize(item.relpath))


def rank_dataframe(
    df: pd.DataFrame,
    *,
    level: str,
    start,
    end,
    metric: str = "flash_density",
    uf: str | None = None,
    top_n: int = 10,
) -> pd.DataFrame:
    work = df.copy()
    work["time"] = pd.to_datetime(work["time"])
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    work = work[(work["time"] >= start) & (work["time"] <= end)]
    if level == "municipality" and uf:
        work = work[work["state_abbrev"] == uf]
    if work.empty:
        return work

    if level == "municipality":
        group_cols = [
            "municipality_code", "municipality_name", "state_abbrev", "state_name",
            "latitude", "longitude", "area_km2",
        ]
    else:
        group_cols = ["state_abbrev", "state_name", "latitude", "longitude", "area_km2"]

    out = work.groupby(group_cols, as_index=False, dropna=False)["flash_count"].sum()
    out["flash_density"] = out["flash_count"] / out["area_km2"]
    out = out.sort_values(metric, ascending=False).head(int(top_n)).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
