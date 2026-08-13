# Arquitetura operacional

```text
NOAA NODD / AWS
      │
      │ GLM-L2-LCFA ~20 s
      ▼
download_glm.py
      │
      ├── piloto: process_glm.py
      │
      └── produção: ingest_partitioned.py
                         │
                         ▼
                Parquet particionado
                         │
                         ▼
                DuckDB aggregation
                         │
      ┌──────────────────┴─────────────────┐
      ▼                                    ▼
data/processed                      Earth Engine Asset
(tabelas)                           (malha municipal)
      │                                    │
      └──────────────────┬─────────────────┘
                         ▼
                     Streamlit
```

## Por que separar GLM e Earth Engine

O GLM bruto é uma coleção de registros vetoriais/temporais em arquivos de alta frequência. O processamento municipal é mais eficiente em Python/Parquet/DuckDB. O Earth Engine entra depois, como mecanismo de renderização/tiles da distribuição espacial municipal.
