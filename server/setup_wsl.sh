#!/usr/bin/env bash
# =========================================================================
# Richtet die WSL2-VM "kam-server" als Docker-Host mit GPU ein (Phase 0).
# Doku: docs/server_einrichtung.md
#
# Aufruf aus Windows (PowerShell), einmalig als root:
#   wsl -d kam-server -u root -- bash /mnt/c/Projekte/KI-Agent/server/setup_wsl.sh <linux-benutzer>
#
# Ablauf:
#   1. Paketquellen von Docker und NVIDIA mit Signaturschlüssel eintragen
#   2. Docker Engine + Compose-Plugin + NVIDIA Container Toolkit installieren
#   3. Docker so konfigurieren, dass Container die GPU nutzen können
#   4. Linux-Benutzer in die Gruppe "docker" aufnehmen (Docker ohne sudo)
# Das Skript kann gefahrlos mehrfach laufen.
# =========================================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
BENUTZER="${1:-}"

echo "== 1. Paketquellen eintragen"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg >/dev/null
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list

echo "== 2. Docker Engine und NVIDIA Container Toolkit installieren"
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin nvidia-container-toolkit >/dev/null

echo "== 3. GPU-Laufzeit für Docker eintragen"
nvidia-ctk runtime configure --runtime=docker
systemctl enable --now docker >/dev/null
systemctl restart docker

if [ -n "$BENUTZER" ]; then
    echo "== 4. Benutzer $BENUTZER in Gruppe docker aufnehmen"
    usermod -aG docker "$BENUTZER"
fi

echo "== Fertig"
docker --version
docker compose version
nvidia-ctk --version | head -1
