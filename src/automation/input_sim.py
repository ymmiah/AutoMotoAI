"""Keyboard and mouse simulation via pyautogui."""
from __future__ import annotations

import logging

from src.core.exceptions import AutomationError

logger = logging.getLogger(__name__)


def _pg():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.3
        return pyautogui
    except ImportError as exc:
        raise AutomationError("pyautogui not installed. Run: pip install pyautogui") from exc


def type_text(text: str, interval: float = 0.03) -> None:
    try:
        _pg().write(text, interval=interval)
        logger.debug("Typed %d chars", len(text))
    except Exception as exc:
        raise AutomationError(f"type_text failed: {exc}") from exc


def press_key(key: str) -> None:
    try:
        _pg().press(key)
    except Exception as exc:
        raise AutomationError(f"press_key '{key}' failed: {exc}") from exc


def hotkey(*keys: str) -> None:
    try:
        _pg().hotkey(*keys)
    except Exception as exc:
        raise AutomationError(f"hotkey {keys} failed: {exc}") from exc


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    try:
        _pg().click(x, y, button=button, clicks=clicks)
    except Exception as exc:
        raise AutomationError(f"click({x},{y}) failed: {exc}") from exc


def move_to(x: int, y: int, duration: float = 0.2) -> None:
    try:
        _pg().moveTo(x, y, duration=duration)
    except Exception as exc:
        raise AutomationError(f"move_to({x},{y}) failed: {exc}") from exc
