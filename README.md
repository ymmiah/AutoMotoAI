<div align="center">
  <h1>🤖 AutoMoto AI</h1>
  <p><strong>Intelligent Windows Desktop Automation Agent</strong></p>
  <p>Transform natural language commands into automated desktop actions using multiple AI providers</p>

  <p>
    <a href="#-features">Features</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-ai-providers">AI Providers</a> •
    <a href="#-documentation">Documentation</a> •
    <a href="#-contributing">Contributing</a> •
    <a href="#-license">License</a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/version-2.1.0-blue.svg" alt="Version">
    <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/windows-10+-blue.svg" alt="Windows Support">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
  </p>

  <p>
    <img src="https://img.shields.io/badge/OpenAI-GPT--4-412991.svg" alt="OpenAI">
    <img src="https://img.shields.io/badge/Google-Gemini-4285F4.svg" alt="Google Gemini">
    <img src="https://img.shields.io/badge/Anthropic-Claude-191919.svg" alt="Anthropic Claude">
    <img src="https://img.shields.io/badge/BLACKBOX-AI-000000.svg" alt="BLACKBOX AI">
  </p>
</div>

---

## 🎯 What is AutoMoto AI?

AutoMoto AI is a revolutionary Windows desktop automation tool that bridges the gap between human language and computer actions. Using advanced AI models, it transforms your natural language commands into automated desktop operations, making computer interaction as simple as having a conversation.

### ✨ Key Highlights
- 🎤 **Voice & Text Input** - Speak or type commands naturally
- 🤖 **Multi-AI Support** - Choose from 4 powerful AI providers
- 🖥️ **Desktop Automation** - Control applications, files, and windows
- 🔒 **Safe Execution** - All actions require user confirmation
- 📸 **Screenshot Capture** - Instant screen capture functionality
- 🔄 **Auto Fallback** - Automatically switches providers if needed

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+** (download from [python.org](https://python.org))
- **Windows 10/11** operating system
- **At least one AI provider API key** (see [AI Providers](#-ai-providers) section)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ymmiah/AutoMotoAI.git
   cd AutoMotoAI
   ```

2. **Run automated setup:**
   ```bash
   setup.bat  # Windows automated installation
   ```

3. **Configure API keys:**
   ```bash
   # Rename .env.example to .env and add your API keys
   copy .env.example .env
   # Edit .env file with your API keys
   ```

4. **Launch the application:**
   ```bash
   run.bat  # or python main.py
   ```

### First Commands to Try
- `"hello"` - Test AI response
- `"open notepad"` - Launch Notepad
- `"take a screenshot"` - Capture screen
- `"create a new file"` - Create a file

---

## 🤖 AI Providers

AutoMoto AI supports **4 major AI providers** with automatic fallback capabilities:

| Provider | Model | Cost | Best For |
|----------|-------|------|----------|
| **OpenAI GPT-4** | `gpt-4` | ~$0.03/1K tokens | Complex reasoning, best quality |
| **Google Gemini** | `gemini-pro` | Free tier available | Fast responses, cost-effective |
| **Anthropic Claude** | `claude-3-sonnet` | ~$0.003/1K tokens | Balanced performance |
| **BLACKBOX AI** | `blackbox-ai` | Competitive | Developer-focused, code generation |

### Getting API Keys

#### OpenAI GPT-4
1. Visit [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Sign up/login to your account
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`)

#### Google Gemini
1. Visit [makersuite.google.com/app/apikey](https://makersuite.google.com/app/apikey)
2. Sign in with Google account
3. Click "Create API Key"
4. Copy the generated key

#### Anthropic Claude
1. Visit [console.anthropic.com](https://console.anthropic.com)
2. Create account and navigate to API Keys
3. Generate new API key
4. Copy the key (starts with `sk-ant-`)

#### BLACKBOX AI
1. Visit [www.blackbox.ai](https://www.blackbox.ai)
2. Sign up for an account
3. Navigate to API section
4. Generate your API key
5. Copy the key

### Configuration
Add your API keys to the `.env` file:
```env
# AI Provider API Keys
OPENAI_API_KEY=sk-your-openai-key-here
GEMINI_API_KEY=your-gemini-key-here
ANTHROPIC_API_KEY=sk-ant-your-claude-key-here
BLACKBOX_API_KEY=your-blackbox-key-here

# Default AI Provider (openai, gemini, claude, or blackbox)
DEFAULT_AI_PROVIDER=openai
```

---

## 🎯 Features

### Core Automation
- ✅ **Application Control** - Open, close, minimize, maximize applications
- ✅ **File Management** - Create files and folders with content
- ✅ **Window Management** - Control window states and focus
- ✅ **Screenshot Capture** - Instant screen capture to file
- ✅ **Keyboard & Mouse** - Simulate typing, clicks, and shortcuts

### AI-Powered Intelligence
- ✅ **Natural Language Processing** - Understand complex commands
- ✅ **Task Analysis** - Break down multi-step operations
- ✅ **Smart Suggestions** - Provide helpful clarifications
- ✅ **Context Awareness** - Remember conversation context
- ✅ **Error Recovery** - Handle failures gracefully

### User Experience
- ✅ **Voice Input** - Speech recognition support
- ✅ **Text Input** - Traditional typing interface
- ✅ **GUI Dialogs** - Clean, intuitive user interface
- ✅ **Text-to-Speech** - Audio feedback for actions
- ✅ **Confirmation System** - Safety-first execution model

### Advanced Features
- ✅ **Multi-Provider Support** - 4 AI providers available
- ✅ **Automatic Fallback** - Switch providers seamlessly
- ✅ **Customizable Prompts** - Modify AI behavior
- ✅ **Logging System** - Track actions and errors
- ✅ **Batch Operations** - Execute multiple tasks

---

## 📚 Documentation

### 📖 User Guides
- **[Getting Started](docs/getting-started.html)** - Complete setup guide
- **[Installation Guide](docs/installation.html)** - Detailed installation instructions
- **[AI Providers Guide](docs/ai-providers.html)** - Configure AI providers
- **[Features Guide](docs/features.html)** - All capabilities explained

### 🛠️ Developer Resources
- **[API Reference](docs/api-reference.html)** - Function documentation
- **[Usage Guide](docs/usage.html)** - Advanced usage patterns
- **[Troubleshooting](docs/troubleshooting.html)** - Common issues & solutions
- **[Examples](docs/examples.html)** - Sample commands and use cases

### 📋 Additional Resources
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and updates
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture

### 🌐 Live Documentation
Open `docs/index.html` in your browser for the complete interactive documentation website.

---

## 🏗️ Project Structure

```
AutoMotoAI/
├── 📁 docs/                    # HTML Documentation Website
│   ├── index.html             # Home page
│   ├── styles.css             # Responsive styling
│   ├── getting-started.html   # Setup guide
│   ├── installation.html      # Installation guide
│   ├── ai-providers.html      # AI providers guide
│   └── features.html          # Features documentation
├── 📄 main.py                 # Main application entry point
├── 📄 config.py               # Configuration and settings
├── 📄 actions.py              # Desktop automation functions
├── 📄 interaction.py          # User interaction handlers
├── 📄 prompts.py              # AI prompt templates
├── 📄 requirements.txt        # Python dependencies
├── 📄 .env.example           # Environment variables template
├── 📄 test_installation.py   # Installation verification
├── 📄 setup.bat              # Automated setup script
├── 📄 run.bat                # Launch script
├── 📄 CHANGELOG.md           # Version history
├── 📄 README.md              # This file
└── 📄 .gitignore             # Git ignore rules
```

---

## 🔧 System Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **Operating System** | Windows 10/11 (64-bit) | Designed specifically for Windows |
| **Python Version** | 3.10 or higher | Must be added to PATH |
| **RAM** | 4GB minimum, 8GB recommended | For smooth AI processing |
| **Disk Space** | 500MB free space | For dependencies and data |
| **Internet** | Active connection | Required for AI API calls |
| **Microphone** | Optional | Required only for voice input |

---

## 🐛 Troubleshooting

### Common Issues

**"Python not found"**
```bash
# Reinstall Python and check "Add Python to PATH"
python --version
```

**"Module import errors"**
```bash
# Activate virtual environment
venv\Scripts\activate
# Reinstall dependencies
pip install -r requirements.txt
```

**"API key not working"**
- Verify key is correctly copied (no extra spaces)
- Check if key has been activated
- Ensure billing is set up for paid providers

**"Voice input not working"**
- Check microphone permissions in Windows Settings
- Ensure microphone is properly connected
- Try text input mode instead

### Getting Help
- 📖 Check the [Troubleshooting Guide](docs/troubleshooting.html)
- 🐛 [Open an Issue](https://github.com/ymmiah/AutoMotoAI/issues)
- 💬 [Discussions](https://github.com/ymmiah/AutoMotoAI/discussions)

---

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Ways to Contribute
- 🐛 **Bug Reports** - [Open an Issue](https://github.com/ymmiah/AutoMotoAI/issues)
- 💡 **Feature Requests** - [Start a Discussion](https://github.com/ymmiah/AutoMotoAI/discussions)
- 🔧 **Code Contributions** - Submit a Pull Request
- 📚 **Documentation** - Help improve our docs
- 🧪 **Testing** - Test on different Windows versions

### Development Setup
```bash
# Fork and clone the repository
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

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **OpenAI** for GPT-4 API
- **Google** for Gemini API
- **Anthropic** for Claude API
- **BLACKBOX AI** for their API
- **Python Community** for amazing libraries
- **Contributors** for their valuable input

---

## 📞 Support

- 📧 **Email**: ymmiah96@gmail.com
- 🐛 **Issues**: [GitHub Issues](https://github.com/ymmiah/AutoMotoAI/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/ymmiah/AutoMotoAI/discussions)
- 📖 **Documentation**: [docs/index.html](docs/index.html)

---

## 📊 Version History

### v2.1.0 (11/10/2025) - Current
- ✅ Added BLACKBOX AI as 4th AI provider
- ✅ Complete HTML/CSS documentation website
- ✅ Enhanced error handling and fallback logic
- ✅ Updated version history and changelog

### v2.0.0 (11/10/2025)
- ✅ Added Google Gemini and Anthropic Claude support
- ✅ Multi-provider architecture with automatic fallback
- ✅ Enhanced configuration system

### v1.0.0 (11/10/2025)
- ✅ Initial release with OpenAI GPT-4
- ✅ Core desktop automation features
- ✅ Voice and text input support

---

<div align="center">
  <p><strong>Built with ❤️ using Python and Powered by Yasin Mohammed Miah.</strong></p>
  <p>
    <a href="#top">Back to Top</a> •
    <a href="docs/index.html">Documentation</a> •
    <a href="CHANGELOG.md">Changelog</a>
  </p>
</div>


