"""Wiederholte Fragen erkennen und ähnliche Fragen vorschlagen.

Problem:
    Stellte man dieselbe Frage im selben Gespräch ein zweites Mal, gab das Umschreiben von Folgefragen
    (verstehen.umschreiben) dem Modell die eigene, schon beantwortete Frage als Verlauf mit. Das kleine Modell
    machte daraus gelegentlich eine andere Frage, und die Suche fand nichts mehr.

Lösung (wie überall: der Code entscheidet, das Modell formuliert nur):
    1. finde_wiederholung() vergleicht die neue Frage im CODE mit den bisherigen Fragen des Gesprächs:
       gleich nach Vereinfachung (Groß-/Kleinschreibung, Satzzeichen, Füllwörter) oder fast gleich (Inhaltswörter
       zu mindestens WIEDERHOLUNG_SCHWELLE gleich, Namen und Zahlen identisch). Kein Modellaufruf.
    2. Bei einer Wiederholung antwortet der Agent nicht neu, sondern verweist auf die frühere Antwort
       (hinweis_markdown) und schlägt ähnliche Fragen vor (vorschlaege). Neu beantworten geht per Knopf.
    3. vorschlaege(): Das Modell schlägt Fragen zu den GEFUNDENEN Quellen vor. Der Code verwirft Vorschläge mit
       Namen, die weder in der Frage noch in den Quellen stehen, und Vorschläge, die schon gestellt wurden.
       Ohne Modellantwort gibt es feste Vorschläge aus den Titeln der Quellen.
"""
import json
import re

import ollama

import config
import verstehen

WIEDERHOLUNG_SCHWELLE = 0.8  # Anteil gleicher Inhaltswörter, ab dem zwei Fragen als gleich gelten
FUELLWOERTER = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "oder",
                "mit", "von", "vom", "zu", "zum", "zur", "für", "bei", "beim", "im", "in", "an", "am", "auf", "ist",
                "sind", "war", "hat", "haben", "gibt", "es", "wir", "ich", "mir", "mich", "uns", "noch", "mal",
                "bitte", "eigentlich", "denn", "doch", "nochmal", "nochmals", "genau", "aktuell", "derzeit"}

# Beispiele mit neutralen Namen (CLAUDE.md: keine Demo-Daten in Prompts)
VORSCHLAG_PROMPT = """Du hilfst einem Key-Account-Manager, gezielte Fragen an seine Unterlagen zu stellen.
Du bekommst eine bereits gestellte Frage und die Titel der Quellen, die dazu gefunden wurden.
Schlage drei ANDERE, kurze Fragen vor, die sich mit genau diesen Quellen beantworten lassen und das Thema sinnvoll
ergänzen (z. B. Fristen, Ansprechpartner, Konditionen, Termine, Stand einer Verhandlung).
Nutze nur Namen von Kunden, Personen, Projekten und Verträgen, die in der Frage oder den Quellen vorkommen.
Wiederhole die gestellte Frage nicht. Antworte nur mit JSON {"fragen": ["...", "...", "..."]}.

Beispiel:
Frage: "Welchen Rabatt hat Firma X?" / Quellen: "Rahmenvertrag RV-100 (Firma X)", "Mail: Lieferverzug Bestellung 4711"
-> {"fragen": ["Bis wann läuft der Rahmenvertrag RV-100 mit Firma X?", "Welches Zahlungsziel gilt für Firma X?",
   "Was ist der Stand beim Lieferverzug der Bestellung 4711?"]}"""


# =============================================================================
# 1. Wiederholung erkennen (Code)
# =============================================================================

def _woerter(frage: str) -> list[str]:
    return [w for w in re.findall(r"[\wäöüß][\wäöüß.-]*", frage.lower()) if w.strip(".-") and w not in FUELLWOERTER]


def normalisiere(frage: str) -> str:
    """Vergleichsform: klein, ohne Satzzeichen und Füllwörter. 'Welchen Rabatt hat Firma X?' -> 'welchen rabatt firma x'"""
    return " ".join(w.strip(".-") for w in _woerter(frage))


def _kennungen(frage: str) -> set[str]:
    """Namen und Zahlen: Darin dürfen sich zwei 'gleiche' Fragen nie unterscheiden ('2026' ≠ '2027', 'X' ≠ 'Y')."""
    zahlen = set(re.findall(r"\d+(?:[.,]\d+)?", frage))
    namen = {w.lower() for w in re.findall(r"\b[A-ZÄÖÜ][\wäöüß-]*", frage)[1:]}  # erstes Wort = Satzanfang
    return zahlen | (namen - FUELLWOERTER)


def gleiche_frage(a: str, b: str) -> bool:
    """Gleich, wenn die Vergleichsform identisch ist, oder fast gleich bei identischen Namen und Zahlen."""
    na, nb = normalisiere(a), normalisiere(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if _kennungen(a) != _kennungen(b):
        return False
    wa, wb = set(na.split()), set(nb.split())
    return len(wa & wb) / len(wa | wb) >= WIEDERHOLUNG_SCHWELLE


def finde_wiederholung(frage: str, verlauf: list[dict]) -> int | None:
    """Index des Eintrags in verlauf (Liste {"rolle", "text", ...}), unter dem die Frage schon einmal gestellt wurde.
    Gesucht wird die LETZTE gleiche Frage; None = neue Frage."""
    for i in range(len(verlauf) - 1, -1, -1):
        e = verlauf[i]
        if e.get("rolle") == "user" and not e.get("wiederholung") and gleiche_frage(frage, e["text"]):
            return i
    return None


def kurzantwort(text: str, laenge: int = 600) -> str:
    """Die Kurzantwort einer früheren Antwort (ohne Details und den vom Code erzeugten Anhang)."""
    teil = re.split(r"\n#+ (?:Details|Termine im Zeitraum|Widersprüche|Bitte prüfen|Quellen)\b", text)[0]
    teil = teil.replace("### Kurzantwort", "").strip()
    return teil if len(teil) <= laenge else teil[:laenge].rsplit(" ", 1)[0] + " …"


def hinweis_markdown(frage: str, frueher: dict, nummer: int, uhrzeit: str | None, vorschlaege: list[str]) -> str:
    """Text der Antwort auf eine wiederholte Frage. frueher = Eintrag der früheren Antwort im Verlauf."""
    wann = f" um {uhrzeit}" if uhrzeit else ""
    zeilen = ["### Diese Frage wurde bereits gestellt",
              f"Sie haben „{frage}“ in diesem Gespräch schon{wann} gefragt (Frage {nummer}). "
              "Die vollständige Antwort mit Quellen steht weiter oben im Verlauf.", ""]
    if frueher:
        zeilen += ["**Kurzantwort von damals:**", "", "> " + kurzantwort(frueher["text"]).replace("\n", "\n> "), ""]
    if vorschlaege:
        zeilen += ["### Ähnliche Fragen, die Sie stellen können"] + [f"- {v}" for v in vorschlaege]
    return "\n".join(zeilen)


# =============================================================================
# 2. Ähnliche Fragen vorschlagen (Modell formuliert, Code prüft)
# =============================================================================

def _quellentitel(treffer: list[dict], anzahl: int = 6) -> list[str]:
    titel = []
    for t in treffer:
        m = t["meta"]
        if m["quelle"] != "Übersicht":
            eintrag = f"{m['quelle']}: {m['titel']} (Ablage: {m['ort']})"
            if eintrag not in titel:
                titel.append(eintrag)
    return titel[:anzahl]


def _feste_vorschlaege(treffer: list[dict], gestellt: list[str]) -> list[str]:
    """Ohne Modell: Fragen zu den Titeln der gefundenen Quellen. Die Titel sind echt, also nichts erfunden."""
    vorschlaege = []
    for t in treffer:
        m = t["meta"]
        if m["quelle"] in ("Übersicht",) or not m["titel"]:
            continue
        v = (f"Was steht im Termin „{m['titel']}“?" if m["quelle"] == "Kalender"
             else f"Was steht in „{m['titel']}“ ({m['quelle']})?")
        if v not in vorschlaege and not any(gleiche_frage(v, g) for g in gestellt):
            vorschlaege.append(v)
    return vorschlaege[:3]


def pruefe_vorschlaege(liste: list, frage: str, treffer: list[dict], gestellt: list[str]) -> list[str]:
    """Nur Vorschläge ohne erfundene Namen, nicht doppelt und nicht schon gestellt (höchstens drei)."""
    korpus = (frage + " " + " ".join(t["text"] + " " + t["meta"]["ort"] for t in treffer)).lower()
    gut = []
    for v in liste:
        v = str(v).strip()
        if not v or len(v) > 160:
            continue
        if verstehen.unbekannte_begriffe(v, korpus):
            continue  # Name kommt in Frage und Quellen nicht vor -> vom Modell erfunden
        if any(gleiche_frage(v, g) for g in gestellt + gut):
            continue
        gut.append(v if v.endswith("?") else v + "?")
    return gut[:3]


def vorschlaege(frage: str, treffer: list[dict], gestellt: list[str], model: str = config.CHAT_MODEL) -> list[str]:
    """Bis zu drei ähnliche Fragen zu den Quellen der früheren Antwort.

    Parameter:
        treffer:  Quellen der früheren Antwort (leer, wenn damals nichts gefunden wurde)
        gestellt: alle bisherigen Fragen des Gesprächs (werden nicht noch einmal vorgeschlagen)
    Ohne Quellen: Umformulierungen in Fachsprache (verstehen.varianten), damit die Suche eine neue Chance bekommt.
    """
    gestellt = gestellt + [frage]
    if not treffer:
        try:
            return pruefe_vorschlaege(verstehen.varianten(frage, model), frage, [], gestellt)
        except Exception:
            return []
    try:
        inhalt = f"Frage: {frage}\nQuellen:\n" + "\n".join(f"- {t}" for t in _quellentitel(treffer))
        antwort = ollama.chat(model=model, format="json", keep_alive=config.KEEP_ALIVE,
                              options={"temperature": 0, "num_ctx": config.NUM_CTX},
                              messages=[{"role": "system", "content": VORSCHLAG_PROMPT},
                                        {"role": "user", "content": inhalt}])
        liste = json.loads(antwort.message.content).get("fragen", [])
        gut = pruefe_vorschlaege(liste if isinstance(liste, list) else [], frage, treffer, gestellt)
    except Exception:  # Modell nicht erreichbar oder kaputtes JSON -> feste Vorschläge
        gut = []
    for v in _feste_vorschlaege(treffer, gestellt):  # auffüllen, falls das Modell weniger als drei brauchbare lieferte
        if len(gut) < 3 and v not in gut:
            gut.append(v)
    return gut
