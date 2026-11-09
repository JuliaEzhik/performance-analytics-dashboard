VENV   ?= .venv
PY     := $(VENV)/bin/python
DBT    := cd dbt && ../$(VENV)/bin/dbt
DBTARG := --profiles-dir .

.PHONY: setup generate dbt data app test screenshots clean

setup:            ## create the virtualenv and install dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt
	$(DBT) deps $(DBTARG)

generate:         ## write synthetic raw tables into data/warehouse.duckdb
	$(PY) data_gen/generate_data.py

dbt:              ## seeds + models + tests (bronze -> silver -> gold)
	$(DBT) seed $(DBTARG)
	$(DBT) build $(DBTARG)

data: generate dbt  ## full data refresh

app:              ## start the Streamlit dashboard on http://localhost:8501
	$(VENV)/bin/streamlit run dashboard/app.py

test:             ## dbt tests only
	$(DBT) test $(DBTARG)

screenshots:      ## regenerate docs/screenshots (needs the app running + playwright)
	$(PY) scripts/take_screenshots.py --url http://localhost:8501

clean:
	rm -rf data dbt/target dbt/logs dbt/dbt_packages
