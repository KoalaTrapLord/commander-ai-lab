# Commander AI Lab — Developer Makefile
# ======================================
# Targets:
#   make test            — run all tests
#   make test-unit       — run unit tests only (fast)
#   make test-integration— run integration tests
#   make test-benchmark  — run benchmark suite with -s (print timings)
#   make coverage        — run tests with coverage report
#   make serve           — start the FastAPI dev server
#   make lint            — ruff + mypy
#   make fmt             — ruff format
#   make clean           — remove build artefacts

PYTHON  ?= python
UVICORN ?= uvicorn
PORT    ?= 8000
SRC     = src/commander_ai_lab

.PHONY: test test-unit test-integration test-benchmark coverage serve lint fmt clean

test:
	$(PYTHON) -m pytest tests/ -q

test-unit:
	$(PYTHON) -m pytest tests/ -q -m "not integration and not benchmark"

test-integration:
	$(PYTHON) -m pytest tests/test_integration.py -v

test-benchmark:
	$(PYTHON) -m pytest tests/test_benchmark.py -v -s

test-phase3:
	$(PYTHON) -m pytest tests/test_phase3.py -v

test-phase4:
	$(PYTHON) -m pytest tests/test_phase4.py -v

test-phase5:
	$(PYTHON) -m pytest tests/test_phase5.py -v

test-phase6:
	$(PYTHON) -m pytest tests/test_phase6.py -v

test-phase7:
	$(PYTHON) -m pytest tests/test_integration.py tests/test_benchmark.py -v

coverage:
	$(PYTHON) -m pytest tests/ --cov=$(SRC) --cov-report=term-missing --cov-report=html
	echo "Coverage report: htmlcov/index.html"

serve:
	$(UVICORN) commander_ai_lab.web.app:app --reload --port $(PORT)

lint:
	$(PYTHON) -m ruff check $(SRC) tests/
	$(PYTHON) -m mypy $(SRC) --ignore-missing-imports

fmt:
	$(PYTHON) -m ruff format $(SRC) tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .coverage htmlcov .mypy_cache .ruff_cache dist build
