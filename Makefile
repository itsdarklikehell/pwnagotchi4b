# pwnagotchi4b — convenience targets
#
#   make test       run the fast userspace unit tests (bash + python)
#   make vm-test    boot a real Debian VM under QEMU/KVM and run the full
#                   headless setup end-to-end (firstboot + watchdog + A2A)
#   make ci         test + vm-test
#   make clean      drop VM scratch (downloaded image, overlays, tarballs)
#
# The VM test needs qemu-system-x86_64 and /dev/kvm. On a Mac without system
# qemu: `brew install qemu`. On CI we install qemu via apt and enable KVM.

SHELL := /usr/bin/env bash
PYTHON ?= python3
BASH_TESTS := tests/test_firstboot.sh tests/test_watchdog.sh
PY_TESTS   := tests/test_display_import.py tests/test_a2a_roundtrip.py tests/test_register_endpoint.py tests/test_metrics_endpoint.py tests/test_reboot_action.py

.PHONY: all test vm-test ci clean

all: test

test:
	@echo "==> running userspace unit tests"
	@set -e; for t in $(BASH_TESTS); do echo "--- $$t"; bash "$$t"; done
	@for t in $(PY_TESTS); do echo "--- $$t"; $(PYTHON) "$$t"; done
	@echo "==> unit tests PASSED"

vm-test:
	@echo "==> running VM integration test (requires qemu + /dev/kvm)"
	@bash tests/vm/run.sh

ci: test vm-test

clean:
	@rm -rf tests/vm/.work
	@rm -rf tests/__pycache__ tools/__pycache__
	@echo "==> cleaned VM scratch + pycache"
