"""Hugging Face: catálogo e downloads no mesmo commit (sem HEAD por arquivo já em cache). Sem rede."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import huggingface_hub  # noqa: E402
from huggingface_hub.errors import RevisionNotFoundError  # noqa: E402

from src.historical_glm import HistoricalGLMRepository, SourceConfig  # noqa: E402
from src.ranking_glm import RankingRepository  # noqa: E402

SHA = "3da43e6715" + "0" * 30
FILES = [
    "OUTPUT/03_MONTHLY/2024/G16_GLM_FLASH_MONTHLY_202401.nc",
    "OUTPUT/04_YEARLY/G16_GLM_FLASH_YEARLY_2024.nc",
    "OUTPUT/05_RANKINGS/GLM_RANKING_STATE_YEARLY_2020_2025.parquet",
    "README.md",
]


@pytest.fixture()
def fake_hub(monkeypatch, tmp_path):
    calls = {"dataset_info": 0, "list_repo_files": 0, "downloads": []}

    def dataset_info(self, repo_id, **kwargs):
        calls["dataset_info"] += 1
        return SimpleNamespace(sha=SHA, siblings=[SimpleNamespace(rfilename=f) for f in FILES])

    def list_repo_files(self, *a, **k):  # não deve ser usado: dataset_info já traz a lista
        calls["list_repo_files"] += 1
        return FILES

    def hf_hub_download(*, repo_id, repo_type, filename, token, revision=None):
        calls["downloads"].append((filename, revision))
        if revision == "commit-apagado":
            raise RevisionNotFoundError("Revision Not Found",
                                        response=SimpleNamespace(headers={}, request=None, status_code=404))
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        return str(target)

    monkeypatch.setattr(huggingface_hub.HfApi, "dataset_info", dataset_info)
    monkeypatch.setattr(huggingface_hub.HfApi, "list_repo_files", list_repo_files)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", hf_hub_download)
    return calls


CONFIG = SourceConfig(hf_repo="dono/dataset", hf_prefix="OUTPUT")


def test_historico_baixa_no_commit_do_catalogo(fake_hub):
    repo = HistoricalGLMRepository(CONFIG)
    item = repo.get_monthly(2024, 1)
    repo.materialize(item.relpath)
    repo.materialize(repo.get_yearly(2024).relpath)
    assert fake_hub["dataset_info"] == 1 and fake_hub["list_repo_files"] == 0
    assert fake_hub["downloads"] == [
        ("OUTPUT/03_MONTHLY/2024/G16_GLM_FLASH_MONTHLY_202401.nc", SHA),
        ("OUTPUT/04_YEARLY/G16_GLM_FLASH_YEARLY_2024.nc", SHA),
    ]


def test_ranking_baixa_no_commit_da_lista(fake_hub):
    repo = RankingRepository(CONFIG)
    assert repo.available("state", "yearly")
    repo.materialize(repo._select("state", "yearly").relpath)
    assert fake_hub["downloads"][-1] == ("OUTPUT/05_RANKINGS/GLM_RANKING_STATE_YEARLY_2020_2025.parquet", SHA)


def test_materialize_sem_catalogo_le_o_commit_antes(fake_hub):
    repo = HistoricalGLMRepository(CONFIG)
    repo.materialize("03_MONTHLY/2024/G16_GLM_FLASH_MONTHLY_202401.nc")
    assert fake_hub["downloads"] == [("OUTPUT/03_MONTHLY/2024/G16_GLM_FLASH_MONTHLY_202401.nc", SHA)]


def test_commit_apagado_baixa_do_commit_atual(fake_hub):
    repo = HistoricalGLMRepository(CONFIG)
    repo.scan()
    repo._revision = "commit-apagado"  # ex.: histórico do Dataset reescrito depois do catálogo
    repo.materialize("04_YEARLY/G16_GLM_FLASH_YEARLY_2024.nc")
    assert fake_hub["downloads"][-1] == ("OUTPUT/04_YEARLY/G16_GLM_FLASH_YEARLY_2024.nc", SHA)
