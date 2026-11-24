#!/usr/bin/env bash
# Download an official, version-pinned toolchain on a disposable CI runner, verify its
# SHA-256 before unpacking, and add it to GITHUB_PATH. Linux x86_64 only.
# Usage: install-pinned-toolchain.sh zig|nim|crystal|odin|terraform ...
set -euo pipefail
dest="${RUNNER_TEMP:-/tmp}/pinned-toolchains"
mkdir -p "$dest"

fetch() {  # url sha256 file
  local url="$1" sum="$2" file="$dest/$3"
  for attempt in 1 2 3; do
    if curl -fsSL --retry 3 --retry-delay 5 -o "$file" "$url"; then break; fi
    echo "download attempt $attempt failed: $url" >&2
    sleep $((attempt * 10))
  done
  echo "$sum  $file" | sha256sum -c -
}

add_path() { echo "$1" >> "${GITHUB_PATH:-/dev/null}"; export PATH="$1:$PATH"; }

for tool in "$@"; do
  case "$tool" in
    zig)
      fetch https://ziglang.org/download/0.17.1/zig-x86_64-linux-0.17.1.tar.xz \
        3581863e3cbcfd0fce0efc682ce7e9e93da96668a977791d356a26d2a7e9b17a zig.tar.xz
      tar -xJf "$dest/zig.tar.xz" -C "$dest"
      add_path "$dest/zig-x86_64-linux-0.17.1" ;;
    nim)
      fetch https://nim-lang.org/download/nim-2.4.2-linux_x64.tar.xz \
        0ee5b16e81852a956d4fddb4aa44b5958c645c992132fa43be45f489573ee325 nim.tar.xz
      tar -xJf "$dest/nim.tar.xz" -C "$dest"
      add_path "$dest/nim-2.4.2/bin" ;;
    crystal)
      fetch https://github.com/crystal-lang/crystal/releases/download/1.22.3/crystal-1.22.3-1-linux-x86_64-bundled.tar.gz \
        140302ecb6316b6202895caf3a4764810a0d60b0ca2d81c8156891171dc2ff60 crystal.tar.gz
      tar -xzf "$dest/crystal.tar.gz" -C "$dest"
      add_path "$dest/crystal-1.22.3-1/bin" ;;
    odin)
      fetch https://github.com/odin-lang/Odin/releases/download/dev-2026-11a/odin-linux-amd64-dev-2026-11a.tar.gz \
        65c9f6e97d6f8a30930e151f270ce5aeaa98fe8b2ba49fe067394e2af04f7618 odin.tar.gz
      tar -xzf "$dest/odin.tar.gz" -C "$dest"
      add_path "$(dirname "$(find "$dest" -maxdepth 2 -type f -name odin -perm -u+x | head -n1)")" ;;
    terraform)
      fetch https://releases.hashicorp.com/terraform/1.17.2/terraform_1.17.2_linux_amd64.zip \
        e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b terraform.zip
      mkdir -p "$dest/terraform"
      python3 -m zipfile -e "$dest/terraform.zip" "$dest/terraform"
      chmod +x "$dest/terraform/terraform"
      add_path "$dest/terraform" ;;
    *) echo "unknown toolchain: $tool" >&2; exit 2 ;;
  esac
done
