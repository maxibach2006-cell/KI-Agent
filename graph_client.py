"""Kleiner Client für Microsoft Graph (die Programmierschnittstelle von Microsoft 365).

Anmeldung per Device-Code-Flow (delegiert): Man öffnet einen Link, gibt einen Code ein und meldet
sich mit dem eigenen Konto an. Graph liefert dann nur Daten, auf die DIESER Nutzer Zugriff hat.
Das Token wird lokal in .token_cache.json gespeichert, damit man sich nicht jedes Mal anmelden muss.

Die Klasse kapselt drei technische Details, damit die Connectoren nur noch Pfade angeben müssen:
    1. Anmeldung und Token-Erneuerung       (_token)
    2. Wiederholen bei Drosselung (HTTP 429)  (request)
    3. Seitenweises Abholen langer Listen     (get_all)
"""
import time

import msal
import requests

import config

GRAPH = "https://graph.microsoft.com/v1.0"  # Basis-URL; Pfade wie "/me/messages" werden angehängt


class GraphClient:
    """Verbindung zu Microsoft Graph für einen angemeldeten Nutzer.

    Parameter:
        scopes: Berechtigungen, die beim Anmelden angefragt werden (config.READ_SCOPES oder SEED_SCOPES)
    """

    def __init__(self, scopes: list[str]):
        if not config.CLIENT_ID:
            raise RuntimeError("CLIENT_ID fehlt – bitte .env anlegen (siehe .env.example).")
        self.scopes = scopes
        # Token-Cache aus der Datei laden, damit eine frühere Anmeldung wiederverwendet wird
        self.cache = msal.SerializableTokenCache()
        if config.TOKEN_CACHE.exists():
            self.cache.deserialize(config.TOKEN_CACHE.read_text())
        # "Public Client" = Desktop-App ohne geheimen Schlüssel; die Identität kommt allein vom Nutzer
        self.app = msal.PublicClientApplication(
            config.CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{config.TENANT_ID}",
            token_cache=self.cache,
        )

    def _token(self) -> str:
        """Gültiges Zugriffstoken holen: erst still aus dem Cache, sonst per Device-Code-Anmeldung."""
        konten = self.app.get_accounts()
        ergebnis = self.app.acquire_token_silent(self.scopes, account=konten[0]) if konten else None
        if not ergebnis:
            flow = self.app.initiate_device_flow(scopes=self.scopes)
            print(flow["message"])  # "Öffnen Sie https://microsoft.com/devicelogin und geben Sie den Code ... ein"
            ergebnis = self.app.acquire_token_by_device_flow(flow)  # wartet, bis der Nutzer sich angemeldet hat
        if "access_token" not in ergebnis:
            raise RuntimeError(f"Anmeldung fehlgeschlagen: {ergebnis.get('error_description')}")
        if self.cache.has_state_changed:  # neues oder erneuertes Token -> Cache-Datei aktualisieren
            config.TOKEN_CACHE.write_text(self.cache.serialize())
        return ergebnis["access_token"]

    def request(self, methode: str, pfad: str, **kwargs) -> requests.Response:
        """Eine HTTP-Anfrage an Graph mit Token. Bei Drosselung bis zu 5 Versuche.

        pfad: relativer Pfad ("/me/messages") oder vollständige URL (z. B. ein @odata.nextLink)
        """
        url = pfad if pfad.startswith("http") else GRAPH + pfad
        headers = {"Authorization": f"Bearer {self._token()}", **(kwargs.pop("headers", None) or {})}
        for _ in range(5):
            r = requests.request(methode, url, headers=headers, timeout=60, **kwargs)
            if r.status_code in (429, 503):  # Graph drosselt -> kurz warten und erneut versuchen
                time.sleep(int(r.headers.get("Retry-After", 5)))  # Graph sagt, wie lange gewartet werden soll
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

    def get_all(self, pfad: str, **kwargs) -> list[dict]:
        """Holt alle Einträge einer Liste und folgt dabei den Seiten (@odata.nextLink).

        Graph liefert lange Listen (z. B. 500 Mails) nur seitenweise; jede Seite enthält den Link zur nächsten.
        """
        eintraege, url = [], pfad
        while url:
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
