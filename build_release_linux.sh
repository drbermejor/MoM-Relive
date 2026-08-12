#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

python_bin="${PYTHON:-python3}"
version="$($python_bin -c 'from version import __version__; print(__version__)')"
architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" ]]; then
  echo "Linux releases are currently supported only on x86_64 (found $architecture)." >&2
  exit 2
fi

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  $python_bin -m unittest discover -s tests -v
fi
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMNativeServer \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  native_server.py
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMReliveClient \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  linux_client.py
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMReliveConfigure \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  linux_configure.py

package_name="MoMRelive-${version}-linux-x86_64"
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/mom-relive-release.XXXXXX")"
trap 'rm -rf -- "$stage_root"' EXIT
package_dir="$stage_root/$package_name"
mkdir -p "$package_dir"
install -m 755 dist/linux/MoMNativeServer "$package_dir/MoMNativeServer"
install -m 755 dist/linux/MoMReliveClient "$package_dir/MoMReliveClient"
install -m 755 dist/linux/MoMReliveConfigure "$package_dir/MoMReliveConfigure"
install -m 755 install_linux.sh "$package_dir/install_linux.sh"
install -m 644 README-LINUX.md "$package_dir/README-LINUX.md"
install -m 644 LEGAL.md "$package_dir/LEGAL.md"
install -m 644 LICENSE "$package_dir/LICENSE"

archive="dist/${package_name}.tar.gz"
tar -C "$stage_root" -czf "$archive" "$package_name"
sha256sum "$archive" > "$archive.sha256"

echo "Created $archive"
cat "$archive.sha256"
