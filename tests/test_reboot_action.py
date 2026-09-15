#!/usr/bin/env python3
"""
tests/test_reboot_action.py — verify the reboot/restart A2A action.

The handler maps reboot/restart to a fancyserver command (reboot-auto / reboot-manual).
In --simulate mode this returns the command string without touching real hardware.

Run:
    python3 tests/test_reboot_action.py
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
        for _ in range(15):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("TEST FAILED: server did not start on port %d" % port, file=sys.stderr)
            return 1

        # 1. reboot (auto mode) returns expected command
        resp = post(base, {
            "jsonrpc": "2.0", "id": 1, "method": "message/send",
            "params": {"message": {
                "messageId": "rb-1", "contextId": "ctx-reboot-test", "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"action": "reboot", "args": {"mode": "auto"}})}],
            }},
        })
        data = resp["result"]["artifacts"][0]["parts"][0]["text"]
        art = json.loads(data)
        assert art["command"] == "reboot-auto", art
        assert art.get("dispatched") is True, art
        print("[ok] reboot action returns 'reboot-auto' command")

        # 2. restart (manual mode) returns expected command
        resp = post(base, {
            "jsonrpc": "2.0", "id": 2, "method": "message/send",
            "params": {"message": {
                "messageId": "rb-2", "contextId": "ctx-restart-test", "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"action": "restart", "args": {"mode": "manual"}})}],
            }},
        })
        data = resp["result"]["artifacts"][0]["parts"][0]["text"]
        art = json.loads(data)
        assert art["command"] == "reboot-manual", art
        assert art.get("dispatched") is True, art
        print("[ok] restart action returns 'reboot-manual' command (manual mode)")

        # 3. unknown action returns error
        resp = post(base, {
            "jsonrpc": "2.0", "id": 3, "method": "message/send",
            "params": {"message": {
                "messageId": "rb-3", "contextId": "ctx-bad-test", "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"action": "bogus_action"})}],
            }},
        })
        data = resp["result"]["artifacts"][0]["parts"][0]["text"]
        err = json.loads(data)
        assert err["error"] == "unknown action: bogus_action", err
        print("[ok] unknown action returns error artifact")

        print("\nALL REBOOT ACTION TESTS PASSED")
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
