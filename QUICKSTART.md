# 🚀 AutoMoto AI - Quick Start Guide

Get up and running with AutoMoto AI in 5 minutes!

---

## ⚡ Fast Setup (Windows)

### Step 1: Run Setup Script
Double-click `setup.bat` in the AutoMotoAI folder. This will:
- Create a virtual environment
- Install all dependencies
- Run installation tests

### Step 2: Configure API Key
1. Rename `.env.example` to `.env`
2. Get your OpenAI API key from: https://platform.openai.com/api-keys
3. Open `.env` in Notepad
4. Replace `your_openai_api_key_here` with your actual key
5. Save and close

### Step 3: Run the App
Double-click `run.bat` to start AutoMoto AI!

---

## 🎯 First Commands to Try

Once the app starts, try these commands:

### Basic Commands
```
"hello"                    → Test the AI response
"open notepad"            → Opens Notepad
"take a screenshot"       → Captures your screen
"create a new file"       → Creates a file (you'll be prompted for name)
```

### Window Management
```
"minimize notepad"        → Minimizes Notepad window
"maximize chrome"         → Maximizes Chrome window
"close calculator"        → Closes Calculator
```

---

## 💡 Tips for Best Results

### ✅ DO:
- Use clear, simple commands
- Confirm tasks when prompted
- Start with basic commands to learn
- Use text input if voice isn't working

### ❌ DON'T:
- Give vague or complex multi-step commands initially
- Move mouse to screen corners during automation (failsafe)
- Run without confirming tasks first

---

## 🎤 Voice vs Text Input

When the app starts, you'll choose:

**Option 1 - Text Input** (Recommended for beginners)
- Type your commands in a dialog box
- More reliable and precise
- No microphone needed

**Option 2 - Voice Input**
- Speak your commands
- Requires working microphone
- Needs internet connection
- May have recognition errors

---

## 🔧 Quick Troubleshooting

### "API key not set"
→ Make sure you renamed `.env.example` to `.env` and added your key

### "Module not found"
→ Run `setup.bat` again or manually: `pip install -r requirements.txt`

### Voice input not working
→ Switch to text input (Option 1) or check microphone permissions

### App won't start
→ Make sure Python 3.10+ is installed and in PATH

---

## 📚 Learn More

- **README.md** - Full documentation and features
- **DOCUMENTATION.md** - Technical details and API info
- **setup_guide.txt** - Detailed setup instructions

---

## 🎓 Example Session

```
AutoMoto AI: "Hello! I am AutoMoto AI. What task would you like me to do?"

[Choose input method: 1 for text, 2 for voice]
You: 1

[Dialog box appears]
You: "open notepad"

AutoMoto AI: "Task: open notepad
AI says: User requested task: open notepad. Should I proceed? (Yes/No)
Proceed with execution?"

You: [Click Yes]

AutoMoto AI: "Executing your task now"
[Notepad opens]
AutoMoto AI: "Task completed successfully!"

[Dialog box appears again for next command]
You: "exit"

AutoMoto AI: "Goodbye! Have a great day!"
```

---

## 🆘 Need Help?

1. Check the troubleshooting section above
2. Read `setup_guide.txt` for detailed instructions
3. Review `DOCUMENTATION.md` for technical details
4. Test your installation with: `python test_installation.py`

---

## 🎉 You're Ready!

Start exploring AutoMoto AI's capabilities. Begin with simple commands and gradually try more complex tasks as you get comfortable.

**Have fun automating! 🤖**
