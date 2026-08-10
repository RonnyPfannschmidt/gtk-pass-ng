# Contributing to GTKPass

Thank you for considering contributing to GTKPass! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors. We follow the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/).

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues to avoid duplicates. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce** the issue
- **Expected behavior**
- **Actual behavior**
- **System information** (OS, GTK version, Python version)
- **Screenshots** if applicable
- **Error messages or logs**

There are no issue templates; the list above is what one would ask for.
Never paste a decrypted entry into an issue.

### Suggesting Features

Feature suggestions are welcome! Please:

- Check existing feature requests first
- Explain the use case and benefits
- Consider if it fits the project goals
- Check [ROADMAP.md](ROADMAP.md) first: it lists what is already planned,
  and what has been ruled out and why

### Code Contributions

We welcome code contributions! Here's how to get started:

#### 1. Set Up Development Environment

```bash
git clone https://github.com/RonnyPfannschmidt/gtk-pass-ng.git
cd gtkpass

# Environment, dependencies and the pre-commit hook, in one step
make sync
```

GTK4 and Libadwaita have to come from your distribution, and so do PyGObject
and pycairo — see [DEVELOPMENT.md](DEVELOPMENT.md) for the package names and
for why `make sync` is not `pip install -e .`.

Read [AGENTS.md](AGENTS.md) before you start. Its first rule — development code
must never read your real password store — is not optional.

#### 2. Create a Branch

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Or a bugfix branch
git checkout -b fix/issue-number-description
```

#### 3. Make Your Changes

Follow these guidelines:

**Python Code Style:**
- Follow PEP 8
- Use type hints for all functions
- Write docstrings for public APIs
- Keep functions focused and small
- Prefer composition over inheritance

**GTK/UI Code:**
- Use Blueprint (.blp) format for UI definitions
- Follow GNOME Human Interface Guidelines
- Support keyboard navigation
- Ensure accessibility
- Test with dark mode

**Security:**
- Never log or print passwords
- Clear sensitive data from memory
- Validate all user inputs
- Handle GPG errors gracefully
- Follow security best practices

**Git Commits:**
- Use conventional commits format:
  - `feat:` for new features
  - `fix:` for bug fixes
  - `docs:` for documentation
  - `refactor:` for code refactoring
  - `test:` for adding tests
  - `chore:` for maintenance tasks
- Reference issue numbers (e.g., `fix: clipboard not clearing (#42)`)
- Keep commits atomic and focused
- Write clear commit messages

#### 4. Write Tests

Write the failing test first, run it, watch it fail, then make it pass. The
backend conformance suite in `tests/test_backend_contract.py` is the definition
of done for backend work.

#### 5. Run Quality Checks

```bash
make test    # the suite, headless under xvfb
make check   # lint, format and types, via pre-commit
```

The pre-commit hook `make sync` installed runs `make check`'s hooks on the way
in, and CI runs both on the pull request. Running them here first is faster than
finding out from a red run.

#### 6. Submit Pull Request

- Push your branch to GitHub
- Open a pull request describing what changed and why
- Reference related issues
- Wait for review and address feedback

## Development Guidelines

### Project Structure

```
gtkpass/
├── src/gtkpass/          # Application code
│   ├── backends/         # The backend contract and its implementations
│   ├── ui/               # Widgets
│   │   └── blueprints/   # Blueprint sources and compiled .ui files
│   └── utils/            # Threading and clipboard helpers
├── tests/                # Test suite, flat
├── data/                 # GSettings schema, desktop and AppStream files
├── packaging/            # RPM spec and the RPM/sysext build scripts
├── build-aux/            # Flatpak manifest
└── docs/                 # Documentation
```

### Architecture

GTKPass is a frontend over pluggable backends:

1. **UI**: GTK4/Libadwaita widgets, declared in Blueprint
2. **Window**: loads the configured backends and drives the panes
3. **Backends**: the `PasswordBackend` contract and its implementations,
   discovered through the `gtkpass.backends` entry point group

See [ARCHITECTURE.md](ARCHITECTURE.md) for detail.

### Key Technologies

- **Python 3.10+**
- **GTK4** and **Libadwaita**, through PyGObject
- **Blueprint**: UI definition format
- **uv**: environment and dependencies

Runtime dependencies are deliberately few. Adding one is a discussion first —
in particular `keyring`, `GitPython`, `pyotp`, `qrcode`, `pillow` and `opencv`,
which an earlier version of this file prescribed and none of which were ever
used.

### Documentation

- Update the documentation a change makes wrong. [ROADMAP.md](ROADMAP.md) and
  [README.md](README.md) both make claims about what works, and a feature that
  lands without moving them leaves the repository lying about itself.
- Add docstrings to public APIs, and say *why* where the reason is not obvious
  from the code

### Testing

- Write unit tests for business logic
- Write integration tests for workflows
- Test edge cases and error conditions
- Mock external dependencies (GPG, filesystem, git)
- Test with different password stores

### Security

Security is critical. Follow these practices:

- **Never commit secrets** or test passwords
- **Validate all inputs** from users and files
- **Clear sensitive data** from memory
- **Use secure random** for password generation
- **Handle GPG errors** gracefully
- **Test encryption/decryption** thoroughly
- **Review security implications** of changes

### UI/UX Guidelines

- Follow GNOME HIG
- Support keyboard shortcuts
- Ensure accessibility (screen readers, high contrast)
- Test with different screen sizes
- Support dark mode
- Provide visual feedback for actions
- Use Libadwaita patterns (toast, dialogs, etc.)

## Code Review Process

All contributions go through code review:

1. **Automated Checks**: the pre-commit hook runs lint, format and
   types on the way in, and CI runs the suite and the packaging jobs on the
   pull request.
2. **Manual Review**: Maintainers review code quality and design
3. **Testing**: Reviewers may test functionality manually
4. **Feedback**: Address review comments and update PR
5. **Approval**: Once approved, PR will be merged

## Questions?

- Check existing documentation ([README.md](README.md),
  [ARCHITECTURE.md](ARCHITECTURE.md), [FAQ.md](FAQ.md))
- Search existing issues and discussions
- Ask in GitHub Discussions
- Reach out to maintainers

## Recognition

Contributions are credited in the commit history, which is the record that
matters and the one that cannot drift out of date.

## License

By contributing to GTKPass, you agree that your contributions will be licensed under the MPL-2.0 License.

## Getting Help

- **Documentation**: Start with [README.md](README.md) and [FAQ.md](FAQ.md)
- **Development**: See [AGENTS.md](AGENTS.md), [DEVELOPMENT.md](DEVELOPMENT.md)
  and [ARCHITECTURE.md](ARCHITECTURE.md)
- **Issues**: Browse existing issues
- **Discussions**: Ask questions in GitHub Discussions
- **Contact**: Reach out to maintainers

## Development Resources

### GNOME Resources
- [GNOME Developer Center](https://developer.gnome.org/)
- [GTK4 Documentation](https://docs.gtk.org/gtk4/)
- [Libadwaita Documentation](https://gnome.pages.gitlab.gnome.org/libadwaita/)
- [Blueprint Documentation](https://jwestman.pages.gitlab.gnome.org/blueprint-compiler/)
- [GNOME HIG](https://developer.gnome.org/hig/)

### passwordstore Resources
- [passwordstore](https://www.passwordstore.org/)
- [pass man page](https://git.zx2c4.com/password-store/about/)
- [pass-otp](https://github.com/tadfisher/pass-otp)

### Python Resources
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [PEP 8 Style Guide](https://pep8.org/)
- [pytest Documentation](https://docs.pytest.org/)

## Maintainers

- Ronny Pfannschmidt ([@RonnyPfannschmidt](https://github.com/RonnyPfannschmidt))

## Thank You!

Your contributions make GTKPass better for everyone. We appreciate your time and effort! 🎉
