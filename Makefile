.PHONY: all build build-onedir clean test lint

all: test lint build

# ---- Development ----

test:
	.venv\Scripts\pytest tests -v

lint:
	.venv\Scripts\ruff check src/tgparser tests
	.venv\Scripts\ruff format --check src/tgparser tests

format:
	.venv\Scripts\ruff format src/tgparser tests

# ---- Building standalone executable ----

build:
	python bin/build_standalone.py

build-onedir:
	python bin/build_standalone.py --onedir

# ---- Cleanup ----

clean:
	rm -rf build dist __pycache__ .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
