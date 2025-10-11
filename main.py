"""
AutoMoto AI - Main Application
A fully automated AI agent for Windows desktop automation
"""

import openai
import google.generativeai as genai
import anthropic
import requests
import json
from config import (
    OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, BLACKBOX_API_KEY,
    DEFAULT_AI_PROVIDER, SYSTEM_PROMPT, APP_NAME, VERSION,
    AI_MODELS, AI_TEMPERATURE, AI_MAX_TOKENS, BLACKBOX_API_URL
)
from prompts import get_task_prompt, get_analysis_prompt, get_clarification_prompt
from actions import (
    open_application, close_application, create_file, create_folder,
    type_text, press_key, hotkey, take_screenshot, say_hello,
    minimize_window, maximize_window, run_command
)
from interaction import speak, listen, ask_user, show_message, ask_yes_no, get_input_method

# Initialize AI providers
def initialize_ai_providers():
    """Initialize available AI providers"""
    providers = {}
    
    if OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here":
        openai.api_key = OPENAI_API_KEY
        providers['openai'] = True
    
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        genai.configure(api_key=GEMINI_API_KEY)
        providers['gemini'] = True
    
    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
        providers['claude'] = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    if BLACKBOX_API_KEY and BLACKBOX_API_KEY != "your_blackbox_api_key_here":
        providers['blackbox'] = True
    
    return providers

# Get available providers
available_providers = initialize_ai_providers()

def ask_ai_openai(prompt):
    """Send prompt to OpenAI"""
    try:
        response = openai.ChatCompletion.create(
            model=AI_MODELS['openai'],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=AI_TEMPERATURE,
            max_tokens=AI_MAX_TOKENS
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"OpenAI Error: {str(e)}"

def ask_ai_gemini(prompt):
    """Send prompt to Google Gemini"""
    try:
        model = genai.GenerativeModel(AI_MODELS['gemini'])
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser: {prompt}"
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=AI_TEMPERATURE,
                max_output_tokens=AI_MAX_TOKENS
            )
        )
        return response.text.strip()
    except Exception as e:
        return f"Gemini Error: {str(e)}"

def ask_ai_claude(prompt):
    """Send prompt to Anthropic Claude"""
    try:
        client = available_providers.get('claude')
        if not client:
            return "Claude Error: API key not configured"
        
        response = client.messages.create(
            model=AI_MODELS['claude'],
            max_tokens=AI_MAX_TOKENS,
            temperature=AI_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Claude Error: {str(e)}"

def ask_ai_blackbox(prompt):
    """Send prompt to BLACKBOX AI"""
    try:
        headers = {
            "Authorization": f"Bearer {BLACKBOX_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "model": AI_MODELS['blackbox'],
            "temperature": AI_TEMPERATURE,
            "max_tokens": AI_MAX_TOKENS
        }
        
        response = requests.post(BLACKBOX_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except requests.exceptions.RequestException as e:
        return f"BLACKBOX Error: {str(e)}"
    except Exception as e:
        return f"BLACKBOX Error: {str(e)}"

def ask_ai(prompt, provider=None):
    """Send a prompt to the configured AI provider"""
    if provider is None:
        provider = DEFAULT_AI_PROVIDER
    
    # Try the specified provider first
    if provider == 'openai' and 'openai' in available_providers:
        return ask_ai_openai(prompt)
    elif provider == 'gemini' and 'gemini' in available_providers:
        return ask_ai_gemini(prompt)
    elif provider == 'claude' and 'claude' in available_providers:
        return ask_ai_claude(prompt)
    elif provider == 'blackbox' and 'blackbox' in available_providers:
        return ask_ai_blackbox(prompt)
    
    # Fallback to any available provider
    if 'openai' in available_providers:
        print("Falling back to OpenAI...")
        return ask_ai_openai(prompt)
    elif 'gemini' in available_providers:
        print("Falling back to Gemini...")
        return ask_ai_gemini(prompt)
    elif 'claude' in available_providers:
        print("Falling back to Claude...")
        return ask_ai_claude(prompt)
    elif 'blackbox' in available_providers:
        print("Falling back to BLACKBOX...")
        return ask_ai_blackbox(prompt)
    
    return "Error: No AI provider configured. Please add an API key to .env file"

def parse_and_execute_task(task_desc):
    """Parse the task description and execute appropriate actions"""
    task_lower = task_desc.lower()
    
    # Simple task parsing and execution
    if "open" in task_lower:
        # Extract application name
        app_name = task_lower.replace("open", "").strip()
        speak(f"Opening {app_name}")
        return open_application(app_name)
    
    elif "close" in task_lower:
        # Extract window name
        window_name = task_lower.replace("close", "").strip()
        speak(f"Closing {window_name}")
        return close_application(window_name)
    
    elif "create file" in task_lower or "new file" in task_lower:
        filename = ask_user("Enter the filename:")
        if filename:
            speak(f"Creating file {filename}")
            return create_file(filename)
    
    elif "create folder" in task_lower or "new folder" in task_lower:
        foldername = ask_user("Enter the folder name:")
        if foldername:
            speak(f"Creating folder {foldername}")
            return create_folder(foldername)
    
    elif "screenshot" in task_lower:
        speak("Taking screenshot")
        return take_screenshot()
    
    elif "hello" in task_lower or "hi" in task_lower:
        say_hello()
        speak("Hello! How can I help you today?")
        return True
    
    elif "minimize" in task_lower:
        window_name = task_lower.replace("minimize", "").strip()
        speak(f"Minimizing {window_name}")
        return minimize_window(window_name)
    
    elif "maximize" in task_lower:
        window_name = task_lower.replace("maximize", "").strip()
        speak(f"Maximizing {window_name}")
        return maximize_window(window_name)
    
    else:
        # Use AI to understand complex tasks
        analysis = ask_ai(get_analysis_prompt(task_desc))
        show_message(f"AI Analysis:\n{analysis}", "Task Analysis")
        
        if ask_yes_no("Would you like me to attempt this task?"):
            speak("I'll try my best to complete this task")
            # For now, show that we need more specific implementation
            show_message("This task requires custom implementation. Please break it down into simpler commands.", "Info")
            return False
        else:
            speak("Task cancelled")
            return False

def main():
    """Main application loop"""
    print(f"Starting {APP_NAME} v{VERSION}")
    
    # Check if at least one API key is set
    if not available_providers:
        show_message(
            "Please set at least one AI provider API key in the .env file!\n\n"
            "1. Rename .env.example to .env\n"
            "2. Add at least one API key:\n"
            "   - OpenAI: https://platform.openai.com/api-keys\n"
            "   - Gemini: https://makersuite.google.com/app/apikey\n"
            "   - Claude: https://console.anthropic.com/\n"
            "   - BLACKBOX: https://www.blackbox.ai/\n"
            "3. Restart the application",
            "API Key Required",
            "error"
        )
        return
    
    # Show which provider is being used
    provider_name = DEFAULT_AI_PROVIDER.upper()
    if DEFAULT_AI_PROVIDER in available_providers:
        print(f"Using {provider_name} as AI provider")
    else:
        fallback = list(available_providers.keys())[0]
        print(f"Default provider {provider_name} not available, using {fallback.upper()}")
    
    # Welcome message
    speak(f"Hello! I am {APP_NAME}. What task would you like me to do?")
    show_message(
        f"Welcome to {APP_NAME}!\n\n"
        "I can help you with:\n"
        "- Opening/closing applications\n"
        "- Creating files and folders\n"
        "- Taking screenshots\n"
        "- Window management\n"
        "- And much more!\n\n"
        "Type 'exit' or 'quit' to stop.",
        "Welcome"
    )
    
    # Main loop
    while True:
        try:
            # Get input method choice
            input_method = get_input_method()
            
            if input_method == "2":
                # Voice input
                speak("Please speak your command")
                task_desc = listen()
                if not task_desc:
                    speak("I didn't catch that. Please try again.")
                    continue
            else:
                # Text input
                task_desc = ask_user("Please enter your task description:")
            
            # Check for exit commands
            if task_desc is None or task_desc.lower() in ['exit', 'quit', 'stop', 'bye']:
                speak("Goodbye! Have a great day!")
                show_message("Thank you for using AutoMoto AI!", "Goodbye")
                break
            
            if not task_desc.strip():
                continue
            
            print(f"\nTask received: {task_desc}")
            
            # Get AI confirmation/analysis
            confirm_prompt = get_task_prompt(task_desc)
            ai_response = ask_ai(confirm_prompt)
            
            print(f"AI Response: {ai_response}")
            
            # Ask user for confirmation
            if ask_yes_no(f"Task: {task_desc}\n\nAI says: {ai_response}\n\nProceed with execution?"):
                speak("Executing your task now")
                success = parse_and_execute_task(task_desc)
                
                if success:
                    speak("Task completed successfully")
                    show_message("Task completed successfully!", "Success")
                else:
                    speak("Task execution encountered an issue")
                    show_message("Task could not be completed. Please try a different command.", "Info")
            else:
                speak("Task cancelled. Please specify something else.")
                show_message("Task cancelled by user.", "Cancelled")
        
        except KeyboardInterrupt:
            print("\nInterrupted by user")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            show_message(f"An error occurred: {str(e)}", "Error", "error")
            speak("An error occurred. Please try again.")

if __name__ == "__main__":
    main()
