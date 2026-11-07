"""Alarme de relâmpagos na sua área de observação (GLM/GOES, NOAA/AWS).

Roda no seu computador, olha os arquivos novos do GLM a cada minuto e, quando cai relâmpago dentro da área,
toca um alarme com uma janela vermelha e, se você configurar, manda um aviso urgente para o celular (app ntfy).

Uso, na pasta do repositório:
    python scripts/alarme_relampagos.py              monitora usando alarme.toml
    python scripts/alarme_relampagos.py --testar     toca o alarme e manda um aviso de teste
    python scripts/alarme_relampagos.py --uma-vez    olha só os últimos minutos, mostra o que achou e sai

Guia: docs/ALARME.md. Dado observacional, com ~1–3 min de atraso; não substitui alertas oficiais.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.alarme import AlarmMonitor, ObservationArea, alarm_message  # noqa: E402
from src.glm_aws import iter_hours, list_hour_keys, unsigned_s3_client  # noqa: E402
from src.glm_reader import read_glm_files  # noqa: E402

SITE_URL = "https://flashview.streamlit.app"
USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FlashView"
LOG_FILE = USER_DIR / "alarme.log"
FILE_SECONDS = 20  # cada arquivo GLM-L2-LCFA cobre ~20 s
MAX_GAP_MIN = 60   # se ficar mais que isso sem buscar (PC suspenso), recomeça pelos últimos minutos

DEFAULTS = {
    "area": {"nome": "Minha área", "raio_km": 20.0},
    "alarme": {"min_relampagos": 1, "janela_min": 10, "rearmar_min": 30, "intervalo_s": 60,
               "qualidade": "zero_only", "aviso_sem_dados_min": 10},
    "computador": {"ativo": True, "som": True, "arquivo_som": "", "duracao_max_min": 10},
    "celular": {"ativo": False, "ntfy_topico": "", "ntfy_servidor": "https://ntfy.sh", "prioridade": "urgent"},
}
NTFY_PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
def load_config(path: Path | None) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path else {}
    return {section: {**values, **data.get(section, {})} for section, values in DEFAULTS.items()}


def build_area(cfg: dict, base_dir: Path) -> ObservationArea:
    a = cfg["area"]
    polygon = None
    if a.get("arquivo"):
        from src.map_uploads import load_user_overlay

        path = Path(a["arquivo"]).expanduser()
        path = path if path.is_absolute() else base_dir / path
        _, polygon, _ = load_user_overlay(path.name, path.read_bytes())
        if polygon is None:
            raise ValueError(f"{path.name} não tem polígonos (só pontos ou linhas).")
    if "lat" in a and "lon" in a:
        lat, lon = float(a["lat"]), float(a["lon"])
    elif polygon is not None:
        c = polygon.representative_point()
        lat, lon = c.y, c.x
    else:
        raise ValueError("Coloque lat e lon do centro da área em [area] no alarme.toml.")
    return ObservationArea(str(a["nome"]), lat, lon,
                           radius_km=None if polygon is not None else float(a["raio_km"]), polygon=polygon)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def log(message: str) -> None:
    line = f"[{datetime.now():%d/%m %H:%M:%S}] {message}"
    print(line, flush=True)
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def local(dt) -> datetime:
    return pd.Timestamp(dt).floor("s").to_pydatetime().astimezone()


# ---------------------------------------------------------------------------
# Dados do GLM (NOAA/AWS, sem conta)
# ---------------------------------------------------------------------------
class GlmFeed:
    """Busca só os arquivos LCFA que ainda não foram lidos, lê os flashes e apaga os arquivos."""

    def __init__(self, lookback_minutes: float, quality: str):
        self.client = unsigned_s3_client()
        self.lookback = timedelta(minutes=lookback_minutes)
        self.quality = quality
        self.started = datetime.now(timezone.utc)
        self.last_start = self.started - self.lookback
        self.last_obs_end: datetime | None = None
        self.tmp = Path(tempfile.mkdtemp(prefix="flashview_alarme_"))

    def poll(self) -> tuple[pd.DataFrame, datetime | None, int]:
        now = datetime.now(timezone.utc)
        if now - self.last_start > timedelta(minutes=MAX_GAP_MIN):
            log(f"Ficou {(now - self.last_start).total_seconds() / 60:.0f} min sem buscar dados "
                f"(PC suspenso?). Recomeçando pelos últimos {self.lookback.total_seconds() / 60:.0f} min.")
            self.last_start = now - self.lookback
        keys = []
        for hour in iter_hours(self.last_start - timedelta(minutes=1), now):
            keys.extend(list_hour_keys(self.client, hour))
        new = sorted((k for k in keys if k[2] > self.last_start), key=lambda k: k[2])
        if not new:
            return pd.DataFrame(), None, 0

        def fetch(item):
            bucket, key, _ = item
            target = self.tmp / Path(key).name
            self.client.download_file(bucket, key, str(target))
            return target

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = list(pool.map(fetch, new))
            flashes = read_glm_files(paths, quality=self.quality)
        finally:
            for p in self.tmp.glob("*"):
                p.unlink(missing_ok=True)
        self.last_start = new[-1][2]
        self.last_obs_end = self.last_start + timedelta(seconds=FILE_SECONDS)
        return flashes, self.last_obs_end, len(new)

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Avisos: computador e celular
# ---------------------------------------------------------------------------
def keep_awake() -> None:
    """Impede a suspensão automática do Windows enquanto o alarme roda (a tela pode apagar)."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def make_alarm_wav(path: Path, rate: int = 22050) -> Path:
    """Bipes agudos alternados (1000/1500 Hz), estilo despertador; cada ciclo ~1,5 s, tocado em loop."""
    t = np.arange(int(0.18 * rate)) / rate
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
    parts = []
    for freq in (1000, 1500, 1000, 1500):
        tone = np.tanh(4 * np.sin(2 * np.pi * freq * t)) / np.tanh(4)  # quase quadrada: mais penetrante
        parts += [tone * fade, np.zeros(int(0.07 * rate))]
    parts.append(np.zeros(int(0.5 * rate)))
    samples = (np.concatenate(parts) * 0.9 * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return path


def sound_file(computer: dict) -> str:
    custom = str(computer.get("arquivo_som") or "").strip()
    if custom:
        return str(Path(custom).expanduser())
    path = USER_DIR / "alarme.wav"
    return str(path if path.exists() else make_alarm_wav(path))


def notify_computer(cfg: dict, title: str, text: str) -> subprocess.Popen | None:
    """Abre a janela de alarme num processo separado, para o monitor continuar rodando."""
    computer = cfg["computador"]
    if not computer["ativo"]:
        return None
    args = [sys.executable, str(Path(__file__).resolve()), "--tocar", "--titulo", title, "--mensagem", text,
            "--duracao", str(computer["duracao_max_min"])]
    if computer["som"]:
        args += ["--som", sound_file(computer)]
    return subprocess.Popen(args)


def notify_phone(cfg: dict, title: str, text: str, *, priority=None, tags=("zap",)) -> None:
    phone = cfg["celular"]
    if not phone["ativo"]:
        return
    topic = str(phone["ntfy_topico"]).strip()
    if not topic:
        log("Celular ativo, mas ntfy_topico está vazio no alarme.toml: aviso não enviado.")
        return
    import requests

    level = priority or phone["prioridade"]
    payload = {"topic": topic, "title": title, "message": text, "tags": list(tags), "click": SITE_URL,
               "priority": int(level) if str(level).isdigit() else NTFY_PRIORITIES.get(str(level), 5)}
    try:
        requests.post(str(phone["ntfy_servidor"]).rstrip("/"), json=payload, timeout=15).raise_for_status()
        log("Aviso enviado para o celular (ntfy).")
    except Exception as exc:  # sem internet, servidor fora etc.: o alarme do PC continua valendo
        log(f"Não consegui mandar o aviso para o celular: {type(exc).__name__}: {exc}")


def run_alarm_window(title: str, text: str, duration_min: float, sound: str | None) -> None:
    """Janela vermelha, sempre por cima, com o som em loop até clicar em Parar (ou acabar o tempo)."""
    import tkinter as tk

    winsound = None
    if sys.platform == "win32":
        import winsound

        # Liga a tela e não deixa suspender enquanto a janela está aberta.
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        if sound:
            winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)

    def silence():
        if winsound is not None:
            winsound.PlaySound(None, 0)

    root = tk.Tk()
    root.title("Flash View — alarme de relâmpagos")
    root.attributes("-topmost", True)
    width, height = 760, 460
    root.geometry(f"{width}x{height}+{(root.winfo_screenwidth() - width) // 2}"
                  f"+{(root.winfo_screenheight() - height) // 3}")
    colors = ("#c62828", "#7f0000")
    frame = tk.Frame(root, bg=colors[0], padx=28, pady=22)
    frame.pack(fill="both", expand=True)
    header = tk.Label(frame, text="⚡ RELÂMPAGO NA SUA ÁREA", font=("Segoe UI", 30, "bold"), fg="white",
                      bg=colors[0])
    header.pack(anchor="w")
    subtitle = tk.Label(frame, text=title, font=("Segoe UI", 17, "bold"), fg="white", bg=colors[0],
                        wraplength=width - 60, justify="left")
    subtitle.pack(anchor="w", pady=(10, 6))
    body = tk.Label(frame, text=text, font=("Segoe UI", 12), fg="white", bg=colors[0],
                    wraplength=width - 60, justify="left")
    body.pack(anchor="w")
    end_at = datetime.now() + timedelta(minutes=duration_min)
    footer = tk.Label(frame, text=f"O som para sozinho às {end_at:%H:%M}.", font=("Segoe UI", 10),
                      fg="#ffd7d7", bg=colors[0])
    footer.pack(side="bottom", anchor="w")
    button = tk.Button(frame, text="Parar alarme", font=("Segoe UI", 18, "bold"), bg="white", fg=colors[1],
                       activebackground="#ffd7d7", relief="flat", padx=24, pady=8)
    button.pack(side="bottom", anchor="w", pady=(16, 10))
    tinted = (frame, header, subtitle, body, footer)
    state = {"blink": True, "i": 0}

    def blink():
        if not state["blink"]:
            return
        state["i"] ^= 1
        for widget in tinted:
            widget.configure(bg=colors[state["i"]])
        root.after(600, blink)

    def timeout():
        silence()
        state["blink"] = False
        for widget in tinted:
            widget.configure(bg=colors[1])
        footer.configure(text=f"Som desligado às {datetime.now():%H:%M} (tempo máximo). Clique para fechar.")
        button.configure(text="Fechar")

    def close():
        silence()
        root.destroy()

    button.configure(command=close)
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(600, blink)
    root.after(int(duration_min * 60_000), timeout)
    root.lift()
    root.focus_force()
    root.mainloop()


# ---------------------------------------------------------------------------
# Laço principal
# ---------------------------------------------------------------------------
def monitor(cfg: dict, area: ObservationArea, *, once: bool = False) -> None:
    a = cfg["alarme"]
    window = float(a["janela_min"])
    interval = max(15, int(a["intervalo_s"]))
    stale_after = timedelta(minutes=float(a["aviso_sem_dados_min"]))
    mon = AlarmMonitor(area, min_flashes=int(a["min_relampagos"]), window_minutes=window,
                       rearm_minutes=float(a["rearmar_min"]))
    feed = GlmFeed(window, str(a["qualidade"]))
    keep_awake()
    n = int(a["min_relampagos"])
    log(f"Área: {area.description}, centro em {area.lat:.4f}, {area.lon:.4f}.")
    log(f"Toca com {n} relâmpago{'s' if n > 1 else ''} na área em {window:g} min; depois de tocar, só toca de novo "
        f"após {float(a['rearmar_min']):g} min sem relâmpagos na área.")
    avisos = [x for x, on in (("janela com som no PC", cfg["computador"]["ativo"]),
                              ("celular (ntfy)", cfg["celular"]["ativo"])) if on]
    log("Avisos: " + (", ".join(avisos) or "nenhum (só este registro)") + f". Registro em {LOG_FILE}.")
    if not once:
        log("Deixe esta janela aberta e o volume ligado. Para parar: Ctrl+C ou feche a janela.")

    stale_warned = False
    alarm_proc: subprocess.Popen | None = None
    try:
        while True:
            try:
                flashes, obs_end, n_files = feed.poll()
            except Exception as exc:
                log(f"Falha ao buscar os dados ({type(exc).__name__}: {exc}). Tento de novo em {interval} s.")
                flashes, obs_end, n_files = pd.DataFrame(), None, 0

            now = datetime.now(timezone.utc)
            if obs_end is not None:
                in_area = area.select(flashes)
                lag = (now - obs_end).total_seconds() / 60
                files = f"{n_files} arquivo{'s' if n_files > 1 else ''}"
                status = (f"Dados até {local(obs_end):%H:%M:%S} ({lag:.1f} min de atraso, {files}): "
                          f"{len(flashes)} flashes no satélite, {len(in_area)} na área")
                if len(in_area):
                    status += f", o mais perto a {in_area['dist_km'].min():.0f} km"
                log(status + ".")
                if stale_warned:
                    log("Os dados do GLM voltaram; o alarme está funcionando de novo.")
                    notify_phone(cfg, "Flash View: dados de volta", "O alarme voltou a receber dados do GLM.",
                                 priority="low", tags=("white_check_mark",))
                    stale_warned = False
                for event in mon.update(in_area, obs_end):
                    if event.kind == "rearmado":
                        log(f"Área sem relâmpagos há {float(a['rearmar_min']):g} min: alarme rearmado.")
                        continue
                    title, text = alarm_message(area, event, window)
                    log(f"ALARME: {title}. {text}")
                    if once:
                        log("(--uma-vez: só mostra, não toca)")
                        continue
                    if alarm_proc is None or alarm_proc.poll() is not None:
                        alarm_proc = notify_computer(cfg, title, text)
                    notify_phone(cfg, title, text)

            last = feed.last_obs_end or feed.started
            if not stale_warned and now - last > stale_after:
                text = (f"Sem dados novos do GLM há {(now - last).total_seconds() / 60:.0f} min "
                        "(internet ou NOAA). O alarme não enxerga relâmpagos até os dados voltarem.")
                log(text)
                notify_phone(cfg, "Flash View: alarme sem dados", text, priority="high", tags=("warning",))
                stale_warned = True

            if once:
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        log("Alarme parado.")
    finally:
        feed.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Alarme de relâmpagos (GLM) na sua área de observação.")
    parser.add_argument("--config", type=Path, default=ROOT / "alarme.toml", help="arquivo de configuração")
    parser.add_argument("--testar", action="store_true", help="toca o alarme e manda um aviso de teste")
    parser.add_argument("--uma-vez", action="store_true", help="olha os últimos minutos, mostra e sai")
    parser.add_argument("--lat", type=float, help="latitude do centro (substitui a do arquivo)")
    parser.add_argument("--lon", type=float, help="longitude do centro (substitui a do arquivo)")
    parser.add_argument("--raio", type=float, help="raio em km (substitui o do arquivo)")
    parser.add_argument("--nome", help="nome da área (substitui o do arquivo)")
    parser.add_argument("--sem-som", action="store_true", help="janela de alarme sem som")
    # Uso interno: a janela de alarme roda num processo separado.
    parser.add_argument("--tocar", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--titulo", default="", help=argparse.SUPPRESS)
    parser.add_argument("--mensagem", default="", help=argparse.SUPPRESS)
    parser.add_argument("--duracao", type=float, default=10.0, help=argparse.SUPPRESS)
    parser.add_argument("--som", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.tocar:
        run_alarm_window(args.titulo, args.mensagem, args.duracao, args.som)
        return 0

    overrides = args.lat is not None and args.lon is not None
    if args.config.is_file():
        cfg = load_config(args.config)
    elif overrides:
        cfg = load_config(None)
    else:
        print(f"Não achei {args.config}.\nCopie alarme.exemplo.toml para alarme.toml e coloque a sua área "
              "(lat, lon e raio_km), ou rode com --lat, --lon e --raio.")
        return 1
    if overrides:
        cfg["area"].update({"lat": args.lat, "lon": args.lon})
        cfg["area"].pop("arquivo", None)
    if args.raio is not None:
        cfg["area"]["raio_km"] = args.raio
    if args.nome:
        cfg["area"]["nome"] = args.nome
    if args.sem_som:
        cfg["computador"]["som"] = False

    try:
        area = build_area(cfg, args.config.resolve().parent)
    except (ValueError, OSError) as exc:
        print(f"Área inválida: {exc}")
        return 1

    if args.testar:
        title = f"TESTE — relâmpago a 8 km (NE) — {area.name}"
        text = ("Isto é um teste do alarme do Flash View. Se você está vendo e ouvindo isto, o alarme "
                "está funcionando.")
        log("Teste: abrindo a janela de alarme" + (" e mandando o aviso para o celular." if cfg["celular"]["ativo"]
                                                    else ". Celular desativado no alarme.toml."))
        notify_phone(cfg, title, text)
        proc = notify_computer(cfg, title, text)
        if proc is not None:
            proc.wait()
        return 0

    monitor(cfg, area, once=args.uma_vez)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
