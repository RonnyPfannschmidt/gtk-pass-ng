# Development entry points. CI invokes these same targets, so there is one
# definition of what "check the project" means.

BLUEPRINTS := src/gtkpass/ui/blueprints

# PyGObject and pycairo ship as source distributions only, so uv would compile
# them -- which needs cairo, girepository and GTK development headers, and fails
# on a machine that has the runtime but not the -devel packages. Take them from
# the distribution instead: they are already built against the system GTK, which
# is the version the application actually runs on.
#
# Two things are required for that to work. The environment has to be created
# against the *system* interpreter, because a uv-managed Python's site-packages
# does not contain the distribution's bindings. And the packages have to be
# excluded from the sync explicitly.
SYSTEM_PROVIDED := pygobject pycairo
NO_INSTALL := $(foreach package,$(SYSTEM_PROVIDED),--no-install-package $(package))
SYSTEM_PYTHON ?= /usr/bin/python3

# Every target below reuses the environment as-is rather than re-resolving it;
# without this `uv run` re-syncs and tries to build the excluded packages again.
export UV_NO_SYNC := 1

# GTK4 has no usable headless backend, and a private bus keeps the tests away
# from the developer's real keyring.
HEADLESS := xvfb-run -a dbus-run-session --

.PHONY: help venv sync ui schemas check test test-gui build run clean

help:
	@echo "sync     create the environment and install dependencies"
	@echo "ui       compile Blueprint .blp sources to .ui"
	@echo "schemas  compile the GSettings schema"
	@echo "check    run every pre-commit hook (lint, format, types)"
	@echo "test     run the test suite headless"
	@echo "build    build the wheel and sdist"
	@echo "run      launch the application"
	@echo "clean    remove build and cache artefacts"

venv:
	uv venv --system-site-packages --python $(SYSTEM_PYTHON)

sync: venv
	UV_NO_SYNC=0 uv sync --all-extras $(NO_INSTALL)

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
