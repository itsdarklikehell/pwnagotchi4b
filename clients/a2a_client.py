#!/usr/bin/env python3
"""
a2a_client.py — shared A2A JSON-RPC client for pwnagotchi4b peers.

Dependency-light (urllib only). Both glados_client.py and wheatley_client.py
import from here; they only supply a name for logging / description purposes.

Call recipe (mirrors the verified GLaDOS<->Wheatley contract):
  POST /a2a/jsonrpc  ← JSON-RPC 2.0 message/send
  body carries {kind:text} part with a JSON {action, args} command
  reply read from result.artifacts[].parts[].text
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def send(
    peer_url: str,
    token: str,
    action: str,
    args: Dict[str, Any] | None = None,
    client_name: str = "a2a_client",
) -> dict:
    """Send an A2A message/send JSON-RPC call and return the decoded result."""
    url = peer_url.rstrip("/") + "/a2a/jsonrpc"
    message: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": f"msg-{client_name}-1",
                "contextId": f"ctx-{client_name}",
                "role": "user",
                "parts": [
                    {"kind": "text", "text": json.dumps({"action": action, "args": args or {}})}
                ],
            }
        },
    }
    data = json.dumps(message).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"connection failed: {e.reason}") from e

    # Surface JSON-RPC errors cleanly instead of KeyError on missing result.
    if "error" in payload:
        err = payload["error"]
        raise RuntimeError(f"A2A error {err.get('code')}: {err.get('message')}")
    result = payload.get("result", {})
    artifacts = result.get("artifacts", [])
    if artifacts:
        text = artifacts[0]["parts"][0]["text"]
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}
    return result


def watch(peer: str, token: str, interval: int, client_name: str = "a2a_client") -> int:
    """Poll get_status every INTERVAL s and print a compact line."""
    print(f"# watching {peer} every {interval}s (Ctrl-C to stop)", file=sys.stderr)
    try:
        while True:
            try:
                st = send(peer, token, "get_status", {}, client_name=client_name)
                mode = st.get("mode", "?")
                pwnd = st.get("pwnd_tot", st.get("pwndrun", "?"))
                ups = st.get("ups", st.get("battery", "?"))
                print(f"{time.strftime('%H:%M:%S')} mode={mode} pwnd={pwnd} ups={ups}")
            except Exception as e:
                print(f"{time.strftime('%H:%M:%S')} ERR {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def build_parser(description: str, client_name: str) -> argparse.ArgumentParser:
    """Build the CLI argument parser for a named client."""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--peer", default=os.environ.get("PWNAGOTCHI_A2A_URL", "http://pwnagotchi4b.local:8700"),
                    help="Pwnagotchi A2A endpoint")
    ap.add_argument("--token", default=os.environ.get("PWNAGOTCHI_A2A_TOKEN", ""),
                    help="A2A bearer token")
    sub = ap.add_subparsers(dest="action", required=True)

    sub.add_parser("get_status")
    p_hs = sub.add_parser("fetch_handshakes")
    p_hs.add_argument("--limit", type=int, default=20)
    p_hf = sub.add_parser("fetch_handshake_files")
    p_hf.add_argument("--limit", type=int, default=20)
    sub.add_parser("shutdown")
    sub.add_parser("reboot")
    p_mode = sub.add_parser("set_mode")
    p_mode.add_argument("--mode", default="auto")
    p_toggle = sub.add_parser("toggle_plugin")
    p_toggle.add_argument("--name", required=True)
    p_toggle.add_argument("--enabled", type=lambda x: x.lower() == "true", default=True)
    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--interval", type=int, default=30)

    return ap


def resolve_cmd_args(action: str, args: argparse.Namespace) -> Dict[str, Any]:
    """Map parsed argparse args to the command dict for send()."""
    cmd_args: Dict[str, Any] = {}
    if action == "set_mode":
        cmd_args = {"mode": args.mode}
    elif action == "toggle_plugin":
        cmd_args = {"name": args.name, "enabled": args.enabled}
    elif action == "fetch_handshakes":
        cmd_args = {"limit": args.limit}
    elif action == "fetch_handshake_files":
        cmd_args = {"limit": args.limit}
    elif action == "watch":
        pass  # handled specially
    return cmd_args
