#!/usr/bin/env bash
# AutoMoto AI installer for Linux, macOS, ChromeOS (Linux) and Raspberry Pi.
#
#   ./scripts/install.sh                     # release wheel (SHA-256 checked) into its own virtualenv
#   ./scripts/install.sh --from-source       # this checkout instead (developers, newest code)
#   ./scripts/install.sh --system-deps       # also install LibreOffice, poppler, 7-Zip, PHP (asks first, uses sudo)
#   ./scripts/install.sh --service           # also start AutoMoto when you log in (systemd user service / launchd)
#   ./scripts/install.sh --uninstall         # remove the program (keeps your data in ~/.automoto)
#
# Safe by design: nothing is piped into a shell, the release wheel is checked against a pinned SHA-256,
# nothing runs as root except the optional --system-deps package install (shown and confirmed first),
# and your keys go into ~/.automoto/.env (mode 600), never into this folder.
set -euo pipefail

VERSION="5.5.0"
REPO="ymmiah/AutoMotoAI"
# pinned checksums of the wheels attached to the GitHub releases
sha_for() {
  case "$1" in
    5.5.0) echo "755bc31b8f8b6f1ed5330c5356b05e9509f94f0eafc3b6e9aa7eab443f223107" ;;
    5.6.0b1) echo "0c9529605b3d18e9739f408da745074a48dd77408fdc4526e241938955a13b22" ;;  # beta (tag v5.6.0-beta.1)
    5.6.0b2) echo "f4c1ab42003f2cf8964dfec783e005fa847a38831d5f22385b119d27922f68c5" ;;  # beta (tag v5.6.0-beta.2)
    5.6.0b3) echo "48dbf3a3f08c95781221fef287b8377f80a7caecba79e9b07a15a04a6f488216" ;;  # beta (tag v5.6.0-beta.3)
    *) echo "" ;;
  esac
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${AUTOMOTO_DATA_DIR:-$HOME/.automoto}"
VENV="${AUTOMOTO_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/automoto-ai/venv}"
BIN_DIR="${AUTOMOTO_BIN_DIR:-$HOME/.local/bin}"
SOURCE="release"   # release | source | git
SRC_DIR="$REPO_DIR"
GIT_REF="main"
EXTRAS="office"
SHA=""
WHEEL=""
SYSTEM_DEPS=0
SERVICE=0
YES=0
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/automoto.service"
PLIST="$HOME/Library/LaunchAgents/com.ymmiah.automoto.plist"
ACTION="install"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  cat <<USAGE

Options:
  --version X        release to install (default $VERSION)
  --sha256 HASH      checksum for a release that isn't pinned in this script
  --wheel FILE       install a wheel you already downloaded (checked against the pinned SHA-256 or --sha256)
  --from-source [D]  install from a source checkout (default: this repo, $REPO_DIR)
  --from-git REF     install from GitHub at a tag/branch (needs git), e.g. --from-git main
  --extras LIST      optional Python extras: office (pandas, default), data (Parquet/7z/TOML), desktop (pyautogui); "" for none
  --full             same as --extras office,data
  --system-deps      install LibreOffice, poppler, 7-Zip and PHP with your package manager (sudo, asks first)
  --venv DIR         virtualenv location (default $VENV)
  --bin-dir DIR      where the \`automoto\` command goes (default $BIN_DIR)
  --service          start AutoMoto automatically at login (Linux: systemd user service, macOS: launchd agent)
  --yes              don't ask before --system-deps / --uninstall --purge
  --uninstall        remove the virtualenv and the command (keeps $DATA_DIR)
  --purge            with --uninstall: also delete $DATA_DIR (chats, memory, files, keys)
USAGE
}

PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:?}"; shift 2 ;;
    --sha256) SHA="${2:?}"; shift 2 ;;
    --wheel) WHEEL="${2:?}"; shift 2 ;;
    --from-source) SOURCE="source"; if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then SRC_DIR="$2"; shift; fi; shift ;;
    --from-git) SOURCE="git"; GIT_REF="${2:?}"; shift 2 ;;
    --extras) EXTRAS="${2-}"; shift 2 ;;
    --full) EXTRAS="office,data"; shift ;;
    --system-deps) SYSTEM_DEPS=1; shift ;;
    --service) SERVICE=1; shift ;;
    --venv) VENV="${2:?}"; shift 2 ;;
    --bin-dir) BIN_DIR="${2:?}"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --purge) PURGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

confirm() {  # confirm "question" -> 0 if yes
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || { warn "not a terminal - pass --yes to agree"; return 1; }
  printf '%s [y/N] ' "$1"; read -r ans; case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

have_user_systemd() { command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; }

remove_service() {
  if [ -f "$UNIT" ]; then
    have_user_systemd && systemctl --user disable --now automoto.service >/dev/null 2>&1 || true
    rm -f "$UNIT"; have_user_systemd && systemctl --user daemon-reload || true
    say "Removed the systemd user service"
  fi
  if [ -f "$PLIST" ]; then
    launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
    rm -f "$PLIST"; say "Removed the launchd agent"
  fi
}

if [ "$ACTION" = "uninstall" ]; then
  remove_service
  say "Removing $VENV and $BIN_DIR/automoto"
  rm -rf "$VENV"; rm -f "$BIN_DIR/automoto"
  if [ "$PURGE" = 1 ]; then
    if confirm "Also delete $DATA_DIR (chats, memory, workspace files, keys)?"; then rm -rf "$DATA_DIR"; say "Deleted $DATA_DIR"; fi
  else
    say "Kept your data in $DATA_DIR (delete it yourself, or run with --uninstall --purge)"
  fi
  exit 0
fi

# ---- 1. Python 3.10+ -------------------------------------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  warn "Python 3.10 or newer is needed. Install it, then run this again:"
  case "$(uname -s)" in
    Darwin) echo "  brew install python@3.12      (Homebrew: https://brew.sh)" ;;
    *) echo "  Ubuntu/Debian: sudo apt install python3 python3-venv   Fedora: sudo dnf install python3   Arch: sudo pacman -S python" ;;
  esac
  exit 1
fi
say "Using $("$PY" -V 2>&1) at $PY"

# ---- 2. optional system tools (LibreOffice, poppler, 7-Zip, PHP) -----------------------------------
if [ "$SYSTEM_DEPS" = 1 ]; then
  CMD=""
  if [ "$(uname -s)" = "Darwin" ]; then
    command -v brew >/dev/null 2>&1 || die "Homebrew not found - install it from https://brew.sh first"
    CMD="brew install poppler sevenzip php && brew install --cask libreoffice"
  elif command -v apt-get >/dev/null 2>&1; then
    CMD="sudo apt-get update && sudo apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils 7zip php-cli"
  elif command -v dnf >/dev/null 2>&1; then
    CMD="sudo dnf install -y libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils 7zip php-cli"
  elif command -v pacman >/dev/null 2>&1; then
    CMD="sudo pacman -S --needed --noconfirm libreoffice-fresh poppler 7zip php"
  fi
  if [ -z "$CMD" ]; then
    warn "Unknown package manager - install LibreOffice, poppler (pdftotext), 7-Zip and PHP yourself (all optional)."
  else
    echo "  $CMD"
    if confirm "Run this to install the optional Office/PDF/archive/PHP tools?"; then sh -c "$CMD"; else warn "Skipped system tools."; fi
  fi
fi

# ---- 3. virtualenv ---------------------------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating a private virtualenv in $VENV"
  mkdir -p "$(dirname "$VENV")"
  if ! "$PY" -m venv "$VENV" 2>/tmp/automoto-venv.err; then
    cat /tmp/automoto-venv.err >&2
    die "Couldn't create a virtualenv. On Ubuntu/Debian run: sudo apt install python3-venv"
  fi
fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --quiet --upgrade pip

# ---- 4. get and install AutoMoto -------------------------------------------------------------------
EXTRA_SPEC=""
[ -n "$EXTRAS" ] && EXTRA_SPEC="[$EXTRAS]"
case "$SOURCE" in
  release)
    [ -n "$SHA" ] || SHA="$(sha_for "$VERSION")"
    [ -n "$SHA" ] || die "No pinned checksum for $VERSION - pass --sha256 <hash from the release page> or use --from-source"
    NAME="automoto_ai-$VERSION-py3-none-any.whl"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    if [ -n "$WHEEL" ]; then
      cp "$WHEEL" "$TMP/$NAME"
    else
      # beta wheels (5.6.0b1) live under the tag v5.6.0-beta.1
      TAG="v$(printf %s "$VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+)b([0-9]+)$/\1-beta.\2/')"
      URL="https://github.com/$REPO/releases/download/$TAG/$NAME"
      say "Downloading $URL"
      "$VPY" - "$URL" "$TMP/$NAME" <<'PYDL'
import sys, urllib.request
url, out = sys.argv[1], sys.argv[2]
if not url.startswith("https://github.com/"):
    raise SystemExit("refusing a non-GitHub URL")
with urllib.request.urlopen(url, timeout=120) as r, open(out, "wb") as f:  # nosec - fixed https URL
    f.write(r.read())
PYDL
    fi
    GOT="$("$VPY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$TMP/$NAME")"
    [ "$GOT" = "$SHA" ] || die "Checksum mismatch for $NAME (got $GOT, expected $SHA) - not installing"
    say "SHA-256 verified: $GOT"
    "$VPY" -m pip install --quiet --upgrade "$TMP/$NAME$EXTRA_SPEC"
    ;;
  source)
    [ -f "$SRC_DIR/pyproject.toml" ] || die "$SRC_DIR is not an AutoMoto source folder (no pyproject.toml)"
    say "Installing from source: $SRC_DIR"
    "$VPY" -m pip install --quiet --upgrade "$SRC_DIR$EXTRA_SPEC"
    ;;
  git)
    command -v git >/dev/null 2>&1 || die "git is needed for --from-git"
    say "Installing from https://github.com/$REPO @ $GIT_REF"
    "$VPY" -m pip install --quiet --upgrade "automoto-ai$EXTRA_SPEC @ git+https://github.com/$REPO.git@$GIT_REF"
    ;;
esac

# ---- 5. the `automoto` command (reads ~/.automoto/.env) -------------------------------------------
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/automoto" <<WRAP
#!/bin/sh
# AutoMoto AI launcher made by scripts/install.sh - loads keys from \$AUTOMOTO_DATA_DIR/.env (default ~/.automoto/.env)
exec "$VPY" -c 'import os, sys
sys.path[:] = [p for p in sys.path if p not in ("", ".")]  # never pick up an automoto/ folder in the current directory
from dotenv import load_dotenv
d = os.environ.get("AUTOMOTO_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".automoto")
load_dotenv(os.path.join(os.path.expanduser(d), ".env"), override=False)
sys.argv[0] = "automoto"
from automoto.cli import main
sys.exit(main())' "\$@"
WRAP
chmod 755 "$BIN_DIR/automoto"

# ---- 6. settings file for keys -----------------------------------------------------------------------
mkdir -p "$DATA_DIR"; chmod 700 "$DATA_DIR" 2>/dev/null || true
if [ ! -f "$DATA_DIR/.env" ]; then
  umask 077
  cat > "$DATA_DIR/.env" <<'ENV'
# AutoMoto AI settings. Add at least ONE key (free: NVIDIA NIM at https://build.nvidia.com,
# Gemini at https://aistudio.google.com/apikey, Groq at https://console.groq.com/keys,
# OpenRouter at https://openrouter.ai/keys). Environment variables override this file.
NVIDIA_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
# Slow answers / timeouts? Raise this (seconds):
AI_TIMEOUT=120
ENV
  say "Created $DATA_DIR/.env (only you can read it) - put your key(s) there"
else
  say "Kept your existing $DATA_DIR/.env"
fi

# ---- 7. check ------------------------------------------------------------------------------------------
"$BIN_DIR/automoto" --version

# ---- 8. optional: start at login ----------------------------------------------------------------------
if [ "$SERVICE" = 1 ]; then
  SVC_PATH="$BIN_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  if [ "$(uname -s)" = "Darwin" ]; then
    mkdir -p "$(dirname "$PLIST")"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ymmiah.automoto</string>
  <key>ProgramArguments</key>
  <array><string>$BIN_DIR/automoto</string><string>serve</string><string>--no-browser</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$SVC_PATH</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$DATA_DIR/automoto.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/automoto.log</string>
</dict>
</plist>
PL
    launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
    if launchctl bootstrap "gui/$(id -u)" "$PLIST"; then
      say "AutoMoto now starts when you log in (launchd agent $PLIST). Open it with: automoto open"
    else
      warn "Couldn't load the launchd agent; it will load at your next login ($PLIST)"
    fi
  else
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<UN
[Unit]
Description=AutoMoto AI (local web app on http://127.0.0.1:8765)
After=network-online.target

[Service]
ExecStart=$BIN_DIR/automoto serve --no-browser
Environment=PATH=$SVC_PATH
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UN
    if have_user_systemd; then
      systemctl --user daemon-reload
      systemctl --user enable --now automoto.service
      say "AutoMoto now runs as a systemd user service. Open it with: automoto open   (logs: journalctl --user -u automoto)"
      say "To keep it running after you log out / at boot: sudo loginctl enable-linger $USER"
    else
      warn "No systemd user session here (containers, WSL without systemd, ChromeOS). Wrote $UNIT anyway;"
      warn "start AutoMoto yourself with: automoto serve"
    fi
  fi
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) RUN="automoto" ;;
  *) RUN="$BIN_DIR/automoto"
     warn "$BIN_DIR is not on your PATH. Add it:  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.$(basename "${SHELL:-bash}")rc  (then open a new terminal)" ;;
esac
cat <<DONE

Done. Next:
  1. Edit $DATA_DIR/.env and paste a key (e.g. NVIDIA_API_KEY=nvapi-...)
  2. $RUN status          # shows which AIs are ready
  3. $RUN serve           # opens the web app in your browser (http://127.0.0.1:8765)
Guide: https://github.com/$REPO/blob/main/docs/INSTALL.md
DONE
