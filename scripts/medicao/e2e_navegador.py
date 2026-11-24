"""Validação no navegador (Edge headless): abertura, fuso, XSS pelo nome do arquivo, Séries/Climatologia com
base sintética (0 ≠ ausente, tela = arquivo baixado) e tela de celular.

Uso: python e2e_navegador.py <url> <pasta_saida> <rotulo>
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from playwright.sync_api import sync_playwright

URL, OUT, LABEL = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
OUT.mkdir(parents=True, exist_ok=True)
R = {"rotulo": LABEL}
EVIL_NAME = "bacia<img src=x onerror=alert('xss-nome')>.geojson"
GEOJSON = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Polygon", "coordinates": [[[-45, -22], [-44, -22], [-44, -21],
                                                                       [-45, -21], [-45, -22]]]}}]}).encode()


def choose(f, label, option):
    box = f.locator('[data-testid="stSelectbox"]', has=f.get_by_text(label, exact=True)).first
    box.click()
    f.get_by_role("option", name=option, exact=True).first.click()
    f.wait_for_timeout(1200)


def tab(f, name):
    f.locator('[data-testid="stTab"]', has_text=name).first.click()
    f.wait_for_timeout(2500)


def card(f, label):
    el = f.locator(".metric-card", has=f.locator(".metric-card-label", has_text=label)).first
    return el.locator(".metric-card-value").inner_text(), el.locator(".metric-card-small").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 1050}, accept_downloads=True)
    page = ctx.new_page()
    dialogs, console_errors = [], []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.on("console", lambda m: console_errors.append(m.text[:160]) if m.type == "error" else None)

    # --- A. primeira abertura + fuso -------------------------------------------------------------
    t0 = time.perf_counter()
    page.goto(URL, wait_until="domcontentloaded")
    page.locator('[data-testid="stTab"]').first.wait_for(timeout=120000)
    R["abas_visiveis_s"] = round(time.perf_counter() - t0, 2)
    page.locator(".metric-card-label", has_text="Hora").first.wait_for(timeout=180000)
    R["dados_ao_vivo_s"] = round(time.perf_counter() - t0, 2)
    hora_br, fuso_br = card(page, "Hora")
    data_br, _ = card(page, "Data")
    page.locator("button").filter(has_text=re.compile(r"^s*UTCs*$")).first.click()
    page.wait_for_timeout(2500)
    hora_utc, fuso_utc = card(page, "Hora")
    h_br, h_utc = (int(x.split(":")[0]) for x in (hora_br, hora_utc))
    R["fuso"] = {"brasilia": f"{data_br} {hora_br} ({fuso_br})", "utc": f"{hora_utc} ({fuso_utc})",
                 "diferenca_h": (h_utc - h_br) % 24}
    page.screenshot(path=str(OUT / f"{LABEL}_ao_vivo.png"))

    # --- B. Tendência: nome de arquivo malicioso ---------------------------------------------------
    tab(page, "Tendência")
    page.locator("button").filter(has_text=re.compile(r"^s*Arquivos*$")).first.click()
    page.wait_for_timeout(1500)
    page.locator('input[type="file"]').first.set_input_files(
        {"name": EVIL_NAME, "mimeType": "application/geo+json", "buffer": GEOJSON})
    page.wait_for_timeout(9000)
    injected = 0
    for fr in page.frames:
        try:
            injected += fr.locator('img[src="x"]').count()
            fr.locator(".leaflet-interactive").first.hover(timeout=1500)  # abre o tooltip
        except Exception:
            pass
    page.wait_for_timeout(1500)
    for fr in page.frames:
        try:
            injected += fr.locator('img[src="x"]').count()
        except Exception:
            pass
    R["xss_tendencia"] = {"alertas": list(dialogs), "img_injetada": injected}
    page.screenshot(path=str(OUT / f"{LABEL}_tendencia_arquivo.png"))

    # --- C. Séries: base sintética (jan–jun/2024, mar = 0 flashes, abr sem arquivo) -------------------
    tab(page, "Séries temporais")
    choose(page, "Área", "Retângulo")
    page.get_by_text("Digitar coordenadas", exact=True).first.click()
    page.wait_for_timeout(1200)
    choose(page, "Escala temporal", "Mensal")
    choose(page, "Mês inicial", "Janeiro/2024")
    choose(page, "Mês final", "Junho/2024")
    t1 = time.perf_counter()
    page.get_by_role("button", name="📈 Calcular série").first.click()
    page.locator(".js-plotly-plot").first.wait_for(timeout=120000)
    R["series_calcular_s"] = round(time.perf_counter() - t1, 2)
    page.wait_for_timeout(1500)
    trace = page.evaluate("""() => { const d = document.querySelector('.js-plotly-plot')._fullData[0];
        return {x: Array.from(d.x).map(String), y: Array.from(d.y).map(v => v === null ? null : Number(v))}; }""")
    with page.expect_download() as dl:
        page.get_by_role("button", name="⬇️ Dados CSV").first.click()
    csv_path = OUT / f"{LABEL}_serie.csv"
    dl.value.save_as(str(csv_path))
    csv = pd.read_csv(csv_path)
    infos = [t for t in page.locator('[data-testid="stAlertContentInfo"]').all_inner_texts() if "sem dado" in t]
    tela = {str(x)[:7]: y for x, y in zip(trace["x"], trace["y"])}
    arquivo = {str(d)[:7]: (None if pd.isna(v) else float(v)) for d, v in zip(csv["date"], csv["value"])}
    R["series"] = {"grafico": tela, "csv": arquivo, "csv_colunas": list(csv.columns), "aviso": infos[:1],
                   "tela_igual_arquivo": bool(tela) and all(arquivo.get(k) == (None if v is None else float(v))
                                             for k, v in tela.items())}
    page.locator(".js-plotly-plot").first.scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / f"{LABEL}_series.png"))

    # --- D. Climatologia: mar/2024 (0 flashes) num retângulo; NetCDF baixado = seleção da tela ---------
    tab(page, "Climatologia")
    choose(page, "Recorte espacial", "Retângulo")
    page.get_by_text("Digitar coordenadas", exact=True).first.click()
    page.wait_for_timeout(1200)
    choose(page, "Escala", "Mensal")
    choose(page, "Mês", "Março")
    page.get_by_role("button", name="🗺️ Gerar mapa").first.click()
    page.get_by_text("Downloads do produto").first.wait_for(timeout=120000)
    produto, _ = card(page, "Produto")
    recorte, _ = card(page, "Recorte")
    with page.expect_download() as dl:
        page.get_by_role("button", name="⬇️ Dados NetCDF").first.click()
    nc_path = OUT / f"{LABEL}_climatologia.nc"
    dl.value.save_as(str(nc_path))
    import xarray as xr
    with xr.open_dataset(nc_path, engine="scipy") as ds:  # NetCDF3 (o app grava com scipy)
        name = next(iter(ds.data_vars))
        vals = np.asarray(ds[name].values, dtype=float)
        lat, lon = np.asarray(ds["lat"].values), np.asarray(ds["lon"].values)
        title = str(ds.attrs.get("title", ""))
    R["climatologia"] = {"tela_produto": produto, "tela_recorte": recorte, "arquivo": nc_path.name,
                         "titulo_nc": title, "lat": [float(lat.min()), float(lat.max())],
                         "lon": [float(lon.min()), float(lon.max())],
                         "valores_finitos": sorted(set(np.unique(vals[np.isfinite(vals)]).round(3).tolist()))[:5],
                         "celulas_nan": int(np.isnan(vals).sum())}
    page.screenshot(path=str(OUT / f"{LABEL}_climatologia.png"))
    R["erros_console"] = console_errors[:8]
    ctx.close()

    # --- E. Celular (375×812) ------------------------------------------------------------------------
    mob = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
                              device_scale_factor=2)
    mp = mob.new_page()
    mp.goto(URL, wait_until="domcontentloaded")
    mp.locator(".metric-card-label", has_text="Hora").first.wait_for(timeout=180000)
    mp.wait_for_timeout(4000)
    overflow = mp.evaluate("() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth})")
    mp.screenshot(path=str(OUT / f"{LABEL}_celular_ao_vivo.png"))
    tab(mp, "Séries temporais")
    overflow2 = mp.evaluate("() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth})")
    mp.screenshot(path=str(OUT / f"{LABEL}_celular_series.png"))
    R["celular"] = {"ao_vivo": overflow, "series": overflow2}
    browser.close()

(OUT / f"{LABEL}_resultado.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str),
                                             encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
