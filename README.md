
## Instalação V4 limpa

Para substituir a V3 sem aplicar patch, siga `INSTALACAO_LIMPA_V4.md`.
A V4 deve ser extraída em uma pasta nova e pode reutilizar apenas os diretórios de dados da V3.
# ⚡ GLM Brasil — V4

Dashboard de análise espacial e temporal de flashes do **GOES Geostationary Lightning Mapper (GLM)** com Python, Streamlit, GeoPandas, DuckDB/Parquet e integração opcional com Google Earth Engine.

A V4 mantém o backend validado da V3 e muda o produto principal para:

> **Área → Período → Análises**

## Produto principal

O usuário escolhe uma das três áreas:

1. **Município** — UF + município;
2. **Estado** — UF;
3. **Região personalizada** — polígono ou retângulo desenhado diretamente em um mapa de satélite.

Depois escolhe o período e executa a análise. Todos os produtos são recalculados para exatamente aquela seleção.

## Produtos do V4

- mapa de satélite com flashes;
- modo de últimos 15 min: vermelho 0–5, azul 5–10, verde 10–15 min;
- mapa de calor para períodos grandes;
- contagem e densidade de flashes;
- séries diária, mensal e anual;
- média mensal climatológica;
- anomalias absoluta, percentual e z-score;
- dias com relâmpagos;
- flashes/dia e flashes/dia ativo;
- máximos horário e diário;
- duração, energia e área dos flashes: média, mediana, desvio, P90, P95, P99 e máximo;
- ciclo de 24 h;
- divisão diurno/noturno;
- sazonalidade mensal e DJF/MAM/JJA/SON;
- **Estado:** ranking municipal;
- **Região personalizada:** ranking estadual e municipal usando somente os flashes dentro do polígono;
- **Município:** perfil dos 12 meses, total, média, mediana, mínimo, máximo, participação climatológica e identificação do mês climatologicamente mais/menos ativo.

## Arquitetura

```text
NOAA/AWS GLM-L2-LCFA
        ↓
    NetCDF 20 s
        ↓
 xarray + QC
        ↓
 flash_lat / flash_lon
        ↓
 GeoPandas + municípios IBGE
        ↓
 flashes individuais enriquecidos
        ↓
 Parquet / DuckDB
        ↓
┌──────────────┬──────────────┬────────────────────┐
│ Município    │ Estado       │ Polígono desenhado │
└──────────────┴──────────────┴────────────────────┘
        ↓
 filtro espacial + temporal
        ↓
 cálculos dinâmicos V4
        ↓
 Streamlit + mapa de satélite
        ↓
 Earth Engine opcional
```

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

No Ubuntu, se necessário:

```bash
sudo apt update
sudo apt install -y gdal-bin libgdal-dev libgeos-dev libproj-dev python3-dev
```

## Teste do pacote

```bash
python -m pytest -q
python -m compileall -q app.py src scripts pages tests
```

## Preparar municípios

```bash
python scripts/prepare_municipalities.py --year 2025 --full
```

Para evitar enviar centenas de MB ao navegador, gere também a malha leve de visualização:

```bash
python scripts/prepare_web_geometry.py --tolerance-m 1000
```

A malha completa continua sendo usada no spatial join. A versão `municipios_brasil_web.geojson` é apenas para o frontend.

## Processar GLM real

A V4 depende dos **flashes individuais** para permitir região desenhada e cálculos dinâmicos. Portanto use `--save-flashes`:

```bash
python scripts/process_glm.py \
  --raw-dir data/raw \
  --municipalities data/municipalities/municipios_brasil.gpkg \
  --output data/processed \
  --save-flashes
```

Isso deve criar, entre outros:

```text
data/processed/flashes_enriched.parquet
```

## Histórico grande

Para anos de dados, não mantenha tudo em um único Parquet. Use:

```bash
python scripts/ingest_partitioned.py \
  --raw-dir data/raw \
  --municipalities data/municipalities/municipios_brasil.gpkg \
  --output data/flashes
```

A V4 consegue consultar `data/flashes/**/*.parquet` com DuckDB e filtrar período/município/UF antes de materializar os dados em memória.

## Executar

Para evitar conflito com Conda/venv, prefira:

```bash
python -m streamlit run app.py
```

## Páginas

- `app.py` — **Análise**: produto principal V4;
- `pages/02_Monitoramento.py` — últimos 15 minutos disponíveis;
- `pages/03_Dados.py` — diagnóstico da base e comandos de pipeline;
- `pages/04_Metodologia.py` — definições e cálculos.

## Notas metodológicas

- unidade primária: **flash** GLM;
- o GLM mede **total lightning**;
- município: associação pelo centroide do flash;
- região desenhada: teste ponto-em-polígono diretamente nos flashes individuais;
- climatologia mensal inclui períodos sem flashes como zero dentro do intervalo selecionado;
- V4 permite UTC ou Brasília (UTC-3);
- divisão diurno/noturno atual: 06:00–17:59 / 18:00–05:59 na base escolhida;
- para climatologia/anomalias robustas, use vários anos de observações.

Veja também `V4_MIGRACAO.md`.
