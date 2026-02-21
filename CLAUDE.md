# Bambu Lab Printer External LED Controller

Pico W firmware that connects directly to a Bambu Lab P1S printer via MQTT/TLS
and drives an external LED strip + RGB status indicator.

## Hardware

- **Pico W** — Raspberry Pi Pico W running MicroPython
- **LED strip** — pin 15, digital on/off (1 = on, 0 = off)
- **Button** — pin 14, active low with internal pull-up
- **RGB LED** — common-anode, PWM at 10kHz, inverted duty cycle (65535 = off, 0 = full brightness)
  - Red: pin 13
  - Green: pin 12
  - Blue: pin 11

## Architecture

Three `uasyncio` tasks run concurrently:

1. **Button monitor** (50ms poll) — always runs, toggles LED strip locally;
   sends chamber light command over MQTT when connected
2. **MQTT loop** (100ms poll) — `check_msg()` non-blocking read, parses
   `print.gcode_state` and `print.lights_report` from printer JSON
3. **Connection manager** — handles WiFi connect/retry, MQTT TLS handshake,
   keepalive pings, and reconnection

## MQTT Protocol

- Host: printer LAN IP, port 8883, TLS with `CERT_NONE` (self-signed cert)
- Username: `bblp`, password: printer's LAN access code
- Subscribe topic: `device/{serial}/report`
- Publish topic: `device/{serial}/request`
- Send `{"pushing": {"sequence_id": "0", "command": "pushall"}}` once after
  connecting to get initial full state
- Delta updates: printer sends only changed fields — merge into local state
- Do NOT send `pushall` more than once per 5 minutes (causes P1 series lag)

### Gcode State to RGB Color Mapping

| gcode_state        | RGB Color |
|--------------------|-----------|
| RUNNING / PREPARE  | Green     |
| IDLE               | Blue      |
| PAUSE              | Yellow    |
| FINISH             | Purple    |
| FAILED             | Red       |

RGB LED turns off when LED strip is off (user toggled lights off).

## Configuration

Config is stored in `config.json` on the Pico W filesystem:

```json
{
    "wifi_ssid": "...",
    "wifi_password": "...",
    "printer_ip": "...",
    "printer_serial": "...",
    "printer_access_code": "..."
}
```

Hardcoded constants (never change): port 8883, username "bblp", keepalive 60s.

## Deployment

```bash
mpremote cp mqtt_client.py :mqtt_client.py
mpremote cp main.py :main.py
mpremote cp config.json :config.json
# Delete old config module if present:
mpremote rm :config.py
```

## Constraints

- TLS handshake takes ~7 seconds on Pico W (one-time per connection)
- ~264KB RAM total, ~70-90KB free after MicroPython + TLS
- No web server — saves ~30-50KB RAM
- Bambu Lab printer resets LAN access code on restart — user must update
  `config.json` and reboot Pico W
- `gc.collect()` before TLS operations and `json.loads()` to avoid OOM
