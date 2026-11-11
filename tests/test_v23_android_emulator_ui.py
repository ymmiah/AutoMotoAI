"""The emulator UI check must see V23_ANDROID_RUNNING, not adb's pipe status.

`adb shell cat … | grep -q` under `pipefail` exits 1 when a multi-line
hierarchy is larger than the pipe buffer: grep stops at the marker's line and
adb, which ignores SIGPIPE, returns 1. A dump that fits in the pipe still
exits 0, which is why the same script passed once and then failed three times
on emulator 37.2.13.0.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "scripts" / "v23_android_emulator.sh"
MARKER = "V23_ANDROID_RUNNING"
BAD_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hierarchy rotation="0"><node package="com.android.systemui" text="" /></hierarchy>\n'
)


def _xml(with_marker: bool, pad_nodes: int) -> str:
    """Multi-line hierarchy, matching `uiautomator dump` (one node per line)."""
    label = MARKER if with_marker else "systemui"
    package = "com.automoto.v23" if with_marker else "com.android.systemui"
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<hierarchy rotation="0">\n'
        f'<node package="{package}" text="{label}" content-desc="{label}"/>\n'
    )
    return head + ('<node text="pad"/>\n' * pad_nodes) + "</hierarchy>\n"


def _write_adb(bin_dir: Path, python: str) -> None:
    fake = bin_dir / "fake_adb.py"
    fake.write_text(
        textwrap.dedent(
            """\
            import os, signal, sys
            from pathlib import Path
            if hasattr(signal, "SIGPIPE"):
                signal.signal(signal.SIGPIPE, signal.SIG_IGN)
            device = Path(os.environ["V23_FAKE_DEVICE_XML"])
            counter = Path(os.environ["V23_FAKE_COUNTER"])
            good = Path(os.environ["V23_FAKE_GOOD_XML"])
            bad = Path(os.environ["V23_FAKE_BAD_XML"])
            miss = int(os.environ.get("V23_FAKE_MISS_DUMPS", "0"))
            args = sys.argv[1:]

            def silence():
                # Python flushes stdout again on the way out. Point it at
                # /dev/null so a reader that already exited cannot turn a
                # completed write into a second BrokenPipeError.
                null = os.open(os.devnull, os.O_WRONLY)
                os.dup2(null, 1)
                os.close(null)

            def stream():
                data = device.read_bytes()
                fd = sys.stdout.buffer
                off = 0
                while off < len(data):
                    try:
                        fd.write(data[off:off + 4096])
                        fd.flush()
                    except BrokenPipeError:
                        silence()
                        raise SystemExit(1)
                    off += 4096
                silence()

            if args[:3] == ["shell", "uiautomator", "dump"]:
                n = int(counter.read_text() or "0") if counter.exists() else 0
                n += 1
                counter.write_text(str(n))
                device.write_bytes((bad if n <= miss else good).read_bytes())
                print("UI hierchary dumped to: " + args[3])
                raise SystemExit(0)
            if args[:2] == ["shell", "cat"] and len(args) == 3:
                stream()
                raise SystemExit(0)
            if args[:2] == ["logcat", "-d"]:
                print("I/ActivityTaskManager: Displayed com.automoto.v23/.MainActivity")
                raise SystemExit(0)
            sys.stderr.write("unexpected adb args: %r\\n" % (args,))
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    launcher = bin_dir / "adb"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        f'exec "{python}" "{fake}" "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)


def _env(tmp: Path, good: str, miss: str, attempts: str, pause: str) -> dict[str, str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    _write_adb(bin_dir, sys.executable)
    (tmp / "good.xml").write_text(good, encoding="utf-8")
    (tmp / "bad.xml").write_text(BAD_XML, encoding="utf-8")
    (tmp / "device.xml").write_text(good, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
            "V23_FAKE_DEVICE_XML": str(tmp / "device.xml"),
            "V23_FAKE_COUNTER": str(tmp / "dumps.txt"),
            "V23_FAKE_GOOD_XML": str(tmp / "good.xml"),
            "V23_FAKE_BAD_XML": str(tmp / "bad.xml"),
            "V23_FAKE_MISS_DUMPS": miss,
            "V23_EMULATOR_LIB_ONLY": "1",
            "V23_UI_ATTEMPTS": attempts,
            "V23_UI_PAUSE_SECONDS": pause,
            "TMPDIR": str(tmp),
        }
    )
    return env


def _bash(tmp: Path, env: dict[str, str], body: str) -> subprocess.CompletedProcess[str]:
    bash = "bash"
    return subprocess.run(
        [bash, "-c", body],
        cwd=tmp,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


@pytest.fixture(autouse=True)
def _unix_only():
    if sys.platform == "win32":
        pytest.skip("pipe status regression is Unix-specific")
    if subprocess.run(["bash", "-c", "exit 0"], check=False).returncode != 0:
        pytest.skip("bash is required")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Ubuntu emulator grep stops at the marker line")
def test_large_hierarchy_pipe_is_a_false_failure_and_file_check_passes(tmp_path):
    good = _xml(with_marker=True, pad_nodes=8000)
    assert len(good.encode()) > 64 * 1024
    env = _env(tmp_path, good, miss="0", attempts="1", pause="0")
    piped = _bash(
        tmp_path,
        env,
        "set -o pipefail; adb shell cat /sdcard/v23-window.xml | grep -q V23_ANDROID_RUNNING",
    )
    assert piped.returncode == 1, (piped.returncode, piped.stdout, piped.stderr)
    checked = _bash(
        tmp_path,
        env,
        f'source "{SCRIPT}"; v23_wait_for_ui_marker',
    )
    assert checked.returncode == 0, (checked.returncode, checked.stdout, checked.stderr)
    assert "visible in UI hierarchy (attempt 1," in checked.stdout
    assert MARKER in checked.stdout
    assert int(checked.stdout.split("attempt 1, ", 1)[1].split(" bytes", 1)[0]) > 64 * 1024


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Ubuntu emulator grep stops at the marker line")
def test_small_hierarchy_pipe_can_pass(tmp_path):
    """A dump that fits in the pipe is why the same one-liner was green once."""
    good = _xml(with_marker=True, pad_nodes=10)
    assert len(good.encode()) < 4096
    env = _env(tmp_path, good, miss="0", attempts="1", pause="0")
    piped = _bash(
        tmp_path,
        env,
        "set -o pipefail; adb shell cat /sdcard/v23-window.xml | grep -q V23_ANDROID_RUNNING",
    )
    assert piped.returncode == 0, (piped.returncode, piped.stdout, piped.stderr)


def test_marker_absent_until_a_later_dump_still_required(tmp_path):
    good = _xml(with_marker=True, pad_nodes=20)
    env = _env(tmp_path, good, miss="2", attempts="5", pause="0")
    checked = _bash(tmp_path, env, f'source "{SCRIPT}"; v23_wait_for_ui_marker')
    assert checked.returncode == 0, (checked.returncode, checked.stdout, checked.stderr)
    assert "attempt 3," in checked.stdout
    assert "not visible yet (attempt 1/" in checked.stderr
    assert "not visible yet (attempt 2/" in checked.stderr


def test_missing_marker_fails_closed(tmp_path):
    good = _xml(with_marker=False, pad_nodes=20)
    env = _env(tmp_path, good, miss="0", attempts="2", pause="0")
    checked = _bash(
        tmp_path,
        env,
        f'source "{SCRIPT}"; set +e; v23_wait_for_ui_marker; printf "EXIT:%s\\n" "$?"',
    )
    assert "EXIT:1" in checked.stdout
    assert "V23_ANDROID_EMULATOR_UI_PASS" not in checked.stdout
    assert "missing from UI hierarchy after 2 dumps" in checked.stderr
    assert "does not contain package com.automoto.v23" in checked.stderr


def test_script_still_builds_installs_and_requires_the_marker():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "assembleDebug" in text
    assert "adb install -r" in text
    assert 'grep -q "Status: ok"' in text
    assert "V23_ANDROID_EMULATOR_UI_PASS" in text
    assert "V23_ANDROID_RUNNING" in text
    assert "cat /sdcard/v23-window.xml | grep" not in text
    assert "| grep -q V23_ANDROID_RUNNING" not in text
