import gc
import json
import network
import ssl
import time
import uasyncio as asyncio
from machine import Pin, PWM
from mqtt_client import MQTTClient

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
with open("config.json") as f:
    config = json.load(f)

WIFI_SSID = config["wifi_ssid"]
WIFI_PASSWORD = config["wifi_password"]
PRINTER_IP = config["printer_ip"]
PRINTER_SERIAL = config["printer_serial"]
PRINTER_ACCESS_CODE = config["printer_access_code"]

MQTT_PORT = 8883
MQTT_USER = "bblp"
MQTT_KEEPALIVE = 60
TOPIC_REPORT = "device/{}/report".format(PRINTER_SERIAL)
TOPIC_REQUEST = "device/{}/request".format(PRINTER_SERIAL)

# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------
led_strip = Pin(15, Pin.OUT)
button = Pin(14, Pin.IN, Pin.PULL_UP)

PWM_FREQ = 10000
pwm_r = PWM(Pin(13), freq=PWM_FREQ)
pwm_g = PWM(Pin(12), freq=PWM_FREQ)
pwm_b = PWM(Pin(11), freq=PWM_FREQ)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
printer_gcode_state = "IDLE"
led_strip_on = False
mqtt_client = None
mqtt_connected = False
wifi_connected = False
wlan = None

# ---------------------------------------------------------------------------
# RGB helpers (common-anode: 65535 = off, 0 = full brightness)
# ---------------------------------------------------------------------------
def set_color(r, g, b):
    pwm_r.duty_u16(65535 - r)
    pwm_g.duty_u16(65535 - g)
    pwm_b.duty_u16(65535 - b)


def rgb_off():
    set_color(0, 0, 0)


STATE_COLORS = {
    "RUNNING":  (0, 65535, 0),      # green
    "PREPARE":  (0, 65535, 0),      # green
    "IDLE":     (0, 0, 65535),      # blue
    "PAUSE":    (65535, 65535, 0),   # yellow
    "FINISH":   (32768, 0, 32768),  # purple
    "FAILED":   (65535, 0, 0),      # red
}


def update_rgb():
    """Set RGB LED based on current printer state. Off when strip is off."""
    if not led_strip_on:
        rgb_off()
        return
    color = STATE_COLORS.get(printer_gcode_state, (0, 0, 65535))
    set_color(*color)

# ---------------------------------------------------------------------------
# MQTT message handler
# ---------------------------------------------------------------------------
def on_mqtt_message(topic, msg):
    global printer_gcode_state, led_strip_on
    try:
        gc.collect()
        data = json.loads(msg)
    except (ValueError, MemoryError) as e:
        print("JSON parse error:", e)
        return

    p = data.get("print", {})

    gcode_state = p.get("gcode_state")
    if gcode_state is not None:
        printer_gcode_state = gcode_state.upper()
        print("State:", printer_gcode_state)

    lights = p.get("lights_report")
    if lights is not None and len(lights) > 0:
        mode = lights[0].get("mode")
        if mode is not None:
            new_state = mode == "on"
            if new_state != led_strip_on:
                led_strip_on = new_state
                led_strip.value(1 if led_strip_on else 0)
                print("Light:", "on" if led_strip_on else "off")

    update_rgb()

# ---------------------------------------------------------------------------
# MQTT publish helper
# ---------------------------------------------------------------------------
def send_chamber_light_command(on):
    """Send chamber light toggle to printer."""
    global mqtt_client, mqtt_connected
    if not mqtt_connected or mqtt_client is None:
        return
    cmd = json.dumps({
        "system": {
            "sequence_id": "0",
            "command": "ledctrl",
            "led_node": "chamber_light",
            "led_mode": "on" if on else "off",
            "led_on_time": 500,
            "led_off_time": 500,
            "loop_times": 0,
            "interval_time": 0
        }
    })
    try:
        mqtt_client.publish(TOPIC_REQUEST, cmd)
    except Exception as e:
        print("Publish error:", e)
        mqtt_connected = False


def send_pushall():
    """Request full state dump from printer."""
    global mqtt_client, mqtt_connected
    if not mqtt_connected or mqtt_client is None:
        return
    cmd = json.dumps({
        "pushing": {
            "sequence_id": "0",
            "command": "pushall"
        }
    })
    try:
        mqtt_client.publish(TOPIC_REQUEST, cmd)
        print("Sent pushall")
    except Exception as e:
        print("Pushall error:", e)
        mqtt_connected = False

# ---------------------------------------------------------------------------
# Task 1: Button monitor — always runs regardless of connectivity
# ---------------------------------------------------------------------------
async def task_button_monitor():
    global led_strip_on
    prev = 1  # button not pressed (active low, pull-up)
    while True:
        cur = button.value()
        # Detect falling edge (button press)
        if prev == 1 and cur == 0:
            led_strip_on = not led_strip_on
            led_strip.value(1 if led_strip_on else 0)
            update_rgb()
            print("Button -> strip", "on" if led_strip_on else "off")
            # Send MQTT command if connected
            send_chamber_light_command(led_strip_on)
        prev = cur
        await asyncio.sleep_ms(50)

# ---------------------------------------------------------------------------
# Task 2: MQTT message loop — checks for incoming messages
# ---------------------------------------------------------------------------
async def task_mqtt_loop():
    global mqtt_client, mqtt_connected
    while True:
        if mqtt_connected and mqtt_client is not None:
            try:
                mqtt_client.check_msg()
            except Exception as e:
                print("MQTT recv error:", e)
                mqtt_connected = False
        await asyncio.sleep_ms(100)

# ---------------------------------------------------------------------------
# Task 3: Connection manager — WiFi + MQTT connect/reconnect/keepalive
# ---------------------------------------------------------------------------
async def task_connection_manager():
    global wlan, wifi_connected, mqtt_client, mqtt_connected

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    last_ping = time.time()

    while True:
        # --- Phase 1: WiFi ---
        if not wlan.isconnected():
            wifi_connected = False
            mqtt_connected = False
            print("WiFi connecting...")
            try:
                wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            except OSError:
                pass
            # Wait up to 15 seconds, blinking white
            deadline = time.time() + 15
            while not wlan.isconnected() and time.time() < deadline:
                set_color(65535, 65535, 65535)
                await asyncio.sleep_ms(500)
                rgb_off()
                await asyncio.sleep_ms(500)
            if wlan.isconnected():
                wifi_connected = True
                print("WiFi connected:", wlan.ifconfig())
            else:
                print("WiFi failed, retry in 30s")
                # Blink white for 30 seconds then retry
                end = time.time() + 30
                while time.time() < end:
                    set_color(65535, 65535, 65535)
                    await asyncio.sleep_ms(500)
                    rgb_off()
                    await asyncio.sleep_ms(1000)
                continue

        # --- Phase 2: MQTT ---
        if not mqtt_connected:
            print("MQTT connecting...")
            # Blink red while attempting
            set_color(65535, 0, 0)
            await asyncio.sleep_ms(200)
            rgb_off()
            await asyncio.sleep_ms(200)

            gc.collect()
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.verify_mode = ssl.CERT_NONE
                gc.collect()
                client = MQTTClient(
                    client_id="pico_led_ctrl",
                    server=PRINTER_IP,
                    port=MQTT_PORT,
                    user=MQTT_USER,
                    password=PRINTER_ACCESS_CODE,
                    keepalive=MQTT_KEEPALIVE,
                    ssl=ctx,
                )
                client.set_callback(on_mqtt_message)
                client.connect(timeout=15)
                client.subscribe(TOPIC_REPORT)
                mqtt_client = client
                mqtt_connected = True
                last_ping = time.time()
                print("MQTT connected")
                send_pushall()
                update_rgb()
            except Exception as e:
                print("MQTT connect error:", e)
                mqtt_connected = False
                # Wait before retry, blinking red
                end = time.time() + 10
                while time.time() < end:
                    set_color(65535, 0, 0)
                    await asyncio.sleep_ms(500)
                    rgb_off()
                    await asyncio.sleep_ms(1000)
                continue

        # --- Phase 3: Maintenance ---
        # Check WiFi still up
        if not wlan.isconnected():
            wifi_connected = False
            mqtt_connected = False
            print("WiFi lost")
            continue

        # Ping at half keepalive interval
        now = time.time()
        if mqtt_connected and (now - last_ping) >= MQTT_KEEPALIVE // 2:
            try:
                mqtt_client.ping()
                last_ping = now
            except Exception as e:
                print("Ping error:", e)
                mqtt_connected = False
                continue

        await asyncio.sleep(1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    asyncio.create_task(task_button_monitor())
    asyncio.create_task(task_mqtt_loop())
    asyncio.create_task(task_connection_manager())
    # Keep main alive
    while True:
        await asyncio.sleep(60)

rgb_off()
led_strip.value(0)
print("Starting LED controller...")
asyncio.run(main())
