"""Mede o fluxo do Flash View com o AppTest: tempo de cada passo e chamadas externas.

Uso:
    python medir_fluxo.py <repo> <cenario> <saida.json> [--hf-sim] [--perfil PASSO]

Cenários: ao_vivo, climatologia, series, duas_sessoes.

Cada cenário roda num processo novo (caches do Streamlit e lru_cache vazios).
--hf-sim troca a pasta local por um "Hugging Face" simulado: list_repo_files e hf_hub_download
são substituídos por funções que leem a mesma pasta local e contam as chamadas (sem rede, sem token).
"""
from __future__ import annotations

import collections
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
REPO = Path(sys.argv[1]).resolve()
SCENARIO = sys.argv[2]
OUT = Path(sys.argv[3]).resolve()
HF_SIM = "--hf-sim" in sys.argv
# --hf-real PASTA: Dataset real do Hugging Face (login salvo por `hf auth login` ou HF_TOKEN no ambiente),
# com o cache de downloads nessa pasta (vazia = frio; reaproveitada = morno). O token nunca é exibido.
HF_REAL = Path(sys.argv[sys.argv.index("--hf-real") + 1]).resolve() if "--hf-real" in sys.argv else None
PROFILE_STEPS = sys.argv[sys.argv.index("--perfil") + 1].split(",") if "--perfil" in sys.argv else []
DATA_ROOT = Path(os.environ.get("FV_DATA_ROOT", REPO.parent / "GLM_Process" / "OUTPUT"))

os.chdir(REPO)
sys.path.insert(0, str(REPO))
if HF_SIM:
    os.environ.pop("FLASH_VIEW_DATA_ROOT", None)
    os.environ["FLASH_VIEW_HF_REPO"] = "simulado/flash-view"
elif HF_REAL:
    os.environ.pop("FLASH_VIEW_DATA_ROOT", None)
    os.environ["HF_HUB_CACHE"] = str(HF_REAL)  # antes de importar huggingface_hub
else:
    os.environ["FLASH_VIEW_DATA_ROOT"] = str(DATA_ROOT)

# ----------------------------------------------------------------------------- contadores
LOCK = threading.Lock()
CALLS: collections.Counter = collections.Counter()


def count(label: str) -> None:
    with LOCK:
        CALLS[label] += 1


def wrap(owner, attr: str, label):
    original = getattr(owner, attr)

    def wrapper(*args, **kwargs):
        count(label(*args, **kwargs) if callable(label) else label)
        return original(*args, **kwargs)

    setattr(owner, attr, wrapper)
    return original


import botocore.client  # noqa: E402

_orig_api = botocore.client.BaseClient._make_api_call


def _api(self, operation_name, api_params):
    count(f"noaa_s3:{operation_name}")
    return _orig_api(self, operation_name, api_params)


botocore.client.BaseClient._make_api_call = _api

import urllib3.connectionpool  # noqa: E402

wrap(urllib3.connectionpool.HTTPConnectionPool, "urlopen", lambda self, *a, **k: f"http:{self.host}")
for _mod in ("httpx", "httpx2"):  # huggingface_hub 2.x usa httpx2
    try:
        _httpx = __import__(_mod)
        wrap(_httpx.Client, "send", lambda self, request, *a, **k: f"http:{request.url.host}")
    except ImportError:
        pass

import h5py  # noqa: E402

_orig_h5 = h5py.File.__init__


def _h5_init(self, name, *args, **kwargs):
    if isinstance(name, (str, os.PathLike)):
        count("arquivo:h5py.File (abertura)")
    return _orig_h5(self, name, *args, **kwargs)


h5py.File.__init__ = _h5_init
_orig_rglob = Path.rglob


def _rglob(self, pattern, *args, **kwargs):
    count(f"arquivo:rglob({pattern})")
    return _orig_rglob(self, pattern, *args, **kwargs)


Path.rglob = _rglob
import geopandas  # noqa: E402

wrap(geopandas, "read_parquet", "arquivo:gpd.read_parquet")
wrap(geopandas, "read_file", "arquivo:gpd.read_file")

if HF_SIM:
    import huggingface_hub  # noqa: E402

    def _list_repo_files(self, repo_id, *args, **kwargs):
        count("hf:list_repo_files")
        return [p.relative_to(DATA_ROOT).as_posix() for p in _orig_rglob(DATA_ROOT, "*.nc")]

    def _hf_hub_download(*, repo_id, filename, **kwargs):
        count("hf:hf_hub_download")
        return str(DATA_ROOT / filename)

    huggingface_hub.HfApi.list_repo_files = _list_repo_files
    huggingface_hub.hf_hub_download = _hf_hub_download
    import src.historical_glm as hg  # noqa: E402

    hg.autodetect_local_root = lambda *a, **k: None
elif HF_REAL:
    import huggingface_hub  # noqa: E402

    import src.historical_glm as hg  # noqa: E402

    hg.autodetect_local_root = lambda *a, **k: None  # não usar a pasta local GLM_Process/OUTPUT
    wrap(huggingface_hub, "hf_hub_download", "hf:hf_hub_download")
    for _name in ("list_repo_files", "dataset_info"):
        wrap(huggingface_hub.HfApi, _name, f"hf:{_name}")

# Disco do "ao vivo" vazio: a primeira abertura baixa os arquivos como num servidor novo.
import src.realtime_glm as rt  # noqa: E402

rt.LIVE_CACHE_DIR = Path(tempfile.mkdtemp(prefix="fv_live_medicao_"))

from streamlit.testing.v1 import AppTest  # noqa: E402

STEPS: list[dict] = []


def step(name: str, at: AppTest, action=None):
    """Roda uma interação, mede o tempo e as chamadas feitas só nela."""
    before = CALLS.copy()
    prof = cProfile.Profile() if name.split(".")[0] in PROFILE_STEPS else None
    t0 = time.perf_counter()
    if prof:
        prof.enable()
    (action or (lambda a: a))(at).run()
    if prof:
        prof.disable()
    elapsed = time.perf_counter() - t0
    diff = {k: v - before.get(k, 0) for k, v in CALLS.items() if v - before.get(k, 0)}
    errors = [str(e.value)[:300] for e in at.exception]
    STEPS.append({"passo": name, "segundos": round(elapsed, 3), "chamadas": diff, "erros": errors})
    print(f"{name:<45} {elapsed:8.2f} s  {diff}  {'ERRO ' + errors[0][:120] if errors else ''}", flush=True)
    if prof:
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(35)
        (OUT.parent / f"perfil_{OUT.stem}_{name.split(".")[0]}.txt").write_text(s.getvalue(), encoding="utf-8")
    return at


def new_app() -> AppTest:
    return AppTest.from_file(str(REPO / "app.py"), default_timeout=900)


def option(widget, prefix: str):
    for opt in widget.options:
        if str(opt).startswith(prefix):
            return opt
    raise KeyError(f"{prefix!r} não está em {widget.options[:8]}")


def set_tab(label):
    def go(at):
        at.session_state["fv_active_tab"] = label
        return at
    return go


def sel(key, value=None, prefix=None):
    def go(at):
        w = at.selectbox(key=key)
        w.set_value(value if prefix is None else option(w, prefix))
        return at
    return go


def click(key):
    return lambda at: at.button(key=key).click()


CLIM = "🌦️ Climatologia"
SERIES = "📈 Séries temporais"

if SCENARIO == "ao_vivo":
    at = new_app()
    step("1. primeira abertura (aba ao vivo)", at)
    step("2. repetição (rerun, mesma seleção)", at)
    step("3. troca de um filtro (fuso UTC)",
         at, lambda a: a.session_state.__setitem__("fv_live_time_zone", "UTC") or a)
    step("4. área: Estados", at, lambda a: a.session_state.__setitem__("fv_live_area_mode", "Estados") or a)
    w = at.multiselect(key="fv_live_states")
    step("5. escolhe MG", at, lambda a: a.multiselect(key="fv_live_states").select(option(w, "MG")))
    step("6. vai para Tendência", at, set_tab("📊 Tendência"))
    step("7. volta ao ao vivo", at, set_tab("⚡ Relâmpagos em tempo real"))

elif SCENARIO == "climatologia":
    at = new_app()
    at.session_state["fv_active_tab"] = CLIM  # abre direto na aba, sem o ao vivo
    step("1. primeira abertura (Climatologia)", at)
    step("2. escala Mensal", at, sel("clim_scale", "Mensal"))
    step("3. período jan/2025", at, lambda a: sel("spec_month_year", 2025)(a).selectbox(key="spec_month").set_value(1))
    step("4. recorte Estado", at, sel("clim_area", "Estado"))
    step("5. UF MG", at, sel("clim_state", prefix="MG"))
    step("6. Gerar mapa (MG, jan/2025)", at, click("generate_historical_map"))
    res = at.session_state["historical_map_result"]
    print("   recorte:", res["location_label"], "| período:", res["period_text"], "| células:", res["field"].size)
    step("7. Gerar mapa de novo (mesma consulta)", at, click("generate_historical_map"))
    step("8. rerun sem mudança (ex.: clique em download)", at)
    step("9. troca UF -> SP", at, sel("clim_state", prefix="SP"))
    step("10. Gerar mapa (SP, jan/2025)", at, click("generate_historical_map"))
    res = at.session_state["historical_map_result"]
    print("   recorte:", res["location_label"], "| período:", res["period_text"])
    step("11. troca período -> fev/2025", at, lambda a: a.selectbox(key="spec_month").set_value(2))
    step("12. Gerar mapa (SP, fev/2025)", at, click("generate_historical_map"))

elif SCENARIO == "series":
    at = new_app()
    at.session_state["fv_active_tab"] = SERIES
    step("1. primeira abertura (Séries)", at)
    step("2. área Estado", at, sel("series_area", "Estado"))
    step("3. UF MG", at, sel("series_state", prefix="MG"))
    step("4. escala Mensal", at, sel("series_scale", "Mensal"))
    step("5. período jan/2024–dez/2025", at,
         lambda a: sel("series_month_start", prefix="Jan")(a) and a)
    w = at.selectbox(key="series_month_start")
    start = next(o for o in w.options if o.endswith("/2024") and o.lower().startswith("jan"))
    end = next(o for o in w.options if o.endswith("/2025") and o.lower().startswith("dez"))
    step("5b. define início/fim", at,
         lambda a: (a.selectbox(key="series_month_start").set_value(start),
                    a.selectbox(key="series_month_end").set_value(end))[0])
    step("6. Calcular série (MG)", at, click("calculate_historical_series"))
    s = at.session_state["historical_series_result"]
    print("   pontos:", len(s), "| soma:", round(float(s['value'].sum()), 1))
    step("7. Calcular de novo (mesma consulta)", at, click("calculate_historical_series"))
    step("8. rerun sem mudança (ex.: clique em download)", at)
    step("9. troca UF -> SP", at, sel("series_state", prefix="SP"))
    step("10. Calcular série (SP)", at, click("calculate_historical_series"))
    step("11. rerun sem mudança (ex.: clique em download)", at)

elif SCENARIO == "duas_sessoes":
    a1, a2 = new_app(), new_app()
    for at in (a1, a2):
        at.session_state["fv_active_tab"] = SERIES
    step("A1. sessão A abre Séries", a1)
    step("B1. sessão B abre Séries", a2)
    for at, uf in ((a1, "MG"), (a2, "SP")):
        sel("series_area", "Estado")(at).run()
        sel("series_state", prefix=uf)(at).run()
        sel("series_scale", "Anual")(at).run()
        w = at.selectbox(key="series_year_start")
        at.selectbox(key="series_year_start").set_value(w.options[0]).run()
    step("A2. sessão A calcula MG", a1, click("calculate_historical_series"))
    step("B2. sessão B calcula SP", a2, click("calculate_historical_series"))
    sa = a1.session_state["historical_series_result"]
    sb = a2.session_state["historical_series_result"]
    step("A3. sessão A rerun (não pode virar SP)", a1)
    print("   A:", a1.session_state["historical_series_location"], round(float(sa['value'].sum())),
          "| B:", a2.session_state["historical_series_location"], round(float(sb['value'].sum())))
    STEPS.append({"isolamento": {
        "A_local": a1.session_state["historical_series_location"],
        "B_local": a2.session_state["historical_series_location"],
        "A_soma": float(sa["value"].sum()), "B_soma": float(sb["value"].sum()),
        "A_selectbox": a1.selectbox(key="series_state").value,
        "B_selectbox": a2.selectbox(key="series_state").value,
    }})
    # Ao vivo nas duas sessões ao mesmo tempo: o snapshot (cache global) deve ser buscado uma vez só.
    b1, b2 = new_app(), new_app()
    results = {}

    def run(name, at):
        t0 = time.perf_counter()
        at.run()
        results[name] = time.perf_counter() - t0

    before = CALLS.copy()
    threads = [threading.Thread(target=run, args=(n, a)) for n, a in (("C", b1), ("D", b2))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    diff = {k: v - before.get(k, 0) for k, v in CALLS.items() if v - before.get(k, 0)}
    print("   ao vivo em paralelo:", {k: round(v, 2) for k, v in results.items()}, diff)
    STEPS.append({"passo": "C+D. duas sessões abrem o ao vivo juntas", "segundos": results, "chamadas": diff,
                  "erros": [str(e.value)[:200] for e in (*b1.exception, *b2.exception)]})

OUT.write_text(json.dumps({"cenario": SCENARIO, "hf_sim": HF_SIM, "passos": STEPS}, ensure_ascii=False, indent=1,
                          default=str), encoding="utf-8")
