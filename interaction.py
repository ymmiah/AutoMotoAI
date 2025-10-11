"""
User interaction module for AutoMoto AI
Handles voice, text, and GUI interactions
"""

import pyttsx3
import speech_recognition as sr
import tkinter as tk
from tkinter import simpledialog, messagebox

# Initialize text-to-speech engine
engine = pyttsx3.init()

def speak(text):
    """Convert text to speech"""
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Error in text-to-speech: {e}")

def listen():
    """Listen to microphone and convert speech to text"""
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            print("Listening...")
            r.adjust_for_ambient_noise(source, duration=1)
            audio = r.listen(source, timeout=5)
        
        print("Processing speech...")
        text = r.recognize_google(audio)
        return text
    except sr.WaitTimeoutError:
        print("No speech detected")
        return ""
    except sr.UnknownValueError:
        print("Could not understand audio")
        return ""
    except sr.RequestError as e:
        print(f"Could not request results; {e}")
        return ""
    except Exception as e:
        print(f"Error in speech recognition: {e}")
        return ""

def ask_user(text, title="AutoMoto AI"):
    """Show a GUI dialog to get user input"""
    try:
        root = tk.Tk()
        root.withdraw()
        answer = simpledialog.askstring(title, text)
        root.destroy()
        return answer
    except Exception as e:
        print(f"Error showing dialog: {e}")
        return None

def show_message(text, title="AutoMoto AI", msg_type="info"):
    """Show a message box to the user"""
    try:
        root = tk.Tk()
        root.withdraw()
        
        if msg_type == "info":
            messagebox.showinfo(title, text)
        elif msg_type == "warning":
            messagebox.showwarning(title, text)
        elif msg_type == "error":
            messagebox.showerror(title, text)
        
        root.destroy()
    except Exception as e:
        print(f"Error showing message: {e}")

def ask_yes_no(text, title="AutoMoto AI"):
    """Show a yes/no dialog"""
    try:
        root = tk.Tk()
        root.withdraw()
        result = messagebox.askyesno(title, text)
        root.destroy()
        return result
    except Exception as e:
        print(f"Error showing yes/no dialog: {e}")
        return False

def get_input_method():
    """Ask user to choose input method"""
    try:
        root = tk.Tk()
        root.withdraw()
        choice = simpledialog.askstring(
            "AutoMoto AI - Input Method",
            "Choose input method:\n1. Type\n2. Voice\n\nEnter 1 or 2:"
        )
        root.destroy()
        return choice
    except Exception as e:
        print(f"Error getting input method: {e}")
        return "1"
