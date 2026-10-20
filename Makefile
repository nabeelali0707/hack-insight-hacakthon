# BijliCast - one command per pipeline stage.
# On Windows without make:  python run.py <target>   (same targets)

PYTHON ?= python
export PYTHONPATH := src

.PHONY: data data-fast quality model optimize forecast agent golden flow serve export-runs test all

## Rebuild everything from an empty data/ folder: fetch + SHA-256 verify -> cleaned -> gold -> quality checks
data:
	$(PYTHON) -m bijlicast.cli data

## Same, but reuse raw files already on disk (still SHA-256 verified)
data-fast:
	$(PYTHON) -m bijlicast.cli data --keep-raw

quality:
	$(PYTHON) -m bijlicast.cli quality

## Train, evaluate once against the declared baseline, write report + figures
model:
	$(PYTHON) -m bijlicast.model.train
	$(PYTHON) -m bijlicast.model.report

## Optimization experiments (validation only) -> docs/optimization_log.md
optimize:
	$(PYTHON) -m bijlicast.model.optimize

## Live outlook (current + next month), Peak Cost Lens, drift monitor
forecast:
	$(PYTHON) -m bijlicast.model.forecast
	$(PYTHON) -m bijlicast.insight.costlens
	$(PYTHON) -m bijlicast.quality.drift

## Build the document index (cached by document SHA-256) and run the golden question set
agent:
	$(PYTHON) -m bijlicast.insight.index
	$(PYTHON) -m bijlicast.insight.evaluate

golden:
	$(PYTHON) -m bijlicast.insight.evaluate

## One supervised pipeline run through Prefect / serve on schedule "5 * * * *" / export run history
flow:
	$(PYTHON) -m bijlicast.pipeline.flow run

serve:
	$(PYTHON) -m bijlicast.pipeline.flow serve

export-runs:
	$(PYTHON) -m bijlicast.pipeline.flow export

test:
	$(PYTHON) -m pytest -q tests

all: data model forecast agent
