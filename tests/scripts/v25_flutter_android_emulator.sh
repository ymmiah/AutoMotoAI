#!/usr/bin/env bash
# V25: CI-only Android emulator proof. Studio inspection/run never connects devices.
set -euo pipefail
apk="tests/fixtures/v25-flutter/build/app/outputs/flutter-apk/app-debug.apk"
test -s "$apk"
adb wait-for-device
adb install -r "$apk"
pkg="com.example.automoto_v25_flutter"
# A cold Flutter start on a software-rendered CI emulator can exceed am start -W's
# internal wait and report "Status: timeout" even though the app is launching.
# Accept "Status: ok" immediately; otherwise poll until the activity is resumed.
result="$(adb shell am start -W -n "$pkg/.MainActivity" || true)"
printf '%s\n' "$result"
launched=0
for attempt in $(seq 1 36); do
  if grep -q "Status: ok" <<<"$result"; then launched=1; break; fi
  pid="$(adb shell pidof "$pkg" 2>/dev/null | tr -d '\r' || true)"
  adb shell dumpsys activity activities > "${RUNNER_TEMP:-/tmp}/v25-activities.txt" 2>/dev/null || true
  if [ -n "$pid" ] && grep -E "(mResumedActivity|topResumedActivity|ResumedActivity).*$pkg" "${RUNNER_TEMP:-/tmp}/v25-activities.txt" >/dev/null; then
    echo "V25 activity resumed (pid $pid) after poll $attempt"
    launched=1; break
  fi
  if [ "$attempt" -eq 12 ] || [ "$attempt" -eq 24 ]; then
    result="$(adb shell am start -W -n "$pkg/.MainActivity" || true)"
    printf '%s\n' "$result"
  fi
  sleep 5
done
if [ "$launched" -ne 1 ]; then
  echo "V25 Flutter activity never reached resumed state" >&2
  tail -n 60 "${RUNNER_TEMP:-/tmp}/v25-activities.txt" >&2 || true
  exit 1
fi
sleep 5
adb shell dumpsys activity activities > "${RUNNER_TEMP:-/tmp}/v25-activities.txt"
grep -F "$pkg" "${RUNNER_TEMP:-/tmp}/v25-activities.txt" >/dev/null
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
