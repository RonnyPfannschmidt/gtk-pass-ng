# Development entry points, and the one definition of what "check the project"
# means. CI runs these same targets, so there is one definition rather than two
# that drift; the pre-commit hook runs `check` on the way in.

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

# Which interpreter that is, asked rather than assumed. This was hardcoded to
# /usr/bin/python3, which is right on most machines and quietly wrong on one
# whose bindings belong to a different minor version -- and quietly is the
# problem, the answer arriving much later as an ImportError from inside the
# application. scripts/system-python.sh settles it the only way that settles it,
# by importing both, and says what to install when nothing can.
#
# Left empty here so the script chooses. Name one to override, in either
# spelling, and it is checked rather than taken on trust:
#
#   make sync SYSTEM_PYTHON=/usr/bin/python3.13
SYSTEM_PYTHON ?=
SELECT_PYTHON := ./scripts/system-python.sh $(SYSTEM_PYTHON)

# The interpreter the suite runs against, and the reason `test` is one target
# rather than three spellings of it. The default is the development
# environment; CI overrides it with the interpreter that has the wheel or the
# RPM installed, so what CI runs is this target rather than a copy of it that
# drifts -- which is what the top of this file claims and, until this existed,
# was not true of the tests.
#
#   make test                                     the editable install
#   make test PYTHON=build/wheel-venv/bin/python   an installed wheel
#   make test PYTHON=python3                      an installed rpm
#
# Assigned rather than defaulted, so an exported PYTHON in somebody's shell
# cannot redirect the suite behind their back. A command-line override still
# wins, that being the spelling above.
PYTHON := uv run python

# Whether the suite about to run is the one that reads the working copy. Only
# the default does; every override above names an interpreter with the package
# installed into it. See UI_PREREQUISITES below, which is the one thing that
# turns on the difference.
ifeq ($(PYTHON),uv run python)
TESTS_THE_WORKING_COPY := yes
endif

# Every target below reuses the environment as-is rather than re-resolving it;
# without this `uv run` re-syncs and tries to build the excluded packages again.
export UV_NO_SYNC := 1

# GTK4 has no usable headless backend, a private bus keeps the tests away from
# the developer's real keyring, and a private XDG_RUNTIME_DIR keeps them away
# from the real document portal -- whose mount a test run otherwise tears down
# for the whole session, silently. The script is the one definition of all
# three, shared with packaging/test-sysext.sh and the test jobs in CI; the
# reasoning, including why none of it can move into conftest.py, is in there.
HEADLESS := ./scripts/headless-session.sh

FLATPAK_ID := io.github.RonnyPfannschmidt.GTKPass
FLATPAK_MANIFEST := build-aux/$(FLATPAK_ID).yml

# -- what is built from what ---------------------------------------------------
#
# The packaging targets used to be phony, and the scripts behind them decided
# for themselves whether there was anything to do. build-sysext.sh builds an RPM
# only when dist/rpm holds none at all, so an image built the day after a change
# was an image of the day before it -- silently, and with the version in the
# filename saying so to anyone who thought to look.
#
# So the outputs are files with prerequisites now, and make decides. The phony
# names stay as the way to ask for them.
BLUEPRINT_SOURCES := $(wildcard $(BLUEPRINTS)/*.blp)
UI_FILES := $(BLUEPRINT_SOURCES:.blp=.ui)

SCHEMA_SOURCES := $(wildcard data/*.gschema.xml)
COMPILED_SCHEMAS := data/gschemas.compiled

PYTHON_SOURCES := $(shell find src -name '*.py' -not -path '*/__pycache__/*')
DATA_SOURCES := $(wildcard data/*.xml) $(wildcard data/*.desktop) \
	$(shell find data/icons -type f 2>/dev/null)

# The version comes from the git tags through setuptools-scm, so a commit with
# no file change still produces a different package -- which is what the
# packaging targets were getting wrong. HEAD moves on checkout, and the branch
# ref it names moves on commit; both together are "a different revision is
# checked out now". Not the index, which `git status` rewrites when it refreshes
# its stat cache, and which would put a container build behind every status.
GIT_DIR := $(shell git rev-parse --git-dir 2>/dev/null)
GIT_REF := $(shell git symbolic-ref -q HEAD 2>/dev/null)
GIT_STATE := $(wildcard $(GIT_DIR)/HEAD $(if $(GIT_REF),$(GIT_DIR)/$(GIT_REF)))

# Everything a package is built out of.
PACKAGE_SOURCES := $(PYTHON_SOURCES) $(UI_FILES) $(DATA_SOURCES) $(GIT_STATE) \
	pyproject.toml uv.lock

# The RPM's own name carries the version, so it cannot be named as a target
# before it is built. The stamp stands in for it: build-rpm.sh empties dist/rpm
# before it starts, so nothing older survives beside what it produces.
RPM_STAMP := dist/rpm/.built

# An extension names the system it was built for and systemd refuses it
# anywhere else, so the image for *this* machine is what these targets mean.
OS_ID := $(shell . /etc/os-release && echo $$ID)
OS_VERSION_ID := $(shell . /etc/os-release && echo $$VERSION_ID)
SYSEXT_IMAGE := dist/sysext/gtkpass-$(OS_ID)-$(OS_VERSION_ID).raw

.PHONY: help venv sync hooks ui schemas check test test-gui test-wheel build \
	run run-dev devstore flatpak flatpak-run flatpak-lint flatpak-lint-repo \
	rpm sysext sysext-test sysext-install clean

help:
	@echo "sync     create the environment, install dependencies and git hooks"
	@echo "hooks    install the pre-commit hook into .git"
	@echo "ui       compile Blueprint .blp sources to .ui"
	@echo "schemas  compile the GSettings schema"
	@echo "check    run every pre-commit hook (lint, format, types)"
	@echo "test     run the test suite headless"
	@echo "test-gui run only the tests that need a display"
	@echo "test-wheel  install the built wheel and run the suite against that"
	@echo "build    build the wheel and sdist"
	@echo "run      launch the application (make run ARGS=\"--debug\")"
	@echo "devstore create a throwaway store with fake passwords"
	@echo "run-dev  launch against the throwaway store, never the real one"
	@echo "flatpak  build and install the Flatpak for the current user"
	@echo "flatpak-run   run the installed Flatpak"
	@echo "flatpak-lint  check the manifest against Flathub's rules"
	@echo "flatpak-lint-repo  build to a repo and run Flathub's repo checks"
	@echo "rpm      build the RPM in a Fedora container"
	@echo "sysext   build a systemd-sysext image for Bluefin/Silverblue"
	@echo "sysext-test  merge that image onto this machine, test it, unmerge"
	@echo "sysext-install  install that image on this machine and merge it, for keeps"
	@echo "clean    remove build and cache artefacts"

# --allow-existing so this is idempotent. Without it `uv venv` refuses outright
# once .venv is there, which made `make sync` -- the documented way to pick up a
# dependency change -- fail for everyone who had already run it once.
#
# The `&&` matters: a failed command substitution leaves the variable empty and
# the line would otherwise carry on and build the environment against nothing.
venv:
	python="$$($(SELECT_PYTHON))" && \
		uv venv --system-site-packages --python "$$python" --allow-existing

sync: venv
	UV_NO_SYNC=0 uv sync --all-extras $(NO_INSTALL)
	$(MAKE) hooks

# `check` only tells you about a problem after it is committed. This runs the
# same hooks on the way in, which is the point at which they are still cheap.
hooks:
	uv run pre-commit install

# Never hand-edit a .ui file: it is generated. Edit the .blp and run this.
#
# One recipe produces all of them -- batch-compile takes the whole directory at
# once -- so this is a grouped target. With a plain rule make would run the
# batch once per .ui it wanted, which is fifteen compilations of everything to
# produce the one file that changed.
ui: $(UI_FILES)

# The touch is not cosmetic. batch-compile leaves a .ui alone when what it
# would write is what is already there, so an unchanged one keeps a timestamp
# older than every .blp beside it -- and make, seeing a target it just built
# still older than its prerequisites, would run the compiler again on the next
# invocation, and the one after that, forever.
$(UI_FILES) &: $(BLUEPRINT_SOURCES)
	uv run blueprint-compiler batch-compile $(BLUEPRINTS) $(BLUEPRINTS) $(BLUEPRINTS)/*.blp
	@touch $(UI_FILES)

schemas: $(COMPILED_SCHEMAS)

$(COMPILED_SCHEMAS): $(SCHEMA_SOURCES)
	glib-compile-schemas data/

check:
	uv run pre-commit run --all-files

# The generated files rather than an assumption that they are current: a suite
# run against a stale .ui tests the widgets somebody had an hour ago, and
# passes.
#
# The .ui files only when the suite reads them, though, which is when it runs
# against the working copy. Against an installed wheel or RPM the widgets come
# out of the installed copy, compiled when the package was built -- the files
# here are not opened at all. And asking for them there does not merely do
# nothing: those jobs in CI deliberately have no development environment, so the
# recipe below reaches for a uv that is not installed and the suite never runs.
#
# It would reach for it every time, too. A checkout writes files in path order,
# so window.blp lands after about.ui, and the grouped rule makes every .ui
# depend on every .blp -- which leaves a freshly checked-out .ui older than a
# prerequisite that was never edited.
UI_PREREQUISITES := $(if $(TESTS_THE_WORKING_COPY),$(UI_FILES))

test: $(COMPILED_SCHEMAS) $(UI_PREREQUISITES)
	$(HEADLESS) $(PYTHON) -m pytest

test-gui: $(COMPILED_SCHEMAS) $(UI_PREREQUISITES)
	$(HEADLESS) $(PYTHON) -m pytest -m gui

build: $(UI_FILES)
	uv build

# The suite against the wheel, installed. This is the question the working copy
# cannot answer -- nobody runs the working copy -- and it is where the faults
# packaging introduces show up: a wheel that installed without its .ui files, a
# schema that never reached the compiled cache, an entry point resolving to
# nothing. CI runs this same target; `make build && make test-wheel` is that job
# on a developer's machine.
#
# --system-site-packages for PyGObject, which comes from the distribution here
# as everywhere else, and the system interpreter for the same reason.
WHEEL_VENV := build/wheel-venv

# No generated files among the prerequisites: what is tested here is the wheel
# in dist/, which carries the .ui files it was built with, and the delegated
# `test` below brings up the schema. `make build` is what compiles a .blp into
# the wheel, and this target says so when dist/ holds nothing.
test-wheel:
	@wheels=$$(ls -1 dist/*.whl 2>/dev/null | wc -l); \
	if [ "$$wheels" != 1 ]; then \
		echo "make test-wheel: expected one wheel in dist/, found $$wheels."; \
		echo "  none: run make build"; \
		echo "  more: run make clean build -- dist/ keeps every wheel ever"; \
		echo "        built here, and an old one installed is an old one"; \
		echo "        tested, silently, which is what this target exists to"; \
		echo "        stop happening"; \
		exit 1; \
	fi
	rm -rf $(WHEEL_VENV)
	python="$$($(SELECT_PYTHON))" && \
		"$$python" -m venv --system-site-packages $(WHEEL_VENV)
	$(WHEEL_VENV)/bin/pip install --quiet dist/*.whl pytest
	# The src/ layout is what makes this honest: `import gtkpass` from the
	# repository root finds nothing, so what the suite exercises can only be
	# the installed copy. Said out loud, because a path that quietly resolved
	# to the checkout would make the whole target agree with itself and mean
	# nothing.
	$(WHEEL_VENV)/bin/python -c \
		"import gtkpass; print(gtkpass.__file__); \
		assert 'site-packages' in gtkpass.__file__, 'not the installed copy'"
	$(MAKE) test PYTHON=$(WHEEL_VENV)/bin/python

# Pass arguments through: make run ARGS="--debug"
#
# The generated files are prerequisites here too: launching the application to
# look at a change to a .blp, and being shown the previous one, is the most
# expensive minute in the day.
run: $(COMPILED_SCHEMAS) $(UI_FILES)
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
run-dev: devstore $(COMPILED_SCHEMAS) $(UI_FILES)
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
#
# --no-documents-portal for the same reason as flatpak-run above, and it is not
# optional here either: these run the linter through `flatpak run`, so without
# it a missing portal mount stops the check with a bwrap error rather than a
# lint result.
flatpak-lint:
	flatpak run --no-documents-portal \
		--command=flatpak-builder-lint org.flatpak.Builder manifest \
		$(FLATPAK_MANIFEST)

flatpak-lint-repo:
	flatpak-builder --force-clean --user --repo=.flatpak-repo \
		.flatpak-build $(FLATPAK_MANIFEST)
	flatpak run --no-documents-portal \
		--command=flatpak-builder-lint org.flatpak.Builder repo \
		.flatpak-repo

# Both build in a Fedora container: this is developed on an ostree desktop,
# where layering rpm-build in order to package something is a reboot and a
# permanent addition to the image. See docs/PACKAGING.md.
rpm: $(RPM_STAMP)

# The container it is built in counts as an input: a change to the toolchain
# is a change to what comes out of it.
BUILD_CONTAINER := packaging/Containerfile.build packaging/builder-image.sh

$(RPM_STAMP): $(PACKAGE_SOURCES) packaging/build-rpm.sh packaging/gtkpass.spec \
	$(BUILD_CONTAINER)
	./packaging/build-rpm.sh
	@touch $@

# The image is built from the RPM, so it is out of date whenever that is. This
# is the dependency that was missing: build-sysext.sh builds an RPM only when
# dist/rpm has none at all, so once one existed every later image was made from
# it however old it had become.
sysext: $(SYSEXT_IMAGE)

$(SYSEXT_IMAGE): $(RPM_STAMP) packaging/build-sysext.sh $(BUILD_CONTAINER)
	./packaging/build-sysext.sh

# Needs root, and says what it changes before it changes it. This is the step CI
# cannot do: merging needs a running systemd, which a container has not got.
sysext-test: $(SYSEXT_IMAGE)
	./packaging/test-sysext.sh

# The one that keeps the image installed. Replaces an earlier one, which means
# unmerging first: a merged image is loop-mounted, so writing over the file
# underneath it is not an update but a running system reading from a file that
# has gone. ARGS="--yes" to skip the confirmation.
#
# Depends on the image, so what gets installed is built from the working tree as
# it is now. It used to install whatever was in dist/sysext, which is why the
# script prints the build date and the commit before it asks.
sysext-install: $(SYSEXT_IMAGE)
	./packaging/install-sysext.sh $(ARGS)

clean:
	rm -rf build/ dist/ htmlcov/ .coverage .pytest_cache/ .ruff_cache/ .mypy_cache/
	# Building an sdist leaves these in the source tree, and an editable install
	# puts src/ on the path -- so a stale one from an earlier name shows up as a
	# second distribution and duplicates every entry point it declares.
	rm -rf src/*.egg-info
	rm -rf .flatpak-build/ .flatpak-builder/ .flatpak-repo/
	rm -f data/gschemas.compiled
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .dev/
