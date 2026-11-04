"""Datei-Connector: Dateien aus OneDrive und den SharePoint-Bibliotheken der eigenen Teams.

Unterstützt abgelegte Mails (.msg, .eml) und Dokumente (.docx, .pdf, .txt, .md). Gerade ältere
Kundenkorrespondenz liegt oft als .msg-Datei in Ordnern statt im Postfach.
"""
import json
from pathlib import Path

import requests

from parsers import datei_zu_dokument

ENDUNGEN = {".msg", ".eml", ".docx", ".pdf", ".txt", ".md"}  # andere Dateien (Bilder, Excel ...) werden übersprungen


def _durchlaufe(graph, laufwerk: str, ordner_id: str, pfad: str, docs: list[dict],
                alt: dict | None = None, neu: dict | None = None) -> None:
    """Durchläuft einen Ordner rekursiv (inkl. aller Unterordner) und hängt gefundene Dokumente an docs an.

    pfad: lesbarer Ablageort für die Quellenangabe, z. B. "Teams: Key Account - Kunden/Hoffmann"
    alt/neu: gelesene Dateien vom letzten bzw. für den nächsten Lauf {Datei-ID: {"etag", "doc"}}. Unveränderte
             Dateien (gleicher eTag) werden nicht erneut heruntergeladen.
    """
    alt, neu = alt if alt is not None else {}, neu if neu is not None else {}
    for item in graph.get_all(f"/drives/{laufwerk}/items/{ordner_id}/children"):
        if "folder" in item:
            _durchlaufe(graph, laufwerk, item["id"], f"{pfad}/{item['name']}", docs, alt, neu)
        elif Path(item["name"]).suffix.lower() in ENDUNGEN:
            bekannt = alt.get(item["id"])
            if bekannt and bekannt["etag"] == item.get("eTag"):
                neu[item["id"]] = bekannt
                docs.append(bekannt["doc"])
                continue
            try:
                daten = graph.get_bytes(f"/drives/{laufwerk}/items/{item['id']}/content")
                doc = datei_zu_dokument(item["name"], daten, ort=pfad, link=item["webUrl"],
                                        datum=item["lastModifiedDateTime"][:10])
            except Exception as e:  # defekte oder verschlüsselte Datei: die übrigen Dateien trotzdem einlesen
                graph.melde_problem(f"{pfad}/{item['name']}: {e}")
                continue
            if doc:
                docs.append(doc)
                neu[item["id"]] = {"etag": item.get("eTag"), "doc": doc}


def lade(graph) -> list[dict]:
    """Alle unterstützten Dateien aus dem eigenen OneDrive und den Dateiablagen aller eigenen Teams."""
    docs: list[dict] = []
    laufwerke = [("OneDrive", graph.get("/me/drive"))]
    for team in graph.get_all("/me/joinedTeams"):
        # Jedes Team hat im Hintergrund eine Microsoft-365-Gruppe mit eigener SharePoint-Dateiablage.
        # Manche Teams haben (noch) keine Ablage: Das darf die Dateien der übrigen Teams nicht verhindern.
        try:
            laufwerke.append((f"Teams: {team['displayName']}", graph.get(f"/groups/{team['id']}/drive")))
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                raise
            print(f"  Team {team['displayName']}: keine Dateiablage, übersprungen")
    cache = graph.dateien_cache
    alt = json.loads(cache.read_text(encoding="utf-8")) if cache and cache.exists() else {}
    neu: dict = {}
    for name, laufwerk in laufwerke:
        wurzel = graph.get(f"/drives/{laufwerk['id']}/root")
        _durchlaufe(graph, laufwerk["id"], wurzel["id"], name, docs, alt, neu)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(neu, ensure_ascii=False), encoding="utf-8")
    return docs
