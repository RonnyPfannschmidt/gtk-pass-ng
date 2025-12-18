# GTKPass Development Setup

This guide will help you set up your development environment for GTKPass.

## Dev Container (Recommended)

If you're using the provided dev container (VS Code or GitHub Codespaces):

1. **The container automatically installs all dependencies** when it starts via `.devcontainer/setup.sh`
2. **The app is installed in editable mode** at `.venv/bin/python`
3. **Wayland and X11 are both supported** for GUI access from the container

⚠️ **Important**: If you just updated the devcontainer configuration, rebuild it to apply changes:
- In VS Code: `Cmd/Ctrl+Shift+P` → "Dev Containers: Rebuild Container"

### Running the App in Dev Container

```bash
# Quick run
./run_app.sh

# Or check display backend status first
./check_display.sh

# Or manually
source .venv/bin/activate
python -m gtkpass
```

### GUI Requirements

The devcontainer supports both **Wayland and X11**:

**Wayland (preferred on modern Linux):**
- Works out of the box on GNOME, KDE Plasma 6, Sway, etc.
- No additional configuration needed!

**X11 (fallback or macOS/Windows):**

**On Linux:**
```bash
xhost +local:
```

**On macOS:**
- Install XQuartz: `brew install --cask xquartz`
- Enable "Allow connections from network clients" in XQuartz preferences
- Run: `xhost +localhost`

**On Windows (WSL2):**
- Install VcXsrv or X410
- Set DISPLAY and run: `xhost +`

See [docs/DEVCONTAINER_GUI.md](docs/DEVCONTAINER_GUI.md) for detailed GUI setup instructions.

### Troubleshooting Dev Container

If the setup failed or you need to reinstall:
```bash
# Run the setup script manually
bash .devcontainer/setup.sh

# Or rebuild the container
# In VS Code: Cmd/Ctrl+Shift+P → "Dev Containers: Rebuild Container"
```

## Prerequisites

- Python 3.10 or higher
- GTK4 4.10+ and Libadwaita 1.4+ (for running the application)
- Git

### Installing System Dependencies

#### Ubuntu/Debian
```bash
sudo apt install python3 python3-pip python3-venv \
    libgtk-4-dev libadwaita-1-dev \
    gobject-introspection libgirepository1.0-dev \
    gir1.2-gtk-4.0 gir1.2-adwaita-1
```

#### Fedora
```bash
sudo dnf install python3 python3-pip \
    gtk4-devel libadwaita-devel \
    gobject-introspection-devel \
    python3-gobject
```

#### Arch Linux
```bash
sudo pacman -S python python-pip \
    gtk4 libadwaita \
    gobject-introspection \
    python-gobject
```

## Setting Up the Development Environment

1. Clone the repository:
```bash
git clone https://github.com/RonnyPfannschmidt/gtkpass.git
cd gtkpass
```

2. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install the package in development mode with all dependencies:
```bash
pip install -e ".[dev]"
```

4. Install pre-commit hooks (optional but recommended):
```bash
pip install pre-commit
pre-commit install
```

5. Compile Blueprint UI files (optional - pre-compiled UI files are included):
```bash
./compile_blueprints.sh
```

Note: Blueprint compiler is not required for development as pre-compiled `.ui` files are included in the repository. However, if you modify `.blp` files, you'll need to recompile them.

## Running the Application

```bash
# Using the installed command
gtkpass

# Or using Python module
python -m gtkpass
```

## Running Tests

### All Tests
```bash
# Run all tests with coverage
pytest tests/

# Or use the convenience script
./run_tests.sh
```

### Specific Test Types
```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# Acceptance tests only
pytest tests/acceptance/ -v

# Run with markers
pytest -m unit
pytest -m integration
pytest -m acceptance
```

### Test Coverage
```bash
# Generate coverage report
pytest --cov=gtkpass --cov-report=html tests/

# View the report
open htmlcov/index.html
```

## Code Quality

### Linting
```bash
# Check code with ruff
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

### Formatting
```bash
# Check formatting
ruff format --check src/ tests/

# Format code
ruff format src/ tests/
```

### Type Checking
```bash
# Run mypy
mypy src/gtkpass
```

## Project Structure

```
gtkpass/
├── src/gtkpass/          # Main application code
│   ├── __init__.py
│   ├── __main__.py       # Entry point
│   ├── app.py            # Application class
│   ├── window.py         # Main window
│   └── services/         # Service layer
│       ├── __init__.py
│       └── background.py # Background task service
├── tests/                # Test suite
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── acceptance/       # Acceptance tests
├── pyproject.toml        # Project configuration
└── README.md
```

## Development Workflow

1. Create a new branch for your feature:
```bash
git checkout -b feature/my-feature
```

2. Make your changes following the coding standards

3. Run tests and linters:
```bash
./run_tests.sh
```

4. Commit your changes:
```bash
git add .
git commit -m "feat: add my feature"
```

5. Push and create a pull request:
```bash
git push origin feature/my-feature
```

## Coding Standards

- Follow PEP 8 style guidelines
- Use type hints for all function signatures
- Minimum Python version: 3.10
- Write docstrings for all public functions and classes
- Ensure all tests pass before submitting PR
- Maintain or improve code coverage

## Testing Guidelines

- Write unit tests for all new code
- Use meaningful test names that describe what is being tested
- Follow the AAA pattern: Arrange, Act, Assert
- Mock external dependencies (GTK, filesystem, etc.)
- Mark tests appropriately (`@pytest.mark.unit`, etc.)

## Getting Help

- Read the [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- Check [REQUIREMENTS.md](REQUIREMENTS.md) for feature requirements
- Read [CLAUDE.md](CLAUDE.md) for AI-assisted development guidelines
- Open an issue on GitHub for questions

## Troubleshooting

### GTK not found
If you get GTK import errors, ensure you've installed the system GTK4 packages listed above.

### Tests fail with GTK errors
Some tests require GTK4 to be installed. Tests that depend on GTK will be automatically skipped if GTK is not available.

### Virtual environment issues
If you have issues with the virtual environment, try removing it and creating a new one:
```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
