#!/usr/bin/env bash
# V24: ONLY called by a dedicated GitHub macOS runner after unsigned Xcode build.
# No device or simulator commands are executed by Developer Studio itself.
set -euo pipefail
: "${V24_APP:?Expected unsigned iOS app location}"
: "${V24_SCREENSHOT:?Expected screenshot location}"
test -d "$V24_APP"
xcrun simctl list devices available -j > "$RUNNER_TEMP/v24-simulator-devices.json"
uuid="$(python3 - "$RUNNER_TEMP/v24-simulator-devices.json" <<'PY'
import json, sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
phones=[device for devices in data.get("devices",{}).values()
        for device in devices if device.get("isAvailable",True)
        and device.get("name","").startswith("iPhone")
        and device.get("udid")]
if not phones:
    raise SystemExit("NO_INSTALLED_IOS_SIMULATOR: Cannot claim real simulator validation.")
print(phones[0]["udid"])
PY
)"
echo "Selected installed iOS Simulator: $uuid"
cleanup() {
  xcrun simctl shutdown "$uuid" >/dev/null 2>&1 || true
}
trap cleanup EXIT
xcrun simctl boot "$uuid"
xcrun simctl bootstatus "$uuid" -b
xcrun simctl install "$uuid" "$V24_APP"
installed="$(xcrun simctl get_app_container "$uuid" org.automoto.v24fixture app)"
test -d "$installed"
result=""
for try in 1 2 3 4 5 6; do
  result="$(xcrun simctl launch "$uuid" org.automoto.v24fixture || true)"
  printf '%s\n' "$result"
  if grep -q 'org.automoto.v24fixture:' <<<"$result"; then
    break
  fi
  printf '%s\n' "simctl launch attempt ${try} did not report the app pid; retrying" >&2
  sleep 2
done
grep -q 'org.automoto.v24fixture:' <<<"$result"
sleep 3
xcrun simctl io "$uuid" screenshot "$V24_SCREENSHOT"
python3 - "$V24_SCREENSHOT" <<'PY'
from pathlib import Path
import sys
from PIL import Image
path=Path(sys.argv[1])
assert path.is_file() and path.stat().st_size > 8000, "Simulator screenshot missing or empty"
with Image.open(path) as im:
    im.verify()
print("V24_IOS_SIMULATOR_BUILD_INSTALL_LAUNCH_SCREENSHOT_PASS")
PY
