#!/usr/bin/env python3
"""
tests/test_fleet_health.py — verify fleet_health.py check_tcp and pwnagotchi health check.

Deze test mockt de netwerkcalls zodat we de logica kunnen verifiëren zonder
echte servers.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

# Importeer de module via sys.path manipulatie
HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
TOOLS_DIR = __import__("os").path.join(HERE, "..", "tools")
sys.path.insert(0, str(TOOLS_DIR))
import fleet_health as fh

class FakeResponse:
    """Mock urllib response die werkt als context manager."""
    def __init__(self, status: int, read_data: bytes):
        self.status = status
        self._read_data = read_data
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
    
    def read(self):
        return self._read_data
    
    def decode(self):
        return self._read_data.decode()

def test_check_tcp_port_open():
    """check_tcp moet True retourneren voor een open poort."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        result = fh.check_tcp("127.0.0.1", port, timeout=1.0)
        assert result is True, f"verwacht True voor open poort {port}, kreeg {result}"
        print("[ok] check_tcp rapporteert True voor open poort")

def test_check_tcp_port_closed():
    """check_tcp moet False retourneren voor een gesloten poort."""
    result = fh.check_tcp("127.0.0.1", 19999, timeout=0.5)
    assert result is False, f"verwacht False voor gesloten poort, kreeg {result}"
    print("[ok] check_tcp rapporteert False voor gesloten poort")

def test_check_tcp_invalid_host():
    """check_tcp moet False retourneren voor ongeldig host."""
    result = fh.check_tcp("192.0.2.1", 80, timeout=0.5)
    assert result is False, f"verwacht False voor onbereikbare host, kreeg {result}"
    print("[ok] check_tcp rapporteert False voor onbereikbare host")

def test_pwnagotchi_health_up():
    """Pwnagotchi health check moet OK rapporteren als /healthz 200 antwoordt."""
    base = "http://192.0.2.1:8700"
    fake_resp = FakeResponse(200, b'{"status":"ok"}')
    os.environ["PWNAGOTCHI_A2A_URL"] = base
    
    original_urlopen = urllib.request.urlopen
    try:
        def mock_urlopen(request, timeout=5):
            url = request.full_url
            if "/healthz" in url:
                return fake_resp
            raise urllib.error.URLError("unexpected URL")
        
        with patch.object(urllib.request, "urlopen", mock_urlopen):
            f = StringIO()
            with redirect_stdout(f):
                fh.main()
            output = f.getvalue()
            assert "Pwnagotchi4b" in output, f"Pwnagotchi4b niet in output: {output[:200]}"
            assert "🟢" in output, f"verwacht 🟢 voor up pwnagotchi, kreeg: {output[:200]}"
            print("[ok] Pwnagotchi health check rapporteert up bij 200 OK")
    finally:
        urllib.request.urlopen = original_urlopen
        os.environ.pop("PWNAGOTCHI_A2A_URL", None)

def test_pwnagotchi_health_down():
    """Pwnagotchi health check moet down rapporteren bij fout."""
    base = "http://192.0.2.1:8700"
    os.environ["PWNAGOTCHI_A2A_URL"] = base
    
    original_urlopen = urllib.request.urlopen
    try:
        def mock_urlopen(request, timeout=5):
            url = request.full_url
            if "/healthz" in url:
                raise urllib.error.URLError("connection refused")
            raise urllib.error.URLError("unexpected URL")
        
        with patch.object(urllib.request, "urlopen", mock_urlopen):
            f = StringIO()
            with redirect_stdout(f):
                fh.main()
            output = f.getvalue()
            assert "Pwnagotchi4b" in output, f"Pwnagotchi4b niet in output: {output[:200]}"
            assert "🔴" in output, f"verwacht 🔴 voor down pwnagotchi, kreeg: {output[:200]}"
            print("[ok] Pwnagotchi health check rapporteert down bij fout met PWNAGOTCHI_A2A_URL")
    finally:
        urllib.request.urlopen = original_urlopen
        os.environ.pop("PWNAGOTCHI_A2A_URL", None)

if __name__ == "__main__":
    print("=== test_check_tcp_port_open ===")
    test_check_tcp_port_open()
    print("=== test_check_tcp_port_closed ===")
    test_check_tcp_port_closed()
    print("=== test_check_tcp_invalid_host ===")
    test_check_tcp_invalid_host()
    print("=== test_pwnagotchi_health_up ===")
    test_pwnagotchi_health_up()
    print("=== test_pwnagotchi_health_down ===")
    test_pwnagotchi_health_down()
    print("\nALL FLEET_HEALTH TESTS PASSED")
