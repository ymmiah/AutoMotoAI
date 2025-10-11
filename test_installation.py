"""
Test script to verify AutoMoto AI installation
Run this to check if all dependencies are properly installed
"""

import sys

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing AutoMoto AI Installation...\n")
    print("=" * 50)
    
    modules = {
        'openai': 'OpenAI API client',
        'google.generativeai': 'Google Gemini API client',
        'anthropic': 'Anthropic Claude API client',
        'requests': 'HTTP requests (for BLACKBOX AI)',
        'dotenv': 'Environment variables (python-dotenv)',
        'pyttsx3': 'Text-to-speech',
        'speech_recognition': 'Speech recognition',
        'pyautogui': 'Desktop automation',
        'tkinter': 'GUI dialogs'
    }
    
    failed = []
    passed = []
    
    for module, description in modules.items():
        try:
            if module == 'dotenv':
                __import__('dotenv')
            elif module == 'speech_recognition':
                __import__('speech_recognition')
            else:
                __import__(module)
            print(f"✓ {description}: OK")
            passed.append(module)
        except ImportError as e:
            print(f"✗ {description}: FAILED")
            print(f"  Error: {e}")
            failed.append(module)
    
    print("=" * 50)
    print(f"\nResults: {len(passed)} passed, {len(failed)} failed")
    
    if failed:
        print("\nTo fix failed imports, run:")
        print("pip install -r requirements.txt")
        return False
    else:
        print("\n✓ All dependencies installed successfully!")
        return True

def test_config():
    """Test if configuration is set up"""
    print("\n" + "=" * 50)
    print("Testing Configuration...")
    print("=" * 50)
    
    try:
        from config import OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, BLACKBOX_API_KEY, DEFAULT_AI_PROVIDER
        
        configured_providers = []
        
        # Check OpenAI
        if OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here":
            print("✓ OpenAI API key configured")
            configured_providers.append('openai')
        else:
            print("○ OpenAI API key not configured (optional)")
        
        # Check Gemini
        if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
            print("✓ Gemini API key configured")
            configured_providers.append('gemini')
        else:
            print("○ Gemini API key not configured (optional)")
        
        # Check Claude
        if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
            print("✓ Claude API key configured")
            configured_providers.append('claude')
        else:
            print("○ Claude API key not configured (optional)")
        
        # Check BLACKBOX
        if BLACKBOX_API_KEY and BLACKBOX_API_KEY != "your_blackbox_api_key_here":
            print("✓ BLACKBOX AI API key configured")
            configured_providers.append('blackbox')
        else:
            print("○ BLACKBOX AI API key not configured (optional)")
        
        if not configured_providers:
            print("\n✗ No AI provider API keys configured")
            print("  Please add at least one API key to .env file:")
            print("  - OpenAI: https://platform.openai.com/api-keys")
            print("  - Gemini: https://makersuite.google.com/app/apikey")
            print("  - Claude: https://console.anthropic.com/")
            print("  - BLACKBOX: https://www.blackbox.ai/")
            return False
        
        print(f"\n✓ {len(configured_providers)} AI provider(s) configured: {', '.join(configured_providers)}")
        print(f"✓ Default provider: {DEFAULT_AI_PROVIDER}")
        
        if DEFAULT_AI_PROVIDER not in configured_providers:
            print(f"⚠ Warning: Default provider '{DEFAULT_AI_PROVIDER}' is not configured")
            print(f"  Will fallback to: {configured_providers[0]}")
        
        return True
    except Exception as e:
        print(f"✗ Error loading configuration: {e}")
        print("  Make sure .env file exists and is properly formatted")
        return False

def test_modules():
    """Test if project modules can be imported"""
    print("\n" + "=" * 50)
    print("Testing Project Modules...")
    print("=" * 50)
    
    modules = ['config', 'prompts', 'actions', 'interaction']
    failed = []
    
    for module in modules:
        try:
            __import__(module)
            print(f"✓ {module}.py: OK")
        except Exception as e:
            print(f"✗ {module}.py: FAILED - {e}")
            failed.append(module)
    
    if failed:
        print(f"\n✗ {len(failed)} module(s) failed to load")
        return False
    else:
        print("\n✓ All project modules loaded successfully!")
        return True

def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 48 + "╗")
    print("║" + " " * 10 + "AutoMoto AI Installation Test" + " " * 9 + "║")
    print("╚" + "=" * 48 + "╝")
    print("\n")
    
    results = []
    
    # Test imports
    results.append(test_imports())
    
    # Test configuration
    results.append(test_config())
    
    # Test project modules
    results.append(test_modules())
    
    # Final summary
    print("\n" + "=" * 50)
    print("FINAL SUMMARY")
    print("=" * 50)
    
    if all(results):
        print("\n✓✓✓ All tests passed! ✓✓✓")
        print("\nYou're ready to run AutoMoto AI!")
        print("Run: python main.py")
    else:
        print("\n✗ Some tests failed")
        print("\nPlease fix the issues above before running AutoMoto AI")
        print("Refer to setup_guide.txt for detailed instructions")
    
    print("\n")

if __name__ == "__main__":
    main()
