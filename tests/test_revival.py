import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import backend
import client_launcher
import momlib
import native_server
import redirect_urls
import server_manager

AWS_URL = "https://7pxwu4beee.execute-api.eu-west-1.amazonaws.com/Prod/"


def fake_exe(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"MZ"
        + AWS_URL.encode("ascii")
        + b"\0tail"
        + AWS_URL.encode("utf-16le")
        + b"\0\0end"
    )


class ClientLauncherTests(unittest.TestCase):
    @unittest.skipUnless(client_launcher.os.name == "nt", "Windows-only behavior")
    def test_external_game_uses_the_system_dll_search_path(self):
        kernel32 = mock.MagicMock()
        kernel32.SetDllDirectoryW.return_value = 1
        with mock.patch("client_launcher.ctypes.WinDLL", return_value=kernel32):
            client_launcher._restore_system_dll_search()
        kernel32.SetDllDirectoryW.assert_called_once_with(None)

    @unittest.skipUnless(client_launcher.os.name == "nt", "Windows-only behavior")
    def test_dll_search_restore_failure_is_not_ignored(self):
        kernel32 = mock.MagicMock()
        kernel32.SetDllDirectoryW.return_value = 0
        with (
            mock.patch("client_launcher.ctypes.WinDLL", return_value=kernel32),
            mock.patch("client_launcher.ctypes.get_last_error", return_value=5),
        ):
            with self.assertRaisesRegex(OSError, "DLL search path"):
                client_launcher._restore_system_dll_search()


class BinaryPatchTests(unittest.TestCase):
    def test_patch_keeps_size_and_restore_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            original = exe.read_bytes()
            replaced = redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            self.assertEqual(replaced, 2)
            self.assertEqual(len(exe.read_bytes()), len(original))
            self.assertIn(b"http://127.0.0.1:8080/r/abcd/1/", exe.read_bytes())
            self.assertTrue(redirect_urls.restore(exe))
            self.assertEqual(exe.read_bytes(), original)

    def test_rejects_url_that_does_not_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            with self.assertRaises(redirect_urls.PatchError):
                redirect_urls.patch(exe, "http://" + "x" * 70 + "/")
            self.assertEqual(
                exe.read_bytes(), exe.with_suffix(".exe.orig").read_bytes()
            )

    def test_steam_update_refreshes_original_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            updated = b"new-version-" + AWS_URL.encode("ascii") + b"\0"
            exe.write_bytes(updated)
            redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            redirect_urls.restore(exe)
            self.assertEqual(exe.read_bytes(), updated)


class ConfigTests(unittest.TestCase):
    def test_existing_world_with_more_player_data_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            sparse = server / "Game/Saved/DB/Serversparse/Version_1.1/PlayerData/1"
            complete = server / "Game/Saved/DB/Servercomplete/Version_1.1/PlayerData/1"
            sparse.mkdir(parents=True)
            complete.mkdir(parents=True)
            (sparse / "Stats.json").write_text("{}", encoding="utf-8")
            for name in ("Stats.json", "Inventory.json", "Flops.json"):
                (complete / name).write_text("{}", encoding="utf-8")

            worlds = momlib.discover_server_worlds(server)

            self.assertEqual(worlds[0]["server_id"], "complete")
            self.assertEqual(worlds[0]["players"], 1)
            self.assertEqual(worlds[0]["player_files"], 3)

    def test_ini_apply_and_restore_preserve_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "Engine.ini"
            ini.write_text(
                "[Core.System]\nPaths=keep\n\n[OnlineSubsystemLimbic]\nOther=keep\n",
                encoding="utf-8",
            )
            momlib.set_limbic_url(ini, "http://127.0.0.1:8080/r/abcd/1/")
            text = ini.read_text(encoding="utf-8")
            self.assertEqual(text.count("BaseURL="), 2)
            momlib.remove_ini_key(ini, momlib.LIMBIC_SECTION, "BaseURL")
            text = ini.read_text(encoding="utf-8")
            self.assertIn("Paths=keep", text)
            self.assertIn("Other=keep", text)
            self.assertNotIn("BaseURL", text)

    def test_client_and_server_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "client"
            server = root / "server"
            fake_exe(client / momlib.CLIENT_EXE_REL)
            fake_exe(server / momlib.SERVER_EXE_REL)
            (server / momlib.SERVER_CFG_REL).write_text(
                json.dumps({"ServerName": "old", "EnableEAC": True}), encoding="utf-8"
            )
            ini = root / "client.ini"

            result = momlib.apply_client(
                client, "127.0.0.1", 8080, "abcd", "12345", ini
            )
            self.assertIn("/abcd/12345/", result["url"])
            self.assertFalse(
                (server / momlib.SERVER_EXE_REL).with_suffix(".exe.orig").exists()
            )

            result = momlib.apply_server(
                server, "127.0.0.1", 8080, "abcd", server_name="new", max_players=4
            )
            self.assertIn("/abcd/s/", result["url"])
            cfg = json.loads(
                (server / momlib.SERVER_CFG_REL).read_text(encoding="utf-8")
            )
            self.assertEqual(cfg["ServerName"], "new")
            self.assertEqual(cfg["MaxPlayers"], 4)
            self.assertFalse(cfg["EnableEAC"])
            momlib.restore_server(server)
            game_ini = (server / momlib.SERVER_GAME_REL).read_text(encoding="utf-8")
            self.assertNotIn("bNeverSpawnInCloningFacility", game_ini)
            cfg = json.loads(
                (server / momlib.SERVER_CFG_REL).read_text(encoding="utf-8")
            )
            self.assertTrue(cfg["EnableEAC"])

    def test_compatibility_only_preserves_native_server_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            fake_exe(server / momlib.SERVER_EXE_REL)
            config = server / momlib.SERVER_CFG_REL
            config.write_text(
                json.dumps(
                    {
                        "ServerName": "Configured natively",
                        "ServerPassword": "keep-me",
                        "ServerID": "native-world",
                        "MaxPlayers": 23,
                        "EnableEAC": True,
                    }
                ),
                encoding="utf-8",
            )

            momlib.apply_server_compatibility(
                server, "127.0.0.1", 8080, "abcd"
            )

            updated = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(updated["ServerName"], "Configured natively")
            self.assertEqual(updated["ServerPassword"], "keep-me")
            self.assertEqual(updated["ServerID"], "native-world")
            self.assertEqual(updated["MaxPlayers"], 23)
            self.assertFalse(updated["EnableEAC"])

    def test_server_openssl_compatibility_is_enabled_by_default(self):
        env = momlib.server_environment({}, {"KEEP": "yes"})

        self.assertEqual(env["OPENSSL_ia32cap"], ":~0x20000000")
        self.assertEqual(env["KEEP"], "yes")

    def test_server_openssl_compatibility_can_be_disabled(self):
        env = momlib.server_environment(
            {"server_openssl_compat": False}, {"KEEP": "yes"}
        )

        self.assertNotIn("OPENSSL_ia32cap", env)

    def test_client_launcher_replaces_eac_and_restores_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            official = root / momlib.CLIENT_LAUNCHER_REL
            official.write_bytes(b"official-eac-launcher")
            revival = root / "MoMClientLauncher.exe"
            revival.write_bytes(b"revival-launcher-v1")
            ini = root / "Engine.ini"

            result = momlib.apply_client(
                root,
                "127.0.0.1",
                8080,
                "abcd",
                "12345",
                ini,
                launcher_source=revival,
            )
            self.assertEqual(official.read_bytes(), revival.read_bytes())
            self.assertTrue(result["launcher"])
            self.assertTrue(momlib.client_launcher_is_installed(root))

            restored = momlib.restore_client(root, ini)
            self.assertTrue(restored["launcher_restored"])
            self.assertEqual(official.read_bytes(), b"official-eac-launcher")
            self.assertFalse(momlib.client_launcher_is_installed(root))

    def test_client_launcher_refresh_preserves_latest_steam_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            target = root / momlib.CLIENT_LAUNCHER_REL
            target.write_bytes(b"official-v1")
            launcher = root / "MoMClientLauncher.exe"
            launcher.write_bytes(b"revival-v1")
            momlib.install_client_launcher(root, launcher)

            # Actualizar Revival no debe convertir el lanzador Revival anterior
            # en la copia supuestamente oficial.
            launcher.write_bytes(b"revival-v2")
            momlib.install_client_launcher(root, launcher)
            self.assertTrue(momlib.client_launcher_is_installed(root))
            momlib.restore_client_launcher(root)
            self.assertEqual(target.read_bytes(), b"official-v1")

            # Si Steam actualiza el fichero, esa versión sí pasa a ser la nueva
            # base restaurable antes de volver a aplicar Revival.
            target.write_bytes(b"official-v2")
            self.assertFalse(momlib.client_launcher_is_installed(root))
            momlib.install_client_launcher(root, launcher)
            momlib.restore_client_launcher(root)
            self.assertEqual(target.read_bytes(), b"official-v2")

    def test_blank_account_id_uses_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            result = momlib.apply_client(
                root, "127.0.0.1", 8080, "abcd", "", root / "Engine.ini"
            )
            self.assertIn("/abcd/p/", result["url"])

    def test_blank_account_id_preserves_existing_manual_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / "Engine.ini"
            fake_exe(root / momlib.CLIENT_EXE_REL)
            momlib.apply_client(root, "127.0.0.1", 8080, "abcd", "12345", ini)
            result = momlib.apply_client(root, "192.0.2.1", 8081, "efgh", "", ini)
            self.assertIn("/efgh/12345/", result["url"])

    def test_generated_account_id_is_17_digits(self):
        generated = momlib.generate_account_id()
        self.assertRegex(generated, r"^[0-9]{17}$")
        self.assertNotEqual(generated, "0" * 17)

    def test_public_ip_detection(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"203.0.113.20\n"
        with mock.patch("momlib.urllib.request.urlopen", return_value=response):
            self.assertEqual(momlib.detect_public_ip(), "203.0.113.20")

    def test_url_limit_is_explained(self):
        with self.assertRaisesRegex(momlib.ConfigError, "maximo 60"):
            momlib.backend_url(
                "a-very-long-backend-name.example.invalid",
                8080,
                "longaccesskey123",
                "76561198000000001",
            )

    def test_ipv6_url_uses_brackets(self):
        self.assertEqual(
            momlib.backend_url("::1", 8080, "abcd", "1"),
            "http://[::1]:8080/r/abcd/1/",
        )


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        backend.STATE_FILE = data / "state.json"
        backend.TRACE_LOG = data / "requests.log"
        backend.UNKNOWN_LOG = data / "unknown.log"
        backend.STATE = backend._empty_state()
        backend.ACCESS_KEY = "abcd"
        backend.ADVERTISE_HOST = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, body=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.load(response)

    def test_health_and_key_enforcement(self):
        status, body = self.request("/health")
        self.assertEqual((status, body["result"]), (200, "ok"))
        with self.assertRaises(urllib.error.HTTPError) as hit:
            self.request("/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(hit.exception.code, 403)
        hit.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as hit:
            self.request("/r/wrong/123/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(hit.exception.code, 403)
        hit.exception.close()

    def test_manual_account_overrides_steam_identity(self):
        _, login = self.request("/r/abcd/12345/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(login["accid"], "12345")
        _, patterns = self.request("/r/abcd/12345/GetUnlockedPatterns/999")
        self.assertEqual(patterns["result"]["accid"], "12345")

    def test_passthrough_preserves_game_identity(self):
        _, login = self.request("/r/abcd/p/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(login["accid"], "999")
        _, patterns = self.request("/r/abcd/p/GetUnlockedPatterns/999")
        self.assertEqual(patterns["result"]["accid"], "999")

    def test_public_host_overrides_private_server_address(self):
        backend.ADVERTISE_HOST = "game.example.net"
        _, created = self.request(
            "/r/abcd/s/CreateSession",
            {"IpAddress": "192.168.50.122", "Port": 7777},
            "POST",
        )
        self.assertEqual(created["IpAddress"], "game.example.net")
        _, updated = self.request(
            "/r/abcd/s/UpdateSession",
            {"SessionId": created["SessionId"], "IpAddress": "10.0.0.2"},
            "PATCH",
        )
        self.assertEqual(updated["IpAddress"], "game.example.net")
        local = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="127.0.0.1")
        )
        remote = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="8.8.8.8")
        )
        self.assertEqual(local["Sessions"][0]["IpAddress"], "10.0.0.2")
        self.assertEqual(remote["Sessions"][0]["IpAddress"], "game.example.net")

    def test_server_prefix_can_create_and_list_session(self):
        _, created = self.request(
            "/r/abcd/s/CreateSession",
            {"OwningUserName": "test", "IpAddress": "192.0.2.1", "Port": 7777},
            "POST",
        )
        self.assertEqual(created["SessionId"], "1")
        _, listed = self.request("/r/abcd/12345/GetAllSessions")
        self.assertEqual(len(listed["Sessions"]), 1)

        # El servidor manda KeepAlive cada unos 10 segundos. Una sesión reciente
        # no debe caducar durante una carga normal.
        backend.STATE["sessions"]["1"]["_last_seen"] = time.time()
        self.assertFalse(backend.prune_sessions())
        _, listed = self.request("/r/abcd/12345/GetAllSessions")
        self.assertEqual(len(listed["Sessions"]), 1)

        self.request(
            "/r/abcd/s/RegisterPlayers",
            {"SessionId": "1", "Players": ["STEAM_12345"]},
            "PATCH",
        )
        _, status = self.request("/r/abcd/s/AdminStatus")
        self.assertEqual(status["api_version"], 1)
        self.assertEqual(status["players"][0]["account_id"], "12345")
        self.request(
            "/r/abcd/s/UnregisterPlayers",
            {"SessionId": "1", "Players": ["STEAM_12345"]},
            "PATCH",
        )
        _, status = self.request("/r/abcd/s/AdminStatus")
        self.assertEqual(status["players"], [])

    def test_session_without_keepalive_expires(self):
        backend.STATE["sessions"]["dead"] = {
            "SessionId": "dead",
            "OwningUserName": "apagado",
            "_last_seen": time.time() - backend.SESSION_TTL - 1,
        }
        self.assertTrue(backend.prune_sessions())
        self.assertNotIn("dead", backend.STATE["sessions"])


class ManagerTests(unittest.TestCase):
    def test_managed_launch_applies_server_openssl_environment(self):
        settings = {
            "server_dir": "C:/server",
            "server_openssl_compat": True,
        }
        process = mock.Mock(pid=123)
        with (
            mock.patch("server_manager._restore_system_dll_search"),
            mock.patch("server_manager.subprocess.Popen", return_value=process) as popen,
        ):
            result = server_manager._launch_server_process(settings)

        self.assertIs(result, process)
        self.assertEqual(
            popen.call_args.kwargs["env"]["OPENSSL_ia32cap"], ":~0x20000000"
        )

    def test_managed_world_exit_triggers_automatic_restart(self):
        manager = server_manager.ServerManager.__new__(server_manager.ServerManager)
        manager.starting = False
        manager.stopping = False
        manager.auto_restarting = False
        manager.last_auto_restart_at = 0.0
        manager.status_var = mock.Mock()
        manager.status_label = mock.Mock()
        manager.log = mock.Mock()
        manager._auto_restart_world = mock.Mock()
        manager._saved_process_matches = mock.Mock(side_effect=[False, True])
        runtime = {"server_pid": 101, "backend_pid": 202}

        with (
            mock.patch.object(server_manager, "_read_runtime", return_value=runtime),
            mock.patch.object(server_manager.threading, "Thread") as thread,
        ):
            manager._watch_managed_server()

        self.assertTrue(manager.auto_restarting)
        manager.status_var.set.assert_called_once_with("Restarting world...")
        thread.assert_called_once_with(
            target=manager._auto_restart_world, args=(runtime,), daemon=True
        )
        thread.return_value.start.assert_called_once_with()

    def test_server_log_maps_account_to_character_name(self):
        manager = server_manager.ServerManager.__new__(server_manager.ServerManager)
        manager.character_names = {}

        manager._learn_character_names(
            "LogMarsPlayer: (76561198000000001) Spawn of previous Character "
            "for TestPilot (Login) - Fetching previous inventory and health"
        )

        self.assertEqual(manager.character_names["76561198000000001"], "TestPilot")

    def test_detects_an_occupied_backend_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.assertTrue(server_manager._port_is_listening(listener.getsockname()[1]))

    def test_rejects_generic_response_from_old_backend(self):
        manager = object.__new__(server_manager.ServerManager)
        manager.settings = {"backend_port": 8080, "access_key": "abcd"}
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b'{"result":"ok"}'
        with (
            mock.patch("server_manager.urllib.request.urlopen", return_value=response),
            self.assertRaises(server_manager.IncompatibleBackendError),
        ):
            manager._fetch_status()


class NativeServerTests(unittest.TestCase):
    def test_prepare_uses_compatibility_only(self):
        settings = {
            "server_dir": "C:/server",
            "server_backend_host": "127.0.0.1",
            "backend_port": 8080,
            "access_key": "abcd",
            "skip_cloning": True,
        }
        with mock.patch(
            "native_server.momlib.apply_server_compatibility",
            return_value={"url": "http://127.0.0.1", "config": "server.cfg"},
        ) as apply_compatibility:
            native_server._prepare(settings)

        apply_compatibility.assert_called_once_with(
            "C:/server", "127.0.0.1", 8080, "abcd", skip_cloning=True
        )


if __name__ == "__main__":
    unittest.main()
