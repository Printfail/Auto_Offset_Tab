#!/bin/bash
#####################################################################
# AUTO_OFFSET INSTALLATION SCRIPT
# Mit Menü-System, Logo und Symlinks (wie Happy Hare)
#####################################################################

VERSION="1.0.0"
GITHUB_REPO="https://github.com/Printfail/Auto_Offset_Tab.git"
REPO_NAME="Auto_Offset_Tab"

# Farben
OFF='\033[0m'
B_RED='\033[1;31m'
B_GREEN='\033[1;32m'
B_YELLOW='\033[1;33m'
B_CYAN='\033[1;36m'
B_WHITE='\033[1;37m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'

# Pfade
SCRIPTPATH="$(dirname "$(readlink -f "$0")")"
KLIPPER_HOME="${HOME}/klipper"
KLIPPER_CONFIG_HOME="${HOME}/printer_data/config"
KLIPPER_EXTRAS="${KLIPPER_HOME}/klippy/extras"
CONFIG_DIR="${KLIPPER_CONFIG_HOME}/Auto_Offset"

# GitHub Installation: Prüfe ob wir im geklonten Repo sind
# Falls nicht: Klone das Repo erst
if [ ! -d "${SCRIPTPATH}/extras" ]; then
    # Wir sind NICHT im Repository - wahrscheinlich One-Liner Install
    INSTALL_DIR="${HOME}/${REPO_NAME}"
    
    echo -e "${B_CYAN}═══════════════════════════════════════════════════════${OFF}"
    echo -e "${B_CYAN}  GitHub Installation${OFF}"
    echo -e "${B_CYAN}═══════════════════════════════════════════════════════${OFF}"
    echo ""
    
    # Prüfe ob bereits geklont
    if [ -d "${INSTALL_DIR}" ]; then
        echo -e "${B_YELLOW}⚠${OFF} Repository existiert bereits in ${INSTALL_DIR}"
        read -p "$(echo -e ${CYAN}Git Pull für Update? \(y/n\): ${OFF})" yn
        case $yn in
            [JjYy]* )
                cd "${INSTALL_DIR}"
                git pull
                ;;
            * )
                echo -e "${CYAN}ℹ${OFF} Verwende existierendes Repository"
                ;;
        esac
    else
        echo -e "${B_GREEN}➜${OFF} Klone Repository von GitHub..."
        git clone "${GITHUB_REPO}" "${INSTALL_DIR}"
        if [ $? -ne 0 ]; then
            echo -e "${B_RED}✗${OFF} Git Clone fehlgeschlagen!"
            exit 1
        fi
        echo -e "${B_GREEN}✓${OFF} Repository geklont"
    fi
    
    # Wechsle ins Repository und führe Script erneut aus
    echo ""
    echo -e "${B_GREEN}➜${OFF} Starte Installation aus Repository..."
    cd "${INSTALL_DIR}"
    chmod +x install.sh 2>/dev/null || true  # Setze Execute-Rechte (falls nötig)
    bash ./install.sh
    exit 0
fi

# Wir sind im Repository - normale Installation
SRCDIR="${SCRIPTPATH}"

#####################################################################
# LOGO & HEADER
#####################################################################

show_logo() {
    clear
    echo -e "${B_CYAN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo -e "${B_CYAN}║${B_WHITE}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_GREEN}            █████╗ ██╗   ██╗████████╗ ██████╗               ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_GREEN}           ██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗              ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_GREEN}           ███████║██║   ██║   ██║   ██║   ██║              ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_YELLOW}           ██╔══██║██║   ██║   ██║   ██║   ██║              ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_YELLOW}           ██║  ██║╚██████╔╝   ██║   ╚██████╔╝              ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_YELLOW}           ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝               ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_CYAN}                   ╔═╗╔═╗╔═╗╔═╗╔═╗╔╦╗                       ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_CYAN}                   ║ ║╠╣ ╠╣ ╚═╗║╣  ║                        ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_CYAN}                   ╚═╝╚  ╚  ╚═╝╚═╝ ╩                        ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}╠════════════════════════════════════════════════════════════╣${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}           🎯 Precision Z-Offset Calibration 🎯             ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${PURPLE}               ⚡ µm-Accurate Probing ⚡                    ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                    Version ${VERSION}                           ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}╚════════════════════════════════════════════════════════════╝${OFF}"
    echo -e "${OFF}"
    echo ""
}

#####################################################################
# HELPER FUNKTIONEN
#####################################################################

print_msg() {
    echo -e "${B_GREEN}➜${OFF} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${OFF} $1"
}

print_warning() {
    echo -e "${B_YELLOW}⚠${OFF} $1"
}

print_error() {
    echo -e "${B_RED}✗${OFF} $1"
}

print_success() {
    echo -e "${B_GREEN}✓${OFF} $1"
}

ask_yn() {
    # Bei non-interactive Installation: Auto-Yes
    if [ "${NON_INTERACTIVE}" = "1" ]; then
        return 0
    fi
    
    while true; do
        read -p "$(echo -e ${CYAN}$1 \(y/n\): ${OFF})" yn
        case $yn in
            [JjYy]* ) return 0;;
            [Nn]* ) return 1;;
            * ) echo "Bitte 'y' oder 'n' eingeben.";;
        esac
    done
}

#####################################################################
# MENÜ
#####################################################################

show_menu() {
    show_logo
    echo -e "${B_CYAN}╔════════════════════════════════════════════════════════════╗${OFF}"
    echo -e "${B_CYAN}║${B_WHITE}                        HAUPT-MENÜ                          ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}╠════════════════════════════════════════════════════════════╣${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}  ${B_GREEN}1)${OFF} Neu installieren                                       ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}     ${DIM}Erstinstallation mit Symlinks${OFF}                          ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}  ${B_YELLOW}2)${OFF} Update / Re-installieren                               ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}     ${DIM}Aktualisiert Code, behaelt Config${OFF}                      ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}  ${B_RED}3)${OFF} Deinstallieren                                         ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}     ${DIM}Entfernt alle Dateien${OFF}                                  ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}  ${B_CYAN}4)${OFF} Status anzeigen                                        ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}     ${DIM}Prueft Installation${OFF}                                    ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}  ${B_WHITE}5)${OFF} Beenden                                                ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}║${OFF}                                                            ${B_CYAN}║${OFF}"
    echo -e "${B_CYAN}╚════════════════════════════════════════════════════════════╝${OFF}"
    echo ""
}

#####################################################################
# PRÜFUNGEN
#####################################################################

check_klipper() {
    if [ ! -d "${KLIPPER_EXTRAS}" ]; then
        print_error "Klipper nicht gefunden: ${KLIPPER_EXTRAS}"
        exit 1
    fi
    print_success "Klipper gefunden: ${KLIPPER_HOME}"
}

check_source_files() {
    if [ ! -f "${SRCDIR}/extras/auto_offset.py" ]; then
        print_error "auto_offset.py nicht gefunden!"
        exit 1
    fi
    if [ ! -f "${SRCDIR}/config/Auto_Offset_Variables.cfg" ]; then
        print_error "Auto_Offset_Variables.cfg nicht gefunden!"
        exit 1
    fi
    if [ ! -f "${SRCDIR}/config/Auto_Offset.cfg" ]; then
        print_error "Auto_Offset.cfg nicht gefunden!"
        exit 1
    fi
    print_success "Quell-Dateien gefunden"
}

#####################################################################
# INSTALLATION (mit Symlinks!)
#####################################################################

do_install() {
    # Bei interaktivem Aufruf: Zeige Logo/Header
    if [ "${NON_INTERACTIVE}" != "1" ]; then
        show_logo
        echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
        echo -e "${B_YELLOW}  INSTALLATION${OFF}"
        echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
        echo ""
    fi
    
    print_msg "Prüfe Voraussetzungen..."
    check_klipper
    check_source_files
    echo ""
    
    # Python-Modul (Symlink!)
    print_msg "Installiere Python-Modul..."
    if [ -L "${KLIPPER_EXTRAS}/auto_offset.py" ]; then
        print_warning "Symlink existiert bereits - wird aktualisiert"
        rm -f "${KLIPPER_EXTRAS}/auto_offset.py"
    elif [ -f "${KLIPPER_EXTRAS}/auto_offset.py" ]; then
        print_warning "Alte Datei gefunden - wird durch Symlink ersetzt"
        rm -f "${KLIPPER_EXTRAS}/auto_offset.py"
    fi
    ln -sf "${SRCDIR}/extras/auto_offset.py" "${KLIPPER_EXTRAS}/auto_offset.py"
    print_success "Python-Modul verlinkt (Symlink)"
    echo ""
    
    # Config-Ordner
    if [ ! -d "${CONFIG_DIR}" ]; then
        print_msg "Erstelle Config-Ordner..."
        mkdir -p "${CONFIG_DIR}"
        chmod 775 "${CONFIG_DIR}"
        print_success "Ordner erstellt: ${CONFIG_DIR}"
    fi
    
    # Auswertung-Ordner
    if [ ! -d "${CONFIG_DIR}/Auswertung" ]; then
        print_msg "Erstelle Auswertung-Ordner..."
        mkdir -p "${CONFIG_DIR}/Auswertung"
        chmod 775 "${CONFIG_DIR}/Auswertung"
        print_success "Ordner erstellt: ${CONFIG_DIR}/Auswertung"
    fi
    
    # Config-Dateien (nur wenn nicht vorhanden!)
    if [ ! -f "${CONFIG_DIR}/Auto_Offset_Variables.cfg" ]; then
        print_msg "Installiere Auto_Offset_Variables.cfg..."
        cp "${SRCDIR}/config/Auto_Offset_Variables.cfg" "${CONFIG_DIR}/"
        chmod 644 "${CONFIG_DIR}/Auto_Offset_Variables.cfg"
        print_success "Auto_Offset_Variables.cfg installiert"
    else
        print_warning "Auto_Offset_Variables.cfg existiert bereits - wird NICHT überschrieben"
    fi
    
    if [ ! -f "${CONFIG_DIR}/Auto_Offset.cfg" ]; then
        print_msg "Installiere Auto_Offset.cfg..."
        cp "${SRCDIR}/config/Auto_Offset.cfg" "${CONFIG_DIR}/"
        chmod 644 "${CONFIG_DIR}/Auto_Offset.cfg"
        print_success "Auto_Offset.cfg installiert"
    else
        print_warning "Auto_Offset.cfg existiert bereits - wird NICHT überschrieben"
    fi
    echo ""
    
    # Aufräumen
    if [ -f "${KLIPPER_EXTRAS}/probe_silent.py" ]; then
        print_msg "Entferne alte probe_silent.py..."
        rm -f "${KLIPPER_EXTRAS}/probe_silent.py"
        print_success "probe_silent.py entfernt"
        echo ""
    fi
    
    print_success "Installation abgeschlossen!"
    echo ""
    
    # Klipper Restart
    if ask_yn "Klipper jetzt neu starten?"; then
        print_msg "Starte Klipper neu..."
        sudo systemctl restart klipper
        sleep 2
        print_success "Klipper neu gestartet!"
    fi
    echo ""
    
    show_next_steps
}

#####################################################################
# UPDATE
#####################################################################

do_update() {
    show_logo
    echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
    echo -e "${B_YELLOW}  UPDATE${OFF}"
    echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
    echo ""
    
    print_msg "Aktualisiere Python-Modul (Symlink)..."
    rm -f "${KLIPPER_EXTRAS}/auto_offset.py"
    ln -sf "${SRCDIR}/extras/auto_offset.py" "${KLIPPER_EXTRAS}/auto_offset.py"
    print_success "Python-Modul aktualisiert"
    echo ""
    
    # Auswertung-Ordner erstellen falls nicht vorhanden
    if [ ! -d "${CONFIG_DIR}/Auswertung" ]; then
        print_msg "Erstelle Auswertung-Ordner..."
        mkdir -p "${CONFIG_DIR}/Auswertung"
        chmod 775 "${CONFIG_DIR}/Auswertung"
        print_success "Ordner erstellt: ${CONFIG_DIR}/Auswertung"
    fi
    
    # Auto_Offset.cfg immer überschreiben (enthält nur Makros, keine User-Einstellungen)
    print_msg "Aktualisiere Auto_Offset.cfg (Makros)..."
    cp -f "${SRCDIR}/config/Auto_Offset.cfg" "${CONFIG_DIR}/"
    chmod 644 "${CONFIG_DIR}/Auto_Offset.cfg"
    print_success "Auto_Offset.cfg aktualisiert"
    echo ""
    
    print_warning "Auto_Offset_Variables.cfg wird NICHT überschrieben (um deine Einstellungen zu behalten)"
    echo ""
    
    print_success "Update abgeschlossen!"
    echo ""
    
    if ask_yn "Klipper jetzt neu starten?"; then
        print_msg "Starte Klipper neu..."
        sudo systemctl restart klipper
        sleep 2
        print_success "Klipper neu gestartet!"
    fi
    echo ""
}

#####################################################################
# DEINSTALLATION
#####################################################################

do_uninstall() {
    show_logo
    echo -e "${B_RED}═══════════════════════════════════════════════════════${OFF}"
    echo -e "${B_RED}  DEINSTALLATION${OFF}"
    echo -e "${B_RED}═══════════════════════════════════════════════════════${OFF}"
    echo ""
    
    print_warning "Dies wird Auto_Offset vollständig entfernen!"
    echo ""
    
    if ! ask_yn "Wirklich deinstallieren?"; then
        print_info "Abgebrochen"
        return
    fi
    echo ""
    
    # Python-Modul
    if [ -L "${KLIPPER_EXTRAS}/auto_offset.py" ] || [ -f "${KLIPPER_EXTRAS}/auto_offset.py" ]; then
        print_msg "Entferne Python-Modul..."
        rm -f "${KLIPPER_EXTRAS}/auto_offset.py"
        print_success "Python-Modul entfernt"
    fi
    
    # Config (nur wenn gewünscht)
    if [ -d "${CONFIG_DIR}" ]; then
        echo ""
        if ask_yn "Auch Config-Ordner löschen? (Einstellungen gehen verloren!)"; then
            print_msg "Entferne Config-Ordner..."
            rm -rf "${CONFIG_DIR}"
            print_success "Config entfernt"
        else
            print_info "Config bleibt erhalten"
        fi
    fi
    
    echo ""
    print_success "Deinstallation abgeschlossen!"
    echo ""
    print_warning "Entferne folgende Zeilen aus printer.cfg:"
    print_warning "  [include Auto_Offset/Auto_Offset_Variables.cfg]"
    print_warning "  [include Auto_Offset/Auto_Offset.cfg]"
    echo ""
    
    if ask_yn "Klipper jetzt neu starten?"; then
        print_msg "Starte Klipper neu..."
        sudo systemctl restart klipper
        sleep 2
        print_success "Klipper neu gestartet!"
    fi
    echo ""
}

#####################################################################
# STATUS
#####################################################################

show_status() {
    show_logo
    echo -e "${B_WHITE}═══════════════════════════════════════════════════════${OFF}"
    echo -e "${B_WHITE}  STATUS${OFF}"
    echo -e "${B_WHITE}═══════════════════════════════════════════════════════${OFF}"
    echo ""
    
    # Python-Modul
    if [ -L "${KLIPPER_EXTRAS}/auto_offset.py" ]; then
        print_success "Python-Modul: Installiert (Symlink)"
        print_info "  Link: $(readlink "${KLIPPER_EXTRAS}/auto_offset.py")"
    elif [ -f "${KLIPPER_EXTRAS}/auto_offset.py" ]; then
        print_warning "Python-Modul: Installiert (Datei, kein Symlink!)"
    else
        print_error "Python-Modul: Nicht installiert"
    fi
    
    # Config
    if [ -f "${CONFIG_DIR}/Auto_Offset_Variables.cfg" ]; then
        print_success "Auto_Offset_Variables.cfg: Installiert"
        print_info "  Pfad: ${CONFIG_DIR}/Auto_Offset_Variables.cfg"
    else
        print_error "Auto_Offset_Variables.cfg: Nicht installiert"
    fi
    
    if [ -f "${CONFIG_DIR}/Auto_Offset.cfg" ]; then
        print_success "Auto_Offset.cfg: Installiert"
        print_info "  Pfad: ${CONFIG_DIR}/Auto_Offset.cfg"
    else
        print_error "Auto_Offset.cfg: Nicht installiert"
    fi
    
    # Klipper
    if systemctl is-active --quiet klipper; then
        print_success "Klipper: Läuft"
    else
        print_error "Klipper: Gestoppt"
    fi
    
    echo ""
}

#####################################################################
# NÄCHSTE SCHRITTE
#####################################################################

show_next_steps() {
    echo -e "${B_GREEN}╔════════════════════════════════════════════════════════════╗${OFF}"
    echo -e "${B_GREEN}║${B_WHITE}                   NÄCHSTE SCHRITTE                         ${B_GREEN}║${OFF}"
    echo -e "${B_GREEN}╚════════════════════════════════════════════════════════════╝${OFF}"
    echo ""
    echo -e "  ${B_CYAN}📝 1.${OFF} Füge in ${B_WHITE}printer.cfg${OFF} ein:"
    echo -e "        ${CYAN}[include Auto_Offset/Auto_Offset_Variables.cfg]${OFF}"
    echo -e "        ${CYAN}[include Auto_Offset/Auto_Offset.cfg]${OFF}"
    echo ""
    echo -e "  ${B_CYAN}💾 2.${OFF} Falls noch nicht vorhanden:"
    echo -e "        ${CYAN}[save_variables]${OFF}"
    echo -e "        ${CYAN}filename: ~/printer_data/config/variables.cfg${OFF}"
    echo ""
    echo -e "  ${B_CYAN}⚙️  3.${OFF} Passe ${B_WHITE}Auto_Offset_Variables.cfg${OFF} an (in Mainsail/Fluidd)"
    echo ""
    echo -e "  ${B_CYAN}🚀 4.${OFF} Teste mit: ${B_GREEN}AUTO_OFFSET_START${OFF}"
    echo ""
}

#####################################################################
# HAUPTPROGRAMM
#####################################################################

main() {
    while true; do
        show_menu
        read -p "$(echo -e ${CYAN}Wähle eine Option \[1-5\]: ${OFF})" choice
        echo ""
        
        case $choice in
            1)
                do_install
                read -p "Drücke Enter zum Fortfahren..."
                ;;
            2)
                do_update
                read -p "Drücke Enter zum Fortfahren..."
                ;;
            3)
                do_uninstall
                read -p "Drücke Enter zum Fortfahren..."
                ;;
            4)
                show_status
                read -p "Drücke Enter zum Fortfahren..."
                ;;
            5)
                show_logo
                print_success "Auf Wiedersehen!"
                echo ""
                exit 0
                ;;
            *)
                print_error "Ungültige Auswahl!"
                sleep 1
                ;;
        esac
    done
}

# Script starten
# Prüfe ob stdin ein TTY ist (interaktive Shell)
if [ -t 0 ]; then
    # Interaktiv → Zeige Menü
    main
else
    # Nicht interaktiv (curl | bash) → Direkt installieren
    export NON_INTERACTIVE=1
    show_logo
    echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
    echo -e "${B_YELLOW}  AUTO-INSTALLATION (One-Liner)${OFF}"
    echo -e "${B_YELLOW}═══════════════════════════════════════════════════════${OFF}"
    echo ""
    print_info "Keine interaktive Shell erkannt - starte automatische Installation..."
    echo ""
    sleep 1
    do_install
fi
