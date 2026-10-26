# ⚡ Flash View

Painel web de **relâmpagos totais no Brasil** a partir do sensor **GLM** (Geostationary Lightning Mapper)
do satélite **GOES-19** (NOAA). Feito com Python e Streamlit.

[![Testes do site](../../actions/workflows/tests.yml/badge.svg)](../../actions/workflows/tests.yml)

## O que o site oferece

| Aba | O que mostra |
|---|---|
| ⚡ **Relâmpagos em tempo real** | Flashes dos últimos 30 min no mapa de satélite (atualiza a cada ~60 s), animação da última hora, seleção de área, importação de SHP/KMZ/KML/GeoJSON e exportação PNG/JPEG/GIF. |
| 🌦️ **Climatologia** | Mapas diários, mensais e anuais, climatologias e **anomalias** (período − média dos anos de referência) para Brasil, estado, município, retângulo ou buffer. |
| 📈 **Séries temporais** | Séries diárias, mensais ou anuais de uma área, com opção de **comparar duas áreas**. Download em PNG, JPEG e CSV. |
| 🏆 **Ranking** | Municípios e estados com maior densidade ou número de flashes no período. |
| 📊 **Tendência** | Atividade nos últimos 10/20/30 min em um ponto + raio ou em um **estado inteiro**, e um panorama das 27 UFs (clique numa linha para abrir o estado). |

> Um **flash** é um relâmpago completo detectado do espaço — inclui descargas dentro das nuvens e as que
> tocam o solo. A tendência é observacional; não é previsão nem alerta oficial.

## De onde vêm os dados

- **Tempo real:** arquivos GLM-L2-LCFA (~20 s cada) do bucket público da NOAA na AWS. Não precisa de chave.
- **Histórico (até 31/12/2023):** grades NetCDF processadas, guardadas num Dataset privado do Hugging Face
  (`01_HOURLY`, `02_DAILY`, `03_MONTHLY`, `04_YEARLY`, `05_RANKINGS`). Precisa de `HF_TOKEN`.
- **Limites de estados e municípios:** IBGE, via pacote `geobr`.

## Rodar no seu computador

Requer Python 3.12.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/Mac: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m streamlit run app.py
```

Para as abas históricas, copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e
preencha o `HF_TOKEN`. Sem o token, a aba de tempo real e a Tendência continuam funcionando.

## Publicar no Streamlit Community Cloud

1. Em [share.streamlit.io](https://share.streamlit.io), crie o app apontando para este repositório, branch `main`, arquivo `app.py`.
2. Em **Advanced settings**, escolha **Python 3.12** (o Cloud ignora o `runtime.txt`).
3. Em **Settings → Secrets**, cole o conteúdo do `secrets.toml.example` com o seu token.
4. Cada `push` na `main` atualiza o site automaticamente.

## Estrutura do repositório

```text
app.py                     # interface Streamlit (todas as abas)
src/
  realtime_glm.py          # busca dos arquivos GLM recentes na NOAA/AWS
  glm_reader.py            # leitura rápida dos NetCDF LCFA (h5py, com fallback xarray)
  maplibre_realtime.*      # mapa ao vivo (MapLibre GL JS)
  previsao_flash.py        # aba Tendência e panorama por estado
  alertas_flash.py         # cálculo da tendência 0–10 / 10–20 / 20–30 min
  historical_glm.py        # base histórica, climatologia, anomalia, séries e mapas
  ranking_glm.py           # ranking administrativo
  cartographic_export.py   # pranchas PNG/JPEG/GIF
  export_area.py, spatial_tools.py, map_uploads.py, view_exports.py
scripts/                   # processamento e envio da base histórica ao Hugging Face
tests/                     # testes automatizados (pytest)
desktop/                   # aplicativo Windows (.exe) — ver desktop/COMO-GERAR.md
docs/                      # arquitetura, validação e documentos antigos (docs/historico)
.github/workflows/         # testes do site e build do .exe
```

## Testes

```bash
python -m pytest -q                              # testes automatizados
python -m ruff check app.py src tests --select F # erros de código
```

Os mesmos testes rodam no GitHub a cada `push` (aba **Actions → Testes do site**).

## Histórico de mudanças

Veja [CHANGELOG.md](CHANGELOG.md).
