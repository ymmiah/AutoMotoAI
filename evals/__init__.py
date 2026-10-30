"""AutoMoto end-to-end scenario evaluation.

``python -m evals`` runs every scenario in ``scenarios.py`` through the real agent loop (planner, tool
subset, policy/approvals, sandbox, real tools, real sample files) with a scripted model, and checks the
results (files created and valid, content correct, risky steps asked for approval, unsafe ones refused).
``python -m evals --real`` sends the same requests to a real AI provider configured in .env.
"""
