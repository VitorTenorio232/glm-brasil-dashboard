# Histórico de mudanças

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
