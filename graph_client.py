"""Kleiner Client für Microsoft Graph (die Programmierschnittstelle von Microsoft 365).

Anmeldung per Device-Code-Flow (delegiert): Man öffnet einen Link, gibt einen Code ein und meldet
sich mit dem eigenen Konto an. Graph liefert dann nur Daten, auf die DIESER Nutzer Zugriff hat.
Das Token wird lokal gespeichert, damit man sich nicht jedes Mal anmelden muss: mit Nutzerangabe in einer eigenen
Datei je Konto (config.token_cache), sonst in .token_cache.json.

Mehrere Nutzer auf einem Rechner/Server: IMMER mit Nutzer aufrufen (GraphClient(scopes, nutzer="anna@firma.de")).
Dann wird nur das Token dieses Kontos verwendet, und eine Anmeldung mit einem anderen Konto wird abgelehnt.
Ohne Nutzer und mit mehreren Konten im Cache bricht der Client ab, statt still das erste Konto zu nehmen.

Die Klasse kapselt drei technische Details, damit die Connectoren nur noch Pfade angeben müssen:
    1. Anmeldung und Token-Erneuerung       (_token)
    2. Wiederholen bei Drosselung (HTTP 429)  (request)
    3. Seitenweises Abholen langer Listen     (get_all)
"""
import time
from pathlib import Path

import msal
import requests

import config

GRAPH = "https://graph.microsoft.com/v1.0"  # Basis-URL; Pfade wie "/me/messages" werden angehängt


def waehle_konto(konten: list[dict], nutzer: str | None) -> dict | None:
    """Konto aus dem Token-Cache, dessen Token verwendet werden darf (None = neu anmelden).

    Mit Nutzer: nur genau dieses Konto. Ohne Nutzer: das einzige Konto; bei mehreren Konten Abbruch, denn sonst
    bekäme ein zweiter Nutzer beim Einlesen still die Daten des ersten (Fehler aus dem Server-PR).
    """
    if nutzer:
        return next((k for k in konten if k.get("username", "").lower() == nutzer.lower()), None)
    if len(konten) > 1:
        namen = ", ".join(k.get("username", "?") for k in konten)
        raise RuntimeError(f"Mehrere Konten im Token-Cache ({namen}). Bitte den Nutzer angeben, "
                           "z. B. python ingest.py --source graph --nutzer anna@firma.de")
    return konten[0] if konten else None


def pruefe_anmeldung(ergebnis: dict, nutzer: str | None) -> None:
    """Nach dem Gerätecode-Login: Wurde wirklich das erwartete Konto angemeldet?"""
    angemeldet = (ergebnis.get("id_token_claims") or {}).get("preferred_username", "").lower()
    if nutzer and angemeldet != nutzer.lower():
        raise RuntimeError(f"Falsches Konto angemeldet: {angemeldet or 'unbekannt'} statt {nutzer}. "
                           "Tipp: im privaten Browserfenster anmelden.")


class GraphClient:
    """Verbindung zu Microsoft Graph für einen angemeldeten Nutzer.

    Parameter:
        scopes: Berechtigungen, die beim Anmelden angefragt werden (config.READ_SCOPES oder SEED_SCOPES)
        nutzer: erwartetes Konto (UPN). Empfohlen, sobald mehr als ein Nutzer auf demselben Rechner einliest.
        melde_anmeldung: bekommt Link und Code der Anmeldung (dict von MSAL) statt der Ausgabe im Terminal.
            Auf dem Server nötig, sonst stünde der Code im Log und jeder mit Log-Zugriff könnte ihn benutzen.
    """

    def __init__(self, scopes: list[str], nutzer: str | None = None, melde_anmeldung=None):
        if not config.CLIENT_ID:
            raise RuntimeError("CLIENT_ID fehlt – bitte .env anlegen (siehe .env.example).")
        self.scopes = scopes
        self.nutzer = nutzer.lower() if nutzer else None
        self.melde_anmeldung = melde_anmeldung
        self.cache_datei = config.token_cache(nutzer)
        self.probleme: list[str] = []  # Teilfehler der Connectoren (siehe melde_problem)
        self.dateien_cache: Path | None = None  # bereits gelesene Dateien (connectors/files.py), setzt ingest.py
        # Token-Cache aus der Datei laden, damit eine frühere Anmeldung wiederverwendet wird
        self.cache = msal.SerializableTokenCache()
        if self.cache_datei.exists():
            self.cache.deserialize(self.cache_datei.read_text())
        # "Public Client" = Desktop-App ohne geheimen Schlüssel; die Identität kommt allein vom Nutzer
        self.app = msal.PublicClientApplication(
            config.CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{config.TENANT_ID}",
            token_cache=self.cache,
        )

    def melde_problem(self, text: str) -> None:
        """Ein Connector konnte einen Teil seiner Quelle nicht lesen. ingest.py behält dann deren alte Abschnitte."""
        print(f"  Problem: {text}")
        self.probleme.append(text)

    def _token(self) -> str:
        """Gültiges Zugriffstoken holen: erst still aus dem Cache, sonst per Device-Code-Anmeldung."""
        konto = waehle_konto(self.app.get_accounts(), self.nutzer)
        ergebnis = self.app.acquire_token_silent(self.scopes, account=konto) if konto else None
        if not ergebnis:
            flow = self.app.initiate_device_flow(scopes=self.scopes)
            if "message" not in flow:  # z. B. App-Registrierung falsch eingerichtet
                raise RuntimeError(f"Anmeldung nicht möglich: {flow.get('error_description')}")
            if self.melde_anmeldung:
                self.melde_anmeldung(flow)
            else:
                if self.nutzer:
                    print(f"Bitte als {self.nutzer} anmelden:")
                print(flow["message"])  # "Öffnen Sie https://microsoft.com/devicelogin und geben Sie den Code ... ein"
            ergebnis = self.app.acquire_token_by_device_flow(flow)  # wartet, bis der Nutzer sich angemeldet hat
            if "access_token" in ergebnis:
                pruefe_anmeldung(ergebnis, self.nutzer)  # falsches Konto -> abbrechen, nichts speichern
        if "access_token" not in ergebnis:
            raise RuntimeError(f"Anmeldung fehlgeschlagen: {ergebnis.get('error_description')}")
        if self.cache.has_state_changed:  # neues oder erneuertes Token -> Cache-Datei aktualisieren
            self.cache_datei.write_text(self.cache.serialize())
            self.cache.has_state_changed = False
        return ergebnis["access_token"]

    def anmelden(self) -> None:
        """Anmeldung vorab erledigen, ohne schon Daten zu lesen (wartet ggf. auf den Gerätecode-Login)."""
        self._token()

    def request(self, methode: str, pfad: str, **kwargs) -> requests.Response:
        """Eine HTTP-Anfrage an Graph mit Token. Bei Drosselung bis zu 5 Versuche.

        pfad: relativer Pfad ("/me/messages") oder vollständige URL (z. B. ein @odata.nextLink)
        """
        url = pfad if pfad.startswith("http") else GRAPH + pfad
        headers = {"Authorization": f"Bearer {self._token()}", **(kwargs.pop("headers", None) or {})}
        for _ in range(5):
            r = requests.request(methode, url, headers=headers, timeout=60, **kwargs)
            if r.status_code in (429, 503):  # Graph drosselt -> kurz warten und erneut versuchen
                warten = r.headers.get("Retry-After", "5")  # Graph sagt, wie lange gewartet werden soll
                time.sleep(int(warten) if warten.isdigit() else 5)
                continue
            # Die OneNote-API lehnt gültige Tokens zeitweise mit Code 40001 ab (gleiches Token, gleicher Pfad:
            # mal 200, mal 401; beobachtet im neuen Test-Tenant). Ein neuer Versuch reicht dann meist aus.
            if r.status_code == 401 and '"40001"' in r.text:
                time.sleep(2)
                continue
            r.raise_for_status()  # andere Fehler (z. B. 403 fehlende Berechtigung) als Ausnahme melden
            return r
        r.raise_for_status()
        return r

    def get(self, pfad: str, **kwargs) -> dict:
        """GET-Anfrage, Antwort als JSON-Objekt."""
        return self.request("GET", pfad, **kwargs).json()

    def get_bytes(self, pfad: str) -> bytes:
        """GET-Anfrage, Antwort als Rohdaten (z. B. Dateiinhalt)."""
        return self.request("GET", pfad).content

    def get_all(self, pfad: str, maximal: int | None = None, **kwargs) -> list[dict]:
        """Holt die Einträge einer Liste und folgt dabei den Seiten (@odata.nextLink).

        Graph liefert lange Listen (z. B. 500 Mails) nur seitenweise; jede Seite enthält den Link zur nächsten.
        maximal: keine weiteren Seiten holen, sobald so viele Einträge vorliegen.
        """
        eintraege, url = [], pfad
        while url and (maximal is None or len(eintraege) < maximal):
            daten = self.get(url, **kwargs)
            eintraege += daten.get("value", [])
            url = daten.get("@odata.nextLink")  # fehlt auf der letzten Seite -> Schleife endet
        return eintraege

    def post(self, pfad: str, **kwargs) -> dict:
        """POST-Anfrage (Anlegen). Manche Endpunkte antworten ohne Inhalt -> leeres dict."""
        r = self.request("POST", pfad, **kwargs)
        return r.json() if r.content else {}

    def put(self, pfad: str, **kwargs) -> dict:
        """PUT-Anfrage (z. B. Datei hochladen)."""
        return self.request("PUT", pfad, **kwargs).json()
