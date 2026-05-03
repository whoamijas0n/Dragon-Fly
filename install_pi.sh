#!/bin/bash
set -e
echo "[*] Instalando dependencias base..."
sudo apt update && sudo apt install -y python3-tk python3-venv python3-pip nmap aircrack-ng hostapd dnsmasq iw nmcli macchanger xinit matchbox-keyboard

echo "[*] Creando entorno virtual..."
python3 -m venv /opt/dragonfly_venv
source /opt/dragonfly_venv/bin/activate
pip install -r requirements.txt

echo "[*] Configurando permisos de log..."
sudo touch /var/log/dragonfly.log
sudo chown $USER:$USER /var/log/dragonfly.log
sudo chmod 664 /var/log/dragonfly.log

echo "[*] Creando directorios de trabajo..."
mkdir -p ~/Resultados_{Nmap,Handshake,EvilTwin,BLE} payloads evil_portals

echo "[*] Script listo. Para iniciar en kiosk desde CLI:"
echo "    xinit -- :0 vt7 &"
echo "    /opt/dragonfly_venv/bin/python main.py"
echo "[✅] Instalación completada."
