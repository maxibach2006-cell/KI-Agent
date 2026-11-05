# Server-Einrichtung: Agent und Sprachmodell in einer virtuellen Umgebung

Protokoll der Einrichtung mit allen Entscheidungen, Problemen und Lösungen. Grundlage für die Projektdokumentation.
Branch: `max/server`. Beginn: 02.11.2026.

## Ziel
Der Agent (Streamlit-App) und das Sprachmodell (Ollama) laufen nicht mehr direkt unter Windows, sondern in einer
virtuellen Umgebung, die wie ein Server wirkt. Nutzer laden eine kleine App herunter und erreichen den Server
auch von außerhalb des Heimnetzes. Zweck ist die Vorführung in der Abgabe (Client-Server-Architektur).

```
App (.exe, pywebview) ──HTTPS──► agent.<domain>
                                   │  Cloudflare Access: Microsoft-Anmeldung, nur Team-Mitglieder
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
| 2 | Cloudflare Tunnel und Domain | erledigt 05.11.2026 |
| 3 | Anmeldung über Cloudflare Access | erledigt 05.11.2026, Test mit Nicht-Mitglied offen |
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
| E6 | **Cloudflare Access mit Microsoft-Anmeldung und Team-Prüfung** (zuerst geplant: Einmalcode per Mail) | Einmalcode per Mail, Microsoft-Anmeldung in der App (`st.login`), gemeinsames Passwort | Nur Mitglieder des Teams „Key Account - Kunden“ kommen auf die Seite, es gibt keine zweite Mitgliederliste, und die bestätigte Adresse bestimmt den Index. Kein Anmeldecode im Projekt. Einschränkungen: Nutzer brauchen ein Konto im Tenant, und Cloudflare liest die Gruppen bei der Anmeldung, wer aus dem Team entfernt wird, kommt also bis zum Ablauf der Sitzung weiter hinein. Die Anmeldung gibt dem Agenten keinen Zugriff auf Postfächer: Die Daten werden weiterhin vorab eingelesen. |
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

## Phase 2: Tunnel und Domain (begonnen)

### Stand 04.11.2026
- Domain `auremlips.store` bei **Strato**, geplante Adresse `agent.auremlips.store`, Cloudflare-Konto vorhanden.
- Container `tunnel` ist vorbereitet, aber noch nicht gestartet (kein Token, keine Access-Regel).
- Nameserver bei Strato auf Cloudflare umgestellt. Die Registry führt jetzt `marge.ns.cloudflare.com` und
  `uriah.ns.cloudflare.com` (per RDAP geprüft). Bei der ersten Prüfung stand dort noch Strato: Erst die Abfrage bei der
  Registry zeigte, dass die Änderung noch nicht angekommen war und kein Cache die Ursache ist.
- Entschieden: Microsoft-Anmeldung mit Prüfung der Team-Mitgliedschaft (E6). Entra ID ist als Anmeldeweg in Cloudflare
  eingerichtet. Der Test liefert die Adresse und die Gruppen, darunter „Key Account - Kunden“ (Object ID `20c9c084-…`).
  Die Einstellung „Entra ID Policy Sync“ gehört nicht dazu: Sie verlangt weitere Rechte für Conditional Access, die das
  Projekt nicht braucht. Ist sie an, scheitert der Test mit „Failed to fetch Entra ID Authentication Context“.

### DNS-Bestandsaufnahme vor dem Umzug (öffentliche Abfrage über 1.1.1.1, 04.11.2026)
Die Domain galt als ungenutzt. Die Abfrage zeigte aber Einträge, die beim Umzug verloren gehen könnten (P6):

| Name | Typ | Wert | Bedeutung |
|---|---|---|---|
| `auremlips.store` | NS | `docks14.rzone.de`, `shades18.rzone.de` | Nameserver von Strato |
| `auremlips.store` | A / AAAA | `217.160.0.224` / `2001:8d8:100f:f000::200` | Webserver, HTTP antwortet (Apache), HTTPS schlägt fehl |
| `www.auremlips.store` | CNAME | `auremlips.store` | zeigt auf denselben Webserver |
| `auremlips.store`, `send.auremlips.store` | MX | `feedback-smtp.eu-west-1.amazonses.com` | Rückläufer beim Mailversand über Amazon SES |
| `resend._domainkey.auremlips.store` | TXT | DKIM-Schlüssel | Mailversand über den Dienst Resend |
| `_dmarc.auremlips.store` | TXT | `v=DMARC1;p=reject;` | Mail-Richtlinie der Domain |
| `mail.`, `shop.`, `_amazonses.auremlips.store` | MX | `smtpin.rzone.de` | Mail-Server von Strato, vermutlich ein Sammeleintrag |

Die Liste ist nicht vollständig, weil sich öffentlich nur gezielt nach Namen fragen lässt. Maßgeblich ist die
DNS-Verwaltung bei Strato.

### Geplante Reihenfolge
1. **Bestandsaufnahme bei Strato:** Welche DNS-Einträge gibt es (MX für Mail, A/CNAME für eine Website, TXT für
   SPF/DKIM)? Sie müssen bei Cloudflare identisch übernommen werden, sonst fällt z. B. die Mail aus.
2. **Cloudflare-Konto** (Free-Plan) anlegen und die Domain hinzufügen. Konto und Anmeldung legt Max selbst an.
3. **Nameserver bei Strato** auf die beiden von Cloudflare genannten Server umstellen. Die Umstellung kann
   einige Stunden dauern.
4. **Zuerst die Access-Regel** (Phase 3) für die geplante Adresse anlegen, **dann** den Tunnel freischalten (E15).
5. **Tunnel** im Cloudflare-Dashboard anlegen. Das Tunnel-Token trägt Max selbst als `TUNNEL_TOKEN` in die `.env` ein
   (geheim, nicht im Repository).
6. **Container `cloudflared`** in `server/docker-compose.yml`, Ziel `http://agent:8510` im internen Docker-Netz.
7. **Test von außen**, z. B. über das Handy im Mobilfunknetz.

### Entscheidungen
| Nr. | Entscheidung | Alternativen | Begründung |
|---|---|---|---|
| E15 | **Anmeldung vor Freischaltung:** Die Access-Regel steht, bevor der Tunnel die Adresse erreichbar macht | Tunnel zuerst testen, Anmeldung danach | Sonst wäre die App mit GPU und Index für kurze Zeit ohne Schutz im Internet. Auch für einen Test gibt es keinen Grund dafür. |
| E16 | **Tunnel-Token in eigener Datei** `server/tunnel.env` | in der `.env` | Die `.env` wird auch an den Agent-Container übergeben, der aus dem Internet erreichbar ist. Eine Lücke in der App gäbe sonst das Token preis. |
| E17 | **Zwei Docker-Netze:** `intern` (Agent, Ollama) und `tunnel` (Agent, Tunnel) | ein gemeinsames Netz | Der Tunnel-Container erreicht nur den Agenten, nicht Ollama. |
| E18 | **Tunnel als Compose-Profil**, startet nur mit `--profile tunnel` | startet immer mit | Ohne Token und Access-Regel darf er nicht laufen. So bleibt der Zugang von außen ein bewusster Schritt, und `up -d` allein startet weiter nur die lokale App. |

## Anbindung an Microsoft 365 (Test-Tenant)

### Warum
Die Graph-Connectoren waren geschrieben, aber noch nie gegen echtes Microsoft 365 gelaufen. Die Teams-Quellen in der
Demo sind nur Textdateien. Um die Funktion zu zeigen statt sie zu behaupten, läuft sie jetzt gegen einen eigenen
Test-Tenant mit den fiktiven Daten aus `demo_data/`.

### Stand 04.11.2026
| Quelle | Anlegen (`seed_graph.py`) | Einlesen (`ingest.py --source graph`) |
|---|---|---|
| Teams | 7 Nachrichten | 7 Dokumente |
| Outlook | 7 Mails | 8 Dokumente (zusätzlich eine Mail, die schon im Postfach lag) |
| Kalender | 7 Termine | 7 Dokumente |
| Dateien (SharePoint) | 4 Dateien | 4 Dokumente |
| OneNote | 10 Seiten erst nach acht Versuchen mit Pausen, dabei 2 Dubletten (P9, P10) | 12 Dokumente, davon 2 Dubletten |

Beleg für Teams: Die Frage nach der Eskalation zur Bestellung 4500-8812 wird aus der Kanalnachricht im Tenant
beantwortet, die Quelle verlinkt direkt in Teams. Diese erste Antwort dauerte 191 s, die Ursache ist nicht untersucht
(vermutlich Kaltstart der Modelle).

Beleg für OneNote und Outlook: Die Demo-Frage zum Rahmenvertrag Hoffmann führt beide Quellen zusammen und erkennt den
Widerspruch 31.03.2027 (OneNote) vs. 30.06.2027 (Outlook), Antwort in 11,7 s. Die Dubletten aus P10 tauchen dabei als
Quellen ohne Seitentitel auf.

Live-Test: Max schrieb eine neue Nachricht in einen Teams-Kanal, die in keinen Demo-Daten steht („Am Dienstag ist wieder
Schnitzeltag …“). Nach `ingest.py --source graph` nennt der Agent sie mit Absender und Datum als Quelle, Antwort in 16,1 s.
Der Weg von Teams bis zur Antwort ist damit belegt. Die Antwort enthielt aber ein erfundenes Datum (P11).

Noch offen: Der Index liegt vorerst unter Windows in `data/`, noch nicht im Agent-Container.

### Datumsprüfung (P11): Testlauf vorher/nachher
Vollständiger Testlauf ohne Gutachter, 60 Fragen, Demo-Daten, unter Windows gegen das Container-Ollama:

| | vorher | nachher |
|---|---|---|
| Regelprüfung | 57/60 | 58/60 |
| Antworten mit vollständigem Datum | 26 | 25 |
| Hinweis „Bitte prüfen“ | (0, nachträglich berechnet) | 0 |
| Zeit pro Frage (Schnitt) | 8,2 s | 6,0 s |

Die Prüfung erzeugte also keinen Fehlalarm. In diesen beiden Läufen erfand das Modell kein Datum, ihre Wirkung belegen
deshalb der Fall aus dem Tenant und die 13 Prüfungen in `evaluation/test_datumspruefung.py`. Der Unterschied 57/58 stammt
nicht von der Änderung: Die Frage nach der Kundenliste scheiterte vorher und gelang nachher, vermutlich Streuung des
Modells. Auch die Zeiten liegen im Rahmen der Streuung. Offen bleiben der Widerspruch bei „Bedarfsanalyse Hannover“ und die
Folgefrage „Wann treffe ich sie das nächste Mal?“. Ein Lauf mit 14B-Gutachter fehlt noch, ebenso ein eigener Testfall
im Katalog: Die Demo-Daten enthalten keine Quelle mit relativer Angabe, die Regel „Datum“ gilt aber für alle 60 Fragen.

### Code-Review und Absicherung (04.11.2026)
Ein Code-Review über die gesamte Codebasis meldete 32 Befunde (Obergrenze, nicht einzeln gegengeprüft). Sie wurden in
vier Gruppen abgearbeitet:

| Gruppe | Inhalt |
|---|---|
| 1 Daten und Vorführung | Ausfall einer Quelle löscht nichts mehr, einzelne Fehler kosten nicht die ganze Quelle, kein Absturz bei unerwartetem JSON oder „KW 60“ (P12) |
| 2 Sicherheit vor dem Tunnel | Servermodus (E22), Bilder aus Modellantworten entfernt (E23), Token auf eigenem Volume, Nutzernamen eindeutig (E24) |
| 3 Testergebnisse | Demo-Beispiele aus allen Prompts entfernt (E25) |
| 4 Performance und Vereinfachung | Index im Speicher bis zum nächsten Einlesen, Outlook mit echter Obergrenze, Teams mit `$expand=replies`, unveränderte Dateien werden nicht neu geladen, gemeinsamer Ablauf für App und `antworte()`, Linter `ruff`, feste Versionen (E12) |

Dazu kleinere Fehler: Gesprächsverlauf nach einem Fehler, OneNote-Abschnittsgruppen, Quellennummer 0, Uhrzeit in der
Terminliste nur noch bei Kalenderterminen, Kundennamen aus Graph-Pfaden, Dubletten beim Befüllen, allgemeine Fragen ohne
Kunden werden nicht mehr abgelegt.

**Testlauf vorher/nachher** (60 Fragen, nur Regelprüfung, Demo-Daten):

| Stand | Regelprüfung | Zeit pro Frage |
|---|---|---|
| vor dem Review | 58/60 | 6,0 s |
| nach Gruppe 1 | 58/60 | 6,7 s |
| alle Gruppen, 1. Lauf | 57/60 | 26,1 s (PC ausgelastet, P13) |
| alle Gruppen, 2. Lauf | 59/60 | 7,6 s |

Die Prompts ohne Demo-Beispiele schneiden also nicht schlechter ab. Die Unterschiede zwischen 57 und 59 liegen im Rahmen
der Streuung: Im 1. Lauf schlug zweimal die neue Datumsprüfung an, im 2. Lauf gar nicht. Offen bleibt der nicht erkannte
Widerspruch bei „Bedarfsanalyse Hannover“.

**Nicht geprüft:**
- kein Lauf mit 14B-Gutachter (Modell nicht im Container, Absturzrisiko bei 10 GB für die VM)
- die Anmeldung über den Header von Cloudflare Access (erst mit dem Tunnel testbar, ohne Header gilt „Gast“ mit Demo-Daten)
- Thread-Antworten über `$expand=replies` gegen echtes Teams (im Tenant gibt es noch keine Antwort, nur nachgebildet getestet)
- ein echter Fehler 401 aus dem Tenant beim Einlesen (nur nachgebildet getestet)

**Bewusst nicht umgesetzt:** Eine Neuformatierung aller Dateien (`ruff format`) folgt erst, wenn der Branch
`jonas/steckbrief-vertrag` zusammengeführt ist, sonst entstehen Konflikte in jeder Zeile. Auch in `ablage.py` gibt es
dadurch Überschneidungen mit diesem Branch. `_woerter` in `agent.py` und `ablage.py` bleibt getrennt, weil die Funktionen
verschiedene Regeln haben. Ein eigener Testfall für relative Datumsangaben im Testkatalog fehlt noch.

### Entscheidungen
| Nr. | Entscheidung | Alternativen | Begründung |
|---|---|---|---|
| E22 | **Servermodus** (`SERVER_MODUS=1`): Nutzer nur aus dem Header der Anmeldung, keine Modellwahl, kein Einlesen in der Oberfläche; Adresse ohne eigenen Index bekommt Demo-Daten | Eingabefeld behalten, Passwort in der App | Der Port ist nur über den Tunnel erreichbar, den Header setzt Cloudflare Access. Das Einlesen läuft auf dem Server von Hand, weil die Microsoft-Anmeldung dort sonst im Log landet. |
| E23 | **Markdown-Bilder aus Modellantworten werden zu Links** | Bilder anzeigen, ganze Antwort filtern | Die Antwort beruht auf fremden Mails. Der Browser lädt Bilder sofort, eine präparierte Quelle könnte so Inhalte nach außen senden. |
| E24 | **Ordnername mit Prüfwert**, sobald der Nutzername Sonderzeichen enthält | bisherige Ersetzung durch „_“ | `a.b@firma.de` und `a_b@firma.de` teilten sonst Index und Ablage. Der Demo-Index behält seinen Namen, Tenant-Indizes werden neu eingelesen. |
| E25 | **Neutrale Beispiele und Regeln in allen Prompts**, auch die auf die Fangfragen abgestimmten Regeln (Rabatt/Gutschrift) sind entfernt | Beispiele behalten | Vorgabe aus CLAUDE.md. Nur so sagt der Testlauf etwas über fremde Daten aus. Die Begriffspaare in `VARIANTEN_PROMPT` (zu spät → Lieferverzug) bleiben als allgemeine Fachsprache. |
| E21 | **Unvollständig gelesene Quellen behalten ihre alten Abschnitte** | fehlende Abschnitte immer löschen | Ein fehlendes Dokument kann gelöscht oder nur nicht erreichbar sein. Lieber kurz veraltete Daten als eine verschwundene Quelle. Der Preis: Bei einem Teilfehler bleiben auch wirklich gelöschte Inhalte dieser Quelle bis zum nächsten vollständigen Lauf im Index. |
| E20 | **Datumsprüfung im Code**, Hinweis unter der Antwort | Regel im Prompt, Antwort nachträglich korrigieren | Eine Prompt-Regel half im Versuch nicht (3 von 3 falsch, vorher 2 von 3). Der Code entscheidet, wie bei den Widersprüchen. Korrigieren geht nicht, weil die Antwort schon gestreamt ist und der Code das richtige Datum nicht kennt. |
| E19 | **Eigener Test-Tenant** (Business Basic, Testversion) mit fiktiven Daten | nur Demo-Dateien, Dev Proxy, Firmen-Tenant | Nur ein echter Tenant prüft Anmeldung, Rechte und das Verhalten der Dienste. P8 und P9 wären mit Demo-Daten nie aufgefallen. Er ist befristet, deshalb bleiben die Demo-Daten als Rückfallebene für die Vorführung. |

## Phase 2 und 3: Zugang von außen eingerichtet (05.11.2026)

Reihenfolge wie in E15: erst Anmeldung, dann Tunnel.

1. **Zweite App in Entra** (`KAM Cloudflare Anmeldung`) mit geheimem Schlüssel, getrennt von der App zum Einlesen. Der
   Schlüssel liegt nur bei Cloudflare. **Sein Ablaufdatum notieren:** Danach funktioniert die Anmeldung nicht mehr.
2. **Entra ID als Anmeldeweg** bei Cloudflare, mit „Support Groups“ und PKCE.
3. **Access-Anwendung** `KAM Agent` für `agent.auremlips.store`, Sitzung 8 Stunden, Regel „Allow“ nur für die Gruppe des
   Teams „Key Account - Kunden“.
4. **Tunnel** `kam-server`: Token in `server/tunnel.env`, Container mit `--profile tunnel`, Ziel `http://agent:8510`.
5. **Tenant-Index im Container** eingelesen, Anmeldetoken im Volume `token`.
   Für jeden weiteren Nutzer einzeln und immer mit Konto (E28): `docker compose exec agent python ingest.py --source graph --nutzer anna@firma.de`. Die Anmeldung im privaten Browserfenster, sonst nimmt der Browser das zuletzt angemeldete Konto, und das Einlesen bricht ab.

**Start mit Tunnel** (in der VM, im Projektordner):
`docker compose -f server/docker-compose.yml --profile tunnel up -d`

**Prüfung ohne Anmeldung** (05.11.2026, aus der VM): Startseite, `/_stcore/health`, `/_stcore/stream`, `/api/tags` und eine
Anfrage mit gefälschtem Header `Cf-Access-Authenticated-User-Email` antworten alle mit HTTP 302 auf die Anmeldeseite von
Cloudflare. Am Router ist kein Port offen, Ollama ist aus dem Netz `tunnel` nicht erreichbar.

**Test von außen** (05.11.2026, durch Max): Anmeldung mit dem Team-Konto und Nutzung der App funktionieren. Noch offen:
Test mit einem Konto ohne Team-Mitgliedschaft, damit auch die Ablehnung belegt ist.

## Strom-Tracker (05.11.2026)
`strom.py` zeigt unter jeder Antwort den Verbrauch und in der Seitenleiste die Summe in Geld. Der Stand liegt in
`data/strom.json` und übersteht einen Neustart.

| Wert | Herkunft |
|---|---|
| Grafikkarte | **gemessen** mit `nvidia-smi`, einmal pro Sekunde |
| übriger PC | **geschätzt**, fester Wert `STROM_REST_WATT` (60 W), ohne Messgerät an der Steckdose nicht messbar |
| Strompreis | **Annahme** `STROM_PREIS_EURO_KWH` (35 Cent/kWh), eigenen Tarif in `.env` eintragen |

Erste Messung: Eine Frage in der App verbrauchte rund 0,85 Wh (davon Grafikkarte gemessen 0,62 Wh), das sind rund
0,03 Cent. Das ist ein Einzelwert, die Laufzeit einer Frage schwankt stark. Grafikkarte im Leerlauf mit geladenen
Modellen: rund 26 W. Dazu kommt der geschätzte Rest des PCs.

Grenzen: Eine Anfrage zählt den gesamten Verbrauch während ihrer Laufzeit, auch den Grundverbrauch und das, was
andere Programme auf dem PC an der Grafikkarte verursachen. Gemessen wird erst, wenn die App nach einem Start zum
ersten Mal geöffnet wurde. Das Einlesen im Terminal zählt nicht mit. Die Kosten sieht jeder angemeldete Nutzer.

| Nr. | Entscheidung | Alternativen | Begründung |
|---|---|---|---|
| E26 | **Agent-Container bekommt Zugriff auf die GPU** (`gpus: all`), nur um `nvidia-smi` zu lesen | eigener Mess-Container, Messgerät an der Steckdose | Am einfachsten, der Messwert liegt direkt in der App. Preis: Der aus dem Internet erreichbare Container hat GPU-Zugriff, läuft aber weiter als eigener Benutzer ohne Root. Für den echten Betrieb wäre ein getrennter Mess-Container sauberer. |
| E27 | **Hochrechnung auf den Monat nur aus der Zeit ohne Anfragen** | Mittelwert der gesamten Laufzeit | Kurz nach dem Start bestimmten wenige Anfragen das Ergebnis: Der erste Test zeigte irreführend 38 € im Monat. |
| E28 | **Token-Cache je Nutzer** (`config.token_cache`), Einlesen mit `--nutzer`; angemeldetes Konto wird geprüft | ein gemeinsamer Cache, `TOKEN_CACHE` je Lauf von Hand umsetzen | `GraphClient._token` nahm das erste Konto im Cache: Las der Server erst für A und dann für B ein, bekam B still die Daten von A. Jetzt: eigene Datei je Konto im Token-Volume, falsches Konto bei der Anmeldung wird abgelehnt, ohne `--nutzer` und mit mehreren Konten bricht das Einlesen ab. Test: `evaluation/test_token_cache.py`, dazu echt gegen den Tenant geprüft (Jonas liest nur eigene Daten, Bellas Cache mit fremdem Token erzwingt neue Anmeldung). |

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
| P4 | Erste Seite der App hing über eine Minute bei „Lade Sprachmodell …“ | Kaltstart: qwen2.5:7b (4,7 GB) wird beim ersten Aufruf von der virtuellen Festplatte gelesen und auf die GPU geladen (1 min 20 s laut Ollama-Log). Die Anfrage danach (18 s) wartete noch auf die Initialisierung. | Kein Fehler, aber im Test von außen als langes Warten aufgefallen. Gemessen: 96 s zum Laden (bge-m3 14,5 s, qwen 82 s). Lösung: `agent_start.sh` lädt die Modelle beim Serverstart, und auf dem Server bleiben sie dauerhaft geladen (`KEEP_ALIVE=-1m`). Aufwärmen danach: 0,07 s. Preis: Solange der Server läuft, sind etwa 5,7 GB VRAM belegt. Freigeben mit `wsl --shutdown`. Nach dem Start einer VM dauert es bis zur Bereitschaft weiterhin 1–2 Minuten. |
| P8 | Der Datei-Connector übersprang alle Dateien mit einem 404 | Das automatisch angelegte Team „KAM-Pilot“ hat keine SharePoint-Ablage. Dieser eine Fehler brach den ganzen Connector ab. | `connectors/files.py` überspringt nur noch das betroffene Team. Danach: 4 Dateien eingelesen. |
| P9 | OneNote antwortet unzuverlässig: gültiges Token erhält zeitweise 401 (Code 40001) oder 403 (Code 40007), das Anlegen von Seiten scheitert mit 404 | Vergleichstest: gleiches Token, gleicher Pfad, mal 200, mal 401. Token und Rechte sind also nicht die Ursache. Vermutung: OneNote ist im neuen Tenant noch nicht fertig bereitgestellt (nicht belegt). | `graph_client.py` wiederholt Anfragen bei Code 40001 bis zu fünfmal. Das Anlegen gelang erst nach acht Versuchen mit Pausen. Ob das Lesen dauerhaft zuverlässig ist, muss sich noch zeigen. |
| P10 | 2 Hoffmann-Seiten doppelt im Notizbuch (12 statt 10) | `seed_graph.py` prüft vor dem Anlegen den Titel. Frisch angelegte Seiten erscheinen in der Liste zunächst ohne Titel, gelten also als fehlend. | Dubletten von Hand in OneNote löschen. Offen: Prüfung in `seed_graph.py` verbessern. |
| P11 | Der Agent erfand ein Datum: „Schnitzeltag ist Dienstag, 07.11.2026“. In der Quelle steht nur „Am Dienstag“, gemeint wäre ausgehend vom 04.11.2026 der 10.11.2026, und der 07.11.2026 ist ein Samstag. | Das Modell rechnet die relative Angabe selbst um und verrechnet sich. Keine Prüfung im Code erfasst Daten im Antworttext. Versuch mit 3 Läufen je Fassung: bisheriger Prompt 2-mal falsch, Prompt-Variante („relative Angaben aus Quellen wörtlich wiedergeben“) 3-mal falsch, die Variante hilft also nicht. | **Erkannt, nicht verhindert.** `agent.unbelegte_daten()` vergleicht vollständige Daten der Antwort mit Quellen, Frage, heutigem Datum und den berechneten Grenzen des Zeitraums; fehlt der Beleg, nennt der Anhang das Datum unter „Bitte prüfen“. In der App erscheint der Hinweis bei der Schnitzeltag-Frage. Eine ältere Antwort mit erfundenem Termin („Freitag, 10.11.2026“) hätte er ebenfalls erfasst. Grenzen: Das falsche Datum bleibt im Text stehen (die Antwort wird gestreamt), nur vollständige Daten werden geprüft, ein echtes Datum aus einer Quelle am falschen Ort fällt nicht auf. |
| P13 | Ein Testlauf brauchte 26 s pro Frage statt rund 7 s | Der Code war es nicht: Direkt danach brauchte eine Frage rund 5 s und der nächste volle Lauf 7,6 s. Während des Laufs waren unter Windows nur 0,4 GB RAM frei, die VM lagerte aus, und Ollama belegte 8,1 GB. Nebenbei liefen weitere Programme (u. a. Spiele-Launcher). Die genaue Ursache ist nicht belegt. | Vor Vorführung und Messungen andere Programme schließen. Zeitwerte nur aus ruhigen Läufen vergleichen. |
| P12 | Fehler aus dem Code-Review: (a) Ein Connector-Ausfall löschte die ganze Quelle aus dem Index. (b) Doppelte Abschnitte brachen das Einlesen ab. (c) Eine defekte Datei oder ein gesperrter Kanal kostete die ganze Quelle. (d) Unerwartetes JSON vom Modell ließ die Antwort abstürzen. (e) „KW 60“ brachte die Frage zum Absturz. | (a) Der Abgleich wertete „fehlt in dieser Lieferung“ als „gelöscht“, und es wurde vor dem Speichern des Neuen gelöscht. (b) Die ID ergibt sich aus Text und Link. (c) Fehler wurden nur je Connector abgefangen. (d) `format="json"` erzwingt gültiges JSON, aber keinen Aufbau. (e) Ungültige Daten wurden nicht abgefangen. | (a) `ingest()` schützt unvollständige Quellen (E21) und löscht erst nach dem Speichern. (b) Gleiche Abschnitte werden einmal gespeichert. (c) Absicherung je Datei, Kanal und Chat über `GraphClient.melde_problem()`. (d) `verstehen.json_wert()` prüft auch den Typ. (e) Unmögliche Zeitangaben gelten als normale Frage. Die App warnt jetzt bei unvollständigem Lesen. |
| P6 | Domain galt als ungenutzt, im DNS stehen aber Webserver- und Mail-Einträge (Resend/Amazon SES, DMARC) | Herkunft der Einträge nicht geklärt; der Mailversand wird laut Max nicht gebraucht | Vor dem Nameserver-Umzug öffentlich geprüft (Tabelle in „Phase 2“) und mit Max geklärt. Die Resend-/SES-Einträge werden nicht zu Cloudflare übernommen. Lehre: Vor einem DNS-Umzug die Einträge prüfen, auch wenn eine Domain als ungenutzt gilt. |
| P7 | Nach einem Neustart von Windows war die VM aus (`Stopped`), die App also nicht erreichbar | `instanceIdleTimeout=-1` verhindert nur das Beenden bei Leerlauf. Gestartet wird WSL erst durch den ersten `wsl`-Aufruf. Danach fuhren die Container von selbst hoch und waren nach gut einer Minute „healthy“. | Offen für Phase 5: `start_server.bat` startet die VM, optional per Aufgabenplanung bei der Anmeldung. |
| P5 | Streamlit zeigt im Log `External URL: http://<öffentliche IP>:8510` | Streamlit ermittelt beim Start die öffentliche IP und zeigt sie nur an | Unkritisch: Der Port ist nur an `127.0.0.1` gebunden und von außen nicht erreichbar. Zugriff von außen erst in Phase 2 über den Tunnel. |
