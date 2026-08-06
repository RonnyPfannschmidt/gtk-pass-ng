> **Status: aspirational.** This compares qtpass against the GTKPass that was
> planned, not the one that exists. Features credited to GTKPass here are
> largely unbuilt. See [README.md](README.md) for what actually works.

# GTKPass vs qtpass Comparison

This document compares GTKPass with qtpass to help users understand the differences and advantages of each tool.

## Overview

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| **UI Framework** | GTK4 + Libadwaita | Qt5/Qt6 |
| **Language** | Python | C++ |
| **Desktop Integration** | GNOME native | Cross-desktop |
| **UI Definition** | Blueprint (.blp) | Qt Designer (.ui) |
| **Development Status** | In Development | Mature (Active) |
| **First Release** | TBD (2025) | 2014 |

## Why GTKPass?

GTKPass is designed specifically for GNOME users who want:

1. **Native GNOME Experience**
   - Libadwaita widgets that match GNOME apps
   - Seamless dark mode support
   - GNOME HIG compliance
   - Native GNOME notifications and integration

2. **Modern UI/UX**
   - Clean, modern interface
   - Adaptive layouts
   - Touch-friendly design
   - Better keyboard navigation

3. **Python Codebase**
   - Easier to contribute for Python developers
   - Faster prototyping
   - More accessible to new contributors

4. **Built-in OTP Support**
   - Native TOTP/HOTP generation
   - QR code scanning and generation
   - No external plugins needed

5. **Enhanced Security Features**
   - System keyring integration
   - Better session management
   - Modern security practices

## Why qtpass?

qtpass may be better if you:

1. **Use Multiple Desktop Environments**
   - Works on KDE, XFCE, Windows, macOS
   - Qt provides consistent experience across platforms

2. **Need Stability**
   - Mature, well-tested codebase
   - Years of production use
   - Large user base

3. **Prefer Qt**
   - Qt fans
   - Integration with other Qt apps

## Feature Comparison

### Core Features

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| View passwords | ✅ Planned | ✅ Yes |
| Edit passwords | ✅ Planned | ✅ Yes |
| Add passwords | ✅ Planned | ✅ Yes |
| Delete passwords | ✅ Planned | ✅ Yes |
| Search passwords | ✅ Planned | ✅ Yes |
| Copy to clipboard | ✅ Planned | ✅ Yes |
| Generate passwords | ✅ Planned | ✅ Yes |
| Git integration | ✅ Planned | ✅ Yes |
| GPG encryption | ✅ Planned | ✅ Yes |

### OTP Support

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| TOTP generation | ✅ Native | ⚠️ Via pass-otp |
| HOTP generation | ✅ Native | ⚠️ Via pass-otp |
| QR code generation | ✅ Native | ❌ No |
| QR code scanning | ✅ Native | ❌ No |
| OTP countdown | ✅ Yes | ⚠️ Basic |

### UI/UX Features

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| Dark mode | ✅ Native | ⚠️ Qt theme |
| Keyboard shortcuts | ✅ Yes | ✅ Yes |
| Tree view | ✅ Yes | ✅ Yes |
| Search/filter | ✅ Advanced | ✅ Basic |
| Drag & drop | ✅ Planned | ❌ No |
| Undo/redo | ✅ Planned | ❌ No |
| Context menus | ✅ Yes | ✅ Yes |
| Toast notifications | ✅ Native | ⚠️ System tray |

### Security Features

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| GPG encryption | ✅ Yes | ✅ Yes |
| Clipboard timeout | ✅ Configurable | ✅ Configurable |
| Auto-lock | ✅ Yes | ✅ Yes |
| Keyring integration | ✅ Native | ⚠️ Limited |
| Session locking | ✅ Yes | ⚠️ Basic |
| Password strength | ✅ Advanced | ✅ Basic |
| Duplicate detection | ✅ Yes | ❌ No |

### Password Management

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| Password age tracking | ✅ Yes | ❌ No |
| Weak password detection | ✅ Yes | ❌ No |
| Rotation reminders | ✅ Yes | ❌ No |
| Lifecycle management | ✅ Yes | ❌ No |
| Batch operations | ✅ Planned | ❌ No |
| Password history | ✅ Git-based | ✅ Git-based |

### Advanced Features

| Feature | GTKPass | qtpass |
|---------|---------|--------|
| QR code support | ✅ Full | ❌ No |
| Backup/restore | ✅ Built-in | ⚠️ Manual |
| Import/export | ✅ Planned | ⚠️ Limited |
| Templates | ✅ Planned | ❌ No |
| Custom fields | ✅ Yes | ⚠️ Limited |
| Multi-store | ⚠️ Future | ✅ Yes |

## Platform Support

### GTKPass
- ✅ Linux (GNOME)
- ⚠️ Linux (other DEs) - works but not optimized
- ❌ Windows - not planned
- ❌ macOS - not planned initially
- ⚠️ Mobile - future consideration

### qtpass
- ✅ Linux (all DEs)
- ✅ Windows
- ✅ macOS
- ❌ Mobile

## Performance

| Aspect | GTKPass | qtpass |
|--------|---------|--------|
| **Startup time** | Target < 2s | ~1-2s |
| **Memory usage** | Python overhead | Lower (C++) |
| **Search speed** | Optimized | Fast |
| **Large stores** | Lazy loading | Good |

## Compatibility

Both tools are compatible with:
- Standard passwordstore format
- pass CLI
- Android Password Store
- pass-otp (for OTP)
- Git synchronization

## Migration

### From qtpass to GTKPass
- ✅ Same password store format
- ✅ No migration needed
- ✅ Can use both tools simultaneously
- ✅ Same git repository

### From GTKPass to qtpass
- ✅ Same password store format
- ✅ No migration needed
- ✅ Can use both tools simultaneously

## Development

| Aspect | GTKPass | qtpass |
|--------|---------|--------|
| **Language** | Python 3.10+ | C++ |
| **Contributors** | Starting | Active community |
| **Issue tracker** | GitHub | GitHub |
| **License** | GPL-3.0 | GPL-3.0 |
| **Contribution** | Python-friendly | C++ knowledge needed |

## When to Choose GTKPass

Choose GTKPass if you:
- Use GNOME as your desktop environment
- Want a modern, native GNOME experience
- Need built-in OTP support
- Want QR code functionality
- Prefer Python for contributions
- Need advanced password lifecycle management
- Want better keyring integration

## When to Choose qtpass

Choose qtpass if you:
- Use multiple operating systems
- Need Windows or macOS support
- Prefer Qt applications
- Want a mature, stable tool
- Use KDE or other Qt-based desktops
- Need multi-store support now
- Prefer C++ for contributions

## Can I Use Both?

**Yes!** Both tools use the same passwordstore format, so you can:
- Use GTKPass on your GNOME laptop
- Use qtpass on your Windows desktop
- Switch between them freely
- Sync via git

They can coexist peacefully and work with the same password repository.

## Future Roadmap

### GTKPass Plans
- v1.0: Core functionality, OTP, QR codes
- v1.1: Import/export, advanced features
- v2.0: Browser extension, mobile apps

### qtpass Status
- Mature and stable
- Active maintenance
- Community-driven features

## Community

### GTKPass
- GitHub: https://github.com/RonnyPfannschmidt/gtkpass
- Status: Building community
- Activity: In development

### qtpass
- GitHub: https://github.com/IJHack/qtpass
- Status: Established community
- Activity: Active

## Conclusion

GTKPass and qtpass serve different audiences:

- **GTKPass**: Modern GNOME users who want a native experience
- **qtpass**: Cross-platform users who need Qt integration

Both are excellent choices for passwordstore management. Pick the one that fits your desktop environment and workflow best.

## Comparison Summary

| Criteria | Winner |
|----------|--------|
| GNOME integration | GTKPass |
| Cross-platform | qtpass |
| Maturity | qtpass |
| Modern UI | GTKPass |
| OTP support | GTKPass |
| QR codes | GTKPass |
| Stability | qtpass |
| Python development | GTKPass |
| C++ development | qtpass |
| Lifecycle management | GTKPass |

## Questions?

- **GTKPass**: See [REQUIREMENTS.md](REQUIREMENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
- **qtpass**: Visit [qtpass.org](https://qtpass.org)
- **passwordstore**: Visit [passwordstore.org](https://www.passwordstore.org)

---

*Note: GTKPass is currently in development. This comparison reflects planned features. The stable, production-ready choice today is qtpass.*
