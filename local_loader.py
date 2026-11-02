"""Lokaler Demo-Modus: liest die fiktiven Daten aus demo_data/ im selben Format wie die Graph-Connectoren.

So funktioniert die Demo auch ohne Microsoft-365-Tenant oder Internet. Die restliche Pipeline
(Chunking, Suche, Antwort) ist identisch.

Erwartete Dateien in demo_data/:
    onenote.json   Seiten       {"abschnitt", "seite", "datum", "text"}
    outlook.json   E-Mails      {"betreff", "absender", "datum", "text"}
    teams.json     Nachrichten  {"kanal", "betreff", "absender", "datum", "text"}
    kalender.json  Termine      {"betreff", "woche", "wochentag", "von", "bis", "ort",
                                 "organisator", "teilnehmende", "text"}
    sharepoint/    Ordner je Kunde mit .eml/.docx/... Dateien
"""
import json
from datetime import timedelta
from pathlib import Path

import config
from connectors.kalender import termin_text
from parsers import datei_zu_dokument


def demo_termin_tag(k: dict):
    """Datum eines Demo-Termins relativ zur laufenden Woche.

    "woche": 1, "wochentag": 1 = Dienstag nächster Woche (Montag = 0); "woche": -1 = letzte Woche.
    Feste Daten würden mit der Zeit in die Vergangenheit rutschen, dann fände "nächste Woche" nichts mehr.
    """
    montag = config.heute() - timedelta(days=config.heute().weekday())
    return montag + timedelta(weeks=k["woche"], days=k["wochentag"])


def lade_alle(ordner: Path) -> list[dict]:
    """Alle Demo-Daten aus `ordner` als Liste von Dokumenten {"text", "meta"}."""
    docs = []

    # --- OneNote-Seiten ---
    for s in json.loads((ordner / "onenote.json").read_text(encoding="utf-8")):
        docs.append({"text": s["text"], "meta": {
            "quelle": "OneNote", "titel": s["seite"], "ort": f"MBS 2 / {s['abschnitt']}",
            "datum": s["datum"], "link": f"onenote:MBS 2/{s['abschnitt']}/{s['seite']}"}})

    # --- Outlook-Mails ---
    for m in json.loads((ordner / "outlook.json").read_text(encoding="utf-8")):
        docs.append({"text": f"Betreff: {m['betreff']}\n\n{m['text']}", "meta": {
            "quelle": "Outlook", "titel": m["betreff"], "ort": "Postfach",
            "absender": m["absender"], "datum": m["datum"], "link": f"outlook:{m['betreff']}"}})

    # --- Teams-Nachrichten ---
    for n in json.loads((ordner / "teams.json").read_text(encoding="utf-8")):
        docs.append({"text": n["text"], "meta": {
            "quelle": "Teams", "titel": n["betreff"] or n["text"][:60],
            "ort": f"Key Account - Kunden > {n['kanal']}", "absender": n["absender"],
            "datum": n["datum"], "link": f"teams:{n['kanal']}"}})

    # --- Kalendertermine ---
    # Demo-Termine liegen relativ zur aktuellen Woche, damit "nächste Woche" in der Demo immer etwas findet
    for k in json.loads((ordner / "kalender.json").read_text(encoding="utf-8")):
        tag = demo_termin_tag(k)
        docs.append({"text": termin_text(k["betreff"], tag, k["von"], k["bis"], k["ort"], k["teilnehmende"], k["text"]),
                     "meta": {"quelle": "Kalender", "titel": k["betreff"], "ort": k["ort"],
                              "absender": k["organisator"], "datum": tag.isoformat(),
                              "link": f"kalender:{tag.isoformat()} {k['von']}"}})

    # --- Dateien (simulierte SharePoint-Ablage, ein Unterordner je Kunde) ---
    for datei in sorted((ordner / "sharepoint").rglob("*")):
        if datei.is_file():
            ort = "SharePoint > Key Account - Kunden > " + datei.parent.name
            doc = datei_zu_dokument(datei.name, datei.read_bytes(), ort=ort,
                                    link=str(datei.relative_to(ordner.parent)))
            if doc:
                docs.append(doc)
    return docs
