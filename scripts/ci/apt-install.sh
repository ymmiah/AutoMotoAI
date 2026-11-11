#!/usr/bin/env bash
# Install apt packages on GitHub-hosted Ubuntu when archive DNS or mirrors are flaky.
#
# ubuntu-latest (26.04) points apt at /etc/apt/apt-mirrors.txt, whose only hosts are
# azure.archive.ubuntu.com, archive.ubuntu.com, and security.ubuntu.com. When those
# names fail to resolve, apt still walks every .deb through each mirror and burns
# about 20s per lookup, then exits 100 after tens of minutes. Other HTTPS hosts on
# the same runner keep working, so this script:
#   1. fails a dead lookup in a few seconds instead of hanging
#   2. resolves a mirror with DNS-over-HTTPS when system DNS cannot
#   3. installs from one signed mirror that actually serves this release, its
#      updates, and its security pocket
#   4. tries a non-ubuntu.com mirror if the official archives are unreachable
#
# Packages are still installed for real and checked with dpkg. Signatures stay on.
set -euo pipefail

APT_MIRRORS_FILE="${AUTOMOTO_APT_MIRRORS_FILE:-/etc/apt/apt-mirrors.txt}"
HOSTS_FILE="${AUTOMOTO_APT_HOSTS_FILE:-/etc/hosts}"
# Seconds. A stalled official mirror must not consume the whole job.
APT_UPDATE_TIMEOUT="${AUTOMOTO_APT_UPDATE_TIMEOUT:-90}"
APT_INSTALL_TIMEOUT="${AUTOMOTO_APT_INSTALL_TIMEOUT:-360}"

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

# timeout is the root process so the signal hits apt. env execs apt in place,
# which keeps that the process timeout is watching (a sudo wrapper would not).
apt_cmd() {
  local seconds="$1"
  shift
  run_root timeout -k 20s "${seconds}s" env \
    DEBIAN_FRONTEND=noninteractive \
    RES_OPTIONS="timeout:2 attempts:1" \
    "$@"
}

log() {
  echo "apt-install: $*" >&2
}

write_apt_timeouts() {
  run_root tee /etc/apt/apt.conf.d/99-automoto-ci-apt >/dev/null <<'EOF'
APT::Get::Assume-Yes "true";
Acquire::Retries "1";
Acquire::http::Timeout "15";
Acquire::https::Timeout "15";
Acquire::ftp::Timeout "15";
Acquire::ForceIPv4 "true";
Acquire::http::Pipeline-Depth "0";
Acquire::AllowReleaseInfoChange::Suite "true";
Acquire::AllowReleaseInfoChange::Origin "true";
Acquire::AllowReleaseInfoChange::Label "true";
Acquire::AllowReleaseInfoChange::Codename "true";
EOF
}

codename() {
  local name
  name="$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')"
  if [[ -z "$name" ]]; then
    echo "apt-install: VERSION_CODENAME missing from /etc/os-release" >&2
    return 1
  fi
  printf '%s' "$name"
}

# apt-mirrors.txt lines are "URL<whitespace>priority:N", not a bare URL.
normalize_mirror() {
  local uri="$1"
  uri="${uri%%#*}"
  uri="${uri%%[[:space:]]*}"
  uri="${uri%/}"
  printf '%s' "$uri"
}

mirror_host() {
  local uri="$1"
  uri="${uri#http://}"
  uri="${uri#https://}"
  uri="${uri%%/*}"
  printf '%s' "$uri"
}

is_official_host() {
  local host="$1"
  [[ "$host" == *.ubuntu.com || "$host" == "ubuntu.com" ]]
}

# mawk (Ubuntu's default awk) rejects {n,m} in match(), so split the work:
# GNU grep pulls candidate addresses, awk keeps the first four real IPv4s.
ipv4s_from_json() {
  grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | awk -F. '
    $1 <= 255 && $2 <= 255 && $3 <= 255 && $4 <= 255 && !seen[$0]++ && count < 4 {
      print
      count++
    }
  '
}

doh_ipv4() {
  local host="$1" body
  body="$(curl -fsS --ipv4 --max-time 8 \
    --resolve "cloudflare-dns.com:443:1.1.1.1" \
    -H "accept: application/dns-json" \
    "https://cloudflare-dns.com/dns-query?name=${host}&type=A" 2>/dev/null || true)"
  if [[ -z "$body" ]]; then
    body="$(curl -fsS --ipv4 --max-time 8 \
      --resolve "dns.google:443:8.8.8.8" \
      -H "accept: application/dns-json" \
      "https://dns.google/resolve?name=${host}&type=A" 2>/dev/null || true)"
  fi
  [[ -n "$body" ]] || return 1
  printf '%s\n' "$body" | ipv4s_from_json
}

host_resolves() {
  local host="$1"
  RES_OPTIONS="timeout:2 attempts:1" timeout 3 getent ahostsv4 "$host" >/dev/null 2>&1
}

pin_host_from_doh() {
  local host="$1" ips ip escaped
  ips="$(doh_ipv4 "$host" || true)"
  [[ -n "${ips}" ]] || return 1
  if [[ -f "$HOSTS_FILE" ]]; then
    escaped="$(printf '%s' "$host" | sed 's/[.[\*^$]/\\&/g')"
    run_root sed -i "/# automoto-ci-apt ${escaped}\$/d" "$HOSTS_FILE"
  fi
  while IFS= read -r ip; do
    [[ -z "$ip" ]] && continue
    printf '%s %s # automoto-ci-apt %s\n' "$ip" "$host" "$host" | run_root tee -a "$HOSTS_FILE" >/dev/null
  done <<<"$ips"
}

ensure_resolvable() {
  local host="$1"
  if host_resolves "$host"; then
    return 0
  fi
  log "system DNS failed for ${host}; resolving with DNS-over-HTTPS"
  pin_host_from_doh "$host" || return 1
  host_resolves "$host"
}

# A usable mirror serves the release, updates, and security pocket as signed
# Ubuntu indexes. backports is unnecessary for LibreOffice and poppler.
mirror_usable() {
  local base="$1" suite="$2" path body
  for path in "$suite" "${suite}-updates" "${suite}-security"; do
    body="$(curl -4 -fsS --connect-timeout 5 --max-time 20 \
      "${base}/dists/${path}/InRelease" 2>/dev/null || true)"
    # Match the Suite line exactly. "Suite: resolute" is a prefix of
    # "Suite: resolute-security", so a substring check would accept the wrong index.
    if ! grep -q -x -F "Origin: Ubuntu" <<<"$body" || ! grep -q -x -F "Suite: ${path}" <<<"$body"; then
      log "skip ${base} (${path} index unavailable)"
      return 1
    fi
  done
}

collect_candidates() {
  local line uri
  if [[ -f "$APT_MIRRORS_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in
        ''|\#*) continue ;;
      esac
      uri="$(normalize_mirror "$line")"
      case "$uri" in
        http://*|https://*) printf '%s\n' "$uri" ;;
      esac
    done <"$APT_MIRRORS_FILE"
  fi
  # Official archives first (fast on Azure when DNS works), then mirrors that
  # are not under ubuntu.com. Those still answered in the CI failure where
  # every ubuntu.com name failed to resolve together.
  cat <<'EOF'
http://azure.archive.ubuntu.com/ubuntu
http://archive.ubuntu.com/ubuntu
http://security.ubuntu.com/ubuntu
https://mirrors.edge.kernel.org/ubuntu
http://mirror.csclub.uwaterloo.ca/ubuntu
https://ftp.uni-stuttgart.de/ubuntu
https://mirror.math.princeton.edu/pub/ubuntu
EOF
}

deduped_candidates() {
  collect_candidates | awk 'NF && !seen[$0]++'
}

signing_key() {
  local f line key
  shopt -s nullglob
  for f in /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.sources.disabled-by-automoto; do
    line="$(grep -m1 -E '^Signed-By:.*ubuntu-archive-keyring\.gpg' "$f" 2>/dev/null || true)"
    if [[ -n "$line" ]]; then
      key="${line#Signed-By:}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      shopt -u nullglob
      printf '%s' "$key"
      return 0
    fi
  done
  shopt -u nullglob
  if [[ -f /usr/share/keyrings/ubuntu-archive-keyring.gpg ]]; then
    printf '%s' /usr/share/keyrings/ubuntu-archive-keyring.gpg
    return 0
  fi
  echo "apt-install: Ubuntu archive keyring not found" >&2
  return 1
}

disable_ubuntu_archive_sources() {
  local f
  shopt -s nullglob
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do
    [[ -f "$f" ]] || continue
    [[ "$f" == *.disabled-by-automoto ]] && continue
    [[ "$(basename "$f")" == "automoto-ci-ubuntu.sources" ]] && continue
    if grep -Eq '(archive|security|azure\.archive|ports)\.ubuntu\.com|apt-mirrors\.txt|mirror\+file:' "$f"; then
      run_root mv "$f" "${f}.disabled-by-automoto"
    fi
  done
  shopt -u nullglob
}

write_sources() {
  local base="$1" suite="$2" key="$3"
  run_root tee /etc/apt/sources.list.d/automoto-ci-ubuntu.sources >/dev/null <<EOF
Types: deb
URIs: ${base}/
Suites: ${suite} ${suite}-updates ${suite}-security
Components: main universe restricted multiverse
Signed-By: ${key}
EOF
}

packages_installed() {
  local pkg status
  for pkg in "$@"; do
    status="$(dpkg-query -W -f '${Status}' "$pkg" 2>/dev/null || true)"
    if [[ "$status" != "install ok installed" ]]; then
      return 1
    fi
  done
}

install_from_mirror() {
  local base="$1" suite="$2" key="$3" pkg
  log "installing ${REQUESTED_PACKAGES[*]} from ${base}"
  run_root env DEBIAN_FRONTEND=noninteractive dpkg --configure -a || true
  disable_ubuntu_archive_sources
  write_sources "$base" "$suite" "$key"
  apt_cmd "$APT_UPDATE_TIMEOUT" apt-get update -q || return 1
  for pkg in "${REQUESTED_PACKAGES[@]}"; do
    # Same Ubuntu release on every mirror. Another mirror will not invent a
    # package this release does not publish, so do not spend the fallback on it.
    if ! run_root apt-cache show "$pkg" >/dev/null 2>&1; then
      log "${pkg} is not in ${suite}; not retrying other mirrors"
      return 3
    fi
  done
  apt_cmd "$APT_INSTALL_TIMEOUT" apt-get install -y -q --no-install-recommends "${REQUESTED_PACKAGES[@]}" || return 1
  packages_installed "${REQUESTED_PACKAGES[@]}"
}

# Try mirrors in order. A mirror that fails the index probe is skipped and does
# not use an install attempt. Stop after max_installs installs that still fail,
# so a dead official archive cannot block the external mirrors.
try_mirrors() {
  local max_installs="$1" suite="$2" key="$3"
  shift 3
  local base host installs=0 status=0
  [[ $# -gt 0 ]] || return 1
  for base in "$@"; do
    [[ -z "$base" ]] && continue
    host="$(mirror_host "$base")"
    if ! ensure_resolvable "$host"; then
      log "skip ${base} (unresolvable)"
      continue
    fi
    if ! mirror_usable "$base" "$suite"; then
      continue
    fi
    installs=$((installs + 1))
    status=0
    install_from_mirror "$base" "$suite" "$key" || status=$?
    if [[ "$status" -eq 0 ]]; then
      return 0
    fi
    if [[ "$status" -eq 3 ]]; then
      return 3
    fi
    log "install attempt ${installs} failed for ${base}"
    if [[ "$installs" -ge "$max_installs" ]]; then
      return 1
    fi
  done
  return 1
}

main() {
  if [[ $# -lt 1 ]]; then
    echo "usage: apt-install.sh PACKAGE..." >&2
    exit 2
  fi
  REQUESTED_PACKAGES=("$@")
  if packages_installed "${REQUESTED_PACKAGES[@]}"; then
    log "already installed: ${REQUESTED_PACKAGES[*]}"
    exit 0
  fi
  command -v curl >/dev/null 2>&1 || {
    echo "apt-install: curl is required" >&2
    exit 1
  }
  export DEBIAN_FRONTEND=noninteractive
  export RES_OPTIONS="${RES_OPTIONS:-timeout:2 attempts:1}"
  write_apt_timeouts

  local suite key base host status=1
  local -a official=() external=()
  suite="$(codename)"
  key="$(signing_key)"
  while IFS= read -r base; do
    [[ -z "$base" ]] && continue
    host="$(mirror_host "$base")"
    if is_official_host "$host"; then
      official+=("$base")
    else
      external+=("$base")
    fi
  done < <(deduped_candidates)

  # One official attempt: the runner list is three names for the same archive.
  # If that archive cannot be reached, install from a mirror outside ubuntu.com.
  if [[ ${#official[@]} -gt 0 ]]; then
    status=0
    try_mirrors 1 "$suite" "$key" "${official[@]}" || status=$?
    if [[ "$status" -eq 0 ]]; then
      log "installed: ${REQUESTED_PACKAGES[*]}"
      exit 0
    fi
    if [[ "$status" -eq 3 ]]; then
      echo "apt-install: package is not in this Ubuntu release: ${REQUESTED_PACKAGES[*]}" >&2
      exit 1
    fi
  fi
  if [[ ${#external[@]} -gt 0 ]]; then
    status=0
    try_mirrors 2 "$suite" "$key" "${external[@]}" || status=$?
    if [[ "$status" -eq 0 ]]; then
      log "installed: ${REQUESTED_PACKAGES[*]}"
      exit 0
    fi
  fi
  echo "apt-install: could not install from any Ubuntu mirror: ${REQUESTED_PACKAGES[*]}" >&2
  exit 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
