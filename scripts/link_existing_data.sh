#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Uso: bash scripts/link_existing_data.sh '/caminho/para/dashboard_glm_v3'"
  exit 1
fi

OLD="$(cd "$1" && pwd)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/data"

for name in raw municipalities processed flashes; do
  src="$OLD/data/$name"
  dst="$ROOT/data/$name"
  if [ -e "$src" ]; then
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      echo "Mantendo existente: $dst"
    else
      ln -s "$src" "$dst"
      echo "Ligado: $dst -> $src"
    fi
  fi
done

echo
echo "Dados reaproveitados sem copiar arquivos grandes."
echo "V4: $ROOT"
echo "V3: $OLD"
