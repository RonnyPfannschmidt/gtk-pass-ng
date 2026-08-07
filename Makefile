# Development entry points, and the one definition of what "check the project"
# means. There is no CI; the pre-commit hook and these targets are the gate.

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

FLATPAK_ID := io.github.RonnyPfannschmidt.GTKPass
FLATPAK_MANIFEST := build-aux/$(FLATPAK_ID).yml

.PHONY: help venv sync hooks ui schemas check test test-gui build run run-dev \
	devstore flatpak flatpak-run flatpak-lint flatpak-lint-repo clean

help:
	@echo "sync     create the environment, install dependencies and git hooks"
	@echo "hooks    install the pre-commit hook into .git"
	@echo "ui       compile Blueprint .blp sources to .ui"
	@echo "schemas  compile the GSettings schema"
	@echo "check    run every pre-commit hook (lint, format, types)"
	@echo "test     run the test suite headless"
	@echo "build    build the wheel and sdist"
	@echo "run      launch the application (make run ARGS=\"--debug\")"
	@echo "devstore create a throwaway store with fake passwords"
	@echo "run-dev  launch against the throwaway store, never the real one"
	@echo "flatpak  build and install the Flatpak for the current user"
	@echo "flatpak-run   run the installed Flatpak"
	@echo "flatpak-lint  check the manifest against Flathub's rules"
	@echo "flatpak-lint-repo  build to a repo and run Flathub's repo checks"
	@echo "clean    remove build and cache artefacts"

venv:
	uv venv --system-site-packages --python $(SYSTEM_PYTHON)

sync: venv
	UV_NO_SYNC=0 uv sync --all-extras $(NO_INSTALL)
	$(MAKE) hooks

# `check` only tells you about a problem after it is committed. This runs the
# same hooks on the way in, which is the point at which they are still cheap.
hooks:
	uv run pre-commit install

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

# Pass arguments through: make run ARGS="--debug"
run:
	./run_app.sh $(ARGS)

# A store full of invented passwords, for manual testing and screenshots.
# Use this instead of the real one; see src/gtkpass/safety.py.
DEV_STORE := .dev/store
DEV_GNUPGHOME := .dev/gnupg
# A bare repository on disk, so the sync button is exercisable without a
# network, an ssh agent or the sandbox permissions sync would otherwise need.
DEV_REMOTE := .dev/remote.git

devstore:
	./scripts/make-dev-store.sh $(DEV_STORE) $(DEV_GNUPGHOME) $(DEV_REMOTE)

# The 0 matters. This launches through run_app.sh, which opts in to the real
# store by default; without turning it back off the development run would have
# the guard disabled. The scratch store is opened on its own merits -- it is
# marked as throwaway -- and everything else stays refused.
run-dev: devstore
	PASSWORD_STORE_DIR=$(PWD)/$(DEV_STORE) GNUPGHOME=$(PWD)/$(DEV_GNUPGHOME) \
		GTKPASS_ALLOW_REAL_STORE=0 ./run_app.sh $(ARGS)

# Builds against org.gnome.Sdk, which --install-deps-from pulls from Flathub on
# the first run. That is a substantial download.
#
# The remote has to exist in the *user* installation: a system-wide flathub is
# not visible to `--user --install-deps-from=flathub`, which fails with "No
# remote refs found" however well configured the system one is.
flatpak:
	flatpak remote-add --user --if-not-exists \
		flathub https://dl.flathub.org/repo/flathub.flatpakrepo
	flatpak-builder --force-clean --user --install --install-deps-from=flathub \
		.flatpak-build $(FLATPAK_MANIFEST)

# --no-documents-portal because this application opens no file chooser and
# exports no document, so the portal is other applications' files mounted into
# a password manager for nothing -- and one more thing whose absence stops it
# launching. It has to be passed per run: no manifest or override option
# expresses it, and X-Flatpak-RunOptions in the desktop file does not either.
flatpak-run:
	flatpak run --no-documents-portal $(FLATPAK_ID) $(ARGS)

# Flathub runs these on submission; they catch permission and metadata problems
# that would otherwise surface during review. The repo check needs a build, and
# sees things the manifest check cannot -- missing screenshots, for one.
flatpak-lint:
	flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest \
		$(FLATPAK_MANIFEST)

flatpak-lint-repo:
	flatpak-builder --force-clean --user --repo=.flatpak-repo \
		.flatpak-build $(FLATPAK_MANIFEST)
	flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo \
		.flatpak-repo

clean:
	rm -rf build/ dist/ htmlcov/ .coverage .pytest_cache/ .ruff_cache/ .mypy_cache/
	rm -rf .flatpak-build/ .flatpak-builder/ .flatpak-repo/
	rm -f data/gschemas.compiled
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .dev/
