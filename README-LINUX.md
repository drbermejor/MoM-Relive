# MoM Relive — native Linux server

This package runs the Steam **Memories of Mars - Dedicated Server** build
natively on x86-64 Linux. It contains no game files and does not require Wine
or Python.

## Start

Install the dedicated-server tool through Steam, edit its normal
`DedicatedServerConfig.cfg`, and run as a normal user:

```bash
./MoMNativeServer
```

The standard native, Flatpak and Snap Steam locations and additional libraries
in `steamapps/libraryfolders.vdf` are detected automatically. To select a path
or set the values shared with Windows clients explicitly:

```bash
./MoMNativeServer \
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
./MoMNativeServer -- -Port=7778
```

## Maintenance

```bash
./MoMNativeServer --prepare-only  # patch only
./MoMNativeServer --backend-only  # backend only
./MoMNativeServer --restore       # restore managed changes
./MoMNativeServer --help
```

Patching is reversible and idempotent. The original ELF executable is kept as
`MemoriesOfMarsServer.orig`; its size and executable mode are preserved.
Native server settings remain in `DedicatedServerConfig.cfg`, except EAC is
disabled because it cannot be used with the community backend.

MoM Relive is an unofficial community compatibility project. See `LEGAL.md`
and `LICENSE` in this package.
