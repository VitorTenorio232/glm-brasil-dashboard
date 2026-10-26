# Instalação limpa — GLM Brasil V4

Esta instalação **não aplica patch na V3**. A V4 deve ser extraída em uma pasta nova.
O código antigo permanece intacto e os dados grandes podem ser reaproveitados por links simbólicos.

## 1. Extraia a V4

```bash
cd "$HOME/Dashboard GLM"
unzip ~/Downloads/dashboard_glm_v4_full.zip
cd dashboard_glm_v4_full
```

## 2. Reaproveite somente os dados da V3

Supondo que a V3 continue em:

```text
$HOME/Dashboard GLM/dashboard_glm_v3
```

rode:

```bash
bash scripts/link_existing_data.sh "$HOME/Dashboard GLM/dashboard_glm_v3"
```

Isso reaproveita, quando existirem:

- `data/raw`
- `data/municipalities`
- `data/processed`
- `data/flashes`

Nenhum arquivo do frontend V3 é reutilizado.

## 3. Crie um ambiente Python novo

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Evite executar o `streamlit` do Conda base. Use sempre:

```bash
python -m streamlit run app.py
```

## 4. Garanta que os flashes individuais existem

```bash
ls -lh data/processed/flashes_enriched.parquet
```

Se não existir:

```bash
python scripts/process_glm.py \
  --raw-dir data/raw \
  --municipalities data/municipalities/municipios_brasil.gpkg \
  --output data/processed \
  --save-flashes
```

## 5. Gere a geometria leve do navegador

```bash
python scripts/prepare_web_geometry.py --tolerance-m 1000
```

A malha completa continua sendo usada no backend. O arquivo `municipios_brasil_web.geojson`
é usado apenas na interface.

## 6. Valide

```bash
python -m pytest -q
python -m compileall -q app.py src scripts pages tests
```

Resultado esperado dos testes internos:

```text
10 passed
```

## 7. Execute

```bash
python -m streamlit run app.py
```

A V4 possui a seleção principal:

**Município / Estado / Região personalizada → Período → Análises**.
