"""
API de contrôle d'accès par carte - Serveur principal
"""

import contextlib
import json
import logging
import logging.handlers
import re
import socket
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# ─── Configuration ────────────────────────────────────────────────────────────

HOST             = "0.0.0.0"
PORT             = 8000
BASE_DIR         = Path(__file__).parent
DB_PATH          = BASE_DIR / "access_control.db"
LOG_PATH         = BASE_DIR / "access_control.log"
LOG_MAX_BYTES    = 50 * 1024 * 1024  # 50 Mo
LOG_BACKUP_COUNT = 3                  # 3 fichiers de rotation


# ─── Logging ─────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """
    Configure le logger avec :
    - un RotatingFileHandler (max 50 Mo, 3 fichiers de rotation)
    - un StreamHandler vers stdout
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger = logging.getLogger("access_control")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False  # Evite la double emission vers le logger racine
    return logger


log = setup_logging()


# ─── Support REGEXP dans SQLite ───────────────────────────────────────────────

def _regexp(pattern: str, value: str) -> bool:
    try:
        return bool(re.search(pattern, str(value)))
    except re.error:
        return False


def get_db() -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec le support REGEXP et row_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, _regexp)
    return conn


def init_db() -> None:
    """Crée les tables si elles n'existent pas encore."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                id      TEXT    PRIMARY KEY,
                level   INTEGER NOT NULL DEFAULT 1,
                owner   TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS cardReaders (
                id      TEXT    PRIMARY KEY,
                level   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                cardId       TEXT    NOT NULL,
                cardReaderId TEXT    NOT NULL,
                date         TEXT    NOT NULL,
                levelInScan  INTEGER NOT NULL
            );
        """)
    log.info("Base de donnees initialisee : %s", DB_PATH)


# ─── Helpers génériques ───────────────────────────────────────────────────────

def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_int(value, default: int) -> int:
    """Convertit value en entier, retourne default en cas d'échec."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ─── Helpers HTTP ─────────────────────────────────────────────────────────────

def json_response(handler: BaseHTTPRequestHandler, status: int, data) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if isinstance(handler, Handler):
        handler._send_cors()
    handler.end_headers()
    handler.wfile.write(body)


def http_error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    json_response(handler, status, {"error": message})


def parse_body(handler: BaseHTTPRequestHandler) -> dict:
    length = safe_int(handler.headers.get("Content-Length", 0), 0)
    if length <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(length))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ─── Logique métier ───────────────────────────────────────────────────────────

def check_card(card_id: str, reader_id: str) -> tuple[bool, int]:
    """
    Vérifie si card_id est autorisée sur reader_id.
    Enregistre l'événement en base et dans les logs.
    Retourne (valid, level_in_scan).
    """
    with get_db() as conn:
        card   = row_to_dict(conn.execute("SELECT * FROM cards       WHERE id=?", (card_id,)).fetchone())
        reader = row_to_dict(conn.execute("SELECT * FROM cardReaders WHERE id=?", (reader_id,)).fetchone())

        level_in_scan = card["level"] if card else 0
        valid = bool(card and reader and card["level"] >= reader["level"])

        conn.execute(
            "INSERT INTO logs (cardId, cardReaderId, date, levelInScan) VALUES (?,?,?,?)",
            (card_id, reader_id, utc_now_iso(), level_in_scan),
        )

    status_label = "ACCES ACCORDE" if valid else "ACCES REFUSE"
    log.info("[SCAN] card=%s reader=%s level=%d -> %s", card_id, reader_id, level_in_scan, status_label)

    return valid, level_in_scan


# ─── Routeur HTTP ─────────────────────────────────────────────────────────────

# Format : (METHOD, pattern, handler_method_name)
# Les routes exactes doivent être déclarées AVANT les routes avec captures.
ROUTES: list[tuple[str, str, str]] = [
    # Cards
    ("POST",   "/admin/cards",             "card_create"),
    ("GET",    "/admin/cards",             "card_list"),
    ("GET",    r"/admin/cards/([^/]+)",    "card_get"),
    ("PUT",    r"/admin/cards/([^/]+)",    "card_update"),
    ("DELETE", r"/admin/cards/([^/]+)",    "card_delete"),
    # CardReaders
    ("POST",   "/admin/readers",           "reader_create"),
    ("GET",    "/admin/readers",           "reader_list"),
    ("GET",    r"/admin/readers/([^/]+)",  "reader_get"),
    ("PUT",    r"/admin/readers/([^/]+)",  "reader_update"),
    ("DELETE", r"/admin/readers/([^/]+)",  "reader_delete"),
    # Logs — route exacte avant la route avec capture
    ("GET",    "/admin/logs",              "logs_list"),
    ("DELETE", "/admin/logs",              "logs_delete_all"),
    ("DELETE", r"/admin/logs/([^/]+)",     "logs_delete_one"),
    # Check
    ("POST",   "/check",                   "check"),
]

# Pré-compilation des patterns regex pour la performance
_COMPILED_ROUTES = [
    (method, re.compile(pattern + "$"), name)
    for method, pattern, name in ROUTES
]


class Handler(BaseHTTPRequestHandler):

    # Silence le logger interne de BaseHTTPRequestHandler
    def log_message(self, fmt, *args) -> None:  # noqa: N802
        pass

    # ── CORS ──────────────────────────────────────────────────────────────
    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path.rstrip("/")
        qs   = parse_qs(urlparse(self.path).query)

        for route_method, pattern, handler_name in _COMPILED_ROUTES:
            if route_method != method:
                continue
            match = pattern.fullmatch(path)
            if match:
                getattr(self, handler_name)(qs, match.groups())
                return

        http_error(self, 404, "Route introuvable")

    def do_GET(self):    self._dispatch("GET")     # noqa: N802
    def do_POST(self):   self._dispatch("POST")    # noqa: N802
    def do_PUT(self):    self._dispatch("PUT")     # noqa: N802
    def do_DELETE(self): self._dispatch("DELETE")  # noqa: N802

    # ── Cards ─────────────────────────────────────────────────────────────────

    def card_create(self, qs: dict, groups: tuple) -> None:
        body  = parse_body(self)
        cid   = body.get("id", "").strip()
        if not cid:
            return http_error(self, 400, "Champ 'id' requis")

        level = safe_int(body.get("level", 1), 1)
        owner = str(body.get("owner", ""))

        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO cards (id, level, owner) VALUES (?,?,?)",
                    (cid, level, owner),
                )
            json_response(self, 201, {"id": cid, "level": level, "owner": owner})
        except sqlite3.IntegrityError:
            http_error(self, 409, f"Carte '{cid}' existe deja")

    def card_list(self, qs: dict, groups: tuple) -> None:
        pattern = qs.get("q", [None])[0]
        with get_db() as conn:
            if pattern:
                rows = conn.execute("SELECT * FROM cards WHERE id REGEXP ?", (pattern,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM cards").fetchall()
        json_response(self, 200, rows_to_list(rows))

    def card_get(self, qs: dict, groups: tuple) -> None:
        cid = groups[0]
        with get_db() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()
        if row is None:
            return http_error(self, 404, "Carte introuvable")
        json_response(self, 200, row_to_dict(row))

    def card_update(self, qs: dict, groups: tuple) -> None:
        """
        Met à jour une carte, y compris son id si le champ 'id' du body diffère.
        Le renommage d'id est effectué en une seule transaction (INSERT + DELETE).
        """
        old_id = groups[0]
        body   = parse_body(self)

        with get_db() as conn:
            row = row_to_dict(conn.execute("SELECT * FROM cards WHERE id=?", (old_id,)).fetchone())
            if row is None:
                return http_error(self, 404, "Carte introuvable")

            new_id = body.get("id", old_id).strip() or old_id
            level  = safe_int(body.get("level", row["level"]), row["level"])
            owner  = str(body.get("owner", row["owner"]))

            if new_id != old_id:
                # Renommage de la clé primaire : INSERT puis DELETE dans la même transaction
                try:
                    conn.execute(
                        "INSERT INTO cards (id, level, owner) VALUES (?,?,?)",
                        (new_id, level, owner),
                    )
                except sqlite3.IntegrityError:
                    return http_error(self, 409, f"Carte '{new_id}' existe deja")
                conn.execute("DELETE FROM cards WHERE id=?", (old_id,))
            else:
                conn.execute(
                    "UPDATE cards SET level=?, owner=? WHERE id=?",
                    (level, owner, old_id),
                )

        json_response(self, 200, {"id": new_id, "level": level, "owner": owner})

    def card_delete(self, qs: dict, groups: tuple) -> None:
        cid = groups[0]
        with get_db() as conn:
            deleted = conn.execute("DELETE FROM cards WHERE id=?", (cid,)).rowcount
        if deleted == 0:
            return http_error(self, 404, "Carte introuvable")
        json_response(self, 200, {"deleted": cid})

    # ── CardReaders ───────────────────────────────────────────────────────────

    def reader_create(self, qs: dict, groups: tuple) -> None:
        body  = parse_body(self)
        rid   = body.get("id", "").strip()
        if not rid:
            return http_error(self, 400, "Champ 'id' requis")

        level = safe_int(body.get("level", 1), 1)

        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO cardReaders (id, level) VALUES (?,?)",
                    (rid, level),
                )
            json_response(self, 201, {"id": rid, "level": level})
        except sqlite3.IntegrityError:
            http_error(self, 409, f"Lecteur '{rid}' existe deja")

    def reader_list(self, qs: dict, groups: tuple) -> None:
        pattern = qs.get("q", [None])[0]
        with get_db() as conn:
            if pattern:
                rows = conn.execute("SELECT * FROM cardReaders WHERE id REGEXP ?", (pattern,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM cardReaders").fetchall()
        json_response(self, 200, rows_to_list(rows))

    def reader_get(self, qs: dict, groups: tuple) -> None:
        rid = groups[0]
        with get_db() as conn:
            row = conn.execute("SELECT * FROM cardReaders WHERE id=?", (rid,)).fetchone()
        if row is None:
            return http_error(self, 404, "Lecteur introuvable")
        json_response(self, 200, row_to_dict(row))

    def reader_update(self, qs: dict, groups: tuple) -> None:
        """
        Met à jour un lecteur, y compris son id si le champ 'id' du body diffère.
        Le renommage d'id est effectué en une seule transaction (INSERT + DELETE).
        """
        old_id = groups[0]
        body   = parse_body(self)

        with get_db() as conn:
            row = row_to_dict(conn.execute("SELECT * FROM cardReaders WHERE id=?", (old_id,)).fetchone())
            if row is None:
                return http_error(self, 404, "Lecteur introuvable")

            new_id = body.get("id", old_id).strip() or old_id
            level  = safe_int(body.get("level", row["level"]), row["level"])

            if new_id != old_id:
                try:
                    conn.execute(
                        "INSERT INTO cardReaders (id, level) VALUES (?,?)",
                        (new_id, level),
                    )
                except sqlite3.IntegrityError:
                    return http_error(self, 409, f"Lecteur '{new_id}' existe deja")
                conn.execute("DELETE FROM cardReaders WHERE id=?", (old_id,))
            else:
                conn.execute("UPDATE cardReaders SET level=? WHERE id=?", (level, old_id))

        json_response(self, 200, {"id": new_id, "level": level})

    def reader_delete(self, qs: dict, groups: tuple) -> None:
        rid = groups[0]
        with get_db() as conn:
            deleted = conn.execute("DELETE FROM cardReaders WHERE id=?", (rid,)).rowcount
        if deleted == 0:
            return http_error(self, 404, "Lecteur introuvable")
        json_response(self, 200, {"deleted": rid})

    # ── Logs ──────────────────────────────────────────────────────────────────

    def logs_list(self, qs: dict, groups: tuple) -> None:
        card_filter   = qs.get("card",   [None])[0]
        reader_filter = qs.get("reader", [None])[0]
        limit         = qs.get("limit",  [None])[0]

        sql    = "SELECT * FROM logs WHERE 1=1"
        params: list = []

        if card_filter:
            sql += " AND cardId REGEXP ?"
            params.append(card_filter)
        if reader_filter:
            sql += " AND cardReaderId REGEXP ?"
            params.append(reader_filter)

        sql += " ORDER BY id DESC"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(safe_int(limit, 100))

        with get_db() as conn:
            rows = conn.execute(sql, params).fetchall()
        json_response(self, 200, rows_to_list(rows))

    def logs_delete_all(self, qs: dict, groups: tuple) -> None:
        """Supprime tous les logs de la base."""
        with get_db() as conn:
            deleted = conn.execute("DELETE FROM logs").rowcount
        log.info("[ADMIN] Tous les logs supprimes (%d lignes)", deleted)
        json_response(self, 200, {"deleted": deleted})

    def logs_delete_one(self, qs: dict, groups: tuple) -> None:
        """Supprime un log par son id numérique."""
        log_id = safe_int(groups[0], -1)
        if log_id < 0:
            return http_error(self, 400, "ID de log invalide")
        with get_db() as conn:
            deleted = conn.execute("DELETE FROM logs WHERE id=?", (log_id,)).rowcount
        if deleted == 0:
            return http_error(self, 404, "Log introuvable")
        log.info("[ADMIN] Log #%d supprime", log_id)
        json_response(self, 200, {"deleted": log_id})

    # ── Check ─────────────────────────────────────────────────────────────────

    def check(self, qs: dict, groups: tuple) -> None:
        body      = parse_body(self)
        card_id   = body.get("cardId",   "").strip()
        reader_id = body.get("readerId", "").strip()

        if not card_id or not reader_id:
            return http_error(self, 400, "Champs 'cardId' et 'readerId' requis")

        valid, _ = check_card(card_id, reader_id)
        json_response(self, 200, {"valid": valid})


# ─── Point d'entrée ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    server   = HTTPServer((HOST, PORT), Handler)
    local_ip = socket.gethostbyname(socket.gethostname())

    log.info("Serveur d'acces demarre")
    log.info("  Local  -> http://localhost:%d", PORT)
    log.info("  Reseau -> http://%s:%d", local_ip, PORT)
    log.info("  Logs   -> %s", LOG_PATH)

    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()

    log.info("Arret du serveur")