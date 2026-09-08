#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".streamlit" / "secrets.toml"


def load_local_secrets() -> dict:
    if not SECRETS.exists():
        return {}
    with SECRETS.open("rb") as f:
        return tomllib.load(f)


def main() -> int:
    secrets = load_local_secrets()
    repo = os.getenv("FLASH_VIEW_HF_REPO") or secrets.get("FLASH_VIEW_HF_REPO")
    prefix = os.getenv("FLASH_VIEW_HF_PREFIX") or secrets.get("FLASH_VIEW_HF_PREFIX", "")
    token = os.getenv("HF_TOKEN") or secrets.get("HF_TOKEN")

    if not repo:
        print("ERRO: FLASH_VIEW_HF_REPO não está configurado.")
        print("Crie .streamlit/secrets.toml a partir de .streamlit/secrets.example.toml.")
        return 2

    # token=None permite usar o login local já salvo por `hf auth login`.
    api = HfApi(token=token or None)
    try:
        info = api.repo_info(repo_id=repo, repo_type="dataset")
        files = api.list_repo_files(repo_id=repo, repo_type="dataset")
    except Exception as exc:
        print("ERRO ao acessar o Dataset privado.")
        print(f"Repositório: {repo}")
        print(f"Detalhe: {type(exc).__name__}: {exc}")
        print("Verifique HF_TOKEN, permissões do token e o nome do repositório.")
        return 3

    prefix = str(prefix).strip("/")
    if prefix:
        pref = prefix + "/"
        files = [f[len(pref):] for f in files if f.startswith(pref)]

    nc = [f for f in files if f.endswith(".nc")]
    counts = {
        "01_HOURLY": sum(f.startswith("01_HOURLY/") for f in nc),
        "02_DAILY": sum(f.startswith("02_DAILY/") for f in nc),
        "03_MONTHLY": sum(f.startswith("03_MONTHLY/") for f in nc),
        "04_YEARLY": sum(f.startswith("04_YEARLY/") for f in nc),
    }

    print("Conexão OK")
    print(f"Dataset: {repo}")
    print(f"Privado: {getattr(info, 'private', 'desconhecido')}")
    print(f"Prefixo: {prefix or '(raiz)'}")
    print(f"NetCDF encontrados: {len(nc)}")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    if not counts["02_DAILY"]:
        print("\nAVISO: não encontrei arquivos em 02_DAILY; as séries diárias não ficarão disponíveis.")

    if not counts["03_MONTHLY"] and not counts["04_YEARLY"]:
        print("\nAVISO: não encontrei 03_MONTHLY nem 04_YEARLY.")
        print("Se os arquivos estiverem, por exemplo, em OUTPUT/03_MONTHLY, use:")
        print('FLASH_VIEW_HF_PREFIX = "OUTPUT"')
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
