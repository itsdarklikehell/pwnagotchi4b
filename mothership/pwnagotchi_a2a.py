#!/usr/bin/env python3
"""
pwnagotchi_a2a.py — Pwnagotchi-side A2A "mothership" bridge endpoint.

This is a DESIGN + SKELETON. It does NOT flash or run anything on hardware.
It implements the A2A JSON-RPC endpoint (the NEW pwnagotchi peer, port :8700)
that GLaDOS (Hermes :9900) and Wheatley (OpenClaw :18800) can call.

Features
--------
- Serves the Agent Card at  /.well-known/agent-card.json   (discovery, public)
- Implements A2A JSON-RPC at /a2a/jsonrpc                  (bearer-token guarded)
    methods: message/send, tasks/get, tasks/cancel
- Maps A2A `action`s to:
    * pwnagotchi local API  http://127.0.0.1:8666/api/v1/...   (state / handshakes)
    * fancyserver Listener  127.0.0.1:3699                     (control commands)
- Falls back to SIMULATED state when the Pi APIs are absent (--simulate) so the
  entire A2A flow is exercisable on a dev laptop.

Run
---
    python3 pwnagotchi_a2a.py                      # real mode (guard-guarded)
    python3 pwnagotchi_a2a.py --simulate           # fake state, no Pi needed
    python3 pwnagotchi_a2a.py --register           # push own card to mothership peers

Auth: bearer token from env PWNAGOTCHI_A2A_TOKEN or config.json -> a2a_token.
      Unset + non-simulate -> warns and runs permissive (dev only).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Dict, Optional

LOG = logging.getLogger("pwnagotchi_a2a")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ----------------------------------------------------------------------------
# Metrics — Prometheus-style snapshot for /metrics endpoint
# ----------------------------------------------------------------------------
def _metrics_snapshot() -> Dict[str, Any]:
    """Return a JSON-serializable snapshot of A2A server metrics."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "timestamp": now,
        "server": {
            "name": "pwnagotchi4b",
            "version": "0.1.0",
            "simulate": SIMULATE,
            "port": CONFIG.get("port", 8700),
        },
        "tasks": {
            "active": len(TASKS),
            "completed": sum(1 for t in TASKS.values() if t.get("status", {}).get("state") == "completed"),
            "canceled": sum(1 for t in TASKS.values() if t.get("status", {}).get("state") == "canceled"),
        },
        "peers": [
            {"name": p.get("name"), "url": p.get("url")}
            for p in CONFIG.get("peers", [])
        ],
        "actions_served": list(ACTION_COUNTERS.keys()) if ACTION_COUNTERS else [],
    }


def _inc_action(name: str) -> None:
    ACTION_COUNTERS[name] = ACTION_COUNTERS.get(name, 0) + 1


ACTION_COUNTERS: Dict[str, int] = {}

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
AGENT_CARD_PATH = os.path.join(HERE, "agent-card.json")  # optional override

DEFAULTS: Dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8700,
    "a2a_token": "",
    "fancyserver_authkey": "REPLACE_WITH_FANCYSERVER_KEY",
    "fancyserver_host": "127.0.0.1",
    "fancyserver_port": 3699,
    "pwnagotchi_api": "http://127.0.0.1:8666/api/v1",
    "self_url": "http://pwnagotchi4b.local:8700",
    "peers": [
        {"name": "glados-hermes", "url": "http://127.0.0.1:9900", "token": ""},
        {"name": "wheatley-openclaw", "url": "http://127.0.0.1:18800", "token": ""},
    ],
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as fh:
                cfg.update(json.load(fh))
            LOG.info("Loaded config from %s", CONFIG_PATH)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Could not read %s: %s", CONFIG_PATH, exc)
    # env overrides
    if os.environ.get("PWNAGOTCHI_A2A_TOKEN"):
        cfg["a2a_token"] = os.environ["PWNAGOTCHI_A2A_TOKEN"]
    if os.environ.get("FANCYSERVER_AUTHKEY"):
        cfg["fancyserver_authkey"] = os.environ["FANCYSERVER_AUTHKEY"]
    return cfg


CONFIG = load_config()
SIMULATE = False

# In-memory task store (A2A tasks/get). Not durable by design.
TASKS: Dict[str, Dict[str, Any]] = {}


# ----------------------------------------------------------------------------
# Agent Card (the canonical one lives in AGENT_SPEC.md; this is the served copy)
# ----------------------------------------------------------------------------
def agent_card(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if os.path.exists(AGENT_CARD_PATH):
        with open(AGENT_CARD_PATH) as fh:
            return json.load(fh)
    return {
        "protocolVersion": "0.2.0",
        "name": "pwnagotchi4b",
        "description": (
            "A2A agent peer for a Pwnagotchi on a Raspberry Pi 4B "
            "(Waveshare 3.5B / ILI9486 fbtft). Telemetry + remote control for "
            "mothership agents GLaDOS (Hermes) and Wheatley (OpenClaw)."
        ),
        "url": cfg.get("self_url", "http://pwnagotchi4b.local:8700"),
        "provider": {
            "organization": "itsdarklikehell",
            "url": "https://github.com/itsdarklikehell/pwnagotchi4b",
        },
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "authentication": {"schemes": ["bearer"]},
        "skills": [
            {"id": "get_status", "name": "Get Pwnagotchi status",
             "description": "Returns current state artifact.", "tags": ["status", "telemetry"],
             "examples": ["{\"action\":\"get_status\"}"]},
            {"id": "fetch_handshakes", "name": "Fetch handshake list",
             "description": "Returns captured handshake files.", "tags": ["handshakes"],
             "examples": ["{\"action\":\"fetch_handshakes\",\"args\":{\"limit\":20}}"]},
            {"id": "set_mode", "name": "Set mode",
             "description": "AUTO/MANUAL via fancyserver restart.", "tags": ["control"],
             "examples": ["{\"action\":\"set_mode\",\"args\":{\"mode\":\"manual\"}}"]},
            {"id": "reboot", "name": "Reboot", "tags": ["control", "power"],
             "examples": ["{\"action\":\"reboot\",\"args\":{\"mode\":\"auto\"}}"]},
            {"id": "shutdown", "name": "Shutdown", "tags": ["control", "power"],
             "examples": ["{\"action\":\"shutdown\"}"]},
            {"id": "toggle_plugin", "name": "Toggle plugin", "tags": ["control", "plugin"],
             "examples": ["{\"action\":\"toggle_plugin\",\"args\":{\"name\":\"fancygotchi\",\"enabled\":true}}"]},
        ],
    }


# ----------------------------------------------------------------------------
# Local integrations (GUARDED — never crash if the Pi bits are absent)
# ----------------------------------------------------------------------------
def _pwnagotchi_get(path: str, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if SIMULATE:
        return None
    try:
        import requests  # type: ignore
    except Exception:  # noqa: BLE001
        LOG.warning("requests not installed; cannot reach pwnagotchi API")
        return None
    try:
        r = requests.get(f"{cfg['pwnagotchi_api']}/{path}", timeout=5)
        if r.ok:
            return r.json()
        LOG.warning("pwnagotchi API %s -> %s", path, r.status_code)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("pwnagotchi API %s error: %s", path, exc)
    return None


def _fancyserver_send(command: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Send a control command to the fancyserver multiprocessing Listener."""
    if SIMULATE:
        LOG.info("[simulate] fancyserver <- %r", command)
        return {"dispatched": True, "command": command, "simulated": True}
    try:
        from multiprocessing.connection import Client  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"dispatched": False, "error": f"no multiprocessing: {exc}"}
    try:
        conn = Client(
            (cfg["fancyserver_host"], cfg["fancyserver_port"]),
            authkey=cfg["fancyserver_authkey"].encode(),
        )
        with conn:
            conn.send(command)
            try:
                reply = conn.recv()  # fancyserver may or may not echo
            except Exception:  # noqa: BLE001
                reply = None
        LOG.info("fancyserver <- %r -> %r", command, reply)
        return {"dispatched": True, "command": command, "reply": reply}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("fancyserver send failed: %s", exc)
        return {"dispatched": False, "error": str(exc)}


# ---- state normalization (reuses pwnmothership field set) -------------------
def get_status(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if SIMULATE:
        return _sim_status()
    raw = _pwnagotchi_get("status", cfg) or {}
    bot = raw.get("bot", {}) if isinstance(raw, dict) else {}
    wifi = raw.get("wifi", {}) if isinstance(raw, dict) else {}
    return {
        "name": bot.get("name"),
        "version": bot.get("version"),
        "fingerprint": (bot.get("identity") or {}).get("fingerprint"),
        "mode": bot.get("mode"),
        "face": bot.get("face"),
        "pwnd_run": bot.get("pwnd_run"),
        "pwnd_tot": bot.get("pwnd_tot"),
        "aps": wifi.get("aps") if isinstance(wifi, dict) else raw.get("bot", {}).get("ap_tot"),
        "channel": wifi.get("channel") if isinstance(wifi, dict) else None,
        "handshakes": bot.get("pwnd_tot"),
        "peers": [],  # fill from /peers if desired
        "uptime": raw.get("uptime"),
        "cpu": raw.get("cpu"),
        "temp": raw.get("temp"),
        "memory": raw.get("mem"),
        "battery": (raw.get("ups") if isinstance(raw.get("ups"), dict) else None),
        "timestamp": _now_iso(),
    }


def _sim_status() -> Dict[str, Any]:
    return {
        "name": "pwnagotchi4b", "version": "1.5.5",
        "fingerprint": "aa:bb:cc:dd:ee:ff", "mode": "auto", "face": "happy",
        "pwnd_run": 3, "pwnd_tot": 1287, "aps": 42, "channel": 6,
        "handshakes": 1287, "peers": ["unit-2", "unit-7"], "uptime": 93144,
        "cpu": 18.2, "temp": 47.5, "memory": 33.1,
        "battery": {"percent": 87, "voltage": 4.12, "charging": True},
        "timestamp": _now_iso(),
    }


def fetch_handshakes(cfg: Dict[str, Any], limit: int = 20) -> Dict[str, Any]:
    if SIMULATE:
        items = [
            {"filename": f"handshake_{i}.pcap", "size": 4096 + i, "age_days": i}
            for i in range(min(limit, 5))
        ]
        return {"count": len(items), "items": items}
    raw = _pwnagotchi_get("handshakes", cfg) or {}
    items = raw.get("handshakes", []) if isinstance(raw, dict) else []
    return {"count": len(items), "items": items[:limit]}


# ---- command handlers -------------------------------------------------------
_HANDLERS: Dict[str, Any] = {}


def _handle_get_status(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": "pwnagotchi_state", "data": get_status(cfg)}


def _handle_fetch_handshakes(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": "handshake_list", "data": fetch_handshakes(cfg, int(args.get("limit", 20)))}

def _handle_fetch_handshake_files(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return captured handshake files with path, filename, size, age (real: pwnagotchi API, sim: synthetic)."""
    limit = int(args.get("limit", 20))
    if SIMULATE:
        items = [
            {
                "path": f"/root/run/handshakes/handshake_{i}.pcap",
                "filename": f"handshake_{i}.pcap",
                "size": 4096 + i * 1024,
                "age_days": i,
            }
            for i in range(min(limit, 5))
        ]
        return {"count": len(items), "items": items}
    raw = _pwnagotchi_get("handshakes", cfg) or {}
    items_in = raw.get("handshakes", []) if isinstance(raw, dict) else []
    items = []
    for h in items_in[:limit]:
        if not isinstance(h, dict):
            continue
        items.append({
            "path": h.get("path", ""),
            "filename": h.get("filename", ""),
            "size": h.get("size", 0),
            "age_days": (datetime.now(timezone.utc) - datetime.fromisoformat(h["datetime"][:19]))
                        .days if h.get("datetime") else 0,
        })
    return {"count": len(items), "items": items}


def _handle_set_mode(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode", "auto")).lower()
    cmd = "restart-auto" if mode == "auto" else "restart-manual"
    return {"name": "ack", "data": {"mode": mode, **_fancyserver_send(cmd, cfg)}}


def _handle_register(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": "agent_card", "data": agent_card(cfg)}


def _handle_reboot_restart(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode", "auto")).lower()
    cmd = "reboot-auto" if mode == "auto" else "reboot-manual"
    return {"name": "ack", "data": {"command": "reboot", **_fancyserver_send(cmd, cfg)}}


def _handle_shutdown(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": "ack", "data": {"command": "shutdown", **_fancyserver_send("shutdown", cfg)}}


def _handle_toggle_plugin(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    enabled = bool(args.get("enabled", True))
    if not name:
        return {"name": "plugin_status", "data": {"error": "missing plugin name"}}
    cmd = f"plugin {name} {enabled}"
    return {"name": "plugin_status", "data": {"name": name, "enabled": enabled,
                                              **_fancyserver_send(cmd, cfg)}}


_HANDLERS = {
    "get_status": _handle_get_status,
    "fetch_handshakes": _handle_fetch_handshakes,
    "set_mode": _handle_set_mode,
    "register": _handle_register,
    "reboot": _handle_reboot_restart,
    "restart": _handle_reboot_restart,
    "shutdown": _handle_shutdown,
    "toggle_plugin": _handle_toggle_plugin,
}


def do_action(action: str, args: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch an A2A action to local effect via handler table. Returns artifact-shaped dict."""
    args = args or {}
    LOG.info("action=%s args=%s", action, args)
    handler = _HANDLERS.get(action)
    if handler is None:
        return {"name": "error", "data": {"error": f"unknown action: {action}"}}
    return handler(action, args, cfg)


# ----------------------------------------------------------------------------
# A2A JSON-RPC core
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonrpc_error(code: int, message: str, req_id=None) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_jsonrpc(payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _jsonrpc_error(-32600, "Invalid Request")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(-32600, "Invalid Request: jsonrpc != 2.0")
    req_id = payload.get("id")
    method = payload.get("method")

    if method == "message/send":
        return _handle_message_send(payload.get("params", {}), req_id, cfg)
    if method == "tasks/get":
        task_id = (payload.get("params", {}) or {}).get("id")
        task = TASKS.get(task_id) if task_id else None
        if not task:
            return _jsonrpc_error(-32002, f"task not found: {task_id}", req_id)
        return {"jsonrpc": "2.0", "id": req_id, "result": task}
    if method == "tasks/cancel":
        task_id = (payload.get("params", {}) or {}).get("id")
        task = TASKS.get(task_id) if task_id else None
        if not task:
            return _jsonrpc_error(-32002, f"task not found: {task_id}", req_id)
        task["status"] = {"state": "canceled", "timestamp": _now_iso()}
        return {"jsonrpc": "2.0", "id": req_id, "result": task}

    return _jsonrpc_error(-32601, f"Method not found: {method}", req_id)


def _handle_message_send(params: Dict[str, Any], req_id, cfg: Dict[str, Any]) -> Dict[str, Any]:
    msg = params.get("message", {})
    task_id = msg.get("taskId") or f"task-{uuid.uuid4().hex[:12]}"
    context_id = msg.get("contextId", "ctx-bridge")
    parts = msg.get("parts", [])

    # Extract the command: we expect a single text part holding a JSON string.
    raw_cmd = ""
    for part in parts:
        if part.get("kind") == "text":
            raw_cmd = part.get("text", "")
            break
    try:
        command = json.loads(raw_cmd) if raw_cmd else {}
    except Exception as exc:  # noqa: BLE001
        command = {}
        LOG.warning("Could not parse command JSON: %s", exc)

    action = command.get("action", "get_status")
    args = command.get("args", {})

    artifact = do_action(action, args, cfg)
    art_id = f"art-{uuid.uuid4().hex[:12]}"
    task = {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": "completed", "timestamp": _now_iso()},
        "artifacts": [
            {
                "artifactId": art_id,
                "name": artifact.get("name", "result"),
                "parts": [{"kind": "text", "text": json.dumps(artifact.get("data", {}), indent=2)}],
            }
        ],
        "history": [{"role": "user", "parts": [{"kind": "text", "text": raw_cmd or "{}"}]}],
    }
    # mark destructive-but-unconfirmed commands as completed-with-ack (unit may go dark)
    if action in ("reboot", "restart", "shutdown"):
        task["status"]["state"] = "completed"
        task["note"] = "command dispatched; unit may be offline until reboot"

    TASKS[task_id] = task
    _inc_action(action)
    LOG.info("task %s -> %s (action=%s)", task_id, task["status"]["state"], action)
    return {"jsonrpc": "2.0", "id": req_id, "result": task}


# ----------------------------------------------------------------------------
# Peer registration (active push of our card to GLaDOS / Wheatley)
# ----------------------------------------------------------------------------
def register_with_peers(cfg: Dict[str, Any]) -> None:
    card = agent_card(cfg)
    for peer in cfg.get("peers", []):
        url = peer.get("url", "").rstrip("/") + "/a2a/jsonrpc"
        token = peer.get("token", "")
        body = {
            "jsonrpc": "2.0", "id": f"reg-{uuid.uuid4().hex[:8]}",
            "method": "message/send",
            "params": {"message": {
                "messageId": f"msg-{uuid.uuid4().hex[:8]}",
                "contextId": "ctx-register",
                "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"action": "register"})}]}},
        }
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            import requests  # type: ignore
            r = requests.post(url, json=body, headers=headers, timeout=5)
            LOG.info("registered with %s -> %s", peer.get("name"), r.status_code)
            LOG.debug("peer reply: %s", r.text[:400])
        except Exception as exc:  # noqa: BLE001
            LOG.warning("register failed for %s: %s", peer.get("name"), exc)


# ----------------------------------------------------------------------------
# HTTP transport: Flask if present, else stdlib http.server
# ----------------------------------------------------------------------------
def _auth_ok(headers: Dict[str, str], cfg: Dict[str, Any]) -> bool:
    # In simulate mode we are explicitly a dev/test harness — accept all.
    if SIMULATE:
        return True
    token = cfg.get("a2a_token", "")
    if not token:
        return True  # permissive/dev mode (warned at startup)
    auth = headers.get("Authorization", "") or headers.get("authorization", "")
    return auth == f"Bearer {token}"


# --- Flask path --------------------------------------------------------------
def _build_flask_app(cfg: Dict[str, Any]):
    from flask import Flask, request, Response  # type: ignore

    app = Flask("pwnagotchi_a2a")

    @app.get("/.well-known/agent-card.json")
    def card():
        return Response(json.dumps(agent_card(cfg)), mimetype="application/json")

    @app.post("/a2a/jsonrpc")
    def jsonrpc():
        if not _auth_ok(dict(request.headers), cfg):
            return Response(
                json.dumps(_jsonrpc_error(-32001, "Unauthorized")),
                status=HTTPStatus.UNAUTHORIZED, mimetype="application/json")
        try:
            payload = request.get_json(force=True)
        except Exception:  # noqa: BLE001
            return Response(json.dumps(_jsonrpc_error(-32600, "Invalid JSON")),
                            status=HTTPStatus.BAD_REQUEST, mimetype="application/json")
        return Response(json.dumps(handle_jsonrpc(payload, cfg)), mimetype="application/json")

    @app.get("/healthz")
    def health():
        return {"ok": True, "simulate": SIMULATE}

    @app.get("/metrics")
    def metrics():
        return Response(json.dumps(_metrics_snapshot()), mimetype="application/json")

    return app


# --- stdlib fallback path ----------------------------------------------------
def _build_stdlib_handler(cfg: Dict[str, Any]):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/.well-known/agent-card.json":
                self._send(200, agent_card(cfg))
            elif self.path == "/healthz":
                self._send(200, {"ok": True, "simulate": SIMULATE})
            elif self.path == "/metrics":
                self._send(200, _metrics_snapshot())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/a2a/jsonrpc":
                self._send(404, {"error": "not found"})
                return
            if not _auth_ok(dict(self.headers), cfg):
                self._send(401, _jsonrpc_error(-32001, "Unauthorized"))
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except Exception:  # noqa: BLE001
                self._send(400, _jsonrpc_error(-32600, "Invalid JSON"))
                return
            self._send(200, handle_jsonrpc(payload, cfg))

        def log_message(self, *a):  # quieter
            LOG.debug("http: " + (a[0] % a[1:] if a else ""))

    return Handler


def serve(cfg: Dict[str, Any]) -> None:
    global SIMULATE
    if not cfg.get("a2a_token") and not SIMULATE:
        LOG.warning("a2a_token is EMPTY — running permissive/dev mode. DO NOT ship this.")

    try:
        app = _build_flask_app(cfg)
        LOG.info("Using Flask transport")
        app.run(host=cfg["host"], port=cfg["port"], threaded=True)
        return
    except ImportError:
        LOG.info("Flask not available — using stdlib http.server")

    from http.server import HTTPServer
    handler = _build_stdlib_handler(cfg)
    httpd = HTTPServer((cfg["host"], cfg["port"]), handler)
    LOG.info("Serving A2A on http://%s:%s", cfg["host"], cfg["port"])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopping")
        httpd.server_close()


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    global SIMULATE
    ap = argparse.ArgumentParser(description="Pwnagotchi A2A mothership bridge (skeleton).")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--simulate", action="store_true",
                    help="Use simulated state; no Pi APIs required.")
    ap.add_argument("--register", action="store_true",
                    help="Push our Agent Card to configured mothership peers and exit.")
    args = ap.parse_args(argv)

    if args.simulate:
        SIMULATE = True
    if args.host:
        CONFIG["host"] = args.host
    if args.port:
        CONFIG["port"] = args.port

    if args.register:
        register_with_peers(CONFIG)
        return 0

    LOG.info("Starting pwnagotchi A2A peer (simulate=%s)", SIMULATE)
    serve(CONFIG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
