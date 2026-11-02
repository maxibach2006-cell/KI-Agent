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
| 1 | Container für Ollama und Agent (docker compose) | erledigt 02.11.2026 |
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
| E10 | **`OLLAMA_MAX_LOADED_MODELS=2`** | 1 (wie zunächst geplant) | Pro Frage braucht der Agent das Embedding-Modell (bge-m3) **und** das Chat-Modell. Mit 1 würde bei jeder Frage umgeladen. Die Regel „nie zwei große Modelle“ bleibt gewahrt: bge-m3 ist klein (0,7 GB), zusammen 5,7 GB von 8 GB VRAM. `OLLAMA_NUM_PARALLEL=1`: eine Anfrage nach der anderen. |
| E11 | **Ein einziges Ollama, im Container**; Port 11434 nur für diesen PC (`127.0.0.1`) freigegeben | Windows-Ollama behalten | Zwei Ollama-Instanzen würden sich die 8 GB VRAM teilen. Über den freigegebenen Port nutzen Testlauf und Entwicklung unter Windows (`python …` aus CLAUDE.md) unverändert das Container-Ollama, ohne Codeänderung. Aus dem Netz ist der Port nicht erreichbar. |
| E12 | **Feste Versionen** (`ollama/ollama:0.40.13`, `python:3.12-slim`) | Tag `latest` | Ein Neustart soll nicht unbemerkt eine neue Version laden. 0.40.13 ist dieselbe Version wie bisher unter Windows, so sind die Ergebnisse vergleichbar. |
| E13 | **App im Container als eigener Benutzer** `agent`, nicht root | root (Docker-Standard) | Eine Lücke in der Web-App gäbe keine Root-Rechte im Container. Wichtig, weil die App in Phase 2 aus dem Internet erreichbar wird. |
| E14 | **Kein Python-Code geändert.** Container-Einstellungen über Umgebungsvariablen | `config.py` anpassen | Die `ollama`-Bibliothek liest `OLLAMA_HOST`, Streamlit nimmt `--server.address` als Startparameter, `ABLAGE_DIR` und `HEUTE` kommen schon aus der Umgebung. `agent.py`, `config.py` und `prompts.py` bleiben unberührt, keine Absprache und kein Konflikt mit Jonas' Arbeit nötig. |

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

## Phase 1: Container für Ollama und Agent

### Neue Dateien
| Datei | Aufgabe |
|---|---|
| [server/docker-compose.yml](../server/docker-compose.yml) | beschreibt beide Container, ihre Volumes, Ports, Health-Checks und Neustart-Regeln |
| [server/Dockerfile](../server/Dockerfile) | baut den Agent-Container: Python 3.12, Pakete aus `requirements.txt`, Zeitzonendaten, eigener Benutzer |
| [server/agent_start.sh](../server/agent_start.sh) | Startablauf im Container: auf Ollama warten, fehlende Modelle laden, Demo-Daten einlesen, Streamlit starten |
| [.dockerignore](../.dockerignore) | hält `.env`, Token, Index und Git-Verlauf aus dem Container-Image heraus |

```
WSL2-VM kam-server
 ├─ Container ollama  (GPU)     Volume ollama-modelle  Port 127.0.0.1:11434
 └─ Container agent   (Streamlit) Volumes index, ablage  Port 127.0.0.1:8510
        └─ OLLAMA_HOST=http://ollama:11434  (internes Docker-Netz)
```

### Schritte
1. **Ausgangswert gemessen** (Windows-Ollama, vorher): `testlauf.py --kategorie Fakten --ohne-gutachter`
   → 17/17 bestanden, 100 s inklusive Einlesen, ≈ 5,5 s pro Frage.
2. **Windows-Ollama abgeschaltet:** Prozesse beendet, Autostart-Verknüpfung `Ollama.lnk` aus dem Autostart-Ordner nach
   `H:\WSL\windows-ollama-autostart\` verschoben (nicht gelöscht, Rückweg: zurückkopieren).
3. **Images gebaut und Modelle geladen:** `docker compose build`, dann `ollama pull qwen2.5:7b` und `ollama pull bge-m3`
   im Container. Die Modell-IDs (`845dbda0ea48`, `790764642607`) sind identisch mit denen unter Windows.
   Ollama meldet `library=CUDA … RTX 2070 SUPER … available 7.0 GiB`, nutzt also die GPU.
4. **Erster Start brach ab** → Problem P3. Lösung in `.wslconfig`, danach laufen beide Container dauerhaft.
5. **Prüfung:** Beide Container „healthy“, unter Windows antworten `http://localhost:8510` (App) und
   `http://localhost:11434` (Ollama). `ollama ps`: qwen2.5:7b und bge-m3 zu 100 % auf der GPU, Kontext 8192.
6. **Demo-Frage in der App** („Konditionen Rahmenvertrag Hoffmann …“): korrekte Antwort mit Quellen in 12,6 s,
   Widerspruch 31.03.2027 vs. 30.06.2027 erkannt, Ablage schreibt ins Volume (`/daten/ablage/demo/_register.json`).
7. **Testlauf im Container** (`docker exec … python evaluation/testlauf.py --kategorie Fakten --ohne-gutachter`).

### Ergebnis: vorher/nachher
| | Windows (vorher) | Container in WSL2 (nachher) |
|---|---|---|
| Regelprüfung Fakten | 17/17 | 17/17 |
| Zeit pro Frage (Schnitt) | ≈ 5,5 s | 6,4 s |
| Schreibgeschwindigkeit (warm) | – | ≈ 60 Token/s, 0,2–0,3 s für eine kurze Antwort |
| Erster Start (Modelle kalt laden) | ≈ 10 s | 1–2 min |

Die Antwortqualität ist unverändert. Der Container ist ≈ 15 % langsamer. Wahrscheinliche Gründe: Die GPU wird über
eine Virtualisierungsschicht (WDDM/`dxgkrnl`) angesprochen, und die VM hat 8 statt 12 CPU-Threads. Für die Demo
unerheblich. Der langsame Kaltstart betrifft nur die erste Frage nach dem Hochfahren; `start_server` (Phase 5) soll
die Modelle deshalb vorab laden.

### Wichtige Befehle (in der VM, im Ordner `/mnt/c/Projekte/KI-Agent`)
| Zweck | Befehl |
|---|---|
| Starten / nach Änderungen neu bauen | `docker compose -f server/docker-compose.yml up -d --build` |
| Zustand | `docker compose -f server/docker-compose.yml ps` |
| Logs des Agenten | `docker compose -f server/docker-compose.yml logs -f agent` |
| geladene Modelle | `docker exec kam-server-ollama-1 ollama ps` |
| Testlauf im Container | `docker exec -u root kam-server-agent-1 python evaluation/testlauf.py --kategorie Fakten --ohne-gutachter` |
| Stoppen | `docker compose -f server/docker-compose.yml down` (Volumes bleiben erhalten) |

Codeänderungen erreichen den Container erst nach `up -d --build`, so wie Streamlit unter Windows erst nach einem
Neustart geänderte Module lädt.

**Für Jonas:** Auf seinem Rechner ändert sich nichts, er arbeitet weiter mit dem Windows-Ollama. Auf Max' Rechner
gibt es nur noch das Container-Ollama. Der Testlauf unter Windows funktioniert dort, solange die VM läuft.

## Abhängigkeiten zu anderer Arbeit im Repository
**PR #1 „Persönliche Ablage“ (Branch `jonas/ablage-ordnerstruktur`, Stand 02.11.2026):** Nach jeder Antwort legt
`ablage.py` Frage, Antwort und Quellen in Ordnern je Kunde und Thema ab (`ABLAGE_DIR`, Standard `~/KAM-Ablage`).
Kein Konflikt mit diesem Branch, aber Folgen für den Server:

| Nr. | Folge | Geplante Lösung |
|---|---|---|
| A1 | Auf dem Server landet die Ablage im Dateisystem des Containers, nicht auf dem PC des App-Nutzers. Ohne Volume geht sie beim Neubau des Containers verloren. | Phase 1 erledigt: Volume `ablage` für `ABLAGE_DIR=/daten/ablage`. Offen für Phase 4: Ablage in der Oberfläche anzeigen bzw. als ZIP herunterladen. |
| A2 | Pro Frage ein zusätzlicher Modell- und Embedding-Aufruf. Auf dem Server warten alle Nutzer in einer gemeinsamen Schlange. | Zusatzzeit im Testlauf messen (steht auch in PR #1 als offen). |
| A3 | Das Embedding in `ablage._vektor()` setzt kein `keep_alive`, bge-m3 wird dann nach 5 statt 30 Minuten entladen. | Erledigt: `OLLAMA_KEEP_ALIVE=30m` als Standard im Ollama-Container. Hinweis an Jonas für den Betrieb unter Windows. |
| A4 | Nutzername wird zu einem Ordnernamen bereinigt (nur Buchstaben/Ziffern). Wichtig, sobald der Nutzer aus der Cloudflare-Anmeldung (Mail-Adresse) kommt. | Bereits sicher, kein Pfad außerhalb von `ABLAGE_DIR` möglich. |

## Probleme und Lösungen
| Nr. | Problem | Ursache | Lösung |
|---|---|---|---|
| P1 | Geplanter Speicherort D: ungeeignet | D: ist eine HDD, nicht wie angenommen eine SSD | Prüfung mit `Get-PhysicalDisk`, Umstieg auf H: (E8) |
| P2 | Installationsbefehle, direkt aus PowerShell an `wsl … bash -c` übergeben, liefen nicht; Ausgabe nur „deb“ | PowerShell zerlegt mehrzeilige Argumente und Anführungszeichen beim Aufruf von `wsl.exe`, Bash bekam ein zerstückeltes Skript | Befehle als Datei `server/setup_wsl.sh` ins Repository, Aufruf über `/mnt/c/...`. Zusatznutzen: Einrichtung ist dokumentiert und wiederholbar. Zeilenenden LF sind durch `.gitattributes` gesichert, mit CRLF würde Bash scheitern. |
| P3 | Beim ersten Start brach der Agent mit `Server disconnected without sending a response` ab, beide Container starteten kurz darauf neu. Ollama meldete danach irreführend „total blobs: 0“ (die Modelle waren aber vorhanden). | Das Systemprotokoll (`journalctl`) zeigte um 20:19:31, dass systemd die **ganze Distribution herunterfuhr**: WSL beendet eine Distribution ≈ 15 s, nachdem das letzte Windows-Terminal sie verlassen hat, auch wenn darin Dienste laufen. Der Startbefehl hatte sich beendet, beim Warten war kein Terminal mehr offen. | `.wslconfig`: `[general] instanceIdleTimeout=-1` und `[wsl2] vmIdleTimeout=-1`. Test: `wsl --shutdown`, Container starten, Terminal schließen, 60 s warten → `kam-server` läuft weiter. Nebenbei bestätigt: Nach einem Start der VM fahren die Container dank `restart: unless-stopped` von selbst hoch. Lehre: Ein „Server“ unter WSL braucht diese Einstellung, sonst lebt er nur, solange ein Fenster offen ist. |
| P4 | Erste Seite der App hing über eine Minute bei „Lade Sprachmodell …“ | Kaltstart: qwen2.5:7b (4,7 GB) wird beim ersten Aufruf von der virtuellen Festplatte gelesen und auf die GPU geladen (1 min 20 s laut Ollama-Log). Die Anfrage danach (18 s) wartete noch auf die Initialisierung. | Kein Fehler. Ab der zweiten Anfrage 0,2–0,3 s. Für die Demo: Modelle beim Serverstart vorladen (Phase 5). |
| P5 | Streamlit zeigt im Log `External URL: http://<öffentliche IP>:8510` | Streamlit ermittelt beim Start die öffentliche IP und zeigt sie nur an | Unkritisch: Der Port ist nur an `127.0.0.1` gebunden und von außen nicht erreichbar. Zugriff von außen erst in Phase 2 über den Tunnel. |
