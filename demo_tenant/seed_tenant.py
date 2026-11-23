"""Lädt die von erzeuge.py vorbereiteten Testdaten für EINEN Nutzer in den Test-Tenant.

Jeder Nutzer meldet sich selbst per Gerätecode an (delegierte Rechte, nur eigene Daten). Dadurch landen OneNote,
Postfach, Kalender und OneDrive wirklich beim richtigen Konto. Mehrfaches Ausführen legt nichts doppelt an.

Aufruf (nacheinander für jeden Nutzer):
    python demo_tenant/erzeuge.py                  # einmal: Dateien + plan.json erzeugen
    python demo_tenant/seed_tenant.py jonas        # Kürzel siehe kunden.NUTZER

Client-ID/Tenant-ID kommen wie überall aus der .env (CLIENT_ID, TENANT_ID). Der Token-Cache je Nutzer liegt in
TOKEN_DIR (Standard: ~/.kampilot_tokens), nie im Repository.

NUR für den Test-Tenant gedacht. Termine mit Teilnehmenden verschicken echte Einladungen an die Testkonten.
"""
import html
import json
import os
import re
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import msal
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from kunden import NUTZER  # noqa: E402

AUSGABE = Path(__file__).parent / "ausgabe"
TEAM = "KAM-Pilot"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["User.Read", "Notes.ReadWrite", "Mail.ReadWrite", "Calendars.ReadWrite", "Files.ReadWrite.All",
          "Team.ReadBasic.All", "Channel.ReadBasic.All", "Channel.Create", "ChannelMessage.Send",
          "ChannelMessage.Read.All", "Chat.Create", "ChatMessage.Send", "Chat.Read"]
TOKEN_DIR = Path(os.getenv("TOKEN_DIR", Path.home() / ".kampilot_tokens"))


class Graph:
    """Minimaler Graph-Client mit Gerätecode-Login und Wiederholung bei Drosselung (429)."""

    def __init__(self, kuerzel: str):
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self.cache_datei = TOKEN_DIR / f"{kuerzel}.json"
        self.cache = msal.SerializableTokenCache()
        if self.cache_datei.exists():
            self.cache.deserialize(self.cache_datei.read_text())
        self.app = msal.PublicClientApplication(config.CLIENT_ID, token_cache=self.cache,
                                                authority=f"https://login.microsoftonline.com/{config.TENANT_ID}")
        self.erwartet = NUTZER[kuerzel]["upn"].lower()

    def token(self) -> str:
        konten = [a for a in self.app.get_accounts() if a["username"].lower() == self.erwartet]
        ergebnis = self.app.acquire_token_silent(SCOPES, account=konten[0]) if konten else None
        if not ergebnis:
            flow = self.app.initiate_device_flow(scopes=SCOPES)
            print(f"\n>>> Anmelden als {self.erwartet}: {flow['verification_uri']}  Code: {flow['user_code']}\n", flush=True)
            ergebnis = self.app.acquire_token_by_device_flow(flow)
            if "access_token" not in ergebnis:
                raise RuntimeError(ergebnis.get("error_description"))
            angemeldet = ergebnis.get("id_token_claims", {}).get("preferred_username", "").lower()
            if angemeldet != self.erwartet:
                raise RuntimeError(f"Falsches Konto angemeldet: {angemeldet} statt {self.erwartet}")
        self.cache_datei.write_text(self.cache.serialize())
        return ergebnis["access_token"]

    def request(self, methode: str, pfad: str, **kw) -> requests.Response:
        url = pfad if pfad.startswith("http") else GRAPH + pfad
        extra = kw.pop("headers", {})
        for versuch in range(12):
            headers = {"Authorization": "Bearer " + self.token(), **extra}
            r = requests.request(methode, url, headers=headers, timeout=60, **kw)
            if r.status_code in (429, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 5 * (versuch + 1))))
                continue
            # Neue Konten: der OneNote-Dienst antwortet in den ersten Stunden zeitweise mit 401/403 (40001, 40007),
            # gerade angelegte Abschnitte sind kurz "nicht gefunden" (404, 20102) -> warten und wiederholen
            if "/onenote/" in url and r.status_code in (401, 403, 404) and any(
                    c in r.text for c in ("40001", "40007", "20102")):
                time.sleep(15)
                continue
            return r
        return r

    def ok(self, methode: str, pfad: str, **kw) -> dict:
        r = self.request(methode, pfad, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{methode} {pfad}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def alle(self, pfad: str) -> list[dict]:
        werte, url = [], pfad
        while url:
            d = self.ok("GET", url)
            werte += d.get("value", [])
            url = d.get("@odata.nextLink")
        return werte


def als_html(text: str) -> str:
    return "<br>".join(html.escape(z) for z in text.splitlines())


def schritt(name: str, fehler: list):
    """Dekorator-Ersatz: führt eine Teilaufgabe aus, Fehler werden gesammelt statt abzubrechen."""
    def wrapper(funktion, *args):
        try:
            funktion(*args)
        except Exception as e:
            fehler.append(f"{name}: {e}")
            print("  FEHLER", name, e)
    return wrapper


# =============================================================================
# Teilaufgaben
# =============================================================================

def seitentitel(g: Graph, seite: dict) -> str:
    """Titel einer OneNote-Seite. Bei frisch angelegten Seiten liefert die Seitenliste den Titel teils noch leer
    (OneNote indexiert verzögert). Dann aus dem Inhalt lesen, sonst würde die Seite als fehlend doppelt angelegt."""
    if seite.get("title"):
        return seite["title"]
    r = g.request("GET", f"/me/onenote/pages/{seite['id']}/content")
    treffer = re.search(r"<title>(.*?)</title>", r.text) if r.status_code == 200 else None
    return html.unescape(treffer.group(1)) if treffer else ""


def onenote(g: Graph, seiten: list[dict]) -> None:
    if not seiten:
        return
    nb = next((n for n in g.alle("/me/onenote/notebooks") if n["displayName"] == config.NOTEBOOK_NAME), None)
    nb = nb or g.ok("POST", "/me/onenote/notebooks", json={"displayName": config.NOTEBOOK_NAME})
    abschnitte = {s["displayName"]: s for s in g.alle(f"/me/onenote/notebooks/{nb['id']}/sections")}
    for s in seiten:
        name = s["abschnitt"].replace("&", "und")[:50]  # OneNote erlaubt kein & in Abschnittsnamen
        if name not in abschnitte:
            abschnitte[name] = g.ok("POST", f"/me/onenote/notebooks/{nb['id']}/sections", json={"displayName": name})
        vorhanden = [seitentitel(g, p) for p in g.alle(f"/me/onenote/sections/{abschnitte[name]['id']}/pages")]
        if s["seite"] in vorhanden:
            continue
        seite = (f"<html><head><title>{html.escape(s['seite'])}</title>"
                 f'<meta name="created" content="{s["datum"]}T09:00:00+01:00" /></head>'
                 f"<body><p>{als_html(s['text'])}</p></body></html>")
        g.ok("POST", f"/me/onenote/sections/{abschnitte[name]['id']}/pages", data=seite.encode("utf-8"),
             headers={"Content-Type": "text/html"})
        print("  OneNote:", name, "/", s["seite"])


def mails(g: Graph, liste: list[dict], ordner: str) -> None:
    """Mails mit Originaldatum direkt in Posteingang bzw. 'Gesendete Elemente' legen (wie seed_graph.py)."""
    if not liste:
        return
    vorhanden = {(m["subject"], (m.get("receivedDateTime") or "")[:10])
                 for m in g.alle(f"/me/mailFolders/{ordner}/messages?$select=subject,receivedDateTime&$top=200")}
    for m in liste:
        if (m["betreff"], m["datum"]) in vorhanden:
            continue
        h = zlib.crc32(m["betreff"].encode())  # feste, aber unterschiedliche Uhrzeit je Mail
        zeit = f"{m['datum']}T{6 + h % 10:02d}:{h % 60:02d}:00Z"
        g.ok("POST", f"/me/mailFolders/{ordner}/messages", json={
            "subject": m["betreff"], "body": {"contentType": "html", "content": als_html(m["text"])},
            "from": {"emailAddress": {"name": m["von_name"], "address": m["von_mail"]}},
            "toRecipients": [{"emailAddress": {"address": a}} for a in m.get("an", [])] or
                            [{"emailAddress": {"address": g.erwartet}}],
            "isRead": True,
            "singleValueExtendedProperties": [{"id": "Integer 0x0E07", "value": "1"},
                                              {"id": "SystemTime 0x0E06", "value": zeit},
                                              {"id": "SystemTime 0x0039", "value": zeit}]})
        print(f"  Mail ({ordner}):", m["datum"], m["betreff"])


def termine(g: Graph, liste: list[dict]) -> None:
    if not liste:
        return
    vorhanden = {(t["subject"], t["start"]["dateTime"][:10]) for t in
                 g.alle("/me/calendarView?startDateTime=2026-01-01T00:00:00&endDateTime=2027-12-31T23:59:59"
                        "&$select=subject,start&$top=200")}
    for t in liste:
        if (t["betreff"], t["tag"]) in vorhanden:
            continue
        g.ok("POST", "/me/events", json={
            "subject": t["betreff"], "body": {"contentType": "html", "content": als_html(t["text"])},
            "start": {"dateTime": f"{t['tag']}T{t['von']}:00", "timeZone": "W. Europe Standard Time"},
            "end": {"dateTime": f"{t['tag']}T{t['bis']}:00", "timeZone": "W. Europe Standard Time"},
            "location": {"displayName": t["ort"]},
            "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in t["teilnehmer"]]})
        print("  Termin:", t["tag"], t["betreff"])


def onedrive(g: Graph, liste: list[dict]) -> None:
    for f in liste:
        pfad = quote(f["ziel"])
        g.ok("PUT", f"/me/drive/root:/{pfad}:/content", data=(AUSGABE / f["datei"]).read_bytes())
        print("  OneDrive:", f["ziel"])


def team_und_kanaele(g: Graph, namen: set[str]) -> tuple[dict, dict]:
    team = next((t for t in g.alle("/me/joinedTeams") if t["displayName"] == TEAM), None)
    if team is None:
        raise RuntimeError(f'Team "{TEAM}" nicht gefunden oder Nutzer ist kein Mitglied')
    kanaele = {k["displayName"]: k for k in g.alle(f"/teams/{team['id']}/channels")}
    for n in sorted(namen - set(kanaele)):
        kanaele[n] = g.ok("POST", f"/teams/{team['id']}/channels",
                          json={"displayName": n, "description": f"Kunde {n}", "membershipType": "standard"})
        print("  Kanal angelegt:", n)
    return team, kanaele


def kanal_posts(g: Graph, team: dict, kanaele: dict, liste: list[dict], name: str) -> None:
    for p in liste:
        pfad = f"/teams/{team['id']}/channels/{kanaele[p['kanal']]['id']}/messages"
        kopf = f"[{p['datum']} – {name}]"
        if any(kopf in (m["body"]["content"] or "") and p["text"][:30] in (m["body"]["content"] or "")
               for m in g.alle(pfad)):
            continue
        g.ok("POST", pfad, json={"body": {"contentType": "html", "content": f"<b>{html.escape(kopf)}</b><br>{als_html(p['text'])}"}})
        print("  Teams:", p["kanal"], "-", p["text"][:50])


def kanal_dateien(g: Graph, team: dict, kanaele: dict, liste: list[dict]) -> None:
    for f in liste:
        for versuch in range(5):  # der Dateiordner eines neuen Kanals entsteht verzögert
            r = g.request("GET", f"/teams/{team['id']}/channels/{kanaele[f['kanal']]['id']}/filesFolder")
            if r.status_code == 200:
                break
            time.sleep(10)
        ordner = r.json()
        g.ok("PUT", f"/drives/{ordner['parentReference']['driveId']}/items/{ordner['id']}:/{quote(f['name'])}:/content",
             data=(AUSGABE / f["datei"]).read_bytes())
        print("  Teams-Datei:", f["kanal"], "/", f["name"])


def chats(g: Graph, liste: list[dict], name: str) -> None:
    for c in liste:
        chat = g.ok("POST", "/chats", json={"chatType": "oneOnOne", "members": [
            {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
             "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{u}')"} for u in (g.erwartet, c["mit"])]})
        pfad = f"/chats/{chat['id']}/messages"
        kopf = f"[{c['datum']} – {name}]"
        if any(kopf in (m.get("body", {}).get("content") or "") for m in g.alle(pfad)):
            continue
        g.ok("POST", pfad, json={"body": {"contentType": "html", "content": f"<b>{html.escape(kopf)}</b><br>{als_html(c['text'])}"}})
        print("  Chat mit", c["mit"], ":", c["text"][:50])


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in NUTZER:
        sys.exit(f"Aufruf: python demo_tenant/seed_tenant.py <{'|'.join(NUTZER)}> [--nur-onenote|--ohne-onenote|--nur-onedrive]")
    kuerzel = sys.argv[1]
    plan = json.loads((AUSGABE / "plan.json").read_text(encoding="utf-8"))[kuerzel]
    g = Graph(kuerzel)
    print("Angemeldet als", g.ok("GET", "/me")["userPrincipalName"], "–", datetime.now().strftime("%H:%M"))
    fehler = []
    s = lambda name: schritt(name, fehler)  # noqa: E731
    if sys.argv[2:] not in (["--ohne-onenote"], ["--nur-onedrive"]):
        s("OneNote")(onenote, g, plan["onenote"])
    if sys.argv[2:] == ["--nur-onenote"]:
        print("Fertig (nur OneNote)." + (f" Fehler: {fehler}" if fehler else ""))
        return
    if sys.argv[2:] == ["--nur-onedrive"]:  # z. B. nach neuen Ordnern: nur Dateien (vorhandene werden überschrieben)
        s("OneDrive")(onedrive, g, plan["onedrive"])
        print("Fertig (nur OneDrive)." + (f" Fehler: {fehler}" if fehler else ""))
        return
    s("Posteingang")(mails, g, plan["inbox"], "inbox")
    s("Gesendet")(mails, g, plan["gesendet"], "sentitems")
    s("Termine")(termine, g, plan["termine"])
    s("OneDrive")(onedrive, g, plan["onedrive"])
    if plan["kanal_posts"] or plan["kanal_dateien"]:
        try:
            team, kanaele = team_und_kanaele(g, {p["kanal"] for p in plan["kanal_posts"] + plan["kanal_dateien"]})
            s("Teams-Nachrichten")(kanal_posts, g, team, kanaele, plan["kanal_posts"], NUTZER[kuerzel]["name"])
            s("Teams-Dateien")(kanal_dateien, g, team, kanaele, plan["kanal_dateien"])
        except Exception as e:
            fehler.append(f"Teams: {e}")
    s("Chats")(chats, g, plan["chats"], NUTZER[kuerzel]["name"])
    print(f"\nFertig für {NUTZER[kuerzel]['name']}." + (f" {len(fehler)} Fehler:\n- " + "\n- ".join(fehler) if fehler else " Keine Fehler."))


if __name__ == "__main__":
    main()
