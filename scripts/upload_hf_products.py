#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi


def main():
    parser = argparse.ArgumentParser(
        description="Envia os produtos históricos do Flash View para um Dataset no Hugging Face Hub."
    )
    parser.add_argument("--repo", required=True, help="Ex.: usuario/flash-view-glm-data")
    parser.add_argument("--data-root", required=True, help="Caminho para GLM_Process/OUTPUT")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Envia também 01_HOURLY e 02_DAILY. Sem esta opção, envia apenas 03_MONTHLY e 04_YEARLY.",
    )
    parser.add_argument("--private", action="store_true", help="Cria o Dataset como privado, se ainda não existir.")
    args = parser.parse_args()

    root = Path(args.data_root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Diretório não encontrado: {root}")

    folders = ["03_MONTHLY", "04_YEARLY"]
    if args.all:
        folders = ["01_HOURLY", "02_DAILY", "03_MONTHLY", "04_YEARLY"]

    api = HfApi()
    api.create_repo(repo_id=args.repo, repo_type="dataset", private=args.private, exist_ok=True)

    for name in folders:
        source = root / name
        if not source.exists():
            print(f"[AVISO] Pasta ausente, pulando: {source}")
            continue
        print(f"\nEnviando {source} -> datasets/{args.repo}/{name}")
        api.upload_folder(
            repo_id=args.repo,
            repo_type="dataset",
            folder_path=str(source),
            path_in_repo=name,
            commit_message=f"Add/update Flash View {name}",
        )

    print("\nUpload concluído. Se for interrompido, execute o mesmo comando novamente.")


if __name__ == "__main__":
    main()
