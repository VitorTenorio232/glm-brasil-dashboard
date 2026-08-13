# Data directory

Os dados utilizados pelo Dashboard GLM não são distribuídos neste repositório.

A estrutura esperada é:

data/
├── raw/              # Arquivos GLM-L2-LCFA NetCDF
├── processed/        # Produtos derivados e flashes enriquecidos
├── flashes/          # Parquet particionado para séries históricas
└── municipalities/   # Malha municipal brasileira

## Fonte dos dados

Os dados de relâmpagos são provenientes do Geostationary Lightning Mapper
(GLM) a bordo dos satélites GOES.

O pipeline do projeto realiza automaticamente:

GLM-L2-LCFA
→ leitura dos flashes
→ controle de qualidade
→ associação espacial
→ agregações temporais
→ análises no dashboard.

Os dados brutos e processados são ignorados pelo Git devido ao volume.
