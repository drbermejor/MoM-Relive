#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
bin_home="${XDG_BIN_HOME:-$HOME/.local/bin}"
install_root="$data_home/MoMRelive"
installed_binary="$install_root/MoMNativeServer"
installed_client="$install_root/MoMReliveClient"
installed_configure="$install_root/MoMReliveConfigure"
command_link="$bin_home/mom-relive-server"
client_link="$bin_home/mom-relive-client"
configure_link="$bin_home/mom-relive-configure"
desktop_file="$data_home/applications/mom-relive-server.desktop"
client_desktop="$data_home/applications/mom-relive-client.desktop"
configure_desktop="$data_home/applications/mom-relive-configure.desktop"
service_file="$config_home/systemd/user/mom-relive-server.service"

if [[ "${1:-}" == "--uninstall" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now mom-relive-server.service >/dev/null 2>&1 || true
  fi
  rm -f -- "$command_link" "$client_link" "$configure_link" "$desktop_file" "$client_desktop" "$configure_desktop" "$service_file" "$installed_binary" "$installed_client" "$installed_configure"
  rmdir -- "$install_root" 2>/dev/null || true
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  echo "MoM Relive Linux tools removed. Game backups and user data were preserved."
  exit 0
fi

if [[ ! -x "$source_dir/MoMNativeServer" || ! -x "$source_dir/MoMReliveClient" || ! -x "$source_dir/MoMReliveConfigure" ]]; then
  echo "All three Linux tools must be next to install_linux.sh." >&2
  exit 2
fi

mkdir -p -- "$install_root" "$bin_home" "$(dirname -- "$desktop_file")" "$(dirname -- "$service_file")"

install_atomic() {
  local source_path="$1"
  local target_path="$2"
  local pending_path="${target_path}.new"
  install -m 755 "$source_path" "$pending_path"
  mv -f -- "$pending_path" "$target_path"
}

# Renaming a complete temporary file also permits upgrades while an older
# installed executable is still mapped by a running process.
install_atomic "$source_dir/MoMNativeServer" "$installed_binary"
install_atomic "$source_dir/MoMReliveClient" "$installed_client"
install_atomic "$source_dir/MoMReliveConfigure" "$installed_configure"
ln -sfn -- "$installed_binary" "$command_link"
ln -sfn -- "$installed_client" "$client_link"
ln -sfn -- "$installed_configure" "$configure_link"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=MoM Relive Server'
  printf '%s\n' 'Comment=Run the native Memories of Mars community server'
  printf 'Exec="%s"\n' "$installed_binary"
  printf '%s\n' 'Icon=network-server'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;'
} > "$desktop_file"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=MoM Relive Client (Proton)'
  printf '%s\n' 'Comment=Prepare and run Memories of Mars through Proton'
  printf 'Exec="%s"\n' "$installed_client"
  printf '%s\n' 'Icon=steam_icon_644290'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;'
} > "$client_desktop"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=Configure MoM Relive (Linux)'
  printf '%s\n' 'Comment=Apply one host, port and key to client and server'
  printf 'Exec="%s"\n' "$installed_configure"
  printf '%s\n' 'Icon=preferences-system-network'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;Settings;'
} > "$configure_desktop"

{
  printf '%s\n' '[Unit]'
  printf '%s\n' 'Description=MoM Relive native dedicated server'
  printf '%s\n' 'After=network-online.target'
  printf '%s\n' 'Wants=network-online.target'
  printf '%s\n' '' '[Service]'
  printf '%s\n' 'Type=simple'
  printf 'ExecStart="%s"\n' "$installed_binary"
  printf '%s\n' 'KillSignal=SIGINT'
  printf '%s\n' 'KillMode=mixed'
  printf '%s\n' 'SuccessExitStatus=130 143'
  printf '%s\n' 'TimeoutStopSec=60'
  printf '%s\n' 'Restart=on-failure'
  printf '%s\n' 'RestartSec=10'
  printf '%s\n' '' '[Install]'
  printf '%s\n' 'WantedBy=default.target'
} > "$service_file"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$(dirname -- "$desktop_file")" >/dev/null 2>&1 || true
fi

echo "MoM Relive Linux tools installed."
echo "Command: $command_link"
echo "Client: $client_link"
echo "Configure: $configure_link"
echo "Desktop: $desktop_file"
echo "Service: $service_file"
echo "Configuration and saves remain under: $data_home/MoMRevival"
echo
echo "Run 'mom-relive-configure --help' or use the desktop launchers."
echo "Optional background service: systemctl --user enable --now mom-relive-server"
