"""Trocar de aba não pode zerar a área escolhida (src/estado_abas.py)."""
from streamlit.testing.v1 import AppTest


def _app():
    import streamlit as st

    from src.estado_abas import keep_widget_values, kept_value

    # Como o app: a aba só é desenhada quando está aberta.
    if st.session_state.get("aba_aberta", True):
        keep_widget_values(restore=["area"], remember=["raio"])
        st.multiselect("Área", ["Arquivo", "Pontual"], key="area")
        st.slider("Raio", 5, 100, kept_value("raio", 20), 5, key="raio")


def test_area_volta_depois_de_trocar_de_aba():
    at = AppTest.from_function(_app).run()
    at.multiselect(key="area").select("Arquivo").run()
    at.slider(key="raio").set_value(50).run()

    at.session_state["aba_aberta"] = False  # outra aba: os campos não são desenhados
    at.run()
    assert "area" not in at.session_state  # o Streamlit apagou o valor do campo

    at.session_state["aba_aberta"] = True  # volta para a aba
    at.run()
    assert at.multiselect(key="area").value == ["Arquivo"]
    assert at.slider(key="raio").value == 50
    assert not at.exception and not at.warning  # sem o aviso de valor duplicado do Streamlit
