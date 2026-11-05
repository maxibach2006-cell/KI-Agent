"""Steckbrief je Thema: der aktuelle Stand eines Vertrags, der mit jeder Frage dazu wächst.

Rolle im System:
    ablage.py legt Fragen und Antworten in Ordnern je Kunde/Thema ab. Für Verträge führt dieses Modul zusätzlich
    einen Steckbrief (_Stand.md im Themenordner): Laufzeit, Rabatt, Zahlungsziel, Kündigungsfrist … jeweils mit
    Wert, Quelle und Datum der Quelle. So sieht man den Stand auf einen Blick, statt alle Antworten zu lesen.

Ablauf von aktualisiere() – wie bei den Widersprüchen gilt: Das Modell beschreibt, der Code entscheidet.
    1. extrahiere()      Das Modell liest die Antwort und nennt Feld, Wert und Quellennummer [n] (JSON).
    2. belege()          Der CODE prüft jeden Wert gegen die Originalquelle: Alle Zahlen/Daten (bzw. Wörter) des Werts
                         müssen in EINER Zeile der Quelle stehen, und diese Zeile muss ein Schlüsselwort des Felds
                         enthalten ("Zahlungsziel" -> zahlung, netto, skonto …). Sonst wird der Wert verworfen.
                         Das verhindert erfundene Werte und Werte im falschen Feld (z. B. Rabatt als Zahlungsziel).
    3. zusammenfuehren() Der CODE gleicht mit dem bisherigen Stand ab. Entscheidend ist das Datum der QUELLE,
                         nicht der Zeitpunkt der Frage: Neuere Quelle ersetzt den Wert (alter Wert -> "Änderungen"),
                         ältere Quelle ändert nichts, gleich alte Quelle mit anderem Wert -> Widerspruch (⚠️).
    4. markdown()        Der CODE erzeugt _Stand.md mit Fristen. Jede Quelle ist mit ihrer abgelegten Kopie im
                         Ordner Quellen/ verlinkt (ablage.py speichert sie dort).

Wichtig: Der Steckbrief ist eine Zusammenfassung, KEINE Quelle. Er wird nicht eingelesen und belegt nie eine Antwort,
sonst würde der Agent eigene Fehler verstärken. Belegt wird immer mit den Originalquellen.

Datenformat (liegt im Register der Ablage unter thema["stand"]):
    {"felder": {"Rabatt": {"wert": "8 %", "quelle": {"text", "meta"}, "seit": "2026-11-03T09:30:00",
                           "weitere": [quelle, ...], "widerspruch": [{"wert", "quelle"}, ...]}},
     "aenderungen": [{"feld", "alt", "neu", "quelle", "zeit"}]}
"""
import calendar
import json
import re
from datetime import date

import ollama

import config
from zeitraum import daten_im_text

# Felder eines Vertrags und Schlüsselwörter, von denen mindestens eines in der belegenden Zeile stehen muss.
FELDER_VERTRAG = {
    "Vertragsnummer": ["vertrag", "nr", "nummer"],
    "Laufzeit": ["laufzeit", "läuft", "gültig", "vertragsbeginn", "vertragsende"],
    "Rabatt": ["rabatt", "nachlass", "bonus"],
    "Zahlungsziel": ["zahlung", "netto", "skonto"],
    "Kündigungsfrist": ["kündig"],
    "Preisanpassung": ["preisgleit", "preisanpassung", "preiserhöhung"],
    "Ansprechpartner": ["unterzeichnet", "ansprechpartner", "zuständig", "einkauf", "leiter", "leiterin"],
}

# Beispiele mit neutralen Namen (CLAUDE.md: keine Demo-Daten in Prompts)
EXTRAKTION_PROMPT = """Du bekommst eine Antwort zu einem Vertrag. Die Zahlen in eckigen Klammern [n] sind Quellennummern.
Übernimm jede Angabe zu diesen Feldern: {felder}.
Regeln:
- "wert": die Angabe möglichst wörtlich und kurz, mit allen Zahlen und Daten, z. B. "45 Tage netto".
- "quelle": die Quellennummer, die in der Antwort an dieser Angabe steht.
- Nur Angaben, die in der Antwort stehen. Fehlt ein Feld, lass es weg. Erfinde nichts.
Antworte nur mit JSON {{"felder": [{{"feld": "...", "wert": "...", "quelle": n}}]}}.

Beispiel:
Antwort: "Der Vertrag RV-100 mit Firma X läuft vom 01.01.2025 bis 31.12.2027 [1]. Firma X erhält 5 % Rabatt [2]."
-> {{"felder": [{{"feld": "Vertragsnummer", "wert": "RV-100", "quelle": 1}},
               {{"feld": "Laufzeit", "wert": "01.01.2025 bis 31.12.2027", "quelle": 1}},
               {{"feld": "Rabatt", "wert": "5 %", "quelle": 2}}]}}"""

FUELLWOERTER = {"und", "der", "die", "das", "von", "vom", "bis", "auf", "für", "mit", "bei", "zum", "zur", "alle",
                "eine", "einer", "ein", "den", "dem", "des", "frau", "herr"}


def leer() -> dict:
    return {"felder": {}, "aenderungen": []}


def ist_vertrag(thema: dict) -> bool:
    """Steckbriefe gibt es vorerst nur für Verträge (klare Felder). Erkennbar an der Art oder am Namen."""
    return thema.get("art", "").lower() == "vertrag" or "vertrag" in thema["name"].lower()


# =============================================================================
# 1. Extraktion (Sprachmodell)
# =============================================================================

def _antwort_ohne_anhang(antwort: str) -> str:
    """Nur den vom Modell geschriebenen Teil: Terminliste, Widersprüche und Quellenliste erzeugt der Code."""
    return re.split(r"\n#+ (?:Termine im Zeitraum|Widersprüche|Quellen)\b", antwort)[0].strip()


def extrahiere(antwort: str, model: str = config.CHAT_MODEL) -> list[dict]:
    """Schritt 1: [{"feld", "wert", "quelle"}] aus der Antwort. Kaputtes JSON -> leere Liste (Schritt entfällt)."""
    prompt = EXTRAKTION_PROMPT.format(felder=", ".join(FELDER_VERTRAG))
    ergebnis = ollama.chat(model=model, format="json", keep_alive=config.KEEP_ALIVE,
                           options={"temperature": 0, "num_ctx": config.NUM_CTX},
                           messages=[{"role": "system", "content": prompt},
                                     {"role": "user", "content": "Antwort:\n" + _antwort_ohne_anhang(antwort)}])
    try:
        felder = json.loads(ergebnis.message.content).get("felder", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [f for f in felder if isinstance(f, dict) and f.get("feld") in FELDER_VERTRAG and str(f.get("wert", "")).strip()]


# =============================================================================
# 2. Belegprüfung (Code)
# =============================================================================

def _kerne(text: str) -> set[str]:
    """Zahlen und Daten eines Textes, vereinheitlicht: '01.04.2023' -> '2023-04-01', '1,5' -> '1.5'."""
    daten = {d.isoformat() for d in daten_im_text(text)}
    ohne_daten = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b|\b\d{4}-\d{2}-\d{2}\b", " ", text)
    return daten | {z.replace(",", ".") for z in re.findall(r"\d+(?:[.,]\d+)?", ohne_daten)}


def _woerter(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]{3,}", text.lower()) if w not in FUELLWOERTER}


def _schluessel(wert: str) -> frozenset:
    """Vergleichsschlüssel: Zahlen/Daten, falls vorhanden, sonst die Wörter. '45 Tage' = '45 Tage netto'."""
    return frozenset(_kerne(wert) or _woerter(wert))


def _zeilen(text: str) -> list[str]:
    """Zeilen der Quelle ohne Kopfzeile; lange Absätze (Mails) zusätzlich in Sätze geteilt.
    Satzende nur nach einem Kleinbuchstaben-Wort, damit 'Dr. Wolff' oder '01.04.2023' nicht getrennt werden."""
    zeilen = []
    for zeile in text.split("\n")[1:]:
        zeilen += re.split(r"(?<=[a-zäöüß]{2}[.!?])\s+", zeile) if len(zeile) > 300 else [zeile]
    return [z for z in zeilen if z.strip()]


def belegzeile(feld: str, wert: str, text: str) -> str | None:
    """Zeile der Quelle, die den Wert belegt, oder None. Bedingungen siehe Modulkopf (Schritt 2)."""
    kerne, woerter = _kerne(wert), _woerter(wert)
    for zeile in _zeilen(text):
        klein = zeile.lower()
        if not any(s in klein for s in FELDER_VERTRAG[feld]):
            continue
        if kerne and kerne <= _kerne(zeile):
            return zeile.strip()
        if not kerne and woerter and woerter <= _woerter(zeile):
            return zeile.strip()
    return None


def belege(kandidaten: list[dict], treffer: list[dict]) -> list[dict]:
    """Schritt 2: nur belegte Werte, je Feld der erste. Bevorzugt die vom Modell genannte Quelle, sonst jede andere.
    Rückgabe: [{"feld", "wert", "quelle": {"text", "meta"}, "zeile"}]"""
    belegt = {}
    quellen = [t for t in treffer if t["meta"]["quelle"] != "Übersicht"]
    for k in kandidaten:
        feld, wert = k["feld"], str(k["wert"]).strip()
        if feld in belegt:
            continue
        try:
            genannt = [treffer[int(k.get("quelle")) - 1]]
        except (ValueError, TypeError, IndexError):
            genannt = []
        for t in genannt + quellen:
            if t["meta"]["quelle"] == "Übersicht":
                continue
            zeile = belegzeile(feld, wert, t["text"])
            if zeile:
                belegt[feld] = {"feld": feld, "wert": wert, "zeile": zeile,
                                "quelle": {"text": t["text"], "meta": t["meta"]}}
                break
    return list(belegt.values())


# =============================================================================
# 3. Zusammenführen mit dem bisherigen Stand (Code)
# =============================================================================

def _quelldatum(quelle: dict) -> str:
    return quelle["meta"].get("datum", "")[:10]


def _gleiche_quelle(a: dict, b: dict) -> bool:
    return a["meta"]["link"] == b["meta"]["link"] and a["meta"]["titel"] == b["meta"]["titel"]


def zusammenfuehren(stand: dict, belegte: list[dict], zeit: str) -> list[str]:
    """Schritt 3: Stand aktualisieren. Rückgabe: kurze Meldungen ('Rabatt neu', 'Zahlungsziel geändert')."""
    meldungen = []
    for b in belegte:
        feld, wert, quelle = b["feld"], b["wert"], b["quelle"]
        alt = stand["felder"].get(feld)
        if alt is None:
            stand["felder"][feld] = {"wert": wert, "quelle": quelle, "seit": zeit, "weitere": [], "widerspruch": []}
            meldungen.append(f"{feld} neu")
        elif _schluessel(wert) == _schluessel(alt["wert"]):
            # gleicher Wert: weitere Quelle merken (bestätigt den Wert)
            if not any(_gleiche_quelle(quelle, q) for q in [alt["quelle"]] + alt["weitere"]):
                alt["weitere"].append(quelle)
        elif _quelldatum(quelle) > _quelldatum(alt["quelle"]):
            # neuere Quelle: Wert ersetzen, alten Wert in die Änderungen
            stand["aenderungen"].append({"feld": feld, "alt": alt["wert"], "neu": wert, "quelle": quelle, "zeit": zeit})
            stand["felder"][feld] = {"wert": wert, "quelle": quelle, "seit": zeit, "weitere": [], "widerspruch": []}
            meldungen.append(f"{feld} geändert")
        elif _quelldatum(quelle) == _quelldatum(alt["quelle"]):
            # gleich alt, anderer Wert: nicht entscheidbar -> beide anzeigen
            if not any(_schluessel(w["wert"]) == _schluessel(wert) for w in alt["widerspruch"]):
                alt["widerspruch"].append({"wert": wert, "quelle": quelle})
                meldungen.append(f"{feld} widersprüchlich")
        # ältere Quelle mit anderem Wert: veraltet, Stand bleibt
    return meldungen


def aktualisiere(stand: dict, antwort: str, treffer: list[dict], model: str, zeit: str) -> list[str]:
    """Schritte 1-3 für eine neue Antwort. Rückgabe: Meldungen für die App."""
    return zusammenfuehren(stand, belege(extrahiere(antwort, model), treffer), zeit)


# =============================================================================
# 4. Fristen und Markdown (Code)
# =============================================================================

def _minus_monate(tag: date, monate: int) -> date:
    jahr, monat = divmod(tag.year * 12 + tag.month - 1 - monate, 12)
    return date(jahr, monat + 1, min(tag.day, calendar.monthrange(jahr, monat + 1)[1]))


def fristen(stand: dict, heute: date) -> list[tuple[date, str]]:
    """Kommende Daten aus den Feldern, dazu der letzte Kündigungstermin, falls berechenbar
    ('6 Monate zum Laufzeitende' + Laufzeitende). Ein verstrichener Kündigungstermin wird gezeigt,
    solange der Vertrag noch läuft – genau das will man wissen."""
    felder = stand["felder"]
    liste = []
    for feld, f in felder.items():
        for tag in daten_im_text(f["wert"]):
            if tag >= heute:
                liste.append((tag, f"{feld}: {f['wert']}"))
    laufzeit, kuendigung = felder.get("Laufzeit"), felder.get("Kündigungsfrist")
    if laufzeit and kuendigung and daten_im_text(laufzeit["wert"]):
        ende = max(daten_im_text(laufzeit["wert"]))
        monate = re.search(r"(\d+)\s*monat", kuendigung["wert"].lower())
        if monate and re.search(r"laufzeitende|vertragsende|zum ende", kuendigung["wert"].lower()) and ende >= heute:
            termin = _minus_monate(ende, int(monate[1]))
            liste.append((termin, "Letzter Kündigungstermin (berechnet aus Laufzeit und Kündigungsfrist)"
                          + (" – verstrichen" if termin < heute else "")))
    return sorted(liste)


def _datum_de(quelle: dict) -> str:
    """Datum der Quelle für die Anzeige: 2023-04-03 -> 03.04.2023."""
    iso = _quelldatum(quelle)
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else iso


def _quellenname(quelle: dict) -> str:
    m = quelle["meta"]
    return f"{m['quelle']} – {m['titel']}"


def markdown(titel: str, kunde: str, stand: dict, link_fuer, heute: date, anzahl_fragen: int) -> str:
    """Schritt 4: _Stand.md. link_fuer(quelle) speichert die Originalquelle in Quellen/ und liefert den
    relativen Link dorthin (kommt aus ablage.py, damit dieses Modul keine Dateien kennen muss)."""
    def verweis(q: dict) -> str:
        link = link_fuer(q)
        return f"[{_quellenname(q)}]({link.replace(' ', '%20')})" if link else _quellenname(q)

    felder = stand["felder"]
    quellen = {(q["meta"]["link"], q["meta"]["titel"]) for f in felder.values() for q in [f["quelle"]] + f["weitere"]}
    zeilen = [f"# {titel} – {kunde}", "",
              f"Stand: {heute:%d.%m.%Y} · aus {anzahl_fragen} Fragen · {len(quellen)} Quellen  ",
              "Automatisch gepflegt. Zusammenfassung, keine Quelle: Maßgeblich sind die verlinkten Originale.", "",
              "| Feld | Wert | Quelle | Quelle vom |", "|---|---|---|---|"]
    for feld in FELDER_VERTRAG:
        f = felder.get(feld)
        if f is None:
            zeilen.append(f"| {feld} | – (nicht belegt) | | |")
            continue
        weitere = f" (+{len(f['weitere'])} bestätigt)" if f["weitere"] else ""
        zeilen.append(f"| {feld} | {f['wert']} | {verweis(f['quelle'])}{weitere} | {_datum_de(f['quelle'])} |")
        for w in f["widerspruch"]:
            zeilen.append(f"| ⚠️ {feld} | {w['wert']} (widerspricht) | {verweis(w['quelle'])} | {_datum_de(w['quelle'])} |")
    for f in felder.values():  # weitere Belege ebenfalls als Kopie ablegen
        for q in f["weitere"]:
            link_fuer(q)

    termine = fristen(stand, heute)
    if termine:
        zeilen += ["", "## ⏰ Fristen"]
        for tag, text in termine:
            tage = (tag - heute).days
            abstand = f"in {tage} Tagen" if tage > 0 else ("heute" if tage == 0 else f"vor {-tage} Tagen")
            zeilen.append(f"- {tag:%d.%m.%Y} {text} ({abstand})")
    if stand["aenderungen"]:
        zeilen += ["", "## Änderungen"]
        for a in sorted(stand["aenderungen"], key=lambda a: _quelldatum(a["quelle"]), reverse=True):
            zeilen.append(f"- {_datum_de(a['quelle'])}: {a['feld']} „{a['alt']}“ → „{a['neu']}“ laut {verweis(a['quelle'])}")
    return "\n".join(zeilen) + "\n"
