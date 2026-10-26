# -*- mode: python ; coding: utf-8 -*-
# Gera o Flash View para Windows rodando o MESMO app.py do site.
# Uso (na raiz do repositório):  pyinstaller --noconfirm desktop/FlashView.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent  # raiz do repositório

# --- Código e dados do site (o Streamlit executa o app.py a partir do disco) ---
datas = [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / "src"), "src"),
    (str(ROOT / "data"), "data"),
    (str(ROOT / ".streamlit" / "config.toml"), ".streamlit"),  # tema do site (sem secrets!)
    (str(ROOT / "desktop" / "flashview.ico"), "desktop"),
]
binaries = []
hiddenimports = ["app"] + collect_submodules("src")

# --- Pacotes sem hook oficial que precisam de arquivos estáticos/metadados ---
# (folium, branca, plotly, altair, geopandas, pyproj, shapely, xarray, netCDF4,
#  h5py, pyarrow, boto3/botocore, matplotlib, scipy, webview... já têm hooks)
COLLECT_ALL = [
    "streamlit", "streamlit_folium", "pydeck", "contextily", "geobr",
    "pyogrio", "huggingface_hub",
]
for pkg in COLLECT_ALL:
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # pacote ausente nesta plataforma
        print(f"[FlashView.spec] aviso: {pkg}: {exc}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

# Bibliotecas que consultam a própria versão via importlib.metadata
for pkg in ["pandas", "numpy", "xarray", "geopandas", "plotly", "folium", "branca",
            "altair", "pyarrow", "requests", "packaging", "pywebview"]:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

hiddenimports += [
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "xarray.backends.netCDF4_",
    "xarray.backends.h5netcdf_",
    "clr",  # pythonnet, usado pelo pywebview/WebView2 no Windows
]

a = Analysis(
    [str(ROOT / "desktop" / "flashview_desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "jupyter", "notebook", "pytest", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlashView",
    icon=str(ROOT / "desktop" / "flashview.ico"),
    console=False,          # sem janela preta de terminal
    debug=False,
    strip=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FlashView")
