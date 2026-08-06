# Blueprint UI Files

This directory contains UI definitions for GTKPass.

## File Types

- **`.blp` files**: Blueprint format (source files)
- **`.ui` files**: GTK UI XML format (compiled files)

## Blueprint Format

Blueprint is a modern, readable format for defining GTK UIs. It's more concise and easier to read than XML.

Example:
```blp
using Gtk 4.0;
using Adw 1;

template $MyWindow : Adw.ApplicationWindow {
  title: "My App";

  Adw.HeaderBar {
    // Header content
  }
}
```

## Compiling Blueprints

To compile `.blp` files to `.ui` files:

```bash
# From project root
./compile_blueprints.sh
```

Or manually:
```bash
blueprint-compiler compile window.blp --output window.ui
```

## Installing Blueprint Compiler

The blueprint compiler is not available via pip. Install it from your system package manager:

**Fedora:**
```bash
sudo dnf install blueprint-compiler
```

**Ubuntu/Debian:**
```bash
# Not yet available in standard repos, install from source:
# https://github.com/jwestman/blueprint-compiler
```

**From source:**
```bash
git clone https://gitlab.gnome.org/jwestman/blueprint-compiler.git
cd blueprint-compiler
meson setup build
meson install -C build
```

## Development Workflow

1. Edit the `.blp` source file
2. Run `./compile_blueprints.sh` to generate `.ui` file
3. The `.ui` file is loaded by the application at runtime

## Note

For initial development, both `.blp` and `.ui` files are committed to the repository to ensure the application works even without blueprint-compiler installed. In production builds, only `.blp` files would be in version control and `.ui` files would be generated during the build process.

## Resources

- [Blueprint Documentation](https://jwestman.pages.gitlab.gnome.org/blueprint-compiler/)
- [GTK4 Documentation](https://docs.gtk.org/gtk4/)
- [Libadwaita Documentation](https://gnome.pages.gitlab.gnome.org/libadwaita/)
