# Bambu Lab Printer External LED Controller

MicroPython firmware for Raspberry Pi Pico W that connects directly to a Bambu Lab P1S printer over MQTT/TLS and controls an external LED strip and RGB status indicator.

## Features

- **Direct connection** — Pico W talks to the printer over LAN, no intermediary server needed
- **Physical button** — toggles the LED strip and printer chamber light; works offline
- **RGB status LED** — shows printer state at a glance:

| State              | Color  |
|--------------------|--------|
| Idle               | Blue   |
| Printing / Prepare | Green  |
| Paused             | Yellow |
| Finished           | Purple |
| Failed             | Red    |

- **Connection indicators** — blinking white = WiFi connecting, blinking red = MQTT connecting
- **Auto-reconnect** — recovers from WiFi or printer disconnections automatically

## Hardware

- Raspberry Pi Pico W
- LED strip on **GPIO 15** (digital on/off)
- Momentary push button on **GPIO 14** (active low, uses internal pull-up)
- Common-anode RGB LED on **GPIO 13** (R), **12** (G), **11** (B)

## Setup

1. Flash [MicroPython](https://micropython.org/download/RPI_PICO_W/) onto the Pico W

2. Copy `config.json.example` to `config.json` and fill in your values:

   ```json
   {
       "wifi_ssid": "YOUR_WIFI_SSID",
       "wifi_password": "YOUR_WIFI_PASSWORD",
       "printer_ip": "PRINTER_LAN_IP",
       "printer_serial": "YOUR_PRINTER_SERIAL",
       "printer_access_code": "YOUR_8CHAR_CODE"
   }
   ```

   You can find the printer serial, IP, and access code in Bambu Studio under the device settings, or on the printer's touchscreen under Settings > Network.

3. Upload files to the Pico W:

   ```bash
   mpremote cp mqtt_client.py :mqtt_client.py
   mpremote cp main.py :main.py
   mpremote cp config.json :config.json
   ```

4. Reboot the Pico W — it will start automatically.

## Notes

- The TLS handshake takes ~7 seconds on the Pico W (one-time per connection).
- The Bambu Lab printer resets the LAN access code when it restarts. You'll need to update `config.json` with the new code and reboot the Pico W.
