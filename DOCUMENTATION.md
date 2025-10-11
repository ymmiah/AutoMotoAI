# AutoMoto AI - Technical Documentation

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Module Details](#module-details)
3. [API Integration](#api-integration)
4. [Extending Functionality](#extending-functionality)
5. [Security Considerations](#security-considerations)
6. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

AutoMoto AI follows a modular architecture with clear separation of concerns:

```
┌─────────────────────────────────────────┐
│           User Interface Layer          │
│  (interaction.py - Voice/Text/GUI)      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│         Application Logic Layer         │
│     (main.py - Task Processing)         │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼────────┐   ┌────────▼─────────┐
│   AI Layer     │   │  Action Layer    │
│ (OpenAI API)   │   │  (actions.py)    │
└────────────────┘   └──────────────────┘
        │                     │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │  Configuration      │
        │  (config.py)        │
        └─────────────────────┘
```

---

## Module Details

### 1. config.py
**Purpose**: Central configuration management

**Key Components**:
- `OPENAI_API_KEY`: Stores the OpenAI API key from environment variables
- `SYSTEM_PROMPT`: Defines the AI agent's behavior and capabilities
- `APP_NAME`, `VERSION`: Application metadata

**Usage**:
```python
from config import OPENAI_API_KEY, SYSTEM_PROMPT
```

### 2. prompts.py
**Purpose**: Template management for AI interactions

**Functions**:
- `get_task_prompt(task_desc)`: Creates confirmation prompts
- `get_analysis_prompt(task_desc)`: Generates task analysis requests
- `get_error_prompt(error_msg)`: Handles error scenarios
- `get_clarification_prompt(task_desc)`: Requests task clarification

**Example**:
```python
from prompts import get_task_prompt
prompt = get_task_prompt("Open notepad")
# Returns: "User requested task: Open notepad. Should I proceed? (Yes/No)"
```

### 3. actions.py
**Purpose**: Desktop automation and system interaction

**Key Functions**:

| Function | Description | Parameters | Returns |
|----------|-------------|------------|---------|
| `open_application(app_path)` | Opens an application | app_path: str | bool |
| `close_application(window_title)` | Closes a window | window_title: str | bool |
| `create_file(filepath, content)` | Creates a file | filepath: str, content: str | bool |
| `create_folder(folderpath)` | Creates a folder | folderpath: str | bool |
| `type_text(text, interval)` | Types text | text: str, interval: float | None |
| `take_screenshot(filename)` | Captures screen | filename: str | bool |

**Safety Features**:
- `pyautogui.FAILSAFE = True`: Move mouse to corner to stop
- `pyautogui.PAUSE = 1`: 1-second delay between actions

### 4. interaction.py
**Purpose**: User interaction management

**Functions**:

| Function | Description | Returns |
|----------|-------------|---------|
| `speak(text)` | Text-to-speech output | None |
| `listen()` | Speech-to-text input | str |
| `ask_user(text, title)` | GUI text input dialog | str or None |
| `show_message(text, title, msg_type)` | Display message box | None |
| `ask_yes_no(text, title)` | Yes/No confirmation | bool |
| `get_input_method()` | Choose input method | str |

**Example**:
```python
from interaction import speak, ask_user
speak("Hello!")
response = ask_user("Enter your name:")
```

### 5. main.py
**Purpose**: Application entry point and main logic

**Key Functions**:
- `ask_ai(prompt)`: Communicates with OpenAI API
- `parse_and_execute_task(task_desc)`: Parses and executes tasks
- `main()`: Main application loop

**Flow**:
1. Initialize and check API key
2. Display welcome message
3. Enter main loop:
   - Get user input (voice or text)
   - Send to AI for analysis
   - Request user confirmation
   - Execute task
   - Provide feedback
4. Handle exit gracefully

---

## API Integration

### OpenAI API Configuration

**Model Used**: GPT-4

**Parameters**:
```python
{
    "model": "gpt-4",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ],
    "temperature": 0.3,  # Lower = more deterministic
    "max_tokens": 500    # Response length limit
}
```

**Error Handling**:
```python
try:
    response = openai.ChatCompletion.create(...)
except openai.error.AuthenticationError:
    # Invalid API key
except openai.error.RateLimitError:
    # Rate limit exceeded
except openai.error.APIError:
    # API error
```

---

## Extending Functionality

### Adding New Actions

1. **Define the action in actions.py**:
```python
def new_action(param1, param2):
    """Description of the action"""
    try:
        # Implementation
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False
```

2. **Import in main.py**:
```python
from actions import new_action
```

3. **Add to task parser**:
```python
def parse_and_execute_task(task_desc):
    task_lower = task_desc.lower()
    
    if "keyword" in task_lower:
        # Extract parameters
        param = extract_param(task_lower)
        speak(f"Executing new action with {param}")
        return new_action(param)
```

### Adding New Prompts

Add to `prompts.py`:
```python
def get_custom_prompt(context):
    return f"Custom prompt with {context}"
```

### Customizing AI Behavior

Modify `SYSTEM_PROMPT` in `config.py`:
```python
SYSTEM_PROMPT = """
You are AutoMoto AI with enhanced capabilities:
- [Add new capability]
- [Add new behavior]
- [Add new constraint]
"""
```

---

## Security Considerations

### API Key Protection
- ✅ Store in `.env` file (not in code)
- ✅ Add `.env` to `.gitignore`
- ✅ Never commit API keys to version control
- ✅ Use environment variables

### Task Execution Safety
- ✅ Always request user confirmation
- ✅ Display task details before execution
- ✅ Enable PyAutoGUI failsafe
- ✅ Validate file paths
- ✅ Sanitize user input

### Best Practices
```python
# ❌ Bad: Direct execution
os.system(user_input)

# ✅ Good: Validated execution
if validate_command(user_input):
    if ask_yes_no(f"Execute: {user_input}?"):
        subprocess.run(user_input, shell=True)
```

---

## Troubleshooting

### Common Issues

#### 1. Import Errors
**Problem**: `ModuleNotFoundError: No module named 'openai'`

**Solution**:
```bash
# Activate virtual environment
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 2. API Key Issues
**Problem**: `openai.error.AuthenticationError`

**Solution**:
- Verify `.env` file exists
- Check API key format: `sk-...`
- Ensure no extra spaces or quotes
- Verify key is active on OpenAI platform

#### 3. Voice Input Not Working
**Problem**: Speech recognition fails

**Solution**:
- Check microphone permissions
- Test microphone in Windows settings
- Ensure internet connection (Google Speech API)
- Use text input as alternative

#### 4. PyAutoGUI Errors
**Problem**: `pyautogui.FailSafeException`

**Solution**:
- Don't move mouse to screen corners during automation
- Increase `pyautogui.PAUSE` value
- Run with administrator privileges if needed

### Debug Mode

Enable detailed logging:
```python
# Add to main.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Testing Individual Modules

```bash
# Test imports
python test_installation.py

# Test specific module
python -c "from actions import open_application; print('OK')"

# Test AI connection
python -c "from main import ask_ai; print(ask_ai('Hello'))"
```

---

## Performance Optimization

### Reducing API Costs
- Cache common responses
- Use GPT-3.5-turbo for simple tasks
- Implement local task parsing for common commands

### Improving Response Time
- Pre-load modules
- Use async operations
- Implement command queue

---

## Future Development Roadmap

### Phase 1: Core Enhancements
- [ ] Command history and favorites
- [ ] Task scheduling
- [ ] Multi-step task execution
- [ ] Error recovery mechanisms

### Phase 2: Advanced Features
- [ ] Web browser automation (Selenium)
- [ ] Email integration
- [ ] Calendar management
- [ ] File organization AI

### Phase 3: UI/UX Improvements
- [ ] Rich GUI interface (PyQt/Tkinter)
- [ ] System tray integration
- [ ] Hotkey activation
- [ ] Visual task builder

### Phase 4: Intelligence
- [ ] Learning from user patterns
- [ ] Context-aware suggestions
- [ ] Multi-agent collaboration
- [ ] Custom skill plugins

---

## Contributing

To contribute to AutoMoto AI:

1. Fork the repository
2. Create a feature branch
3. Follow the existing code style
4. Add tests for new features
5. Update documentation
6. Submit a pull request

---

## License & Credits

**AutoMoto AI** - Built with Python and OpenAI

**Dependencies**:
- OpenAI Python Library
- PyAutoGUI
- pyttsx3
- SpeechRecognition
- python-dotenv

---

**Version**: 1.0.0  
**Last Updated**: 2024
