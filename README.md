sudo systemctl enable --now libvirtd# pwnagotchi4b

Run **Pwnagotchi** + **Fancygotchi** on a **Raspberry Pi 4B** with an
**off-brand Waveshare 3.5" (B) / ILI9486** SPI screen — then flash a prepared
image to an SD card and let **GLaDOS (Hermes)** and **Wheatley (OpenClaw)**
remotely help and control the little unit by unifying their forces over **A2A**.

> ⚠️ **Educational / authorized-use only.** Pwnagotchi is a Wi-Fi auditing tool.
> Only capture handshakes on networks you own or have explicit permission to test.

---

## What this repo is

A curated, reproducible build for a RPi4B Pwnagotchi with a 3.5" color screen,
plus the **"mothership" A2A bridge** that turns the Pi into an agent peer that
GLaDOS and Wheatley can query and command.

| Directory | Purpose |
|-----------|---------|
| `config/` | `config.toml` ready for the RPi4B + off-brand 3.5B (Fancygotchi + plugins + custom `waveshare35b` display). |
| `display/` | Custom `waveshare35b` framebuffer display class (fbcp-ili9341 **recommended**, fbtft **fallback**) + install script. |
| `fancygotchi/` | Fancygotchi install + default theme bootstrap. |
| `plugins/` | Install script that pulls `itsdarklikehell/pwnagotchi-plugins` (your own collection). |
| `build/` | Download the `jayofelony` 64-bit image and **flash + provision** an SD card (reuses `pwnagotchi-control-center`). |
| `mothership/` | **The A2A bridge** (designed with Wheatley). Pi-side A2A agent endpoint at `:8700`. |
| `clients/` | `glados_client.py` / `wheatley_client.py` — how the two cores talk to the Pi. |
| `tools/` | `provision.sh` (apply config/plugins/display + enable first-boot & watchdog on a mounted SD or live Pi), `flash.sh` helper, `firstboot.sh` + `watchdog.sh` (headless setup + self-healing). |
| `tests/` | Real A2A simulate round-trip + display-class import check. |

---

## Hardware assumptions

- **Board:** Raspberry Pi 4B (2 GB RAM minimum).
- **Screen:** Waveshare 3.5" (B) **clone** using the **ILI9486** controller over
  SPI (the most common off-brand 3.5B). Pinout: SPI0 (GPIO 7=RST/DC, 8=DC, 10=MOSI,
  11=SCLK, 24=CS), backlight on GPIO 18 (or board-specific). Confirm your clone's
  controller with `ls /sys/bus/spi/devices/` / `dmesg | grep -i ili` on first boot.
- **SD card:** ≥ 16 GB (A1 rated).

---

## Quick start (laptop → SD → Pi)

All commands that touch the SD card are written to be run **on your laptop**
(`SgtStroopwafel-Laptop`) with the target SD card inserted. They are linted but
are **not auto-executed by the agent** — flashing is a deliberate, manual step.

```bash
# 1. clone this repo
git clone https://github.com/itsdarklikehell/pwnagotchi4b.git
cd pwnagotchi4b

# 2. download the official 64-bit image (jayofelony/pwnagotchi, ~2.9.5.8)
bash build/download-image.sh

# 3. flash + provision the SD card (interactive: picks the right device)
sudo bash tools/flash.sh          # wraps build/flash-image.sh + tools/provision.sh
                                # provision.sh ALSO enables a first-boot service

# 4. insert the SD into the RPi4B and power on. On first boot, the
#    pwnagotchi4b-firstboot systemd oneshot runs ALL FOUR installers
#    (display → fancygotchi → plugins → mothership) automatically, then reboots.
#    No keyboard / SSH needed — fully hands-off.

# 5. after the auto-reboot, verify the A2A bridge is live (from any host):
python3 clients/glados_client.py --peer http://<pi-ip>:8700 get_status
# or:  python3 clients/wheatley_client.py --peer http://<pi-ip>:8700 get_status
```

> **A2A bridge contract (what the clients + fleet poller expect):**
> - Clients POST JSON-RPC to **`/a2a/jsonrpc`** (method `message/send`, a
>   `{kind: text}` part carrying a JSON command; reply is read from
>   `result.artifacts[].parts[].text`).
> - `tools/fleet_health.py` (Cornelis's home-fleet poller) probes **`/healthz`**
>   (returns `200 {"status":"ok"}`) when `PWNAGOTCHI_A2A_URL` is set.
> - The agent card lives at **`/.well-known/agent-card.json`**.
> The test stub `tools/a2a_sim.py` implements all three and is what the VM
> integration test (`make vm-test`) and `tests/test_a2a_roundtrip.py` exercise.

See [**`docs/INSTALL.md`**](docs/INSTALL.md) for the full, step-by-step procedure,
and **`mothership/AGENT_SPEC.md`** for the A2A design.

---

## The "unify forces" part (GLaDOS + Wheatley ↔ Pwnagotchi)

The Pi runs `mothership/pwnagotchi_a2a.py`, an A2A JSON-RPC peer on port `:8700`:

```
         A2A (JSON-RPC, bearer token)
   ┌─────────────┐  message/send   ┌──────────────────────┐
   │ GLaDOS      │ ───────────────▶│  pwnagotchi4b peer   │
   │ Hermes :9900│ ◀───────────────│  :8700 (this repo)   │
   └─────────────┘   tasks+artifacts│        │             │
   ┌─────────────┐  message/send   │  localhost           │
   │ Wheatley    │ ───────────────▶│  ┌─────────┐┌──────┐ │
   │ OpenClaw:18800│◀──────────────│  │pwnagotchi││fancy-│ │
   └─────────────┘                 │  │ API :8666││server│ │
                                   │  └─────────┘└:3699 ┘ │
                                   └──────────────────────┘
```

- **GLaDOS** (Hermes, `:9900`) and **Wheatley** (OpenClaw, `:18800`) are the
  *motherships*. Either can call `get_status`, `fetch_handshakes`, `set_mode`,
  `reboot`, `shutdown`, `toggle_plugin` on the Pi.
- The Pi reuses your existing seeds: **`pwnmothership`** (state schema) and
  **`fancyserver`** (the `127.0.0.1:3699` control socket) — so no new control
  protocol is invented; A2A is just the *remote* layer on top.
- Design fully specified by Wheatley in `mothership/AGENT_SPEC.md`; the endpoint
  is implemented in `mothership/pwnagotchi_a2a.py` and verified via
  `tests/test_a2a_roundtrip.py`.

---

## Why a custom display class?

Current `jayofelony/pwnagotchi` has **no `waveshare35b` display type**, and your
panel is an off-brand ILI9486. So `display/waveshare35b.py` subclasses pwnagotchi's
`DisplayImpl` and writes the rendered canvas to the Linux framebuffer
(`/dev/fb1`). Two backends are supported:

1. **fbcp-ili9341 (recommended, fast):** `juj/fbcp-ili9341` with the `ILI9486`
   target mirrors the Pi's framebuffer to the TFT over SPI via DMA. *Caveat:*
   it uses the deprecated DispmanX API — works on the **Pi 4** with the legacy
   GL driver; absent on Pi 5 / pure-KMS kernels. See `display/fbcp-ili9341/`.
2. **fbtft (fallback, slower but robust):** `dtoverlay=waveshare35b` (or
   `flexfb` + `fbtft_device`) drives `/dev/fb1` through the kernel framebuffer
   — works under KMS too.

Fancygotchi picks the display up automatically because it reads
`ui.display.type` — set it to `waveshare35b` in `config/config.toml`.

---

## Repo credits / reuse

- Base image & Pwnagotchi: [`jayofelony/pwnagotchi`](https://github.com/jayofelony/pwnagotchi) (64-bit, `noai` branch, v2.9.5.8).
- Fancygotchi: [`V0r-T3x/Fancygotchi`](https://github.com/V0r-T3x/Fancygotchi).
- Plugins: your own [`itsdarklikehell/pwnagotchi-plugins`](https://github.com/itsdarklikehell/pwnagotchi-plugins).
- Flash/provision base: your [`itsdarklikehell/pwnagotchi-control-center`](https://github.com/itsdarklikehell/pwnagotchi-control-center).
- Display backend: [`juj/fbcp-ili9341`](https://github.com/juj/fbcp-ili9341) (ILI9486 target).
- A2A bridge: designed jointly with **Wheatley (OpenClaw)** — see `mothership/AGENT_SPEC.md`.

## License

GPL-3.0 (inherits Pwnagotchi's license). See `LICENSE`.


---

## 🎥 Gource Visualization

De ontwikkelhistorie van dit project in een film:

<video src="https://raw.githubusercontent.com/itsdarklikehell/pwnagotchi4b/main/gource.mp4" controls width="100%"></video>

*De video wordt automatisch gegenereerd door de [Gource workflow](.github/workflows/gource.yml) bij elke push.*

Lokale video genereren:
```bash
gource --max-files 1000 --key -800x600 \
  --highlight-users --filename-time 3 --output-framerate 25 \
  -s 0.6 --multi-sampling --auto-skip-seconds 0.1 \
  --stop-at-end --hide mouse,progress -o gource.ppm

ffmpeg -y -r 15 -f image2pipe -vcodec ppm -i gource.ppm \
  -vcodec libx264 -preset medium -pix_fmt yuv420p \
  -crf 1 -threads 0 -bf 0 gource.mp4
```
