#!/usr/bin/env bash
# V23 acceptance on an isolated GitHub emulator runner ONLY.
# This script is NOT invoked by the desktop Studio.
set -euo pipefail

# Poll the accessibility hierarchy until the sample activity's label is visible.
# `am start -W` only proves the process launched. On API 35 the first
# uiautomator dump can still be the system UI, so a single read is not enough.
#
# Do not pipe `adb shell cat` into `grep -q`. adb ignores SIGPIPE and returns 1
# when the reader closes early. With `pipefail` that fails this script after a
# successful dump whenever the hierarchy is larger than the pipe buffer, even
# though V23_ANDROID_RUNNING is in the bytes already written. The green run and
# the following red runs on the same emulator build were that race. adb's exit
# status is not the assertion; the marker in the captured hierarchy is.
v23_wait_for_ui_marker() {
  local marker="V23_ANDROID_RUNNING"
  local remote="/sdcard/v23-window.xml"
  local attempts="${V23_UI_ATTEMPTS:-15}"
  local pause="${V23_UI_PAUSE_SECONDS:-2}"
  local work="${TMPDIR:-/tmp}/v23-ui-marker"
  local dest="$work/window.xml"
  local dump_log="$work/uiautomator.txt"
  local attempt=1
  local bytes=0
  local logcat="$work/logcat.txt"
  mkdir -p "$work"
  while (( attempt <= attempts )); do
    : >"$dump_log"
    adb shell uiautomator dump "$remote" >"$dump_log" 2>&1 || true
    : >"$dest"
    adb shell cat "$remote" >"$dest" 2>>"$dump_log" || true
    if [[ -s "$dest" ]]; then
      bytes=$(wc -c <"$dest" | tr -d '[:space:]')
    else
      bytes=0
    fi
    if [[ "$bytes" != 0 ]] && grep -F -q -- "$marker" "$dest"; then
      printf '%s\n' "V23_ANDROID_RUNNING visible in UI hierarchy (attempt ${attempt}, ${bytes} bytes)"
      return 0
    fi
    if (( attempt < attempts )); then
      printf '%s\n' "UI marker not visible yet (attempt ${attempt}/${attempts}, ${bytes} bytes); retrying" >&2
      sleep "$pause"
    fi
    attempt=$((attempt + 1))
  done
  printf '%s\n' "V23_ANDROID_RUNNING missing from UI hierarchy after ${attempts} dumps" >&2
  printf '%s\n' "last dump bytes=${bytes}" >&2
  if [[ -s "$dest" ]]; then
    if grep -F -q -- "com.automoto.v23" "$dest"; then
      printf '%s\n' "dump contains package com.automoto.v23 but not the visible marker" >&2
    else
      printf '%s\n' "dump does not contain package com.automoto.v23" >&2
    fi
    grep -o -E 'package="[^"]+"' "$dest" | sort -u | head -n 30 >&2 || true
    grep -o -E 'text="[^"]*"' "$dest" | head -n 30 >&2 || true
  else
    printf '%s\n' "no UI dump captured" >&2
  fi
  if [[ -s "$dump_log" ]]; then
    tail -n 20 "$dump_log" >&2 || true
  fi
  adb logcat -d -t 80 >"$logcat" 2>&1 || true
  if [[ -s "$logcat" ]]; then
    grep -E 'com\.automoto\.v23|AndroidRuntime|FATAL EXCEPTION' "$logcat" | head -n 40 >&2 || true
  fi
  return 1
}

main() {
  local project="tests/fixtures/v23-android"
  gradle -p "$project" --offline --no-daemon --console=plain :app:assembleDebug
  local apk="$project/app/build/outputs/apk/debug/app-debug.apk"
  test -s "$apk"
  adb wait-for-device
  adb install -r "$apk"
  local result try
  # A cold start can exceed am start -W's wait. Retry the launch; the
  # V23_ANDROID_RUNNING UI marker remains the actual acceptance check.
  result=""
  for try in 1 2 3 4 5 6; do
    result="$(adb shell am start -W -n com.automoto.v23/.MainActivity || true)"
    printf '%s\n' "$result"
    if grep -q "Status: ok" <<<"$result"; then
      break
    fi
    printf '%s\n' "am start attempt ${try} did not report Status: ok; retrying" >&2
    sleep 2
  done
  grep -q "Status: ok" <<<"$result"
  v23_wait_for_ui_marker
  printf '%s\n' "V23_ANDROID_EMULATOR_UI_PASS"
}

if [[ "${V23_EMULATOR_LIB_ONLY:-}" != 1 ]]; then
  main "$@"
fi
