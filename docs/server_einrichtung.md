# Server-Einrichtung: Agent und Sprachmodell in einer virtuellen Umgebung

Protokoll der Einrichtung mit allen Entscheidungen, Problemen und Lösungen. Grundlage für die Projektdokumentation.
Branch: `max/server`. Beginn: 02.11.2026.

## Ziel
Der Agent (Streamlit-App) und das Sprachmodell (Ollama) laufen nicht mehr direkt unter Windows, sondern in einer
virtuellen Umgebung, die wie ein Server wirkt. Nutzer laden eine kleine App herunter und erreichen den Server
auch von außerhalb des Heimnetzes. Zweck ist die Vorführung in der Abgabe (Client-Server-Architektur).

```
App (.exe, pywebview) ──HTTPS──► agent.<domain>
                                   │  Cloudflare Access: Einmalcode per Mail
                                   ▼
                       Cloudflare Tunnel (nur ausgehende Verbindung)
                                   ▼
  WSL2 / Ubuntu ── Docker ─────────────────────────────────────────
     cloudflared  ──►  agent (Streamlit, app.py)  ──►  ollama (GPU)
```

## Phasen
| Phase | Inhalt | Stand |
|---|---|---|
| 0 | WSL2, Ubuntu, Docker Engine, NVIDIA Container Toolkit, GPU-Test | erledigt 02.11.2026 |
| 1 | Container für Ollama und Agent (docker compose) | offen |
| 2 | Cloudflare Tunnel und Domain | offen |
| 3 | Anmeldung über Cloudflare Access | offen |
| 4 | Client-App (pywebview als .exe) | offen |
| 5 | Demo-Betrieb: Start per Doppelklick, Statusprüfung | offen |
| 6 | Testlauf und Dokumentation | offen |

## Ausgangslage (geprüft 02.11.2026)
| Komponente | Wert | Bedeutung für den Server |
|---|---|---|
| Betriebssystem | Windows 11 Home, Build 26200 | kein Hyper-V-Manager, WSL2 ist möglich |
| CPU | AMD Ryzen 5 3600, 6 Kerne / 12 Threads, Virtualisierung aktiv | reicht für VM und Container |
| RAM | 16 GB | muss zwischen Windows und VM aufgeteilt werden |
| GPU | NVIDIA RTX 2070 Super, 8 GB, Treiber 610.47 | wird an WSL2 durchgereicht |
| Laufwerk C: | NVMe-SSD, 18 GB frei | zu wenig Platz für VM und Modelle |
| Laufwerk D: | HDD (Hitachi, mechanisch), 58 GB frei | zu langsam für Modelle |
| Laufwerk H: | SATA-SSD (Kingston), 650 GB frei | Speicherort der VM |
| Ollama | unter Windows installiert, startet automatisch, Modelle 14 GB | darf nicht parallel zum Server-Ollama laufen |
| WSL / Docker | nicht installiert | – |

## Entscheidungen
| Nr. | Entscheidung | Alternativen | Begründung |
|---|---|---|---|
| E1 | **WSL2** als virtuelle Umgebung | Hyper-V-VM, VirtualBox | Hyper-V fehlt bei Windows Home. VirtualBox kann die GPU nicht durchreichen, das 7B-Modell liefe auf der CPU (Minuten statt Sekunden pro Antwort). WSL2 ist eine echte Linux-VM und reicht die GPU über den Windows-Treiber durch. |
| E2 | **Docker-Container** in WSL2 | Dienste direkt in Ubuntu (systemd) | Näher an einem echten Server-Deployment: Ollama und Agent sind getrennt, die Umgebung ist als Datei (`docker-compose.yml`) beschrieben und auf jedem Rechner reproduzierbar. |
| E3 | **Docker Engine** direkt in Ubuntu | Docker Desktop | Docker Desktop ist ein zusätzliches Windows-Programm mit eigener VM und Lizenzbedingungen. Die Engine in WSL ist schlanker und entspricht einem Linux-Server. |
| E4 | **Weg A: Web-Oberfläche** bleibt Streamlit, die App ist ein Programmfenster (pywebview) | eigene HTTP-API + eigener Client | Kaum neuer Code, keine Absprache für ein neues Framework nötig. Für die Demo ausreichend. |
| E5 | **Cloudflare Tunnel** für den Zugriff von außen | Portfreigabe am Router, Tailscale | Keine offenen Ports, private IP bleibt verborgen, HTTPS automatisch. Tailscale müsste jeder Nutzer selbst installieren. |
| E6 | **Cloudflare Access** mit Einmalcode per Mail | Microsoft-Anmeldung (`st.login`), gemeinsames Passwort | Kein Code im Projekt, Freigabeliste von Mail-Adressen, kostenlos bis 50 Nutzer. Ein öffentlicher Server ohne Anmeldung wäre für jeden nutzbar. |
| E7 | **Nur Demo-Daten** auf dem öffentlich erreichbaren Server | echte Daten | Echte Kundendaten auf einem privaten, aus dem Internet erreichbaren PC bräuchten eine Freigabe der Firma. |
| E8 | **VM auf Laufwerk H:** (SATA-SSD) | C: (NVMe), D: | Geplant war D:, die Prüfung zeigte aber eine mechanische Festplatte. Ollama lädt beim Start ~5 GB Modell, auf einer HDD dauert das ein Vielfaches. C: hat nur 18 GB frei. |
| E9 | **Ubuntu 24.04 LTS** | Ubuntu 26.04 LTS, Debian | Für 24.04 sind Docker und das NVIDIA Container Toolkit am längsten erprobt und am besten dokumentiert. Support bis 2029, für das Projekt ausreichend. Ein Server soll stabil sein, nicht neu. |

## Phase 0: Grundlage

### Schritte
1. **Branch** `max/server` angelegt (Projektregel: nicht auf `main` arbeiten).
2. **Ressourcen der VM begrenzt** in `%USERPROFILE%\.wslconfig` (gilt für alle WSL-Distributionen):

   | Einstellung | Wert | Grund |
   |---|---|---|
   | `memory` | 10GB | Ohne Grenze nimmt WSL bis zu 50 % des RAM und gibt ihn nur langsam zurück. Bekanntes Risiko: Mit dem 14B-Gutachter (≈ 9 GB, passt nicht ganz in 8 GB VRAM) wird es knapp, siehe Absturz im Testlauf (architektur_uebersicht, „Agent und Gutachter gleichzeitig“). |
   | `processors` | 8 | 4 Threads bleiben für Windows |
   | `swap`, `swapFile` | 8GB auf H: | Auslagerung auf die SSD statt auf das volle C: |
   | `autoMemoryReclaim` | gradual | ungenutzter Speicher geht schrittweise an Windows zurück |
   | `sparseVhd` | true | virtuelle Festplatte schrumpft wieder, wenn Daten gelöscht werden |

3. **WSL installieren** (PowerShell als Administrator, danach Neustart):
   `wsl --install --no-distribution`. Ohne `--no-distribution` würde Ubuntu sofort auf C: installiert.
   Ergebnis: WSL 3.0.3, Kernel 6.18, Standardversion 2. Der Hinweis „WSL1 wird nicht unterstützt“ ist
   unkritisch, der Server nutzt nur WSL2.
4. **Ubuntu auf H: installiert** (ohne Admin-Rechte möglich):
   `wsl --install Ubuntu-24.04 --location H:\WSL\Ubuntu-24.04 --name kam-server --no-launch`
   - `--location`: virtuelle Festplatte `ext4.vhdx` auf H: statt im Benutzerprofil auf C: (E8).
   - `--name kam-server`: sprechender Name statt „Ubuntu-24.04“, damit klar ist, dass dies die Server-VM ist.
   - `--no-launch`: Der Linux-Benutzer wird bewusst in einem eigenen Schritt angelegt (Passwort tippt der Nutzer selbst).
   - Hinweis „Sparse VHDs sind experimentell“ kommt von `sparseVhd=true` in `.wslconfig`, bisher ohne Auswirkung.
5. **Prüfung in der VM** (`wsl -d kam-server -u root`):

   | Prüfung | Ergebnis |
   |---|---|
   | System | Ubuntu 24.04.5 LTS |
   | RAM / Swap / Kerne | 9,7 GB / 8 GB / 8 → `.wslconfig` greift |
   | Festplatte | 1007 GB virtuell, wächst nur bei Bedarf (aktuell 1,4 GB auf H:) |
   | GPU | `nvidia-smi` zeigt RTX 2070 Super, 8192 MiB, Treiber 610.47. In WSL wird **kein** eigener Linux-Treiber installiert, der Windows-Treiber wird durchgereicht. |
   | systemd | aktiv (`/etc/wsl.conf`), nötig für den Docker-Dienst |

6. **Docker Engine und NVIDIA Container Toolkit** mit dem Skript [server/setup_wsl.sh](../server/setup_wsl.sh):
   `wsl -d kam-server -u root -- bash /mnt/c/Projekte/KI-Agent/server/setup_wsl.sh <linux-benutzer>`
   - Paketquellen von Docker und NVIDIA mit Signaturschlüssel, damit nur geprüfte Pakete installiert werden.
   - `nvidia-ctk runtime configure` trägt die GPU-Laufzeit in `/etc/docker/daemon.json` ein.
   - Das Skript kann mehrfach laufen und dient zugleich als Anleitung für einen zweiten Rechner.
   - Ergebnis: Docker 29.9.2, Compose v5.7.0, NVIDIA Container Toolkit 1.20.1.
7. **GPU-Test im Container:** `docker run --rm --gpus all ubuntu:24.04 nvidia-smi`
   zeigt die RTX 2070 Super mit 8192 MiB. Damit ist die Kette Windows-Treiber → WSL2 → Docker → Container
   durchgängig. 948 MiB sind bereits durch die Windows-Oberfläche belegt, für die Modelle bleiben ≈ 7 GB.
8. **Linux-Benutzer** `max` mit `adduser` angelegt (Passwort vom Nutzer selbst gesetzt), in die Gruppen `sudo` und
   `docker` aufgenommen und in `/etc/wsl.conf` (`[user] default=max`) als Standard eingetragen. Nach
   `wsl --terminate kam-server` startet die VM als `max`, und `docker run --gpus all … nvidia-smi -L` läuft ohne root.

### Ergebnis Phase 0
Die Kette Windows-Treiber → WSL2 → Docker → Container mit GPU funktioniert. Der Windows-Ollama läuft bewusst
noch weiter, damit die bisherige App nutzbar bleibt. Er wird in Phase 1 abgeschaltet, sobald der Ollama-Container
läuft (nie beide gleichzeitig, sonst teilen sich zwei Ollama-Instanzen die 8 GB VRAM).

Wichtige Befehle:
| Zweck | Befehl (PowerShell) |
|---|---|
| Server-VM öffnen | `wsl -d kam-server` |
| Server-VM stoppen (gibt RAM/VRAM frei) | `wsl --terminate kam-server` |
| Alle VMs stoppen | `wsl --shutdown` |
| Zustand anzeigen | `wsl -l -v` |

## Abhängigkeiten zu anderer Arbeit im Repository
**PR #1 „Persönliche Ablage“ (Branch `jonas/ablage-ordnerstruktur`, Stand 02.11.2026):** Nach jeder Antwort legt
`ablage.py` Frage, Antwort und Quellen in Ordnern je Kunde und Thema ab (`ABLAGE_DIR`, Standard `~/KAM-Ablage`).
Kein Konflikt mit diesem Branch, aber Folgen für den Server:

| Nr. | Folge | Geplante Lösung |
|---|---|---|
| A1 | Auf dem Server landet die Ablage im Dateisystem des Containers, nicht auf dem PC des App-Nutzers. Ohne Volume geht sie beim Neubau des Containers verloren. | Phase 1: eigenes Volume für `ABLAGE_DIR`. Phase 4: Ablage in der Oberfläche anzeigen bzw. als ZIP herunterladen. |
| A2 | Pro Frage ein zusätzlicher Modell- und Embedding-Aufruf. Auf dem Server warten alle Nutzer in einer gemeinsamen Schlange. | Zusatzzeit im Testlauf messen (steht auch in PR #1 als offen). |
| A3 | Das Embedding in `ablage._vektor()` setzt kein `keep_alive`, bge-m3 wird dann nach 5 statt 30 Minuten entladen. | Im Container `OLLAMA_KEEP_ALIVE=30m` als Standard setzen, Hinweis an Jonas. |
| A4 | Nutzername wird zu einem Ordnernamen bereinigt (nur Buchstaben/Ziffern). Wichtig, sobald der Nutzer aus der Cloudflare-Anmeldung (Mail-Adresse) kommt. | Bereits sicher, kein Pfad außerhalb von `ABLAGE_DIR` möglich. |

## Probleme und Lösungen
| Nr. | Problem | Ursache | Lösung |
|---|---|---|---|
| P1 | Geplanter Speicherort D: ungeeignet | D: ist eine HDD, nicht wie angenommen eine SSD | Prüfung mit `Get-PhysicalDisk`, Umstieg auf H: (E8) |
| P2 | Installationsbefehle, direkt aus PowerShell an `wsl … bash -c` übergeben, liefen nicht; Ausgabe nur „deb“ | PowerShell zerlegt mehrzeilige Argumente und Anführungszeichen beim Aufruf von `wsl.exe`, Bash bekam ein zerstückeltes Skript | Befehle als Datei `server/setup_wsl.sh` ins Repository, Aufruf über `/mnt/c/...`. Zusatznutzen: Einrichtung ist dokumentiert und wiederholbar. Zeilenenden LF sind durch `.gitattributes` gesichert, mit CRLF würde Bash scheitern. |
