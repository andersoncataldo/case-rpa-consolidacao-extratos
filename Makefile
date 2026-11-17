PYTHON ?= python

.PHONY: instalar preparar rodar painel testar testar-gemini limpar

instalar:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install --no-build-isolation --no-deps -e .

preparar:
	$(PYTHON) scripts/preparar_entrada.py

rodar:
	$(PYTHON) -m rpa_extratos --entrada entrada --saida saida --logs logs

painel:
	$(PYTHON) -m streamlit run app/streamlit_app.py

testar:
	pytest -m "not gemini" -v

testar-gemini:
	pytest -v

limpar:
	rm -rf .pytest_cache saida/*.xlsx logs/*.log logs/*.json
