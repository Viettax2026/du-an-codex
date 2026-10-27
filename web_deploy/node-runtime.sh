#!/usr/bin/env bash
# Private Node.js runtime: do not replace Node used by other websites.
set -euo pipefail
destination=${1:?Cần đường dẫn đích cho Node.js}
[[ ! -e "$destination" ]] || { echo "Đích Node đã tồn tại: $destination" >&2; exit 1; }
case "$(uname -m)" in
  x86_64) node_arch=x64 ;;
  aarch64|arm64) node_arch=arm64 ;;
  *) echo 'Chỉ hỗ trợ Linux x64 hoặc ARM64.' >&2; exit 1 ;;
esac
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt -o "$scratch/SHASUMS256.txt"
node_archive=$(awk -v arch="$node_arch" '$2 ~ ("^node-v22\\.[0-9]+\\.[0-9]+-linux-" arch "\\.tar\\.xz$") {print $2;exit}' "$scratch/SHASUMS256.txt")
[[ "$node_archive" =~ ^node-v22\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] || { echo 'Không xác định được bản Node 22 chính thức.' >&2; exit 1; }
node_release=${node_archive%-linux-*}
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "https://nodejs.org/dist/${node_release#node-}/$node_archive" -o "$scratch/$node_archive"
(cd "$scratch"; awk -v file="$node_archive" '$2==file' SHASUMS256.txt | sha256sum --check --status -)
install -d -m 755 "$destination"
tar -xJf "$scratch/$node_archive" -C "$destination" --strip-components=1
"$destination/bin/node" --version
