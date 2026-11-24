"""Simula falhas da fonte NOAA na aba ao vivo (AppTest) e verifica a mensagem e a recuperação.

Uso: python simular_falhas.py <repo> <saida.json>
Casos: lenta, timeout, vazia, arquivo_corrompido, lacuna (10–20 min sem arquivos).
O cache de disco do ao vivo fica numa pasta fixa (aquecida no primeiro caso) para não baixar tudo de novo.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
os.chdir(REPO)
sys.path.insert(0, str(REPO))

import botocore.client  # noqa: E402
import botocore.exceptions  # noqa: E402

import src.glm_aws as aws  # noqa: E402
import src.realtime_glm as rt  # noqa: E402

rt.LIVE_CACHE_DIR = OUT.parent / "live_cache"
from streamlit.testing.v1 import AppTest  # noqa: E402

_orig_api = botocore.client.BaseClient._make_api_call
_orig_list = rt.list_hour_keys
MODE = {"name": None}


def api(self, op, params):
    mode = MODE["name"]
    if mode == "lenta" and op == "ListObjectsV2":
        time.sleep(6)
    if mode == "timeout":
        raise botocore.exceptions.ConnectTimeoutError(endpoint_url="https://noaa-goes19.s3.amazonaws.com")
    if mode == "vazia" and op == "ListObjectsV2":
        return {"KeyCount": 0, "IsTruncated": False}
    return _orig_api(self, op, params)


def list_hour_keys(client, hour):
    rows = _orig_list(client, hour)
    if MODE["name"] == "lacuna" and rows:
        newest = max(r[2] for r in rows) if rows else None
        cut_hi = MODE["newest"] - timedelta(minutes=10)
        cut_lo = MODE["newest"] - timedelta(minutes=20)
        rows = [r for r in rows if not (cut_lo <= r[2] < cut_hi)]
        del newest
    return rows


botocore.client.BaseClient._make_api_call = api
rt.list_hour_keys = list_hour_keys


def screen(at: AppTest) -> dict:
    return {
        "erros": [e.value for e in at.error],
        "avisos": [w.value for w in at.warning],
        "excecoes": [str(e.value)[:160] for e in at.exception], "codigo": [c.value[:200] for c in at.code],
        "expanders": [x.label for x in at.expander if "Detalhes" in x.label],
        "metricas": [m.value for m in at.markdown if "time-card-value" in m.value][:4],
    }


def counts_cards(at: AppTest) -> list[str]:
    import re
    out = []
    for m in at.markdown:
        if "time-card" in m.value:
            label = re.search(r"<span>([^<]+)</span>", m.value)
            value = re.search(r'time-card-value">([^<]+)<', m.value)
            if label and value:
                out.append(f"{label.group(1)}={value.group(1)}")
    return out


results = []



def clear_caches():
    import streamlit as st
    st.cache_data.clear()


def case(name: str):
    clear_caches()
    MODE["name"] = name
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=600)
    t0 = time.perf_counter()
    at.run()
    dt = time.perf_counter() - t0
    first = screen(at)
    first["cartoes"] = counts_cards(at)
    MODE["name"] = None  # a fonte volta ao normal
    clear_caches()  # o fragmento de 60 s busca de novo quando o cache de 55 s vence
    t1 = time.perf_counter()
    at.run()
    back = screen(at)
    back["cartoes"] = counts_cards(at)
    results.append({"caso": name, "segundos_com_falha": round(dt, 2), "tela_com_falha": first,
                    "segundos_recuperacao": round(time.perf_counter() - t1, 2), "tela_depois": back})
    print(f"\n== {name}: {dt:.1f} s\n  com falha: {first}\n  depois:    {back}", flush=True)
    return at


# Aquecimento (baixa a janela uma vez para o cache de disco).
MODE["name"] = None
warm = AppTest.from_file(str(REPO / "app.py"), default_timeout=600).run()
print("aquecido; cartões:", counts_cards(warm), flush=True)
MODE["newest"] = max(r[2] for r in rt._list_recent_keys(aws.unsigned_s3_client(),
                                                         __import__("datetime").datetime.now(
                                                             __import__("datetime").timezone.utc)))

case("lenta")
case("timeout")
case("vazia")

# Arquivo corrompido: trunca um arquivo da janela já baixado (como um download que gravou lixo ou um
# arquivo ruim publicado na fonte). O download não refaz arquivos que já existem com tamanho > 0.
files = sorted(rt.LIVE_CACHE_DIR.glob("*.nc"))
victim = files[-5]
data = victim.read_bytes()
victim.write_bytes(data[: len(data) // 3])
clear_caches()
at = AppTest.from_file(str(REPO / "app.py"), default_timeout=600).run()
first = screen(at)
clear_caches()
at.run()
again = screen(at)
results.append({"caso": "arquivo_corrompido", "arquivo": victim.name, "tela_com_falha": first,
                "tela_no_refresh_seguinte": again})
print(f"\n== arquivo_corrompido ({victim.name}):\n  com falha: {first}\n  refresh seguinte: {again}", flush=True)
victim.unlink()  # deixa o cache limpo para os próximos testes

case("lacuna")

OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
