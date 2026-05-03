import os
import sys
import time
import threading
import subprocess
import signal
from datetime import datetime
from gpiozero import Button
from PIL import Image, ImageDraw, ImageFont
from luma.core.interface.serial import spi
from luma.oled.device import sh1106

# =========================================================
# IMPORTACIONES DEL BACKEND (Se mantendrán intactas)
# =========================================================
# Se importarán en fases posteriores según corresponda:
# import ducky_logic
# from gadget_handler import BLEGadget

# =========================================================
# CONFIGURACIÓN DE HARDWARE
# =========================================================
PINS = {
    'up': 6, 'down': 19, 'left': 5, 'right': 26, 'center': 13,
    'key1': 21,  # ATRÁS / CANCELAR
    'key2': 20,  # RESERVADO / UTILIDADES
    'key3': 16   # EJECUTAR / CONFIRMAR
}

BASE_DIRS = {
    'nmap': 'Resultados_Nmap',
    'wifi': 'Resultados_Handshake',
    'evil': 'Resultados_EvilTwin',
    'ble': 'Resultados_BLE',
    'logs': 'Logs_Ejecucion'
}

for d in BASE_DIRS.values():
    os.makedirs(d, exist_ok=True)

# =========================================================
# CLASE: OledMenuEngine
# =========================================================
class OledMenuEngine:
    ITEMS_PER_PAGE = 5
    FONT_SIZE = 11
    HEADER_H = 14
    STATUS_H = 10

    def __init__(self):
        # 1. Pantalla SPI
        self.serial = spi(device=0, gpio_DC=25, gpio_RST=27, bus_speed_hz=8000000)
        self.device = sh1106(self.serial, rotate=2)
        self.image = Image.new('1', (self.device.width, self.device.height), 0)
        self.draw = ImageDraw.Draw(self.image)
        
        # Fuente monoespaciada
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", self.FONT_SIZE)
        except IOError:
            self.font = ImageFont.load_default()

        # 2. GPIO Buttons
        self.btn = {name: Button(pin) for name, pin in PINS.items()}
        self.btn['up'].when_pressed = self._nav_up
        self.btn['down'].when_pressed = self._nav_down
        self.btn['center'].when_pressed = self._select
        self.btn['key1'].when_pressed = self._go_back
        self.btn['key3'].when_pressed = self._confirm
        self.btn['left'].when_pressed = self._prev_page
        self.btn['right'].when_pressed = self._next_page

        # 3. Estado
        self.menu_stack = []
        self.sel_idx = 0
        self.page_off = 0
        self.is_busy = False
        self.status_text = "DRAGON FLY SYSTEM"
        self._lock = threading.Lock()
        self._running = True

        # Crear directorios base
        self._ui_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._ui_thread.start()

    # -------------------------------------------------------
    # INTERFAZ DE USUARIO & RENDERIZADO
    # -------------------------------------------------------
    def _render_loop(self):
        while self._running:
            with self._lock:
                self.draw.rectangle((0, 0, self.device.width, self.device.height), fill=0)
                
                # Header
                title = self.menu_stack[-1]['title'] if self.menu_stack else "DRAGON FLY"
                self.draw.rectangle((0, 0, self.device.width, self.HEADER_H), fill=1)
                self.draw.text((2, 0), f" {title} ", fill=0, font=self.font)

                # Menú actual
                items = self.menu_stack[-1]['items'] if self.menu_stack else []
                start = self.page_off
                visible = items[start:start + self.ITEMS_PER_PAGE]
                
                y = self.HEADER_H + 2
                for i, item in enumerate(visible):
                    real_idx = start + i
                    is_sel = (real_idx == self.sel_idx)
                    bg = 1 if is_sel else 0
                    fg = 0 if is_sel else 1
                    txt = f"{'>' if is_sel else ' '} {item['label'][:17]}"
                    self.draw.rectangle((1, y, self.device.width-1, y + self.FONT_SIZE), fill=bg)
                    self.draw.text((3, y), txt, fill=fg, font=self.font)
                    y += self.FONT_SIZE + 2

                # Indicador de paginación
                if len(items) > self.ITEMS_PER_PAGE:
                    pg = (self.sel_idx // self.ITEMS_PER_PAGE) + 1
                    total = (len(items) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE
                    self.draw.text((self.device.width-22, self.device.height-9), f"{pg}/{total}", fill=1, font=self.font)

                # Barra de estado
                self.draw.rectangle((0, self.device.height-self.STATUS_H, self.device.width, self.device.height), fill=1)
                self.draw.text((2, self.device.height-9), f" {self.status_text[:16]} ", fill=0, font=self.font)

                self.device.display(self.image)
            time.sleep(0.08)

    # -------------------------------------------------------
    # CONTROL DE NAVEGACIÓN
    # -------------------------------------------------------
    def _nav_up(self):
        if self.is_busy: return
        with self._lock:
            if self.sel_idx > 0:
                self.sel_idx -= 1
                if self.sel_idx < self.page_off:
                    self.page_off = self.sel_idx

    def _nav_down(self):
        if self.is_busy: return
        with self._lock:
            items = self.menu_stack[-1]['items'] if self.menu_stack else []
            if self.sel_idx < len(items) - 1:
                self.sel_idx += 1
                if self.sel_idx >= self.page_off + self.ITEMS_PER_PAGE:
                    self.page_off = self.sel_idx - self.ITEMS_PER_PAGE + 1

    def _prev_page(self):
        if self.is_busy or self.page_off == 0: return
        with self._lock:
            self.page_off = max(0, self.page_off - self.ITEMS_PER_PAGE)
            self.sel_idx = self.page_off

    def _next_page(self):
        if self.is_busy: return
        with self._lock:
            items = self.menu_stack[-1]['items'] if self.menu_stack else []
            max_pg = ((len(items)-1)//self.ITEMS_PER_PAGE)*self.ITEMS_PER_PAGE
            if self.page_off < max_pg:
                self.page_off += self.ITEMS_PER_PAGE
                self.sel_idx = min(self.page_off, len(items)-1)

    def _go_back(self):
        if self.is_busy: return
        with self._lock:
            if len(self.menu_stack) > 1:
                self.menu_stack.pop()
                self.sel_idx = 0
                self.page_off = 0
                self.status_text = "ATRAS"

    def _select(self):
        self._execute_selected()

    def _confirm(self):
        self._execute_selected()

    def _execute_selected(self):
        if self.is_busy or not self.menu_stack: return
        with self._lock:
            items = self.menu_stack[-1]['items']
            if self.sel_idx < len(items):
                item = items[self.sel_idx]
                if item.get('action'):
                    self._run_task(item)
                elif item.get('submenu'):
                    self.push_menu(item['submenu']['title'], item['submenu']['items'])
                    self.status_text = "ENTRANDO..."

    def _run_task(self, item):
        self.is_busy = True
        self.status_text = "EJECUTANDO..."
        threading.Thread(target=self._task_wrapper, args=(item,), daemon=True).start()

    def _task_wrapper(self, item):
        try:
            if item.get('requires_confirm'):
                # En fases avanzadas se puede añadir un estado de "CONFIRMAR CON KEY3"
                pass
            item['action']()
            self.status_text = "OK"
        except Exception as e:
            self.status_text = f"ERR: {str(e)[:10]}"
        finally:
            self.is_busy = False
            time.sleep(1.5)
            self.status_text = "LISTO"

    # -------------------------------------------------------
    # GESTIÓN DE MENÚS
    # -------------------------------------------------------
    def push_menu(self, title, items):
        with self._lock:
            self.menu_stack.append({'title': title, 'items': items})
            self.sel_idx = 0
            self.page_off = 0

    # -------------------------------------------------------
    # WRAPPER DE COMANDOS (REDIRECCIÓN A LOGS)
    # -------------------------------------------------------
    def run_offensive_cmd(self, cmd, session_dir, timeout=300):
        """Ejecuta comando en background, loggea stdout y actualiza OLED"""
        os.makedirs(session_dir, exist_ok=True)
        log_path = os.path.join(session_dir, f"cmd_{datetime.now().strftime('%H%M%S')}.log")
        self.status_text = "LOGGING..."
        
        with open(log_path, 'w') as log:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                log.write(line)
                log.flush()
                # Opcional: actualizar status con última línea corta
                if len(line) > 4:
                    with self._lock:
                        self.status_text = f"RUN: {line.strip()[:14]}"
            proc.wait(timeout=timeout)
        self.status_text = "FINALIZADO"
        return log_path

# =========================================================
# ESQUELETO PRINCIPAL (Menú Raíz)
# =========================================================
def build_main_menu(engine):
    # Placeholder para las funciones que se definirán en FASE 2, 3, 4
    def placeholder():
        engine.status_text = "PENDIENTE"

    root_items = [
        {'label': '0. Inicio', 'action': lambda: engine.push_menu('INICIO', [
            {'label': 'Ver Version', 'action': lambda: setattr(engine, 'status_text', 'v1.0.0')},
        ])},
        {'label': '1. Reconocimiento', 'submenu': {'title': 'NMAP', 'items': []}}, # FASE 2
        {'label': '2. MAC Changer', 'submenu': {'title': 'MAC', 'items': []}},     # FASE 2
        {'label': '3. Auditoria WiFi', 'submenu': {'title': 'WIFI', 'items': []}}, # FASE 3
        {'label': '4. Bluetooth BLE', 'submenu': {'title': 'BLE', 'items': []}},   # FASE 4
        {'label': '5. Rubber Ducky', 'submenu': {'title': 'DUCKY', 'items': []}},  # FASE 4
        {'label': '6. Utilidades OS', 'submenu': {'title': 'UTILS', 'items': []}},
        {'label': '7. Salir', 'action': lambda: sys.exit(0)}
    ]
    engine.push_menu('DRAGON FLY', root_items)

def main():
    print("[+] Inicializando Dragon Fly System (OLED Mode)...")
    engine = OledMenuEngine()
    try:
        build_main_menu(engine)
        # Mantener hilo principal activo
        while engine._running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[+] Apagando sistema...")
        engine._running = False
    finally:
        engine.device.cleanup()

if __name__ == '__main__':
    main()
