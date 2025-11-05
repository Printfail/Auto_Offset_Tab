 # 🎯 Klipper Auto Z-Offset

Automatische Z-Offset Messung für Klipper

## ✨ Features

- 🚀 **schnelle Messungen**
- 🎯 **Hochpräzise** (±0.0075mm mit 6 Nachkommastellen)
- 📊 **Delta-Offset System** - Korrekte Berechnung bei mehrfachen Messungen
- 🧪 **Multi-Sensor Support** (TAP, Endstops, MMU, Custom MCU)
- 📈 **Plots** - History & Current Plots
- 🔧 **3 Debug-Level** (0=Clean, 1=Details, 2=Maximum)
- ⚡ **Optimierte 2. Messung** - Nutzt gespeicherte Werte

---

## 📈 Plots & Visualisierung

Das Modul erstellt automatisch **professionelle Plots** deiner Z-Offset Messung:

### 📊 History Plot
Zeigt alle bisherigen Messungen über die Zeit - perfekt um Trends zu erkennen:

![History Plot](docs/images/auto_offset_history.png)

### 🎯 Current Plot  
Zeigt detaillierte Statistiken der aktuellen Messung:

![Current Plot](docs/images/auto_offset_current.png)

**Plot Features:**
- 📊 Automatische CSV-Speicherung aller Messungen
- 📈 Trend-Erkennung über Zeit (History)
- 🎨 Shake&Tune inspiriertes Design
- 📁 Speicherort: `~/printer_data/config/Auto_Offset/Auswertung/`
- 🖼️ PNG-Export für Mainsail/Fluidd Ansicht

---

## 🚀 Installation

### **Methode 1: One-Liner (schnell)** ⚡
```bash
curl -sSL https://raw.githubusercontent.com/Printfail/Auto_Offset_Tab/main/install.sh | bash
```

### **Methode 2: Manuell (empfohlen)** 📦
```bash
cd ~
git clone https://github.com/Printfail/Auto_Offset_Tab.git
cd Auto_Offset_Tab
chmod +x install.sh  # Execute-Rechte setzen
./install.sh
```

**Das Menü bietet folgende Optionen:**

| Option | Beschreibung |
|--------|--------------|
| **1️⃣ Install** | Installiert Auto_Offset zum ersten Mal (Python-Modul, Config-Dateien) |
| **2️⃣ Update** | Aktualisiert das Python-Modul (bei Updates via `git pull`) |
| **3️⃣ Uninstall** | Entfernt Auto_Offset komplett (optional: auch Config löschen) |
| **4️⃣ Status** | Zeigt Installationsstatus (Python-Modul, Config, Klipper) |
| **5️⃣ Exit** | Beendet das Menü |

> 💡 **Tipp:** Methode 1 (One-Liner) installiert automatisch ohne Menü!

---

### **printer.cfg anpassen**
```ini
# Füge hinzu:
[include Auto_Offset/Auto_Offset_Variables.cfg]

# Falls noch nicht vorhanden:
[save_variables]
filename: ~/printer_data/config/variables.cfg
```

### **Anpassen & Starten**

Bearbeite `~/printer_data/config/Auto_Offset/Auto_Offset_Variables.cfg`:
- `measure_x` / `measure_y` (Bett-Mitte!)
- `sensor_offset_path` (dein Sensor)
- `led_name`, `clean_macro` (optional)

```gcode
RESTART
AUTO_OFFSET_START
```

---

## 📖 Verwendung

```gcode
# Standard
AUTO_OFFSET_START

# Mit eigenen Temperaturen
AUTO_OFFSET_START NOZZLE_TEMP=200 BED_TEMP=60

# Schnell (kalt)
AUTO_OFFSET_START HEAT=0 QGL=0 CLEAN=0

# Debug
AUTO_OFFSET_START DEBUG=2
```

**Verfügbare Parameter:** `HEAT`, `NOZZLE_TEMP`, `BED_TEMP`, `QGL`, `CLEAN`, `ACCURACY_CHECK`, `TRIGGER_DISTANCE`, `OFFSET_MEASURE`, `DEBUG`

### 🎯 Delta-Offset System

**Warum wichtig?** Bei mehrfachen Messungen (z.B. nach Düsenwechsel, Wartung) würde ein normales Makro den alten Offset einfach überschreiben und könnte zu falschen Werten führen.

**Unsere Lösung:** Das Modul berechnet **Delta-Offsets** - es erkennt was sich geändert hat und wendet nur die Differenz an:
- **1. Messung:** Neuer Offset wird komplett gespeichert
- **2.+ Messung:** Nur die **Differenz** zum vorherigen Offset wird angewendet
- **Kein doppeltes Zählen!** Alter Offset wird automatisch berücksichtigt

**Beispiel:**
```
1. Messung: -0.6675 mm → SAVE_CONFIG
2. Messung: -0.6500 mm → Delta: +0.0175 mm
   → SET_GCODE_OFFSET Z=-0.0175 mm (Runtime)
   → Korrekt! Kein doppeltes Addieren!
```

### 🔍 Debug Levels

| Level | Zielgruppe | Ausgabe | Befehl |
|-------|-----------|---------|--------|
| **0** | Normale User | Nur wichtigste Infos (Schaltabstand, Z-Offset, Delta) | `AUTO_OFFSET_START DEBUG=0` |
| **1** | Troubleshooting | + Delta-Berechnung, Offset-Vergleich, Kategorien | `AUTO_OFFSET_START DEBUG=1` |
| **2** | Entwickler | + MCU States, Bewegungen, Sensor-Queries, alle Details | `AUTO_OFFSET_START DEBUG=2` |

---

## 🔧 Wichtige Einstellungen

```ini
[auto_offset]
measure_x: 175.0              # Bett-Mitte X
measure_y: 175.0              # Bett-Mitte Y
sensor_offset_path: mmu.sensors.toolhead  # Dein Sensor
led_name: Licht               # LED-Name (optional)
clean_macro: BLOBIFIER_CLEAN  # Reinigung (optional)
```

**Sensor-Optionen:**
- `mmu.sensors.toolhead` (MMU)
- `probe` (TAP)
- `endstop.z` (Z-Endstop)

---

## 📈 Plots

Automatisch erstellte Plots:

**Current Plot:**
- Probe Accuracy Samples (gezoomt)
- Measurement Overview (2 Balken: Trigger Distance, Z-Offset)
- Statistics Table

**History Plot:**
- Z-Offset über Zeit
- Trigger Distance über Zeit
- Temperaturen (Nozzle/Bed)

Plots werden gespeichert in: `~/printer_data/config/Auto_Offset/Auswertung/`

---

## ⚙️ How It Works

### 📋 Messprozess

| Schritt | Aktion | Beschreibung |
|---------|--------|-------------|
| 1️⃣ | **Homing** | Sicherer Ausgangspunkt |
| 2️⃣ | **Heizen** (optional) | Thermische Stabilität |
| 3️⃣ | **QGL** (optional) | Ebenes Bett |
| 4️⃣ | **Reinigung** (optional) | Saubere Düse |
| 5️⃣ | **Probe Accuracy** | Qualitätssicherung (5 Samples) |
| 6️⃣ | **Trigger Distance** | TAP Schaltabstand (1.25µm Präzision) |
| 7️⃣ | **Sensor Offset** | Custom Sensor (10µm Präzision) |
| 8️⃣ | **Delta-Berechnung** | `delta = neu - alt` → Vorzeichen umkehren |
| 9️⃣ | **SET_GCODE_OFFSET** | Runtime-Anpassung |
| 🔟 | **SAVE_CONFIG** | Dauerhaftes Speichern |

### 💡 Intelligente Features

- ⚡ **Gespeicherte Startposition** - 2. Messung fährt direkt zur letzten Position (schnell!)
- 🎯 **Delta-Offset** - Verhindert doppeltes Zählen bei mehrfachen Messungen
- 📊 **6 Nachkommastellen** - Höhere Präzision für Analysen

---

## 🔍 Fehlersuche

### Häufige Fehler

**"Unknown command AUTO_OFFSET_START"**
- → Prüfe ob `auto_offset.py` in `~/klipper/klippy/extras/` liegt
- → Führe `FIRMWARE_RESTART` aus

**"Could not load saved variables"**
- → Füge `[save_variables]` in `printer.cfg` hinzu
- → Prüfe Pfad: `filename: ~/printer_data/config/variables.cfg`

**Debug:** Nutze `AUTO_OFFSET_START DEBUG=2` für maximale Details

---

## 💬 Support

- [GitHub Issues](https://github.com/Printfail/Auto_Offset_Tab/issues)
- [GitHub Discussions](https://github.com/Printfail/Auto_Offset_Tab/discussions)

---

## 📄 Lizenz

GNU GPLv3 - siehe [LICENSE](LICENSE)

---

Made with ❤️ for the Klipper Community
