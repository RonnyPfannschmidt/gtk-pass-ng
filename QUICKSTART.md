# Developer Quick Start Guide

This guide will help you get started with GTKPass development quickly.

## Prerequisites

### System Requirements

- Linux (GNOME desktop recommended)
- Python 3.10 or higher
- GTK4 4.10 or higher
- Libadwaita 1.4 or higher
- GnuPG 2.x
- Git

### Install System Dependencies

**Fedora/RHEL:**
```bash
sudo dnf install python3-devel gtk4-devel libadwaita-devel \
                 gobject-introspection-devel gnupg2 git \
                 blueprint-compiler
```

**Ubuntu/Debian:**
```bash
sudo apt install python3-dev libgtk-4-dev libadwaita-1-dev \
                 gobject-introspection gir1.2-gtk-4.0 \
                 gir1.2-adw-1 gnupg git blueprint-compiler
```

**Arch Linux:**
```bash
sudo pacman -S python gtk4 libadwaita gobject-introspection \
               gnupg git blueprint-compiler
```

## Quick Setup

### 1. Clone Repository

```bash
git clone https://github.com/RonnyPfannschmidt/gtkpass.git
cd gtkpass
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Development Dependencies

```bash
# Once pyproject.toml is set up:
pip install -e ".[dev]"

# For now (manual install):
pip install pytest pytest-cov mypy ruff pygobject keyring GitPython \
            python-gnupg pyotp qrcode pillow
```

### 4. Verify Installation

```bash
# Check Python version
python --version  # Should be 3.10+

# Check GTK installation
python -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print(f'GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}')"

# Check Libadwaita
python -c "import gi; gi.require_version('Adw', '1'); from gi.repository import Adw; print('Libadwaita OK')"
```

## Project Structure

```
gtkpass/
├── src/
│   └── gtkpass/              # Main package (to be created)
│       ├── __init__.py
│       ├── __main__.py       # Entry point
│       ├── app.py            # Application class
│       ├── window.py         # Main window
│       ├── models/           # Data models
│       ├── services/         # Business logic
│       ├── ui/               # UI components
│       │   └── blueprints/   # Blueprint UI files
│       └── utils/            # Utilities
├── tests/                    # Test suite (to be created)
├── data/                     # Resources (to be created)
├── docs/                     # Documentation
├── REQUIREMENTS.md           # Feature requirements
├── ARCHITECTURE.md           # Technical architecture
├── ROADMAP.md               # Development plan
├── CLAUDE.md                # Claude AI guidelines
├── CONTRIBUTING.md          # Contribution guide
├── SECURITY.md              # Security policy
└── README.md                # Project overview
```

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes

Edit files in `src/gtkpass/` following the guidelines in [CLAUDE.md](CLAUDE.md).

### 3. Write Tests

Add tests in `tests/` directory:

```python
# tests/test_password.py
from gtkpass.models.password import Password

def test_password_creation():
    pwd = Password(
        name="test",
        path="/test.gpg",
        password="secret123"
    )
    assert pwd.name == "test"
    assert pwd.password == "secret123"
```

### 4. Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=gtkpass --cov-report=html

# Run specific test file
pytest tests/test_password.py

# Run specific test
pytest tests/test_password.py::test_password_creation
```

### 5. Check Code Quality

```bash
# Lint code
ruff check src/

# Format code
ruff format src/

# Type check
mypy src/
```

### 6. Commit Changes

```bash
git add .
git commit -m "feat: add password model with basic fields"
```

Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `refactor:` - Code refactoring
- `test:` - Tests
- `chore:` - Maintenance

### 7. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Common Development Tasks

### Running the Application (when implemented)

```bash
# From repository root
python -m gtkpass

# Or after installation
gtkpass
```

### Building UI with Blueprint

```bash
# Compile Blueprint to XML (when UI is implemented)
blueprint-compiler compile ui/blueprints/window.blp

# Watch mode for development
blueprint-compiler compile --watch ui/blueprints/
```

### Testing with Test Password Store

```bash
# Create a test password store
mkdir -p /tmp/test-password-store
export PASSWORD_STORE_DIR=/tmp/test-password-store

# Initialize it
pass init your-gpg-key-id

# Add test passwords
pass insert test/example
```

### Debugging GTK Applications

```bash
# Enable GTK debug messages
GTK_DEBUG=interactive python -m gtkpass

# Check for memory leaks (with valgrind)
G_DEBUG=gc-friendly G_SLICE=always-malloc valgrind \
    --leak-check=full python -m gtkpass
```

### Generate Documentation

```bash
# Generate API documentation (when set up)
pdoc --html --output-dir docs/api src/gtkpass

# Build user documentation (when using Sphinx)
cd docs
make html
```

## Useful Commands

### Git Operations

```bash
# Check repository status
git status

# View changes
git diff

# View commit history
git log --oneline --graph

# Update from main
git fetch origin
git rebase origin/main
```

### Python Environment

```bash
# Activate virtual environment
source venv/bin/activate

# Deactivate
deactivate

# Update dependencies
pip install --upgrade -e ".[dev]"

# List installed packages
pip list
```

### Testing Shortcuts

```bash
# Run tests in parallel
pytest -n auto

# Run only failed tests
pytest --lf

# Run tests with print output
pytest -s

# Generate coverage report
pytest --cov=gtkpass --cov-report=term-missing
```

## Development Tips

### 1. Use Blueprint for UI

Write UI in Blueprint format (`.blp`), not XML:

```blp
using Gtk 4.0;
using Adw 1;

template $MainWindow : Adw.ApplicationWindow {
  title: "GTKPass";
  default-width: 800;
  default-height: 600;

  Adw.ToolbarView {
    [top]
    Adw.HeaderBar {
      title-widget: Adw.WindowTitle {
        title: "GTKPass";
      };
    }

    content: Gtk.Box {
      orientation: vertical;

      Gtk.Label {
        label: "Hello, GTKPass!";
      }
    };
  }
}
```

### 2. Follow Python Type Hints

```python
from pathlib import Path
from typing import Optional

def get_password(path: Path) -> Optional[str]:
    """Get password from file."""
    if not path.exists():
        return None
    return path.read_text()
```

### 3. Use Dataclasses for Models

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass
class Password:
    """Password entry model."""
    name: str
    path: Path
    password: str
    username: Optional[str] = None
    created_at: datetime = datetime.now()
```

### 4. Write Testable Code

```python
# Good: Dependency injection
class PasswordStore:
    def __init__(self, gpg_service: GPGService):
        self.gpg = gpg_service

    def decrypt(self, data: str) -> str:
        return self.gpg.decrypt(data)

# In tests, use mock
def test_decrypt():
    mock_gpg = Mock()
    mock_gpg.decrypt.return_value = "secret"
    store = PasswordStore(mock_gpg)
    assert store.decrypt("encrypted") == "secret"
```

### 5. Use GTK Templates

```python
from gi.repository import Gtk, Adw

@Gtk.Template(resource_path='/org/gnome/gtkpass/ui/window.ui')
class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'MainWindow'

    # Bind template widgets
    content_box = Gtk.Template.Child()

    @Gtk.Template.Callback()
    def on_button_clicked(self, button):
        """Handle button click from template."""
        print("Button clicked!")
```

## Learning Resources

### GTK/GNOME Development
- [GTK4 Tutorial](https://docs.gtk.org/gtk4/getting_started.html)
- [Libadwaita Demo](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/demo.html)
- [Blueprint Tutorial](https://jwestman.pages.gitlab.gnome.org/blueprint-compiler/tutorial.html)
- [GNOME Developer Center](https://developer.gnome.org/)

### Python Development
- [Real Python](https://realpython.com/)
- [Python Type Hints](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
- [pytest Documentation](https://docs.pytest.org/)

### passwordstore
- [pass Documentation](https://www.passwordstore.org/)
- [pass Source Code](https://git.zx2c4.com/password-store/)
- [pass-otp](https://github.com/tadfisher/pass-otp)

## Getting Help

- **Documentation**: Check REQUIREMENTS.md, ARCHITECTURE.md, CLAUDE.md
- **Issues**: Search [GitHub Issues](https://github.com/RonnyPfannschmidt/gtkpass/issues)
- **Discussions**: Ask in [GitHub Discussions](https://github.com/RonnyPfannschmidt/gtkpass/discussions)
- **GTK Help**: [GNOME Discourse](https://discourse.gnome.org/)
- **Python Help**: [Python Discord](https://pythondiscord.com/)

## Next Steps

1. Read [REQUIREMENTS.md](REQUIREMENTS.md) to understand feature requirements
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand system design
3. Read [CLAUDE.md](CLAUDE.md) for development guidelines
4. Check [ROADMAP.md](ROADMAP.md) for current priorities
5. Pick an issue labeled "good first issue" to start contributing

## Troubleshooting

### GTK Not Found

```bash
# Make sure GTK4 is installed
pkg-config --modversion gtk4

# Install PyGObject
pip install pygobject
```

### Blueprint Compiler Missing

```bash
# Install blueprint-compiler
# Fedora
sudo dnf install blueprint-compiler

# Ubuntu (may need to build from source)
git clone https://gitlab.gnome.org/jwestman/blueprint-compiler.git
cd blueprint-compiler
meson build
ninja -C build install
```

### Import Errors

```bash
# Make sure you're in the virtual environment
source venv/bin/activate

# Reinstall in development mode
pip install -e .
```

### GPG Issues

```bash
# Check GPG installation
gpg --version

# List GPG keys
gpg --list-keys

# Generate test key (for development)
gpg --quick-generate-key test@example.com
```

## Code of Conduct

Please read and follow our code of conduct when contributing. Be respectful, inclusive, and constructive.

---

Happy coding! 🚀
