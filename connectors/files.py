"""Datei-Connector: Dateien aus OneDrive und den SharePoint-Bibliotheken der eigenen Teams.

Unterstützt abgelegte Mails (.msg, .eml) und Dokumente (.docx, .pdf, .txt, .md). Gerade ältere
Kundenkorrespondenz liegt oft als .msg-Datei in Ordnern statt im Postfach.
"""
from pathlib import Path

from parsers import datei_zu_dokument

ENDUNGEN = {".msg", ".eml", ".docx", ".pdf", ".txt", ".md"}  # andere Dateien (Bilder, Excel ...) werden übersprungen


def _durchlaufe(graph, laufwerk: str, ordner_id: str, pfad: str, docs: list[dict]) -> None:
    """Durchläuft einen Ordner rekursiv (inkl. aller Unterordner) und hängt gefundene Dokumente an docs an.

    pfad: lesbarer Ablageort für die Quellenangabe, z. B. "Teams: Key Account - Kunden/Hoffmann"
    """
    for item in graph.get_all(f"/drives/{laufwerk}/items/{ordner_id}/children"):
        if "folder" in item:
            _durchlaufe(graph, laufwerk, item["id"], f"{pfad}/{item['name']}", docs)
        elif Path(item["name"]).suffix.lower() in ENDUNGEN:
            daten = graph.get_bytes(f"/drives/{laufwerk}/items/{item['id']}/content")
            doc = datei_zu_dokument(item["name"], daten, ort=pfad, link=item["webUrl"],
                                    datum=item["lastModifiedDateTime"][:10])
            if doc:
                docs.append(doc)


def lade(graph) -> list[dict]:
    """Alle unterstützten Dateien aus dem eigenen OneDrive und den Dateiablagen aller eigenen Teams."""
    docs: list[dict] = []
    laufwerke = [("OneDrive", graph.get("/me/drive"))]
    for team in graph.get_all("/me/joinedTeams"):
        # Jedes Team hat im Hintergrund eine Microsoft-365-Gruppe mit eigener SharePoint-Dateiablage
        laufwerke.append((f"Teams: {team['displayName']}", graph.get(f"/groups/{team['id']}/drive")))
    for name, laufwerk in laufwerke:
        wurzel = graph.get(f"/drives/{laufwerk['id']}/root")
        _durchlaufe(graph, laufwerk["id"], wurzel["id"], name, docs)
    return docs
