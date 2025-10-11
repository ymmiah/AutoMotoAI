# 🤖 AI Providers Guide - AutoMoto AI

AutoMoto AI now supports **three AI providers**: OpenAI, Google Gemini, and Anthropic Claude. You can use any one or all three!

---

## 🎯 Supported AI Providers

| Provider | Model | Strengths | API Cost |
|----------|-------|-----------|----------|
| **OpenAI** | GPT-4 | Most capable, best reasoning | ~$0.03/1K tokens |
| **Google Gemini** | Gemini Pro | Fast, free tier available | Free tier available |
| **Anthropic Claude** | Claude 3 Sonnet | Balanced performance | ~$0.003/1K tokens |

---

## 🚀 Quick Setup

### Step 1: Get API Keys

Choose one or more providers and get their API keys:

**OpenAI (GPT-4)**
- Visit: https://platform.openai.com/api-keys
- Sign up/login
- Create new API key
- Copy the key (starts with `sk-`)

**Google Gemini**
- Visit: https://makersuite.google.com/app/apikey
- Sign in with Google account
- Create API key
- Copy the key

**Anthropic Claude**
- Visit: https://console.anthropic.com/
- Sign up/login
- Go to API Keys section
- Create new key
- Copy the key (starts with `sk-ant-`)

### Step 2: Configure .env File

1. Rename `.env.example` to `.env`
2. Open `.env` in a text editor
3. Add your API key(s):

```env
# Add at least one API key
OPENAI_API_KEY=sk-your-openai-key-here
GEMINI_API_KEY=your-gemini-key-here
ANTHROPIC_API_KEY=sk-ant-your-claude-key-here

# Set your preferred provider
DEFAULT_AI_PROVIDER=openai
```

### Step 3: Choose Default Provider

Set `DEFAULT_AI_PROVIDER` to one of:
- `openai` - Use OpenAI GPT-4
- `gemini` - Use Google Gemini Pro
- `claude` - Use Anthropic Claude 3

---

## 💡 Usage Examples

### Using Default Provider

The app will automatically use your configured default provider:

```python
# In .env file
DEFAULT_AI_PROVIDER=gemini

# App will use Gemini for all AI tasks
```

### Automatic Fallback

If your default provider is not configured, the app automatically falls back to any available provider:

```
Default provider: openai (not configured)
→ Falling back to: gemini ✓
```

---

## 🔄 Switching Between Providers

### Method 1: Change .env File

Edit `.env` and change `DEFAULT_AI_PROVIDER`:

```env
# Before
DEFAULT_AI_PROVIDER=openai

# After
DEFAULT_AI_PROVIDER=gemini
```

Then restart the application.

### Method 2: Configure Multiple Keys

Add all three API keys to use any provider:

```env
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_AI_PROVIDER=openai
```

The app will use OpenAI by default, but can fallback to others if needed.

---

## 📊 Provider Comparison

### OpenAI GPT-4
✅ **Pros:**
- Most advanced reasoning
- Best for complex tasks
- Excellent code understanding
- Reliable and consistent

❌ **Cons:**
- Most expensive
- Requires paid account
- Rate limits on free tier

**Best for:** Complex automation, detailed analysis, production use

### Google Gemini Pro
✅ **Pros:**
- Free tier available
- Fast response times
- Good general performance
- Multimodal capabilities

❌ **Cons:**
- Less advanced than GPT-4
- Newer, less tested
- Some regional restrictions

**Best for:** Testing, development, cost-conscious users

### Anthropic Claude 3
✅ **Pros:**
- Excellent value for money
- Strong reasoning abilities
- Good safety features
- Longer context window

❌ **Cons:**
- Requires separate account
- Less widely adopted
- API access may vary

**Best for:** Balanced performance and cost, safety-critical tasks

---

## 🔧 Configuration Details

### Model Selection

Each provider uses a specific model (configured in `config.py`):

```python
AI_MODELS = {
    "openai": "gpt-4",
    "gemini": "gemini-pro",
    "claude": "claude-3-sonnet-20240229"
}
```

### Generation Parameters

All providers use consistent parameters:

```python
AI_TEMPERATURE = 0.3  # Lower = more deterministic
AI_MAX_TOKENS = 500   # Response length limit
```

---

## 🐛 Troubleshooting

### "No AI provider configured"

**Problem:** No API keys are set in `.env` file

**Solution:**
1. Check `.env` file exists (not `.env.example`)
2. Add at least one API key
3. Restart the application

### "OpenAI Error: Invalid API key"

**Problem:** API key is incorrect or expired

**Solution:**
1. Verify key is correct (no extra spaces)
2. Check key is active on provider's website
3. Generate new key if needed

### "Falling back to [provider]"

**Info:** This is normal behavior when default provider is unavailable

**Action:** No action needed, or configure your preferred provider

### Rate Limit Errors

**Problem:** Too many requests to AI provider

**Solution:**
1. Wait a few minutes
2. Switch to different provider
3. Upgrade to paid tier if needed

---

## 💰 Cost Comparison

### Example: 1000 Tasks

Assuming average 500 tokens per task:

| Provider | Cost per Task | Total Cost |
|----------|---------------|------------|
| OpenAI GPT-4 | $0.015 | $15.00 |
| Gemini Pro | $0.000 (free tier) | $0.00 |
| Claude 3 Sonnet | $0.0015 | $1.50 |

**Note:** Costs are approximate and vary based on actual usage.

---

## 🔒 Security Best Practices

### Protecting API Keys

✅ **DO:**
- Store keys in `.env` file only
- Add `.env` to `.gitignore`
- Never commit keys to version control
- Rotate keys periodically
- Use separate keys for development/production

❌ **DON'T:**
- Share keys publicly
- Hardcode keys in source code
- Use same key across multiple projects
- Commit `.env` file to Git

### Key Rotation

To rotate an API key:
1. Generate new key on provider's website
2. Update `.env` file with new key
3. Restart application
4. Delete old key from provider's website

---

## 📈 Performance Tips

### Optimize Response Time

1. **Use Gemini for speed** - Fastest response times
2. **Cache common responses** - Reduce API calls
3. **Batch similar tasks** - More efficient processing

### Reduce Costs

1. **Use Gemini free tier** - For development/testing
2. **Lower max_tokens** - Shorter responses = lower cost
3. **Implement local parsing** - For simple commands

### Improve Accuracy

1. **Use GPT-4** - Best reasoning and understanding
2. **Adjust temperature** - Lower for consistency
3. **Refine system prompt** - Better task understanding

---

## 🔄 Migration Guide

### From OpenAI-only to Multi-Provider

**Before (v1.0.0):**
```env
OPENAI_API_KEY=sk-...
```

**After (v2.0.0):**
```env
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_AI_PROVIDER=openai
```

No code changes needed! The app automatically detects and uses available providers.

---

## 🆘 Getting Help

### Check Configuration
```bash
python test_installation.py
```

This will show:
- Which providers are configured
- Which provider will be used
- Any configuration warnings

### Test Specific Provider

Edit `.env` to test each provider:
```env
DEFAULT_AI_PROVIDER=gemini  # Test Gemini
DEFAULT_AI_PROVIDER=claude  # Test Claude
DEFAULT_AI_PROVIDER=openai  # Test OpenAI
```

---

## 📚 Additional Resources

### API Documentation
- **OpenAI:** https://platform.openai.com/docs
- **Gemini:** https://ai.google.dev/docs
- **Claude:** https://docs.anthropic.com/

### Pricing Information
- **OpenAI:** https://openai.com/pricing
- **Gemini:** https://ai.google.dev/pricing
- **Claude:** https://www.anthropic.com/pricing

### Community Support
- Check GitHub issues
- Read DOCUMENTATION.md
- Review code comments

---

## ✨ Future Enhancements

Planned features for AI providers:

- [ ] Dynamic provider switching during runtime
- [ ] Provider-specific optimizations
- [ ] Cost tracking and analytics
- [ ] Custom model selection
- [ ] Local LLM support (Ollama, LM Studio)
- [ ] Multi-provider consensus mode

---

**Version:** 2.0.0  
**Last Updated:** 2024  
**Status:** Production Ready ✅
