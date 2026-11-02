"""Befüllt einen Microsoft-365-TEST-Tenant mit den fiktiven Daten aus demo_data/.

Zweck:
    Damit lässt sich der echte Graph-Weg (Anmeldung, Connectoren, Berechtigungen) testen, ohne
    echte Kundendaten zu verwenden. Nach dem Befüllen liest "python ingest.py --source graph"
    dieselben Inhalte wie der Demo-Modus, nur eben über Microsoft 365.

Vorher manuell in Teams ein Team mit dem Namen aus config.TEAM_NAME anlegen ("Key Account - Kunden").
Das Skript legt dann an:
  - OneNote-Notizbuch "MBS 2" mit Abschnitten und Seiten (mit ursprünglichem Erstelldatum)
  - E-Mails im Posteingang (mit ursprünglichem Empfangsdatum)
  - Kalendertermine (relativ zu heute: letzte, diese und nächste Woche)
  - Kanäle und Nachrichten im Team
  - Dateien (.eml, .docx, ...) in der SharePoint-Bibliothek des Teams
Mehrfaches Ausführen legt nichts doppelt an (vor jedem Anlegen wird geprüft, ob es den Eintrag schon gibt).

NUR für einen Test-Tenant gedacht, nicht für ein echtes Firmenpostfach!
"""
import html
import json
from datetime import timedelta

import config
from graph_client import GraphClient
from local_loader import demo_termin_tag


def lade_json(name: str) -> list[dict]:
    """Eine Datei aus demo_data/ laden."""
    return json.loads((config.DEMO_DIR / name).read_text(encoding="utf-8"))


def als_html(text: str) -> str:
    """Klartext -> einfaches HTML (Sonderzeichen maskiert, Zeilenumbrüche als <br>)."""
    return "<br>".join(html.escape(z) for z in text.splitlines())


def seed_onenote(graph: GraphClient) -> None:
    """Notizbuch, Abschnitte und Seiten anlegen (fehlende Teile werden ergänzt)."""
    notizbuecher = graph.get_all("/me/onenote/notebooks")
    nb = next((n for n in notizbuecher if n["displayName"] == config.NOTEBOOK_NAME), None)
    if nb is None:
        nb = graph.post("/me/onenote/notebooks", json={"displayName": config.NOTEBOOK_NAME})
    abschnitte = {s["displayName"]: s for s in graph.get_all(f"/me/onenote/notebooks/{nb['id']}/sections")}

    for seite in lade_json("onenote.json"):
        abschnitt = abschnitte.get(seite["abschnitt"])
        if abschnitt is None:
            abschnitt = graph.post(f"/me/onenote/notebooks/{nb['id']}/sections",
                                   json={"displayName": seite["abschnitt"]})
            abschnitte[seite["abschnitt"]] = abschnitt
        titel = [p["title"] for p in graph.get_all(f"/me/onenote/sections/{abschnitt['id']}/pages")]
        if seite["seite"] in titel:
            continue  # Seite gibt es schon
        # <meta name="created"> setzt das ursprüngliche Erstelldatum -> "alte" Notizen bleiben alt
        seiten_html = (f"<html><head><title>{html.escape(seite['seite'])}</title>"
                       f'<meta name="created" content="{seite["datum"]}T09:00:00+01:00" /></head>'
                       f"<body><p>{als_html(seite['text'])}</p></body></html>")
        graph.post(f"/me/onenote/sections/{abschnitt['id']}/pages",
                   data=seiten_html.encode("utf-8"), headers={"Content-Type": "text/html"})
        print("OneNote:", seite["abschnitt"], "/", seite["seite"])


def seed_outlook(graph: GraphClient) -> None:
    """E-Mails direkt im Posteingang anlegen, als wären sie am Originaldatum empfangen worden."""
    vorhanden = {m["subject"] for m in graph.get_all("/me/mailFolders/inbox/messages?$select=subject&$top=100")}
    for mail in lade_json("outlook.json"):
        if mail["betreff"] in vorhanden:
            continue
        name, adresse = mail["absender"].rstrip(">").split(" <")  # "Max Muster <max@firma.de>" zerlegen
        zeit = f"{mail['datum']}T09:30:00Z"
        graph.post("/me/mailFolders/inbox/messages", json={
            "subject": mail["betreff"],
            "body": {"contentType": "html", "content": als_html(mail["text"])},
            "from": {"emailAddress": {"name": name, "address": adresse}},
            "isRead": True,
            # MAPI-Eigenschaften: als "empfangen" (nicht Entwurf) markieren und Datum zurücksetzen
            "singleValueExtendedProperties": [
                {"id": "Integer 0x0E07", "value": "1"},       # PR_MESSAGE_FLAGS = gelesen, kein Entwurf
                {"id": "SystemTime 0x0E06", "value": zeit},   # PR_MESSAGE_DELIVERY_TIME
                {"id": "SystemTime 0x0039", "value": zeit},   # PR_CLIENT_SUBMIT_TIME
            ],
        })
        print("Outlook:", mail["betreff"])


def seed_kalender(graph: GraphClient) -> None:
    """Termine relativ zur aktuellen Woche anlegen, damit "Was steht nächste Woche an?" Treffer hat."""
    heute = config.heute()
    vorhanden = {t["subject"] for t in graph.get_all(
        f"/me/calendarView?startDateTime={heute - timedelta(days=30)}T00:00:00"
        f"&endDateTime={heute + timedelta(days=60)}T23:59:59&$select=subject&$top=100")}
    for k in lade_json("kalender.json"):
        if k["betreff"] in vorhanden:
            continue
        tag = demo_termin_tag(k).isoformat()
        graph.post("/me/events", json={
            "subject": k["betreff"],
            "body": {"contentType": "html",
                     "content": als_html(f"Teilnehmende: {k['teilnehmende']}\n\n{k['text']}")},
            "start": {"dateTime": f"{tag}T{k['von']}:00", "timeZone": "W. Europe Standard Time"},
            "end": {"dateTime": f"{tag}T{k['bis']}:00", "timeZone": "W. Europe Standard Time"},
            "location": {"displayName": k["ort"]},
        })
        print("Kalender:", tag, k["betreff"])


def finde_team(graph: GraphClient) -> dict:
    """Das vorher manuell angelegte Team suchen (Teams lassen sich nicht ohne Weiteres per Graph anlegen)."""
    team = next((t for t in graph.get_all("/me/joinedTeams") if t["displayName"] == config.TEAM_NAME), None)
    if team is None:
        raise RuntimeError(f'Team "{config.TEAM_NAME}" nicht gefunden – bitte zuerst in Teams anlegen.')
    return team


def seed_teams(graph: GraphClient, team: dict) -> None:
    """Kanäle (einer je Kunde) und Nachrichten anlegen."""
    kanaele = {k["displayName"]: k for k in graph.get_all(f"/teams/{team['id']}/channels")}
    kanaele["Allgemein"] = graph.get(f"/teams/{team['id']}/primaryChannel")  # "General"/"Allgemein"

    for n in lade_json("teams.json"):
        kanal = kanaele.get(n["kanal"])
        if kanal is None:
            kanal = graph.post(f"/teams/{team['id']}/channels",
                               json={"displayName": n["kanal"], "membershipType": "standard"})
            kanaele[n["kanal"]] = kanal
        pfad = f"/teams/{team['id']}/channels/{kanal['id']}/messages"
        # Duplikatprüfung über den Textanfang (Nachrichten haben keinen eindeutigen Titel)
        if any(n["text"][:40] in (m["body"]["content"] or "") for m in graph.get_all(pfad)):
            continue
        # Teams-Nachrichten lassen sich nicht rückdatieren -> Originaldatum und Absender in den Text
        # (connectors/teams.py liest diese Kennzeichnung beim Einlesen wieder aus)
        kopf = f"<b>[{n['datum']} – {html.escape(n['absender'])}]</b><br>"
        graph.post(pfad, json={"subject": n["betreff"] or None,
                               "body": {"contentType": "html", "content": kopf + als_html(n["text"])}})
        print("Teams:", n["kanal"], "-", n["text"][:50])


def seed_dateien(graph: GraphClient, team: dict) -> None:
    """Dateien aus demo_data/sharepoint/ in die SharePoint-Ablage des Teams hochladen (überschreibt vorhandene)."""
    for datei in sorted((config.DEMO_DIR / "sharepoint").rglob("*")):
        if datei.is_file():
            ziel = f"{datei.parent.name}/{datei.name}"  # Unterordner je Kunde beibehalten
            graph.put(f"/groups/{team['id']}/drive/root:/{ziel}:/content", data=datei.read_bytes())
            print("SharePoint:", ziel)


if __name__ == "__main__":
    graph = GraphClient(config.SEED_SCOPES)  # Anmeldung mit Schreibrechten
    print("Angemeldet als", graph.get("/me")["userPrincipalName"])
    seed_onenote(graph)
    seed_outlook(graph)
    seed_kalender(graph)
    team = finde_team(graph)
    seed_teams(graph, team)
    seed_dateien(graph, team)
    print("Fertig.")
