"""OneNote-Connector: Notizbuch "MBS 2" -> Abschnitte -> Seiten -> Text.

OneNote ist die wichtigste Quelle (fachliche Vorgabe) und wird in der Suche bevorzugt (config.ONENOTE_BOOST).
"""
import config
from parsers import html_zu_text


def lade(graph) -> list[dict]:
    """Alle Seiten des Notizbuchs config.NOTEBOOK_NAME als Dokumente (eine Seite = ein Dokument)."""
    notizbuecher = graph.get_all("/me/onenote/notebooks")
    nb = next((n for n in notizbuecher if n["displayName"] == config.NOTEBOOK_NAME), None)
    if nb is None:
        raise RuntimeError(f'Notizbuch "{config.NOTEBOOK_NAME}" nicht gefunden')

    docs = []
    for abschnitt in graph.get_all(f"/me/onenote/notebooks/{nb['id']}/sections"):
        for seite in graph.get_all(f"/me/onenote/sections/{abschnitt['id']}/pages"):
            # Seiteninhalt kommt als HTML und muss einzeln abgefragt werden
            html = graph.request("GET", f"/me/onenote/pages/{seite['id']}/content").text
            docs.append({
                "text": html_zu_text(html),
                "meta": {
                    "quelle": "OneNote",
                    "titel": seite["title"],
                    # Abschnittsname = in der Praxis meist der Kunde -> wichtig für die Zuordnung
                    "ort": f"{config.NOTEBOOK_NAME} / {abschnitt['displayName']}",
                    "datum": seite["createdDateTime"][:10],  # nur das Datum (JJJJ-MM-TT), ohne Uhrzeit
                    "link": seite["links"]["oneNoteWebUrl"]["href"],
                },
            })
    return docs
