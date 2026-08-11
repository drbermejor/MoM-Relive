"""Backend local para Memories of Mars.

Sustituye los servicios AWS que Limbic/505 apagaron. Reimplementa la API que
el juego espera: sesiones (registro y listado de servidores), cuentas, patterns,
achievements, stats y reports.

Uso:
    python backend.py [--host 0.0.0.0] [--port 8080]

El estado se guarda en state.json junto a este fichero, asi que los datos
sobreviven a reinicios.
"""

import argparse
import hmac
import ipaddress
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"
UNKNOWN_LOG = HERE / "unknown_requests.log"
TRACE_LOG = HERE / "requests.log"
ACCESS_KEY = ""
ADVERTISE_HOST = ""

# El servidor envia KeepAlive cada unos 10 segundos. Un margen amplio evita
# falsos positivos durante cargas pesadas y retira anuncios de procesos caidos.
SESSION_TTL = 120.0
MAX_BODY = 2 * 1024 * 1024
STARTED_AT = time.time()

_lock = threading.RLock()


# --------------------------------------------------------------------------
# Estado persistente
# --------------------------------------------------------------------------
def _empty_state():
    return {
        "next_session_id": 1,
        "sessions": {},  # SessionId -> objeto de sesion
        "accounts": {},  # accid -> datos de cuenta
        "patterns": {},  # accid -> [pattern ids]
        "achievements": {},  # accid -> {}
        "stats": {},  # accid -> {}
        "reports": [],
    }


def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            base = _empty_state()
            base.update(data)
            return base
        except (ValueError, OSError) as exc:
            print(f"[!] state.json ilegible ({exc}), empiezo de cero")
    return _empty_state()


STATE = load_state()


def save_state():
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


def prune_sessions():
    """Descarta sesiones cuyo KeepAlive lleva demasiado tiempo sin llegar."""
    now = time.time()
    dead = [
        sid
        for sid, session in STATE["sessions"].items()
        if now - session.get("_last_seen", 0) > SESSION_TTL
    ]
    for sid in dead:
        print(
            f"[-] sesion {sid} caducada ({STATE['sessions'][sid].get('OwningUserName')})"
        )
        del STATE["sessions"][sid]
    return bool(dead)


# --------------------------------------------------------------------------
# Servicios
# --------------------------------------------------------------------------
def create_session(body):
    with _lock:
        sid = str(STATE["next_session_id"])
        STATE["next_session_id"] += 1
        session = dict(body)
        session["_private_ip"] = session.get("IpAddress", "")
        if ADVERTISE_HOST:
            session["IpAddress"] = ADVERTISE_HOST
        session["SessionId"] = sid
        session["_last_seen"] = time.time()
        STATE["sessions"][sid] = session
        save_state()
    name = session.get("OwningUserName", "?")
    addr = f"{session.get('IpAddress')}:{session.get('Port')}"
    print(f"[+] sesion {sid} creada: {name} @ {addr}")
    return public_session(session)


def update_session(body):
    sid = str(body.get("SessionId", "0"))
    with _lock:
        session = STATE["sessions"].get(sid)
        if session is None:
            # El servidor cree tener una sesion que nosotros perdimos: la readoptamos.
            return create_session(body)
        # UpdateSession no reenvia IpAddress/Port, asi que conservamos los previos.
        for key, value in body.items():
            if value not in (None, "", 0) or key not in ("IpAddress", "Port"):
                session[key] = value
        if body.get("IpAddress"):
            session["_private_ip"] = body["IpAddress"]
        session["SessionId"] = sid
        if ADVERTISE_HOST:
            session["IpAddress"] = ADVERTISE_HOST
        session["_last_seen"] = time.time()
        save_state()
    return public_session(session)


def keep_alive(sid):
    with _lock:
        session = STATE["sessions"].get(str(sid))
        if session is None:
            return None
        session["_last_seen"] = time.time()
    return public_session(session)


def destroy_session(sid):
    with _lock:
        session = STATE["sessions"].pop(str(sid), None)
        if session:
            save_state()
            print(f"[-] sesion {sid} destruida")
    return {"result": "ok"}


def all_sessions(req):
    """Lista de servidores para el navegador del cliente.

    El cliente hace GetArrayField("Sessions") sobre la respuesta y NO comprueba
    el nulo: si la clave no existe, revienta con access violation. Por eso la
    lista tiene que ir envuelta en {"Sessions": [...]} y nunca como array pelado.
    """
    with _lock:
        if prune_sessions():
            save_state()
        sessions = []
        try:
            client_ip = ipaddress.ip_address(req.remote_addr)
            local_client = client_ip.is_private or client_ip.is_loopback
        except ValueError:
            local_client = False
        for stored in STATE["sessions"].values():
            session = public_session(stored)
            if local_client and stored.get("_private_ip"):
                session["IpAddress"] = stored["_private_ip"]
            sessions.append(session)
    platform = (req.query.get("platform") or [None])[0]
    build = (req.query.get("build") or [None])[0]
    print(
        f"[?] GetAllSessions platform={platform} build={build} -> {len(sessions)} sesion(es)"
    )
    return {"result": "ok", "Sessions": sessions}


def _player_id(value):
    value = str(value)
    return value.split("_", 1)[-1] if "_" in value else value


def register_players(req, present):
    body = req.json or {}
    sid = str(body.get("SessionId", ""))
    players = [_player_id(value) for value in body.get("Players", [])]
    with _lock:
        session = STATE["sessions"].get(sid)
        if session is None:
            return {"result": "not found"}
        active = session.setdefault("_players", {})
        now = time.time()
        for accid in players:
            if present:
                entry = active.setdefault(accid, {"joined_at": now})
                entry["last_seen"] = now
            else:
                active.pop(accid, None)
        save_state()
    action = "registrados" if present else "retirados"
    print(f"[players] {len(players)} {action} en sesion {sid}: {', '.join(players)}")
    return {"result": "ok"}


def admin_status(req):
    if req.identity != "s":
        return {"result": "forbidden"}
    with _lock:
        if prune_sessions():
            save_state()
        sessions = []
        players = []
        for sid, session in STATE["sessions"].items():
            server_name = session.get("OwningUserName", "Servidor")
            active = session.get("_players", {})
            sessions.append(
                {
                    "session_id": sid,
                    "name": server_name,
                    "address": session.get("IpAddress", ""),
                    "port": session.get("Port", 0),
                    "players": len(active),
                    "last_seen": session.get("_last_seen", 0),
                }
            )
            for accid, info in active.items():
                account = STATE["accounts"].get(accid, {})
                players.append(
                    {
                        "account_id": accid,
                        "name": account.get("name", f"Player_{accid[-6:]}"),
                        "session_id": sid,
                        "server": server_name,
                        "joined_at": info.get("joined_at", 0),
                    }
                )
    return {
        "result": "ok",
        "api_version": 1,
        "uptime": max(0, time.time() - STARTED_AT),
        "sessions": sessions,
        "players": players,
    }


def public_session(session):
    """Copia sin los campos internos (los que empiezan por _)."""
    return {k: v for k, v in session.items() if not k.startswith("_")}


def account_for(accid):
    accid = str(accid)
    with _lock:
        acc = STATE["accounts"].get(accid)
        if acc is None:
            acc = {"accid": accid, "name": f"Player_{accid[-6:]}", "platformdata": {}}
            STATE["accounts"][accid] = acc
            save_state()
            print(f"[+] cuenta nueva: {accid}")
        return acc


# --------------------------------------------------------------------------
# Enrutado
# --------------------------------------------------------------------------
class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler):
        self.routes.append((method, re.compile(pattern + r"$", re.IGNORECASE), handler))

    def match(self, method, path):
        for m, rx, handler in self.routes:
            if m in (method, "*"):
                hit = rx.match(path)
                if hit:
                    return handler, hit.groupdict()
        return None, None


R = Router()

# --- Sesiones (el servicio critico: sin esto el servidor dedicado no arranca)
R.add("POST", r"/CreateSession", lambda req: create_session(req.json))
R.add("PATCH", r"/UpdateSession", lambda req: update_session(req.json))
R.add(
    "PATCH",
    r"/KeepAliveSession/(?P<sid>[^/]+)",
    lambda req: keep_alive(req.args["sid"]),
)
R.add(
    "DELETE",
    r"/DestroySession/(?P<sid>[^/]+)",
    lambda req: destroy_session(req.args["sid"]),
)
R.add("*", r"/GetAllSessions", all_sessions)
R.add("*", r"/RegisterPlayers", lambda req: register_players(req, True))
R.add("*", r"/UnregisterPlayers", lambda req: register_players(req, False))
R.add("GET", r"/AdminStatus", admin_status)

# --- Cuentas y autenticacion
R.add("*", r"/Login", lambda req: login(req))
R.add("*", r"/CreateAccount", lambda req: login(req))
R.add("*", r"/DeleteAccount", lambda req: {"result": "ok"})
R.add("*", r"/Logout(?:/(?P<rest>.*))?", lambda req: {"result": "ok"})
R.add("*", r"/GetPlayerData", lambda req: get_player_data(req))
R.add(
    "*",
    r"/GenerateAuthTicket(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "ticket": "offline-ticket"},
)  # campo: ticket
R.add(
    "*",
    r"/ValidateAuthTicket(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "ticket": "offline-ticket", "message": ""},
)
R.add(
    "*",
    r"/GenerateEncryptionKey(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "encryption_key": "0" * 32},
)
R.add(
    "*",
    r"/RequestEncryptionKey(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "encryption_key": "0" * 32},
)
R.add("*", r"/UpdateData(?:/(?P<rest>.*))?", lambda req: {"result": "ok"})

# --- Patterns (planos desbloqueables)
R.add("*", r"/GetPatternDefinitions", lambda req: {"result": []})
R.add(
    "*",
    r"/GetUnlockedPatterns/(?P<accid>[^/]+)",
    lambda req: unlocked_patterns(req.account_id or req.args["accid"]),
)
R.add("*", r"/UnlockPattern", lambda req: unlock_pattern(req))
R.add("*", r"/UnlockPatternWithCode", lambda req: unlock_pattern(req))

# --- Achievements / stats / reports (no criticos: el juego tolera fallos aqui)
R.add("*", r"/Achievements(?:/(?P<rest>.*))?", lambda req: {"result": "ok", "data": {}})
R.add(
    "*",
    r"/PendingAchievements(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "data": {}},
)
R.add(
    "*",
    r"/ClearAchievements(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "clearedAchievements": []},
)
R.add(
    "*",
    r"/GetStats(?:/(?P<rest>.*))?",
    lambda req: {"result": "ok", "stats": [], "entries": []},
)
R.add("*", r"/SendReport", lambda req: store_report(req))


def login(req):
    """Login del cliente: {"authtype":"steam","steamaccid":..,"steamticket":..}

    El cliente exige exactamente dos campos string en la respuesta, "accid" y
    "logintoken"; si falta cualquiera de los dos aborta con BadResponseBody
    ("Respuesta inesperada de DataService"). El logintoken es el que despues
    viaja en la cabecera Authorization: Limbic <token>.
    """
    body = req.json or {}
    accid = str(
        req.account_id
        or body.get("steamaccid")
        or body.get("accid")
        or body.get("AccID")
        or "offline"
    )
    acc = account_for(accid)
    return {
        "result": "ok",
        "message": "",
        "accid": acc["accid"],
        "logintoken": f"tok{accid}",
        "displayname": acc["name"],
    }


def get_player_data(req):
    """GetPlayerData?accids=a,b&attribs=displayname,...

    Los atributos usan el vocabulario del servicio de cuentas ("displayname",
    no "name"). Devolvemos la lista bajo varias claves porque aun no esta
    confirmado cual lee el cliente.
    """
    raw = req.query.get("accids") or req.form.get("accids") or []
    ids = [i for chunk in raw for i in chunk.split(",") if i]
    players = [
        {
            "accid": a["accid"],
            "name": a["name"],
            "displayname": a["name"],
            "platformdata": a.get("platformdata", {}),
        }
        for a in (account_for(i) for i in ids)
    ]
    # El cliente pide attribs=name,platformdata, asi que esos son los nombres
    # buenos. Por el patron del resto de la API "result" es el sobre; aun no
    # esta confirmado si dentro espera un objeto o una lista.
    return {
        "result": players[0] if len(players) == 1 else players,
        "message": "",
        "players": players,
        "data": players,
    }


def unlocked_patterns(accid):
    """ "result" es un OBJETO (no un array) con "accid" y "pids" dentro.

    Verificado en el desensamblado: el juego hace GetObjectField("result") y
    despues TryGetStringField("accid") sobre ese objeto; si cualquiera de los
    dos falla aborta con "[PatternUnlockManager]: Failed to deserialize".
    """
    with _lock:
        pids = STATE["patterns"].get(str(accid), [])
    return {"result": {"accid": str(accid), "pids": pids}}


def unlock_pattern(req):
    """Los pids son numericos (el cliente los formatea con %llu)."""
    body = req.json or {}
    accid = str(req.account_id or body.get("accid", "offline"))
    incoming = body.get("pids") or [body.get("pid") or body.get("code")]
    with _lock:
        owned = STATE["patterns"].setdefault(accid, [])
        for pid in incoming:
            if pid is not None and pid not in owned:
                owned.append(pid)
        save_state()
    return unlocked_patterns(accid)


def store_report(req):
    with _lock:
        STATE["reports"].append({"at": time.time(), "body": req.json})
        save_state()
    return {"result": "ok"}


# --------------------------------------------------------------------------
# Servidor HTTP
# --------------------------------------------------------------------------
class Request:
    def __init__(
        self,
        method,
        path,
        query,
        headers,
        body,
        args,
        account_id=None,
        identity=None,
        remote_addr="",
    ):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.raw = body
        self.args = args
        # Lo fija el prefijo /r/<clave>/<id>/. Es la identidad manual elegida
        # en el instalador y prevalece sobre el Steam ID enviado por el juego.
        self.account_id = account_id
        self.identity = identity
        self.remote_addr = remote_addr
        self.json = {}
        self.form = {}
        text = body.decode("utf-8", "replace") if body else ""
        if text.strip().startswith(("{", "[")):
            try:
                self.json = json.loads(text)
            except ValueError:
                pass
        elif text:
            self.form = parse_qs(text)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MoMBackend/1.0"

    def _dispatch(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            self._send_json(400, {"result": "invalid content length"})
            return
        if length > MAX_BODY:
            self.close_connection = True
            self._send_json(413, {"result": "request too large"})
            return
        body = self.rfile.read(length) if length else b""

        if path == "/health":
            self._send_json(200, {"result": "ok", "service": "MoMBackend/2.0"})
            return

        account_id = None
        prefixed = re.match(r"^/r/([^/]+)/([^/]+)(/.*)$", path)
        if prefixed:
            supplied_key, identity, path = prefixed.groups()
            if ACCESS_KEY and not hmac.compare_digest(supplied_key, ACCESS_KEY):
                self._send_json(403, {"result": "forbidden"})
                return
            if identity not in ("s", "p"):
                if not re.fullmatch(r"[0-9]{1,20}", identity):
                    self._send_json(400, {"result": "invalid account id"})
                    return
                account_id = identity
        elif ACCESS_KEY:
            self._send_json(403, {"result": "forbidden"})
            return

        handler, args = R.match(self.command, path)
        if handler is None:
            self._log_unknown(path, body)
            payload = {"result": "ok"}
            status = 200
        else:
            req = Request(
                self.command,
                path,
                query,
                self.headers,
                body,
                args or {},
                account_id,
                identity if prefixed else None,
                self.client_address[0],
            )
            try:
                payload = handler(req)
                status = 200 if payload is not None else 404
                if payload is None:
                    payload = {"result": "not found"}
            except Exception as exc:  # noqa: BLE001 - una ruta no debe tumbar el servicio
                print(f"[!] error en {path}: {exc!r}")
                payload = {"result": "error", "error": str(exc)}
                status = 500

        data = json.dumps(payload).encode("utf-8")
        self._trace(path, body, status, data)
        self._send_data(status, data)

    def _send_json(self, status, payload):
        self._send_data(status, json.dumps(payload).encode("utf-8"))

    def _send_data(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _trace(self, path, body, status, response):
        """Traza completa peticion/respuesta: es como se descubre que espera el juego."""
        line = [f"{time.strftime('%H:%M:%S')} {self.command} {self.path} -> {status}"]
        auth = self.headers.get("Authorization")
        if auth:
            line.append(f"    auth: {auth}")
        if body:
            line.append(f"    req:  {body.decode('utf-8', 'replace')[:1200]}")
        line.append(f"    resp: {response.decode('utf-8')[:600]}")
        text = "\n".join(line) + "\n"
        print(text, end="", flush=True)
        with open(TRACE_LOG, "a", encoding="utf-8") as fh:
            fh.write(text)

    def _log_unknown(self, path, body):
        """Toda ruta desconocida queda registrada: asi se descubre lo que falta."""
        print(f"[?] RUTA DESCONOCIDA {self.command} {path}")
        with open(UNKNOWN_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {self.command} {path}\n")
            if body:
                fh.write(f"    {body.decode('utf-8', 'replace')}\n")

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _dispatch

    def log_message(self, *args):
        pass  # silenciamos el log por defecto; ya imprimimos lo relevante

    def handle_one_request(self):
        # El juego corta conexiones keep-alive sin avisar; no es un error.
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True


def run_server(
    host="0.0.0.0",
    port=8080,
    access_key="",
    data_dir=None,
    advertise_host="",
):
    global ACCESS_KEY, ADVERTISE_HOST, STATE_FILE, UNKNOWN_LOG, TRACE_LOG, STATE
    ACCESS_KEY = access_key
    ADVERTISE_HOST = str(advertise_host or "").strip()
    if data_dir:
        data_dir = Path(data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        STATE_FILE = data_dir / "state.json"
        UNKNOWN_LOG = data_dir / "unknown_requests.log"
        TRACE_LOG = data_dir / "requests.log"
        STATE = load_state()

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Backend de Memories of Mars escuchando en http://{host}:{port}/")
    print(f"Estado: {STATE_FILE}")
    if ADVERTISE_HOST:
        print(f"Direccion anunciada: {ADVERTISE_HOST}")
    print(f"Sesiones cargadas: {len(STATE['sessions'])}")
    print("Acceso protegido por clave.\n" if access_key else "Modo legado sin clave.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nParando.")
    finally:
        save_state()
        srv.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backend local de Memories of Mars")
    ap.add_argument(
        "--host",
        default="0.0.0.0",
        help="0.0.0.0 para que otros jugadores de la LAN lo alcancen",
    )
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument(
        "--access-key",
        default="",
        help="key included in client and server backend URLs",
    )
    ap.add_argument("--data-dir", help="writable folder for state and logs")
    ap.add_argument(
        "--advertise-host",
        default="",
        help="IP publica o DNS que se entrega a los clientes en el navegador",
    )
    opts = ap.parse_args(argv)
    run_server(
        opts.host,
        opts.port,
        opts.access_key,
        opts.data_dir,
        opts.advertise_host,
    )


if __name__ == "__main__":
    main()
