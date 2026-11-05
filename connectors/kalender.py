"""Kalender-Connector: Outlook-Termine der letzten zwei Jahre und des kommenden Jahres.

Termine sind die Hauptquelle für Zeitfragen ("Was steht nächste Woche an?", siehe zeitraum.py).
"""
from datetime import date, timedelta

import config
from parsers import html_zu_text
from zeitraum import WOCHENTAGE

FELDER = "subject,start,end,location,organizer,attendees,body,webLink"


def termin_text(betreff: str, tag: date, von: str, bis: str, ort: str, teilnehmende: str, inhalt: str) -> str:
    """Einheitlicher Text eines Termins (auch vom lokalen Loader genutzt).

    Das Datum steht ausgeschrieben im Text (z. B. "Dienstag, 10.11.2026"), damit ingest.py es mit
    daten_im_text() findet und der Termin bei Zeitfragen herausgefiltert werden kann.
    """
    return (f"Termin: {betreff}\n"
            f"Wann: {WOCHENTAGE[tag.weekday()]}, {tag.strftime('%d.%m.%Y')}, {von}–{bis} Uhr\n"
            f"Ort: {ort}\nTeilnehmende: {teilnehmende}\n\n{inhalt}")


def lade(graph) -> list[dict]:
    """Alle Termine im Zeitraum heute - 2 Jahre bis heute + 1 Jahr als Dokumente."""
    heute = config.heute()
    von, bis = heute - timedelta(days=730), heute + timedelta(days=365)
    # calendarView liefert auch Einzeltermine von Serienterminen (anders als /me/events).
    # Prefer-Header: Zeiten in deutscher Zeitzone statt UTC
    termine = graph.get_all(f"/me/calendarView?startDateTime={von}T00:00:00&endDateTime={bis}T23:59:59"
                            f"&$select={FELDER}&$top=100",
                            headers={"Prefer": 'outlook.timezone="W. Europe Standard Time"'})
    docs = []
    for t in termine:
        tag = date.fromisoformat(t["start"]["dateTime"][:10])
        teilnehmende = ", ".join(a["emailAddress"]["name"] for a in t.get("attendees", []))
        organisator = t["organizer"]["emailAddress"]["name"]
        docs.append({
            # dateTime hat die Form "2026-11-10T14:00:00" -> [11:16] ist die Uhrzeit "14:00"
            "text": termin_text(t["subject"], tag, t["start"]["dateTime"][11:16], t["end"]["dateTime"][11:16],
                                t["location"].get("displayName", ""), teilnehmende,
                                html_zu_text(t["body"]["content"])),
            "meta": {"quelle": "Kalender", "titel": t["subject"], "ort": t["location"].get("displayName", ""),
                     "absender": organisator, "datum": tag.isoformat(), "link": t["webLink"]},
        })
    return docs
