#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tecnonautica RS-485 to MQTT Bridge
Home Assistant Add-on Source Code
Handles connection with Yacht switches, dials, and alarms.
"""

import os
import sys
import json
import time
import serial
import threading
import paho.mqtt.client as mqtt

# Path to the persistent discovered boards config inside the HA container
DISCOVERY_FILE = "/data/discovered_boards.json"
OPTIONS_FILE = "/data/options.json"

# Load options or use defaults
config = {
    "usb_port": "/dev/ttyUSB0",
    "baud_rate": 19200,
    "scan_interval": 5,
    "mqtt_host": "core-mosquitto",
    "mqtt_port": 1883,
    "mqtt_username": "homeassistant_addon",
    "mqtt_password": "",
    "mqtt_base_topic": "tecnonautica"
}

if os.path.exists(OPTIONS_FILE):
    try:
        with open(OPTIONS_FILE, "r") as f:
            ha_options = json.load(f)
            config.update(ha_options)
            print(f"[BOOT] Caricate opzioni da Home Assistant: {ha_options}")
    except Exception as e:
        print(f"[BOOT ERROR] Errore di lettura options.json: {e}")

# Machine Types definitions
MACHINE_DEFS = {
    "T1": {"name": "TN222 Switch Panel 10ch", "switches": 10, "spie": 10, "analog": False, "alarms": 0},
    "T2": {"name": "TN218 Dashboard Card 6ch", "switches": 6, "spie": 6, "analog": False, "alarms": 0},
    "PM": {"name": "TN267 Instruments Panel", "switches": 6, "spie": 6, "analog": True, "alarms": 0},
    "AL": {"name": "TN234 Alarm Panel", "switches": 4, "spie": 4, "analog": False, "alarms": 16},
    "SP": {"name": "TN223 Warning Lights Panel", "switches": 0, "spie": 10, "analog": False, "alarms": 0},
    "SL": {"name": "TN224/TN239 Lights Board", "switches": 6, "spie": 6, "analog": False, "alarms": 0}
}

discovered_boards = {}

# Load persistent boards
if os.path.exists(DISCOVERY_FILE):
    try:
        with open(DISCOVERY_FILE, "r") as f:
            discovered_boards = json.load(f)
            print(f"[BOOT] Caricati {len(discovered_boards)} moduli salvati in precedenza.")
    except Exception as e:
        print(f"[BOOT ERROR] Errore di caricamento moduli salvati: {e}")

# RS-485 Serial Communication Lock & Setup
serial_lock = threading.Lock()
ser = None

def init_serial():
    global ser
    port = config["usb_port"]
    baud = config["baud_rate"]
    print(f"[SERIAL] Connessione a {port} a {baud} bps (8,N,1)...")
    try:
        # RS-485 19200 8N1
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.3
        )
        print("[SERIAL] Connessione seriale stabilita con successo!")
    except Exception as e:
        print(f"[SERIAL ERROR] Impossibile aprire la porta seriale {port}: {e}")
        print("[SERIAL INFO] L'add-on funzionerà in modalità di emulazione virtuale se la porta fisica non risponde.")
        ser = None

# Calculate XOR NMEA style Checksum
def calculate_checksum(msg_body: str) -> str:
    chk = 0
    for char in msg_body:
        chk ^= ord(char)
    # Returns 2-char hex uppercase string
    return f"{chk:02X}"

# Format message properly
def format_message(m_type: str, machine: str, addr: str, data: str) -> str:
    body = f"{m_type}{machine}{addr}{data}KK"
    chk = calculate_checksum(body)
    return f"[{body}*{chk}]"

# Parse incoming message
def parse_message(raw: str):
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    content = raw[1:-1]
    if "*" not in content:
        return None
    body, chk = content.rsplit("*", 1)
    
    if calculate_checksum(body) != chk.upper():
        print(f"[PROTOCOL] Warning: Checksum non valida per pacchetto: {raw}")
        return None
        
    m_type = body[0]
    if m_type == 'P': # PING message [PnnKK*cc]
        return {"type": "PING", "cycle": body[1:3]}
        
    # Standard formats
    machine = body[1:3]
    addr = body[3:5]
    data = body[5:]
    if data.endswith("KK"):
        data = data[:-2]
        
    return {
        "type": m_type,
        "machine": machine,
        "address": addr,
        "data": data,
        "raw": raw
    }

# Transmit command on the bus and get synchronous response
def write_and_read(m_type: str, machine: str, addr: str, data: str) -> str:
    global ser
    payload = format_message(m_type, machine, addr, data)
    
    with serial_lock:
        if not ser:
            # Emulation mode
            time.sleep(0.2)
            # Dummy responses for testing
            if m_type == 'Q' and data == 'ID':
                return format_message('A', machine, addr, f"ID114")
            return None
            
        try:
            ser.reset_input_buffer()
            # Send command
            print(f"[TX] {payload}")
            ser.write(payload.encode('ascii'))
            ser.flush()
            
            # Wait at least 180ms as instructed by PDF timing 2.1 to avoid overlapping
            time.sleep(0.18)
            
            # Read response
            response = ser.readline().decode('ascii', errors='ignore').strip()
            if response:
                print(f"[RX] {response}")
                return response
        except Exception as e:
            print(f"[SERIAL ERROR] Errore di scrittura/lettura bus: {e}")
            
    return None

# MQTT Setup & Auto-Discovery
try:
    # paho-mqtt >= 2.0.0
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, config["mqtt_base_topic"] + "_bridge")
except AttributeError:
    # paho-mqtt < 2.0.0
    mqtt_client = mqtt.Client(config["mqtt_base_topic"] + "_bridge")

def publish_discovery(addr, mach, b_def):
    """
    Sends MQTT discovery configs so Home Assistant automatically exposes 
    all Relays, Switches, Buttons, voltmeters and Alarms corresponding to found boards.
    """
    base_topic = config["mqtt_base_topic"]
    unique_node = f"tecnonautica_{addr}_{mach}"
    
    # Common device block
    device_info = {
        "identifiers": [unique_node],
        "name": f"Tecnonautica {mach} (Adr {addr})",
        "manufacturer": "Tecnonautica",
        "model": b_def["name"],
        "via_device": "tecnonautica_mqtt_bridge"
    }

    # 1. Output relay Switch entities (Switches)
    switches_count = b_def.get("switches", 0)
    for i in range(1, switches_count + 1):
        # State & Command topics
        relay_topic = f"{base_topic}/{addr}/relay_{i}"
        
        # Output relay Switch entity
        disc_topic = f"homeassistant/switch/{unique_node}/relay_{i}/config"
        payload = {
            "name": f"Canale {i} Interruttore",
            "state_topic": f"{relay_topic}/state",
            "command_topic": f"{relay_topic}/set",
            "unique_id": f"{unique_node}_relay_{i}",
            "device": device_info,
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:power"
        }
        mqtt_client.publish(disc_topic, json.dumps(payload), retain=True)

        # Clear legacy button sensors to keep Home Assistant UI pristine
        disc_btn = f"homeassistant/binary_sensor/{unique_node}/button_{i}/config"
        mqtt_client.publish(disc_btn, "", retain=True)

    # 2. Status Feedback Indicator Light entities (Spie)
    spie_count = b_def.get("spie", 0)
    for i in range(1, spie_count + 1):
        spia_topic = f"{base_topic}/{addr}/spia_{i}"
        disc_spia = f"homeassistant/binary_sensor/{unique_node}/spia_{i}/config"
        spia_payload = {
            "name": f"Spia Feedback {i}",
            "state_topic": f"{spia_topic}/state",
            "unique_id": f"{unique_node}_spia_{i}",
            "device": device_info,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "light",
            "icon": "mdi:led-on"
        }
        mqtt_client.publish(disc_spia, json.dumps(spia_payload), retain=True)

    # 3. Instruments panel: PM (Analog fields Volts/Amps)
    if b_def.get("analog", False):
        # Voltage sensor
        volt_disc = f"homeassistant/sensor/{unique_node}/voltage/config"
        volt_p = {
            "name": "Tensione Servizi",
            "state_topic": f"{base_topic}/{addr}/voltage/state",
            "unique_id": f"{unique_node}_voltage",
            "device": device_info,
            "unit_of_measurement": "V",
            "device_class": "voltage",
            "state_class": "measurement"
        }
        mqtt_client.publish(volt_disc, json.dumps(volt_p), retain=True)

        # Current sensor
        curr_disc = f"homeassistant/sensor/{unique_node}/current/config"
        curr_p = {
            "name": "Corrente Consumo",
            "state_topic": f"{base_topic}/{addr}/current/state",
            "unique_id": f"{unique_node}_current",
            "device": device_info,
            "unit_of_measurement": "A",
            "device_class": "current",
            "state_class": "measurement"
        }
        mqtt_client.publish(curr_disc, json.dumps(curr_p), retain=True)

    # 4. Alarm centralizer: AL (16 boolean alarms)
    alarms_count = b_def.get("alarms", 0)
    for i in range(1, alarms_count + 1):
        alarm_id = f"zone_{i}"
        disc_al = f"homeassistant/binary_sensor/{unique_node}/{alarm_id}/config"
        payload_al = {
            "name": f"Zona Allarme {i}",
            "state_topic": f"{base_topic}/{addr}/{alarm_id}/state",
            "unique_id": f"{unique_node}_{alarm_id}",
            "device": device_info,
            "device_class": "safety",
            "payload_on": "ON",
            "payload_off": "OFF"
        }
        mqtt_client.publish(disc_al, json.dumps(payload_al), retain=True)
        
    # Extra legacy mappings for AL navigation/anchor light switches for backward compatibility
    if mach == "AL":
        nav_disc = f"homeassistant/switch/{unique_node}/nav_light/config"
        nav_payload = {
            "name": "Luci di Navigazione",
            "state_topic": f"{base_topic}/{addr}/nav_light/state",
            "command_topic": f"{base_topic}/{addr}/nav_light/set",
            "unique_id": f"{unique_node}_nav_light",
            "device": device_info
        }
        mqtt_client.publish(nav_disc, json.dumps(nav_payload), retain=True)

        anc_disc = f"homeassistant/switch/{unique_node}/anchor_light/config"
        anc_payload = {
            "name": "Luce di Fonda",
            "state_topic": f"{base_topic}/{addr}/anchor_light/state",
            "command_topic": f"{base_topic}/{addr}/anchor_light/set",
            "unique_id": f"{unique_node}_anchor_light",
            "device": device_info
        }
        mqtt_client.publish(anc_disc, json.dumps(anc_payload), retain=True)

# Scan the bus from 00 to 32 to auto-discover boards
def scan_rs485_bus():
    print("[BUS_SCAN] Avvio scansione completa indirizzi RS-485 (da 00 a 32)...")
    global discovered_boards
    found_any = False
    
    # Iterate through potential addresses
    for addr_val in range(33):
        addr = f"{addr_val:02d}"
        for mach, b_def in MACHINE_DEFS.items():
            print(f"[BUS_SCAN] Controllo Indirizzo: {addr} [tipo {mach}]...")
            
            # Send ID Check query
            rx = write_and_read('Q', mach, addr, 'ID')
            if rx:
                parsed = parse_message(rx)
                if parsed and parsed["type"] == 'A':
                    firmware = parsed["data"]
                    print(f"[BUS_SCAN] RILEVATO modulo {mach} ad indirizzo {addr}! FW: {firmware}")
                    
                    # Store
                    discovered_boards[f"{addr}_{mach}"] = {
                        "address": addr,
                        "type": mach,
                        "firmware": firmware,
                        "model": b_def["name"],
                        "switches": b_def.get("switches", 0),
                        "spie": b_def.get("spie", 0),
                        "analog": b_def.get("analog", False),
                        "alarms": b_def.get("alarms", 0),
                        "last_seen": time.time()
                    }
                    found_any = True
                    
                    # Publish Discovery
                    publish_discovery(addr, mach, b_def)
                    
            # Small delay to keep bus clean and respect timing
            time.sleep(0.05)
            
    # Persist boards layout
    try:
        with open(DISCOVERY_FILE, "w") as f:
            json.dump(discovered_boards, f, indent=2)
        print("[BUS_SCAN] Scansione completata. Layout memorizzato correttamente.")
    except Exception as e:
        print(f"[BUS_SCAN ERROR] Impossibile memorizzare layout: {e}")
        
    return found_any

# Background polling process
def polling_loop():
    print("[POLLING] Avvio ciclo periodico di acquisizione canali e sensori...")
    base_topic = config["mqtt_base_topic"]
    
    while True:
        if not discovered_boards:
            print("[POLLING] Nessuna scheda trovata sul bus. In attesa di scansione o boot...")
            time.sleep(10)
            continue
            
        for key, board in list(discovered_boards.items()):
            addr = board["address"]
            mach = board["type"]
            b_def = MACHINE_DEFS.get(mach)
            if not b_def:
                continue
            
            switches_count = b_def.get("switches", 0)
            spie_count = b_def.get("spie", 0)
            alarms_count = b_def.get("alarms", 0)
            
            # 1. Query feedback state (FB) for outputs / spie (all boards except AL)
            if spie_count > 0 and mach != "AL":
                rx = write_and_read('Q', mach, addr, 'FB')
                if rx:
                    parsed = parse_message(rx)
                    if parsed and parsed["type"] == 'A':
                        status = parsed["data"]
                        for idx, char in enumerate(status):
                            ch_num = idx + 1
                            state = "ON" if char == '1' else "OFF"
                            if ch_num <= switches_count:
                                mqtt_client.publish(f"{base_topic}/{addr}/relay_{ch_num}/state", state, retain=True)
                            if ch_num <= spie_count:
                                mqtt_client.publish(f"{base_topic}/{addr}/spia_{ch_num}/state", state, retain=True)

            # 2. Query instruments analog data (ME)
            if b_def.get("analog", False):
                rx = write_and_read('Q', mach, addr, 'ME')
                if rx:
                    parsed = parse_message(rx)
                    if parsed and parsed["type"] == 'A':
                        data_payload = parsed["data"]
                        if 'A' in data_payload and 'B' in data_payload:
                            try:
                                part_a = data_payload.split('B')[0].replace('ME', '').replace('A', '') 
                                part_b = data_payload.split('B')[1]
                                
                                val_a = float(part_a) / 10.0
                                val_b = float(part_b) / 10.0
                                
                                mqtt_client.publish(f"{base_topic}/{addr}/voltage/state", f"{val_a:.1f}", retain=True)
                                mqtt_client.publish(f"{base_topic}/{addr}/current/state", f"{val_b:.1f}", retain=True)
                            except Exception as parse_ex:
                                print(f"[PARSE ERROR] Errore parsing pacchetto analogico: {parse_ex}")

            # 3. Query alarm statuses (AS) for AL board
            if alarms_count > 0:
                rx = write_and_read('Q', mach, addr, 'AS')
                if rx:
                    parsed = parse_message(rx)
                    if parsed and parsed["type"] == 'A':
                        status_str = parsed["data"].replace('AS', '')
                        for idx, char in enumerate(status_str):
                            if idx < alarms_count:
                                alarm_num = idx + 1
                                state = "ON" if char in ['A', 'R'] else "OFF"
                                mqtt_client.publish(f"{base_topic}/{addr}/zone_{alarm_num}/state", state, retain=True)

            # 4. Query lights statuses (LS) for AL board outputs
            if mach == "AL" and switches_count > 0:
                rx_lights = write_and_read('Q', mach, addr, 'LS')
                if rx_lights:
                    parsed_ls = parse_message(rx_lights)
                    if parsed_ls and parsed_ls["type"] == 'A':
                        data_ls = parsed_ls["data"].replace('LS', '')
                        # Handle up to switches_count/spie_count outputs
                        for idx, char in enumerate(data_ls):
                            ch_num = idx + 1
                            state = "ON" if char == '1' else "OFF"
                            if ch_num <= switches_count:
                                mqtt_client.publish(f"{base_topic}/{addr}/relay_{ch_num}/state", state, retain=True)
                            if ch_num <= spie_count:
                                mqtt_client.publish(f"{base_topic}/{addr}/spia_{ch_num}/state", state, retain=True)
                        
                        # Backward compatibility legacy mappings (e.g. first 2 states mapping anchor and nav lights)
                        if len(data_ls) >= 2:
                            mqtt_client.publish(f"{base_topic}/{addr}/anchor_light/state", "ON" if data_ls[0] == '1' else "OFF", retain=True)
                            mqtt_client.publish(f"{base_topic}/{addr}/nav_light/state", "ON" if data_ls[1] == '1' else "OFF", retain=True)

            time.sleep(0.3) # Avoid bus saturation, spacing packets elegantly
            
        time.sleep(config["scan_interval"])

# Handle MQTT Commands from Home Assistant (Subscribed)
def on_mqtt_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8').upper()
    topic = msg.topic
    print(f"[MQTT] Ricevuto set: {topic} -> {payload}")
    
    base_topic = config["mqtt_base_topic"]
    # Parsing Topic: e.g "tecnonautica/02/relay_1/set"
    parts = topic.split('/')
    if len(parts) < 4:
        return
        
    addr = parts[1]
    sub_device = parts[2]
    
    # Check scan execution command: "tecnonautica/command/scan"
    if addr == "command" and sub_device == "scan":
        print("[MQTT] Avvio scansione completa indirizzi richiesta tramite MQTT MQTT topic!")
        threading.Thread(target=scan_rs485_bus, daemon=True).start()
        return

    # Extract machine mapping
    board_matches = [b for b in discovered_boards.values() if b["address"] == addr]
    if not board_matches:
        print(f"[MQTT ERROR] Nessuna scheda registrata all'indirizzo {addr}")
        return
        
    board = board_matches[0]
    mach = board["type"]
    
    # 1. Action set Relays ON/OFF on TN222/TN218
    if sub_device.startswith("relay_"):
        try:
            ch_num = int(sub_device.split('_')[1])
            # Key mappings: x is key number (1...9, "0" as 10)
            key_num_char = "0" if ch_num == 10 else str(ch_num)
            
            # Send command packet S (COMMUTA RELÈ)
            # Syntax: [S MM aa Px KK *cc]
            # When we tell it 'Px', it toggles output or force state
            cmd_data = f"P{key_num_char}"
            rx = write_and_read('S', mach, addr, cmd_data)
            
            if rx:
                parsed = parse_message(rx)
                if parsed and parsed["type"] == 'C':
                    # Successfully confirmed! Feed back to state topic immediately
                    client.publish(f"{base_topic}/{addr}/relay_{ch_num}/state", payload, retain=True)
                    print(f"[MQTT CONFIRM] Canale {ch_num} su {addr} impostato a {payload} con successo!")
        except Exception as e:
            print(f"[MQTT ACTUATOR ERROR] {e}")

    # 2. Action set Lights Navigator / Anchor on TN234 AL
    elif sub_device in ["anchor_light", "nav_light"] and mach == "AL":
        cmd_code = "FD" if sub_device == "anchor_light" else "NA"
        rx = write_and_read('S', mach, addr, cmd_code)
        if rx:
            parsed = parse_message(rx)
            if parsed and parsed["type"] == 'C':
                client.publish(f"{base_topic}/{addr}/{sub_device}/state", payload, retain=True)
                print(f"[MQTT CONFIRM] {sub_device} su {addr} commutata!")

def on_mqtt_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connesso al broker MQTT di Home Assistant con codice: {rc}")
    base_topic = config["mqtt_base_topic"]
    
    # Subscribe to control sets
    client.subscribe(f"{base_topic}/+/+/set")
    client.subscribe(f"{base_topic}/command/scan")
    
    # Publish all discovery properties for recovered boards
    for entry in discovered_boards.values():
        addr = entry["address"]
        mach = entry["type"]
        b_def = MACHINE_DEFS.get(mach, {"name": "Discovered Board", "switches": 6, "spie": 6, "analog": False, "alarms": 0})
        publish_discovery(addr, mach, b_def)

# Main orchestrator Entry point
def main():
    init_serial()
    
    # Init MQTT connect
    try:
        if config["mqtt_username"]:
            mqtt_client.username_pw_set(config["mqtt_username"], config["mqtt_password"])
        
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect(config["mqtt_host"], config["mqtt_port"], 60)
        
        # Start MQTT loop thread
        mqtt_thread = threading.Thread(target=mqtt_client.loop_forever, daemon=True)
        mqtt_thread.start()
    except Exception as e:
        print(f"[MQTT ERROR] Avvio broker errato ({config['mqtt_host']}): {e}")

    # First general boot scan to populate system if empty!
    if not discovered_boards:
        print("[BOOT] Nessun modulo salvato trovato. Eseguo scansione iniziale bus completa...")
        scan_rs485_bus()
    else:
        print(f"[BOOT] Trovate {len(discovered_boards)} schede memorizzate. Salto scansione iniziale. Moduli guidati.")
        # Make sure they are discovered by publishing configs on start
        time.sleep(1)
        for entry in discovered_boards.values():
            addr = entry["address"]
            mach = entry["type"]
            b_def = MACHINE_DEFS.get(mach, {"name": "Discovered Board", "switches": 6, "spie": 6, "analog": False, "alarms": 0})
            publish_discovery(addr, mach, b_def)

    # Start polling loop thread
    poll_thread = threading.Thread(target=polling_loop, daemon=True)
    poll_thread.start()

    # Block main thread so background tasks manage flow
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("[INFO] Arresto add-on Tecnonautica RS485 Bridge...")
            sys.exit(0)

if __name__ == "__main__":
    main()
