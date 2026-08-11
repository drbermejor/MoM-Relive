# MoM Relive

An unofficial community replacement for the retired online services used by
**Memories of Mars**. It lets owners of the game run a dedicated server, list it
in the in-game browser, connect without EAC, and keep world and character
progress on the server machine.

Current version: **0.5.1**. Tested on Windows 11 with the Steam client and the
Steam dedicated-server installation.

> This project does not contain or redistribute the game, game assets, Steam
> files, EAC files, or saved games. You must own and install Memories of Mars
> and its dedicated server separately.
>
> See the project [legal notice](LEGAL.md) for its unofficial status, intended
> scope, privacy information, and user responsibilities.

## What works

- Replacement HTTP backend for login, account identity and server sessions.
- Separate client and dedicated-server applications.
- Reversible, repeatable patching; Steam updates are detected and the clean
  `.orig` baseline is refreshed safely.
- A permanent `Launch_Game.exe` replacement that starts the game with `-NoEAC`.
- Server browser discovery over LAN or the Internet.
- Persistent inventory, equipment, action bar, health, oxygen, food, FLOPS,
  learned blueprints, work orders, character progress and world deployables.
- Automatic save backups before shutdown and on demand.
- Server manager with live status, connected players, character names parsed
  from `Game.log`, a scrollable live log, panel activity, and a safely hidden or
  visible native server console.
- Automatic public-IP detection and automatic recovery after the game's daily
  server restart.

## Install

Download `MoMRevivalSetup.exe` from the latest GitHub release. The installer is
self-contained and does not require Python. Choose one of these components:

- **Client** on every player's PC.
- **Dedicated server** on the host machine.
- **Client and dedicated server** when both run on the same PC.

The applications request administrator rights because Steam commonly installs
the game below `Program Files (x86)`.

## Host a server

1. Install the Steam tool **Memories of Mars - Dedicated Server**.
2. Open **MoM Server Manager**, then open **Configuration**.
3. Select the dedicated-server folder and an existing world ID if you already
   have a save. Changing the world ID selects a different save directory.
4. Set the server name, optional password, player limit and shared access key.
5. Save and apply the server patch, then click **Start**.
6. Allow or forward these ports:

   | Port | Protocol | Purpose |
   |---|---|---|
   | 7777 | UDP | Game traffic |
   | 15000 | UDP | Server query/beacon |
   | 8080 | TCP | Revival backend (or your configured port) |

For Internet play, forward the ports in the router to the host PC. The manager
can create the matching Windows Firewall rules, but it cannot configure the
router.

The shared key keeps casual Internet scans out of the API. It is not an
anti-cheat secret: an authorized client can read the value from its own patched
executable.

## Connect a client

1. Install the Steam game **Memories of Mars**.
2. Open **MoM Revival Client**.
3. Enter the host's public IP or DNS name, backend port and shared key.
4. Leave **Account ID** blank to preserve the currently installed identity, or
   generate a new numeric ID. Keep the same ID forever to load the same
   character, and never share one ID between two players.
5. Click **Prepare / repair**, then **Play without EAC**. Steam's normal Play
   button will also use the Revival launcher after preparation.

**Restore official files** restores both the original game executable and the
official EAC launcher. It does not delete saves.

## Saves and backups

The replacement backend does not own the world save. The dedicated server
writes JSON data below:

```text
Game/Saved/DB/Server<WorldId>/Version_1.1/
|-- PlayerData/<account-id>/
|   |-- Inventory.json
|   |-- Equipment.json
|   |-- Actionbar.json
|   |-- Stats.json
|   |-- Flops.json
|   |-- Blueprints.json
|   |-- Workorders.json
|   `-- Progress.json
`-- ServerData/
    |-- Deployables.json
    `-- Alliances.json
```

The manager discovers existing worlds and prefers the one with the most player
data. Managed backups are stored outside the source tree in
`%APPDATA%\MoMRevival\saves`. Back up the whole `Game\Saved\DB` directory
before migrating a server.

The option that preserves characters on reconnect writes:

```ini
[/Script/ShooterGame.MarsGameMode]
bNeverSpawnInCloningFacility=True
```

New characters may need one initial connection with that option disabled to
receive the cloning-facility starter equipment. Re-enable it afterwards to
preserve the character on reconnect.

## Build from source

Requirements:

- Windows 10 or 11
- Python 3.11 or later
- `pyinstaller`
- Inno Setup 6

Run:

```powershell
python -m unittest discover -s tests -v
.\build_release.ps1
```

The reproducible outputs are written to `dist\`. Neither `dist\` nor PyInstaller
build files are committed.

Command-line patching is also available:

```powershell
python apply.py server --key ab12cd34 --public-ip 203.0.113.10
python backend.py --access-key ab12cd34 --data-dir "$env:APPDATA\MoMRevival"
python apply.py client --host 203.0.113.10 --key ab12cd34 --account-id 10001
```

## How it works

The original AWS API Gateway endpoints no longer resolve. MoM Relive redirects
the session service through Unreal configuration and rewrites the retired
account-service URL in the client executable without changing its file size.
The local backend reproduces the response shapes required by the original game.

Important compatibility details discovered during recovery:

- The legacy Unreal build can crash while loading on high-thread-count CPUs;
  the client launcher can temporarily restrict CPU affinity during startup.

## Known limitations

- Achievements and global online statistics are placeholders.
- Some harmless serialization warnings from retired optional services remain in
  the game log.
- This is a community compatibility project, not an official Limbic, 505 Games,
  Steam, or Epic Games product.

## License

The original code in this repository is released under the GNU General Public
License v3.0. This license does not grant rights to Memories of Mars or any
third-party software. See [LEGAL.md](LEGAL.md) for the complete project notice.
