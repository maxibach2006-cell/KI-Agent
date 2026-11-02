"""Teams-Connector: Kanalnachrichten (inkl. Antworten im Thread) der eigenen Teams und persönliche Chats."""
import re

from parsers import html_zu_text


def _nachricht_zu_dokument(n: dict, ort: str) -> dict | None:
    """Eine Teams-Nachricht -> Dokument. None bei leeren Nachrichten und Systemmeldungen
    (z. B. "X wurde zum Team hinzugefügt"), die keinen fachlichen Inhalt haben."""
    text = html_zu_text(n["body"]["content"])
    if not text or n.get("messageType") != "message":
        return None
    absender = ((n.get("from") or {}).get("user") or {}).get("displayName", "")
    datum = n["createdDateTime"][:10]
    # Von seed_graph.py angelegte Demo-Nachrichten tragen Originaldatum und Absender im Text,
    # weil Graph Teams-Nachrichten nicht rückdatieren kann. Format: "[2024-03-15 – Max Muster] ..."
    original = re.match(r"\[(\d{4}-\d{2}-\d{2}) – (.+?)\]\s*", text)
    if original:
        datum, absender = original.group(1), original.group(2)
        text = text[original.end():]  # Kennzeichnung aus dem Text entfernen
    return {
        "text": text,
        "meta": {
            "quelle": "Teams",
            "titel": n.get("subject") or text[:60],  # Nachrichten ohne Betreff: Textanfang als Titel
            "ort": ort,
            "absender": absender,
            "datum": datum,
            "link": n.get("webUrl") or "",
        },
    }


def lade(graph) -> list[dict]:
    """Alle Nachrichten aus allen Kanälen aller eigenen Teams sowie aus allen persönlichen Chats."""
    docs = []
    for team in graph.get_all("/me/joinedTeams"):
        for kanal in graph.get_all(f"/teams/{team['id']}/channels"):
            for n in graph.get_all(f"/teams/{team['id']}/channels/{kanal['id']}/messages"):
                docs.append(_nachricht_zu_dokument(n, f"{team['displayName']} > {kanal['displayName']}"))
                # Antworten im Thread gehören inhaltlich dazu
                for antwort in graph.get_all(
                        f"/teams/{team['id']}/channels/{kanal['id']}/messages/{n['id']}/replies"):
                    docs.append(_nachricht_zu_dokument(antwort, f"{team['displayName']} > {kanal['displayName']}"))

    for chat in graph.get_all("/me/chats"):
        name = chat.get("topic") or "Chat"  # 1:1-Chats haben kein Thema
        for n in graph.get_all(f"/me/chats/{chat['id']}/messages"):
            docs.append(_nachricht_zu_dokument(n, f"Chat: {name}"))
    return [d for d in docs if d]  # None-Einträge (Systemmeldungen) entfernen
