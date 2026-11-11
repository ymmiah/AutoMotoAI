#!/usr/bin/env bash
# V25: CI-only Android emulator proof. Studio inspection/run never connects devices.
set -euo pipefail
apk="tests/fixtures/v25-flutter/build/app/outputs/flutter-apk/app-debug.apk"
test -s "$apk"
adb wait-for-device
adb install -r "$apk"
result="$(adb shell am start -W -n com.example.automoto_v25_flutter/.MainActivity)"
printf '%s\n' "$result"
grep -q "Status: ok" <<<"$result"
sleep 5
adb shell dumpsys activity activities | grep -F "com.example.automoto_v25_flutter" >/dev/null
adb shell screencap -p /sdcard/v25-flutter.png
adb pull /sdcard/v25-flutter.png "$RUNNER_TEMP/v25-flutter-emulator.png"
python3 - "$RUNNER_TEMP/v25-flutter-emulator.png" <<'PY'
from pathlib import Path
import sys, struct
p=Path(sys.argv[1])
data=p.read_bytes()
assert len(data)>9000, "Android emulator screenshot unexpectedly small"
assert data[:8]==b"\x89PNG\r\n\x1a\n", "Android emulator screenshot not PNG"
w,h=struct.unpack(">II", data[16:24])
assert w>=200 and h>=200, "Android screenshot dimensions invalid"
print("V25_FLUTTER_ANDROID_EMULATOR_INSTALL_LAUNCH_SCREENSHOT_PASS")
PY
