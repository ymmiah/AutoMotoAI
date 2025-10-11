# Contributing to AutoMoto AI

Thank you for your interest in contributing to AutoMoto AI! We welcome contributions from the community. This document provides guidelines and information for contributors.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)
- [Documentation](#documentation)
- [Testing](#testing)
- [Style Guidelines](#style-guidelines)

## 🤝 Code of Conduct

This project follows a code of conduct to ensure a welcoming environment for all contributors. By participating, you agree to:

- Be respectful and inclusive
- Focus on constructive feedback
- Accept responsibility for mistakes
- Show empathy towards other contributors
- Help create a positive community

See our [Code of Conduct](CODE_OF_CONDUCT.md) for more details.

## 🚀 Getting Started

### Prerequisites
- Python 3.10 or higher
- Windows 10/11 (for testing desktop automation)
- Git for version control
- At least one AI provider API key (for testing)

### Quick Setup
```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/ymmiah/AutoMotoAI.git
cd AutoMotoAI

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run tests
python test_installation.py

# Start development
python main.py
```

## 💡 How to Contribute

### Types of Contributions

#### 🐛 Bug Fixes
- Fix bugs in existing code
- Improve error handling
- Fix compatibility issues

#### ✨ New Features
- Add new automation capabilities
- Implement new AI provider support
- Enhance user interface

#### 📚 Documentation
- Improve existing documentation
- Add new guides and tutorials
- Translate documentation

#### 🧪 Testing
- Write unit tests
- Add integration tests
- Test on different Windows versions

#### 🎨 UI/UX Improvements
- Improve user interface
- Enhance user experience
- Add accessibility features

### Contribution Process

1. **Choose an Issue**: Look for open issues or create a new one
2. **Fork the Repository**: Create your own fork
3. **Create a Branch**: Use descriptive branch names
4. **Make Changes**: Implement your contribution
5. **Test Thoroughly**: Ensure your changes work correctly
6. **Submit a Pull Request**: Follow the PR template

## 🛠️ Development Setup

### Detailed Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ymmiah/AutoMotoAI.git
   cd AutoMotoAI
   ```

2. **Set up Python environment:**
   ```bash
   # Create virtual environment
   python -m venv venv

   # Activate virtual environment
   venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   # Copy environment template
   copy .env.example .env

   # Edit .env with your API keys (optional for basic testing)
   ```

5. **Run tests:**
   ```bash
   python test_installation.py
   ```

6. **Start development:**
   ```bash
   python main.py
   ```

### Development Tools

#### Recommended IDEs
- **Visual Studio Code** (recommended)
  - Python extension
  - Pylint for linting
  - Black for formatting
- **PyCharm Professional**
- **Any Python-compatible IDE**

#### Useful Extensions
- Python (Microsoft)
- Pylint
- Python Docstring Generator
- GitLens

## 📝 Submitting Changes

### Pull Request Process

1. **Create a Branch:**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-number-description
   ```

2. **Make Your Changes:**
   - Write clear, concise code
   - Add comments for complex logic
   - Update documentation if needed
   - Add tests for new features

3. **Test Your Changes:**
   ```bash
   # Run installation tests
   python test_installation.py

   # Test your specific changes
   python main.py
   ```

4. **Commit Your Changes:**
   ```bash
   git add .
   git commit -m "feat: add new automation feature

   - Added support for new application type
   - Improved error handling
   - Updated documentation

   Closes #123"
   ```

5. **Push and Create PR:**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then create a Pull Request on GitHub.

### Commit Message Guidelines

We follow conventional commit format:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation changes
- `style`: Code style changes
- `refactor`: Code refactoring
- `test`: Testing changes
- `chore`: Maintenance tasks

Examples:
```
feat: add BLACKBOX AI provider support
fix: resolve PyAutoGUI compatibility issue
docs: update installation guide
```

## 🐛 Reporting Issues

### Bug Reports

When reporting bugs, please include:

1. **Clear Title**: Describe the issue concisely
2. **Steps to Reproduce**: Detailed steps to reproduce the bug
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**: Python version, Windows version, etc.
6. **Screenshots/Logs**: If applicable

### Feature Requests

For feature requests, please include:

1. **Clear Description**: What feature you want
2. **Use Case**: Why you need this feature
3. **Implementation Ideas**: How you think it could work
4. **Alternatives**: Other solutions you've considered

## 📚 Documentation

### Documentation Standards

- Use clear, concise language
- Include code examples where helpful
- Keep screenshots up to date
- Test all instructions on a clean environment

### Updating Documentation

1. **HTML Documentation**: Edit files in `docs/` folder
2. **Markdown Files**: Update relevant `.md` files
3. **Code Comments**: Update docstrings and inline comments
4. **README**: Update main README.md for significant changes

## 🧪 Testing

### Running Tests

```bash
# Run installation verification
python test_installation.py

# Test specific functionality
python main.py
```

### Writing Tests

- Add tests for new features
- Test edge cases and error conditions
- Ensure cross-platform compatibility
- Test with different AI providers

### Test Coverage

Aim for good test coverage of:
- Core functionality
- Error handling
- User interactions
- AI provider integrations

## 🎨 Style Guidelines

### Python Code Style

We follow PEP 8 with some modifications:

```python
# Good: Clear variable names
def open_application(app_path):
    """Open an application by path or name."""
    try:
        if os.path.exists(app_path):
            subprocess.Popen(app_path)
        else:
            # Try Windows search
            pyautogui.press('win')
            time.sleep(1)
            pyautogui.write(app_path)
            pyautogui.press('enter')
        return True
    except Exception as e:
        print(f"Error opening application: {e}")
        return False

# Bad: Unclear names and poor structure
def oa(ap):
    try:
        if os.path.exists(ap):
            subprocess.Popen(ap)
        else:
            pyautogui.press('win')
            time.sleep(1)
            pyautogui.write(ap)
            pyautogui.press('enter')
        return True
    except:
        return False
```

### Key Guidelines

1. **Readability**: Code should be self-documenting
2. **Comments**: Add docstrings and comments for complex logic
3. **Error Handling**: Use try/except blocks appropriately
4. **Imports**: Group imports properly (standard, third-party, local)
5. **Naming**: Use descriptive variable and function names
6. **Line Length**: Keep lines under 88 characters
7. **Functions**: Keep functions focused on single responsibilities

### Documentation Style

- Use Google-style docstrings
- Include type hints where helpful
- Document parameters, return values, and exceptions
- Keep documentation up to date

## 📞 Getting Help

### Communication Channels

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For general questions
- **Documentation**: Check docs/index.html first

### Asking for Help

When asking for help:

1. **Search First**: Check existing issues and documentation
2. **Be Specific**: Include error messages, code snippets, environment details
3. **Provide Context**: Explain what you're trying to accomplish
4. **Share Solutions**: If you find a solution, share it with others

## 🎯 Recognition

Contributors will be recognized in:
- CHANGELOG.md for significant contributions
- GitHub repository contributors list
- Release notes for major features

## 📋 Checklist for Contributions

- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] PR description explains changes
- [ ] No sensitive information included
- [ ] License headers included (if new files)

---

Thank you for contributing to AutoMoto AI! Your contributions help make desktop automation more accessible and powerful for everyone.

For questions or help getting started, don't hesitate to [open an issue](https://github.com/ymmiah/AutoMotoAI/issues) or [start a discussion](https://github.com/ymmiah/AutoMotoAI/discussions).

