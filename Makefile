.PHONY: test compile demo app webgeom

test:
	python -m pytest -q

compile:
	python -m compileall -q app.py src scripts pages tests

demo:
	python scripts/simulate_demo.py --root data/demo

webgeom:
	python scripts/prepare_web_geometry.py --tolerance-m 1000

app:
	python -m streamlit run app.py
