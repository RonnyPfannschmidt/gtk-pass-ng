# Blueprint UI Architecture

## Why Blueprint?

GTKPass uses Blueprint (.blp) files for UI definitions instead of creating widgets programmatically in Python code. This follows GNOME best practices and provides several benefits:

### 1. **Separation of Concerns**
- UI structure is defined in declarative Blueprint files
- Business logic stays in Python code
- Easier to maintain and modify independently

### 2. **Better Readability**
Blueprint syntax is more concise and readable than GTK UI XML or Python code for creating widgets:

**Blueprint (.blp):**
```blp
template $MyWindow : Adw.ApplicationWindow {
  title: "My App";
  default-width: 800;

  Adw.HeaderBar {
    [end]
    MenuButton {
      icon-name: "open-menu-symbolic";
    }
  }
}
```

**Equivalent Python:**
```python
class MyWindow(Adw.ApplicationWindow):
    def __init__(self):
        super().__init__()
        self.set_title("My App")
        self.set_default_width(800)

        header = Adw.HeaderBar()
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        header.pack_end(menu_btn)
        # ... more setup code
```

### 3. **GNOME Guidelines**
The GNOME project recommends using Blueprint for modern GTK4 applications. It's the standard way to define UIs in the GNOME ecosystem.

### 4. **Easier Collaboration**
Designers and developers can work on UI files without needing to understand Python code. Blueprint files can be edited with specialized tools.

### 5. **Better Tooling**
- Blueprint compiler validates UI structure at compile time
- Catches errors early before runtime
- Enables better IDE support and syntax highlighting

## Workflow

1. **Design**: Create or modify `.blp` files in `src/gtkpass/ui/blueprints/`
2. **Compile**: Run `./compile_blueprints.sh` to generate `.ui` XML files
3. **Load**: Python code loads the compiled `.ui` file using `@Gtk.Template` decorator

## File Structure

```
src/gtkpass/ui/blueprints/
├── README.md           # Documentation
├── window.blp          # Blueprint source (human-editable)
└── window.ui           # Compiled GTK UI XML (generated)
```

## Development Notes

- Both `.blp` and `.ui` files are committed to the repository during early development
- This ensures the application works even without blueprint-compiler installed
- In production, only `.blp` files would be tracked and `.ui` files generated during build
- Pre-compiled `.ui` files make it easier for contributors to get started

## Resources

- [Blueprint Documentation](https://jwestman.pages.gitlab.gnome.org/blueprint-compiler/)
- [GNOME Developer Guidelines](https://developer.gnome.org/documentation/introduction.html)
- [GTK4 Template Documentation](https://docs.gtk.org/gtk4/class.Widget.html#template-xml)
