# GLM Brasil V4 — migração do V3

O V4 mantém o backend validado do V3 (download GLM, leitura LCFA, QC, associação municipal, Parquet/DuckDB e Earth Engine opcional), mas muda o produto principal para:

**Área → Período → Análises**

## Área
- Município
- Estado
- Região personalizada desenhada como polígono ou retângulo no mapa de satélite

## Produtos calculados para a seleção
- diário, mensal e anual
- média mensal climatológica
- anomalias absoluta, percentual e z-score
- dias com relâmpagos
- flashes/dia e flashes/dia ativo
- máximos horário e diário
- duração, energia e área dos flashes
- ciclo de 24 h e diurno/noturno
- sazonalidade mensal e DJF/MAM/JJA/SON
- ranking municipal para seleção estadual
- ranking estadual e municipal para região personalizada
- para município: perfil dos 12 meses, quantidade total, média, mínimo, máximo, mês climatologicamente mais ativo e menos ativo

## Pré-requisito importante
A tela V4 consulta os flashes individuais. Processe o GLM com:

```bash
python scripts/process_glm.py \
  --raw-dir data/raw \
  --municipalities data/municipalities/municipios_brasil.gpkg \
  --output data/processed \
  --save-flashes
```

Para histórico grande, use `scripts/ingest_partitioned.py` e mantenha `data/flashes/` particionado.

## Malha leve para o frontend
A malha completa continua sendo usada nos cálculos espaciais. Para o navegador:

```bash
python scripts/prepare_web_geometry.py --tolerance-m 1000
```

Então execute:

```bash
python -m streamlit run app.py
```
