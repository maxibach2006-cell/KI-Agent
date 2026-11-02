"""Connectoren: holen Daten aus Microsoft Graph und liefern sie im einheitlichen Dokumentformat.

Jeder Connector (onenote, outlook, kalender, teams, files) hat dieselbe Schnittstelle:

    lade(graph: GraphClient) -> list[dict]

Jedes Dokument hat die Form
    {"text": "...", "meta": {"quelle", "titel", "ort", "absender", "datum", "link"}}
Dadurch kann ingest.py alle Quellen gleich behandeln, und eine neue Quelle braucht nur einen neuen Connector.
"""
