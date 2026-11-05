"""Outlook-Connector: E-Mails des Postfachs mit Betreff, Absender, Datum und Web-Link."""
from parsers import html_zu_text

# Nur diese Felder abfragen ($select) -> weniger Datenübertragung, schnelleres Einlesen
FELDER = "subject,from,receivedDateTime,body,webLink"


def lade(graph, max_mails: int = 500) -> list[dict]:
    """Die neuesten max_mails E-Mails als Dokumente (eine Mail = ein Dokument)."""
    mails = graph.get_all(f"/me/messages?$select={FELDER}&$top=50&$orderby=receivedDateTime desc", maximal=max_mails)
    docs = []
    for m in mails[:max_mails]:
        absender = (m.get("from") or {}).get("emailAddress", {})  # Entwürfe haben keinen Absender
        body = m["body"]["content"]
        text = html_zu_text(body) if m["body"]["contentType"] == "html" else body
        docs.append({
            "text": f"Betreff: {m['subject']}\n\n{text}",  # Betreff mit in den Text -> auch danach suchbar
            "meta": {
                "quelle": "Outlook",
                "titel": m["subject"],
                "ort": "Postfach",
                "absender": f"{absender.get('name', '')} <{absender.get('address', '')}>",
                "datum": m["receivedDateTime"][:10],
                "link": m["webLink"],
            },
        })
    return docs
