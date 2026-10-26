.PHONY: install test lint compile app

install:
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest -q

lint:
	python -m ruff check app.py src tests --select F

compile:
	python -m compileall -q app.py src scripts tests

app:
	python -m streamlit run app.py
