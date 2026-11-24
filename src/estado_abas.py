"""Campos que sobrevivem à troca de aba.

O app só desenha a aba aberta (``if tab.open``), e o Streamlit apaga o valor de todo campo que passa uma execução
sem ser desenhado. Por isso, sair da aba ao vivo e voltar zerava a área escolhida: a barra "Área no mapa" voltava
para "nenhuma", enquanto o arquivo importado (guardado à parte na sessão) continuava no mapa.

``keep_widget_values`` guarda uma cópia dos valores enquanto os campos existem e, quando voltam, devolve a cópia
ANTES de eles serem criados. Campos com valor padrão (``value=``/``default=``) não podem receber valor pela sessão
sem o Streamlit avisar; para esses, use ``kept_value`` como padrão do próprio campo.
"""
from __future__ import annotations

from collections.abc import Iterable

import streamlit as st

_STORE = "_fv_kept_widgets"


def keep_widget_values(restore: Iterable[str] = (), remember: Iterable[str] = ()) -> None:
    """Chame no começo da aba, antes de criar os campos.

    ``restore``: campos sem valor padrão; a cópia volta pela sessão. ``remember``: campos com valor padrão; só
    guarda a cópia (leia com ``kept_value``).
    """
    restore = tuple(restore)
    store = st.session_state.setdefault(_STORE, {})
    for key in (*restore, *remember):
        if key in st.session_state:
            store[key] = st.session_state[key]
        elif key in restore and key in store:
            st.session_state[key] = store[key]


def kept_value(key: str, default):
    """Valor guardado de um campo com padrão (``remember``), ou ``default`` se nunca foi mudado."""
    return st.session_state.get(_STORE, {}).get(key, default)
