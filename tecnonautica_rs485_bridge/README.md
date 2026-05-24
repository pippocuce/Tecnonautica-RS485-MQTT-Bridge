# Tecnonautica RS485 ↔ MQTT Bridge - Home Assistant Add-on

Questo add-on consente di integrare i sistemi yachting e domotici del produttore **Tecnonautica** directly in Home Assistant, sfruttando la rete fisica interna **RS-485** e l'integrazione standard **MQTT**.

---

## 🔌 Collegamenti Fisici e Cablaggio (Bus RS-485)

Il bus di comunicazione Tecnonautica utilizza uno standard seriale RS-485 half-duplex (2 fili):

1. **Adattatore consigliato**: Convertitore USB a RS-485 (es. chip economico CH340 o FTDI FT232R).
2. **Cablaggio**:
   - Collega il pin **A** (spesso contrassegnato come **D+** o **Data+**) dell'adattatore USB al cavo **A** del bus Tecnonautica.
   - Collega il pin **B** (spesso contrassegnato come **D-** o **Data-**) dell'adattatore USB al cavo **B** del bus Tecnonautica.
   - Si raccomanda di collegare la calza schermata (GND) se presente per evitare disturbi generati da alternatori o inverter di bordo.
3. Elenco parametri fisici seriali della scheda:
   - **Baudrate**: 19200 bps
   - **Data Bits**: 8
   - **Parità**: Nessuna (N)
   - **Stop Bits**: 1
   - **Flusso**: Nessun controllo hardware/software

---

## 🛠️ Come Installare l'Add-on in Home Assistant

Segui questi passaggi per installare manualmente l'add-on sul tuo sistema Home Assistant:

### Metodo 1: Copia Manuale Cartella (Custom Add-ons)
1. Connettiti a Home Assistant in rete tramite **Samba Share**, **FTP**, o tramite l'add-on **Studio Code Server**.
2. Identifica o crea la cartella `/addons` nella directory root del tuo sistema (accanto alle cartelle `config`, `share`, ecc. di Home Assistant).
3. Crea una nuova sottocartella `/addons/tecnonautica_bridge`.
4. Copia al suo interno tutti i file che trovi configurati qui:
   - `config.yaml`
   - `Dockerfile`
   - `run.sh`
   - `main.py`
5. Vai nel portale di Home Assistant e naviga su: **Impostazioni** ➔ **Componenti Aggiuntivi** ➔ **Raccolta di Componenti Aggiuntivi** (in basso a destra).
6. Fai click sui tre puntini verticali nell'angolo in alto a destra e premi **Aggiorna** (Reload).
7. Vedrai apparire la sezione **Add-on Locali** (Local Add-ons). Fai click su **Tecnonautica RS485 MQTT Bridge** e premi **INSTALLA**.

---

## ⚙️ Configurazione dei Parametri dell'Add-on

Una volta completata l'installazione, configura i campi prima di avviare l'add-on:

1. **Porta USB Serial**: Imposta il path associato al tuo convertitore (es. `/dev/ttyUSB0` o `/dev/serial/by-id/...`).
2. **Broker MQTT**: Hostname o indirizzo IP del broker (di default integrato in HA con l'add-on Mosquitto, quindi imposta `core-mosquitto`).
3. **Frequenza di Polling**: Intervallo in secondi tra i cicli di interrogazione dei dispositivi virtuali o fisici (es. `5` secondi).

---

## 🔍 Scansione Automatica ed Auto-Discovery

- Al **primo avvio dell'Add-on**, questo effettuerà in modo autonomo un ciclo completo di scansione degli indirizzi da `00` a `32` per verificare quali schede rispondono.
- Le schede rilevate vengono memorizzate temporaneamente in `/data/discovered_boards.json`.
- Per forzare una scansione manuale in qualsiasi momento o dopo aver aggiunto un nuovo pannello, puoi semplicemente pubblicare un payload vuoto o `SCAN` sul topic MQTT predestinato: `tecnonautica/command/scan`.
- Tutte le luci, relè, allarmi, voltmetri e pulsanti fisici appariranno istantaneamente come entità e dispositivi nella tua dashboard di Home Assistant sotto l'integrazione **MQTT**!
