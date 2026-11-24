"""Mensagens de erro para quem usa o site, sem traceback, caminhos do servidor nem tokens.

``st.exception()`` não respeita ``client.showErrorDetails`` (ver a documentação do Streamlit): os
blocos "Detalhes técnicos" mostravam o traceback completo a qualquer visitante, com caminhos do
servidor e do cache. O traceback completo vai para o log; com ``FLASH_VIEW_DEBUG=1`` o site volta a
mostrá-lo (uso local).
"""
from __future__ import annotations

import logging
import os
import re

import streamlit as st

_LOG = logging.getLogger("flash_view")
# Caminho de arquivo (C:\\... ou /...), sem pegar URLs (https://host/...).
_PATH = re.compile(r"(?:\b[A-Za-z]:[\\/]|(?<![\w:/.])/)(?:[^\s'\"<>|:\\/]+[\\/])+")
_HF_TOKEN = re.compile(r"\bhf_[A-Za-z0-9]{16,}")


def public_message(exc: BaseException, *, with_type: bool = False) -> str:
    """Texto do erro com caminhos trocados por ``…/`` e tokens por ``***``."""
    text = str(exc) or type(exc).__name__
    for secret in (os.getenv("HF_TOKEN"),):
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    text = _HF_TOKEN.sub("hf_***", text)
    text = _PATH.sub("…/", text)
    if with_type and str(exc):
        text = f"{type(exc).__name__}: {text}"
    return text[:500]


def show_error_details(exc: BaseException, label: str = "Detalhes técnicos") -> None:
    """Expander com o tipo e a mensagem do erro (sem traceback); o traceback vai para o log."""
    _LOG.error("Erro mostrado na página: %s", public_message(exc, with_type=True), exc_info=exc)
    with st.expander(label):
        if os.getenv("FLASH_VIEW_DEBUG") == "1":
            st.exception(exc)
        else:
            st.code(public_message(exc, with_type=True), language=None, wrap_lines=True)
            st.caption("O registro completo do erro fica no log do servidor.")


def error_text(exc: BaseException) -> str:
    """Mensagem curta para ``st.error(f"...: {error_text(exc)}")``; registra o traceback no log."""
    _LOG.warning("Erro mostrado na página: %s", public_message(exc, with_type=True), exc_info=exc)
    return public_message(exc)
