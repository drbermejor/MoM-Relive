"""Prepare and launch the Windows Memories of Mars client through Proton."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

import momlib
import redirect_urls

STEAM_APP_ID = "644290"


def _compat_root(value=None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.name == "pfx":
            path = path.parent
        if (path / "pfx").is_dir():
            return path
        raise momlib.ConfigError(f"Could not find a Proton pfx under {path}")
    for steam in momlib.steam_roots():
        path = steam / "steamapps/compatdata" / STEAM_APP_ID
        if (path / "pfx").is_dir():
            return path.resolve()
    raise momlib.ConfigError(
        "The Memories of Mars Proton prefix was not found. Start the game once "
        "from Steam or pass --compat-dir."
    )


def _proton_path(value=None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file():
            return path
        raise momlib.ConfigError(f"The Proton launcher was not found: {path}")
    candidates = []
    for steam in momlib.steam_roots():
        common = steam / "steamapps/common"
        preferred = common / "Proton - Experimental/proton"
        if preferred.is_file():
            candidates.append(preferred)
        candidates.extend(
            path
            for path in common.glob("*Proton*/proton")
            if path.is_file() and path != preferred
        )
    if not candidates:
        raise momlib.ConfigError("Proton was not found; pass --proton.")
    return candidates[0].resolve()


def _client_ini(compat_root: Path) -> Path:
    users = compat_root / "pfx/drive_c/users"
    preferred = users / "steamuser/AppData/Local"
    local = preferred if preferred.is_dir() else None
    if local is None and users.is_dir():
        local = next(
            (path / "AppData/Local" for path in users.iterdir() if (path / "AppData/Local").is_dir()),
            None,
        )
    if local is None:
        local = preferred
    return local / "MemoriesOfMars/Saved/Config/WindowsNoEditor/Engine.ini"


def _steam_root(proton: Path) -> Path:
    for parent in proton.parents:
        if parent.name == "steamapps":
            return parent.parent
    raise momlib.ConfigError(f"Could not determine the Steam root from {proton}")


def _launch(client_dir: Path, compat_root: Path, proton: Path, settings, extra_args):
    exe = client_dir / momlib.CLIENT_EXE_REL
    env = os.environ.copy()
    env.update(
        {
            "STEAM_COMPAT_DATA_PATH": str(compat_root),
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(_steam_root(proton)),
            "SteamAppId": STEAM_APP_ID,
            "SteamGameId": STEAM_APP_ID,
        }
    )
    if settings.get("openssl_compat", False):
        env["OPENSSL_ia32cap"] = ":~0x20000000"
    command = [str(proton), "run", str(exe), "-NoEAC", "-console", *extra_args]
    print(f"Starting the Proton client: {exe}")
    process = subprocess.Popen(
        command,
        cwd=str(exe.parent),
        env=env,
        start_new_session=True,
    )
    if settings.get("limit_client_cpu", True) and hasattr(os, "sched_setaffinity"):
        logical = os.cpu_count() or 1
        if logical > 8:
            load_cores = max(1, min(int(settings.get("client_load_cores", 4)), logical))
            try:
                os.sched_setaffinity(process.pid, range(load_cores))
                print(f"Client startup limited to {load_cores} logical CPUs.")
            except OSError as exc:
                print(f"CPU affinity warning: {exc}", file=sys.stderr)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping the Proton client...")
        os.killpg(process.pid, signal.SIGTERM)
        return process.wait()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Patch and launch the Memories of Mars client through Proton."
    )
    parser.add_argument("--client-dir")
    parser.add_argument("--compat-dir", help="Steam compatdata/644290 directory")
    parser.add_argument("--proton", help="path to Proton's proton script")
    parser.add_argument("--host", help="Relive backend address seen by the client")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key", help="shared Relive access key")
    parser.add_argument("--account-id", help="numeric identity; blank preserves Steam ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--restore", action="store_true")
    parser.add_argument("client_args", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    try:
        settings = momlib.load_settings()
        found_client, _server = momlib.discover_installs()
        client_dir = Path(options.client_dir or settings.get("client_dir") or found_client or "").expanduser().resolve()
        if not (client_dir / momlib.CLIENT_EXE_REL).is_file():
            raise momlib.ConfigError("The Steam game client was not found; pass --client-dir.")
        compat_root = _compat_root(options.compat_dir or settings.get("proton_compat_dir"))
        proton = _proton_path(options.proton or settings.get("proton_path"))
        host = str(options.host or settings.get("client_backend_host") or "127.0.0.1")
        port = momlib.validate_port(
            options.port
            if options.port is not None
            else settings.get("client_backend_port", settings.get("backend_port", 8080))
        )
        key = momlib.validate_key(
            options.key
            if options.key is not None
            else settings.get("client_access_key", settings.get("access_key", "mom1"))
        )
        account_id = options.account_id
        if account_id is None:
            account_id = settings.get("account_id", "")
        ini = _client_ini(compat_root)
        settings.update(
            {
                "client_dir": str(client_dir),
                "client_backend_host": host,
                "client_backend_port": port,
                "client_access_key": key,
                "account_id": str(account_id or ""),
                "proton_compat_dir": str(compat_root),
                "proton_path": str(proton),
            }
        )
        momlib.save_settings(settings)
        if options.restore:
            result = momlib.restore_client(client_dir, ini_path=ini)
            print(
                "Proton client compatibility restored."
                if result["binary_restored"]
                else "No client binary backup was found."
            )
            return 0
        result = momlib.apply_client(client_dir, host, port, key, account_id, ini_path=ini)
        print(f"Proton client prepared: {result['url']}")
        print(f"Unreal configuration: {ini}")
        if options.prepare_only:
            return 0
        client_args = list(options.client_args)
        if client_args[:1] == ["--"]:
            client_args.pop(0)
        return _launch(client_dir, compat_root, proton, settings, client_args)
    except (ValueError, OSError, redirect_urls.PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
