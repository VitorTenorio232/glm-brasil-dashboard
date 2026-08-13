from __future__ import annotations
import streamlit as st

st.set_page_config(page_title="Metodologia GLM", page_icon="ℹ️", layout="wide")
st.title("ℹ️ Metodologia — GLM Brasil V4")

st.markdown("""
### Conceito do V4
O eixo principal é **Área → Período → Análises**. A área pode ser um município, um estado ou um polígono/retângulo desenhado pelo usuário.

### Unidade de análise
O sistema usa **flashes** do produto GLM-L2-LCFA. Eventos e grupos não são contabilizados como flashes independentes.

### Associação espacial
- Município: centroide do flash dentro do polígono municipal.
- Estado: união dos flashes associados aos municípios da UF.
- Região personalizada: teste ponto-em-polígono diretamente contra a geometria desenhada.

### Produtos calculados dinamicamente
- diário, mensal e anual;
- média mensal climatológica;
- anomalias absoluta, percentual e z-score;
- dias com relâmpagos;
- frequência diária e frequência em dias ativos;
- máximos horário e diário;
- energia, área e duração dos flashes;
- ciclo de 24 h e divisão diurno/noturno;
- sazonalidade mensal e DJF/MAM/JJA/SON;
- ranking estadual/municipal quando a seleção permitir;
- perfil dos 12 meses, máximo e mínimo climatológico para municípios.

### Horário
O usuário pode calcular em UTC ou em horário de Brasília (UTC-3). No V4, a divisão diurno/noturno é fixa: 06:00–17:59 e 18:00–05:59 na base escolhida.

### Escalabilidade
Para históricos grandes, a base primária deve ficar em Parquet particionado por ano/mês/dia/hora. O DuckDB reduz a leitura ao período e aos atributos necessários antes dos cálculos em memória.
""")
