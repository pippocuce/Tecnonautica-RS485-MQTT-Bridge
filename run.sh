#!/usr/bin/env bash
# ==============================================================================
# Home Assistant Add-on: Tecnonautica RS485 MQTT Bridge
# Startup script
# ==============================================================================

echo "--------------------------------------------------------"
echo "  Tecnonautica RS485 MQTT Bridge Add-on"
echo "--------------------------------------------------------"

if [ -f /data/options.json ]; then
    echo "[INFO] Opzioni dell'add-on caricate da /data/options.json"
else
    echo "[WARNING] File /data/options.json non trovato. Saranno usati i valori di default."
fi

# Avvia l'applicazione seriale principale
echo "[INFO] Avvio script di comunicazione Python..."
python3 -u main.py
