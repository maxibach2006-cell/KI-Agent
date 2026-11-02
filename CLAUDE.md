# KAM-Informations-Agent – Projektregeln

Lokaler RAG-Agent (Ollama + ChromaDB + Streamlit) für das Key-Account-Management. Er beantwortet Fragen aus
OneNote „MBS 2“, Outlook, Kalender, Teams und Dateien, jede Aussage mit Quelle. Überblick: `README.md`.
Architektur, Entscheidungen und Irrwege: `docs/architektur_uebersicht.html`.

Zwei Personen arbeiten mit je eigenem Claude Code gleichzeitig an diesem Repository.

## Umgebung
- Python-Umgebung: `$env:USERPROFILE\.venvs\ki-agent` (bewusst außerhalb von OneDrive). Befehle immer mit
  `& "$env:USERPROFILE\.venvs\ki-agent\Scripts\python.exe" …` ausführen, sonst fehlen Pakete.
- In PowerShell vor Python-Ausgaben mit Umlauten: `$env:PYTHONIOENCODING="utf-8"`.
- Modelle: `qwen2.5:7b` (Agent), `bge-m3` (Embeddings), `qwen2.5:14b` (nur Gutachter im Testlauf).
- Demo-Index aufbauen: `python ingest.py --source demo`. Der Ordner `data/` ist lokal und nicht im Repository.

## Ressourcen (8 GB VRAM, 16 GB RAM)
- **Nie zwei große Modelle gleichzeitig laden.** 7B + 14B zusammen haben einen PC-Absturz verursacht.
- **Testlauf nie parallel zur laufenden App.** Beide konkurrieren um die GPU.
- Jeder `ollama.chat`-Aufruf nutzt `options={"num_ctx": config.NUM_CTX, …}`. Ein anderes Kontextfenster
  lässt Ollama das Modell neu laden (Antwortzeit 30–60 s statt 4–7 s).

## Tests
- Schnell, nur Regelprüfung: `python evaluation/testlauf.py --kategorie <Kategorie> --ohne-gutachter`
- Vollständig mit 14B-Gutachter (~30 min): `python evaluation/testlauf.py`; fortsetzen: `--nur-gutachter`
- Jede Änderung an Suche, Prompts oder Widerspruchsprüfung mit einem Testlauf belegen und das Ergebnis
  (vorher/nachher) in der PR-Beschreibung nennen.
- Neue Fähigkeiten bekommen Testfälle in `evaluation/testkatalog.json` (Frage, Pflichtfakten, Quellen, Sollantwort).

## Bekannte Fallen
- **Keine Beispiele aus den Demo-Daten in Prompts.** Das Modell kopiert sie in fremde Fragen, und die
  Testergebnisse sind dann geschönt (ist mit „die Hamburger“ passiert). Beispiele mit neutralen Namen wie „Firma X“.
- Das Ja/Nein-Urteil des 7B-Modells ist unzuverlässig. Besser: das Modell beschreiben lassen, der Code entscheidet.
- Quellenliste, Terminliste und Widersprüche erzeugt der Code aus den Metadaten, nicht das Modell.
- Streamlit lädt geänderte Module (`agent.py` …) nicht neu: nach Codeänderungen die App neu starten.

## Zusammenarbeit
- Nicht direkt auf `main` arbeiten. Ein Branch pro Thema (`max/…`, `<name>/…`), Zusammenführen per Pull Request.
- `agent.py`, `prompts.py` und `config.py` werden von fast allem berührt: größere Umbauten dort vorher absprechen.
- Code-Stil: deutsche Bezeichner und Kommentare, einfache Funktionen, keine Frameworks (z. B. LangChain) ohne Absprache.
- Keine echten Kunden- oder Personendaten committen. `demo_data/` ist fiktiv, `.env` und Token-Cache bleiben lokal.
- Wichtige Entscheidungen, verworfene Ideen und Irrwege in `docs/architektur_uebersicht.html` (Liste `TREE`) nachtragen.
