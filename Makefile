PYTHON ?= .venv/bin/python
NPM ?= npm
WEB_DIR ?= web

.PHONY: test test-python test-web typecheck build check

test: test-python test-web

test-python:
	$(PYTHON) -m pytest

test-web:
	$(NPM) --prefix $(WEB_DIR) test

typecheck:
	$(NPM) --prefix $(WEB_DIR) exec --no -- tsc --noEmit --project $(WEB_DIR)/tsconfig.json

build:
	$(NPM) --prefix $(WEB_DIR) run build

check: test typecheck build
