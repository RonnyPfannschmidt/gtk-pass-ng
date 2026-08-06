# Development entry points. CI invokes these same targets, so there is one
# definition of what "check the project" means.

BLUEPRINTS := src/gtkpass/ui/blueprints
# GTK4 has no usable headless backend, and a private bus keeps the tests away
# from the developer's real keyring.
HEADLESS := xvfb-run -a dbus-run-session --

.PHONY: help sync ui schemas check test test-gui build run clean

help:
	@echo "sync     install the project and its dev dependencies"
	@echo "ui       compile Blueprint .blp sources to .ui"
	@echo "schemas  compile the GSettings schema"
	@echo "check    run every pre-commit hook (lint, format, types)"
	@echo "test     run the test suite headless"
	@echo "build    build the wheel and sdist"
	@echo "run      launch the application"
	@echo "clean    remove build and cache artefacts"

sync:
	uv sync --all-extras

# Never hand-edit a .ui file: it is generated. Edit the .blp and run this.
ui:
	uv run blueprint-compiler batch-compile $(BLUEPRINTS) $(BLUEPRINTS) $(BLUEPRINTS)/*.blp

schemas:
	glib-compile-schemas data/

check:
	uv run pre-commit run --all-files

test: schemas
	$(HEADLESS) uv run pytest

test-gui: schemas
	$(HEADLESS) uv run pytest -m gui

build:
	uv build

run:
	./run_app.sh

clean:
	rm -rf build/ dist/ htmlcov/ .coverage .pytest_cache/ .ruff_cache/ .mypy_cache/
	rm -f data/gschemas.compiled
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
