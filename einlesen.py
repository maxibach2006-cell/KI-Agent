"""Einlesen im Hintergrund: beim ersten Öffnen der App und danach regelmäßig ohne Zutun des Nutzers.

Rolle im System:
    Im Serverbetrieb gibt die Cloudflare-Anmeldung dem Agenten keinen Zugriff auf Microsoft 365. Beim ersten Mal
    zeigt die App deshalb Link und Code an (app.py), und der Nutzer gibt den Zugriff frei. Das Token bleibt in der
    Datei des Nutzers (config.token_cache), spätere Läufe kommen ohne Anmeldung aus, bis es ungültig wird.

Ablauf von _arbeite() je Auftrag:
    "anmeldung"   Token prüfen, ggf. auf den Gerätecode-Login warten. Bis zu 15 Minuten, belegt die GPU nicht.
    "wartet"      Ein anderer Nutzer wird gerade eingelesen.
    "laeuft"      ingest(): Daten holen und Embeddings berechnen, immer nur ein Nutzer gleichzeitig.
    "fertig" / "fehler"

Die Aufträge liegen im Speicher des Serverprozesses. Nach einem Neustart startet das nächste Öffnen der App neu: Das
Token liegt im Volume, und ingest() rechnet bereits gespeicherte Abschnitte nicht noch einmal.
"""
import threading
import time

import config
from ingest import ingest

AKTIV = ("anmeldung", "wartet", "laeuft")

_sperre = threading.Lock()         # schützt _auftraege
_sperre_einlesen = threading.Lock()  # nur ein Einlesen gleichzeitig, sonst bremsen sie sich auf der GPU gegenseitig aus
_auftraege: dict[str, dict] = {}   # Schlüssel: Adresse in Kleinschreibung


def _setze(nutzer: str, **werte) -> None:
    with _sperre:
        _auftraege[nutzer.lower()].update(werte)


def auftrag(nutzer: str) -> dict | None:
    """Stand des letzten Auftrags dieses Nutzers (Kopie), None = in diesem Serverprozess noch keiner.
    Enthält den Anmeldecode: nur an die Sitzung geben, die als dieser Nutzer angemeldet ist."""
    with _sperre:
        eintrag = _auftraege.get(nutzer.lower())
        return dict(eintrag) if eintrag else None


def noetig(nutzer: str) -> bool:
    """Muss für diesen Nutzer eingelesen werden? Wird bei jedem Seitenaufbau gefragt und ist deshalb billig.

    Der letzte Versuch zählt mit: Sonst würde ein fehlgeschlagenes Einlesen bei jedem Klick neu starten. Nach einem
    Fehler startet deshalb nur der Button in der App vorzeitig neu.
    """
    jetzt, abstand = time.time(), config.EINLESEN_ALLE_STUNDEN * 3600
    letzter = auftrag(nutzer)
    if letzter and (letzter["zustand"] in AKTIV or jetzt - letzter["gestartet"] < abstand):
        return False
    stand = config.index_stand(nutzer)
    return stand is None or jetzt - stand >= abstand


def starte(nutzer: str) -> bool:
    """Startet einen Auftrag im Hintergrund, außer es läuft schon einer für diesen Nutzer."""
    with _sperre:
        letzter = _auftraege.get(nutzer.lower())
        if letzter and letzter["zustand"] in AKTIV:
            return False
        _auftraege[nutzer.lower()] = {"zustand": "anmeldung", "gestartet": time.time(), "link": None, "code": None,
                                      "meldung": "", "unvollstaendig": []}
    threading.Thread(target=_arbeite, args=(nutzer,), daemon=True, name=f"einlesen-{nutzer}").start()
    return True


def _arbeite(nutzer: str) -> None:
    from graph_client import GraphClient  # erst hier: Demo-Betrieb und Tests brauchen kein msal

    def melde_anmeldung(flow: dict) -> None:
        _setze(nutzer, link=flow["verification_uri"], code=flow["user_code"])

    try:
        graph = GraphClient(config.EINLESE_SCOPES, nutzer, melde_anmeldung=melde_anmeldung)
        graph.anmelden()  # vor der Sperre: Wer seinen Code nicht eingibt, hält niemanden auf
        _setze(nutzer, zustand="wartet", link=None, code=None)
        with _sperre_einlesen:
            _setze(nutzer, zustand="laeuft")
            unvollstaendig = ingest("graph", nutzer=nutzer, graph=graph)
        _setze(nutzer, zustand="fertig", unvollstaendig=unvollstaendig, link=None, code=None)
    except Exception as e:  # jeder Fehler muss beim Nutzer ankommen, sonst wartet die Seite für immer
        print(f"Einlesen für {nutzer} fehlgeschlagen: {e}")
        _setze(nutzer, zustand="fehler", meldung=str(e), link=None, code=None)
