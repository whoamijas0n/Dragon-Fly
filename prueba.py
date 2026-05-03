import os
import time
import subprocess
import threading
import glob
import re
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, RichLog, Label, Select, Checkbox
from textual.screen import ModalScreen
from textual import on

# Importar los scripts proporcionados sin cambios
import ducky_logic
from gadget_handler import BLEGadget

# Directorios base para resultados
BASE_DIR_NMAP = "Resultados_Nmap"
BASE_DIR_WIFI = "Resultados_Handshake"
BASE_DIR_EVIL = "Resultados_EvilTwin"
BASE_DIR_BLE = "Resultados_BLE"

class CmdButton(Button):
    """Botón personalizado que acepta un callback (command) simulando Tkinter."""
    def __init__(self, label, command=None, *args, **kwargs):
        super().__init__(label, *args, **kwargs)
        self.command = command

class ListSelectModal(ModalScreen):
    """Pantalla modal táctil para evitar escribir texto. Muestra una lista de opciones."""
    def __init__(self, title, options, callback):
        super().__init__()
        self.modal_title = title
        self.options = options
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-container"):
            yield Label(self.modal_title, classes="modal-title")
            with VerticalScroll():
                for opt in self.options:
                    # Las opciones pueden ser tuplas (Label, Valor) o un string plano
                    val = opt[1] if isinstance(opt, tuple) else opt
                    lbl = opt[0] if isinstance(opt, tuple) else str(opt)
                    yield CmdButton(lbl, command=lambda v=val: self.select_option(v), classes="red-btn")
            yield CmdButton("Cancelar", command=self.app.pop_screen, classes="back-btn")
            
    def select_option(self, value):
        self.app.pop_screen()
        self.callback(value)

class RedTeamApp(App):
    CSS_PATH = "app.tcss"

    def __init__(self):
        super().__init__()
        self.target_ip = "127.0.0.1"
        self.usar_rango = False
        self.rango_cidr = "/24"
        self.session_dir_nmap = ""
        
        self.wifi_state = {}
        self.ble_state = {}
        
        self.evil_twin_procs = {
            'hostapd': None,
            'dnsmasq': None,
            'capture': None,
            'deauth': None
        }
        self.evil_twin_stop = False

        for d in [BASE_DIR_NMAP, BASE_DIR_WIFI, BASE_DIR_EVIL, BASE_DIR_BLE]:
            os.makedirs(d, exist_ok=True)

        try:
            self.gadget = BLEGadget()
            self.gadget_available = self.gadget.is_available()
        except Exception:
            self.gadget = None
            self.gadget_available = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Barra lateral siempre visible
            with VerticalScroll(id="sidebar"):
                yield Label("DRAGON FLY", classes="title sidebar-title")
                yield CmdButton("0. Inicio", command=self.show_inicio_menu, classes="menu-btn")
                yield CmdButton("1. Nmap Recon", command=self.show_recon_menu, classes="menu-btn")
                yield CmdButton("2. MAC Changer", command=self.show_mac_menu, classes="menu-btn")
                yield CmdButton("3. WiFi Audit", command=self.show_wifi_menu, classes="menu-btn")
                yield CmdButton("4. Bluetooth", command=self.show_bluetooth_menu, classes="menu-btn")
                yield CmdButton("5. Ducky USB", command=self.show_ducky_menu, classes="menu-btn")
                yield CmdButton("6. Sistema", command=self.show_utils_menu, classes="menu-btn")
                
            # Área principal y consola
            with Vertical(id="main_panel"):
                yield VerticalScroll(id="view_content")
                yield RichLog(id="console", auto_scroll=True, markup=True)

    def on_mount(self) -> None:
        if self.gadget_available:
            self.write_console("[+] Gadget ESP32 BLE conectado correctamente.")
        else:
            self.write_console("[!] Gadget ESP32 BLE no detectado.")
        self.show_inicio_menu()

    @on(Button.Pressed)
    def handle_button_pressed(self, event: Button.Pressed) -> None:
        """Rutea el evento click al callback asignado en CmdButton."""
        if isinstance(event.button, CmdButton) and event.button.command:
            event.button.command()

    def write_console(self, text):
        """Escribe en consola de forma segura resolviendo si estamos en hilo principal o secundario"""
        if self._thread_id != threading.get_ident():
            self.call_from_thread(self.write_console, text)
            return
            
        log = self.query_one("#console", RichLog)
        log.write(text)

    def ejecutar_comando(self, comando, callback_after=None, use_shell=True):
        cmd_str = comando if isinstance(comando, str) else ' '.join(comando)
        self.write_console(f"\n[bold red]root@kali:~#[/] {cmd_str}")

        def run():
            try:
                proc = subprocess.Popen(comando, shell=use_shell, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout:
                    self.write_console(line.rstrip())
                proc.wait()
                self.write_console("\n[+] Tarea finalizada.")
                
                if callback_after:
                    if self._thread_id != threading.get_ident():
                        self.call_from_thread(callback_after)
                    else:
                        callback_after()
            except Exception as e:
                self.write_console(f"\n[!] ERROR: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _generar_nombre_temporal(self, prefijo):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"/tmp/{prefijo}_{timestamp}"

    def obtener_interfaces_red(self):
        try:
            return sorted([i for i in os.listdir('/sys/class/net/') if i != "lo"])
        except Exception:
            return ["wlan0", "eth0"]

    # ==========================================
    # GESTOR DE NAVEGACIÓN Y VISTAS TREAD-SAFE
    # ==========================================
    def render_view(self, render_func, *args, back_func=None):
        """Monta la vista asegurando compatibilidad con múltiples hilos."""
        if self._thread_id != threading.get_ident():
            self.call_from_thread(self.render_view, render_func, *args, back_func=back_func)
            return

        content = self.query_one("#view_content")
        for child in content.children:
            child.remove()
        
        if back_func:
            content.mount(CmdButton("← Atrás", command=back_func, classes="back-btn"))
            
        for widget in render_func(*args):
            content.mount(widget)

    # ==========================================
    # 0. INICIO
    # ==========================================
    def show_inicio_menu(self):
        def ui():
            # Raw string (r"") para evitar el error SyntaxWarning de secuencias de escape
            ascii_art = r"""
   __   ___  ___  ___  ___  _  __    ____ __ __  __
  /  \ | _ \/   \/ __|/ _ \| \| |   | __ |  \  \/  /
 | () || v /| - | (_ | (_) | \  |   | _| | - |\   / 
  \__/ |_|_\|_|_|\___|\___/|_|\_|   |_|  |__|  |_|  
            """
            yield Label("BIENVENIDO A DRAGON FLY", classes="title")
            yield Static(ascii_art, classes="ascii-art")
            yield Label("Red Team Toolbox TUI", classes="subtitle")
        self.render_view(ui)

    # ==========================================
    # 1. RECONOCIMIENTO (NMAP)
    # ==========================================
    def show_recon_menu(self):
        self.session_dir_nmap = ""
        def ui():
            yield Label("RECONOCIMIENTO NMAP", classes="title")
            
            ips = ["127.0.0.1", "192.168.1.1", "192.168.0.1", "10.0.0.1", "10.10.10.1"]
            sel_ip = Select([(ip, ip) for ip in ips], value=self.target_ip)
            yield Horizontal(Label("Target IP: "), sel_ip, classes="config-row")
            
            chk_rango = Checkbox("Usar rango CIDR", value=self.usar_rango)
            sel_cidr = Select([(c, c) for c in ["/24", "/16", "/8", "/32"]], value=self.rango_cidr)
            yield Horizontal(chk_rango, sel_cidr, classes="config-row")

            def update_target():
                self.target_ip = sel_ip.value
                self.usar_rango = chk_rango.value
                self.rango_cidr = sel_cidr.value
                self.write_console(f"[*] Target fijado: {self.target_ip}{self.rango_cidr if self.usar_rango else ''}")
            
            yield CmdButton("Validar Target", command=update_target, classes="red-btn")

            comandos_nmap = [
                ("0. Descubrimiento hosts", "-sn {TARGET} -oN {SESSION}/00_hosts.txt"),
                ("1. Puertos comunes", "-sS -T3 --top-ports 1000 {TARGET} -oN {SESSION}/01_common.txt"),
                ("2. Full TCP", "-sS -p- -T3 {TARGET} -oN {SESSION}/02_full.txt"),
                ("3. Servicios/Versiones", "-sV -T3 {TARGET} -oN {SESSION}/03_svcs.txt")
            ]
            for nombre, cmd in comandos_nmap:
                yield CmdButton(nombre, command=lambda c=cmd: self._ejecutar_nmap(c), classes="red-btn")
            
            yield CmdButton("Explorar Guardados", command=self._mostrar_explorador_nmap, classes="back-btn")
        self.render_view(ui)

    def _ejecutar_nmap(self, cmd_template):
        target = f"{self.target_ip}{self.rango_cidr if self.usar_rango else ''}"
        if not self.session_dir_nmap:
            ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            self.session_dir_nmap = os.path.join(BASE_DIR_NMAP, f"Auditoria-{ts}")
        os.makedirs(self.session_dir_nmap, exist_ok=True)
        comando = cmd_template.replace("{TARGET}", target).replace("{SESSION}", self.session_dir_nmap)
        self.ejecutar_comando(f"nmap {comando}")

    def _mostrar_explorador_nmap(self):
        def ui():
            yield Label("AUDITORÍAS NMAP", classes="title")
            carpetas = sorted([d for d in os.listdir(BASE_DIR_NMAP) if os.path.isdir(os.path.join(BASE_DIR_NMAP, d))], reverse=True)
            if not carpetas:
                yield Label("No hay auditorías guardadas.")
                return
            for carpeta in carpetas:
                ruta = os.path.join(BASE_DIR_NMAP, carpeta)
                yield CmdButton(carpeta, command=lambda r=ruta: self._mostrar_archivos_nmap(r), classes="red-btn")
        self.render_view(ui, back_func=self.show_recon_menu)

    def _mostrar_archivos_nmap(self, ruta):
        def ui():
            yield Label(f"ARCHIVOS EN {os.path.basename(ruta)}", classes="title")
            archivos = sorted([f for f in os.listdir(ruta) if os.path.isfile(os.path.join(ruta, f))])
            if not archivos:
                yield Label("Carpeta vacía")
                return
            for archivo in archivos:
                ruta_arch = os.path.join(ruta, archivo)
                yield CmdButton(archivo, command=lambda ra=ruta_arch: self.ejecutar_comando(f"cat '{ra}'"), classes="red-btn")
        self.render_view(ui, back_func=self._mostrar_explorador_nmap)

    # ==========================================
    # 2. MAC CHANGER
    # ==========================================
    def show_mac_menu(self):
        def ui():
            yield Label("DIRECCION MAC", classes="title")
            interfaces = self.obtener_interfaces_red()
            if not interfaces:
                yield Label("No se detectaron interfaces.")
                return
            sel_iface = Select([(i, i) for i in interfaces], value=interfaces[0])
            yield Horizontal(Label("Interfaz: "), sel_iface, classes="config-row")
            
            yield CmdButton("Ver Estado", command=lambda: self.ejecutar_comando(f"sudo macchanger -s {sel_iface.value}"), classes="red-btn")
            yield CmdButton("MAC Random", command=lambda: self.ejecutar_comando(f"sudo ifconfig {sel_iface.value} down && sudo macchanger -r {sel_iface.value} && sudo ifconfig {sel_iface.value} up"), classes="red-btn")
            yield CmdButton("Reset Original", command=lambda: self.ejecutar_comando(f"sudo ifconfig {sel_iface.value} down && sudo macchanger -p {sel_iface.value} && sudo ifconfig {sel_iface.value} up"), classes="red-btn")
            yield CmdButton("MAC Mismo Fabricante", command=lambda: self.ejecutar_comando(f"sudo ifconfig {sel_iface.value} down && sudo macchanger -a {sel_iface.value} && sudo ifconfig {sel_iface.value} up"), classes="red-btn")
        self.render_view(ui)

    # ==========================================
    # 3. WIFI AUDIT
    # ==========================================
    def show_wifi_menu(self):
        def ui():
            yield Label("AUDITORÍA WIFI", classes="title")
            yield CmdButton("Activar Modo Monitor", command=self._wifi_modo_monitor, classes="red-btn")
            yield CmdButton("Captura de Handshake", command=self._wifi_captura_handshake, classes="red-btn")
            yield CmdButton("Ataque Evil Twin", command=self._wifi_evil_twin, classes="red-btn")
            yield CmdButton("Desautenticación", command=self._wifi_deauth, classes="red-btn")
            yield CmdButton("Explorar Handshakes", command=self._wifi_explorar_handshakes, classes="back-btn")
            yield CmdButton("Explorar Evil Twin", command=self._wifi_explorar_evil, classes="back-btn")
        self.render_view(ui)

    def _wifi_modo_monitor(self):
        def ui():
            yield Label("MODO MONITOR", classes="title")
            interfaces = self.obtener_interfaces_red()
            for iface in interfaces:
                yield CmdButton(f"Monitor en {iface}", command=lambda i=iface: self.ejecutar_comando(
                    f"sudo airmon-ng check kill && sudo airmon-ng start {i}",
                    callback_after=lambda: self.write_console("[+] Monitor activado.")), classes="red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _wifi_captura_handshake(self):
        def ui():
            yield Label("SELECCIONA INTERFAZ", classes="title")
            for iface in self.obtener_interfaces_red():
                yield CmdButton(iface, command=lambda i=iface: self._wifi_escanear_redes_handshake(i), classes="red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _wifi_escanear_redes_handshake(self, iface):
        self.wifi_state = {"iface": iface}
        os.system(f"sudo airmon-ng start {iface} >/dev/null 2>&1")
        mon = f"{iface}mon" if os.path.exists(f"/sys/class/net/{iface}mon") else iface
        self.wifi_state["mon_iface"] = mon
        self.write_console(f"[*] Escaneando redes con {mon}...")
        
        scan_prefix = self._generar_nombre_temporal("wifi_hs")
        def escanear():
            os.system(f"sudo timeout 15s airodump-ng {mon} -w {scan_prefix} --output-format csv >/dev/null 2>&1")
            redes = []
            try:
                with open(f"{scan_prefix}-01.csv", "r", errors="ignore") as f:
                    for linea in f.read().split("Station MAC,")[0].split("\n")[2:]:
                        r = linea.split(",")
                        if len(r) >= 14 and ":" in r[0]:
                            redes.append({"bssid": r[0].strip(), "ch": r[3].strip(), "essid": r[13].strip() or "Oculta"})
            except: pass
            self._wifi_mostrar_redes_handshake(redes)
        threading.Thread(target=escanear, daemon=True).start()

    def _wifi_mostrar_redes_handshake(self, redes):
        def ui():
            yield Label("SELECCIONA RED OBJETIVO", classes="title")
            for red in redes:
                lbl = f"{red['essid']} (CH:{red['ch']})"
                yield CmdButton(lbl, command=lambda r=red: self._wifi_seleccionar_cliente_handshake(r), classes="red-btn")
        self.render_view(ui, back_func=self._wifi_captura_handshake)

    def _wifi_seleccionar_cliente_handshake(self, red):
        self.wifi_state["target"] = red
        mon = self.wifi_state["mon_iface"]
        scan_prefix = self._generar_nombre_temporal("wifi_clients")
        os.system(f"sudo timeout 10s airodump-ng --bssid {red['bssid']} -c {red['ch']} {mon} -w {scan_prefix} --output-format csv >/dev/null 2>&1")
        clientes = ["FF:FF:FF:FF:FF:FF"] # Broadcast incluido por defecto
        try:
            with open(f"{scan_prefix}-01.csv", "r", errors="ignore") as f:
                partes = f.read().split("Station MAC,")
                if len(partes) > 1:
                    for linea in partes[1].split("\n")[1:]:
                        c = linea.split(",")
                        if len(c) >= 6 and ":" in c[0]: clientes.append(c[0].strip())
        except: pass
        
        def ui():
            yield Label(f"CLIENTES EN {red['essid']}", classes="title")
            for mac in clientes:
                yield CmdButton(mac + (" (Broadcast)" if mac.startswith("FF") else ""), 
                                command=lambda m=mac: self._wifi_iniciar_ataque_handshake(m),
                                classes="danger-btn" if mac.startswith("FF") else "red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _wifi_iniciar_ataque_handshake(self, cliente_mac):
        red = self.wifi_state["target"]
        mon = self.wifi_state["mon_iface"]
        session_dir = os.path.join(BASE_DIR_WIFI, f"Auditoria-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}")
        os.makedirs(session_dir, exist_ok=True)
        os.system(f"sudo airodump-ng --channel {red['ch']} --bssid {red['bssid']} -w {session_dir}/Captura {mon} >/dev/null 2>&1 &")
        time.sleep(2)
        self.ejecutar_comando(f"sudo aireplay-ng -0 10 -a {red['bssid']} -c {cliente_mac} {mon}")
        self.write_console("[*] Ataque lanzado. Handshake debería guardarse en Resultados_Handshake.")

    def _wifi_evil_twin(self):
        def ui():
            yield Label("EVIL TWIN - INTERFAZ AP", classes="title")
            for iface in self.obtener_interfaces_red():
                yield CmdButton(f"AP: {iface}", command=lambda i=iface: self._evil_twin_select_deauth(i), classes="red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _evil_twin_select_deauth(self, ap_iface):
        self.wifi_state["ap_iface"] = ap_iface
        def ui():
            yield Label("EVIL TWIN - INTERFAZ DEAUTH", classes="title")
            for iface in [i for i in self.obtener_interfaces_red() if i != ap_iface]:
                yield CmdButton(f"Deauth: {iface}", command=lambda i=iface: self._evil_twin_escanear_redes(i), classes="red-btn")
        self.render_view(ui, back_func=self._wifi_evil_twin)

    def _evil_twin_escanear_redes(self, deauth_iface):
        self.wifi_state["deauth_iface"] = deauth_iface
        self.write_console(f"[*] Preparando {deauth_iface} para escanear y atacar...")
        os.system(f"sudo airmon-ng start {deauth_iface} >/dev/null 2>&1")
        mon = f"{deauth_iface}mon" if os.path.exists(f"/sys/class/net/{deauth_iface}mon") else deauth_iface
        self.wifi_state["mon_deauth"] = mon

        scan_prefix = self._generar_nombre_temporal("evil_scan")
        def escanear():
            os.system(f"sudo timeout 15s airodump-ng {mon} -w {scan_prefix} --output-format csv >/dev/null 2>&1")
            redes = []
            try:
                with open(f"{scan_prefix}-01.csv", "r", errors="ignore") as f:
                    for linea in f.read().split("Station MAC,")[0].split("\n")[2:]:
                        r = linea.split(",")
                        if len(r) >= 14 and ":" in r[0]:
                            redes.append({"bssid": r[0].strip(), "ch": r[3].strip(), "essid": r[13].strip()})
            except: pass
            self._evil_twin_mostrar_redes(redes)
        threading.Thread(target=escanear, daemon=True).start()

    def _evil_twin_mostrar_redes(self, redes):
        def ui():
            yield Label("RED OBJETIVO PARA CLONAR", classes="title")
            for red in redes:
                yield CmdButton(f"{red['essid']} (CH:{red['ch']})", command=lambda r=red: self._evil_twin_seleccionar_portal(r), classes="red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _evil_twin_seleccionar_portal(self, red):
        def ui():
            yield Label("PORTAL CAUTIVO", classes="title")
            portals_dir = os.path.join(os.path.dirname(__file__), "evil_portals")
            os.makedirs(portals_dir, exist_ok=True)
            for portal in sorted([d for d in os.listdir(portals_dir) if os.path.isdir(os.path.join(portals_dir, d))]):
                yield CmdButton(portal, command=lambda p=portal: self._evil_twin_ejecutar(red, p, "broadcast"), classes="red-btn")
        self.render_view(ui, back_func=self.show_wifi_menu)

    def _evil_twin_ejecutar(self, red, portal, deauth_mode, cliente_mac=None):
        self.evil_twin_stop = False
        def ui():
            yield Label("EVIL TWIN ACTIVO", classes="title")
            yield Label(f"Target: {red['essid']} | Portal: {portal}")
            yield CmdButton("DETENER ATAQUE", command=self._evil_twin_detener, classes="danger-btn")
        self.render_view(ui)

        def ataque():
            ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            session_dir = os.path.join(BASE_DIR_EVIL, f"Auditoria-{ts}")
            os.makedirs(session_dir, exist_ok=True)
            tmp_web = f"/tmp/evil_twin_web_{ts}"
            os.makedirs(tmp_web, exist_ok=True)
            os.system(f"cp -r evil_portals/{portal}/* {tmp_web}/ 2>/dev/null")
            
            cred_log = os.path.join(session_dir, "credentials.log")
            self.write_console(f"[*] Ataque Evil Twin ejecutándose...")
            while not self.evil_twin_stop:
                time.sleep(2)
                if os.path.exists(cred_log):
                    self.write_console("[+] Credencial Capturada en LOG!")
            
            self.write_console("[*] Deteniendo Evil Twin (Limpieza iptables...)")
            os.system("sudo pkill -f 'hostapd.*evil' 2>/dev/null")
            os.system("sudo pkill -f 'dnsmasq.*evil' 2>/dev/null")
            os.system("sudo iptables --flush")
            os.system("sudo iptables --table nat --flush")
        threading.Thread(target=ataque, daemon=True).start()

    def _evil_twin_detener(self):
        self.evil_twin_stop = True

    def _wifi_deauth(self): pass 
    def _wifi_explorar_handshakes(self): self._mostrar_explorador_nmap() 
    def _wifi_explorar_evil(self): self._mostrar_explorador_nmap()

    # ==========================================
    # 4. BLUETOOTH
    # ==========================================
    def show_bluetooth_menu(self):
        def ui():
            yield Label("BLUETOOTH / BLE", classes="title")
            estado = "Conectado" if self.gadget_available else "Desconectado"
            color = "green" if self.gadget_available else "red"
            
            yield Label(f"Gadget ESP32: [{color}]{estado}[/]", classes="status-label")

            if self.gadget_available:
                yield CmdButton("Escanear BLE (HSPI)", command=lambda: self._ble_scan_gadget(0), classes="red-btn")
                yield CmdButton("Bluejacking (Mensaje)", command=self._gui_bluejacking, classes="red-btn")
                yield CmdButton("Beacon Flooding", command=self._gui_beacon_flood, classes="red-btn")
                yield CmdButton("Jammer Bluetooth", command=self._gui_jammer, classes="red-btn")
                yield CmdButton("Barrido Jammer", command=self._gui_sweep_jammer, classes="red-btn")
                yield CmdButton("Detener Todo", command=lambda: self.gadget.stop(0), classes="danger-btn")
            else:
                yield CmdButton("Escanear BLE (Legacy)", command=self._ble_escanear_legacy, classes="red-btn")
        self.render_view(ui)

    def _gui_bluejacking(self):
        opts = ["Hacked by Dragon Fly", "Red Team Assessment", "Update your BT", "Error 404"]
        def on_select(msg):
            self.gadget.advertise(0, msg)
            self.write_console(f"[*] Enviando publicidad BLE: {msg}")
        self.app.push_screen(ListSelectModal("Mensaje Bluejacking", opts, on_select))

    def _gui_beacon_flood(self):
        opts = [(f"{x} Beacons", x) for x in [10, 50, 100, 500]]
        def on_select(count):
            self.gadget.beacon_flood(0, count, 200)
            self.write_console(f"[*] Flood de {count} beacons activo.")
        self.app.push_screen(ListSelectModal("Cantidad de Beacons", opts, on_select))

    def _gui_jammer(self):
        opts = [(f"Canal {i}", i) for i in [1, 6, 11, 37, 38, 39]]
        def on_select(ch):
            self.gadget.jam(0, ch, 60)
            self.write_console(f"[*] Jammer activo en canal {ch} por 60s")
        self.app.push_screen(ListSelectModal("Canal Jammer", opts, on_select))

    def _gui_sweep_jammer(self):
        opts = [(f"{x} Segundos", x) for x in [10, 30, 60, 120]]
        def on_select(dur):
            self.gadget.sweep_jam(0, dur)
            self.write_console(f"[*] Sweep Jammer activo por {dur}s")
        self.app.push_screen(ListSelectModal("Duración Sweep", opts, on_select))

    def _ble_scan_gadget(self, module):
        self.write_console("[*] Escaneando BLE mediante ESP32 (10s)...")
        def cb(devices):
            def ui():
                yield Label("DISPOSITIVOS BLE (Gadget)", classes="title")
                for d in devices:
                    yield CmdButton(f"{d['name']} ({d['mac']})", classes="red-btn")
            self.render_view(ui, back_func=self.show_bluetooth_menu)
        self.gadget.scan(module, 10, cb)

    def _ble_escanear_legacy(self):
        self.write_console("[*] Escaneando BLE Legacy (bluetoothctl)...")
        pass

    # ==========================================
    # 5. RUBBER DUCKY
    # ==========================================
    def show_ducky_menu(self):
        def ui():
            yield Label("PAYLOADS DUCKY", classes="title")
            os.makedirs("payloads", exist_ok=True)
            archivos = [f for f in os.listdir("payloads") if f.endswith(".txt")]
            if not archivos:
                yield Label("No hay scripts .txt en payloads/")
                return
            for arch in archivos:
                ruta = os.path.join("payloads", arch)
                yield CmdButton(arch, command=lambda r=ruta: self._ejecutar_ducky(r), classes="red-btn")
        self.render_view(ui)

    def _ejecutar_ducky(self, ruta):
        self.write_console(f"[!] Ejecutando {os.path.basename(ruta)}. Tienes 2 segundos...")
        def run():
            time.sleep(2)
            try:
                ducky_logic.ejecutar_script_ducky(ruta)
                self.write_console("[+] Payload finalizado.")
            except Exception as e:
                self.write_console(f"[!] Error: {e}")
        threading.Thread(target=run, daemon=True).start()

    # ==========================================
    # 6. UTILIDADES SISTEMA
    # ==========================================
    def show_utils_menu(self):
        def ui():
            yield Label("SISTEMA", classes="title")
            yield CmdButton("Conectar WiFi", command=self._utils_wifi_seleccionar, classes="red-btn")
            yield CmdButton("Monitoreo (df, free)", command=lambda: self.ejecutar_comando("df -h && free -h"), classes="red-btn")
            yield CmdButton("Top Procesos", command=lambda: self.ejecutar_comando("ps aux --sort=-%cpu | head -6"), classes="red-btn")
            yield CmdButton("REINICIAR PI", command=lambda: os.system("reboot"), classes="danger-btn")
            yield CmdButton("APAGAR PI", command=lambda: os.system("shutdown -h now"), classes="danger-btn")
            yield CmdButton("SALIR (TUI)", command=self.exit, classes="back-btn")
        self.render_view(ui)

    def _utils_wifi_seleccionar(self):
        def ui():
            yield Label("CONECTAR WIFI", classes="title")
            yield CmdButton("Escaneo en progreso (Mock)...", classes="red-btn")
        self.render_view(ui, back_func=self.show_utils_menu)

if __name__ == "__main__":
    app = RedTeamApp()
    app.run()
