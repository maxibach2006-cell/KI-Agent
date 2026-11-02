"""Persönliche Ablage: baut nach jeder Frage eine geordnete Ordnerstruktur auf dem Rechner des Nutzers auf.

Idee:
    Wer mehrmals zum selben Kunden, Projekt oder zur selben Verhandlung fragt, bekommt dafür automatisch
    einen Ordner mit allen bisherigen Antworten und den zugehörigen Quellen. Die Struktur wächst mit jeder Frage.

    KAM-Ablage/<nutzer>/
    ├─ _Uebersicht.md                       ← alle Kunden und Themen (vom Code erzeugt)
    ├─ Firma X/
    │  ├─ _Uebersicht.md                    ← alle Fragen zu diesem Kunden, chronologisch
    │  ├─ _Allgemein/                       ← Fragen, deren Thema (noch) keinen eigenen Ordner hat
    │  └─ Rahmenvertrag RV-1/
    │     ├─ 2026-11-02_0930_Welche Konditionen gelten.md   ← Frage, Antwort, Quellenliste
    │     └─ Quellen/                       ← Kopien bzw. Auszüge der gefundenen Quellen
    └─ _register.json                       ← Gedächtnis der Ablage (nicht von Hand ändern)

Ablauf von ablegen():
    1. _analysiere()     Das Sprachmodell BESCHREIBT, worum es geht: Kunde + Thema (JSON).
    2. _kunde_zuordnen() Der CODE entscheidet, ob es ein bekannter Kunde ist (Namensvergleich, nicht das Modell;
                         siehe CLAUDE.md: Ja/Nein-Urteile des 7B-Modells sind unzuverlässig).
    3. _thema_zuordnen() Der CODE entscheidet, ob es ein bekanntes Thema ist: gleiche Kennwörter (z. B. Vertrags-
                         nummer, Projektname) oder Embedding-Ähnlichkeit (bge-m3) über ABLAGE_THEMA_SCHWELLE.
    4. Eintrag im Register vermerken. Ordner entstehen erst ab ABLAGE_MIN_FRAGEN Fragen:
         - Kundenordner, sobald zum Kunden genug Fragen vorliegen (einzelne Themen liegen dann in _Allgemein),
         - Themenordner, sobald zum Thema genug Fragen vorliegen (frühere Einträge ziehen dorthin um).
       So entsteht kein Ordner-Wildwuchs durch einmalige Fragen.
    5. Dateien schreiben (Antwort + Quellen) und die Übersichten neu erzeugen.

Quellen im Ordner:
    - Lokale Dateien (Demo: demo_data/sharepoint/...) werden kopiert.
    - OneNote, Outlook, Teams, Kalender und Dateien aus Microsoft 365 liegen nicht als Datei vor: Dafür wird
      der gefundene Textauszug mit allen Metadaten gespeichert, bei Web-Links zusätzlich eine .url-Verknüpfung
      zum Original (Doppelklick öffnet SharePoint/OneDrive im Browser).

Nutzung:
    import ablage
    ergebnis = ablage.ablegen(frage, treffer, antwort_text, user="demo")
    print(ergebnis["meldung"])   # z. B. "Abgelegt in Firma X / Rahmenvertrag RV-1"

Fehler in der Ablage dürfen nie die Antwort verhindern: app.py und agent.py fangen sie ab.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import ollama

import config

ALLGEMEIN = "_Allgemein"            # Ordner für Fragen ohne (eigenen) Themenordner
OHNE_KUNDE = "_Ohne Kunde"          # Projekte/Verhandlungen, zu denen kein Kunde erkennbar ist
REGISTER = "_register.json"
UEBERSICHT = "_Uebersicht.md"

# Rechtsformen und Füllwörter spielen beim Namensvergleich keine Rolle ("Firma X GmbH" = "Firma X")
NAMENS_FUELLER = {"gmbh", "ag", "kg", "co", "se", "mbh", "ug", "ohg", "gbr", "und", "&", "der", "die", "das",
                  "firma", "kunde", "kunden", "group", "gruppe", "holding", "e.v", "ev", "inc", "ltd"}
# Wörter, die in fast jedem Thema vorkommen und deshalb kein Kennwort für "dasselbe Thema" sind
# und Oberbegriffe, die es bei jedem Kunden mehrfach geben kann ("Reklamation" A ≠ "Reklamation" B).
# Ob "Rahmenvertrag" und "Rahmenvertrag RV-1" dasselbe sind, entscheidet dann die Embedding-Ähnlichkeit.
THEMEN_FUELLER = {"projekt", "verhandlung", "vertrag", "thema", "allgemein", "angebot", "termin", "mit", "von",
                  "für", "zum", "zur", "und", "der", "die", "das", "den", "dem", "des", "ein", "eine", "neue", "neuer",
                  "neues", "kunde", "kunden", "rahmenvertrag", "reklamation", "preisverhandlung", "konditionen",
                  "lieferung", "lieferverzug", "bestellung", "jahresgespräch", "besuch", "audit", "messe", "preise"}

# Beispiele bewusst mit neutralen Namen (CLAUDE.md: keine Demo-Daten in Prompts, sonst kopiert das Modell sie)
ANALYSE_PROMPT = """Ordne eine Frage aus dem Key-Account-Management für eine Ordnerablage ein.
Gib an:
- "kunde": der Kunde (Firma), um den es geht, so wie er in Frage oder Quellen heißt. Leer, wenn keiner erkennbar
  ist oder es um mehrere Kunden gleichzeitig geht.
- "thema": das konkrete Projekt, die Verhandlung, der Vertrag, die Reklamation oder der Termin, um den es geht,
  in 2 bis 5 Wörtern. Nenne Vertragsnummern und Projektnamen, wenn vorhanden.
  Geht es allgemein um den Kunden (Ansprechpartner, Profil, Zusammenfassung), schreibe "Allgemein".
- "art": eines von "Projekt", "Verhandlung", "Vertrag", "Reklamation", "Termin", "Allgemein".
Gibt es schon passende Themen in der Liste "Bekannte Themen" und geht es um dieselbe Sache, übernimm den Namen
genau. Erfinde nichts, was nicht in Frage oder Quellen steht. Antworte nur mit JSON
{"kunde": "...", "thema": "...", "art": "..."}.

Beispiele:
Frage: "Welchen Rabatt gibt der Rahmenvertrag RV-100 mit Firma X?" -> {"kunde": "Firma X", "thema": "Rahmenvertrag RV-100", "art": "Vertrag"}
Frage: "Wie ist der Stand der Preisverhandlung 2027 mit Firma Y?" -> {"kunde": "Firma Y", "thema": "Preisverhandlung 2027", "art": "Verhandlung"}
Frage: "Wer ist bei Firma X für den Einkauf zuständig?" -> {"kunde": "Firma X", "thema": "Allgemein", "art": "Allgemein"}
Frage: "Welche Termine habe ich nächste Woche?" -> {"kunde": "", "thema": "", "art": "Termin"}"""


# =============================================================================
# A. Hilfsfunktionen: Pfade, Namen, Register
# =============================================================================

def ablage_pfad(user: str) -> Path:
    """Wurzelordner der Ablage eines Nutzers. Wie beim Index (config.db_path) bekommt jeder Nutzer einen
    eigenen Ordner, damit Demo-Daten und echte Kundendaten nie gemischt werden."""
    safe = "".join(c if c.isalnum() else "_" for c in user.lower())
    return config.ABLAGE_DIR / safe


def ordnername(text: str, laenge: int = 60) -> str:
    """Gültiger Datei-/Ordnername unter Windows: verbotene Zeichen raus, Länge begrenzen.
    Beispiel: 'Konditionen: 8 %/Jahr?' -> 'Konditionen 8 %-Jahr'"""
    text = re.sub(r'[<>:"|?*\x00-\x1f]', "", text).replace("/", "-").replace("\\", "-")
    text = re.sub(r"\s+", " ", text).strip(" .")  # Windows erlaubt keinen Punkt/Leerraum am Ende
    return text[:laenge].strip(" .") or "Ohne Titel"


def _woerter(text: str, fueller: set[str]) -> set[str]:
    """Kennwörter eines Namens (klein, ohne Füllwörter). 'RV-2023-117' bleibt als ein Wort erhalten.
    Auch einzelne Zeichen zählen, damit 'Firma X' und 'Firma Y' verschieden bleiben."""
    return {w.strip(".-") for w in re.findall(r"[\wäöüß][\wäöüß.-]*", text.lower()) if w.strip(".-") not in fueller}


def _kommt_vor(name: str, text: str) -> bool:
    """Steht der Name (als ganze Wörter) im Text? Ein längeres Kennwort genügt ('Firma X GmbH' passt zu
    '... die X GmbH ...'); besteht der Name nur aus kurzen Wörtern, müssen alle vorkommen."""
    woerter = _woerter(name, NAMENS_FUELLER)
    gefunden = {w for w in woerter if re.search(rf"(?<![\wäöüß]){re.escape(w)}(?![\wäöüß])", text.lower())}
    return bool(woerter) and (any(len(w) >= 3 for w in gefunden) or gefunden == woerter)


def gleicher_kunde(a: str, b: str) -> bool:
    """Gleicher Kunde, wenn die Kennwörter des kürzeren Namens im längeren enthalten sind.
    'Firma X' = 'Firma X GmbH' = 'X'; 'Meier Bau' ≠ 'Meier Logistik'."""
    wa, wb = _woerter(a, NAMENS_FUELLER), _woerter(b, NAMENS_FUELLER)
    if not wa or not wb:
        return False
    kurz, lang = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return kurz <= lang


def _kennwoerter(thema: str) -> set[str]:
    """Wörter, die ein Thema eindeutig machen: Nummern (RV-100, 2027) und Eigennamen (Billbrook)."""
    return {w for w in _woerter(thema, THEMEN_FUELLER) if any(c.isdigit() for c in w) or len(w) >= 5}



def lade_register(wurzel: Path) -> dict:
    """Register = Gedächtnis der Ablage. Enthält alle Kunden, Themen und Einträge.
    Auch Einträge, für die noch kein Ordner existiert (erste Frage), damit sie beim Anlegen nachgetragen werden."""
    datei = wurzel / REGISTER
    if datei.exists():
        return json.loads(datei.read_text(encoding="utf-8"))
    return {"kunden": []}


def speichere_register(wurzel: Path, register: dict) -> None:
    wurzel.mkdir(parents=True, exist_ok=True)
    tmp = wurzel / (REGISTER + ".tmp")  # erst vollständig schreiben, dann ersetzen -> nie halb geschrieben
    tmp.write_text(json.dumps(register, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(wurzel / REGISTER)


# =============================================================================
# B. Einordnen: Modell beschreibt, Code entscheidet
# =============================================================================

def _quellen_kurz(treffer: list[dict], anzahl: int = 4) -> str:
    """Titel und Ablageort der besten Quellen. Hilft dem Modell, den vollständigen Kundennamen und
    Vertragsnummern zu finden, ohne den ganzen Quelltext lesen zu müssen (schnell, wenig Kontext)."""
    return "\n".join(f"- {t['meta']['quelle']}: {t['meta']['titel']} (Ablage: {t['meta']['ort']})"
                     for t in treffer[:anzahl] if t["meta"]["quelle"] != "Übersicht")


def _analysiere(frage: str, treffer: list[dict], bekannte_themen: list[str], model: str) -> dict:
    """Schritt 1: Das Modell beschreibt Kunde, Thema und Art als JSON. Kaputtes JSON -> leeres Ergebnis."""
    inhalt = (f"Frage: {frage}\n\nGefundene Quellen:\n{_quellen_kurz(treffer) or '- keine'}\n\n"
              f"Bekannte Themen: {', '.join(bekannte_themen) or 'keine'}")
    antwort = ollama.chat(model=model, format="json", keep_alive=config.KEEP_ALIVE,
                          options={"temperature": 0, "num_ctx": config.NUM_CTX},
                          messages=[{"role": "system", "content": ANALYSE_PROMPT},
                                    {"role": "user", "content": inhalt}])
    try:
        daten = json.loads(antwort.message.content)
    except (json.JSONDecodeError, AttributeError):
        return {"kunde": "", "thema": "", "art": ""}
    return {k: str(daten.get(k) or "").strip() for k in ("kunde", "thema", "art")}


def _vektor(text: str) -> list[float]:
    """Bedeutungsvektor eines Themas (dasselbe Embedding-Modell wie die Suche, ist ohnehin geladen)."""
    return list(ollama.embed(model=config.EMBED_MODEL, input=[text]).embeddings[0])


def _kosinus(a: list[float], b: list[float]) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _kunden_aus_quellen(treffer: list[dict]) -> list[str]:
    """Kundennamen, wie sie in der Ablage heißen: letzter Teil des Ablageorts von OneNote, Teams und Dateien,
    z. B. 'MBS 2 / Firma X GmbH' -> 'Firma X GmbH'. Diese Namen sind verlässlicher als die Schreibweise des Modells."""
    namen = []
    for t in treffer:
        meta = t["meta"]
        if meta["quelle"] in ("OneNote", "Teams", "Datei"):
            name = re.split(r"\s*[/>]\s*", meta["ort"])[-1].strip()
            if name and name.lower() != "allgemein" and name not in namen:
                namen.append(name)
    return namen


def _kunde_zuordnen(kunde: str, frage: str, treffer: list[dict], register: dict) -> str:
    """Schritt 2: endgültiger Kundenname oder "" (keiner erkennbar).

    Schutz vor Halluzination: Der Name muss in der Frage oder in den Quellen vorkommen.
    Bekannte Kunden behalten ihren Namen (gleicher Ordner); sonst wird die Schreibweise aus der Ablage übernommen.
    """
    if not kunde or kunde.lower() in ("allgemein", "keiner", "unbekannt", "mehrere"):
        return ""
    belegt = frage + "\n" + "\n".join(t["text"] + " " + t["meta"]["ort"] for t in treffer)
    if not _kommt_vor(kunde, belegt):
        return ""  # Modell hat einen Namen erfunden
    for k in register["kunden"]:
        if gleicher_kunde(kunde, k["name"]):
            return k["name"]
    for name in _kunden_aus_quellen(treffer):
        if gleicher_kunde(kunde, name):
            return name
    return kunde


def _thema_zuordnen(thema: str, kunde_eintrag: dict, vektor: list[float]) -> dict | None:
    """Schritt 3: vorhandenes Thema dieses Kunden oder None (neues Thema). vektor = _vektor(Kunde: Thema).

    Gleich, wenn (a) der Name gleich ist, (b) beide dasselbe Kennwort enthalten (Vertragsnummer, Projektname)
    oder (c) die Bedeutung per Embedding ähnlich genug ist. Bei (b) gilt: verschiedene Nummern -> verschiedene
    Themen ('Rahmenvertrag RV-1' ≠ 'Rahmenvertrag RV-2'), auch wenn die Bedeutung fast gleich ist.
    """
    kennung = _kennwoerter(thema)
    nummern = {w for w in kennung if any(c.isdigit() for c in w)}
    for t in kunde_eintrag["themen"]:
        if t["name"].lower() == thema.lower():
            return t
    for t in kunde_eintrag["themen"]:
        andere = _kennwoerter(t["name"])
        andere_nummern = {w for w in andere if any(c.isdigit() for c in w)}
        if nummern and andere_nummern and not (nummern & andere_nummern):
            continue  # unterschiedliche Nummern -> sicher verschieden
        if kennung & andere:
            return t
    beste, bester_wert = None, config.ABLAGE_THEMA_SCHWELLE
    for t in kunde_eintrag["themen"]:
        andere_nummern = {w for w in _kennwoerter(t["name"]) if any(c.isdigit() for c in w)}
        if nummern and andere_nummern and not (nummern & andere_nummern):
            continue
        wert = _kosinus(vektor, t["vektor"]) if t.get("vektor") else 0.0
        if wert >= bester_wert:
            beste, bester_wert = t, wert
    return beste


def einordnen(frage: str, treffer: list[dict], register: dict, model: str = config.CHAT_MODEL) -> dict | None:
    """Schritte 1-3: {"kunde", "thema", "art", "vektor", "kunde_neu": bool, "thema_neu": bool} oder None,
    wenn weder Kunde noch konkretes Thema erkennbar sind (z. B. "Welche Termine habe ich nächste Woche?")."""
    alle_themen = [f"{t['name']} ({k['name']})" for k in register["kunden"] for t in k["themen"]]
    analyse = _analysiere(frage, treffer, alle_themen, model)
    kunde = _kunde_zuordnen(analyse["kunde"], frage, treffer, register)
    thema = analyse["thema"]
    if thema.lower() in ("", "allgemein", "keins", "kein thema"):
        thema = ""
    if not kunde and not thema:
        return None
    kunde = kunde or OHNE_KUNDE
    kunde_eintrag = next((k for k in register["kunden"] if k["name"] == kunde), None)
    vektor = _vektor(f"{kunde}: {thema}") if thema else None
    vorhanden = _thema_zuordnen(thema, kunde_eintrag, vektor) if thema and kunde_eintrag else None
    return {"kunde": kunde, "thema": vorhanden["name"] if vorhanden else thema, "art": analyse["art"], "vektor": vektor,
            "kunde_neu": kunde_eintrag is None, "thema_neu": bool(thema) and vorhanden is None}


# =============================================================================
# C. Dateien schreiben: Antwort, Quellen, Übersichten
# =============================================================================

def _quellen_ablegen(ziel: Path, treffer: list[dict]) -> list[str]:
    """Kopiert lokale Quelldateien bzw. speichert Textauszüge nach ziel/Quellen. Rückgabe: Dateinamen.
    Gleiche Quelle in mehreren Fragen -> nur einmal gespeichert, Auszüge werden ergänzt."""
    ordner = ziel / "Quellen"
    namen = []
    for t in treffer:
        meta = t["meta"]
        if meta["quelle"] == "Übersicht":
            continue  # automatisch erzeugtes Inhaltsverzeichnis, keine echte Quelle
        ordner.mkdir(parents=True, exist_ok=True)
        # Lokaler Pfad = Link ohne Schema wie "http:", "onenote:", "outlook:" (Demo: demo_data/sharepoint/...)
        ist_pfad = meta["link"] and not re.match(r"^[a-z]{2,}:", meta["link"])
        lokal = config.BASE_DIR / meta["link"] if ist_pfad else None
        if lokal and lokal.is_file():
            # Demo-Dateien (und künftig lokal synchronisierte Dateien): Original kopieren
            datei = ordner / lokal.name
            if not datei.exists():
                shutil.copy2(lokal, datei)
        else:
            datei = ordner / (ordnername(f"{meta['datum'][:10]} {meta['quelle']} - {meta['titel']}") + ".md")
            auszug = t["text"].split("\n", 1)[-1].strip()  # erste Zeile ist die Kopfzeile aus ingest.kopfzeile()
            if not datei.exists():
                kopf = [f"# {meta['titel']}", "", f"- **Quelle:** {meta['quelle']}", f"- **Ablage:** {meta['ort']}",
                        f"- **Datum:** {meta['datum']}"]
                if meta.get("absender"):
                    kopf.append(f"- **Von:** {meta['absender']}")
                kopf += [f"- **Original:** {meta['link']}", "", "## Gefundene Auszüge", ""]
                datei.write_text("\n".join(kopf) + "\n", encoding="utf-8")
            vorhanden = datei.read_text(encoding="utf-8")
            if auszug not in vorhanden:
                datei.write_text(vorhanden + "\n" + auszug + "\n\n---\n", encoding="utf-8")
            if meta["link"].startswith("http"):
                # Windows-Verknüpfung: Doppelklick öffnet das Original (SharePoint, OneDrive, Outlook im Web)
                (datei.with_suffix(".url")).write_text(f"[InternetShortcut]\nURL={meta['link']}\n", encoding="utf-8")
        if datei.name not in namen:
            namen.append(datei.name)
    return namen


def _eintrag_schreiben(ziel: Path, eintrag: dict) -> str:
    """Schreibt eine Frage mit Antwort als Markdown-Datei. Rückgabe: Dateiname."""
    ziel.mkdir(parents=True, exist_ok=True)
    zeit = datetime.fromisoformat(eintrag["zeit"])
    name = ordnername(f"{zeit:%Y-%m-%d_%H%M} {eintrag['frage']}", 80) + ".md"
    nr = 2
    while (ziel / name).exists():  # gleiche Frage in derselben Minute -> nicht überschreiben
        name = ordnername(f"{zeit:%Y-%m-%d_%H%M} {eintrag['frage']}", 76) + f" ({nr}).md"
        nr += 1
    quellen = _quellen_ablegen(ziel, eintrag["treffer"])
    text = [f"# {eintrag['frage']}", "", f"- **Gefragt am:** {zeit:%d.%m.%Y %H:%M}"]
    if eintrag.get("verstanden_als") and eintrag["verstanden_als"] != eintrag["frage"]:
        text.append(f"- **Verstanden als:** {eintrag['verstanden_als']}")
    text += [f"- **Kunde:** {eintrag['kunde']}", f"- **Thema:** {eintrag['thema'] or 'Allgemein'}", "",
             "## Antwort", "", eintrag["antwort"].strip(), ""]
    if quellen:
        text += ["## Abgelegte Quellen", ""] + [f"- [{q}](Quellen/{q.replace(' ', '%20')})" for q in quellen]
    (ziel / name).write_text("\n".join(text) + "\n", encoding="utf-8")
    return name


def _ordner_von(wurzel: Path, kunde: dict, thema: dict | None) -> Path:
    """Zielordner eines Eintrags nach den Regeln aus dem Modulkopf."""
    basis = wurzel / ordnername(kunde["name"])
    if thema and thema["ordner"]:
        return basis / ordnername(thema["name"])
    return basis / ALLGEMEIN


def _uebersichten_schreiben(wurzel: Path, register: dict) -> None:
    """Übersichten erzeugt der Code aus dem Register (vollständig und immer aktuell, kein Modell beteiligt)."""
    gesamt = ["# Meine Ablage", "", f"Automatisch gepflegt vom Informations-Agenten. Stand: {datetime.now():%d.%m.%Y %H:%M}",
              "", "| Kunde | Themen mit Ordner | Fragen | Zuletzt |", "|---|---|---|---|"]
    for k in sorted(register["kunden"], key=lambda k: k["name"].lower()):
        eintraege = [e for t in k["themen"] for e in t["eintraege"]] + k["allgemein"]
        if not k["ordner"]:
            continue
        zuletzt = max(e["zeit"] for e in eintraege)[:10]
        mit_ordner = [t["name"] for t in k["themen"] if t["ordner"]]
        link = ordnername(k["name"]).replace(" ", "%20")
        gesamt.append(f"| [{k['name']}]({link}/{UEBERSICHT}) | {', '.join(mit_ordner) or '–'} | "
                      f"{len(eintraege)} | {zuletzt} |")

        zeilen = [f"# {k['name']}", ""]
        for t in sorted(k["themen"], key=lambda t: t["name"].lower()):
            if not t["ordner"]:
                continue
            zeilen += [f"## {t['name']}" + (f" ({t['art']})" if t.get("art") else ""), ""]
            zeilen += [f"- {e['zeit'][:10]}: [{e['frage']}]({ordnername(t['name']).replace(' ', '%20')}/"
                       f"{e['datei'].replace(' ', '%20')})" for e in sorted(t["eintraege"], key=lambda e: e["zeit"])]
            zeilen.append("")
        lose = sorted(k["allgemein"] + [e for t in k["themen"] if not t["ordner"] for e in t["eintraege"]],
                      key=lambda e: e["zeit"])
        if lose:
            zeilen += ["## Allgemein", ""]
            zeilen += [f"- {e['zeit'][:10]}: [{e['frage']}]({ALLGEMEIN}/{e['datei'].replace(' ', '%20')})"
                       + (f" – Thema: {e['thema']}" if e["thema"] else "") for e in lose]
        (wurzel / ordnername(k["name"]) / UEBERSICHT).write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    (wurzel / UEBERSICHT).write_text("\n".join(gesamt) + "\n", encoding="utf-8")


def _verschieben(alt: Path, neu: Path, eintraege: list[dict]) -> None:
    """Einträge (und ihre Quellen) aus _Allgemein in einen neuen Themenordner umziehen."""
    for e in eintraege:
        if e.get("datei") and (alt / e["datei"]).exists():
            neu.mkdir(parents=True, exist_ok=True)
            (alt / e["datei"]).replace(neu / e["datei"])
        _quellen_ablegen(neu, e["treffer"])  # Quellen im neuen Ordner (in _Allgemein bleiben sie für andere Fragen)


# =============================================================================
# D. Gesamtablauf
# =============================================================================

def ablegen(frage: str, treffer: list[dict], antwort: str, user: str = "demo", model: str = config.CHAT_MODEL,
            verstanden_als: str | None = None) -> dict:
    """Ordnet eine beantwortete Frage ein und legt sie ab.

    Parameter:
        frage:          die Frage, wie der Nutzer sie gestellt hat
        treffer:        Treffer der Suche (agent.suche_verstanden)
        antwort:        vollständiger Antworttext inkl. Anhang (Widersprüche, Quellen)
        verstanden_als: eigenständige Fassung der Frage (verstehen.umschreiben); wird zum Einordnen genutzt
    Rückgabe: {"status": "abgelegt"|"vorgemerkt"|"übersprungen", "kunde", "thema", "ordner", "meldung"}
    """
    if not treffer:
        return {"status": "übersprungen", "kunde": "", "thema": "", "ordner": None,
                "meldung": "Nicht abgelegt: keine Quellen gefunden."}
    wurzel = ablage_pfad(user)
    register = lade_register(wurzel)
    einordnung = einordnen(verstanden_als or frage, treffer, register, model)
    if not einordnung:
        return {"status": "übersprungen", "kunde": "", "thema": "", "ordner": None,
                "meldung": "Nicht abgelegt: kein Kunde und kein Projekt erkennbar."}

    # --- Schritt 4: Register aktualisieren ---
    kunde = next((k for k in register["kunden"] if k["name"] == einordnung["kunde"]), None)
    if kunde is None:
        kunde = {"name": einordnung["kunde"], "ordner": False, "themen": [], "allgemein": []}
        register["kunden"].append(kunde)
    thema = None
    if einordnung["thema"]:
        thema = next((t for t in kunde["themen"] if t["name"] == einordnung["thema"]), None)
        if thema is None:
            thema = {"name": einordnung["thema"], "art": einordnung["art"], "ordner": False, "eintraege": [],
                     "vektor": einordnung["vektor"]}
            kunde["themen"].append(thema)
    eintrag = {"zeit": datetime.now().isoformat(timespec="seconds"), "frage": frage, "verstanden_als": verstanden_als,
               "kunde": kunde["name"], "thema": thema["name"] if thema else "", "antwort": antwort, "datei": None,
               "treffer": [{"text": t["text"], "meta": t["meta"]} for t in treffer]}
    (thema["eintraege"] if thema else kunde["allgemein"]).append(eintrag)

    # --- Schritt 5: Ordner anlegen, sobald genug Fragen vorliegen, dann Dateien schreiben ---
    alle = kunde["allgemein"] + [e for t in kunde["themen"] for e in t["eintraege"]]
    neu_kunde = not kunde["ordner"] and len(alle) >= config.ABLAGE_MIN_FRAGEN
    neu_thema = thema is not None and not thema["ordner"] and len(thema["eintraege"]) >= config.ABLAGE_MIN_FRAGEN
    if neu_kunde:
        kunde["ordner"] = True
    if neu_thema:
        thema["ordner"] = True
        if not neu_kunde:  # bisherige Einträge lagen schon in _Allgemein -> umziehen
            _verschieben(wurzel / ordnername(kunde["name"]) / ALLGEMEIN, _ordner_von(wurzel, kunde, thema),
                         [e for e in thema["eintraege"] if e is not eintrag])
    if kunde["ordner"]:
        # Beim ersten Anlegen auch die früheren (vorgemerkten) Einträge nachtragen
        for t in [None] + kunde["themen"]:
            liste = kunde["allgemein"] if t is None else t["eintraege"]
            for e in liste:
                if e["datei"] is None:
                    e["datei"] = _eintrag_schreiben(_ordner_von(wurzel, kunde, t), e)
        _uebersichten_schreiben(wurzel, register)
    speichere_register(wurzel, register)

    if not kunde["ordner"]:
        return {"status": "vorgemerkt", "kunde": kunde["name"], "thema": eintrag["thema"], "ordner": None,
                "meldung": f"Vorgemerkt für {kunde['name']}: Der Ordner entsteht ab der "
                           f"{config.ABLAGE_MIN_FRAGEN}. Frage zu diesem Kunden."}
    ordner = _ordner_von(wurzel, kunde, thema)
    pfad = ordner.relative_to(wurzel)
    neu = " (neu angelegt)" if neu_kunde or neu_thema else ""
    return {"status": "abgelegt", "kunde": kunde["name"], "thema": eintrag["thema"], "ordner": ordner,
            "meldung": f"Abgelegt in {' / '.join(pfad.parts)}{neu}"}


if __name__ == "__main__":
    # Übersicht der Ablage per Kommandozeile: python ablage.py [nutzer]
    import sys
    wurzel = ablage_pfad(sys.argv[1] if len(sys.argv) > 1 else "demo")
    print(f"Ablage: {wurzel}")
    for k in lade_register(wurzel)["kunden"]:
        anzahl = len(k["allgemein"]) + sum(len(t["eintraege"]) for t in k["themen"])
        print(f"- {k['name']}: {anzahl} Fragen{'' if k['ordner'] else ' (noch kein Ordner)'}")
        for t in k["themen"]:
            print(f"    · {t['name']}: {len(t['eintraege'])}{'' if t['ordner'] else ' (vorgemerkt)'}")
