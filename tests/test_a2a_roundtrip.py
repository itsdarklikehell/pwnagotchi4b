#!/usr/bin/env python3
"""
tests/test_a2a_roundtrip.py — REAL end-to-end verification of the A2A bridge.

Starts the Pwnagotchi A2A endpoint in --simulate mode (no Pi needed), then
exercises get_status / toggle_plugin / set_mode / fetch_handshake_files over the
real JSON-RPC wire and asserts the replies.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
MOTHERSHIP = __import__("os").path.join(HERE, "..", "mothership", "pwnagotchi_a2a.py")


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def main() -> int:
    import os

    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(MOTHERSHIP), "--simulate"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2.5)  # let the server bind
        base = "http://127.0.0.1:8700"

        # 1. Agent Card (discovery, public)
        with urllib.request.urlopen(base + "/.well-known/agent-card.json", timeout=5) as r:
            card = json.loads(r.read().decode())
        assert card["name"] == "pwnagotchi4b", card
        print("[ok] agent card served, name =", card["name"])

        # 2. get_status over JSON-RPC
        resp = post(base + "/a2a/jsonrpc", {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "t1",
                    "contextId": "ctx-test",
                    "role": "user",
                    "parts": [{"kind": "text", "text": json.dumps({"action": "get_status"})}],
                }
            },
        })
        art = resp["result"]["artifacts"][0]["parts"][0]["text"]
        state = json.loads(art)
        assert state["name"] == "pwnagotchi4b" and "pwnd_tot" in state, state
        print("[ok] get_status -> mode=%s pwnd_tot=%s" % (state["mode"], state["pwnd_tot"]))

        # 3. toggle_plugin (action -> fancyserver mapping)
        resp = post(base + "/a2a/jsonrpc", {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "t2",
                    "contextId": "ctx-test",
                    "role": "user",
                    "parts": [
                        {
                            "kind": "text",
                            "text": json.dumps(
                                {"action": "toggle_plugin", "args": {"name": "fancygotchi", "enabled": True}}
                            ),
                        }
                    ],
                }
            },
        })
        art = resp["result"]["artifacts"][0]["parts"][0]["text"]
        plug = json.loads(art)
        # The artifact is shaped as {"name": "plugin_status", "data": {...}}.
        data = plug.get("data", plug)
        assert data.get("dispatched") is True, plug
        print("[ok] toggle_plugin -> dispatched via fancyserver (simulated)")

        # 4. set_mode
        resp = post(base + "/a2a/jsonrpc", {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "t3",
                    "contextId": "ctx-test",
                    "role": "user",
                    "parts": [
                        {
                            "kind": "text",
                            "text": json.dumps(
                                {"action": "set_mode", "args": {"mode": "manual"}}
                            ),
                        }
                    ],
                }
            },
        })
        art = resp["result"]["artifacts"][0]["parts"][0]["text"]
        mode = json.loads(art)
        # The artifact text is the inner 'data' payload: {"mode":..., "command":..., ...}
        assert "restart-manual" in mode["command"], mode
        print("[ok] set_mode manual -> fancyserver cmd:", mode["command"])

        # 5. fetch_handshake_files (path, filename, size, age)
        resp = post(base + "/a2a/jsonrpc", {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "t4",
                    "contextId": "ctx-test",
                    "role": "user",
                    "parts": [
                        {
                            "kind": "text",
                            "text": json.dumps(
                                {"action": "fetch_handshake_files", "args": {"limit": 3}}
                            ),
                        }
                    ],
                }
            },
        })
        art = resp["result"]["artifacts"][0]["parts"][0]["text"]
        hf = json.loads(art)
        assert hf["count"] == 3, hf
        assert hf["items"][0]["path"].startswith("/root/run/handshakes/"), hf
        assert hf["items"][0]["filename"] == "handshake_0.pcap", hf
        assert hf["items"][0]["size"] == 4096, hf
        print("[ok] fetch_handshake_files -> count=%d, item0=%s" % (hf["count"], hf["items"][0]["filename"]))

        print("\nALL A2A ROUND-TRIP TESTS PASSED")
        return 0
    except (AssertionError, urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        print("TEST FAILED:", e, file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
