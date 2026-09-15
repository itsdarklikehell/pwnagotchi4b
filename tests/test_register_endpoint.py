#!/usr/bin/env python3
"""
tests/test_register_endpoint.py — verify that the server's register flow responds
to a message/send with action=register.

This test checks the server-side path: when a peer sends a register action,
the server should return the agent card as the artifact data. This is distinct
from the client-side register_with_peers() push, which requires network to real
mothership peers.

Run:
    python3 tests/test_register_endpoint.py
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
MOTHERSHIP = __import__("os").path.join(HERE, "..", "mothership", "pwnagotchi_a2a.py")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read().decode())


def post(base: str, payload: dict) -> dict:
    url = base + "/a2a/jsonrpc"
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

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(MOTHERSHIP), "--simulate", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to bind.
        for _ in range(15):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("TEST FAILED: server did not start on port %d" % port, file=sys.stderr)
            return 1

        # 1. Register action returns the agent card as artifact data
        resp = post(base, {
            "jsonrpc": "2.0", "id": 1, "method": "message/send",
            "params": {"message": {
                "messageId": "reg-1", "contextId": "ctx-reg-test", "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"action": "register"})}],
            }},
        })
        art = resp["result"]["artifacts"][0]
        data = json.loads(art["parts"][0]["text"])
        assert data["name"] == "pwnagotchi4b", data
        assert data["description"] is not None
        assert "get_status" in {s["id"] for s in data["skills"]}
        # The register action returns the card; the artifact name is "agent_card"
        assert art["name"] == "agent_card", art["name"]
        print("[ok] register action returns agent card")

        # 2. Agent card at /.well-known/agent-card.json matches
        card = get(base, "/.well-known/agent-card.json")
        assert card["name"] == data["name"]
        assert card["description"] == data["description"]
        print("[ok] agent card is consistent")

        print("\nALL REGISTER ENDPOINT TESTS PASSED")
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
