from __future__ import annotations
import streamlit as st
from src.v4_repository import FlashesRepository
from src.v4_ui import geometry_path

st.set_page_config(page_title="Dados GLM", page_icon="💾", layout="wide")
st.title("💾 Dados e estado do pipeline")
repo = FlashesRepository()

if repo.exists():
    tmin, tmax = repo.available_range()
    st.success("Base individual de flashes disponível.")
    st.write(f"**Fonte:** `{repo.source_description()}`")
    st.write(f"**Período UTC:** {tmin} → {tmax}")
else:
    st.error("Base individual de flashes não encontrada.")

st.write(f"**Geometria usada no frontend:** `{geometry_path()}`")

st.subheader("Processamento de um intervalo GLM")
st.code("""python scripts/process_glm.py \\
  --raw-dir data/raw \\
  --municipalities data/municipalities/municipios_brasil.gpkg \\
  --output data/processed \\
  --save-flashes""")

st.subheader("Histórico grande")
st.code("""python scripts/ingest_partitioned.py \\
  --raw-dir data/raw \\
  --municipalities data/municipalities/municipios_brasil.gpkg \\
  --output data/flashes""")
st.info("No V4, os cálculos da Análise partem dos flashes individuais. As tabelas diária/mensal/anual são produtos derivados da seleção do usuário.")
