# 📸 Plot Screenshots

Dieser Ordner enthält Beispiel-Screenshots der Auto_Offset Plots für die README.

## 📋 Benötigte Dateien:

1. **auto_offset_history.png**
   - Screenshot des History Plots
   - Zeigt mehrere Messungen über Zeit
   - Aus: `~/printer_data/config/Auto_Offset/Auswertung/auto_offset_history.png`

2. **auto_offset_current.png**
   - Screenshot des Current Plots
   - Zeigt Details einer einzelnen Messung
   - Aus: `~/printer_data/config/Auto_Offset/Auswertung/auto_offset_current.png`

## 🔧 So erstellst du die Screenshots:

1. Führe mehrere Messungen durch:
   ```gcode
   AUTO_OFFSET_START
   ```

2. Die Plots werden automatisch erstellt in:
   ```
   ~/printer_data/config/Auto_Offset/Auswertung/
   ```

3. Kopiere die PNG-Dateien hierher:
   ```bash
   cp ~/printer_data/config/Auto_Offset/Auswertung/auto_offset_*.png docs/images/
   ```

4. Commit & Push:
   ```bash
   git add docs/images/*.png
   git commit -m "Add plot screenshots"
   git push
   ```

## 📐 Empfohlene Größe:

- **Breite:** 1200-1600px (automatisch vom Script)
- **Format:** PNG
- **Qualität:** Hoch (für GitHub README)

## 🎨 Design:

Die Plots nutzen das **Shake&Tune Design**:
- Dunkler Hintergrund
- Orange/Cyan Farbschema
- Professionelle Achsenbeschriftung
- Grid für bessere Lesbarkeit
