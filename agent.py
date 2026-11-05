"""Der eigentliche Agent: beantwortet eine Frage mit Quellen aus dem lokalen Index.

Rolle im System:
    Dies ist der "Online"-Teil des RAG-Verfahrens (Retrieval-Augmented Generation). Der Index wurde
    vorher von ingest.py aufgebaut. Pro Frage laufen folgende Schritte:

  0. verstehen.umschreiben() Folgefrage mit Gesprächsverlauf eigenständig machen (verstehen.py)
  1. suche_verstanden()      passende Textabschnitte im lokalen Index finden; bei schwachen Treffern
                             zusätzlich mit umformulierten Suchvarianten
                             (bei Zeitfragen wie "nächste Woche": alle Quellen mit Datum im Zeitraum)
  2. pruefe_widersprueche()  eigener LLM-Aufruf, der nur Widersprüche sucht; der Code prüft das Ergebnis nach
  3. generiere()             Antwort nach Ausgabevorlage schreiben
  4. anhang_markdown()       Abschnitte "Widersprüche" und "Quellen" aus Code und Metadaten anhängen

Grundprinzip – Aufgabenteilung zwischen Sprachmodell und Code:
    Das Sprachmodell (qwen2.5:7b) übernimmt nur, was Sprachverständnis braucht: Umformulieren,
    Zusammenfassen, Benennen. Alles, was exakt sein muss (Daten rechnen, Belege prüfen, Quellen
    auflisten), macht der Code. So kann das Modell an diesen Stellen nichts erfinden.

Gliederung dieser Datei:
    A. Hilfsfunktionen für die Suche   (_woerter, _abdeckung, _namen, _genannte_kunden, _aehnlichkeiten, ...)
    B. Suche                           (suche_zeitraum, suche, suche_verstanden)
    C. Widerspruchsprüfung             (pruefe_widersprueche und Hilfsfunktionen)
    D. Antwort erzeugen                (generiere, aufwaermen)
    E. Vom Code erzeugte Anhänge       (quellenangabe, terminliste_markdown, anhang_markdown)
    F. Gesamtablauf                    (vorbereite, ablage_sicher, antworte)

Ein "Treffer" ist im ganzen Modul ein dict mit:
    text          Abschnittstext (mit Kopfzeile aus ingest.kopfzeile())
    meta          Metadaten (quelle, titel, ort, absender, datum, link, termine)
    aehnlichkeit  Kosinus-Ähnlichkeit zur Frage (0 bis 1)
    score         Gesamtbewertung für die Rangfolge (Ähnlichkeit + Boni)
    sowie je nach Suchart: abdeckung, hat_namen (normale Suche) bzw. tage, tag (Zeitsuche)

Beispiel:
    python agent.py "Welche Konditionen gelten für Hoffmann Maschinenbau?"
"""
import re
import sys
import time
from datetime import date
from functools import lru_cache
from typing import Iterator

import numpy as np
import ollama

import ablage
import config
import prompts
import verstehen
from ingest import index_daten, oeffne_collection
from zeitraum import MONATE, WOCHENTAGE, daten_im_text, erkenne_zeitraum


# =============================================================================
# A. Hilfsfunktionen für die Suche
# =============================================================================

def _zeitraum(frage: str):
    """Zeitraum der Frage bezogen auf heute, z. B. "nächste Woche" -> (von, bis, "nächste Woche"), sonst None."""
    return erkenne_zeitraum(frage, config.heute())


def _im_zeitraum(meta: dict, von: date, bis: date) -> list[date]:
    """Daten eines Abschnitts im Zeitraum: genannte Termine im Text oder das Datum der Quelle selbst."""
    # meta["termine"] wurde beim Einlesen gefüllt (kommagetrennte ISO-Daten, siehe ingest.py)
    daten = [date.fromisoformat(d) for d in meta.get("termine", "").split(",") if d]
    if meta["datum"]:
        daten.append(date.fromisoformat(meta["datum"][:10]))
    return sorted(d for d in set(daten) if von <= d <= bis)


# Wörter ohne Aussagekraft für die Stichwortsuche (Fragewörter, Artikel, Zeitwörter, Quellennamen).
# Sie kommen in fast jedem Text vor und würden die Stichwortbewertung verfälschen.
FUELLWOERTER = {
    "termin", "termine", "woche", "wochen", "monat", "monate", "tage", "tagen", "mail", "mails", "kalender",
    "meeting", "meetings", "gespräch", "gespräche", "besprechung", "welche", "welcher", "welches", "wann",
    "habe", "haben", "hatte", "gibt", "steht", "stehen", "unser", "unsere", "unseren", "teams", "outlook",
    "onenote", "eine", "einen", "einem", "einer", "dass", "wurde", "wurden", "wird", "werden", "kann", "muss",
    "soll", "sind", "bitte", "alles", "alle", "mir", "mich", "nächste", "nächsten", "letzte", "diese", "dieser",
    "heute", "morgen", "über", "nach", "bei", "beim", "für", "von", "vom", "mit", "zum", "zur", "noch",
    "wichtige", "wichtiges", "fasse", "zusammen", "what", "does", "the", "with", "get"}

# Ablageorte, die keinen Kunden bezeichnen
OHNE_KUNDE = {"allgemein", "general", "persönliche", "chat", "intern", "interne"}


def _woerter(text: str) -> set[str]:
    """Inhaltswörter eines Textes: kleingeschrieben, mindestens 4 Zeichen, ohne Füllwörter."""
    return {w for w in re.findall(r"[\wäöüß][\wäöüß-]{3,}", text.lower()) if w not in FUELLWOERTER}


def _abdeckung(woerter: set[str], text: str) -> float:
    """Anteil der Fragewörter, die im Text vorkommen (lange Wörter auch über den Wortanfang: bestellt ~ Bestellung).

    Beispiel: Fragewörter {"hoffmann", "rabatt"}, Text enthält nur "Hoffmann" -> 0,5
    """
    if not woerter:
        return 0.0
    text = text.lower()
    return sum(w in text or (len(w) >= 7 and w[:6] in text) for w in woerter) / len(woerter)


def _namen(frage: str, metas: list[dict]) -> set[str]:
    """Wörter der Frage, die als Name in Titeln, Orten oder Absendern vorkommen (Kunden, Personen, Projekte),
    z. B. "hoffmann", "albrecht", "billbrook". Allgemeine Wörter wie "Konditionen" zählen nicht."""
    vokabular = set()
    for m in metas:
        vokabular |= _woerter(f"{m['titel']} {m['ort']} {m['absender']}")
    return {w for w in _woerter(frage) if w in vokabular and w not in MONATE}


def _kennwort_kunde(name: str) -> str:
    """Erstes aussagekräftiges Wort eines Kundennamens: "Firma X Maschinenbau GmbH" -> "x", "Muster Logistik" -> "muster".
    Nur das erste Wort: "Logistik" oder "Pharma" allein bezeichnen keinen Kunden, und eine Frage nach "der Logistik"
    darf nicht auf einen Kunden eingeschränkt werden."""
    for wort in re.findall(r"[^\W\d_][^\W_]*", name.lower()):
        if wort not in ablage.NAMENS_FUELLER:
            return "" if wort in OHNE_KUNDE else wort
    return ""


def _kunden_im_index(metas: list[dict]) -> set[str]:
    """Kennwörter aller Kunden eines Index. Die Ablage ist die verlässliche Quelle, nicht das Sprachmodell:
    OneNote-Abschnitt ("MBS 2 / Firma X"), Teams-Kanal ("Team > Firma X") und Ordner darin ("Teams: Team/Firma X")."""
    kunden = set()
    for m in metas:
        if m["quelle"] in ("OneNote", "Teams") or m["ort"].startswith("Teams:"):
            if not m["ort"].startswith("Chat"):
                kunden.add(_kennwort_kunde(re.split(r"\s*[/>]\s*", m["ort"])[-1]))
    return kunden - {""}


def _genannte_kunden(frage: str, metas: list[dict]) -> set[str]:
    """Kennwörter der Kunden, die die Frage nennt (auch im Genitiv: "Firma Xs Rabatt"). Leer = kein Kunde genannt."""
    woerter = set(re.findall(r"[^\W\d_][^\W_]*", frage.lower()))
    return {k for k in _kunden_im_index(metas) if k in woerter or k + "s" in woerter}


def _nennt_kunden(text: str, kunden: set[str]) -> bool:
    """Nennt der Abschnitt (mit Kopfzeile) einen der Kunden? "_" trennt Wörter, Dateien heißen oft "RV-100_Firma_X.pdf"."""
    return any(re.search(rf"(?<![^\W_]){re.escape(k)}(?![^\W_])", text.lower()) for k in kunden)


def _gehoert_anderem(text: str, genannt: set[str], alle_kunden: set[str]) -> bool:
    """Gehört der Abschnitt erkennbar zu einem anderen Kunden als den genannten? Abschnitte ohne Kundennamen bleiben:
    Eine Chat-Nachricht wie "Herr X ist nicht mehr im Einkauf" nennt die Firma nicht und kann trotzdem entscheidend sein."""
    return not _nennt_kunden(text, genannt) and _nennt_kunden(text, alle_kunden - genannt)


def _aehnlichkeiten(collection, ids: list[str], vektor: list[float]) -> dict:
    """Kosinus-Ähnlichkeit zwischen Fragevektor und den gespeicherten Vektoren der angegebenen Abschnitte.

    Kosinus-Ähnlichkeit = Skalarprodukt / (Länge a * Länge b); 1 = gleiche Richtung = gleiche Bedeutung.
    Rückgabe: {id: (text, meta, ähnlichkeit)}
    """
    daten = collection.get(ids=ids, include=["documents", "metadatas", "embeddings"])
    v = np.array(vektor)
    return {i: (text, meta, float(np.dot(v, emb) / (np.linalg.norm(v) * np.linalg.norm(emb))))
            for i, text, meta, emb in zip(daten["ids"], daten["documents"], daten["metadatas"], daten["embeddings"])}


def _ist_ueberblick(frage: str) -> bool:
    """Überblicksfrage ("Fasse zusammen", "Welche Kunden ...")? Dann werden mehr Quellen gebraucht."""
    return bool(re.search(r"zusammen|überblick|übersicht|alles|welche kunden|offene|aufgaben", frage.lower()))


# =============================================================================
# B. Suche
# =============================================================================

def suche_zeitraum(frage: str, collection, alle: dict, vektor: list[float], von: date, bis: date) -> list[dict]:
    """Zeitfragen ("Was steht nächste Woche an?"): alle Abschnitte mit einem Datum im Zeitraum holen.
    Nennt die Frage einen Namen (z. B. "bei Hoffmann"), bleiben nur Abschnitte, die ihn enthalten.
    Ergebnis chronologisch sortiert.

    Ablauf: 1. nach Datum filtern  2. nach Ähnlichkeit + Kalenderbonus die besten ZEIT_TOP_K auswählen
            3. diese chronologisch sortieren (für die Terminliste)
    """
    namen = _namen(frage, alle["metadatas"])
    ids = [i for i, m, text in zip(alle["ids"], alle["metadatas"], alle["documents"])
           if _im_zeitraum(m, von, bis) and all(n in text.lower() for n in namen)]
    if not ids:
        return []
    treffer = []
    for text, meta, aehnlichkeit in _aehnlichkeiten(collection, ids, vektor).values():
        treffer.append({"text": text, "meta": meta, "aehnlichkeit": aehnlichkeit,
                        "score": aehnlichkeit + (config.KALENDER_BOOST if meta["quelle"] == "Kalender" else 0),
                        "tage": _im_zeitraum(meta, von, bis), "tag": _im_zeitraum(meta, von, bis)[0]})
    treffer = sorted(treffer, key=lambda t: t["score"], reverse=True)[:config.ZEIT_TOP_K]
    return sorted(treffer, key=lambda t: t["tag"])


def suche(frage: str, user: str = "demo", top_k: int = config.TOP_K) -> list[dict]:
    """Hybride Suche: Bedeutung (Embeddings) + Stichwörter (z. B. Namen wie "Jens Albrecht").
    Die Ähnlichkeitssuche allein findet kurze Fragen und Eigennamen schlecht, die Stichwortsuche allein
    versteht keine Umschreibungen. Beides zusammen ist robuster.

    Parameter:
        frage:  (bereits eigenständige) Frage
        user:   Nutzer, dessen Index durchsucht wird
        top_k:  maximale Anzahl Treffer
    Rückgabe:
        Treffer, beste zuerst. Leere Liste = keine ausreichend passende Quelle
        (dann antwortet der Agent mit "keine passende Quelle gefunden").
    """
    alle = index_daten(user)
    if not alle["ids"]:
        return []
    collection = oeffne_collection(user)
    # Frage in denselben Vektorraum übersetzen wie die Abschnitte beim Einlesen
    vektor = ollama.embed(model=config.EMBED_MODEL, input=frage, keep_alive=config.KEEP_ALIVE).embeddings[0]
    if zeitraum := _zeitraum(frage):
        return suche_zeitraum(frage, collection, alle, vektor, zeitraum[0], zeitraum[1])  # Sonderweg für Zeitfragen
    ueberblick = _ist_ueberblick(frage)
    if ueberblick:
        top_k = config.UEBERBLICK_TOP_K

    # --- Kandidaten: die semantisch ähnlichsten Abschnitte + alle, die viele Fragewörter enthalten ---
    woerter, namen = _woerter(frage), _namen(frage, alle["metadatas"])
    abdeckung = {i: _abdeckung(woerter, text) for i, text in zip(alle["ids"], alle["documents"])}
    semantisch = collection.query(query_embeddings=[vektor], n_results=min(20, len(alle["ids"])))["ids"][0]
    stichwort = [i for i, a in abdeckung.items() if a >= 0.5]

    # Nennt die Frage einen Kunden, werden alle seine Abschnitte Kandidaten und die anderer Kunden fallen weg. Verträge
    # klingen ähnlich: Die reine Ähnlichkeit brachte sonst den Vertrag eines anderen Kunden als scheinbaren Beleg.
    kunden = _genannte_kunden(frage, alle["metadatas"])
    if kunden:
        alle_kunden = _kunden_im_index(alle["metadatas"])
        texte = dict(zip(alle["ids"], alle["documents"]))
        eigene = [i for i, text in texte.items() if _nennt_kunden(text, kunden)]
        semantisch = [i for i in semantisch if not _gehoert_anderem(texte[i], kunden, alle_kunden)]
        stichwort = [i for i in stichwort if not _gehoert_anderem(texte[i], kunden, alle_kunden)] + eigene

    # --- Bewertung jedes Kandidaten ---
    # score = Ähnlichkeit + STICHWORT_GEWICHT * Abdeckung + OneNote-Bonus
    # Beispiel: Ähnlichkeit 0,60, Abdeckung 1,0, OneNote -> 0,60 + 0,25 + 0,05 = 0,90
    treffer = []
    for i, (text, meta, aehnlichkeit) in _aehnlichkeiten(collection, list({*semantisch, *stichwort}), vektor).items():
        hat_namen = all(n in text.lower() for n in namen) if namen else False
        score = (aehnlichkeit + config.STICHWORT_GEWICHT * abdeckung[i]
                 + (config.ONENOTE_BOOST if meta["quelle"] == "OneNote" else 0))
        treffer.append({"text": text, "meta": meta, "aehnlichkeit": aehnlichkeit, "score": score,
                        "abdeckung": abdeckung[i], "hat_namen": hat_namen})
    treffer.sort(key=lambda t: t["score"], reverse=True)

    # --- Gate gegen Halluzination ---
    # Es braucht einen klar ähnlichen Abschnitt, ODER einen Abschnitt mit einem
    # bekannten Namen aus der Frage (z. B. "hoffmann rabatt?"), ODER einen Abschnitt mit mind. der Hälfte der
    # Fragewörter ("die Hamburger" ~ "Hamburg-Billbrook") – Letzteres nur, wenn die Frage keinen Begriff enthält,
    # den es in den Daten gar nicht gibt (z. B. "Siemens"). Sonst: "keine passende Quelle".
    alles_bekannt = not verstehen.unbekannte_begriffe(frage, alle["korpus"])
    gate = any(t["aehnlichkeit"] >= config.MIN_SIMILARITY or
               (t["hat_namen"] and (t["aehnlichkeit"] >= config.KONTEXT_MIN or t["abdeckung"] >= 0.5)) or
               (alles_bekannt and t["abdeckung"] >= 0.5 and t["aehnlichkeit"] >= config.KONTEXT_MIN)
               for t in treffer)
    if not gate:
        return []
    # Ist das Gate offen, kommen auch schwächere, aber noch passende Abschnitte in den Kontext
    passend = [t for t in treffer if t["aehnlichkeit"] >= config.KONTEXT_MIN or t["abdeckung"] >= 0.5]

    # --- Auswahl der Treffer ---
    if not ueberblick or namen:
        return passend[:top_k]  # Frage zu einem bestimmten Kunden/Thema: einfach die besten Treffer
    # Allgemeine Überblicksfrage ("Welche Kunden betreue ich?"): erst der beste Abschnitt JEDES Ortes
    # (OneNote-Abschnitt, Teams-Kanal, Ordner), dann auffüllen -> kein Kunde fällt heraus
    erste_je_ort, rest, gesehen = [], [], set()
    for t in passend:
        (rest if t["meta"]["ort"] in gesehen else erste_je_ort).append(t)
        gesehen.add(t["meta"]["ort"])
    return (erste_je_ort + rest)[:top_k]


def suche_verstanden(frage: str, user: str = "demo", model: str = config.CHAT_MODEL) -> tuple[list[dict], list[str]]:
    """Suche mit Absicherung für abweichende Formulierungen. Ist der beste Treffer schwach (oder es gibt
    keinen), formuliert das Modell die Frage in Fachsprache um und es wird zusätzlich damit gesucht.
    Rückgabe: (Treffer, genutzte Suchvarianten)."""
    treffer = suche(frage, user)
    if _zeitraum(frage) or (treffer and max(t["aehnlichkeit"] for t in treffer) >= config.VARIANTEN_SCHWELLE):
        return treffer, []  # Zeitfragen und klare Treffer brauchen keine Varianten
    if verstehen.unbekannte_begriffe(frage, index_daten(user)["korpus"]):
        return treffer, []  # z. B. "Siemens": nicht verwässern, sonst Antwort zu einem anderen Kunden

    # Mit jeder Variante erneut suchen und die Ergebnisse zusammenführen.
    # Kommt ein Abschnitt mehrfach vor, zählt seine beste Bewertung (Schlüssel = Abschnittstext).
    varianten = verstehen.varianten(frage, model)
    alle = {t["text"]: t for t in treffer}
    # Eine Variante kann den Kundennamen verlieren. Es zählt der Kunde aus der Frage des Nutzers.
    metas = index_daten(user)["metadatas"]
    kunden, alle_kunden = _genannte_kunden(frage, metas), _kunden_im_index(metas)
    for variante in varianten:
        for t in suche(variante, user):
            if kunden and _gehoert_anderem(t["text"], kunden, alle_kunden):
                continue
            if t["text"] not in alle or t["score"] > alle[t["text"]]["score"]:
                alle[t["text"]] = t
    top_k = config.UEBERBLICK_TOP_K if _ist_ueberblick(frage) else config.TOP_K
    return sorted(alle.values(), key=lambda t: t["score"], reverse=True)[:top_k], varianten


# =============================================================================
# C. Widerspruchsprüfung
#    Stufe 1: Kandidaten finden      (Sprachmodell + _datums_kandidaten im Code)
#    Stufe 2: Belegprüfung           (Code: Stehen beide Werte wörtlich in einer Quelle?)
#    Stufe 3: Gegenprüfung           (Betreffen beide Werte dieselbe Sache? _gleicher_sachverhalt)
# =============================================================================

def _steht_in(wert: str, text: str) -> bool:
    """Steht der Wert wörtlich im Text? ISO-Datum (2026-11-18) wird auch als 18.11.2026 gesucht."""
    rumpf = text.split("\n", 1)[-1]  # Kopfzeile (Titel, Nachrichtendatum) zählt nicht als Beleg
    varianten = {wert}
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", wert)
    if iso:
        varianten.add(f"{iso[3]}.{iso[2]}.{iso[1]}")
    return any(v in rumpf for v in varianten)


def _beleg(wert: str, nr, treffer: list[dict]) -> int | None:
    """Nummer der Quelle, in der der Wert steht – bevorzugt die vom Modell genannte.

    nr: vom Modell genannte Quellennummer (kann falsch, ungültig oder kein Integer sein)
    Rückgabe: Quellennummer (ab 1) oder None, wenn der Wert in keiner Quelle steht.
    """
    try:
        if 1 <= int(nr) <= len(treffer) and _steht_in(wert, treffer[int(nr) - 1]["text"]):
            return int(nr)
    except (ValueError, TypeError):
        pass  # Modell hat eine ungültige Nummer geliefert -> unten in allen Quellen suchen
    return next((i for i, t in enumerate(treffer, start=1) if _steht_in(wert, t["text"])), None)


def pruefe_widersprueche(frage: str, treffer: list[dict], model: str = config.CHAT_MODEL) -> list[dict]:
    """Ein kleines Modell übersieht Widersprüche leicht, wenn es gleichzeitig die Antwort schreibt.
    Darum ein eigener, kurzer Aufruf nur für diese Aufgabe (JSON-Ausgabe). Danach prüft der Code jeden
    gemeldeten Widerspruch: Beide Werte müssen wörtlich in einer Quelle stehen und sich wirklich unterscheiden.

    Rückgabe: bestätigte Widersprüche [{"thema", "wert_a", "quelle_a", "wert_b", "quelle_b"}]
              (quelle_a/quelle_b = Nummern [n] in der Trefferliste)
    """
    if len(treffer) < 2:
        return []  # mit nur einer Quelle kann es keinen Widerspruch zwischen Quellen geben

    # --- Stufe 1: Kandidaten vom Sprachmodell ---
    antwort = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": prompts.WIDERSPRUCH_PROMPT},
                  {"role": "user", "content": prompts.build_user_prompt(frage, treffer)}],
        format="json",
        options={"temperature": 0, "num_ctx": config.NUM_CTX},
        keep_alive=config.KEEP_ALIVE,
    )
    gemeldet = [w for w in verstehen.json_wert(antwort, "widersprueche", []) if isinstance(w, dict)]
    gemeldet += _datums_kandidaten(treffer)  # Absicherung, falls das Modell einen Fall übersieht

    # --- Stufe 2 und 3: jeden Kandidaten prüfen ---
    geprueft, paare = [], set()
    for w in gemeldet:
        a, b = str(w.get("wert_a", "")).strip(), str(w.get("wert_b", "")).strip()
        if frozenset((a, b)) in paare:
            continue  # schon bestätigt (Modell und Code können denselben Fall finden)
        if not a or not b or a.lower() in b.lower() or b.lower() in a.lower():
            continue  # gleiche oder nur ergänzte Angabe -> kein Widerspruch
        if a.isdigit() and b.isdigit():
            continue  # nackte Zahlen ("600" vs. "300") sind zu mehrdeutig, oft verschiedene Produkte
        qa, qb = _beleg(a, w.get("quelle_a"), treffer), _beleg(b, w.get("quelle_b"), treffer)
        if not (qa and qb and qa != qb):
            continue  # nicht belegte Werte verwerfen (Schutz vor Halluzination)
        if not _gleicher_sachverhalt(a, treffer[qa - 1]["text"], b, treffer[qb - 1]["text"], model):
            continue  # z. B. "max. +4 % Preisgleitklausel" vs. "+3,5 % Listenpreiserhöhung"
        geprueft.append({"thema": w.get("thema", ""), "wert_a": a, "quelle_a": qa, "wert_b": b, "quelle_b": qb})
        paare.add(frozenset((a, b)))
    return geprueft


def _datums_kandidaten(treffer: list[dict], maximal: int = 4) -> list[dict]:
    """Code-Kandidaten für Widersprüche: zwei Quellen nennen verschiedene Daten in Sätzen mit gemeinsamem
    Fachwort (z. B. "Bedarfsanalyse ... 18.11." vs. "Bedarfsanalyse ... auf den 20.11. verschoben").
    Ob es wirklich derselbe Sachverhalt ist, entscheidet danach _gleicher_sachverhalt()."""
    nicht_fachlich = {w.lower() for w in WOCHENTAGE} | set(MONATE)  # "Montag", "November" sind keine Fachwörter
    saetze = []  # (Quellennummer, Datum, Satzwörter)
    for nr, t in enumerate(treffer, start=1):
        rumpf = t["text"].split("\n", 1)[-1]
        for satz in re.split(r"(?<=[.!?])\s+|\n", rumpf):  # Text in Sätze bzw. Zeilen zerlegen
            daten = daten_im_text(satz)
            if not daten:
                continue
            # "01.04.2023 bis 31.03.2027": nur das Enddatum zählt, sonst wird der Beginn mit einem neuen Ende verglichen
            woerter = {w for w in _woerter(satz) if len(w) >= 6 and not re.search(r"\d", w)}
            saetze.append((nr, daten[-1], woerter - nicht_fachlich))
    # Alle Satzpaare aus VERSCHIEDENEN Quellen mit verschiedenem Datum und mindestens einem gemeinsamen Fachwort
    kandidaten = []
    for i, (nr_a, d_a, w_a) in enumerate(saetze):
        for nr_b, d_b, w_b in saetze[i + 1:]:
            if nr_a != nr_b and d_a != d_b and w_a & w_b and len(kandidaten) < maximal:
                kandidaten.append({"thema": ", ".join(sorted(w_a & w_b)).capitalize(),
                                   "wert_a": d_a.strftime("%d.%m.%Y"), "quelle_a": nr_a,
                                   "wert_b": d_b.strftime("%d.%m.%Y"), "quelle_b": nr_b})
    return kandidaten


def _satz_mit(wert: str, text: str) -> str:
    """Den Satz bzw. die Zeile, in der der Wert steht (als Beleg für die Gegenprüfung)."""
    for satz in re.split(r"(?<=[.!?])\s+|\n", text.split("\n", 1)[-1]):
        if _steht_in(wert, "\n" + satz):  # "\n" davor, weil _steht_in() die erste Zeile als Kopfzeile ignoriert
            return satz.strip()
    return wert


# Wörter, die nur eine Änderung anzeigen ("neues Enddatum") und beim Vergleich der Beschreibungen
# ignoriert werden: "Enddatum" und "Neues Enddatum" sollen als dieselbe Sache gelten.
AENDERUNG = {"neu", "neue", "neuer", "neues", "neuen", "geändert", "geänderte", "geändertes", "verschoben",
             "verschobene", "verschobener", "verlängert", "verlängerte", "verlängertes", "aktuell", "aktuelle",
             "ursprünglich", "ursprüngliche", "ursprünglicher", "alte", "alter", "altes"}


@lru_cache(maxsize=512)  # gleiche Satzpaare (z. B. Vertragslaufzeit bei jeder Hoffmann-Frage) nur einmal prüfen
def _gleicher_sachverhalt(a: str, text_a: str, b: str, text_b: str, model: str) -> bool:
    """Gegenprüfung: Ein 7B-Modell meldet oft Werte als Widerspruch, die verschiedene Dinge betreffen, und
    sein Ja/Nein-Urteil ist unzuverlässig. Gut kann es aber benennen, worauf sich ein Wert bezieht.
    Zwei Prüfungen, beide müssen zustimmen:
      1. gemeinsam: beide Sätze sehen und je beschreiben -> Beschreibungen müssen weitgehend gleich sein
         (findet echte Fälle zuverlässig, kopiert aber manchmal die Beschreibung -> Fehlalarme)
      2. getrennt: jeden Satz einzeln beschreiben -> das Hauptwort muss übereinstimmen
         ("Enddatum ..." / "Neues Enddatum ..." ja; "Frist für Angebotsabgabe" / "Gültigkeit des Angebots" nein)"""
    satz_a, satz_b = _satz_mit(a, text_a), _satz_mit(b, text_b)

    # --- Prüfung 1: gemeinsame Beschreibung ---
    frage = (f'Satz A: "{satz_a}"\nSatz B: "{satz_b}"\n\n'
             f'Geht es bei "{a}" (Satz A) und "{b}" (Satz B) um dieselbe Sache, sodass nur ein Wert gelten kann '
             "oder der eine den anderen ändert (verschiebt, verlängert, ersetzt)?")
    antwort = ollama.chat(model=model, messages=[{"role": "system", "content": prompts.GLEICH_PROMPT},
                                                 {"role": "user", "content": frage}], format="json",
                          options={"temperature": 0, "num_ctx": config.NUM_CTX}, keep_alive=config.KEEP_ALIVE)
    # Wortüberlappung der beiden Beschreibungen (Jaccard-Index = Schnittmenge / Vereinigungsmenge)
    wa = _woerter(verstehen.json_wert(antwort, "a_betrifft", "")) - AENDERUNG
    wb = _woerter(verstehen.json_wert(antwort, "b_betrifft", "")) - AENDERUNG
    if not wa or not wb or len(wa & wb) / len(wa | wb) < config.GLEICH_SCHWELLE:
        return False

    # --- Prüfung 2: getrennte Beschreibung, Hauptwort vergleichen ---
    return _gleiches_hauptwort(_beschreibe(a, satz_a, model), _beschreibe(b, satz_b, model))


def _gleiches_hauptwort(beschreibung_a: str, beschreibung_b: str) -> bool:
    """Erstes inhaltliches Wort vergleichen; zusammengesetzte Wörter zählen ("Kick-off-Termin" ~ "Termin")."""
    def hauptwort(text: str) -> str:
        woerter = [w for w in re.findall(r"[\wäöüß][\wäöüß-]{3,}", text.lower()) if w not in AENDERUNG]
        return woerter[0] if woerter else ""
    ha, hb = hauptwort(beschreibung_a), hauptwort(beschreibung_b)
    return bool(ha and hb) and (ha == hb or ha.endswith(hb) or hb.endswith(ha))


@lru_cache(maxsize=1024)
def _beschreibe(wert: str, satz: str, model: str) -> str:
    """Worauf bezieht sich ein Wert im Satz? z. B. "30.06.2026" in "Angebot gültig bis 30.06.2026" -> "Gültigkeit Angebot"."""
    antwort = ollama.chat(model=model, format="json", options={"temperature": 0, "num_ctx": config.NUM_CTX}, keep_alive=config.KEEP_ALIVE,
                          messages=[{"role": "system", "content": prompts.BESCHREIBE_PROMPT},
                                    {"role": "user", "content": f'Satz: "{satz}"\nWert: "{wert}"'}])
    return verstehen.json_wert(antwort, "betrifft", "")


# =============================================================================
# D. Antwort erzeugen
# =============================================================================

def generiere(frage: str, treffer: list[dict], widersprueche: list[dict] | None = None,
              model: str = config.CHAT_MODEL) -> Iterator[str]:
    """Lässt das Sprachmodell die Antwort schreiben (gestreamt, Stück für Stück).

    Gestreamt heißt: Die Funktion liefert den Text in kleinen Teilen, sobald das Modell sie erzeugt.
    Die Oberfläche zeigt so schon nach ca. 1 s die ersten Wörter, statt auf die ganze Antwort zu warten.
    Ohne Treffer wird das Modell gar nicht aufgerufen (feste Antwort "keine passende Quelle").
    """
    zeitraum = _zeitraum(frage)
    if not treffer:
        yield prompts.keine_quelle(zeitraum)
        return
    stream = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": prompts.build_system_prompt(config.heute())},
            {"role": "user", "content": prompts.build_user_prompt(frage, treffer, widersprueche, zeitraum)},
        ],
        options={"temperature": config.TEMPERATURE, "num_ctx": config.NUM_CTX},
        keep_alive=config.KEEP_ALIVE,
        stream=True,
    )
    yield from _ohne_bilder(teil["message"]["content"] for teil in stream)


def _ohne_bilder(teile: Iterator[str]) -> Iterator[str]:
    """Macht aus Markdown-Bildern ("![x](url)") normale Links. Die Antwort beruht auf fremden Mails und Nachrichten:
    Der Browser würde ein Bild sofort laden, und eine präparierte Quelle könnte so Inhalte in der Bildadresse
    nach außen senden. "!" am Ende eines Teils wird zurückgehalten, weil "![" über zwei Teile verteilt sein kann."""
    rest = ""
    for teil in teile:
        text = rest + teil
        rest = "!" if text.endswith("!") else ""
        yield (text[:-1] if rest else text).replace("![", "[")
    if rest:
        yield rest


def aufwaermen(model: str = config.CHAT_MODEL) -> None:
    """Modelle vorab in den Grafikspeicher laden (mit denselben Einstellungen wie später, sonst lädt
    Ollama neu). Sonst wartet die erste Frage ca. 10 s auf das Laden."""
    ollama.embed(model=config.EMBED_MODEL, input="aufwärmen", keep_alive=config.KEEP_ALIVE)
    ollama.chat(model=model, messages=[{"role": "user", "content": "ok"}], keep_alive=config.KEEP_ALIVE,
                options={"num_ctx": config.NUM_CTX, "num_predict": 1})  # num_predict=1: nur ein Token erzeugen


# =============================================================================
# E. Vom Code erzeugte Anhänge (Terminliste, Widersprüche, Quellen)
#    Diese Teile schreibt bewusst NICHT das Sprachmodell: Sie stammen direkt aus den Metadaten,
#    deshalb können Links, Daten und Absender nicht erfunden oder vertauscht sein.
# =============================================================================

def quellenangabe(meta: dict) -> str:
    """Quellenformat je Quellentyp, wie im Copilot-Prompt gefordert.

    Beispiel OneNote: "OneNote – Abschnitt: MBS 2 / Hoffmann – Seite: Rahmenvertrag – 2023-04-01 – [Link](...)"
    """
    # Echte Web-Links werden klickbar, Demo-Pfade (z. B. "onenote:MBS 2/...") als Code-Text angezeigt
    link = f"[Link]({meta['link']})" if meta["link"].startswith("http") else f"`{meta['link']}`"
    if meta["quelle"] == "OneNote":
        return f"OneNote – Abschnitt: {meta['ort']} – Seite: {meta['titel']} – {meta['datum']} – {link}"
    if meta["quelle"] == "Outlook":
        return f"Outlook – Betreff: {meta['titel']} – Von: {meta['absender']} – {meta['datum']} – {link}"
    if meta["quelle"] == "Teams":
        return f"Teams – {meta['ort']} – Von: {meta['absender']} – {meta['datum']} – {link}"
    if meta["quelle"] == "Kalender":
        return f"Kalender – {meta['titel']} – {meta['datum']} – Ort: {meta['ort']} – {link}"
    if meta["quelle"] == "Übersicht":
        return "Übersicht – Inhaltsverzeichnis der Ablage (aus OneNote-Abschnitten, Teams-Kanälen und Ordnern erzeugt)"
    # Dateien (.msg, .docx, .pdf) aus Teams/SharePoint
    extra = f" – Von: {meta['absender']}" if meta["absender"] else ""
    return f"Datei – {meta['titel']}{extra} – {meta['datum']} – Speicherort: {meta['ort']} – {link}"


def terminliste_markdown(treffer: list[dict]) -> str:
    """Bei Zeitfragen: vollständige, chronologische Liste aller Daten im Zeitraum.
    Ein kleines Modell lässt bei langen Listen gern Einträge weg – der Code nicht.

    Nur Treffer aus suche_zeitraum() haben das Feld "tage"; bei normalen Fragen bleibt die Liste leer.
    Rückgabe: Markdown-Tabelle oder "" (keine Zeitfrage).
    """
    zeilen = []
    for nr, t in enumerate(treffer, start=1):
        meta, rumpf = t["meta"], t["text"].split("\n", 1)[-1]
        # Uhrzeit nur bei Kalenderterminen: In Mails und Notizen gehört sie nicht zwingend zum jeweiligen Datum
        uhrzeit = re.search(r"(\d{1,2}:\d{2})(?:–(\d{1,2}:\d{2}))? Uhr", rumpf) if meta["quelle"] == "Kalender" else None
        zeit = "–".join(g for g in uhrzeit.groups() if g) if uhrzeit else "–"
        for tag in t.get("tage", []):
            # Art des Eintrags: echter Termin, nur Eingangsdatum der Quelle, oder im Text genanntes Datum
            if meta["quelle"] == "Kalender":
                art = "Termin"
            elif tag.isoformat() == meta["datum"][:10] and tag.strftime("%d.%m.%Y") not in rumpf:
                art = "eingegangen/erstellt"  # nur das Datum der Mail/Notiz selbst liegt im Zeitraum
            else:
                art = f"genannt in {meta['quelle']}"
            zeilen.append((tag, f"| {WOCHENTAGE[tag.weekday()][:2]}, {tag.strftime('%d.%m.%Y')} | {zeit} | "
                                f"{meta['titel']} | {art} | [{nr}] |"))
    if not zeilen:
        return ""
    zeilen.sort(key=lambda z: z[0])  # chronologisch
    return ("\n\n### Termine im Zeitraum\n| Datum | Uhrzeit | Was | Art | Quelle |\n|---|---|---|---|---|\n"
            + "\n".join(z for _, z in zeilen))


def unbelegte_daten(antwort: str, frage: str, treffer: list[dict]) -> list[date]:
    """Vollständige Daten im Antworttext des Modells, die keine Grundlage haben.

    Beleg ist ein Datum in Text oder Metadaten einer Quelle, in der Frage, das heutige Datum und die vom Code
    berechneten Grenzen des gefragten Zeitraums. Das Modell rechnet relative Angaben ("am Dienstag") teils
    falsch in ein Kalenderdatum um, und eine Regel im Prompt verhindert das nicht. Deshalb entscheidet der Code.
    """
    belegt = {config.heute(), *daten_im_text(frage)}
    zeitraum = _zeitraum(frage)
    if zeitraum:
        belegt |= {zeitraum[0], zeitraum[1]}
    for t in treffer:
        belegt |= set(daten_im_text(t["text"] + " " + " ".join(str(w) for w in t["meta"].values())))
    return [d for d in daten_im_text(antwort) if d not in belegt]


def anhang_markdown(treffer: list[dict], widersprueche: list[dict], antwort: str = "", frage: str = "") -> str:
    """Terminliste, Widersprüche und Quellen schreibt der Code, nicht das Modell -> Links und Daten stimmen garantiert.

    Die Nummer [n] einer Quelle ist ihre Position in `treffer` – dieselbe Nummerierung, die das Modell
    im Prompt gesehen hat (prompts.build_user_prompt). Verweise im Antworttext passen so zur Liste.
    antwort/frage: Text des Modells und die Frage dazu. Daten ohne Beleg werden unter "Bitte prüfen" genannt.
    """
    if not treffer:
        return ""
    text = terminliste_markdown(treffer) + "\n\n### Widersprüche\n"
    if widersprueche:
        for w in widersprueche:
            ma, mb = treffer[w["quelle_a"] - 1]["meta"], treffer[w["quelle_b"] - 1]["meta"]
            text += (f"- **{w['thema']}:** „{w['wert_a']}“ [{w['quelle_a']}] ({ma['quelle']}, {ma['datum']}) "
                     f"vs. „{w['wert_b']}“ [{w['quelle_b']}] ({mb['quelle']}, {mb['datum']})\n")
    else:
        text += "- Keine Widersprüche zwischen den gefundenen Quellen festgestellt.\n"
    unbelegt = unbelegte_daten(antwort, frage, treffer)
    if unbelegt:
        liste = ", ".join(d.strftime("%d.%m.%Y") for d in unbelegt)
        text += f"\n### Bitte prüfen\n- ⚠️ Dieses Datum in der Antwort steht in keiner Quelle: {liste}\n"
    zeilen = [f"- [{i}] {quellenangabe(t['meta'])}" for i, t in enumerate(treffer, start=1)]
    return text + "\n### Quellen\n" + "\n".join(zeilen)


# =============================================================================
# F. Gesamtablauf
# =============================================================================

def vorbereite(frage: str, user: str = "demo", model: str = config.CHAT_MODEL, verlauf: list[dict] | None = None,
               melde=lambda text: None) -> dict:
    """Schritte 0-2, gemeinsam für antworte() und die Oberfläche. melde(text) zeigt den aktuellen Schritt an.
    Rückgabe: {"verstanden", "treffer", "varianten", "widersprueche"}."""
    melde("Verstehe die Frage …")
    verstanden = verstehen.umschreiben(frage, verlauf or [], model)
    melde("Suche in Ihren Quellen …")
    treffer, varianten = suche_verstanden(verstanden, user, model)
    melde("Prüfe Quellen auf Widersprüche …")
    widersprueche = pruefe_widersprueche(verstanden, treffer, model)
    return {"verstanden": verstanden, "treffer": treffer, "varianten": varianten, "widersprueche": widersprueche}


def ablage_sicher(frage: str, treffer: list[dict], text: str, user: str, model: str, verstanden: str) -> dict:
    """Schritt 5: in die persönliche Ablage einordnen. Fehler dort dürfen nie die Antwort verhindern."""
    try:
        return ablage.ablegen(frage, treffer, text, user, model, verstanden_als=verstanden)
    except Exception as e:
        return {"status": "fehler", "meldung": f"Ablage fehlgeschlagen: {e}"}


def antworte(frage: str, user: str = "demo", model: str = config.CHAT_MODEL,
             verlauf: list[dict] | None = None, ablegen: bool = False) -> dict:
    """Komplette Antwort ohne Streaming (für Kommandozeile und Evaluation).
    verlauf: bisherige Runden [{"frage": ..., "antwort": ...}] für Folgefragen.
    ablegen: Frage und Antwort in die persönliche Ablage einordnen (ablage.py). Standard aus, damit der
             Testlauf die Ablage des Nutzers nicht mit Testfragen füllt.

    app.py nutzt dieselben Bausteine, streamt die Antwort aber und zeigt Zwischenstände.
    Rückgabe: dict mit Antworttext, Treffern, Widersprüchen, verstandener Frage, Suchvarianten und Dauer.
    """
    start = time.perf_counter()
    v = vorbereite(frage, user, model, verlauf)                                       # Schritte 0-2
    verstanden, treffer, widersprueche = v["verstanden"], v["treffer"], v["widersprueche"]
    antworttext = "".join(generiere(verstanden, treffer, widersprueche, model))       # Schritt 3
    text = antworttext + anhang_markdown(treffer, widersprueche, antworttext, verstanden)  # Schritt 4
    abgelegt = ablage_sicher(frage, treffer, text, user, model, verstanden) if ablegen else None  # Schritt 5
    return {"antwort": text, "treffer": treffer, "widersprueche": widersprueche, "verstanden_als": verstanden,
            "varianten": v["varianten"], "ablage": abgelegt, "sekunden": time.perf_counter() - start}


if __name__ == "__main__":
    # Aufruf per Kommandozeile: python agent.py "Frage ..."
    frage = " ".join(sys.argv[1:]) or "Welche Konditionen gelten für Hoffmann Maschinenbau?"
    ergebnis = antworte(frage, ablegen=config.ABLAGE_AKTIV)
    print(ergebnis["antwort"])
    if ergebnis["ablage"]:
        print(f"\n📁 {ergebnis['ablage']['meldung']}")
    print(f"\n({ergebnis['sekunden']:.1f} s)")
