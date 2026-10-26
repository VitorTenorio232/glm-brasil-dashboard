"""Flash View — iniciador desktop para Windows.

Roda o MESMO app.py do site (Streamlit) num servidor local e o exibe numa
janela nativa (WebView2/Edge). Assim o app fica idêntico ao site.

Modos:
  FlashView.exe              -> abre a janela (processo principal)
  FlashView.exe --server P   -> processo filho: servidor Streamlit na porta P
  FlashView.exe --browser    -> abre no navegador padrão em vez da janela
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from pathlib import Path

APP_NAME = "Flash View"
FROZEN = getattr(sys, "frozen", False)

# Pasta onde estão app.py, src/, data/ e .streamlit/ (no .exe: a pasta _internal)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
# Pasta onde está o FlashView.exe (no código-fonte: a raiz do repositório)
EXE_DIR = Path(sys.executable).resolve().parent if FROZEN else BUNDLE_DIR
USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "FlashView"


# ---------------------------------------------------------------------------
# Segredos (HF_TOKEN etc.) — nunca embutidos no .exe
# ---------------------------------------------------------------------------
def secrets_candidates() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "FlashView"
    return [
        EXE_DIR / "secrets.toml",
        EXE_DIR / ".streamlit" / "secrets.toml",
        appdata / "secrets.toml",
        BUNDLE_DIR / ".streamlit" / "secrets.toml",  # ao rodar pelo código-fonte
    ]


def load_secrets_into_env() -> list[str]:
    """Copia chaves simples do secrets.toml para variáveis de ambiente.

    O app.py lê st.secrets e, como alternativa, os.getenv — então isso basta
    para HF_TOKEN, FLASH_VIEW_HF_REPO, FLASH_VIEW_DATA_ROOT, EE_PROJECT etc.
    """
    found = []
    for path in secrets_candidates():
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)) and str(value).strip():
                os.environ.setdefault(key, str(value))
        found.append(str(path))
    return found


# ---------------------------------------------------------------------------
# Processo filho: servidor Streamlit
# ---------------------------------------------------------------------------
def parent_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT = ainda vivo
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def watch_parent_and_exit(pid: int) -> None:
    """Encerra o servidor se a janela principal fechar ou travar."""
    while parent_alive(pid):
        time.sleep(1.5)
    os._exit(0)


def run_server(port: int, parent_pid: int | None, log_path: str | None) -> None:
    # Num .exe sem console, stdout/stderr podem não existir: manda tudo para o log
    if log_path:
        log = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    os.chdir(BUNDLE_DIR)  # para o Streamlit achar .streamlit/config.toml (tema do site)
    load_secrets_into_env()
    if parent_pid:
        threading.Thread(target=watch_parent_and_exit, args=(parent_pid,), daemon=True).start()

    from streamlit.web import cli as stcli

    secret_files = [str(p) for p in secrets_candidates()]
    sys.argv = [
        "streamlit", "run", str(BUNDLE_DIR / "app.py"),
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--server.runOnSave=false",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=minimal",
        f"--secrets.files={','.join(secret_files)}",
    ]
    sys.exit(stcli.main())


# ---------------------------------------------------------------------------
# Processo principal: janela
# ---------------------------------------------------------------------------
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server_process(port: int, log_path: Path) -> subprocess.Popen:
    args = ["--server", str(port), "--parent", str(os.getpid()), "--log", str(log_path)]
    if FROZEN:
        cmd = [sys.executable, *args]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve()), *args]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, cwd=str(BUNDLE_DIR), creationflags=flags,
    )


def wait_until_ready(port: int, proc: subprocess.Popen, timeout: float = 180) -> bool:
    url = f"http://127.0.0.1:{port}/_stcore/health"
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


LOADING_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#ffffff;font-family:'Segoe UI',sans-serif;color:#172536}
.c{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px}
.b{font-size:64px;animation:p 1.2s ease-in-out infinite}
@keyframes p{50%{opacity:.35;transform:scale(.92)}}
.t{font-size:22px;font-weight:600}.s{font-size:14px;color:#5b6b7d}
.bar{width:220px;height:4px;background:#e3edf3;border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%;width:40%;background:#087fa3;animation:m 1.1s infinite}
@keyframes m{from{transform:translateX(-100%)}to{transform:translateX(250%)}}
</style></head><body><div class="c"><div class="b">⚡</div>
<div class="t">Flash View</div><div class="bar"><i></i></div>
<div class="s" id="s">Iniciando… a primeira abertura pode levar alguns segundos.</div>
</div></body></html>"""


def error_html(log_path: Path) -> str:
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except Exception:
        tail = "(sem log)"
    tail = tail.replace("&", "&amp;").replace("<", "&lt;")
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style=\"font-family:'Segoe UI';padding:24px;color:#172536\">"
        "<h2>⚡ Não foi possível iniciar o Flash View</h2>"
        f"<p>Log completo em: <code>{log_path}</code></p>"
        f"<pre style='background:#f4f8fb;padding:12px;white-space:pre-wrap'>{tail}</pre>"
        "</body></html>"
    )


def main() -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    log_path = USER_DIR / "flashview.log"
    log_path.write_text("", encoding="utf-8")

    port = free_port()
    proc = start_server_process(port, log_path)
    url = f"http://127.0.0.1:{port}/"

    def shutdown() -> None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    use_browser = "--browser" in sys.argv
    webview = None
    if not use_browser:
        try:
            import webview  # pywebview -> WebView2 no Windows
        except Exception:
            use_browser = True

    if use_browser:
        import webbrowser
        if wait_until_ready(port, proc):
            webbrowser.open(url)
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
        shutdown()
        return

    webview.settings["ALLOW_DOWNLOADS"] = True          # downloads de CSV/PNG/GIF do site
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        APP_NAME, html=LOADING_HTML, width=1440, height=900,
        min_size=(900, 600), maximized=True, background_color="#FFFFFF",
        text_select=True, zoomable=True,
    )

    def boot() -> None:
        if wait_until_ready(port, proc):
            window.load_url(url)
        else:
            window.load_html(error_html(log_path))

    window.events.closed += shutdown
    icon = BUNDLE_DIR / "desktop" / "flashview.ico"
    try:
        webview.start(
            boot, private_mode=False, storage_path=str(USER_DIR / "webview"),
            icon=str(icon) if icon.exists() else None,
        )
    except Exception:
        # Sem WebView2 ou outro problema na janela: cai para o navegador
        import webbrowser
        if wait_until_ready(port, proc):
            webbrowser.open(url)
            proc.wait()
    finally:
        shutdown()


def _arg(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if "--server" in sys.argv:
        parent = _arg("--parent")
        run_server(int(_arg("--server")), int(parent) if parent else None, _arg("--log"))
    else:
        main()
