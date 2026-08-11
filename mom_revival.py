"""Memories of Mars Revival client configurator and launcher."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import momlib
import redirect_urls
import ui_helpers
from version import __version__


def bundled_launcher() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("MoMClientLauncher.exe")
    return Path(__file__).resolve().parent / "dist" / "MoMClientLauncher.exe"


class ClientApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title(f"MoM Relive - Client {__version__}")
        self.root.geometry("840x720")
        self.root.minsize(680, 520)
        self.closing = False
        self.settings = momlib.load_settings()
        legacy_host = self.settings.get("backend_host", "127.0.0.1")
        self.settings.setdefault("client_backend_host", legacy_host or "127.0.0.1")
        self.vars = {
            "client_dir": tk.StringVar(value=str(self.settings.get("client_dir", ""))),
            "client_backend_host": tk.StringVar(
                value=str(self.settings.get("client_backend_host", "127.0.0.1"))
            ),
            "backend_port": tk.StringVar(
                value=str(self.settings.get("backend_port", 8080))
            ),
            "access_key": tk.StringVar(value=str(self.settings.get("access_key", ""))),
            "account_id": tk.StringVar(value=str(self.settings.get("account_id", ""))),
            "limit_client_cpu": tk.BooleanVar(
                value=bool(self.settings.get("limit_client_cpu", True))
            ),
            "openssl_compat": tk.BooleanVar(
                value=bool(self.settings.get("openssl_compat", False))
            ),
        }
        self.patch_status_var = tk.StringVar(value="Checking patch...")
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log(
            "Ready. Prepare installs EAC-free access and redirects the client to the Relive backend."
        )
        self.root.after(150, self.show_patch_status)

    def _build(self):
        ttk = self.ttk
        style = ttk.Style(self.root)
        style.configure(
            "ClientReady.TLabel",
            foreground="#12823b",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "ClientWarning.TLabel",
            foreground="#9a6700",
            font=("Segoe UI", 10, "bold"),
        )

        host = ttk.Frame(self.root)
        host.pack(fill="both", expand=True)
        canvas = self.tk.Canvas(host, highlightthickness=0)
        scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(canvas, padding=14)
        window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        canvas.bind_all(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(
            header, text="Memories of Mars Client", font=("Segoe UI", 16, "bold")
        ).pack(side="left")
        self.patch_status_label = ttk.Label(
            header,
            textvariable=self.patch_status_var,
            style="ClientWarning.TLabel",
        )
        self.patch_status_label.pack(side="right")
        ttk.Label(
            outer,
            text=(
                "Prepare this installation to connect to a Relive server. "
                "The dedicated server is managed in its separate application."
            ),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(3, 10))

        game = ttk.LabelFrame(outer, text="1. Game installation", padding=10)
        game.pack(fill="x")
        self._field(
            game,
            0,
            "Memories of Mars folder",
            "client_dir",
            browse=True,
            help_text="Root folder installed by Steam; it contains Launch_Game.exe.",
        )

        connection = ttk.LabelFrame(
            outer, text="2. Server connection", padding=10
        )
        connection.pack(fill="x", pady=(9, 0))
        self._field(
            connection,
            0,
            "Backend IP or hostname",
            "client_backend_host",
            help_text="Use 127.0.0.1 on the host, or its public IP/DNS from another PC.",
        )
        self._field(
            connection,
            1,
            "Backend port",
            "backend_port",
            width=10,
            help_text="Backend TCP port; it must match the server configuration.",
        )
        self._field(
            connection,
            2,
            "Shared key",
            "access_key",
            width=22,
            help_text="Key protecting the backend; it must match exactly.",
        )
        ttk.Label(
            connection,
            text="The server administrator must give you these three values.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        identity = ttk.LabelFrame(outer, text="3. Player identity", padding=10)
        identity.pack(fill="x", pady=(9, 0))
        self._field(
            identity,
            0,
            "Account ID",
            "account_id",
            width=24,
            help_text="Leave blank to preserve the current identity. A different ID selects different progress.",
        )
        generate = ttk.Button(
            identity, text="Generate ID", command=self.generate_account_id
        )
        generate.grid(row=0, column=2, padx=(7, 0))
        ui_helpers.ToolTip(
            generate,
            "Creates a random ID. Save it and always use the same one for that character.",
        )
        ttk.Label(
            identity,
            text=(
                "Blank preserves the installed ID. Every player needs a different one; "
                "the same ID always restores the same character."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

        compatibility = ttk.LabelFrame(
            outer, text="Modern PC compatibility", padding=10
        )
        compatibility.pack(fill="x", pady=(9, 0))
        cpu_check = ttk.Checkbutton(
            compatibility,
            text="Temporarily limit CPU during loading (recommended)",
            variable=self.vars["limit_client_cpu"],
        )
        cpu_check.pack(anchor="w")
        ui_helpers.ToolTip(
            cpu_check,
            "Prevents an Unreal Engine crash on high-thread-count CPUs, then restores all cores.",
        )
        ssl_check = ttk.Checkbutton(
            compatibility,
            text="Legacy OpenSSL compatibility (only if the game closes while loading)",
            variable=self.vars["openssl_compat"],
        )
        ssl_check.pack(anchor="w", pady=(4, 0))
        ui_helpers.ToolTip(
            ssl_check,
            "Enables the legacy cryptographic compatibility required by some modern processors.",
        )

        actions = ttk.LabelFrame(outer, text="Actions", padding=8)
        actions.pack(fill="x", pady=(9, 8))
        self._action_button(
            actions,
            "Prepare / repair",
            self.apply_client,
            "Applies the reversible patch and installs the Relive launcher instead of EAC.",
        ).pack(side="left")
        self._action_button(
            actions,
            "Play without EAC",
            self.launch_client,
            "Repairs when needed and starts the game directly with -NoEAC.",
        ).pack(side="left", padx=7)
        self._action_button(
            actions,
            "Test connection",
            self.test_connection,
            "Checks the shared key, port, and servers advertised by the backend.",
        ).pack(side="left")
        self._action_button(
            actions,
            "Restore official files",
            self.restore_client,
            "Restores official executables and enables the EAC launcher again.",
        ).pack(side="right")

        activity = ttk.LabelFrame(outer, text="Activity", padding=6)
        activity.pack(fill="both", expand=True, pady=(0, 4))
        self.log_box = self.tk.Text(activity, height=7, state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(
            activity, orient="vertical", command=self.log_box.yview
        )
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _action_button(self, parent, text, command, help_text):
        button = self.ttk.Button(parent, text=text, command=command)
        ui_helpers.ToolTip(button, help_text)
        return button

    def _field(
        self, parent, row, label, key, width=48, browse=False, help_text=""
    ):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        entry = ttk.Entry(parent, textvariable=self.vars[key], width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)
        if help_text:
            ui_helpers.ToolTip(entry, help_text)
        if browse:
            button = ttk.Button(parent, text="Browse...", command=self.browse)
            button.grid(row=row, column=2, padx=(7, 0))
            ui_helpers.ToolTip(button, "Select the game's root folder.")
        return entry

    def browse(self):
        from tkinter import filedialog

        value = filedialog.askdirectory(
            initialdir=self.vars["client_dir"].get() or None, parent=self.root
        )
        if value:
            self.vars["client_dir"].set(value)
            self.show_patch_status(log_result=False)

    def generate_account_id(self):
        account_id = momlib.generate_account_id()
        self.vars["account_id"].set(account_id)
        self.log(f"Generated ID: {account_id}. Save it to preserve your progress.")

    def show_patch_status(self, log_result=True):
        client_dir = self.vars["client_dir"].get().strip()
        active = bool(client_dir) and momlib.client_launcher_is_installed(client_dir)
        if active:
            self.patch_status_var.set("Ready · EAC-free")
            self.patch_status_label.configure(style="ClientReady.TLabel")
            if log_result:
                self.log("Status: Relive launcher active; Steam will not start EAC.")
        else:
            self.patch_status_var.set("Preparation required")
            self.patch_status_label.configure(style="ClientWarning.TLabel")
            if log_result:
                self.log(
                    "WARNING: Steam restored the launcher or the client needs preparation."
                )

    def save(self) -> dict:
        values = dict(self.settings)
        values.update({key: var.get() for key, var in self.vars.items()})
        values["backend_port"] = momlib.validate_port(values["backend_port"])
        values["access_key"] = momlib.validate_key(values["access_key"])
        values["client_backend_host"] = str(values["client_backend_host"]).strip()
        if not values["client_backend_host"]:
            raise momlib.ConfigError("Enter the backend IP address or hostname")
        momlib.save_settings(values)
        self.settings = values
        return values

    def _apply(self, settings: dict) -> dict:
        return momlib.apply_client(
            settings["client_dir"],
            settings["client_backend_host"],
            settings["backend_port"],
            settings["access_key"],
            settings["account_id"],
            launcher_source=bundled_launcher(),
        )

    def apply_client(self):
        try:
            result = self._apply(self.save())
            self.show_patch_status(log_result=False)
            self.log(f"Client prepared successfully: {result['url']}")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Prepare client", exc)

    def launch_client(self):
        try:
            settings = self.save()
            self._apply(settings)
            launcher = Path(settings["client_dir"]) / momlib.CLIENT_LAUNCHER_REL
            subprocess.Popen([str(launcher)], cwd=str(launcher.parent))
            self.show_patch_status(log_result=False)
            self.log("Game started through the Relive launcher (without EAC).")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Start game", exc)

    def test_connection(self):
        try:
            settings = self.save()
            identity = momlib.existing_client_identity(momlib.client_engine_ini())
            base = momlib.backend_url(
                settings["client_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                identity,
            )
        except (ValueError, OSError) as exc:
            self.error("Test connection", exc)
            return
        self.log("Testing the backend connection...")

        def worker():
            try:
                with urllib.request.urlopen(base + "GetAllSessions", timeout=4) as response:
                    data = json.load(response)
                sessions = data.get("Sessions")
                if not isinstance(sessions, list):
                    raise ValueError("the response is not from a compatible Relive backend")
                message = f"Connection successful: {len(sessions)} advertised server(s)."
            except (OSError, ValueError, urllib.error.HTTPError) as exc:
                message = f"CONNECTION ERROR: {exc}"
            try:
                if not self.closing:
                    self.root.after(0, self.log, message)
            except (RuntimeError, self.tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def restore_client(self):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Restore client",
            "The original executable and Steam EAC launcher will be restored. Continue?",
            parent=self.root,
        ):
            return
        try:
            settings = self.save()
            result = momlib.restore_client(settings["client_dir"])
            if not result["binary_restored"] or not result["launcher_restored"]:
                raise momlib.ConfigError(
                    "An original backup is missing. Use Verify integrity in Steam to complete restoration."
                )
            self.show_patch_status(log_result=False)
            self.log("Client restored: Steam will start the official EAC launcher again.")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Restore client", exc)

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{stamp}  {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def error(self, title, error):
        from tkinter import messagebox

        self.log(f"ERROR: {error}")
        messagebox.showerror(title, str(error), parent=self.root)

    def on_close(self):
        self.closing = True
        self.root.unbind_all("<MouseWheel>")
        self.root.destroy()


def gui_main() -> int:
    import tkinter as tk

    root = tk.Tk()
    ClientApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(gui_main())
