# pwnagotchi4b — R&D Bevindingen

**Datum:** 2026-10-02
**Repository:** https://github.com/itsdarklikehell/pwnagotchi4b
**Status:** Alle unit tests slagen, CI failures gefixt

---

## Projectoverzicht

pwnagotchi4b is een curated build voor een Raspberry Pi 4B Pwnagotchi met:
- Off-brand Waveshare 3.5" (B) / ILI9486 SPI scherm
- Fancygotchi 2.0 thema-engine
- Custom `waveshare35b` display class
- A2A "mothership" bridge (:8700) voor GLaDOS (Hermes) en Wheatley (OpenClaw)
- Headless first-boot orchestrator + self-healing watchdog

## Architectuur

```
laptop → build/download-image.sh → build/flash-image.sh → tools/provision.sh
  ↓
SD card → RPi4B eerste boot → pwnagotchi4b-firstboot.service
  ↓ (4 installers)
display/install.sh → fancygotchi/install.sh → plugins/install.sh → mothership/install.sh
  ↓
pwnagotchi-a2a.service (:8700) ← A2A JSON-RPC ← GLaDOS (:9900) / Wheatley (:18800)
```

## CI Status

### Voor fix
- **CI workflow:** FAILED — `test_fleet_health.py::test_pwnagotchi_health_up`
- **Gource workflow:** FAILED — `git push` naar `main` geblokkeerd door branch protection

### Na fix
- **Alle unit tests:** PASSED (8/8)
- **CI workflow:** gefixt (mock urlopen string-vs-Request)
- **Gource workflow:** gefixt (commit naar `gource-automation` branch + PR)

## Fixes toegepast

### 1. test_fleet_health.py — urlopen mock fix
**Probleem:** `fleet_health.py` roept `urllib.request.urlopen(base + "/healthz")` aan met een **string** URL, maar de mock verwachtte een `Request` object met `.full_url`. Resultaat: `AttributeError` → opgevangen als "down" → test faalt.

**Fix:** Mock nu `request if isinstance(request, str) else request.full_url` gebruiken. Ook `getcode()` toegevoegd aan `FakeResponse` voor compatibiliteit.

### 2. gource.yml — branch protection fix
**Probleem:** `git push` naar `main` faalt met `GH006: Protected branch update failed`. Branch protection vereist PR + status check.

**Fix:** Workflow commit nu naar `gource-automation` branch en maakt een PR via `peter-evans/create-pull-request@v6`.

## Testresultaat

```
tests/test_firstboot.sh          PASSED (dry-run)
tests/test_watchdog.sh           PASSED (4 scenarios)
tests/test_display_import.py     PASSED
tests/test_a2a_roundtrip.py      PASSED
tests/test_register_endpoint.py  PASSED
tests/test_metrics_endpoint.py   PASSED
tests/test_reboot_action.py      PASSED
tests/test_fleet_health.py       PASSED (5 tests)
```

## Afhankelijkheden

Geen Python package dependencies. Het project is shell scripts + Python scripts die op de Pi draaien. CI gebruikt `ci-templates` reusable workflow.

## Gource workflow

- **Trigger:** push naar `main` + `workflow_dispatch`
- **Output:** `gource.mp4` (1080p, 60fps, ~3.3 MB)
- **Embed:** README heeft `<video>` tag met raw.githubusercontent URL
- **Fix:** Branch protection omzeild via `gource-automation` branch + PR

## Openstaande zaken (TODO)

- [ ] Hardware test op echte RPi4B + ILI9486 scherm
- [ ] `set_mode` non-destructive maken (live mode flip vs restart)
- [ ] A2A heartbeat interval configureren (momenteel 5s in simulate mode)
- [ ] `pwnmothership` plugin uitbreiden met agent_card_url + token_hint
- [ ] PR voor `fix/ci-fleet-health-and-gource-workflow` reviewen + mergen

## Branch

`fix/ci-fleet-health-and-gource-workflow` — klaar voor PR
