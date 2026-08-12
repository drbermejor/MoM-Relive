# MoM Relive — native Linux server

This package prepares and launches both Steam components on x86-64 Linux:

- `mom-relive-server` runs the dedicated server as a native Linux process.
- `mom-relive-client` patches the Windows client and launches it through the
  installed Steam Proton runtime without EAC.
- `mom-relive-configure` applies the same host, port and shared key to both.

It contains no game files and does not require Python. Proton is needed only
for the game client.

## Install

Extract the archive and install it for the current user. This does not require
`sudo`:

```bash
./install_linux.sh
```

It installs `mom-relive-server` in `~/.local/bin`, adds a desktop launcher and
provides an optional `systemd --user` service. It also installs
`mom-relive-client`, `mom-relive-configure` and their desktop launchers.
Uninstalling preserves settings, saves and game backups:

```bash
./install_linux.sh --uninstall
```

## Start

Configure both components together first:

```bash
mom-relive-configure --host 127.0.0.1 --port 8080 --key YOUR_SHARED_KEY
```

Changing the shared key requires running this command again and restarting the
server. The matching client and server values are persisted in
`~/.local/share/MoMRevival/config.json`.

To connect this client temporarily to somebody else's server, change only its
destination. The local server host, port and key are left untouched:

```bash
mom-relive-configure --client-only \
  --host OTHER_SERVER_ADDRESS --port 8080 --key THEIR_SHARED_KEY
mom-relive-client
```

Run the same command with your own server address and key to switch back. On a
machine that hosts only a server, use `--server-only`; this also allows client
and server tools to be installed on different Linux machines.

Install the dedicated-server tool through Steam, edit its normal
`DedicatedServerConfig.cfg`, and run as a normal user:

```bash
mom-relive-server
```

The standard native, Flatpak and Snap Steam locations and additional libraries
in `steamapps/libraryfolders.vdf` are detected automatically. To select a path
or set the values shared with Windows clients explicitly:

```bash
mom-relive-server \
  --server-dir "$HOME/.local/share/Steam/steamapps/common/Memories of Mars - Dedicated Server" \
  --backend-host 127.0.0.1 \
  --bind 0.0.0.0 \
  --port 8080 \
  --key changeMe
```

The first run stores these values in
`~/.local/share/MoMRevival/config.json`. Use the same backend host, TCP port and
key when preparing each Windows client. For Internet hosting, also pass
`--public-ip YOUR_PUBLIC_IP` and forward UDP 7777, UDP 15000 and the configured
backend TCP port.

The launcher automatically starts the world again after its configured daily
exit, matching Steam's `RunServer.sh`. Pass `--no-auto-restart` to disable this.
Use `Ctrl+C` to stop the world cleanly. Extra arguments after `--` are passed to
the game server, for example:

```bash
mom-relive-server -- -Port=7778
```

## Maintenance

```bash
mom-relive-server --prepare-only  # patch only
mom-relive-server --backend-only  # backend only
mom-relive-server --restore       # restore managed changes
mom-relive-server --help
```

For an unattended user service after initial configuration:

```bash
systemctl --user enable --now mom-relive-server
journalctl --user -u mom-relive-server -f
```

Patching is reversible and idempotent. The original ELF executable is kept as
`MemoriesOfMarsServer.orig`; its size and executable mode are preserved.
Native server settings remain in `DedicatedServerConfig.cfg`, except EAC is
disabled because it cannot be used with the community backend.

MoM Relive is an unofficial community compatibility project. See `LEGAL.md`
and `LICENSE` in this package.

## Proton client

Start the game once from Steam so its Proton prefix exists, then run:

```bash
mom-relive-client --host 127.0.0.1 --port 8080 --key YOUR_SHARED_KEY
```

The tool patches `MemoriesOfMars.exe`, writes the game's `Engine.ini` inside
Steam's `compatdata/644290` prefix and launches the real game executable with
`-NoEAC`. It does not replace Steam's Windows launcher. Use the MoM Relive
desktop entry or `mom-relive-client` for Linux sessions.

```bash
mom-relive-client --prepare-only
mom-relive-client --restore
```

CPU affinity is not changed by default on Linux. If a particular processor
hangs only while the game is starting, `--limit-cpu` temporarily limits the
Proton prefix and restores all available CPUs after 75 seconds. Use
`--diagnostics` to save a detailed Proton log under
`~/.local/share/MoMRevival/diagnostics` while reproducing a crash.

The launcher disables Proton's DXVK-NVAPI layer for Memories of Mars. The game
does not require NVAPI, and the layer can make its old UE4 render thread recurse
and terminate while loading the mobile 3D-printer interface on AMD GPUs. Use
`--enable-nvapi` only to override this compatibility setting for testing. If
the Windows game process exits abnormally, the launcher also cleans up its
remaining Proton/Wine processes instead of waiting indefinitely.
