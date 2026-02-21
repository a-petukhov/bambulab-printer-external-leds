# Bambu Lab Printer External LED Controller

Pico W firmware that connects directly to a Bambu Lab P1S printer via MQTT/TLS
and drives an external LED strip + RGB status indicator.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Async firmware — button monitor, MQTT loop, connection manager |
| `mqtt_client.py` | Modified `umqtt.simple` with TLS `server_hostname` (SNI) support |
| `config.json` | Credentials — gitignored, lives only on the Pico W |
| `config.json.example` | Template for `config.json` |

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

1. **`task_button_monitor()`** (50ms poll) — always runs regardless of connectivity,
   toggles LED strip locally; sends chamber light command over MQTT when connected.
   Uses edge detection (falling edge) for debouncing.
2. **`task_mqtt_loop()`** (100ms poll) — `check_msg()` non-blocking read, parses
   `print.gcode_state` and `print.lights_report` from incoming printer JSON.
   Calls `gc.collect()` before `json.loads()`.
3. **`task_connection_manager()`** — three phases:
   - **WiFi:** connect with 15s timeout, blink white while disconnected, retry every 30s
   - **MQTT:** TLS handshake (~7s), fresh `SSLContext` per attempt, `gc.collect()` before TLS,
     blink red while disconnected, retry every 10s
   - **Maintenance:** ping at half keepalive interval (30s), detect WiFi loss

## MQTT Protocol

- Host: printer LAN IP, port 8883, TLS with `CERT_NONE` (self-signed cert)
- Username: `bblp`, password: printer's LAN access code
- Client ID: `pico_led_ctrl`
- Subscribe topic: `device/{serial}/report`
- Publish topic: `device/{serial}/request`
- Send `pushall` command once after connecting for initial full state
- Printer sends delta updates (only changed fields)
- Do NOT send `pushall` more than once per 5 minutes (causes P1 series lag)

### Chamber Light Command

```json
{"system": {"sequence_id": "0", "command": "ledctrl", "led_node": "chamber_light",
            "led_mode": "on", "led_on_time": 500, "led_off_time": 500,
            "loop_times": 0, "interval_time": 0}}
```

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

Copy `config.json.example` to `config.json` and fill in your values:

```json
{
    "wifi_ssid": "...",
    "wifi_password": "...",
    "printer_ip": "...",
    "printer_serial": "...",
    "printer_access_code": "..."
}
```

Hardcoded constants (never change): port 8883, username `bblp`, keepalive 60s.

## Deployment

```bash
mpremote cp mqtt_client.py :mqtt_client.py
mpremote cp main.py :main.py
mpremote cp config.json :config.json
```

## RGB Status Indicators

- **Blinking white** — WiFi connecting/disconnected
- **Blinking red** — WiFi connected, MQTT connecting/disconnected
- **Solid color** — connected, showing printer state (see color table above)
- **Off** — LED strip toggled off by button

## Constraints

- TLS handshake takes ~7 seconds on Pico W (one-time per connection)
- ~264KB RAM total, ~70-90KB free after MicroPython + TLS — no web server to save RAM
- Bambu Lab printer resets LAN access code on restart — update `config.json` and reboot Pico W
- `gc.collect()` before TLS operations and `json.loads()` to avoid OOM
