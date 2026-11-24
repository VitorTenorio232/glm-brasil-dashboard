"""Busca do ao vivo: um GET por arquivo, arquivo corrompido não derruba o painel e lacunas são avisadas."""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import src.realtime_glm as rt  # noqa: E402
from test_flash_view import _write_fake_lcfa  # noqa: E402

NOW = datetime(2026, 11, 23, 22, 0, 30, tzinfo=timezone.utc)


def _key(start: datetime) -> str:
    stamp = f"{start:%Y%j%H%M%S}{start.microsecond // 100000}"
    return f"GLM-L2-LCFA/{start:%Y/%j/%H}/OR_GLM-L2-LCFA_G19_s{stamp}_e{stamp}_c{stamp}.nc"


class FakeS3:
    """Só o que a busca usa: list_objects_v2 paginado e get_object. Sem download_file/head_object."""

    def __init__(self, starts, payload: bytes, corrupt: set[str] = frozenset()):
        self.keys = [_key(s) for s in starts]
        self.payload = payload
        self.corrupt = set(corrupt)
        self.gets: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in fake.keys if k.startswith(Prefix)]}

        return Paginator()

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        data = self.payload[: len(self.payload) // 3] if Key in self.corrupt else self.payload
        return {"Body": io.BytesIO(data)}


def _setup(tmp_path, monkeypatch, starts, corrupt=()):
    sample = tmp_path / "amostra.nc"
    _write_fake_lcfa(sample)
    fake = FakeS3(starts, sample.read_bytes(), {_key(s) for s in corrupt})
    monkeypatch.setattr(rt, "unsigned_s3_client", lambda: fake)
    monkeypatch.setattr(rt, "LIVE_CACHE_DIR", tmp_path / "cache")
    return fake


def _every_20s(minutes: int, end: datetime = NOW - timedelta(seconds=30)):
    return [end - timedelta(seconds=20 * i) for i in range(minutes * 3)][::-1]


def test_um_get_por_arquivo_e_janela_completa_sem_lacunas(tmp_path, monkeypatch):
    starts = _every_20s(32)
    fake = _setup(tmp_path, monkeypatch, starts)
    snap = rt.fetch_live_snapshot(window_minutes=30, now_utc=NOW)
    assert len(fake.gets) == snap.source_files  # nenhum HeadObject: FakeS3 nem tem head_object
    assert snap.gaps == () and snap.unreadable_files == 0
    assert rt.describe_missing(snap, ZoneInfo("UTC")) is None
    assert not list((tmp_path / "cache").glob("*.part"))


def test_arquivo_corrompido_e_ignorado_apagado_e_baixado_de_novo(tmp_path, monkeypatch):
    starts = _every_20s(32)
    bad = starts[-10]
    fake = _setup(tmp_path, monkeypatch, starts, corrupt=[bad])
    snap = rt.fetch_live_snapshot(window_minutes=30, now_utc=NOW)  # antes: exceção, painel fora do ar
    assert snap.unreadable_files == 1
    assert not (tmp_path / "cache" / Path(_key(bad)).name).exists()  # saiu do cache
    assert "ilegível" in rt.describe_missing(snap, ZoneInfo("UTC"))

    fake.corrupt.clear()  # a fonte voltou a servir o arquivo certo
    fake.gets.clear()
    snap = rt.fetch_live_snapshot(window_minutes=30, now_utc=NOW)
    assert fake.gets == [_key(bad)]  # só o arquivo que faltava foi baixado de novo
    assert snap.unreadable_files == 0


def test_lacuna_de_10_min_vira_aviso_e_nao_queda_de_atividade(tmp_path, monkeypatch):
    end = NOW - timedelta(seconds=30)
    starts = [s for s in _every_20s(32) if not (end - timedelta(minutes=20) <= s < end - timedelta(minutes=10))]
    _setup(tmp_path, monkeypatch, starts)
    snap = rt.fetch_live_snapshot(window_minutes=30, now_utc=NOW)
    assert len(snap.gaps) == 1
    gap_start, gap_end = snap.gaps[0]
    assert timedelta(minutes=9) < gap_end - gap_start <= timedelta(minutes=10, seconds=20)
    text = rt.describe_missing(snap, ZoneInfo("America/Sao_Paulo"))
    assert text and "faltam arquivos GLM" in text and "não queda de atividade" in text
    # A lacuna está fora dos últimos 5 min: o recorte por janela a ignora.
    assert rt.missing_periods(snap, minutes=5) == []


def test_coverage_gaps_tolera_um_arquivo_faltando():
    w0 = NOW - timedelta(minutes=30)
    starts = [w0 + timedelta(seconds=20 * i) for i in range(90) if i != 40]  # falta 1 arquivo (20 s)
    assert rt.coverage_gaps(starts, w0, NOW - timedelta(seconds=10)) == ()
