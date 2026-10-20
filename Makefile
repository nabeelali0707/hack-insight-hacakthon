# BijliCast — one command per pipeline stage.
# On Windows without make:  python run.py data   (same commands)

PYTHON ?= python
export PYTHONPATH := src

.PHONY: data data-fast quality model agent flow test all

## Rebuild everything from an empty data/ folder: fetch + SHA-256 verify -> cleaned -> gold -> quality checks
data:
	$(PYTHON) -m bijlicast.cli data

## Same, but reuse raw files already on disk (still SHA-256 verified)
data-fast:
	$(PYTHON) -m bijlicast.cli data --keep-raw

quality:
	$(PYTHON) -m bijlicast.cli quality

test:
	$(PYTHON) -m pytest -q tests

all: data

## Train, evaluate once against the declared baseline, write report + figures
model:
	$(PYTHON) -m bijlicast.model.train
	$(PYTHON) -m bijlicast.model.report

## Optimization experiments (validation only) -> docs/optimization_log.md
optimize:
	$(PYTHON) -m bijlicast.model.optimize
