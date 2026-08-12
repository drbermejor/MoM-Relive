"""Configure the Linux server and Proton client with one shared contract."""

from __future__ import annotations

import argparse

import linux_client
import momlib
import native_server


def _add_value(argv, option, value):
    if value is not None:
        argv.extend([option, str(value)])


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Apply one Relive host, port and shared key to the native Linux "
            "server and the Windows client running through Proton."
        )
    )
    parser.add_argument("--host", help="backend address seen by both components")
    parser.add_argument("--server-host", help="override the server backend address")
    parser.add_argument("--client-host", help="override the client backend address")
    parser.add_argument("--bind", help="backend listen address")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key", help="shared key written to both components")
    parser.add_argument("--server-dir")
    parser.add_argument("--client-dir")
    parser.add_argument("--compat-dir")
    parser.add_argument("--proton")
    parser.add_argument("--account-id")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--server-only", action="store_true")
    scope.add_argument("--client-only", action="store_true")
    parser.add_argument("--restore", action="store_true")
    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    server_args = ["--restore" if options.restore else "--prepare-only"]
    client_args = ["--restore" if options.restore else "--prepare-only"]

    server_host = options.server_host or options.host
    client_host = options.client_host or options.host
    _add_value(server_args, "--server-dir", options.server_dir)
    _add_value(server_args, "--backend-host", server_host)
    _add_value(server_args, "--bind", options.bind)
    _add_value(server_args, "--port", options.port)
    _add_value(server_args, "--key", options.key)

    _add_value(client_args, "--client-dir", options.client_dir)
    _add_value(client_args, "--compat-dir", options.compat_dir)
    _add_value(client_args, "--proton", options.proton)
    _add_value(client_args, "--host", client_host)
    _add_value(client_args, "--port", options.port)
    _add_value(client_args, "--key", options.key)
    _add_value(client_args, "--account-id", options.account_id)

    if not options.client_only:
        result = native_server.main(server_args)
        if result:
            return result
    if not options.server_only:
        result = linux_client.main(client_args)
        if result:
            return result

    settings = momlib.load_settings()
    if options.restore:
        print("Selected Linux components restored.")
    else:
        if options.client_only:
            print("Linux client destination configured; server settings were preserved.")
            print(f"Host: {settings['client_backend_host']}")
            print(f"Port: {settings['client_backend_port']}")
            print(f"Shared key: {settings['client_access_key']}")
        elif options.server_only:
            print("Linux server contract configured; client settings were preserved.")
            print(f"Host: {settings['server_backend_host']}")
            print(f"Port: {settings['server_backend_port']}")
            print(f"Shared key: {settings['server_access_key']}")
        else:
            print("Linux client/server contract configured.")
            print(f"Host: {settings['client_backend_host']}")
            print(f"Port: {settings['client_backend_port']}")
            print(f"Shared key: {settings['client_access_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
