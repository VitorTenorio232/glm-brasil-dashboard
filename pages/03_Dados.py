from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Dados GLM", page_icon="💾", layout="wide")
st.title("💾 Dados históricos GLM")

st.info("🚧 **Em breve.** A base histórica GLM está sendo processada e será conectada ao dashboard quando estiver disponível.")
st.markdown(
    """
Enquanto isso, o módulo **📡 Monitoramento** funciona independentemente da base histórica e consulta
os arquivos GLM-L2-LCFA mais recentes diretamente no NOAA/AWS.

Quando os dados processados forem disponibilizados, este espaço voltará a apresentar:

- período histórico disponível;
- estado do processamento;
- produtos diários, mensais e anuais;
- climatologia e anomalias;
- rankings e análises por município/estado/região personalizada.
"""
)
st.page_link("pages/02_Monitoramento.py", label="Abrir monitoramento em tempo real", icon="📡")
