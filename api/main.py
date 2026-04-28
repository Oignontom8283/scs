"""
API de contrôle d'accès par carte - Serveur principal
"""

import sqlite3
import re
import json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import logging

DB_PATH = "access_control.db"

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


# ─── Base de données ─────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS cards (
            id      TEXT PRIMARY KEY,
            level   INTEGER NOT NULL DEFAULT 1,
            owner   TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS cardReaders (
            id      TEXT PRIMARY KEY,
            level   INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            cardId        TEXT    NOT NULL,
            cardReaderId  TEXT    NOT NULL,
            date          TEXT    NOT NULL,
            levelInScan   INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    log.info("Base de données initialisée : %s", DB_PATH)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


def json_response(handler, status, data):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", len(body))
    handler.end_headers()
    handler.wfile.write(body)


def error(handler, status, msg):
    json_response(handler, status, {"error": msg})


def parse_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except Exception:
        return {}


# ─── Logique métier ──────────────────────────────────────────────────────────
def check_card(card_id, reader_id):
    """
    Vérifie si la carte card_id est autorisée sur le lecteur reader_id.
    - Logue l'événement en base et dans les logs système.
    - Retourne (valid: bool, level_in_scan: int)
    """
    conn = get_db()
    cur = conn.cursor()

    card   = row_to_dict(cur.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone())
    reader = row_to_dict(cur.execute("SELECT * FROM cardReaders WHERE id=?", (reader_id,)).fetchone())

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    if card is None or reader is None:
        level_in_scan = card["level"] if card else 0
        valid = False
    else:
        level_in_scan = card["level"]
        valid = card["level"] >= reader["level"]

    # Enregistrement en base
    cur.execute(
        "INSERT INTO logs (cardId, cardReaderId, date, levelInScan) VALUES (?,?,?,?)",
        (card_id, reader_id, now, level_in_scan)
    )
    conn.commit()
    conn.close()

    # Log console
    status_str = "ACCÈS ACCORDÉ" if valid else "ACCÈS REFUSÉ"
    log.info("[SCAN] card=%s reader=%s level=%d → %s", card_id, reader_id, level_in_scan, status_str)

    return valid, level_in_scan


# ─── Routeur ─────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # On gère nos propres logs

    def route(self, method):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        qs     = parse_qs(parsed.query)

        routes = [
            # Cards
            ("POST",   "/admin/cards",          self.card_create),
            ("GET",    "/admin/cards",           self.card_list),
            ("GET",    r"/admin/cards/([^/]+)",  self.card_get),
            ("PUT",    r"/admin/cards/([^/]+)",  self.card_update),
            ("DELETE", r"/admin/cards/([^/]+)",  self.card_delete),
            # CardReaders
            ("POST",   "/admin/readers",         self.reader_create),
            ("GET",    "/admin/readers",          self.reader_list),
            ("GET",    r"/admin/readers/([^/]+)", self.reader_get),
            ("PUT",    r"/admin/readers/([^/]+)", self.reader_update),
            ("DELETE", r"/admin/readers/([^/]+)", self.reader_delete),
            # Logs
            ("GET",    "/admin/logs",            self.logs_list),
            # Check
            ("POST",   "/check",                 self.check),
        ]

        for m, pattern, handler_fn in routes:
            if m != method:
                continue
            # Correspondance exacte ou regex
            if pattern.startswith("r\"") or re.search(r"[()\\]", pattern):
                match = re.fullmatch(pattern.strip('r"'), path)
                if match:
                    handler_fn(qs, match.groups())
                    return
            else:
                if path == pattern:
                    handler_fn(qs, ())
                    return

        error(self, 404, "Route introuvable")

    def do_GET(self):    self.route("GET")
    def do_POST(self):   self.route("POST")
    def do_PUT(self):    self.route("PUT")
    def do_DELETE(self): self.route("DELETE")

    # ── Cards ──────────────────────────────────────────────────────────────
    def card_create(self, qs, groups):
        body = parse_body(self)
        cid  = body.get("id", "").strip()
        if not cid:
            return error(self, 400, "Champ 'id' requis")
        level = int(body.get("level", 1))
        owner = body.get("owner", "")
        try:
            conn = get_db()
            conn.execute("INSERT INTO cards (id, level, owner) VALUES (?,?,?)", (cid, level, owner))
            conn.commit()
            conn.close()
            json_response(self, 201, {"id": cid, "level": level, "owner": owner})
        except sqlite3.IntegrityError:
            error(self, 409, f"Carte '{cid}' existe déjà")

    def card_list(self, qs, groups):
        pattern = qs.get("q", [None])[0]
        conn = get_db()
        if pattern:
            rows = conn.execute("SELECT * FROM cards WHERE id REGEXP ?", (pattern,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM cards").fetchall()
        conn.close()
        json_response(self, 200, rows_to_list(rows))

    def card_get(self, qs, groups):
        cid = groups[0]
        conn = get_db()
        row = conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()
        conn.close()
        if row is None:
            return error(self, 404, "Carte introuvable")
        json_response(self, 200, row_to_dict(row))

    def card_update(self, qs, groups):
        cid  = groups[0]
        body = parse_body(self)
        conn = get_db()
        row  = row_to_dict(conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone())
        if row is None:
            conn.close()
            return error(self, 404, "Carte introuvable")
        level = int(body.get("level", row["level"]))
        owner = body.get("owner", row["owner"])
        conn.execute("UPDATE cards SET level=?, owner=? WHERE id=?", (level, owner, cid))
        conn.commit()
        conn.close()
        json_response(self, 200, {"id": cid, "level": level, "owner": owner})

    def card_delete(self, qs, groups):
        cid = groups[0]
        conn = get_db()
        cur = conn.execute("DELETE FROM cards WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return error(self, 404, "Carte introuvable")
        json_response(self, 200, {"deleted": cid})

    # ── CardReaders ────────────────────────────────────────────────────────
    def reader_create(self, qs, groups):
        body = parse_body(self)
        rid  = body.get("id", "").strip()
        if not rid:
            return error(self, 400, "Champ 'id' requis")
        level = int(body.get("level", 1))
        try:
            conn = get_db()
            conn.execute("INSERT INTO cardReaders (id, level) VALUES (?,?)", (rid, level))
            conn.commit()
            conn.close()
            json_response(self, 201, {"id": rid, "level": level})
        except sqlite3.IntegrityError:
            error(self, 409, f"Lecteur '{rid}' existe déjà")

    def reader_list(self, qs, groups):
        pattern = qs.get("q", [None])[0]
        conn = get_db()
        if pattern:
            rows = conn.execute("SELECT * FROM cardReaders WHERE id REGEXP ?", (pattern,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM cardReaders").fetchall()
        conn.close()
        json_response(self, 200, rows_to_list(rows))

    def reader_get(self, qs, groups):
        rid = groups[0]
        conn = get_db()
        row = conn.execute("SELECT * FROM cardReaders WHERE id=?", (rid,)).fetchone()
        conn.close()
        if row is None:
            return error(self, 404, "Lecteur introuvable")
        json_response(self, 200, row_to_dict(row))

    def reader_update(self, qs, groups):
        rid  = groups[0]
        body = parse_body(self)
        conn = get_db()
        row  = row_to_dict(conn.execute("SELECT * FROM cardReaders WHERE id=?", (rid,)).fetchone())
        if row is None:
            conn.close()
            return error(self, 404, "Lecteur introuvable")
        level = int(body.get("level", row["level"]))
        conn.execute("UPDATE cardReaders SET level=? WHERE id=?", (level, rid))
        conn.commit()
        conn.close()
        json_response(self, 200, {"id": rid, "level": level})

    def reader_delete(self, qs, groups):
        rid = groups[0]
        conn = get_db()
        cur = conn.execute("DELETE FROM cardReaders WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return error(self, 404, "Lecteur introuvable")
        json_response(self, 200, {"deleted": rid})

    # ── Logs ───────────────────────────────────────────────────────────────
    def logs_list(self, qs, groups):
        card_q   = qs.get("card",   [None])[0]
        reader_q = qs.get("reader", [None])[0]
        limit    = qs.get("limit",  [None])[0]

        sql    = "SELECT * FROM logs WHERE 1=1"
        params = []

        if card_q:
            sql += " AND cardId REGEXP ?"
            params.append(card_q)
        if reader_q:
            sql += " AND cardReaderId REGEXP ?"
            params.append(reader_q)

        sql += " ORDER BY id DESC"

        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))

        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        json_response(self, 200, rows_to_list(rows))

    # ── Check ──────────────────────────────────────────────────────────────
    def check(self, qs, groups):
        body      = parse_body(self)
        card_id   = body.get("cardId",   "").strip()
        reader_id = body.get("readerId", "").strip()

        if not card_id or not reader_id:
            return error(self, 400, "Champs 'cardId' et 'readerId' requis")

        valid, _ = check_card(card_id, reader_id)
        json_response(self, 200, {"valid": valid})


# ─── Support REGEXP dans SQLite ──────────────────────────────────────────────
def regexp(pattern, value):
    try:
        return bool(re.search(pattern, str(value)))
    except re.error:
        return False


# Monkey-patch pour ajouter REGEXP à chaque nouvelle connexion
_orig_connect = sqlite3.connect
def _connect_with_regexp(*args, **kwargs):
    conn = _orig_connect(*args, **kwargs)
    conn.create_function("REGEXP", 2, regexp)
    conn.row_factory = sqlite3.Row
    return conn

sqlite3.connect = _connect_with_regexp  # type: ignore


if __name__ == "__main__":
    init_db()
    # "0.0.0.0" permet d'écouter sur tout le réseau (LAN + WAN si port ouvert)
    HOST, PORT = "0.0.0.0", 8000
    server = HTTPServer((HOST, PORT), Handler)

    # Récupération d'une IP plus explicite pour le log
    import socket
    local_ip = socket.gethostbyname(socket.gethostname())

    log.info("🚀 Serveur d'accès démarré !")
    log.info("👉 Local : http://localhost:%d", PORT)
    log.info("👉 Réseau : http://%s:%d", local_ip, PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arrêt du serveur")