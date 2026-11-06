# Histórico de mudanças

## 2026-11-06 (municípios pequenos)

### Correções
- **Ranking e séries por fração de área:** cada célula de 0,08° passa a ser dividida entre os municípios pela
  fração da sua área, em vez de ir inteira para o município que contém o seu centro. Municípios menores que uma
  célula ficavam com zero ou com a densidade inflada: Santa Cruz de Minas (MG, 3,6 km²) aparecia com
  217 flashes/km² em 2025 e agora tem 10,6 (vizinhos: 9–13); os municípios com zero flashes em 2025 caíram de 178
  para 17. Totais do Brasil e o ranking dos estados não mudam. Os rankings 2020–2025 em `05_RANKINGS` foram
  refeitos com o novo `build_glm_admin_rankings.py`.

## 2026-11-02 (Tendência)

- **Tendência — 4 cartões:** 0–10, 10–20 e 20–30 min (as três janelas da tendência) e a tendência observada;
  antes a janela de 20–30 min era calculada mas não aparecia.

- **Tendência — opção Arquivo:** área de um shapefile (ZIP), KML, KMZ ou GeoJSON (até 20 MB; usa os polígonos),
  ou reaproveita a área já importada na aba ao vivo.

### Novidades
- **Tendência com 4 tipos de área:** Pontual (clique no mapa ou coordenadas, com raio), Retângulo (desenhado
  no mapa com a ferramenta ▭ ou digitado), Estados e Municípios — nestes dois, vários de uma vez (a análise
  usa a união das áreas). A tabela "Panorama por estado" continua abrindo o estado clicado.

## 2026-11-02

### Novidades
- **Base histórica até 31/12/2025** (2024 e 2025: diário, mensal e anual). Os avisos do site usam a data-limite
  configurada em vez de "2023" fixo.
- `scripts/accumulate_glm.py`: acumula diário → mensal e mensal → anual com a mesma regra da base original
  (contagem somada; energia, área e duração com média ponderada pela contagem). Validado refazendo
  jan/2024, mai/2025 e o anual de 2024: contagens idênticas e médias com diferença ≤ 4·10⁻⁷.
  Usado para gerar abr/2025 (troca GOES-16 → GOES-19 em 07/04) e o anual de 2025.

### Correções
- A legenda "Anos na base" agora mostra também os anos com dados **diários** (antes, na escala diária só
  aparecia 2023 sem explicação, porque a pasta 02_DAILY tem menos anos que a mensal/anual).

## 2026-10-26

### Correções
- **Mapa ao vivo:** os relâmpagos só apareciam depois de clicar em "Ao vivo"; agora aparecem ao abrir.
- **Velocidade:** leitura dos arquivos GLM com `h5py` (≈2 s em vez de ≈10 min no Windows na primeira carga).
- **Estado/Município quebrados:** `geobr 1.0.0` não funciona com `duckdb 2.x`; versão do duckdb fixada (`<2`).
- **Base histórica:** a lista de arquivos do Hugging Face é relida a cada 6 h (antes, anos enviados depois,
  como 2023, só apareciam após reiniciar o app). A Climatologia mostra os anos disponíveis.
- Texto dos botões principais estava quase invisível; rodapé só aparecia na aba Ranking;
  datas da imagem do ranking saíam como "2020-01-01 00:00:00".

### Novidades
- **Tendência:** análise por **estado inteiro** e **panorama das 27 UFs** (clique para abrir o estado).
- **Climatologia:** produto **Anomalia** (período − média dos anos de referência), com escala azul/vermelha.
- **Séries temporais:** opção **comparar com outra área** (gráfico, PNG e CSV com as duas).
- Aba ao vivo reorganizada: números numa linha (incluindo o atraso da fonte) e mapa logo abaixo.
- Gráficos no tema claro do site; CSS unificado e ajustado para celular; explicação de "o que é um flash".

### Repositório
- Removidos backups antigos e um workflow duplicado; documentos da V4 movidos para `docs/historico/`.
- Um único `secrets.toml.example`; `.gitignore` reorganizado; README reescrito.
- Novo workflow **Testes do site** (lint + pytest + abertura do app) a cada push.
