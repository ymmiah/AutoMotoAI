"""
Desktop automation actions for AutoMoto AI
"""

import pyautogui
import time
import os
import subprocess

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 1

def open_application(app_path):
    """Open an application by path or name"""
    try:
        if os.path.exists(app_path):
            subprocess.Popen(app_path)
        else:
            # Try to open via Windows search
            pyautogui.press('win')
            time.sleep(1)
            pyautogui.write(app_path)
            time.sleep(1)
            pyautogui.press('enter')
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Error opening application: {e}")
        return False

def close_application(window_title):
    """Close an application by window title"""
    try:
        windows = pyautogui.getWindowsWithTitle(window_title)
        if windows:
            windows[0].close()
            return True
        return False
    except Exception as e:
        print(f"Error closing application: {e}")
        return False

def create_file(filepath, content=""):
    """Create a new file with optional content"""
    try:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Error creating file: {e}")
        return False

def create_folder(folderpath):
    """Create a new folder"""
    try:
        os.makedirs(folderpath, exist_ok=True)
        return True
    except Exception as e:
        print(f"Error creating folder: {e}")
        return False

def type_text(text, interval=0.05):
    """Type text with specified interval between characters"""
    pyautogui.write(text, interval=interval)

def press_key(key):
    """Press a single key"""
    pyautogui.press(key)

def hotkey(*keys):
    """Press a combination of keys"""
    pyautogui.hotkey(*keys)

def take_screenshot(filename="screenshot.png"):
    """Take a screenshot and save it"""
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(filename)
        return True
    except Exception as e:
        print(f"Error taking screenshot: {e}")
        return False

def get_active_window_title():
    """Get the title of the currently active window"""
    try:
        return pyautogui.getActiveWindow().title
    except:
        return None

def minimize_window(window_title):
    """Minimize a window by title"""
    try:
        windows = pyautogui.getWindowsWithTitle(window_title)
        if windows:
            windows[0].minimize()
            return True
        return False
    except Exception as e:
        print(f"Error minimizing window: {e}")
        return False

def maximize_window(window_title):
    """Maximize a window by title"""
    try:
        windows = pyautogui.getWindowsWithTitle(window_title)
        if windows:
            windows[0].maximize()
            return True
        return False
    except Exception as e:
        print(f"Error maximizing window: {e}")
        return False

def say_hello():
    """Simple hello function for testing"""
    print("Hello from AutoMoto AI!")

def run_command(command):
    """Run a system command"""
    try:
        subprocess.run(command, shell=True, check=True)
        return True
    except Exception as e:
        print(f"Error running command: {e}")
        return False
