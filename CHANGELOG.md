# Histórico de mudanças

## 2026-11-23 (revisão de segurança, confiabilidade e desempenho)

### Segurança
- **Pillow 13:** `requirements.txt` limitava `Pillow<13`, e o pip-audit apontou 42 vulnerabilidades na 12.3
  corrigidas na 13.0. Agora `Pillow>=13.0,<14` (o streamlit 1.66 aceita); as pranchas PNG/JPEG/GIF saem
  idênticas byte a byte.
- **Nome do arquivo enviado virava HTML/JS no mapa:** o folium põe o tooltip cru numa template string e o
  Leaflet monta a lista de camadas com innerHTML. Um GeoJSON chamado `x<img src=x onerror=alert(1)>.geojson`
  executava script na Tendência (e o rótulo também ia para o mapa da Climatologia). `map_text()` escapa
  HTML, crase e cifrão.
- **"Detalhes técnicos" sem traceback:** `st.exception()` ignora `client.showErrorDetails` e mostrava o
  traceback completo (caminhos do servidor e do cache) a qualquer visitante. `src/erros.py` mostra só o tipo e
  a mensagem, com caminhos e tokens removidos; o traceback vai para o log (`FLASH_VIEW_DEBUG=1` mostra tudo).

### Correções
- **Arquivo GLM corrompido derrubava o ao vivo:** um arquivo ilegível entre os ~270 da janela fazia a busca
  inteira falhar, e como ele ficava no cache de disco o painel continuava fora do ar a cada minuto até o
  arquivo sair da janela (~90 min). Agora o arquivo é ignorado, apagado do cache e baixado de novo na
  atualização seguinte, com um aviso.
- **Lacuna de dados parecia queda de atividade:** 10 min sem arquivos na NOAA apareciam como 246 flashes em
  10–20 min (contra ~2.400), e a Tendência indicava dissipação. O ao vivo e a Tendência avisam quais minutos
  estão sem arquivo.
- **Séries: mês sem arquivo sumia:** o gráfico ligava o mês anterior ao seguinte e o CSV pulava a linha, sem
  distinguir "0 flashes" de "sem observação". Agora o período fica em branco no gráfico, vazio no CSV (nova
  coluna `situacao`: observado / sem arquivo na base) e a aba avisa quais períodos faltam.
- Prazos explícitos para a NOAA (10 s para conectar, 30 s por leitura, 4 tentativas); o padrão do botocore
  era 60 s + 60 s com 5 tentativas, com todas as sessões esperando a mesma busca.

### Desempenho (medido; detalhes na revisão)
- **Gerar mapa (Climatologia):** a máscara de células testava a borda à parte (`intersects_xy` em
  `geometry.boundary`, ~0,35 s em MG, duas vezes por mapa). `cells_in_geometry()` dá a mesma máscara em ~6 ms.
  MG jan/2025: 1,84 s → 0,52 s; repetir a consulta: 1,28 s → 0,26 s.
- **Catálogo lido uma vez:** cada período ou área nova criava outro repositório e relia a lista de arquivos
  (no Hugging Face, uma chamada `list_repo_files` por consulta). Agora usa o repositório já lido.
- **Séries:** PNG, JPEG e CSV montados uma vez por resultado (`_series_downloads`), e os botões de download
  (Séries, Ranking, NetCDF) não rodam a página de novo. Rerun com a série na tela: 1,11 s → 0,15 s.
- **Hugging Face no commit do catálogo:** o catálogo vem de `dataset_info` (lista de arquivos e commit
  numa chamada só, ~0,4 s, em vez dos 5 pedidos de `list_repo_files`), e `hf_hub_download` recebe esse
  commit. Com o arquivo em cache, o download não vai mais à rede (antes: um HEAD por arquivo). Dataset real,
  série mensal de 24 meses com cache: 5,1 s e 24 pedidos → 1,6 s e 0 pedidos; abrir a aba: 2,8 s → 1,8 s.
  Também resolve o alerta B615 do Bandit e mantém catálogo e arquivos no mesmo commit (se o commit sumir do
  Dataset, baixa do commit atual).
- **Ao vivo:** um GET por arquivo em vez de HeadObject + GetObject. Primeira abertura a frio: 545 → 274
  pedidos à NOAA; download dos 271 arquivos: 11,8 s → 7,3 s (média de 3 rodadas).

## 2026-11-23 (anéis do alarme)

### Novidades
- **Alarme com anéis em volta da área**, como na Sala do Céu Nowcasting: além da área, o alarme vigia 20, 50 e
  100 km a partir da **borda** dela. No site, até 20 km toca a sirene, até 50 km abre um aviso âmbar com bipe e
  até 100 km mostra uma linha no painel (e notificação do sistema). Os anéis aparecem tracejados no mapa ao vivo
  e cada um pode ser desmarcado no painel do alarme, que mostra as contagens de cada anel. No script do PC
  (`alarme.aneis_km`), 20 km abre a janela vermelha, 50 km uma janela âmbar e 100 km só avisa o celular. Cada
  anel rearma depois de 30 min sem relâmpagos; os de dentro da área contam, para não tocar de novo quando a
  tempestade sai. A distância até a borda usa um índice dos segmentos da borda (estado de Minas: ~0,1 s).

- **Climatologia e Séries temporais com recorte por arquivo:** nova opção **Arquivo** no recorte (e na segunda
  área da comparação): shapefile em ZIP, KML, KMZ ou GeoJSON, como na aba ao vivo e na Tendência. Dá para
  reaproveitar um arquivo já enviado em outra aba (por exemplo, a bacia subida no mapa ao vivo). O polígono é
  simplificado a ~200 m para a grade de 0,08°; o mapa recorta pelos centros das células e a série usa a fração
  de área de cada célula. As escolhas dessas abas também sobrevivem à troca de aba.

### Correções
- **Área perdida ao trocar de aba:** o site só desenha a aba aberta, e o Streamlit apaga o valor dos campos que
  não foram desenhados. Sair da aba ao vivo e voltar zerava a barra "Área no mapa", mas o arquivo importado
  continuava no mapa, como se fosse uma área aplicada. `src/estado_abas.py` guarda os valores e os devolve ao
  voltar (aba ao vivo e Tendência: tipo de área, ponto, raio, retângulo, estados, municípios e fuso). O arquivo
  importado agora só aparece no mapa ao vivo com "Arquivo" escolhido.
- **Relâmpagos dos anéis no mapa ao vivo:** com uma área escolhida, o mapa só recebia os flashes de dentro dela,
  e os anéis ficavam vazios. Agora vão também os de até 100 km da borda, desenhados mais apagados; desmarcar um
  anel no painel do alarme esconde os flashes dele. Os cartões e as exportações continuam contando só a área.

### Melhorias
- **Tendência:** ao escolher a área (por exemplo, dois municípios), aparece logo abaixo da escolha um quadro
  "Área aplicada" com os flashes da última hora, dos últimos 10 min e a tendência. No celular as colunas
  empilham e o mapa e os cartões ficavam longe da lista, e parecia que nada tinha acontecido. As dicas dizem
  "em Área de interesse" em vez de "ao lado".

## 2026-11-23 (ordem dos flashes)

### Correções
- **Relâmpagos mais recentes sempre por cima dos mais antigos:**
  - mapa ao vivo: o MapLibre ordenava os ícones pela posição na tela; agora usa `symbol-sort-key` pelo horário;
  - mapa da Tendência: as faixas eram adicionadas da mais nova para a mais antiga, e a de 30–60 min ficava por
    cima; agora cada faixa tem o seu pane (0–5 min no topo), e dentro da faixa o mais novo é desenhado por último;
  - pranchas PNG/JPEG e GIF: um só scatter do mais antigo para o mais novo (antes o azul cobria o vermelho).

## 2026-11-07 (alarme)

### Novidades
- **Tendência — botão "Atualizar agora":** a aba não se atualiza sozinha; o botão, ao lado do título, descarta
  o cache e busca os arquivos GLM mais novos. Embaixo dele aparece a hora do último dado (Brasília ou UTC).
- **Área no mapa ao vivo, como na Tendência:** a barra **Área no mapa** troca o botão "Selecionar Área" e o
  "Importar área" de baixo do mapa por cinco tipos: **Pontual** (clique no mapa, coordenadas ou município, com
  raio de 5 a 100 km), **Retângulo** (agora é só arrastar no mapa; dois cliques continuam valendo; ou digitar os
  limites), **Estados**, **Municípios** e **Arquivo** (SHP em ZIP, KML, KMZ, GeoJSON). Um aviso amarelo no mapa
  diz o que fazer, e a área escolhida filtra os números e é a área do alarme. Em telas estreitas as barras de
  área (ao vivo e Tendência) quebram em duas linhas. Código em `src/area_ao_vivo.py`.
- **Botão "Ativar alarme" no mapa ao vivo:** com uma área selecionada (retângulo ou polígono importado), o site
  toca uma sirene em loop e cobre a tela com um aviso vermelho quando cai relâmpago na área (distância e
  direção do mais perto, total em 10 min e horário), até clicar em "Parar alarme". Pisca o título da aba, mostra
  notificação do sistema (se permitida), vibra no Android e mantém a tela acesa. Mesma regra do alarme do
  computador; avisa se o site parar de receber dados. "Testar som" toca alguns segundos. Lógica em
  `src/alarme_navegador.js`; o servidor manda só os flashes da área (`browser_alarm_payload`).
- **Alarme de relâmpagos no computador** (`scripts/alarme_relampagos.py`): olha os arquivos novos do GLM a cada
  minuto (só os que ainda não leu) e, quando há relâmpago na área de observação (ponto com raio, ou polígono de
  KML, KMZ, GeoJSON ou SHP em ZIP), abre uma janela vermelha com som em loop até clicar em "Parar alarme". Toca
  uma vez por tempestade e rearma depois de 30 min sem relâmpagos na área; impede a suspensão do Windows
  enquanto roda e avisa se os dados pararem de chegar. Aviso opcional no celular pelo ntfy (prioridade urgente).
  Configuração em `alarme.toml` (fora do Git; modelo em `alarme.exemplo.toml`). Guia: `docs/ALARME.md`.

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
