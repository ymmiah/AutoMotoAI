"""Install / run helpers: .env discovery, the port-in-use message, `automoto open --print`, 7-Zip on Windows."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _env_probe(cwd: Path, data: Path, extra: dict[str, str] | None = None) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AM_TEST_", "AUTOMOTO_"))}
    env.update({"AUTOMOTO_DATA_DIR": str(data), "PYTHONPATH": str(ROOT)})
    env.update(extra or {})
    code = ("import os; from automoto import config; "
            "print(os.environ.get('AM_TEST_A')); print(os.environ.get('AM_TEST_B')); print(os.environ.get('AM_TEST_C'))")
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_env_files_order(tmp_path):
    work, data = tmp_path / "work", tmp_path / "data"
    work.mkdir(), data.mkdir()
    (work / ".env").write_text("AM_TEST_A=from-cwd\nAM_TEST_B=from-cwd\n", encoding="utf-8")
    (data / ".env").write_text("AM_TEST_B=from-data\nAM_TEST_C=from-data\n", encoding="utf-8")
    # cwd .env wins over the data-folder .env; the data-folder .env fills in the rest
    assert _env_probe(work, data) == ["from-cwd", "from-cwd", "from-data"]
    # a real environment variable beats both files
    assert _env_probe(work, data, {"AM_TEST_C": "from-env"})[2] == "from-env"


def test_data_dir_env_alone(tmp_path):
    # pip / pipx installs: no .env next to the code, only ~/.automoto/.env
    data, work = tmp_path / "d", tmp_path / "w"
    data.mkdir(), work.mkdir()
    (data / ".env").write_text("AM_TEST_A=only-data\n", encoding="utf-8")
    assert _env_probe(work, data)[0] == "only-data"


def test_port_in_use_message():
    from automoto import server
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        with pytest.raises(SystemExit) as e:
            server.check_port("127.0.0.1", port)
        assert "already in use" in str(e.value) and f"--port {port + 1}" in str(e.value)
    finally:
        s.close()
    server.check_port("127.0.0.1", port)  # free again: no error


def test_open_print_without_server(capsys):
    from automoto import cli
    assert cli.main(["open", "--print"]) == 1
    assert "No running AutoMoto server" in capsys.readouterr().out


def test_seven_zip_found_in_program_files_on_windows(monkeypatch, tmp_path):
    from automoto import archives
    exe = tmp_path / "7-Zip" / "7z.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(archives.shutil, "which", lambda name: None)
    monkeypatch.setattr(archives.os, "name", "nt")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert archives._seven_cli() == os.path.join(str(tmp_path), "7-Zip", "7z.exe")


def test_install_scripts_pin_the_release_checksum():
    sh = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    ps = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    pin = "755bc31b8f8b6f1ed5330c5356b05e9509f94f0eafc3b6e9aa7eab443f223107"  # automoto_ai-5.5.0 wheel
    assert pin in sh and pin in ps
    for text in (sh, ps):  # never pipe downloads into a shell
        assert "| bash" not in text and "| sh" not in text and "iex" not in text.lower().replace("index", "")
