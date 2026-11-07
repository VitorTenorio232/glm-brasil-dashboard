@echo off
rem Alarme de relampagos do Flash View. De dois cliques para iniciar; feche a janela para parar.
rem Usa, nesta ordem: a variavel FLASHVIEW_PYTHON, o .venv do repositorio ou o python do sistema.
chcp 65001 >nul
cd /d "%~dp0.."
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined FLASHVIEW_PYTHON set "PY=%FLASHVIEW_PYTHON%"
title Flash View - alarme de relampagos
"%PY%" scripts\alarme_relampagos.py %*
pause
