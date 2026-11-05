# Lokaler Informations-Agent für das Key-Account-Management

Ein lokaler KI-Agent mit **Ollama**, der Fragen eines Key-Account-Managers beantwortet. Er durchsucht OneNote („MBS 2“), Teams, Outlook und abgelegte Mail-Dateien (.msg/.eml) und belegt **jede Aussage mit einer Quelle**. Er ist die lokale Umsetzung eines zuvor in Microsoft Copilot genutzten Agenten.

## Problem und Ziel
- Viele Kundendaten sind über Jahre unstrukturiert entstanden. Gerade ältere Informationen findet man kaum wieder.
- Ziel: kürzere Suchzeiten, alte Daten wieder nutzbar machen, einheitlich aufgebaute Antworten mit Quellen.
- Grenze: Es werden **nur Daten des angemeldeten Mitarbeitenden** durchsucht (Datenschutz, Zugriffsrechte).

## Ansatz: Retrieval-Augmented Generation (RAG)
Ein Sprachmodell kennt die Firmendaten nicht. Deshalb werden die Daten vorher in einem lokalen Suchindex abgelegt. Bei jeder Frage sucht der Agent die passenden Textstellen und gibt nur diese mit Quellenangabe an das Modell weiter.

```
 Microsoft Graph (delegiert)                   demo_data/ (Fallback)
 OneNote · Outlook · Kalender · Teams · Dateien        │
            └──────────────┬─────────────────┘
                           ▼
  ingest.py   Text + Metadaten → Abschnitte (800 Zeichen) → Embeddings (bge-m3)
                           ▼
                ChromaDB (lokal, ein Index pro Nutzer)
                           ▼
  agent.py    1. Frage → ähnlichste Abschnitte (OneNote bevorzugt)
              2. Widerspruchsprüfung (LLM als JSON, vom Code nachgeprüft)
              3. qwen2.5:7b schreibt die Antwort nach Ausgabevorlage
              4. Widersprüche + Quellenliste aus Metadaten (nicht vom LLM)
                           ▼
  app.py      Streamlit-Chat mit Quellen, Textauszügen und Antwortzeit
```

| Baustein | Wahl | Begründung |
|---|---|---|
| Sprachmodell | `qwen2.5:7b` | passt in 8 GB VRAM (RTX 2070 Super), gutes Deutsch |
| Embeddings | `bge-m3` | mehrsprachig, stark bei deutschen Texten |
| Vektor-DB | ChromaDB | läuft lokal ohne Server, einfach |
| Datenzugang | Microsoft Graph, delegiert | sieht nur die Daten des angemeldeten Nutzers |
| Oberfläche | Streamlit | Chat-UI in wenigen Zeilen |

## Ausgabekonzept
Jede Antwort hat denselben Aufbau (Vorlage in [prompts.py](prompts.py)):

1. **Kurzantwort**: direkte Antwort in 1–3 Sätzen mit `[n]`
2. **Details**: Stichpunkte, jeder mit Quelle `[n]`
3. **Vorschläge für präzisere Rückfragen**
4. **Widersprüche**: abweichende Angaben mit Quelle und Datum gegenübergestellt
5. **Quellen**: je nach Quellentyp:
   - OneNote: Abschnitt, Seite, Datum, Link
   - Outlook: Betreff, Absender, Datum, Link
   - Teams/SharePoint: Kanal bzw. Dateiname, Speicherort, Link

Teil 1–3 schreibt das Sprachmodell. Teil 4 und 5 erzeugt der Code aus den Metadaten, damit Links und Daten nicht erfunden sein können.

**Datumsprüfung:** Das Modell rechnet relative Angaben („am Dienstag“) teils falsch in ein Kalenderdatum um. Der Code vergleicht deshalb jedes vollständige Datum im Antworttext mit den Quellen und nennt fehlende Belege unter „Bitte prüfen“. Test ohne Ollama: `python evaluation/test_datumspruefung.py`

**Stromkosten:** [strom.py](strom.py) zeigt unter jeder Antwort den Verbrauch und in der Seitenleiste die Summe in Euro. Die Grafikkarte wird gemessen, der übrige PC ist geschätzt, und der Strompreis ist eine Annahme (`STROM_REST_WATT`, `STROM_PREIS_EURO_KWH` in der `.env`). Test ohne Ollama: `python evaluation/test_strom.py`

**Fehlerfälle:** Kann eine Quelle beim Einlesen nicht vollständig gelesen werden (z. B. vorübergehender Fehler 401, defekte Datei, gesperrter Kanal), behält sie ihre bisherigen Abschnitte im Index, und die App zeigt eine Warnung. Test ohne Ollama: `python evaluation/test_robustheit.py`

**Widerspruchsprüfung als eigener Schritt:** Ein 7B-Modell übersieht Widersprüche leicht, wenn es gleichzeitig die Antwort schreibt. Deshalb läuft sie getrennt:
1. **Kandidaten:** Ein kurzer LLM-Aufruf (`format="json"`) meldet mögliche Widersprüche. Zusätzlich schlägt der Code Paare vor: unterschiedliche Daten in zwei Quellen, deren Sätze ein gemeinsames Fachwort haben.
2. **Belegprüfung (Code):** Beide Werte müssen wörtlich in einer Quelle stehen und sich wirklich unterscheiden.
3. **Gegenprüfung:** Betreffen beide Werte dieselbe Sache? Das Ja/Nein-Urteil eines 7B-Modells ist hier unzuverlässig. Gut kann es aber benennen, *worauf* sich ein Wert bezieht. Deshalb wird es einmal mit beiden Sätzen und einmal mit jedem Satz einzeln gefragt, und der Code vergleicht die Beschreibungen. Ergebnis: „Enddatum des Vertrags“ und „Neues Enddatum des Vertrags“ gelten als Widerspruch, „Frist für Angebotsabgabe“ und „Gültigkeit des Angebots“ nicht.

**Frageverständnis** ([verstehen.py](verstehen.py)):
- **Folgefragen:** Mit dem Gesprächsverlauf (die letzten 3 Runden) schreibt das Modell eine Folgefrage vor der Suche in eine eigenständige Frage um. „Und bis wann läuft der?“ wird zu „Bis wann läuft der Rahmenvertrag mit Hoffmann?“. Bei einem Themenwechsel bleibt die Frage unverändert. Die Oberfläche zeigt an, wie die Frage verstanden wurde. „Neues Gespräch“ setzt den Verlauf zurück.
- **Umschreibungen:** Ist der beste Treffer schwach, formuliert das Modell die Frage in Fachsprache um („Steuerungen zu spät“ → „Lieferverzug Steuermodule“), und es wird zusätzlich damit gesucht. Enthält die Frage einen Begriff, den es in den Daten nicht gibt (z. B. „Siemens“), wird **nicht** erweitert. Sonst käme eine Antwort zu einem anderen Kunden heraus.

**Hybride Suche:** Die Ähnlichkeitssuche (Embeddings) findet Umschreibungen, aber Eigennamen und kurze Fragen („hoffmann rabatt?“, „Wer ist Jens Albrecht?“) schlecht. Darum zählt zusätzlich, wie viele Fragewörter in einem Abschnitt vorkommen. Bekannte Namen aus Titeln und Absendern öffnen das Gate gegen Halluzination. Unbekannte Namen („Siemens Energy“) führen weiterhin zu „keine Quelle“.

**Zeitfragen („Was steht nächste Woche an?“):** Eine reine Ähnlichkeitssuche kann nicht rechnen, denn „nächste Woche“ ähnelt keinem Text mit „20.11.2026“. Darum gilt:
1. [zeitraum.py](zeitraum.py) erkennt Zeitangaben (heute, morgen, diese/nächste/letzte Woche, KW 47, im November, am 20.11., in den nächsten 14 Tagen) und rechnet sie ausgehend vom heutigen Datum in ein Von-Bis-Datum um.
2. Beim Einlesen merkt sich jeder Abschnitt alle Daten, die in seinem Text genannt werden.
3. Bei einer Zeitfrage holt der Agent alle Kalendertermine, Mails, Teams-Nachrichten und Notizen mit einem Datum im Zeitraum. Nennt die Frage einen Namen („bei Hoffmann“), bleiben nur passende Einträge übrig.
4. Die chronologische Terminliste erzeugt der Code. Das Modell fasst nur zusammen und kann so keine Termine weglassen.

Das Modell bekommt außerdem das heutige Datum im System-Prompt. Für eine Demo an einem festen Tag lässt sich das Datum in der `.env` setzen, z. B. `HEUTE=2026-11-02`.

Findet die Suche nichts ausreichend Ähnliches (`MIN_SIMILARITY` in [config.py](config.py)), antwortet der Agent ohne Sprachmodell mit „keine passende Quelle gefunden“. So kann er an dieser Stelle nichts erfinden.

## Installation
Voraussetzung: Python 3.11+ und [Ollama](https://ollama.com).
PowerShell:
```bash
ollama pull qwen2.5:7b
ollama pull bge-m3
python -m venv "$env:USERPROFILE\.venvs\ki-agent"
& "$env:USERPROFILE\.venvs\ki-agent\Scripts\Activate.ps1"
pip install -r requirements.txt
```
Am einfachsten startet `start_demo.bat`: Es richtet die Umgebung beim ersten Start selbst ein. In der Eingabeaufforderung (cmd) heißt der Pfad `%USERPROFILE%\.venvs\ki-agent`. In PowerShell funktioniert diese Schreibweise nicht, dort entsteht sonst ein Ordner mit dem Namen `%USERPROFILE%` im Projekt.
Die virtuelle Umgebung liegt bewusst außerhalb des OneDrive-Ordners, damit OneDrive nicht tausende Dateien synchronisiert.

## Nutzung
**Am einfachsten:** `start_demo.bat` doppelklicken. Das Skript liest die Demo-Daten ein und öffnet die Oberfläche. Es nutzt immer die virtuelle Umgebung, aktivieren ist nicht nötig.

Wer die Befehle von Hand ausführt, muss vorher die virtuelle Umgebung aktivieren (PowerShell: `& "$env:USERPROFILE\.venvs\ki-agent\Scripts\Activate.ps1"`). Sonst kommt `No module named 'chromadb'`.

**Demo-Modus (ohne Microsoft 365):**
```bash
python ingest.py --source demo
streamlit run app.py
```
**Mit Microsoft 365:** Einrichtung siehe [docs/TENANT_SETUP.md](docs/TENANT_SETUP.md), dann:
```bash
python seed_graph.py            # nur im Test-Tenant: Demo-Daten anlegen
python ingest.py --source graph --nutzer anna@firma.de   # --nutzer: Pflicht, sobald mehrere Nutzer einlesen
streamlit run app.py
```
**Kommandozeile:** `python agent.py "Bis wann läuft der Vertrag mit Hoffmann?"`

**Als Server (Docker in WSL2):** Agent und Ollama laufen als Container in einer WSL2-VM. Einrichtung, Entscheidungen und Messwerte: [docs/server_einrichtung.md](docs/server_einrichtung.md).
```bash
wsl -d kam-server --cd /mnt/c/Projekte/KI-Agent -- docker compose -f server/docker-compose.yml up -d --build
```
Danach ist die App unter http://localhost:8510 erreichbar. Im Serverbetrieb (`SERVER_MODUS=1`) kommt der Nutzer aus der Anmeldung, Modellwahl und Einlesen sind ausgeblendet.

### Persönliche Ablage
Nach jeder Antwort ordnet der Agent die Frage einem Kunden und einem Thema (Projekt, Verhandlung, Vertrag …) zu und baut daraus eine Ordnerstruktur auf, die mit jeder Frage wächst. Standardort ist `<Benutzerordner>\KAM-Ablage\<nutzer>`, änderbar mit `ABLAGE_DIR` in der `.env`.
```
KAM-Ablage/<nutzer>/
├─ _Uebersicht.md                 alle Kunden und Themen
└─ <Kunde>/
   ├─ _Uebersicht.md              alle Fragen zum Kunden
   ├─ _Allgemein/                 Fragen ohne eigenen Themenordner
   └─ <Thema>/                    z. B. Rahmenvertrag RV-…
      ├─ _Stand.md                Steckbrief (nur Verträge)
      ├─ 2026-11-02_0930 <Frage>.md
      └─ Quellen/                 Kopien (lokale Dateien) bzw. Textauszüge + Link zum Original
```
- Ordner entstehen erst ab der **2. Frage** zum selben Kunden bzw. Thema. Vorher wird die Frage nur vorgemerkt und beim Anlegen nachgetragen.
- Fragen ohne Kunden- oder Projektbezug („Welche Termine habe ich nächste Woche?“) werden nicht abgelegt. Steht der Kunde nicht in der Frage, wird er aus den Quellen nur übernommen, wenn mindestens die Hälfte der Quellen zu ihm gehört (`ABLAGE_KUNDE_ANTEIL`).
- Das Sprachmodell beschreibt nur Kunde und Thema. Ob es ein bekannter Kunde bzw. ein bekanntes Thema ist, entscheidet der Code (Namensvergleich, gleiche Vertrags- oder Projektnummer, Embedding-Ähnlichkeit).
- **Steckbrief bei Verträgen:** Im Themenordner entsteht `_Stand.md` mit Laufzeit, Rabatt, Zahlungsziel, Kündigungsfrist, Preisanpassung und Ansprechpartner, jeweils mit Quelle und Datum der Quelle, dazu Fristen (inkl. berechnetem letzten Kündigungstermin) und Änderungen. Jeder Wert wird vom Code gegen die Originalquelle geprüft; eine neuere Quelle ersetzt einen alten Wert, gleich alte Quellen mit verschiedenen Werten werden als ⚠️ Widerspruch angezeigt. Alle Quellen des Steckbriefs liegen als Kopie bzw. Auszug in `Quellen/` und sind verlinkt. Der Steckbrief ist eine Zusammenfassung, keine Quelle für Antworten.
- In der App lässt sich die Ablage in der Seitenleiste abschalten. `python ablage.py` zeigt den aktuellen Stand. Der Testlauf legt nichts ab.
- Tests ohne Ollama: `python evaluation/test_ablage.py` und `python evaluation/test_steckbrief.py`

## Evaluation
```bash
python evaluation/evaluate.py            # Quellen-Trefferquote (schnell)
python evaluation/evaluate.py --antwort  # inkl. Antwortzeit
```
In [evaluation/testfragen.json](evaluation/testfragen.json) für jede Frage `manuell_sek` eintragen, also die selbst gestoppte Zeit für die manuelle Suche in OneNote/Outlook/Teams. Das Skript berechnet dann die Zeitersparnis und schreibt eine Tabelle nach `evaluation/ergebnisse.md`.

## Automatischer Testlauf (Regelprüfung + KI-Gutachter)
```bash
python evaluation/testlauf.py                 # alle Fragen beantworten und prüfen (~25 min)
python evaluation/testlauf.py --nur-gutachter # nur erneut prüfen, setzt nach Abbruch fort
python evaluation/testlauf.py --kategorie Rückbezug --ohne-gutachter  # schneller Zwischentest
```
[evaluation/testkatalog.json](evaluation/testkatalog.json) enthält 60 Fragen in 11 Kategorien: Fakten, alte Daten, Widersprüche, Zeitfragen, Zusammenfassungen, Formulierungsvarianten (Kleinschreibung, Tippfehler, Englisch), **Rückbezüge** (Dialoge mit 2–3 Fragen, die Vorfragen werden echt durchgespielt), **Umschreibungen** (Umgangssprache, indirekte Bezeichnungen wie „die Feuerbacher“), unbeantwortbare Fragen und Fangfragen. Zu jeder Frage gibt es eine Sollantwort, Pflichtfakten und erwartete Quellen. Jede Antwort wird zweifach geprüft:

1. **Regelprüfung (Code):** Sind die Pflichtfakten enthalten? Wurden die erwarteten Quellen gefunden? Zeigen die `[n]`-Verweise auf existierende Quellen? Ist das Ausgabeformat eingehalten? Wurden Widersprüche erkannt? Wurde bei unbeantwortbaren Fragen nichts erfunden?
2. **KI-Gutachter:** Ein zweites, größeres Modell (`qwen2.5:14b`) vergleicht die Antwort mit Sollantwort und Quelltexten und bewertet Korrektheit, Vollständigkeit und Halluzinationen mit Noten von 1 bis 5.

Agent und Gutachter laufen nacheinander, nie gleichzeitig. Zwei große Modelle zusammen überlasten 8 GB VRAM + 16 GB RAM, das hat im Test einen PC-Absturz verursacht. Ein 7B-Gutachter ist als Ersatz möglich, bewertet das 7B-Agentenmodell aber unzuverlässig.

**Verlauf der Verbesserungen** (Ergebnisse in `evaluation/testlauf_bericht.md`):

| Stand | Regelprüfung | Wichtigste Änderung |
|---|---|---|
| 1. Lauf | 30/46 bestanden (gesamt) | – |
| nach Fix 1 | 43/46 | hybride Suche (Embeddings + Stichwörter/Namen), Gegenprüfung von Widersprüchen |
| nach Fix 2 | 46/46 | Inhaltsverzeichnis der Ablage, Ablageort im Quellenkopf, zweistufige Widerspruchsprüfung |

## Demo-Ablauf
Die Demo-Daten enthalten drei fiktive Kunden (Hoffmann Maschinenbau, NordWerk Logistik, Brenner Medizintechnik) mit Daten von 2019 bis 2026.

| # | Frage | Zeigt |
|---|---|---|
| 1 | „Welche Konditionen gelten im Rahmenvertrag mit Hoffmann Maschinenbau und bis wann läuft er?“ | Zusammenführung OneNote + Mail, **Widerspruch** (31.03.2027 laut OneNote, 30.06.2027 laut neuerer Mail) |
| 2 | „Was haben wir 2019 mit NordWerk im Projekt Billbrook vereinbart?“ | **alte Daten** (OneNote 2019 + archivierte .eml) |
| 3 | „Wann findet die Bedarfsanalyse Hannover mit NordWerk statt?“ | Widerspruch OneNote (18.11.) vs. Mail/Teams (20.11.) |
| 4 | „Welche Termine habe ich nächste Woche?“ / „Was steht nächste Woche bei Hoffmann an?“ | Zeitfragen über den Kalender, vollständige Terminliste |
| 5 | „Welche Konditionen haben wir mit Siemens Energy vereinbart?“ | **keine Quelle → keine Halluzination** |
| 6 | Evaluationstabelle | Trefferquote und Zeitersparnis |

Die Demo-Kalendertermine liegen relativ zum heutigen Tag (letzte, diese und nächste Woche). Vor der Präsentation deshalb einmal „Daten neu einlesen“ klicken oder `python ingest.py --source demo` ausführen.

## Projektstruktur
| Datei | Aufgabe |
|---|---|
| [config.py](config.py) | alle Einstellungen |
| [prompts.py](prompts.py) | System-Prompt (aus Copilot übernommen) und Ausgabevorlage |
| [graph_client.py](graph_client.py) | Login (Device Code) und Graph-Anfragen mit Paging |
| [connectors/](connectors) | OneNote, Outlook, Teams, Dateien → einheitliches Dokumentformat |
| [parsers.py](parsers.py) | Text aus HTML, .msg, .eml, .docx, .pdf |
| [local_loader.py](local_loader.py) | Demo-Daten im selben Format |
| [ingest.py](ingest.py) | Abschnitte bilden, Embeddings, Index |
| [agent.py](agent.py) | Suche, Antwort, Quellenliste |
| [ablage.py](ablage.py) | persönliche Ablage: Ordner je Kunde/Thema, wächst mit jeder Frage |
| [steckbrief.py](steckbrief.py) | Steckbrief je Vertrag (_Stand.md): aktueller Stand mit Quellen und Fristen |
| [app.py](app.py) | Streamlit-Oberfläche |
| [seed_graph.py](seed_graph.py) | Test-Tenant mit Demo-Daten befüllen |
| [evaluation/](evaluation) | Testfragen und Messung |

**Empfohlene Lesereihenfolge für den Code:** Jede Datei beginnt mit einem Kopfkommentar zu ihrer Rolle im System.
1. [config.py](config.py): alle Einstellungen und Schwellwerte
2. [ingest.py](ingest.py): wie der Suchindex entsteht (Offline-Teil)
3. [agent.py](agent.py): wie eine Frage beantwortet wird (Online-Teil, gegliedert in die Abschnitte A–F)
4. [prompts.py](prompts.py) und [verstehen.py](verstehen.py): die Anweisungen an das Sprachmodell
5. [zeitraum.py](zeitraum.py): Regeln für Zeitfragen
6. [app.py](app.py): die Oberfläche, die dieselben Schritte einzeln aufruft
7. Datenzugang: [local_loader.py](local_loader.py) (Demo), [graph_client.py](graph_client.py) und [connectors/](connectors) (Microsoft 365), [parsers.py](parsers.py)

## Mitarbeiten
Das Projekt liegt in einem privaten GitHub-Repository. Jeder arbeitet in seiner eigenen Kopie, der Code wird über Git zusammengeführt. Die Projektregeln für Claude Code stehen in [CLAUDE.md](CLAUDE.md).

**Einmalig einrichten** (PowerShell, Git und Ollama installiert):
```bash
git clone <Repository-URL> KI-Agent
cd KI-Agent
python -m venv "$env:USERPROFILE\.venvs\ki-agent"
& "$env:USERPROFILE\.venvs\ki-agent\Scripts\python.exe" -m pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull bge-m3
.\start_demo.bat
```
Den Klon nicht in einen OneDrive-Ordner legen, z. B. `C:\Projekte\KI-Agent`. OneDrive-Synchronisation und Git stören sich gegenseitig.

**Arbeitsweise:**
- Ein Branch pro Thema, z. B. `git switch -c max/desktop-app`. Nicht direkt auf `main` arbeiten.
- Vor dem Start: `git switch main` und `git pull`, damit man auf dem neuesten Stand aufsetzt.
- Fertig: committen, pushen, Pull Request auf GitHub. Der andere schaut kurz drüber und führt zusammen.
- Größere Umbauten an `agent.py`, `prompts.py` oder `config.py` vorher absprechen, diese Dateien berührt fast jede Änderung.
- Vor dem Pull Request prüfen: `python -m ruff check .` (einmalig `pip install ruff`) und die Tests ohne Ollama in `evaluation/test_*.py`.
- Nicht im Repository: `.env`, Index (`data/`), Testergebnisse und Präsentationen (.pptx). Die Präsentationen liegen im geteilten OneDrive-/Teams-Ordner.

## Grenzen und Ausblick
- Die Qualität hängt vom 7B-Modell ab. Mit mehr VRAM liefert z. B. `qwen2.5:14b` bessere Zusammenfassungen (in der Seitenleiste umschaltbar).
- Neue Daten muss man aktuell per „Daten neu einlesen“ übernehmen. Möglich wäre ein automatischer Abgleich über Graph-Delta-Abfragen.
- Bilder und handschriftliche Notizen in OneNote werden nicht ausgewertet.
