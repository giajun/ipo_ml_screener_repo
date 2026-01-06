.PHONY: venv install refresh app

venv:
	python -m venv .venv

install:
	. .venv/bin/activate && pip install -r requirements.txt && pip install -e .

refresh:
	. .venv/bin/activate && python -m ipo_ml_screener.cli refresh --days-since-ipo 365 --limit 120

app:
	. .venv/bin/activate && streamlit run app.py
