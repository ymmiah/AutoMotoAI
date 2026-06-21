"""Voice I/O — Text-to-Speech and Speech-to-Text with multi-backend support."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_tts_lock = threading.Lock()
_tts_engine = None   # lazy pyttsx3 singleton


# ─────────────────────────── availability checks ──────────────────────────────

def _cmd_exists(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def is_tts_available() -> dict:
    """Return availability info for every TTS backend."""
    info: dict[str, bool] = {}
    info["pyttsx3"] = False
    try:
        import pyttsx3  # noqa: F401
        info["pyttsx3"] = True
    except ImportError:
        pass
    info["espeak"]   = _cmd_exists("espeak")
    info["festival"] = _cmd_exists("festival")
    info["flite"]    = _cmd_exists("flite")
    info["available"] = any(info.values())
    return info


def is_stt_available() -> dict:
    """Return availability info for STT backends."""
    info: dict[str, bool] = {}
    info["speech_recognition"] = False
    try:
        import speech_recognition  # noqa: F401
        info["speech_recognition"] = True
    except ImportError:
        pass
    info["pyaudio"] = False
    try:
        import pyaudio  # noqa: F401
        info["pyaudio"] = True
    except ImportError:
        pass
    info["whisper_local"] = False
    try:
        import whisper  # noqa: F401
        info["whisper_local"] = True
    except ImportError:
        pass
    info["microphone"] = info["speech_recognition"] and info["pyaudio"]
    info["file_transcription"] = info["speech_recognition"] or info["whisper_local"]
    info["available"] = info["microphone"] or info["file_transcription"]
    return info


# ─────────────────────────── TTS ──────────────────────────────────────────────

def _get_pyttsx3_engine():
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 0.9)
    _tts_engine = engine
    return engine


def speak(text: str, rate: int = 175, volume: float = 0.9) -> None:
    """Speak text aloud using the best available TTS engine (blocks until done)."""
    if not text.strip():
        return
    with _tts_lock:
        # pyttsx3 — cross-platform (uses espeak on Linux, SAPI on Windows, NSSpeechSynthesizer on Mac)
        try:
            engine = _get_pyttsx3_engine()
            engine.setProperty("rate", rate)
            engine.setProperty("volume", volume)
            engine.say(text)
            engine.runAndWait()
            return
        except Exception as exc:
            logger.debug("pyttsx3 speak failed: %s", exc)
            global _tts_engine
            _tts_engine = None  # reset in case engine got stuck

        # espeak subprocess fallback
        try:
            subprocess.run(
                ["espeak", "-s", str(rate), "-a", str(int(volume * 200)), text],
                timeout=60, check=False,
            )
            return
        except FileNotFoundError:
            pass

        # festival fallback
        try:
            proc = subprocess.Popen(["festival", "--tts"], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.communicate(input=text.encode(), timeout=60)
            return
        except FileNotFoundError:
            pass

        raise RuntimeError(
            "No TTS engine available. "
            "Install espeak (sudo apt install espeak) or run: pip install pyttsx3"
        )


def speak_to_file(text: str, output_path: str | Path, rate: int = 175) -> Path:
    """Synthesize speech and save to a WAV file. Returns the output path."""
    if not text.strip():
        raise ValueError("text is empty")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # espeak → WAV (most reliable file output on Linux)
    try:
        subprocess.run(
            ["espeak", "-s", str(rate), "-w", str(out), text],
            timeout=120, check=True, capture_output=True,
        )
        if out.exists():
            logger.info("TTS → %s via espeak", out)
            return out
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        logger.debug("espeak -w failed: %s", exc)

    # flite → WAV
    try:
        subprocess.run(
            ["flite", "-t", text, "-o", str(out)],
            timeout=120, check=True, capture_output=True,
        )
        if out.exists():
            logger.info("TTS → %s via flite", out)
            return out
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        logger.debug("flite failed: %s", exc)

    # pyttsx3 save_to_file
    try:
        with _tts_lock:
            engine = _get_pyttsx3_engine()
            engine.setProperty("rate", rate)
            engine.save_to_file(text, str(out))
            engine.runAndWait()
        if out.exists():
            logger.info("TTS → %s via pyttsx3", out)
            return out
    except Exception as exc:
        logger.debug("pyttsx3 save_to_file failed: %s", exc)

    raise RuntimeError(
        "Cannot synthesize speech to file. "
        "Install espeak: sudo apt install espeak  OR  flite: sudo apt install flite"
    )


def stop_speaking() -> None:
    """Stop any ongoing pyttsx3 speech."""
    with _tts_lock:
        try:
            engine = _get_pyttsx3_engine()
            engine.stop()
        except Exception:
            pass


# ─────────────────────────── STT — microphone ─────────────────────────────────

def listen(
    timeout: int = 10,
    phrase_timeout: int = 8,
    language: str = "en-US",
    energy_threshold: int = 300,
) -> str:
    """Record from the default microphone and return transcribed text."""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise RuntimeError(
            "SpeechRecognition not installed. Run: pip install SpeechRecognition"
        ) from exc
    try:
        import pyaudio  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio not installed (required for microphone).\n"
            "  pip install pyaudio\n"
            "  Linux: sudo apt install python3-pyaudio portaudio19-dev"
        ) from exc

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = energy_threshold
    recognizer.dynamic_energy_threshold = True

    with sr.Microphone() as source:
        logger.info("Calibrating for ambient noise (1 s)…")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        logger.info("Listening… (timeout=%ds)", timeout)
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout)
        except sr.WaitTimeoutError as exc:
            raise RuntimeError("No speech detected within the timeout period.") from exc

    try:
        text = recognizer.recognize_google(audio, language=language)
        logger.info("Recognized: %s", text)
        return text
    except sr.UnknownValueError as exc:
        raise RuntimeError("Could not understand audio — please speak more clearly.") from exc
    except sr.RequestError as exc:
        raise RuntimeError(f"Google Speech Recognition error: {exc}") from exc


# ─────────────────────────── STT — file transcription ─────────────────────────

def transcribe_file(audio_path: str | Path, language: str = "en") -> str:
    """Transcribe an audio file. Tries OpenAI Whisper API, local whisper, then SpeechRecognition."""
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    # OpenAI Whisper API (best quality when key available)
    try:
        from src.core.config import ai_config
        if ai_config.openai_api_key:
            import openai
            client = openai.OpenAI(api_key=ai_config.openai_api_key)
            with open(p, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=language,
                )
            logger.info("Transcribed via OpenAI Whisper API")
            return result.text
    except Exception as exc:
        logger.debug("OpenAI Whisper API failed: %s", exc)

    # Local whisper model
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(str(p), language=language)
        logger.info("Transcribed via local whisper")
        return result["text"]
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Local whisper failed: %s", exc)

    # SpeechRecognition audio file reader
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(p)) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language=language)
        logger.info("Transcribed via Google STT")
        return text
    except ImportError as exc:
        raise RuntimeError(
            "No transcription backend available. "
            "Set OPENAI_API_KEY, install openai-whisper, or install SpeechRecognition."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Transcription failed: {exc}") from exc


# ─────────────────────────── audio dir helper ─────────────────────────────────

def _audio_dir() -> Path:
    d = Path.home() / "Documents" / "AutoMotoAI_Documents" / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_audio_dir() -> Path:
    return _audio_dir()
