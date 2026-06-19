# Security Policy

## 🔒 Security Overview

At AutoMoto AI, we take security seriously. This document outlines our security policies, procedures, and guidelines for reporting security vulnerabilities.

## 🚨 Reporting Security Vulnerabilities

If you discover a security vulnerability in AutoMoto AI, please help us by reporting it responsibly.

### 📧 How to Report

**Please DO NOT report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities by emailing:
- **Email**: ymmiah96@gmail.com
- **Subject**: `[SECURITY] Vulnerability Report - AutoMoto AI`

### 📋 What to Include

When reporting a security vulnerability, please include:

1. **Description**: A clear description of the vulnerability
2. **Impact**: What an attacker could achieve by exploiting this vulnerability
3. **Steps to Reproduce**: Detailed steps to reproduce the issue
4. **Proof of Concept**: If possible, include a proof of concept
5. **Environment**: Your system details (OS, Python version, etc.)
6. **Contact Information**: How we can reach you for follow-up

### ⏱️ Response Timeline

We will acknowledge your report within **48 hours** and provide a more detailed response within **7 days** indicating our next steps.

We will keep you informed about our progress throughout the process of fixing the vulnerability.

## 🔍 Security Considerations

### API Keys and Credentials

- **Never commit API keys** to version control
- Use environment variables for sensitive configuration
- Rotate API keys regularly
- Monitor API usage for unusual activity

### Desktop Automation Security

- **User confirmation required** for all automation actions
- **Fail-safe mechanisms** prevent runaway automation
- **Input validation** prevents malicious commands
- **Permission checks** ensure appropriate access levels

### Data Protection

- **No user data collection** without explicit consent
- **Local processing only** - AI requests stay on your machine
- **Secure storage** of configuration files
- **Clean uninstall** removes all user data

## 🛡️ Security Best Practices

### For Users

1. **Keep dependencies updated**:
   ```bash
   pip install --upgrade -r requirements.txt
   ```

2. **Use strong API keys** and rotate them regularly

3. **Monitor system activity** when using automation features

4. **Review confirmation dialogs** carefully before proceeding

5. **Keep your Python environment secure**

### For Developers

1. **Follow secure coding practices**:
   - Input validation and sanitization
   - Proper error handling
   - Secure API usage
   - No hardcoded secrets

2. **Code review requirements**:
   - All changes require review
   - Security-focused review checklist
   - Automated security scanning

3. **Dependency management**:
   - Regular dependency updates
   - Security vulnerability scanning
   - Minimal dependency footprint

## 🔧 Security Features

### Built-in Security Measures (v3.0+)

- **CSRF protection** — all mutating API endpoints require `X-Requested-With: XMLHttpRequest` header
- **Server-issued session tokens** — sessions are created server-side; clients cannot forge or hijack another user's history
- **Application launch allowlist** — only pre-approved executables can be launched via the web API; extend via `ALLOWED_APPS` env var
- **Process-kill PID guard** — PIDs below 100 (system/kernel processes) are rejected unconditionally
- **Output path sandboxing** — document write endpoints restrict output to `~/Documents/AutoMotoAI_Documents/`; caller-supplied paths outside this root are rejected
- **Input length limits** — chat messages (120 KB), document content (500 KB), paths (4096 bytes), batch size (20 files) are all bounded
- **Sanitised error messages** — internal file paths and stack traces are never returned to the client; all error strings are generic
- **Hardened HTTP response headers** — `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`
- **Safe integer parsing** — numeric query/body parameters are parsed with explicit type coercion and range clamping
- **Download path traversal protection** — `Path(filename).name` strips directory components before serving files
- **Debug mode disabled** — Flask debug/Werkzeug debugger is unconditionally off in `server.py`; never set `FLASK_DEBUG=true` in production
- **Confirmation dialogs** for all automation actions
- **Fail-safe hotkeys** (Ctrl+C or mouse to corner)
- **Local data storage** only

### Local-deployment security posture

AutoMoto AI's web server binds to `127.0.0.1` (loopback only) by default,
limiting network exposure to the local machine. This mitigates most remote
attack scenarios, but **does not eliminate** threats from:

- Other processes running on the same machine (SSRF, local scripts)
- Malicious web pages with localhost CSRF (mitigated by CSRF header check)
- Compromised browser extensions

If you expose the server on `0.0.0.0` or a public interface, **you must add
your own authentication layer** (reverse proxy with HTTP Basic Auth, VPN, etc.).

### AI Provider Security

| Provider | Security Features |
|----------|-------------------|
| **OpenAI** | Enterprise-grade security, SOC 2 compliant |
| **Google Gemini** | Google Cloud security standards |
| **Anthropic Claude** | Security-focused AI development |
| **BLACKBOX AI** | Developer-focused security practices |

## 🚩 Known Security Considerations

### Current Limitations

1. **Local Execution**: All automation runs locally with user permissions
2. **API Dependencies**: Relies on third-party AI services
3. **Windows Focus**: Currently Windows-only (by design)
4. **User Responsibility**: Users must review actions before confirmation

### Future Security Enhancements

- [ ] Encrypted configuration storage
- [ ] Two-factor authentication for sensitive operations
- [ ] Audit logging of all actions
- [ ] Sandboxed execution environment
- [ ] Automatic security updates

## 📞 Contact Information

- **Security Issues**: ymmiah96@gmail.com
- **General Support**: ymmiah96@gmail.com
- **GitHub Issues**: For non-security related issues

## 📜 Security Hall of Fame

We appreciate security researchers who help make AutoMoto AI safer. With your permission, we'll acknowledge your contribution in our security hall of fame.

## 📚 Additional Resources

- [OpenAI Security](https://openai.com/security/)
- [Google AI Security](https://ai.google/security/)
- [Anthropic Security](https://www.anthropic.com/security)
- [BLACKBOX AI Security](https://www.blackbox.ai/security)

---

**Last Updated**: June 19, 2026
**Version**: 3.0.0

