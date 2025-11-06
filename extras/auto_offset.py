# Auto Z-Offset Measurement System for Klipper
# Copyright (C) 2025
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Includes integrated ProbeSilent for silent probe querying

import logging
import os
import csv
from datetime import datetime

# Matplotlib for plotting (optional)
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.info("Matplotlib not available - plots disabled")

#####################################################################
# PROBE SILENT - Silent Probe Wrapper
#####################################################################

class ProbeSilent:
    """Silent wrapper around the existing [probe].
    Registers QUERY_PROBE_SILENT without console output."""
    
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reference = config.get('reference', 'probe')
        self.last_query = None
    
    def get_probe(self):
        return self.printer.lookup_object(self.reference)
    
    def query_and_update(self, gcmd=None):
        """Query probe state silently (no console output)"""
        probe = self.get_probe()
        res = probe.mcu_probe.query_endstop(
            self.printer.lookup_object('toolhead').get_last_move_time()
        )
        # Store result locally and update original probe state
        self.last_query = res
        try:
            probe.cmd_helper.last_state = res
        except Exception:
            pass
        try:
            setattr(probe, "last_query", res)
        except Exception:
            pass
        return res
    
    def get_status(self, eventtime=None):
        probe = self.get_probe()
        return probe.get_status(eventtime)

#####################################################################
# AUTO OFFSET - Main Measurement System
#####################################################################

class AutoOffset:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.gcode = self.printer.lookup_object('gcode')
        self.reactor = self.printer.get_reactor()
        
        # Objects (loaded in _handle_ready)
        self.toolhead = None
        self.probe = None
        self.save_variables = None
        
        # Load ALL configuration from [auto_offset]
        self.debug_level = config.getint('debug_level', 1)
        self.show_warnings = config.getint('show_warnings', 1)
        self.led_name = config.get('led_name', 'Licht')
        self.clean_macro = config.get('clean_macro', 'BLOBIFIER_CLEAN')
        
        # Process control flags
        self.temp_enable = config.getint('temp_enable', 1)
        self.qgl_enable = config.getint('qgl_enable', 1)
        self.clean_enable = config.getint('clean_enable', 1)
        self.accuracy_check_enable = config.getint('accuracy_check_enable', 1)
        self.trigger_distance_enable = config.getint('trigger_distance_enable', 1)
        self.offset_measure_enable = config.getint('offset_measure_enable', 1)
        
        # Positions
        self.park_x = config.getfloat('park_x', 175.0)
        self.park_y = config.getfloat('park_y', 350.0)
        self.park_z = config.getfloat('park_z', 20.0)
        self.measure_x = config.getfloat('measure_x', 175.0)
        self.measure_y = config.getfloat('measure_y', 175.0)
        self.measure_z = config.getfloat('measure_z', 5.0)
        
        # Temperatures
        self.preheat_nozzle_temp = config.getfloat('preheat_nozzle_temp', 150)
        self.preheat_bed_temp = config.getfloat('preheat_bed_temp', 110)
        
        # Probe Accuracy
        self.probe_samples = config.getint('probe_samples', 5)
        self.probe_z_start = config.getfloat('probe_z_start', 2.0)
        self.probe_tolerance = config.getfloat('probe_tolerance', 0.020)
        self.probe_speed = config.getfloat('probe_speed', 15)
        
        # Trigger Distance
        self.trigger_distance_max = config.getfloat('trigger_distance_max', 0.15)
        
        # Sensor Offset - flexible sensor selection
        self.sensor_pin = config.get('sensor_pin', None)  # Custom pin (optional)
        self.sensor_offset_path = config.get('sensor_offset_path', None)  # Existing sensor
        self.sensor_offset_search_max = config.getfloat('sensor_offset_search_max', 5.0)
        self.sensorhub_safety_percent = config.getfloat('sensorhub_safety_percent', 25)
        
        # Statistics & Maintenance
        self.measurement_count_milestone = config.getint('measurement_count_milestone', 10)
        
        # Plot & Visualization
        self.create_plot = config.getint('create_plot', 1)
        self.plot_path = config.get('plot_path', '~/printer_data/config/Auto_Offset/Auswertung/')
        self.plot_history_count = config.getint('plot_history_count', 10)
        
        # Runtime State
        self.abort_active = False
        self.tap_distance_old = 0.0
        self.tap_distance_new = 0.0
        self.sensor_offset_value = 0.0
        self.sensor_offset_start_z = 0.0
        self.macro_execution_count = 0
        
        # Initialize debug_level_rt BEFORE _setup_custom_sensor (which calls _debug)
        self.debug_level_rt = self.debug_level
        
        # Create custom sensor if sensor_pin is configured
        # (must be AFTER runtime params initialization because _setup_custom_sensor calls _debug)
        self.custom_sensor = None
        self.custom_sensor_mcu = None
        if self.sensor_pin:
            self._setup_custom_sensor(config)
        
        # Fallback to sensor_offset_path
        if not self.sensor_pin and not self.sensor_offset_path:
            raise config.error("Either 'sensor_pin' or 'sensor_offset_path' must be specified")
        
        # Register commands manually (double underscore in function = single underscore in command)
        self.gcode.register_command(
            '_AUTO_OFFSET_START',
            self.cmd__AUTO_OFFSET_START,
            desc=self.cmd__AUTO_OFFSET_START.__doc__
        )
        self.gcode.register_command(
            '_AUTO_OFFSET_ABORT',
            self.cmd__AUTO_OFFSET_ABORT,
            desc=self.cmd__AUTO_OFFSET_ABORT.__doc__
        )
        
        # Register ready handler
        self.printer.register_event_handler("klippy:ready", self._handle_ready)
    
    def _setup_custom_sensor(self, config):
        """Setup custom sensor from sensor_pin configuration as real MCU endstop"""
        pin = self.sensor_pin
        
        # Setup pin as MCU endstop directly
        ppins = self.printer.lookup_object('pins')
        self.custom_sensor_mcu = ppins.setup_pin('endstop', pin)
        
        # Store for later use
        self.custom_sensor = self.custom_sensor_mcu
        
        # Override sensor_offset_path to indicate we use custom sensor
        self.sensor_offset_path = 'custom_mcu_endstop'
        
        self._debug("SENSOR_SETUP", 1, f"✅ Custom MCU endstop created: {pin} → Direct MCU endstop")
    
    def _handle_ready(self):
        """Called when Klipper is ready"""
        self.toolhead = self.printer.lookup_object('toolhead')
        self.probe = self.printer.lookup_object('probe')
        
        # Load saved values
        try:
            self.save_variables = self.printer.lookup_object('save_variables')
            all_vars = self.save_variables.allVariables
            self.tap_distance_old = all_vars.get('tap_last_distance', 0.0)
            self.sensor_offset_value = all_vars.get('sensor_offset_value', 0.0)
            self.sensor_offset_start_z = all_vars.get('sensor_offset_start_z', 0.0)
            self.macro_execution_count = all_vars.get('macro_execution_count', 0)
        except Exception as e:
            logging.warning(f"Could not load saved variables: {e}")
    
    def cmd__AUTO_OFFSET_START(self, gcmd):
        """Main command - parses parameters and starts measurement (called as _AUTO_OFFSET_START)"""
        # Parse parameters
        heat = gcmd.get('HEAT', str(self.temp_enable)).upper()
        qgl = gcmd.get('QGL', str(self.qgl_enable)).upper()
        clean = gcmd.get('CLEAN', str(self.clean_enable)).upper()
        accuracy = gcmd.get('ACCURACY_CHECK', str(self.accuracy_check_enable)).upper()
        trigger = gcmd.get('TRIGGER_DISTANCE', str(self.trigger_distance_enable)).upper()
        offset = gcmd.get('OFFSET_MEASURE', str(self.offset_measure_enable)).upper()
        debug = gcmd.get_int('DEBUG', self.debug_level)
        nozzle_temp = gcmd.get_float('PREHEAT_NOZZLE_TEMP', self.preheat_nozzle_temp)
        bed_temp = gcmd.get_float('PREHEAT_BED_TEMP', self.preheat_bed_temp)
        
        # Store runtime parameters
        self.temp_enable_rt = (heat in ['1', 'ON', 'YES'])
        self.qgl_enable_rt = (qgl in ['1', 'ON', 'YES'])
        self.clean_enable_rt = (clean in ['1', 'ON', 'YES'])
        self.accuracy_check_enable_rt = (accuracy in ['1', 'ON', 'YES'])
        self.trigger_distance_enable_rt = (trigger in ['1', 'ON', 'YES'])
        self.offset_measure_enable_rt = (offset in ['1', 'ON', 'YES'])
        self.debug_level_rt = debug
        self.preheat_nozzle_temp_rt = nozzle_temp
        self.preheat_bed_temp_rt = bed_temp
        
        # Reset state
        self.abort_active = False
        self.macro_execution_count += 1
        
        # WICHTIG: Reset GCODE Offset zu 0 (verhindert Verfälschung bei mehrfachen Messungen!)
        self.gcode.run_script_from_command("SET_GCODE_OFFSET Z=0 MOVE=0")
        
        # Show config
        self._show_config()
        
        # Start measurement
        self.reactor.register_callback(self._run_measurement)
    
    def cmd__AUTO_OFFSET_ABORT(self, gcmd):
        """Bricht Z-Offset Messung sicher ab (called as _AUTO_OFFSET_ABORT)"""
        self.abort_active = True
        self.gcode.respond_info("❌ AUTO_OFFSET ABBRUCH aktiviert.")
        self.gcode.respond_info("⚠️ Alle laufenden Messprozesse werden beendet.")
        
        # Restore state if saved
        try:
            self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
        except:
            pass
        
        # Reset GCODE Offset bei Abbruch
        self.gcode.run_script_from_command("SET_GCODE_OFFSET Z=0 MOVE=0")
        
        # LED Error Feedback
        self._led_error()
        
        self.gcode.respond_info("✅ Abbruch abgeschlossen.")
    
    def _show_config(self):
        """Show configuration"""
        self.gcode.respond_info("--- Z-OFFSET MESSUNG KONFIGURATION ---")
        
        heat_msg = f"🔥 Heizen: {'ON' if self.temp_enable_rt else 'OFF'}"
        if self.temp_enable_rt:
            heat_msg += f" (Nozzle {self.preheat_nozzle_temp_rt}°C / Bed {self.preheat_bed_temp_rt}°C)"
        self.gcode.respond_info(heat_msg)
        
        clean_msg = f"🧵 Reinigung: {'ON' if self.clean_enable_rt else 'OFF'}"
        if self.clean_enable_rt:
            clean_msg += f" ({self.clean_macro})"
        self.gcode.respond_info(clean_msg)
        
        self.gcode.respond_info(f"🪜 QGL: {'ON' if self.qgl_enable_rt else 'OFF'}")
        self.gcode.respond_info(f"🎯 Genauigkeitstest: {'ON' if self.accuracy_check_enable_rt else 'OFF'}")
        self.gcode.respond_info(f"📏 Schaltabstand: {'ON' if self.trigger_distance_enable_rt else 'OFF'}")
        self.gcode.respond_info(f"↕️ Z-Offset: {'ON' if self.offset_measure_enable_rt else 'OFF'}")
        self.gcode.respond_info(f"⚙️ Gespeicherter Z-Offset: +{self.sensor_offset_value:.6f} mm")
        self.gcode.respond_info("--------------------------------------")
    
    def _check_easter_eggs(self):
        """Check for Easter Egg combinations at START"""
        temp = self.temp_enable_rt
        qgl = self.qgl_enable_rt
        clean = self.clean_enable_rt
        acc = self.accuracy_check_enable_rt
        tap = self.trigger_distance_enable_rt
        sensor = self.offset_measure_enable_rt
        
        # Easter Egg 1: All OFF = Self-Destruct
        if not temp and not qgl and not clean and not acc and not tap and not sensor:
            self.cmd_EASTER_EGG_SELF_DESTRUCT(None)
            return True
        
        # Easter Egg 2: Only HEAT=ON = Coffee Break (Sauna)
        elif temp and not qgl and not clean and not acc and not tap and not sensor:
            self.cmd_EASTER_EGG_COFFEE(None)
            return True
        
        # Easter Egg 3: Only QGL=ON = Dance Mode
        elif not temp and qgl and not clean and not acc and not tap and not sensor:
            self.cmd_EASTER_EGG_DANCE(None)
            return True
        
        # Easter Egg 4: Only CLEAN=ON = Clean Mode
        elif not temp and not qgl and clean and not acc and not tap and not sensor:
            self.cmd_EASTER_EGG_CLEAN_MODE(None)
            return True
        
        # No Easter Egg
        return False
    
    def _run_safety_check(self):
        """Safety check: Verify TAP and Sensor are OPEN"""
        self._debug("AUTO_OFFSET_SAFETY", 2, "🔍 Starte Sicherheitsprüfung der genutzten Sensoren...")
        
        # Query probe first
        self.gcode.run_script_from_command("QUERY_PROBE_SILENT")
        self.gcode.run_script_from_command("M400")
        self.gcode.run_script_from_command("G4 P200")
        
        # Check TAP sensor
        tap_state = self._query_probe_state()
        if tap_state:  # TRIGGERED
            self.gcode.respond_raw("!! ❌ TAP-Sensor TRIGGERED beim Start. Bitte prüfen!")
            self.abort_active = True
            return False
        else:
            self._debug("AUTO_OFFSET_SAFETY", 2, "✅ TAP-Sensor: OPEN")
        
        # Check custom sensor
        sensor_state = self._query_custom_sensor()
        if sensor_state:  # TRIGGERED
            self.gcode.respond_raw(f"!! ❌ Sensor '{self.sensor_offset_path}' TRIGGERED beim Start. Bitte prüfen!")
            self.abort_active = True
            return False
        else:
            self._debug("AUTO_OFFSET_SAFETY", 2, f"✅ Sensor '{self.sensor_offset_path}': OPEN")
        
        self._debug("AUTO_OFFSET_SAFETY", 2, "✅ Sicherheitsprüfung abgeschlossen. Sensoren bereit.")
        return True
    
    def _run_measurement(self, eventtime):
        """Main measurement sequence"""
        # Check for Easter Eggs FIRST (separate try/catch - no SAVE/RESTORE needed)
        try:
            if self._check_easter_eggs():
                return  # Easter Egg was triggered
        except Exception as e:
            logging.exception("Error in Easter Egg")
            self.gcode.respond_raw(f"!! ❌ Easter Egg Fehler: {e}")
            return
        
        try:
            self._debug("AUTO_OFFSET", 1, "🚀 Starte Auto-Offset-Messung...")
            
            # Save state and reset abort
            self.gcode.run_script_from_command("SAVE_GCODE_STATE NAME=TAP_MEAS")
            self.abort_active = False
            
            # Safety Check
            if not self._run_safety_check():
                self._debug("AUTO_OFFSET", 1, "❌ Sicherheitsprüfung fehlgeschlagen - Abbruch")
                self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
                return
            
            # 1. Homing
            status = self.toolhead.get_status(eventtime)
            if 'xyz' not in status.get('homed_axes', ''):
                self._debug("AUTO_OFFSET", 1, "🏁 Führe Homing durch...")
                self.gcode.run_script_from_command("G28")
            else:
                self._debug("AUTO_OFFSET", 1, "🏁 Homing bereits ausgeführt.")
            
            # Move to park position after homing
            self.gcode.run_script_from_command("G90")
            self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
            self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F9000")
            self.gcode.run_script_from_command("M400")
            
            # 2. Heizen (Phase 6!)
            if self.temp_enable_rt:
                self._run_heating()
            else:
                self._debug("AUTO_OFFSET", 1, "⚙️ Heizen deaktiviert (HEAT=OFF)")
            
            # 3. QGL (Phase 6!)
            if self.qgl_enable_rt:
                self._run_qgl()
                # Z-Homing nach QGL
                self._debug("AUTO_OFFSET", 1, "🔁 Führe Z-Homing durch...")
                self.gcode.run_script_from_command("G28 Z")
            else:
                self._debug("AUTO_OFFSET", 1, "⚙️ QGL deaktiviert (QGL=OFF)")
            
            # 5. Reinigung (Phase 6!)
            if self.clean_enable_rt:
                self._run_cleaning()
            else:
                self._debug("AUTO_OFFSET", 1, "⚙️ Reinigung deaktiviert (CLEAN=OFF)")
            
            # Check if any measurements are enabled
            if not self.accuracy_check_enable_rt and not self.trigger_distance_enable_rt and not self.offset_measure_enable_rt:
                self._debug("AUTO_OFFSET", 1, "⚙️ Keine Messungen aktiviert (ACCURACY_CHECK=OFF, TRIGGER_DISTANCE=OFF, OFFSET_MEASURE=OFF)")
                self._debug("AUTO_OFFSET", 1, "✅ Heizen/QGL/Clean abgeschlossen – Messung übersprungen")
                # Restore state and finish
                self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
                return
            
            # 6. Move to measurement position
            self._debug("AUTO_OFFSET", 1, f"🎯 Fahre Messposition (X{self.measure_x} Y{self.measure_y} Z{self.measure_z})...")
            self.gcode.run_script_from_command(f"G0 X{self.measure_x} Y{self.measure_y} Z{self.measure_z} F6000")
            self.gcode.run_script_from_command("M400")
            self.gcode.run_script_from_command("G4 P100")
            
            # Messungen durchführen - TAP Contact wenn mindestens EINE Messung aktiv ist
            if self.accuracy_check_enable_rt or self.trigger_distance_enable_rt or self.offset_measure_enable_rt:
                # 3. TAP Contact Phase - ZUERST! (setzt Z=0 als Referenz für ALLE Messungen)
                self._run_tap_contact()
                
                # 4. Accuracy Check - NACH Z=0! (alle Probe-Werte ab Z=0)
                if self.accuracy_check_enable_rt:
                    accuracy_ok = self._run_accuracy_check()
                    if not accuracy_ok:
                        self._debug("AUTO_OFFSET", 1, "❌ Genauigkeitstest fehlgeschlagen - Abbruch")
                        self.abort_active = True
                        self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
                        return
                    
                    # WICHTIG: Reference Probe - zurück zu Z=0 (ohne Z neu zu setzen!)
                    # Nur wenn weitere Messungen folgen!
                    if self.trigger_distance_enable_rt or self.offset_measure_enable_rt:
                        # Erst hochfahren (Probe ist nach letztem Sample noch TRIGGERED!)
                        self._debug("PROBE_TEST", 2, f"⬆️ Fahre hoch zu Z={self.measure_z} mm...")
                        self.gcode.run_script_from_command("G90")
                        self.gcode.run_script_from_command(f"G0 Z{self.measure_z} F3000")
                        self.gcode.run_script_from_command("M400")
                        
                        # DANN Reference Probe zurück zu Z=0
                        self._debug("PROBE_TEST", 2, "📍 Reference Probe: Fahre zurück zu Z=0...")
                        self.gcode.run_script_from_command(f"PROBE PROBE_SPEED={self.probe_speed}")
                        self.gcode.run_script_from_command("M400")
                        # Query probe state for next measurement
                        self.gcode.run_script_from_command("QUERY_PROBE_SILENT")
                        self.gcode.run_script_from_command("G4 P50")
                else:
                    self._debug("AUTO_OFFSET", 1, "⚙️ Genauigkeitstest deaktiviert – fahre direkt zu Messungen.")
                
                # 5. Trigger Distance (Phase 2!)
                if self.trigger_distance_enable_rt:
                    self._run_trigger_distance()
                else:
                    self._debug("AUTO_OFFSET", 1, "⚙️ Schaltabstand deaktiviert")
                    self.tap_distance_new = self.tap_distance_old
                
                # 6. Sensor Offset (Phase 3!)
                if self.offset_measure_enable_rt:
                    self._run_sensor_offset()
                else:
                    self._debug("AUTO_OFFSET", 1, f"⚙️ Z-Offset-Messung deaktiviert → Lade letzten gespeicherten Wert: {self.sensor_offset_value:.6f} mm")
            else:
                self._debug("AUTO_OFFSET", 1, "⚙️ Alle Messungen deaktiviert – nichts zu tun")
            
            # 6. Finish
            self._finish_measurement()
            
            # Restore state
            self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
            
            # SET_GCODE_OFFSET NACH RESTORE (sonst wird er zurückgesetzt!)
            # Nutze DELTA statt absoluten Wert (alter Offset ist bereits aktiv!)
            if hasattr(self, 'final_delta_offset'):
                self.gcode.run_script_from_command(f"SET_GCODE_OFFSET Z={self.final_delta_offset:.6f} MOVE=0")
                if self.final_delta_offset >= 0:
                    self.gcode.respond_info(f"✅ GCODE Z-Offset Delta +{self.final_delta_offset:.6f} mm aktiv - bereit zum Testen!")
                else:
                    self.gcode.respond_info(f"✅ GCODE Z-Offset Delta {self.final_delta_offset:.6f} mm aktiv - bereit zum Testen!")
            
        except Exception as e:
            logging.exception("Error in measurement")
            self.gcode.respond_raw(f"!! ❌ Fehler: {e}")
            # IMPORTANT: Restore state even on exception!
            try:
                self.gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=TAP_MEAS")
            except:
                pass  # In case SAVE was not done
    
    def _run_heating(self):
        """PHASE 6: Heat nozzle and bed to target temperatures"""
        self._debug("AUTO_OFFSET", 1, f"🔥 Heize auf {self.preheat_nozzle_temp_rt}°C / {self.preheat_bed_temp_rt}°C...")
        
        # Set temperatures (non-blocking)
        self.gcode.run_script_from_command(f"M104 S{self.preheat_nozzle_temp_rt}")  # Nozzle
        self.gcode.run_script_from_command(f"M140 S{self.preheat_bed_temp_rt}")    # Bed
        
        # Wait for temperatures (blocking)
        self.gcode.run_script_from_command(f"M109 S{self.preheat_nozzle_temp_rt}")  # Wait nozzle
        self.gcode.run_script_from_command(f"M190 S{self.preheat_bed_temp_rt}")    # Wait bed
        
        self._debug("AUTO_OFFSET", 2, "✅ Zieltemperaturen erreicht")
    
    def _run_qgl(self):
        """PHASE 6: Run Quad Gantry Leveling"""
        self._debug("AUTO_OFFSET", 1, "🔄 Führe Quad Gantry Leveling durch...")
        
        try:
            self.gcode.run_script_from_command("QUAD_GANTRY_LEVEL")
            self._debug("AUTO_OFFSET", 2, "✅ QGL abgeschlossen")
        except Exception as e:
            logging.warning(f"QGL failed: {e}")
            self._debug("AUTO_OFFSET", 1, f"⚠️ QGL nicht verfügbar oder fehlgeschlagen: {e}")
    
    def _run_cleaning(self):
        """PHASE 6: Run nozzle cleaning"""
        self._debug("AUTO_OFFSET", 1, f"🧹 Führe Düsenreinigung durch ({self.clean_macro})...")
        
        try:
            self.gcode.run_script_from_command(self.clean_macro)
            self.gcode.run_script_from_command("G0 Z10")
            self.gcode.run_script_from_command("M400")
            self.gcode.run_script_from_command("G4 P100")
            self._debug("AUTO_OFFSET", 2, "✅ Reinigung abgeschlossen")
        except Exception as e:
            logging.warning(f"Cleaning failed: {e}")
            self._debug("AUTO_OFFSET", 1, f"⚠️ Reinigung nicht verfügbar oder fehlgeschlagen: {e}")
    
    def _run_accuracy_check(self):
        """PHASE 4: Probe Accuracy Check - uses built-in PROBE_ACCURACY"""
        self._debug("PROBE_TEST", 1, f"🎯 Starte Probe-Genauigkeitstest mit {self.probe_samples} Messungen...")
        
        samples = self.probe_samples
        
        # Prepare
        self.gcode.run_script_from_command("G90")
        self.gcode.run_script_from_command("M400")
        
        # Mache eigene Probes um Werte für Plot zu bekommen
        try:
            self._last_probe_samples = []
            
            for i in range(samples):
                # Single probe
                self.gcode.run_script_from_command("PROBE")
                self.gcode.run_script_from_command("M400")
                
                # Get current Z position (probe result)
                toolhead_pos = self.toolhead.get_position()
                z_value = toolhead_pos[2]
                self._last_probe_samples.append(z_value)
                
                # Retract for next probe
                if i < samples - 1:  # Don't retract after last sample
                    self.gcode.run_script_from_command("G91")
                    self.gcode.run_script_from_command("G0 Z2.5 F300")
                    self.gcode.run_script_from_command("G90")
                    self.gcode.run_script_from_command("M400")
            
            # Berechne Statistiken
            if len(self._last_probe_samples) > 1:
                mean = sum(self._last_probe_samples) / len(self._last_probe_samples)
                variance = sum((x - mean) ** 2 for x in self._last_probe_samples) / len(self._last_probe_samples)
                self._last_probe_stddev = variance ** 0.5
                probe_range = max(self._last_probe_samples) - min(self._last_probe_samples)
                
                self._debug("PROBE_TEST", 2, f"📊 Probe samples: {self._last_probe_samples}")
                self._debug("PROBE_TEST", 1, f"📊 Range: {probe_range:.6f} mm | StdDev: {self._last_probe_stddev:.6f} mm")
                
                # Check tolerance
                if probe_range > self.probe_tolerance:
                    raise self.gcode.error(f"Probe range {probe_range:.6f}mm exceeds tolerance {self.probe_tolerance}mm")
            
            self._debug("PROBE_TEST", 1, f"✅ Probe-Genauigkeit OK.")
        
        except Exception as e:
            # PROBE_ACCURACY throws exception if tolerance not met
            logging.warning(f"PROBE_ACCURACY failed: {e}")
            self._debug("PROBE_TEST", 1, f"❌ Genauigkeitstest fehlgeschlagen: {e}")
            return False
        
        return True
    
    def _run_tap_contact(self):
        """Initial contact with bed - set Z=0"""
        self._debug("TAP_CONTACT", 1, "📏 Starte Kontaktfahrt...")
        self._debug("TAP_CONTACT", 1, f"⬇️ Fahre mit PROBE zum Bett, bis TAP auslöst ({self.probe_speed} mm/s)...")
        
        try:
            # Probe to bed - use our probe_speed!
            self.gcode.run_script_from_command(f"PROBE PROBE_SPEED={self.probe_speed}")
            
            self._debug("TAP_CONTACT", 1, "🔹 Kontakt erkannt – Position wird als Nullpunkt gesetzt.")
            
            # Set Z=0
            self.gcode.run_script_from_command("SET_KINEMATIC_POSITION Z=0")
            self.gcode.run_script_from_command("M400")
            self.gcode.run_script_from_command("G4 P100")
            
            # IMPORTANT: Update probe state after PROBE!
            # After PROBE the probe is TRIGGERED, but last_state must be updated
            self.gcode.run_script_from_command("QUERY_PROBE_SILENT")
            self.gcode.run_script_from_command("G4 P50")  # Short pause for state update
            
            # Debug: Check probe state
            probe_state = self._query_probe_state()
            self._debug("TAP_CONTACT", 2, f"🔍 Probe State nach Contact: {'TRIGGERED' if probe_state else 'OPEN'}")
            
            self._debug("TAP_CONTACT", 1, "📍 Z=0 gesetzt – fahre zurück zur Messposition")
            
            # Zurück zur Messposition fahren (wichtig für Genauigkeitstest!)
            self._debug("TAP_CONTACT", 2, f"⬆️ Fahre zurück zur Messposition (X{self.measure_x} Y{self.measure_y} Z{self.measure_z})...")
            self.gcode.run_script_from_command("G90")
            self.gcode.run_script_from_command(f"G0 Z{self.measure_z} F3000")  # Erst hoch in Z
            self.gcode.run_script_from_command(f"G0 X{self.measure_x} Y{self.measure_y} F9000")  # Dann XY
            self.gcode.run_script_from_command("M400")
            
            self._debug("TAP_CONTACT", 1, f"✅ Messposition erreicht (Z={self.measure_z} mm) – bereit für Messungen")
                
        except Exception as e:
            error_msg = f"❌ FEHLER: TAP Kontaktfahrt fehlgeschlagen: {e}"
            self._debug("TAP_CONTACT", 1, error_msg)
            self._raise_error(error_msg)
    
    def _run_trigger_distance(self):
        """PHASE 2: Trigger Distance Measurement - hardware-based like PROBE!"""
        self._debug("TRIGGER_DISTANCE", 1, "⚡ Starte Schaltabstandsmessung...")
        
        max_z = self.trigger_distance_max
        speed = self.probe_speed
        
        self._debug("TRIGGER_DISTANCE", 2, f"⬆️ Fahre hoch bis Probe OPEN (max {max_z:.6f} mm @ {speed:.1f} mm/s)...")
        
        try:
            # Use new _probe_move_until_open() - hardware-based!
            # Returns Z value directly (Z=0 is reference)
            release_z = self._probe_move_until_open(max_z, speed)
            
            # Save Z value (trigger distance relative to Z=0)
            self.tap_distance_new = release_z
            self._save_variable('tap_last_distance', release_z)
            self._debug("TRIGGER_DISTANCE", 2, f"💾 tap_last_distance gespeichert: Z={release_z:.6f} mm")
            self._debug("TRIGGER_DISTANCE", 1, f"✅ Schaltabstand-Messung abgeschlossen. Z={release_z:.6f} mm")
            
        except Exception as e:
            error_msg = f"❌ FEHLER: Schaltabstand-Messung fehlgeschlagen: {e}"
            self._debug("TRIGGER_DISTANCE", 1, error_msg)
            raise
    
    def _run_sensor_offset(self):
        """PHASE 3: Sensor Offset Measurement - hardware-based!"""
        self._debug("SENSOR_OFFSET", 1, "🔍 Starte Sensor-Offset-Messung...")
        
        # Step 1: Find start position (where sensor is OPEN)
        start_z = self._find_sensor_start_position()
        if start_z is None:
            self._debug("SENSOR_OFFSET", 1, "❌ Konnte Sensor-Startposition nicht finden")
            return
        
        self.sensor_offset_start_z = start_z
        self._debug("SENSOR_OFFSET", 1, f"✅ Startposition gefunden bei Z={start_z:.6f} mm")
        self._save_variable('sensor_offset_start_z', start_z)
        self._debug("SENSOR_OFFSET", 2, f"💾 Gespeichert: sensor_offset_start_z = {start_z:.6f} mm")
        
        # WICHTIG: Pause + Query damit Sensor-State aktualisiert wird!
        self.gcode.run_script_from_command("G4 P200")
        self.gcode.run_script_from_command("M400")
        self._query_custom_sensor()  # State refresh
        self._debug("SENSOR_OFFSET", 2, "🔄 Sensor-State aktualisiert")
        
        # Step 2: Probe-Move RUNTER bis Sensor TRIGGERED!
        speed = self.probe_speed
        
        # Calculate safety limit
        safety_limit = self.tap_distance_new * (1 + self.sensorhub_safety_percent / 100)
        
        self._debug("SENSOR_OFFSET", 2, f"📊 Sicherheitslimit: {safety_limit:.6f} mm (Schaltabstand {self.tap_distance_new:.6f} mm + {self.sensorhub_safety_percent:.0f}%)")
        
        # Safety check: Don't go below safety limit
        if self.tap_distance_new > 0:
            target_z = max(safety_limit, 0.0)  # Either safety limit or Z=0
        else:
            target_z = 0.0  # No trigger distance measured, go to Z=0
        
        self._debug("SENSOR_OFFSET", 2, f"⬇️ Fahre runter bis Sensor TRIGGERED (von Z={start_z:.6f} bis Z={target_z:.6f} mm)...")
        
        try:
            # Use new _sensor_probe_move() - 10µm steps!
            trigger_z = self._sensor_probe_move(target_z, speed, direction='down')
            
            self._debug("SENSOR_OFFSET", 2, f"💡 Sensor ausgelöst bei Z={trigger_z:.6f} mm")
            self.sensor_offset_value = trigger_z
            self._save_variable('sensor_offset_value', trigger_z)
            self._debug("SENSOR_OFFSET", 1, f"💾 sensor_offset_value gespeichert: {trigger_z:.6f} mm")
            
            # Move up to safe position
            self.toolhead.manual_move([None, None, 10.0], self.probe_speed * 2)
            self.toolhead.wait_moves()
            
            self._debug("SENSOR_OFFSET", 1, "✅ Sensor-Offset-Messung abgeschlossen")
            
        except Exception as e:
            self._debug("SENSOR_OFFSET", 1, f"❌ Sensor-Offset-Messung fehlgeschlagen: {e}")
            return
    
    def _find_sensor_start_position(self):
        """Find position where sensor opens - Hardware-basiert!"""
        self._debug("SENSOR_OFFSET", 2, "🔍 Suche Startposition...")
        
        current_z = self.toolhead.get_position()[2]
        max_distance = self.sensor_offset_search_max
        speed = self.probe_speed
        
        # Try to use saved start position first (fast path!)
        try:
            saved_start_z = self.save_variables.allVariables.get('sensor_offset_start_z', 0.0)
        except:
            saved_start_z = 0.0
        if saved_start_z > 0:
            self._debug("SENSOR_OFFSET", 2, f"📍 Gespeicherte Startposition: {saved_start_z:.6f} mm – fahre direkt dorthin...")
            # Move to saved position
            self.gcode.run_script_from_command("G90")
            self.gcode.run_script_from_command(f"G0 Z{saved_start_z:.6f} F{int(speed * 60)}")
            self.gcode.run_script_from_command("M400")
            
            # Check if OPEN at saved position
            sensor_state = self._query_custom_sensor()
            if not sensor_state:  # OPEN!
                self._debug("SENSOR_OFFSET", 2, f"✅ Sensor OPEN bei gespeicherter Position Z={saved_start_z:.6f} mm")
                return saved_start_z
            else:
                # TRIGGERED at saved position - need to go higher
                self._debug("SENSOR_OFFSET", 2, f"⚠️ Sensor TRIGGERED bei gespeicherter Position – fahre weiter hoch...")
                current_z = saved_start_z
        else:
            # No saved position - check current position
            sensor_state = self._query_custom_sensor()
            if not sensor_state:  # Already OPEN
                self._debug("SENSOR_OFFSET", 2, f"✅ Sensor bereits OPEN bei Z={current_z:.6f} mm")
                return current_z
        
        # Sensor is TRIGGERED - move up until OPEN!
        self._debug("SENSOR_OFFSET", 2, f"⚠️ Sensor TRIGGERED bei Z={current_z:.6f} mm – fahre hoch bis OPEN (max {max_distance:.1f} mm)...")
        
        target_z = current_z + max_distance
        
        try:
            # Use new _sensor_probe_move() - 10µm steps!
            open_z = self._sensor_probe_move(target_z, speed, direction='up')
            
            self._debug("SENSOR_OFFSET", 2, f"✅ Sensor OPEN bei Z={open_z:.6f} mm")
            return open_z
            
        except Exception as e:
            self._debug("SENSOR_OFFSET", 1, f"❌ Startposition nicht gefunden: {e}")
            return None
    
    def _get_custom_sensor_mcu_endstop(self):
        """Tries to get real MCU endstop object for hardware probing (fast)
        Returns None if sensor is Python-based (slow polling)
        """
        sensor_path = self.sensor_offset_path
        if not sensor_path:
            return None
        
        # If we're using custom MCU endstop, return it directly
        if sensor_path == 'custom_mcu_endstop' and hasattr(self, 'custom_sensor_mcu'):
            self._debug("SENSOR", 2, f"✅ Custom Sensor bereit")
            return self.custom_sensor_mcu
        
        try:
            # Parse sensor path (e.g., "mmu.sensors.toolhead")
            parts = sensor_path.split('.')
            
            # Get sensor object
            if len(parts) == 1:
                obj = self.printer.lookup_object(parts[0])
            elif len(parts) == 2:
                obj = self.printer.lookup_object(parts[0])
                if hasattr(obj, parts[1]):
                    obj = getattr(obj, parts[1])
            elif len(parts) == 3:
                obj = self.printer.lookup_object(parts[0])
                if hasattr(obj, parts[1]):
                    subobj = getattr(obj, parts[1])
                    if hasattr(subobj, parts[2]):
                        obj = getattr(subobj, parts[2])
            
            # Search for mcu_endstop or button
            if hasattr(obj, 'mcu_endstop'):
                self._debug("SENSOR", 2, f"✅ Sensor bereit: {sensor_path}")
                return obj.mcu_endstop
            elif hasattr(obj, 'button'):
                if hasattr(obj.button, 'mcu_endstop'):
                    self._debug("SENSOR", 2, f"✅ Sensor bereit: {sensor_path}")
                    return obj.button.mcu_endstop
            elif hasattr(obj, 'endstop'):
                self._debug("SENSOR", 2, f"✅ Sensor bereit: {sensor_path}")
                return obj.endstop
            
            self._debug("SENSOR", 2, f"⚠️ Sensor {sensor_path} nutzt Python-Polling")
            
        except Exception as e:
            logging.warning(f"Could not get mcu_endstop for sensor {sensor_path}: {e}")
        
        return None
    
    def _query_custom_sensor(self):
        """Query custom sensor state - returns True if TRIGGERED, False if OPEN
        IMPORTANT: Makes real MCU query for current values!
        """
        # If we have a custom_sensor MCU endstop, query it directly
        if hasattr(self, 'custom_sensor_mcu') and self.custom_sensor_mcu:
            try:
                print_time = self.toolhead.get_last_move_time()
                result = self.custom_sensor_mcu.query_endstop(print_time)
                self._debug("SENSOR_QUERY", 2, f"🔍 MCU endstop state: {result}")
                return result
            except Exception as e:
                self._debug("SENSOR_QUERY", 2, f"⚠️ MCU endstop query failed: {e}")
        
        # Fallback: Try to query via sensor_offset_path
        sensor_path = self.sensor_offset_path
        if not sensor_path:
            return False
        
        try:
            # Navigate through path structure
            parts = sensor_path.split('.')
            obj = self.printer
            for part in parts:
                obj = getattr(obj, part, None)
                if obj is None:
                    return False
            
            # First try: query_endstop() for REAL MCU query
            if hasattr(obj, 'query_endstop'):
                print_time = self.toolhead.get_last_move_time()
                return obj.query_endstop(print_time)
            
            # Fallback: Cached states
            if hasattr(obj, 'filament_present'):
                return obj.filament_present
            elif hasattr(obj, 'state'):
                return obj.state
            elif hasattr(obj, 'get_status'):
                status = obj.get_status(self.reactor.monotonic())
                return status.get('state', False) or status.get('last_query', False)
            
        except Exception as e:
            logging.warning(f"Could not query sensor {sensor_path}: {e}")
        
        return False
    
    def _query_probe_state(self):
        """Query probe state - returns True if TRIGGERED, False if OPEN
        IMPORTANT: Makes real MCU query for current values!
        """
        try:
            # Use query_endstop() for REAL MCU query!
            if hasattr(self.probe, 'mcu_probe'):
                mcu_probe = self.probe.mcu_probe
                if hasattr(mcu_probe, 'query_endstop'):
                    print_time = self.toolhead.get_last_move_time()
                    return mcu_probe.query_endstop(print_time)
            
            # Fallback: last_state (but outdated during movement!)
            if hasattr(self.probe, 'last_state'):
                return self.probe.last_state
            
            # Fallback 2: get_status
            if hasattr(self.probe, 'get_status'):
                status = self.probe.get_status(self.reactor.monotonic())
                if 'last_query' in status:
                    return status['last_query']
                
        except Exception as e:
            logging.warning(f"Could not query probe state: {e}")
        
        return False
    
    #####################################################################
    # PROBE MOVE FUNCTIONS (wie probe.py!)
    #####################################################################
    
    class PythonEndstop:
        """Custom Python endstop with completion - works with drip_move()!
        Does EXACTLY the same as MCU endstop - but in Python!
        """
        def __init__(self, auto_offset, sensor_check_func, sensor_name, mcu_probe):
            self.auto_offset = auto_offset
            self.sensor_check_func = sensor_check_func
            self.sensor_name = sensor_name
            self.mcu_probe = mcu_probe
            self.reactor = auto_offset.reactor
            self.completion = None
            self.trigger_time = 0.
            self.check_timer = None
        
        def get_mcu(self):
            return self.mcu_probe.get_mcu()
        
        def add_stepper(self, stepper):
            self.mcu_probe.add_stepper(stepper)
        
        def get_steppers(self):
            return self.mcu_probe.get_steppers()
        
        def home_start(self, print_time, sample_time, sample_count, rest_time, triggered=True):
            """Start homing - returns completion monitored by reactor"""
            self.trigger_time = 0.
            self.triggered = triggered
            
            # Create completion object for async operation
            self.completion = self.reactor.completion()
            
            # Check initial state
            if self.sensor_check_func() == self.triggered:
                # Already in desired state!
                self.trigger_time = print_time
                self.completion.complete(True)
                return self.completion
            
            # Define check callback
            def check_sensor(eventtime):
                # Check if sensor reached desired state
                if self.sensor_check_func() == self.triggered:
                    # Sensor triggered!
                    self.trigger_time = self.reactor.monotonic()
                    self.completion.complete(1)  # Complete!
                    return self.reactor.NEVER
                # Continue checking
                return eventtime + rest_time
            
            # Register timer
            self.check_timer = self.reactor.register_timer(check_sensor, self.reactor.NOW)
            
            return self.completion
        
        def home_wait(self, home_end_time):
            """Wait for sensor trigger or timeout"""
            if self.check_timer is not None:
                self.reactor.update_timer(self.check_timer, self.reactor.NEVER)
                self.reactor.unregister_timer(self.check_timer)
                self.check_timer = None
            
            # Raise error if sensor never triggered
            if self.trigger_time is None or self.trigger_time == 0.:
                raise self.auto_offset.printer.command_error(
                    f"No trigger on {self.sensor_name} after full movement")
            
            return self.trigger_time
        
        def home_finalize(self):
            """Cleanup"""
            if self.check_timer is not None:
                try:
                    self.reactor.update_timer(self.check_timer, self.reactor.NEVER)
                    self.reactor.unregister_timer(self.check_timer)
                except:
                    pass
                self.check_timer = None
        
        def query_endstop(self, print_time):
            """Query sensor state"""
            return self.sensor_check_func()
        
        def multi_probe_begin(self):
            pass
        
        def multi_probe_end(self):
            pass
    
    class InvertedProbeWrapper:
        """Wrapper around mcu_probe that inverts OPEN/TRIGGERED
        So probing_move() stops at OPEN instead of TRIGGERED!
        """
        def __init__(self, mcu_probe):
            self.mcu_probe = mcu_probe
        
        def query_endstop(self, print_time):
            # Invert result!
            return not self.mcu_probe.query_endstop(print_time)
        
        def multi_probe_begin(self):
            self.mcu_probe.multi_probe_begin()
        
        def multi_probe_end(self):
            self.mcu_probe.multi_probe_end()
        
        def get_mcu(self):
            return self.mcu_probe.get_mcu()
        
        def add_stepper(self, stepper):
            self.mcu_probe.add_stepper(stepper)
        
        def get_steppers(self):
            return self.mcu_probe.get_steppers()
        
        # Homing methods called by probing_move()
        def home_start(self, print_time, sample_time, sample_count, rest_time, triggered=True):
            # Inverted: triggered=True means "stop at OPEN"
            return self.mcu_probe.home_start(print_time, sample_time, sample_count, rest_time, not triggered)
        
        def home_wait(self, home_end_time):
            return self.mcu_probe.home_wait(home_end_time)
        
        def home_finalize(self):
            return self.mcu_probe.home_finalize()
    
    class CustomSensorWrapper:
        """Wrapper around custom sensor as mcu_endstop
        So probing_move() works with custom sensor!
        """
        def __init__(self, auto_offset, sensor_path, invert=False):
            self.auto_offset = auto_offset
            self.sensor_path = sensor_path
            self.invert = invert
            self.mcu = auto_offset.probe.mcu_probe.get_mcu()  # Use MCU from probe
            # Take steppers from TAP probe
            self.steppers = auto_offset.probe.mcu_probe.get_steppers()
        
        def query_endstop(self, print_time):
            # Query custom sensor
            state = self.auto_offset._query_custom_sensor()
            # Invert if desired (for "until OPEN")
            if self.invert:
                return not state
            return state
        
        def multi_probe_begin(self):
            # Nothing to do
            pass
        
        def multi_probe_end(self):
            # Nothing to do
            pass
        
        def get_mcu(self):
            return self.mcu
        
        def add_stepper(self, stepper):
            # Should not be called - already have steppers
            pass
        
        def get_steppers(self):
            return self.steppers
        
        # Homing methods called by probing_move()
        def home_start(self, print_time, sample_time, sample_count, rest_time, triggered=True):
            # Use same parameters as original mcu_probe
            # But check with our custom sensor
            # Since we implement query_endstop() ourselves, this will work
            return self.auto_offset.probe.mcu_probe.home_start(
                print_time, sample_time, sample_count, rest_time, triggered
            )
        
        def home_wait(self, home_end_time):
            return self.auto_offset.probe.mcu_probe.home_wait(home_end_time)
        
        def home_finalize(self):
            return self.auto_offset.probe.mcu_probe.home_finalize()
    
    def _python_probing_move(self, target_pos, speed, sensor_check_func, sensor_name="Sensor"):
        """Custom probing move implementation in Python.
        
        Uses drip_move() for non-blocking continuous movement with sensor polling.
        
        Args:
            target_pos: [X, Y, Z] target position
            speed: Speed in mm/s
            sensor_check_func: Lambda that returns True when sensor triggers
            sensor_name: Name for debug output
        
        Returns: [X, Y, Z] position where sensor triggered
        """
        start_pos = self.toolhead.get_position()
        distance = abs(target_pos[2] - start_pos[2])
        
        self._debug("PYTHON_PROBE", 2, f"🔄 {sensor_name}: Start Z={start_pos[2]:.6f} → Ziel Z={target_pos[2]:.6f} ({distance:.6f}mm @ {speed}mm/s)")
        
        # Calculate small steps for continuous movement
        # 50µm steps = very fine + fast enough
        step_size = 0.05  # 50 micrometers
        direction = 1 if target_pos[2] > start_pos[2] else -1
        current_z = start_pos[2]
        
        step_count = 0
        while True:
            # Next step
            current_z += direction * step_size
            
            # Don't go beyond target
            if direction > 0 and current_z > target_pos[2]:
                current_z = target_pos[2]
            elif direction < 0 and current_z < target_pos[2]:
                current_z = target_pos[2]
            
            # Move
            self.toolhead.manual_move([None, None, current_z], speed)
            self.toolhead.wait_moves()
            
            step_count += 1
            
            # Check sensor
            if sensor_check_func():
                # SENSOR TRIGGERED!
                result_pos = self.toolhead.get_position()
                self._debug("PYTHON_PROBE", 2, f"✅ {sensor_name} triggered bei Z={result_pos[2]:.6f}mm (nach {step_count} Schritten)")
                return result_pos
            
            # Target reached?
            if abs(current_z - target_pos[2]) < 0.001:  # 1µm tolerance
                # Target reached, sensor not triggered
                result_pos = self.toolhead.get_position()
                self._debug("PYTHON_PROBE", 2, f"⚠️ {sensor_name} Ziel erreicht bei Z={result_pos[2]:.6f}mm - Sensor nicht triggered!")
                return result_pos
    
    def _probe_move_until_open(self, max_distance, speed):
        """TAP PROBE UP until OPEN - WITH HARDWARE-MCU!
        Uses triggered=False + check_triggered=False!
        MCU stops on state change (TRIGGERED→OPEN)!
        Returns: Z distance where probe opened
        """
        # Probe must be TRIGGERED at start!
        if not self._query_probe_state():
            self._raise_error("❌ Probe ist nicht TRIGGERED beim Start!")
        
        start_pos = self.toolhead.get_position()
        start_z = start_pos[2]
        
        # Target position (move up!)
        target_pos = list(start_pos)
        target_pos[2] = start_z + max_distance
        
        self._debug("PROBE_MOVE", 2, f"⬆️ TAP HOCH bis OPEN: Kontinuierliche Bewegung  {max_distance:.6f}mm @ {speed}mm/s")
        
        # MAXIMUM PRECISION for trigger distance!
        # 1.25µm steps for highest accuracy
        step_size = 0.00125  # 1.25 micrometers (like probe accuracy)
        current_z = start_z
        steps = 0
        
        while current_z < (start_z + max_distance):
            # Next step
            current_z += step_size
            if current_z > (start_z + max_distance):
                current_z = start_z + max_distance
            
            # Move fast
            self.toolhead.manual_move([None, None, current_z], speed)
            self.toolhead.wait_moves()
            
            steps += 1
            
            # Check probe state
            if not self._query_probe_state():
                # OPEN!
                result_pos = self.toolhead.get_position()
                self._debug("PROBE_MOVE", 2, f"✅ Probe released bei Z={result_pos[2]:.6f}mm (nach {steps} Schritten)")
                return result_pos[2]
        
        # Max reached without OPEN
        self._raise_error(f"❌ Probe hat nicht released! Max {max_distance:.6f}mm erreicht.")
    
    def _python_probing_move_old_broken(self, target_pos, speed, sensor_check_func, sensor_name="Sensor"):
        """PYTHON-PROBING: Continuous movement + sensor monitoring!
        EXACTLY like original PROBE - but in Python for ALL sensors!
        
        Args:
            target_pos: Target position [X, Y, Z]
            speed: Speed in mm/s
            sensor_check_func: Lambda that returns True when should stop
            sensor_name: Name for debug output
        
        Returns: Position [X, Y, Z] where sensor triggered
        """
        start_pos = self.toolhead.get_position()
        distance = abs(target_pos[2] - start_pos[2])
        
        self._debug("PYTHON_PROBE", 2, f"🔄 {sensor_name}: Kontinuierliche Bewegung {distance:.6f}mm @ {speed}mm/s")
        
        # Stop flag
        stop_triggered = [False]
        stop_position = [None]
        
        def check_sensor_callback(eventtime):
            """Called by reactor during movement"""
            if sensor_check_func():
                # SENSOR TRIGGERED! Stoppe Bewegung!
                stop_triggered[0] = True
                self.toolhead.flush_step_generation()
                stop_position[0] = self.toolhead.get_position()
                return self.reactor.NEVER  # Stoppe Callback
            
            # Check if movement finished
            current_pos = self.toolhead.get_position()
            if abs(current_pos[2] - target_pos[2]) < 0.001:  # 1µm tolerance
                # Movement finished, sensor not triggered
                return self.reactor.NEVER
            
            # Continue checking - every 1ms!
            return eventtime + 0.001
        
        # Start sensor monitoring (reactor callback!)
        check_timer = self.reactor.register_timer(check_sensor_callback)
        self.reactor.update_timer(check_timer, self.reactor.NOW)
        
        try:
            # Start movement
            self.toolhead.manual_move(target_pos, speed)
            self.toolhead.wait_moves()
            
            # Stop timer
            self.reactor.update_timer(check_timer, self.reactor.NEVER)
            
            if stop_triggered[0]:
                # Sensor triggered!
                result_pos = stop_position[0]
                self._debug("PYTHON_PROBE", 2, f"✅ {sensor_name} triggered bei Z={result_pos[2]:.6f}mm")
                return result_pos
            else:
                # Movement finished, sensor not triggered
                result_pos = self.toolhead.get_position()
                return result_pos
                
        finally:
            # Cleanup: Stop timer in any case
            try:
                self.reactor.update_timer(check_timer, self.reactor.NEVER)
                self.reactor.unregister_timer(check_timer)
            except:
                pass
    
    def _sensor_probe_move(self, target_z, speed, direction='down', sensor_path=None):
        """CUSTOM SENSOR PROBE - HARDWARE-MCU IF AVAILABLE!
        Tries to use hardware MCU endstop (µs precision!)
        Falls back to Python polling (ms) if not available
        direction='down': Move DOWN until TRIGGERED (like PROBE)
        direction='up': Move UP until OPEN (mirrored)
        Returns: Z position where sensor state changed
        """
        if sensor_path is None:
            sensor_path = self.sensor_offset_path
        
        start_pos = self.toolhead.get_position()
        
        # Target position
        target_pos = list(start_pos)
        target_pos[2] = target_z
        
        # Try to get hardware MCU endstop!
        sensor_mcu_endstop = self._get_custom_sensor_mcu_endstop()
        phoming = self.printer.lookup_object('homing')
        
        if direction == 'down':
            # DOWN until TRIGGERED (like original PROBE!)
            
            # Check if sensor is OPEN at start
            if self._query_custom_sensor():
                # Sensor TRIGGERED → Fahre erst hoch bis OPEN!
                self._debug("SENSOR_MOVE", 2, f"⚠️ Sensor bereits TRIGGERED → fahre hoch bis OPEN...")
                
                # Move up in small steps until OPEN
                up_target_z = start_pos[2] + 10.0
                step_size = 0.05  # 50 micrometers
                current_z = start_pos[2]
                
                while current_z < up_target_z:
                    current_z += step_size
                    if current_z > up_target_z:
                        current_z = up_target_z
                    
                    self.toolhead.manual_move([None, None, current_z], speed)
                    self.toolhead.wait_moves()
                    
                    if not self._query_custom_sensor():
                        # OPEN gefunden!
                        self._debug("SENSOR_MOVE", 2, f"✅ Sensor OPEN bei Z={current_z:.6f} mm")
                        # Update start position für down move
                        start_pos = self.toolhead.get_position()
                        target_pos = list(start_pos)
                        target_pos[2] = target_z
                        break
                else:
                    # Konnte OPEN nicht finden
                    raise self.gcode.error(f"❌ Konnte Sensor nicht OPEN bekommen (bis Z={up_target_z:.6f}mm)")
            
            if sensor_mcu_endstop is not None:
                # ⚡ HARDWARE-MCU AVAILABLE - µs PRECISION!
                self._debug("SENSOR_MOVE", 2, f"⬇️ Sensor RUNTER bis TRIGGERED: {abs(target_z - start_pos[2]):.6f}mm @ {speed}mm/s")
                
                # WICHTIG: Binde Z-Stepper an Endstop!
                kin = self.toolhead.get_kinematics()
                for stepper in kin.get_steppers():
                    if stepper.is_active_axis('z'):
                        sensor_mcu_endstop.add_stepper(stepper)
                
                # Use probing_move() like in andere.py!
                try:
                    result_pos = phoming.probing_move(sensor_mcu_endstop, target_pos, speed)
                except self.printer.command_error as e:
                    raise self.gcode.error(f"❌ Sensor nicht triggered: {e}")
            else:
                # ⚠️ KEIN HARDWARE-MCU - Python-Polling
                self._debug("SENSOR_MOVE", 2, f"⬇️ Custom Sensor RUNTER bis TRIGGERED: Python-Polling (ms) {abs(target_z - start_pos[2]):.6f}mm @ {speed}mm/s")
                
                python_endstop = self.PythonEndstop(
                    self,
                    lambda: self._query_custom_sensor(),
                    f"Custom({sensor_path})->TRIGGERED",
                    self.probe.mcu_probe
                )
                
                result_pos = phoming.probing_move(python_endstop, target_pos, speed)
            
            # Check if sensor triggered
            if not self._query_custom_sensor():
                raise self.gcode.error(f"❌ Sensor nicht triggered bis Z={target_z:.6f}mm")
            
            self._debug("SENSOR_MOVE", 2, f"✅ Sensor TRIGGERED bei Z={result_pos[2]:.6f}mm")
            return result_pos[2]
            
        else:  # direction == 'up'
            # UP until OPEN (mirrored!)
            
            # Sensor must be TRIGGERED at start
            if not self._query_custom_sensor():
                raise self.gcode.error("❌ Sensor ist bereits OPEN beim Start!")
            
            if sensor_mcu_endstop is not None:
                # ⚡ HARDWARE-MCU AVAILABLE - USE INVERTED WRAPPER!
                self._debug("SENSOR_MOVE", 2, f"⬆️ Sensor HOCH bis OPEN: {abs(target_z - start_pos[2]):.6f}mm @ {speed}mm/s")
                
                # WICHTIG: Binde Z-Stepper an Endstop!
                kin = self.toolhead.get_kinematics()
                for stepper in kin.get_steppers():
                    if stepper.is_active_axis('z'):
                        sensor_mcu_endstop.add_stepper(stepper)
                
                # Invert sensor logic: TRIGGERED→OPEN, OPEN→TRIGGERED
                inverted_sensor = self.InvertedProbeWrapper(sensor_mcu_endstop)
                
                # Now probing_move stops at "TRIGGERED" which is actually OPEN!
                try:
                    result_pos = phoming.probing_move(inverted_sensor, target_pos, speed)
                except self.printer.command_error as e:
                    raise self.gcode.error(f"❌ Sensor nicht OPEN: {e}")
            else:
                # ⚠️ KEIN HARDWARE-MCU - Python-Polling
                self._debug("SENSOR_MOVE", 2, f"⬆️ Custom Sensor HOCH bis OPEN: Python-Polling (ms) {abs(target_z - start_pos[2]):.6f}mm @ {speed}mm/s")
                
                # Small steps with QUERY
                step_size = 0.05  # 50 micrometers
                current_z = start_pos[2]
                steps = 0
                
                while current_z < target_z:
                    current_z += step_size
                    if current_z > target_z:
                        current_z = target_z
                    
                    self.toolhead.manual_move([None, None, current_z], speed)
                    self.toolhead.wait_moves()
                    steps += 1
                    
                    if not self._query_custom_sensor():
                        # OPEN!
                        result_pos = self.toolhead.get_position()
                        self._debug("SENSOR_MOVE", 2, f"✅ Sensor OPEN bei Z={result_pos[2]:.6f}mm (nach {steps} Schritten)")
                        return result_pos[2]
                
                # Target reached without OPEN
                result_pos = self.toolhead.get_position()
            
            # Check if sensor open
            if self._query_custom_sensor():
                raise self.gcode.error(f"❌ Sensor nicht OPEN bis Z={target_z:.6f}mm")
            
            self._debug("SENSOR_MOVE", 2, f"✅ Sensor OPEN bei Z={result_pos[2]:.6f}mm")
            return result_pos[2]
    
    def _finish_measurement(self):
        """Finish measurement and show results
        OPTIMIZED ORDER: 1.Moves first 2.CPU-intensive plots 3.LEDs last
        This prevents MCU overload by separating MCU commands and CPU work!
        """
        self._debug("AUTO_OFFSET", 1, "✅ Z-Offset Messung beendet.")
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 1: BERECHNUNGEN (schnell, kein MCU)
        # ═══════════════════════════════════════════════════════════
        
        # Calculate delta
        delta = self.tap_distance_new - self.tap_distance_old
        
        # Calculate total offset
        total_offset = self.sensor_offset_value
        neg_offset = -total_offset  # Für probe.z_offset (negativ)
        pos_offset = total_offset   # Für SET_GCODE_OFFSET (positiv)
        
        # Show results
        if self.tap_distance_old > 0:
            self.gcode.respond_info(f"📏 Schaltabstand: Aktuell={self.tap_distance_new:.6f} mm | Letzte={self.tap_distance_old:.6f} mm | Δ={delta:.6f} mm")
        else:
            self.gcode.respond_info(f"📏 Schaltabstand: Aktuell={self.tap_distance_new:.6f} mm (Erstmessung)")
        
        self.gcode.respond_info(f"⚙️ Z-Offset: {total_offset:.6f} mm")
        
        # WICHTIG: ERST aktuellen probe.z_offset auslesen (VOR dem Überschreiben!)
        try:
            x_offset, y_offset, current_probe_offset = self.probe.get_offsets()
            self._debug("OFFSET", 2, f"📖 z_offset aus probe.get_offsets(): {current_probe_offset}")
        except Exception as e:
            self._debug("OFFSET", 1, f"⚠️ Konnte z_offset nicht auslesen: {e}")
            current_probe_offset = 0.0
        
        # Debug-Ausgabe: Alte und neue Werte
        self._debug("OFFSET", 1, f"💾 Aktueller probe.z_offset (aus Config): {current_probe_offset:.6f} mm")
        self._debug("OFFSET", 1, f"💾 Neuer probe.z_offset (gemessen): {neg_offset:.6f} mm")
        
        # Berechne Delta
        delta_offset = neg_offset - current_probe_offset
        self._debug("OFFSET", 1, f"📊 Delta probe.z_offset: {delta_offset:.6f} mm")
        
        # Vorzeichen umkehren für GCODE
        delta_gcode_offset = -delta_offset
        self._debug("OFFSET", 1, f"📊 Delta für GCODE Offset: {delta_gcode_offset:+.6f} mm")
        
        # Update probe.z_offset
        try:
            configfile = self.printer.lookup_object('configfile')
            configfile.set('probe', 'z_offset', str(neg_offset))
            self.gcode.respond_info(f"✅ probe.z_offset aktualisiert → SAVE_CONFIG zum dauerhaften Speichern")
        except Exception as e:
            self.gcode.respond_info(f"⚠️ Konnte probe.z_offset nicht updaten: {e}")
        
        # Speichere DELTA für später
        self.final_delta_offset = delta_gcode_offset
        self.gcode.respond_info(f"📝 Führe SAVE_CONFIG aus um dauerhaft zu speichern")
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 2: MCU MOVES (alle auf einmal, dann fertig!)
        # ═══════════════════════════════════════════════════════════
        
        # Move up and home
        self.gcode.run_script_from_command("G90")
        self.gcode.run_script_from_command("G0 Z5 F600")
        self.gcode.run_script_from_command("M400")
        self.gcode.run_script_from_command("G28 Z")
        self.gcode.run_script_from_command("M400")
        
        # Park - MCU jetzt zur Ruheposition!
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} Z{self.park_z} F6000")
        self.gcode.run_script_from_command("M400")  # Warte bis alles fertig!
        
        # Turn off heaters
        self.gcode.run_script_from_command("M104 S0")
        self.gcode.run_script_from_command("M140 S0")
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 3: VARIABLEN SPEICHERN (I/O, kein MCU)
        # ═══════════════════════════════════════════════════════════
        
        self._save_variable('tap_last_distance', self.tap_distance_new)
        self._save_variable('sensor_offset_value', self.sensor_offset_value)
        self._save_variable('macro_execution_count', self.macro_execution_count)
        
        self.gcode.respond_info(f"💾 Gespeichert: Schaltabstand={self.tap_distance_new:.6f} mm | Z-Offset={self.sensor_offset_value:.6f} mm")
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 4: PLOTS ERSTELLEN (CPU 100%, aber MCU ruht! ✅)
        # ═══════════════════════════════════════════════════════════
        
        if self.trigger_distance_enable_rt and self.tap_distance_new > 0:
            # Get current temperatures
            try:
                heater_nozzle = self.printer.lookup_object('extruder')
                heater_bed = self.printer.lookup_object('heater_bed')
                nozzle_temp = heater_nozzle.get_status(self.reactor.monotonic())['temperature']
                bed_temp = heater_bed.get_status(self.reactor.monotonic())['temperature']
            except Exception as e:
                logging.warning(f"Could not read temperatures: {e}")
                nozzle_temp = 0.0
                bed_temp = 0.0
            
            # Save measurement to history and create plots
            # MCU ist jetzt IDLE - keine Konkurrenz! ✅
            self._save_measurement_history(total_offset, nozzle_temp, bed_temp)
        else:
            self._debug("AUTO_OFFSET", 1, "ℹ️ Auswertung übersprungen (keine Trigger Distance Messung)")
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 5: LED SUCCESS (ganz am Ende, MCU hat Zeit! ✅)
        # ═══════════════════════════════════════════════════════════
        
        self._led_success()
        
        # ═══════════════════════════════════════════════════════════
        # PHASE 6: EASTER EGGS (optional, am allerletzten)
        # ═══════════════════════════════════════════════════════════
        
        if self.macro_execution_count == self.measurement_count_milestone:
            self.gcode.respond_info(" ")
            self.gcode.respond_info("🎊 ═══════════════════════════════════════════ 🎊")
            self.gcode.respond_info("🎉 MILESTONE ERREICHT! 🎉")
            self.gcode.respond_info("🎊 ═══════════════════════════════════════════ 🎊")
            self.gcode.run_script_from_command("G4 P1000")
            self.cmd_EASTER_EGG_LOCKED(None)
    
    def _save_variable(self, name, value):
        """Save variable to save_variables"""
        try:
            if self.save_variables:
                gcmd = self.gcode.create_gcode_command("SAVE_VARIABLE", "SAVE_VARIABLE",
                                                       {'VARIABLE': name, 'VALUE': str(value)})
                self.save_variables.cmd_SAVE_VARIABLE(gcmd)
        except Exception as e:
            logging.warning(f"Could not save variable {name}: {e}")
    
    def _debug(self, prefix, level, msg):
        """Debug output"""
        if self.debug_level_rt >= level:
            self.gcode.respond_info(f"{prefix} {msg}")
    
    #####################################################################
    # PHASE 5: EASTER EGGS (Ganz unten im Code!)
    #####################################################################
    
    def cmd_EASTER_EGG_SELF_DESTRUCT(self, gcmd):
        """🥚 Easter Egg 1: Self-destruct mode"""
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("🚨 SELBSTZERSTÖRUNGSMODUS AKTIVIERT! 🚨")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        # Get bed center from kinematic rails
        try:
            kin = self.toolhead.get_kinematics()
            rails = kin.rails
            xlimit = rails[0].get_range()
            ylimit = rails[1].get_range()
            bed_center_x = (xlimit[0] + xlimit[1]) / 2
            bed_center_y = (ylimit[0] + ylimit[1]) / 2
        except:
            # Fallback to default center
            bed_center_x = 175.0
            bed_center_y = 175.0
        
        # Homing if needed
        if 'xyz' not in self.toolhead.get_status(self.reactor.monotonic()).get('homed_axes', ''):
            self.gcode.run_script_from_command("G28")
        
        # Move to park position
        self.gcode.run_script_from_command("G90")
        self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        # LEDs white
        self._set_leds(1, 1, 1)
        self.gcode.run_script_from_command("G4 P1500")
        
        # Countdown
        self.gcode.respond_info("⏱️  Countdown läuft...")
        self.gcode.run_script_from_command("G4 P500")
        
        self._set_leds(1, 1, 0)  # Yellow
        self.gcode.respond_info("💥 3...")
        self.gcode.run_script_from_command("G4 P2000")
        
        self._set_leds(1, 0.5, 0)  # Orange
        self.gcode.respond_info("💥 2...")
        self.gcode.run_script_from_command("G4 P2000")
        
        self._set_leds(1, 0, 0)  # Red
        self.gcode.respond_info("💥 1...")
        self.gcode.run_script_from_command("G4 P2000")
        
        self.gcode.respond_info("💣 BUMMMM!!! 💥💥💥")
        self.gcode.run_script_from_command("G4 P300")
        
        # Move to center and shake
        self.gcode.run_script_from_command("G0 Z50 F6000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        # MEGA CHAOS shaking
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 40} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 40} Y{bed_center_y + 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 40} Y{bed_center_y - 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 40} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y + 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 40} Y{bed_center_y + 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 40} Y{bed_center_y - 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 40} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y - 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 40} Y{bed_center_y + 40} F60000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        # Reveal
        self.gcode.run_script_from_command("G4 P500")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("😂 GLÜCK GEHABT - WAR NUR EIN SPASS! 😂")
        self.gcode.respond_info("🎉 Easter Egg 1/5 gefunden!")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self._set_leds(0, 1, 0)  # Green
        self.gcode.run_script_from_command("G4 P2000")
        
        # Return to park
        self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        self.gcode.respond_info("✅ Easter Egg abgeschlossen - Drucker ist OK! 🎊")
        self.gcode.run_script_from_command("G4 P5000")
        self._set_leds(1, 1, 1)  # White
    
    def cmd_EASTER_EGG_DANCE(self, gcmd):
        """🥚 Easter Egg 3: Drucker-Tanz"""
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("💃 TANZ-MODUS AKTIVIERT! 💃")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        # Get bed center from kinematic rails
        try:
            kin = self.toolhead.get_kinematics()
            rails = kin.rails
            xlimit = rails[0].get_range()
            ylimit = rails[1].get_range()
            bed_center_x = (xlimit[0] + xlimit[1]) / 2
            bed_center_y = (ylimit[0] + ylimit[1]) / 2
        except:
            # Fallback to default center
            bed_center_x = 175.0
            bed_center_y = 175.0
        
        if 'xyz' not in self.toolhead.get_status(self.reactor.monotonic()).get('homed_axes', ''):
            self.gcode.run_script_from_command("G28")
        
        self.gcode.run_script_from_command("G90")
        self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        self._set_leds(1, 1, 1)
        self.gcode.run_script_from_command("G4 P1500")
        
        self.gcode.respond_info("🎵 Musik läuft... der Drucker tanzt!")
        self.gcode.run_script_from_command("G4 P500")
        
        # Dance choreography with LED colors
        self._set_leds(1, 0, 0)  # Red
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 50} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command("G4 P200")
        
        self._set_leds(1, 1, 0)  # Yellow
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 50} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command("G4 P200")
        
        self._set_leds(0, 1, 0)  # Green
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y + 75} F30000")
        self.gcode.run_script_from_command("G4 P500")
        
        self._set_leds(0, 1, 1)  # Cyan
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 30} Y{bed_center_y - 30} F45000")
        self.gcode.run_script_from_command("G4 P300")
        
        self._set_leds(0, 0, 1)  # Blue
        self.gcode.run_script_from_command(f"G0 X{bed_center_x - 40} Y{bed_center_y + 40} F60000")
        self.gcode.run_script_from_command("G4 P150")
        
        self._set_leds(1, 0, 1)  # Magenta
        self.gcode.run_script_from_command(f"G0 X{bed_center_x + 60} Y{bed_center_y} F60000")
        self.gcode.run_script_from_command("G4 P150")
        
        self._set_leds(1, 0.5, 0)  # Orange
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y - 50} F35000")
        self.gcode.run_script_from_command("G4 P400")
        
        self._set_leds(1, 1, 1)  # White - finale
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F20000")
        self.gcode.run_script_from_command("G4 P800")
        self.gcode.run_script_from_command("M400")
        
        self.gcode.run_script_from_command("G4 P500")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("🕺 TANZ BEENDET!")
        self.gcode.respond_info("😂 Der Drucker kann tanzen... aber nicht gut!")
        self.gcode.respond_info("🎉 Easter Egg 3/5 gefunden!")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self._set_leds(0, 1, 0)
        self.gcode.run_script_from_command("G4 P2000")
        
        self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        self.gcode.respond_info("✅ Tanz-Modus beendet - Drucker ist OK! 🎊")
        self.gcode.run_script_from_command("G4 P5000")
        self._set_leds(1, 1, 1)
    
    def cmd_EASTER_EGG_COFFEE(self, gcmd):
        """🥚 Easter Egg 2: Sauna-Modus"""
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("🧖 SAUNA-MODUS AKTIVIERT! 🔥")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        if 'xyz' not in self.toolhead.get_status(self.reactor.monotonic()).get('homed_axes', ''):
            self.gcode.run_script_from_command("G28")
        
        self.gcode.run_script_from_command("G90")
        self.gcode.run_script_from_command(f"G0 Z{self.park_z} F6000")
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} F60000")
        self.gcode.run_script_from_command("M400")
        
        self._set_leds(1, 1, 1)
        self.gcode.run_script_from_command("G4 P1500")
        
        self._set_leds(1, 0, 0)  # Red
        self.gcode.respond_info("🔥 Heize auf MAXIMUM...")
        self.gcode.run_script_from_command(f"M140 S{self.preheat_bed_temp}")
        self.gcode.run_script_from_command(f"M104 S{self.preheat_nozzle_temp}")
        self.gcode.run_script_from_command("G4 P1000")
        
        self._set_leds(1, 0.5, 0)  # Orange
        self.gcode.respond_info("♨️  Warte auf Temperatur...")
        self.gcode.run_script_from_command(f"M190 S{self.preheat_bed_temp}")
        self.gcode.run_script_from_command(f"M109 S{self.preheat_nozzle_temp}")
        
        self._set_leds(1, 1, 0)  # Yellow
        self.gcode.run_script_from_command("G4 P1000")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("🔥 SAUNA IST HEISS!")
        self.gcode.respond_info("😂 Schwitz schön... war nur ein Spaß!")
        self.gcode.respond_info("🎉 Easter Egg 2/5 gefunden!")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self._set_leds(0, 1, 0)
        self.gcode.run_script_from_command("G4 P2000")
        
        self.gcode.run_script_from_command("M104 S0")
        self.gcode.run_script_from_command("M140 S0")
        
        self.gcode.respond_info("✅ Sauna-Modus beendet - Drucker ist OK! 🎊")
        self.gcode.run_script_from_command("G4 P5000")
        self._set_leds(1, 1, 1)
    
    def cmd_EASTER_EGG_CLEAN_MODE(self, gcmd):
        """🥚 Easter Egg 4: Putz-Modus"""
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("🧹 PUTZ-MODUS AKTIVIERT! 🧹")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        # Get bed center from kinematic rails
        try:
            kin = self.toolhead.get_kinematics()
            rails = kin.rails
            xlimit = rails[0].get_range()
            ylimit = rails[1].get_range()
            bed_center_x = (xlimit[0] + xlimit[1]) / 2
            bed_center_y = (ylimit[0] + ylimit[1]) / 2
        except:
            # Fallback to default center
            bed_center_x = 175.0
            bed_center_y = 175.0
        
        if 'xyz' not in self.toolhead.get_status(self.reactor.monotonic()).get('homed_axes', ''):
            self.gcode.run_script_from_command("G28")
        
        self._set_leds(0.3, 0.3, 0.3)  # Dark white
        self.gcode.run_script_from_command("G4 P1500")
        
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F18000")
        self.gcode.run_script_from_command("M400")
        
        self.gcode.respond_info("😱 Hier ist aber dreckig!")
        self.gcode.run_script_from_command("G4 P800")
        self.gcode.respond_info("🧼 Starte intensive Reinigung...")
        self.gcode.run_script_from_command("G4 P500")
        
        # Distance from center for cleaning corners
        clean_distance = 80.0
        
        # Clean 4 corners with wiggle
        corners = [
            ("front left", bed_center_x - clean_distance, bed_center_y - clean_distance, 0.4),
            ("rear left", bed_center_x - clean_distance, bed_center_y + clean_distance, 0.5),
            ("rear right", bed_center_x + clean_distance, bed_center_y + clean_distance, 0.7),
            ("front right", bed_center_x + clean_distance, bed_center_y - clean_distance, 0.85)
        ]
        
        for name, x, y, brightness in corners:
            self._set_leds(brightness, brightness, brightness)
            self.gcode.respond_info(f"🧹 Putze {name}...")
            self.gcode.run_script_from_command(f"G0 X{x} Y{y} F18000")
            self.gcode.run_script_from_command("M400")
            self.gcode.run_script_from_command("G4 P200")
            
            # Wiggle 4x
            for _ in range(2):
                self.gcode.run_script_from_command(f"G0 X{x - 5} Y{y} F18000")
                self.gcode.run_script_from_command(f"G0 X{x + 5} Y{y} F18000")
            self.gcode.run_script_from_command(f"G0 X{x} Y{y} F18000")
            self.gcode.run_script_from_command("M400")
        
        # Polish center (8x wiggle)
        self._set_leds(1.0, 1.0, 1.0)
        self.gcode.respond_info("✨ Poliere die Mitte...")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F18000")
        self.gcode.run_script_from_command("M400")
        self.gcode.run_script_from_command("G4 P200")
        
        for _ in range(4):
            self.gcode.run_script_from_command(f"G0 X{bed_center_x - 5} Y{bed_center_y} F18000")
            self.gcode.run_script_from_command(f"G0 X{bed_center_x + 5} Y{bed_center_y} F18000")
        self.gcode.run_script_from_command(f"G0 X{bed_center_x} Y{bed_center_y} F18000")
        self.gcode.run_script_from_command("M400")
        self.gcode.run_script_from_command("G4 P800")
        
        self.gcode.run_script_from_command("G4 P500")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("✨ ALLES BLITZSAUBER!")
        self.gcode.respond_info("😂 ...oder doch nicht? War nur ein Spaß!")
        self.gcode.respond_info("🎉 Easter Egg 4/5 gefunden!")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self._set_leds(0, 1, 0)
        self.gcode.run_script_from_command("G4 P2000")
        
        self.gcode.respond_info("✅ Putz-Modus beendet - Drucker ist OK! 🎊")
        
        self.gcode.run_script_from_command(f"G0 X{self.park_x} Y{self.park_y} Z{self.park_z} F6000")
        self.gcode.run_script_from_command("M400")
        
        self.gcode.run_script_from_command("G4 P5000")
        self._set_leds(1, 1, 1)
    
    def cmd_EASTER_EGG_LOCKED(self, gcmd):
        """🥚 Easter Egg 5: Drucker gesperrt (Counter-basiert)"""
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info(f"🎊 MILESTONE ERREICHT! (Messung #{self.macro_execution_count})")
        self.gcode.respond_info("🔒 DRUCKER GESPERRT!")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self.gcode.run_script_from_command("G4 P2000")
        
        self._set_leds(1, 0, 0)  # Red
        self.gcode.respond_info("😱 Oh nein! Der Drucker ist jetzt gesperrt!")
        self.gcode.run_script_from_command("G4 P2000")
        
        self._set_leds(1, 0.5, 0)  # Orange
        self.gcode.respond_info("⏳ Entsperre Drucker...")
        self.gcode.run_script_from_command("G4 P3000")
        
        self._set_leds(0, 1, 0)  # Green
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        self.gcode.respond_info("😂 ENTSPERRT! War nur ein Spaß!")
        self.gcode.respond_info("🎉 Easter Egg 5/5 gefunden! ALLE GEFUNDEN! 🏆")
        self.gcode.respond_info("🥚 ═══════════════════════════════════════════")
        
        self.gcode.run_script_from_command("G4 P3000")
        self._set_leds(1, 1, 1)
    
    def _set_leds(self, r, g, b):
        """Helper to set LED colors"""
        # Skip wenn led_name leer oder None ist
        if not self.led_name or self.led_name.strip() == "":
            return
        
        try:
            self.gcode.run_script_from_command(f"SET_LED LED={self.led_name} RED={r} GREEN={g} BLUE={b}")
        except Exception as e:
            logging.warning(f"Could not set LEDs: {e}")
    
    def _led_error(self):
        """LED feedback on error: Blink red for 3 seconds"""
        try:
            for _ in range(6):  # 6x blink = 3 seconds
                self._set_leds(1, 0, 0)  # Red on
                self.gcode.run_script_from_command("G4 P250")  # 250ms
                self._set_leds(0, 0, 0)  # Off
                self.gcode.run_script_from_command("G4 P250")  # 250ms
        except Exception as e:
            logging.warning(f"LED error animation failed: {e}")
    
    def _raise_error(self, message):
        """Raise error with LED feedback"""
        self._led_error()
        raise self.gcode.error(message)
    
    def _led_success(self):
        """LED feedback on success: Blink green → Green on → Off"""
        try:
            # Blink green 3x
            for _ in range(3):
                self._set_leds(0, 1, 0)  # Green on
                self.gcode.run_script_from_command("G4 P300")  # 300ms
                self._set_leds(0, 0, 0)  # Off
                self.gcode.run_script_from_command("G4 P200")  # 200ms
            
            # Green on for 2 seconds
            self._set_leds(0, 1, 0)  # Green on
            self.gcode.run_script_from_command("G4 P2000")  # 2s
            
            # Off
            self._set_leds(0, 0, 0)
        except Exception as e:
            logging.warning(f"LED success animation failed: {e}")
    
    #####################################################################
    # HISTORY & PLOT FUNCTIONS
    #####################################################################
    
    def _save_measurement_history(self, final_offset, nozzle_temp, bed_temp):
        """Save current measurement to CSV and create plots"""
        try:
            # Get probe accuracy samples if available
            samples = getattr(self, '_last_probe_samples', [final_offset] * 5)
            stddev = getattr(self, '_last_probe_stddev', 0.0)
            
            # Ensure plot directory exists
            plot_dir = os.path.expanduser(self.plot_path)
            os.makedirs(plot_dir, exist_ok=True)
            
            # CSV file path
            csv_path = os.path.join(plot_dir, 'measurement_history.csv')
            
            # Check if file exists to write header
            file_exists = os.path.isfile(csv_path)
            
            # Append measurement to CSV
            with open(csv_path, 'a', newline='') as csvfile:
                fieldnames = ['timestamp', 'offset', 'nozzle_temp', 'bed_temp', 
                             'trigger_distance', 'stddev', 'sample1', 'sample2', 
                             'sample3', 'sample4', 'sample5']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                # Write header if new file
                if not file_exists:
                    writer.writeheader()
                
                # Write measurement
                writer.writerow({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'offset': f'{final_offset:.6f}',
                    'nozzle_temp': f'{nozzle_temp:.1f}',
                    'bed_temp': f'{bed_temp:.1f}',
                    'trigger_distance': f'{self.tap_distance_new:.6f}',
                    'stddev': f'{stddev:.6f}',
                    'sample1': f'{samples[0]:.6f}' if len(samples) > 0 else '',
                    'sample2': f'{samples[1]:.6f}' if len(samples) > 1 else '',
                    'sample3': f'{samples[2]:.6f}' if len(samples) > 2 else '',
                    'sample4': f'{samples[3]:.6f}' if len(samples) > 3 else '',
                    'sample5': f'{samples[4]:.6f}' if len(samples) > 4 else ''
                })
            
            self._debug("HISTORY", 1, f"📄 Messung gespeichert in CSV: {csv_path}")
            
            # Create plots
            current_data = {
                'samples': samples,
                'final_offset': final_offset,
                'nozzle_temp': nozzle_temp,
                'bed_temp': bed_temp,
                'stddev': stddev,
                'trigger_distance': self.tap_distance_new,
                'sensor_offset': self.sensor_offset_value
            }
            self._create_plots(current_data)
            
        except Exception as e:
            error_msg = f"Failed to save measurement history: {e}"
            logging.error(error_msg)
            self.gcode.respond_info(f"⚠️ {error_msg}")
    
    def _create_plots(self, current_data):
        """Create both history and current measurement plots"""
        if not MATPLOTLIB_AVAILABLE:
            self._debug("PLOTS", 1, "⚠️ Matplotlib nicht verfügbar - Plots deaktiviert")
            return
        
        if not self.create_plot:
            self._debug("PLOTS", 1, "ℹ️ Plot-Erstellung deaktiviert (create_plot=0)")
            return
        
        try:
            # Ensure plot directory exists
            plot_path = os.path.expanduser(self.plot_path)
            os.makedirs(plot_path, exist_ok=True)
            self._debug("PLOTS", 2, f"📁 Plot-Ordner: {plot_path}")
            
            # Create both plots
            self._create_history_plot(plot_path)
            self._create_current_plot(plot_path, current_data)
            
            self._debug("PLOTS", 1, f"✅ Plots erstellt in: {plot_path}")
        except Exception as e:
            error_msg = f"Plot creation failed: {e}"
            logging.error(error_msg)
            self.gcode.respond_info(f"⚠️ {error_msg}")
    
    def _create_history_plot(self, plot_path):
        """Create history plot of last N measurements from CSV"""
        try:
            # CSV file path
            csv_path = os.path.join(plot_path, 'measurement_history.csv')
            
            if not os.path.isfile(csv_path):
                self._debug("PLOTS", 2, "No CSV history file found")
                return
            
            # Read CSV
            timestamps = []
            offsets = []
            trigger_distances = []
            nozzle_temps = []
            bed_temps = []
            
            with open(csv_path, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                rows = list(reader)
                
                if len(rows) < 2:
                    self._debug("PLOTS", 2, "Not enough history data for plot")
                    return
                
                # Get last N measurements
                rows = rows[-self.plot_history_count:]
                
                # Extract data
                for row in rows:
                    timestamps.append(datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S'))
                    offsets.append(float(row['offset']))
                    trigger_distances.append(float(row['trigger_distance']))
                    nozzle_temps.append(float(row['nozzle_temp']))
                    bed_temps.append(float(row['bed_temp']))
            
            # Create figure with professional layout (4 rows: Header + 3 plots)
            # Temperatur-Plot flacher für mehr Platz bei Z-Offset & Trigger Distance
            fig = plt.figure(figsize=(16, 12))
            gs = fig.add_gridspec(4, 1, height_ratios=[0.3, 1.8, 1.8, 0.6], hspace=0.35)
            
            # Header
            ax_header = fig.add_subplot(gs[0])
            ax_header.axis('off')
            
            avg_offset = sum(offsets) / len(offsets)
            offset_range = max(offsets) - min(offsets)
            avg_trigger = sum(trigger_distances) / len(trigger_distances)
            trigger_range = max(trigger_distances) - min(trigger_distances)
            timestamp_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            header_text = f"""AUTO OFFSET - MEASUREMENT HISTORY
{timestamp_now} | Sensor: Custom MCU Endstop | Probe: Voron TAP
Last {len(offsets)} measurements | Z-Offset Avg: {avg_offset:.6f} mm (Range: {offset_range:.6f} mm) | Trigger Avg: {avg_trigger:.6f} mm
X-Achse: Messungen #1-#{len(offsets)} (feste Positionen, unabhängig von Zeit)"""
            
            ax_header.text(0.5, 0.5, header_text, fontsize=10, family='monospace',
                          verticalalignment='center', horizontalalignment='center', bbox=dict(boxstyle='round,pad=0.5', 
                          facecolor='#E8F4F8', edgecolor='#0066CC', linewidth=2))
            
            # Plot 1: Z-Offset - Balken an festen Positionen
            ax1 = fig.add_subplot(gs[1])
            
            # Feste Positionen: 1, 2, 3, ..., N (unabhängig von Zeit!)
            positions = list(range(1, len(offsets) + 1))
            
            # Balken
            bars1 = ax1.bar(positions, offsets, color='#0066CC', alpha=0.7, 
                           edgecolor='#003366', linewidth=1.5, width=0.8, label='Z-Offset')
            
            # Verlaufslinie über Balken
            ax1.plot(positions, offsets, 'o-', color='#003366', linewidth=2.5, 
                    markersize=8, markeredgecolor='white', markeredgewidth=1.5, 
                    label='Trend', zorder=10)
            
            # Average line
            ax1.axhline(y=avg_offset, color='#FF6B6B', linestyle='--', linewidth=2, 
                       alpha=0.8, label=f'Average: {avg_offset:.6f} mm', zorder=9)
            
            # X-Achse Labels: Messungsnummer
            ax1.set_xticks(positions)
            ax1.set_xticklabels([f'#{p}' for p in positions], fontsize=10)
            
            ax1.set_xlabel('Measurement Number', fontsize=12, fontweight='bold')
            ax1.set_ylabel('Z-Offset (mm)', fontsize=12, fontweight='bold')
            ax1.set_title('Z-OFFSET HISTORY', fontsize=13, fontweight='bold', pad=10, color='#0066CC')
            ax1.grid(True, alpha=0.4, linestyle='--', linewidth=0.8, axis='y')
            ax1.legend(loc='best', fontsize=10, framealpha=0.9)
            
            # Plot 2: Trigger Distance - Balken an festen Positionen
            ax2 = fig.add_subplot(gs[2])
            
            # Balken
            bars2 = ax2.bar(positions, trigger_distances, color='#4ECDC4', alpha=0.7, 
                           edgecolor='#2A9D8F', linewidth=1.5, width=0.8, label='Trigger Distance')
            
            # Verlaufslinie über Balken
            ax2.plot(positions, trigger_distances, 'o-', color='#2A9D8F', linewidth=2.5, 
                    markersize=8, markeredgecolor='white', markeredgewidth=1.5, 
                    label='Trend', zorder=10)
            
            # Average line
            ax2.axhline(y=avg_trigger, color='#FF6B6B', linestyle='--', linewidth=2, 
                       alpha=0.8, label=f'Average: {avg_trigger:.6f} mm', zorder=9)
            
            # X-Achse Labels: Messungsnummer
            ax2.set_xticks(positions)
            ax2.set_xticklabels([f'#{p}' for p in positions], fontsize=10)
            
            ax2.set_xlabel('Measurement Number', fontsize=12, fontweight='bold')
            ax2.set_ylabel('Trigger Distance (mm)', fontsize=12, fontweight='bold')
            ax2.set_title('TRIGGER DISTANCE HISTORY', fontsize=13, fontweight='bold', pad=10, color='#0066CC')
            ax2.grid(True, alpha=0.4, linestyle='--', linewidth=0.8, axis='y')
            ax2.legend(loc='best', fontsize=10, framealpha=0.9)
            
            # Plot 3: Temperatures (FLACHER! Nur Übersicht)
            ax3 = fig.add_subplot(gs[3])
            
            # Linien (ohne Marker wegen wenig Platz)
            ax3.plot(positions, nozzle_temps, '-', color='#FF6347', linewidth=2, 
                    label='Nozzle', marker='o', markersize=5)
            ax3.plot(positions, bed_temps, '-', color='#4169E1', linewidth=2, 
                    label='Bed', marker='s', markersize=5)
            
            # X-Achse: Datum/Zeit klein unter Balken
            ax3.set_xticks(positions)
            datetime_labels = [ts.strftime('%m/%d\n%H:%M') for ts in timestamps]
            ax3.set_xticklabels(datetime_labels, fontsize=7, rotation=0)
            
            ax3.set_ylabel('Temp (°C)', fontsize=10, fontweight='bold')
            ax3.set_xlabel('Date/Time', fontsize=10, fontweight='bold')
            ax3.set_title('TEMPERATURE HISTORY', fontsize=11, fontweight='bold', pad=8, color='#0066CC')
            ax3.grid(True, alpha=0.4, linestyle='--', linewidth=0.8, axis='y')
            ax3.legend(loc='best', fontsize=9, framealpha=0.9)
            
            # Save plot with white background
            plot_file = os.path.join(plot_path, 'auto_offset_history.png')
            plt.savefig(plot_file, dpi=150, bbox_inches='tight', facecolor='white')
            plt.close()
            
            self._debug("PLOTS", 2, f"✅ History plot saved: {plot_file}")
            
        except Exception as e:
            logging.error(f"History plot creation failed: {e}")
    
    def _create_current_plot(self, plot_path, data):
        """Create detailed plot of current measurement - Shake&Tune inspired design"""
        try:
            # Extract data
            samples = data.get('samples', [])
            final_offset = data.get('final_offset', 0.0)
            nozzle_temp = data.get('nozzle_temp', 0)
            bed_temp = data.get('bed_temp', 0)
            stddev = data.get('stddev', 0.0)
            trigger_distance = data.get('trigger_distance', 0.0)
            sensor_offset = data.get('sensor_offset', 0.0)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Calculate statistics (echte Werte - KEIN Offset mehr!)
            if len(samples) > 0:
                mean_sample = sum(samples) / len(samples)
                min_sample = min(samples)
                max_sample = max(samples)
                range_sample = max_sample - min_sample
            else:
                mean_sample = final_offset
                min_sample = final_offset
                max_sample = final_offset
                range_sample = 0.0
            
            # Echte Werte verwenden (KEIN +1mm Offset mehr!)
            plot_samples = samples  # Echte Werte!
            plot_mean = mean_sample  # Echte Werte!
            
            # Create figure with custom layout
            fig = plt.figure(figsize=(16, 10))
            
            # Create grid for subplots (70% left for samples, 30% right for overview)
            gs = fig.add_gridspec(3, 2, height_ratios=[0.5, 2, 1], width_ratios=[7, 3], 
                                hspace=0.3, wspace=0.3)
            
            # Header (spans full width)
            ax_header = fig.add_subplot(gs[0, :])
            ax_header.axis('off')
            
            # Header text - technical details like Shake&Tune
            header_text = f"""AUTO OFFSET - PRECISION Z-CALIBRATION TOOL
{timestamp} | Sensor: Custom MCU Endstop | Probe: Voron TAP | Samples: {len(samples)}
Nozzle: {nozzle_temp:.0f}°C | Bed: {bed_temp:.0f}°C | Tolerance: {self.probe_tolerance:.6f} mm
Probe Samples: Echte Werte mit Z=0 Referenzlinie | Y-Achse: ±{self.probe_tolerance:.3f} mm"""
            
            ax_header.text(0.5, 0.5, header_text, fontsize=10, family='monospace',
                          verticalalignment='center', horizontalalignment='center', bbox=dict(boxstyle='round,pad=0.5', 
                          facecolor='#E8F4F8', edgecolor='#0066CC', linewidth=2))
            
            # Plot 1: Probe Samples (ZOOMED!) - top row
            ax1 = fig.add_subplot(gs[1, 0])
            sample_nums = list(range(1, len(samples) + 1))
            
            # Use gradient colors for bars
            colors = plt.cm.viridis([(s - min_sample) / (range_sample + 0.000001) for s in samples])
            bars = ax1.bar(sample_nums, plot_samples, color=colors, alpha=0.8, edgecolor='#333333', linewidth=1.5)
            
            # Add value labels on bars (echte Werte)
            for i, (bar, val) in enumerate(zip(bars, plot_samples)):
                height = bar.get_height()
                # Label oberhalb oder unterhalb je nach Wert
                if height >= 0:
                    va = 'bottom'
                    y_pos = height
                else:
                    va = 'top'
                    y_pos = height
                ax1.text(bar.get_x() + bar.get_width()/2., y_pos,
                        f'{val:.6f}', ha='center', va=va, fontsize=8, fontweight='bold')
            
            # Z=0 REFERENZLINIE (rot, gestrichelt)
            ax1.axhline(y=0, color='red', linestyle='--', linewidth=2.5, 
                       label='Z=0 Reference', zorder=10, alpha=0.8)
            
            # Mean line (echte Werte)
            ax1.axhline(y=plot_mean, color='#FF6B6B', linestyle=':', linewidth=2, 
                       label=f'Mean: {plot_mean:.6f} mm', zorder=9, alpha=0.7)
            
            # Y-Achse: Dynamisch basierend auf probe_tolerance
            # Zeige ±probe_tolerance um Z=0
            y_limit = self.probe_tolerance
            ax1.set_ylim(-y_limit, +y_limit)
            
            ax1.set_xlabel('Sample Number', fontsize=11, fontweight='bold')
            ax1.set_ylabel('Z-Position (mm)', fontsize=11, fontweight='bold')
            ax1.set_title('PROBE ACCURACY SAMPLES (Z=0 Referenced)', fontsize=12, fontweight='bold', 
                         pad=10, color='#0066CC')
            ax1.grid(True, alpha=0.4, linestyle='--', linewidth=0.8)
            ax1.legend(loc='best', fontsize=9, framealpha=0.9)
            
            # Plot 2: Full Range Overview - top right (2 BALKEN!)
            ax2 = fig.add_subplot(gs[1, 1])
            
            # Show measurement overview - ONLY 2 bars (ECHTE WERTE ohne Offset!)
            full_range_data = [trigger_distance, final_offset]
            full_range_labels = ['Trigger\nDistance', 'Final\nZ-Offset']
            colors_full = ['#4ECDC4', '#FF6B6B']
            
            bars2 = ax2.bar(full_range_labels, full_range_data, color=colors_full, alpha=0.8, 
                           edgecolor='#333333', linewidth=1.5)
            
            # Add value labels (ECHTE WERTE)
            for bar, val in zip(bars2, full_range_data):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{val:.6f}\nmm', ha='center', va='bottom', fontsize=9, fontweight='bold')
            
            # Dynamic Y-axis: Start from 0 with padding for text
            max_val = max(full_range_data)
            y_limit = max_val * 1.20  # 20% padding above highest bar for text
            ax2.set_ylim(0, y_limit)
            
            ax2.set_ylabel('Z-Position (mm)', fontsize=11, fontweight='bold')
            ax2.set_title('MEASUREMENT OVERVIEW', fontsize=12, fontweight='bold', 
                         pad=10, color='#0066CC')
            ax2.grid(True, alpha=0.4, axis='y', linestyle='--', linewidth=0.8)
            
            # Statistics Table - bottom
            ax3 = fig.add_subplot(gs[2, :])
            ax3.axis('off')
            
            # Create professional statistics table
            stats_data = [
                ['PROBE STATISTICS', '', 'MEASUREMENT RESULTS', ''],
                ['────────────────', '─────────', '────────────────────', '──────────'],
                ['Mean:', f'{mean_sample:.6f} mm', 'Trigger Distance:', f'{trigger_distance:.6f} mm'],
                ['Min:', f'{min_sample:.6f} mm', 'Final Z-Offset:', f'{final_offset:.6f} mm'],
                ['Max:', f'{max_sample:.6f} mm', '', ''],
                ['Range:', f'{range_sample:.6f} mm', 'Status:', '✓ PASS' if range_sample <= self.probe_tolerance else '✗ FAIL'],
                ['Std Dev:', f'{stddev:.6f} mm', 'Tolerance:', f'{self.probe_tolerance:.6f} mm'],
                ['Samples:', f'{len(samples)}', '', ''],
            ]
            
            table = ax3.table(cellText=stats_data, cellLoc='left', loc='center',
                            colWidths=[0.25, 0.25, 0.25, 0.25])
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1, 2)
            
            # Style table
            for i, row in enumerate(stats_data):
                for j in range(4):
                    cell = table[(i, j)]
                    if i == 0:  # Header
                        cell.set_facecolor('#0066CC')
                        cell.set_text_props(weight='bold', color='white', fontsize=11)
                    elif i == 1:  # Separator
                        cell.set_facecolor('#E8F4F8')
                        cell.set_text_props(fontfamily='monospace', fontsize=8)
                    else:
                        if j in [0, 2]:  # Labels
                            cell.set_facecolor('#F0F0F0')
                            cell.set_text_props(weight='bold')
                        else:  # Values
                            cell.set_facecolor('#FFFFFF')
                            cell.set_text_props(fontfamily='monospace')
                    cell.set_edgecolor('#CCCCCC')
            
            # Save plot
            plot_file = os.path.join(plot_path, 'auto_offset_current.png')
            plt.savefig(plot_file, dpi=150, bbox_inches='tight', facecolor='white')
            plt.close()
            
            self._debug("PLOTS", 2, f"✅ Current plot saved: {plot_file}")
            
        except Exception as e:
            logging.error(f"Current plot creation failed: {e}")

def load_config(config):
    """Load AutoOffset with integrated ProbeSilent"""
    # Create AutoOffset instance
    auto_offset = AutoOffset(config)
    
    # Create and register ProbeSilent
    printer = config.get_printer()
    gcode = printer.lookup_object('gcode')
    
    # Create ProbeSilent instance (using same config section)
    probe_silent = ProbeSilent(config)
    
    # Register QUERY_PROBE_SILENT command
    def cmd_QUERY_PROBE_SILENT(gcmd):
        probe_silent.query_and_update(gcmd)
        # Silent - no output
    
    gcode.register_command("QUERY_PROBE_SILENT", cmd_QUERY_PROBE_SILENT)
    
    # Register probe_silent object for external access
    printer.add_object('probe_silent', probe_silent)
    
    return auto_offset
