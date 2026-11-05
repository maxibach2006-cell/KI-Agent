"""Teams-Connector: Kanalnachrichten (inkl. Antworten im Thread) der eigenen Teams und persönliche Chats."""
import re

import requests

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


def _lies_nachrichten(graph, pfad: str, ort: str, docs: list, mit_antworten: bool = False) -> None:
    """Nachrichten eines Kanals oder Chats an docs anhängen. Ein gesperrter Kanal oder Chat darf die übrigen
    nicht verhindern; das Problem wird gemeldet, damit ingest.py die bisherigen Teams-Daten behält."""
    try:
        # Antworten im Thread gehören inhaltlich dazu; $expand spart einen eigenen Aufruf je Nachricht
        for n in graph.get_all(pfad + "?$expand=replies" if mit_antworten else pfad):
            docs.append(_nachricht_zu_dokument(n, ort))
            docs += [_nachricht_zu_dokument(antwort, ort) for antwort in n.get("replies", [])]
    except requests.RequestException as e:
        graph.melde_problem(f"{ort}: {e}")


def lade(graph) -> list[dict]:
    """Alle Nachrichten aus allen Kanälen aller eigenen Teams sowie aus allen persönlichen Chats."""
    docs = []
    for team in graph.get_all("/me/joinedTeams"):
        try:
            kanaele = graph.get_all(f"/teams/{team['id']}/channels")
        except requests.RequestException as e:
            graph.melde_problem(f"{team['displayName']}: {e}")
            continue
        for kanal in kanaele:
            _lies_nachrichten(graph, f"/teams/{team['id']}/channels/{kanal['id']}/messages",
                              f"{team['displayName']} > {kanal['displayName']}", docs, mit_antworten=True)

    try:
        chats = graph.get_all("/me/chats")
    except requests.RequestException as e:
        graph.melde_problem(f"Chats: {e}")
        chats = []
    for chat in chats:
        name = chat.get("topic") or "Chat"  # 1:1-Chats haben kein Thema
        _lies_nachrichten(graph, f"/me/chats/{chat['id']}/messages", f"Chat: {name}", docs)
    return [d for d in docs if d]  # None-Einträge (Systemmeldungen) entfernen
