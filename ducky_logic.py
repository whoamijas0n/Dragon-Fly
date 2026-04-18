import os, pyautogui, time

def ejecutar_script_ducky(ruta_archivo):
    try:
        with open(ruta_archivo, 'r') as f:
            lineas = f.readlines()
        
        print(f"\n[+] Iniciando payload: {os.path.basename(ruta_archivo)}")
        print("[!] Tienes 2 segundos para situar el cursor...")
        time.sleep(2)
        
        for linea in lineas:
            linea = linea.strip()
            if not linea or linea.startswith("REM"):
                continue
            
            # COMANDO STRING (Escribir texto)
            if linea.startswith("STRING "):
                texto = linea[7:]
                print(f"  [>] Escribiendo: {texto}")
                pyautogui.write(texto)
            
            # COMANDO DELAY (Esperar)
            elif linea.startswith("DELAY "):
                ms = int(linea[6:])
                print(f"  [~] Esperando {ms}ms...")
                time.sleep(ms / 1000)
            
            # TECLAS ESPECIALES
            elif linea in ["ENTER", "GUI", "WINDOWS", "TAB", "ESC", "ALT", "CONTROL", "SHIFT", "UP", "DOWN", "LEFT", "RIGHT"]:
                print(f"  [*] Pulsando tecla: {linea}")
                if linea == "GUI" or linea == "WINDOWS":
                    pyautogui.press('win')
                else:
                    pyautogui.press(linea.lower())
            
            # COMBINACIONES (Ejemplo: GUI r)
            elif " " in linea:
                partes = linea.split(" ")
                print(f"  [*] Combinación: {linea}")
                # Si es algo como "GUI r", pyautogui.hotkey('win', 'r')
                tecla1 = 'win' if partes[0] in ["GUI", "WINDOWS"] else partes[0].lower()
                pyautogui.hotkey(tecla1, partes[1].lower())

        print("[#] Payload finalizado con éxito.\n")
        
    except Exception as e:
        print(f"\n[!] ERROR: {e}")
        time.sleep(2)

def menu(Menu, AccionPython):
    menu_d = Menu("MIS PAYLOADS")
    folder = "payloads"
    if not os.path.exists(folder): os.makedirs(folder)
    archivos = [f for f in os.listdir(folder) if f.endswith(".txt")]
    for archivo in archivos:
        ruta = os.path.join(folder, archivo)
        # Aquí quitamos el "Lanzar" para que solo se vea el nombre
        menu_d.agregar_opcion(f"{archivo}", AccionPython(f"Ejecutando...", ejecutar_script_ducky, ruta))
    return menu_d