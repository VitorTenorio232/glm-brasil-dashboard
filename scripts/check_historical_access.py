#!/usr/bin/env python3
"""Diagnóstico seguro da base histórica no Copal/Streamlit Cloud.

Não imprime nem armazena o HF_TOKEN. Usa .streamlit/secrets.toml,
variáveis de ambiente e, se houver, credencial de login Hugging Face.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "VitorLSR/flash-view-glm-data"
VALID = re.compile(r"(?:^|/)(?:02_DAILY|03_MONTHLY|04_YEARLY)/.*\.nc$", re.I)


def read_config():
    secrets_file = ROOT / ".streamlit" / "secrets.toml"
    secrets = {}
    if secrets_file.is_file():
        with secrets_file.open("rb") as fp:
            secrets = tomllib.load(fp)
    return secrets, secrets_file


def main() -> int:
    print("FLASH VIEW — Diagnóstico da base histórica")
    print("Projeto:", ROOT)
    secrets, config_path = read_config()
    print("secrets.toml:", "presente" if config_path.is_file() else "ausente")
    repo = secrets.get("FLASH_VIEW_HF_REPO") or os.getenv("FLASH_VIEW_HF_REPO") or DEFAULT_REPO
    prefix = (secrets.get("FLASH_VIEW_HF_PREFIX") or os.getenv("FLASH_VIEW_HF_PREFIX") or "").strip("/")
    token = secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN") or None
    local = secrets.get("FLASH_VIEW_DATA_ROOT") or os.getenv("FLASH_VIEW_DATA_ROOT")
    print("Dataset:", repo)
    print("Prefixo:", prefix or "(raiz)")
    print("HF_TOKEN em secrets/ambiente:", "configurado" if token else "ausente")
    print("Fonte local configurada:", local or "não")

    if local:
        path = Path(local).expanduser()
        if path.is_dir():
            files = list(path.rglob("*.nc"))
            matches = [p for p in files if VALID.search(p.relative_to(path).as_posix())]
            print(f"Dados locais: {len(matches)} produtos reconhecidos (de {len(files)} NetCDF).")
            if matches:
                print("OK: existe base histórica local.")
                return 0
        else:
            print("ATENÇÃO: caminho local configurado não existe nesta máquina.")

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("ERRO: instale huggingface_hub com 'python -m pip install -r requirements.txt'.")
        return 2

    try:
        # token=None permite reutilizar hf auth login quando não há secrets.
        files = HfApi(token=token).list_repo_files(repo_id=repo, repo_type="dataset")
    except Exception as exc:
        print("ERRO ao acessar o Dataset:", type(exc).__name__)
        detail = str(exc).replace(str(token), "[TOKEN OCULTO]") if token else str(exc)
        print(detail[:1200])
        print("Verifique HF_TOKEN de leitura, o ID do Dataset e sua conexão.")
        print("O token NÃO foi exibido.")
        return 3

    for cand in dict.fromkeys([prefix, "OUTPUT" if not prefix else ""]):
        selected = [f[len(cand)+1:] if cand else f
                    for f in files if not cand or f.startswith(cand + "/")]
        historical = [p for p in selected if VALID.search(p)]
        ranking = [p for p in selected if p.startswith("05_RANKINGS/") and p.endswith(".parquet")]
        print(f"Prefixo {cand or '(raiz)'}: {len(historical)} arquivos históricos, "
              f"{len(ranking)} rankings Parquet")
        if historical:
            print("OK: catálogo histórico disponível via Hugging Face.")
            if cand != prefix:
                print(f"Sugestão: configure FLASH_VIEW_HF_PREFIX = {cand!r}")
            return 0
    print("ERRO: autenticou no Dataset, mas não encontrou históricos nas pastas esperadas.")
    print("Confira se 02_DAILY/, 03_MONTHLY/ e 04_YEARLY/ foram enviados ao Dataset.")
    return 4


if __name__ == "__main__":
    sys.exit(main())
