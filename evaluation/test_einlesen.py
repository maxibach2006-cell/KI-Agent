"""Test: Einlesen im Hintergrund (einlesen.py), ohne Microsoft-Anmeldung und ohne Ollama.

Geprüft wird, was im Betrieb nicht auffallen würde: halbfertige Indizes, Anmeldecodes im Log, ein Nutzer, der mit
seinem nicht eingegebenen Code alle anderen aufhält, und zwei Einlesen gleichzeitig auf der GPU.

Aufruf:  python evaluation/test_einlesen.py
"""
import contextlib
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import einlesen  # noqa: E402
import graph_client  # noqa: E402

FEHLER = []
ANNA, BERT, CARLA = "Anna@firma.example", "bert@firma.example", "carla@firma.example"


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def warte_auf(bedingung, sekunden: float = 5) -> bool:
    ende = time.time() + sekunden
    while time.time() < ende:
        if bedingung():
            return True
        time.sleep(0.01)
    return False


def zustand(nutzer: str) -> str | None:
    auftrag = einlesen.auftrag(nutzer)
    return auftrag["zustand"] if auftrag else None


def schreibe_stand(nutzer: str, alter_stunden: float = 0) -> None:
    datei = config.db_path(nutzer) / "stand.txt"
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text("x", encoding="utf-8")
    zeit = time.time() - alter_stunden * 3600
    os.utime(datei, (zeit, zeit))


class FalscherClient:
    """Ersetzt GraphClient: Die Anmeldung wartet, bis der Test sie freigibt (wie ein offener Gerätecode)."""
    freigabe: dict[str, threading.Event] = {}
    fehler: dict[str, str] = {}

    def __init__(self, scopes, nutzer, melde_anmeldung=None):
        self.nutzer, self.melde_anmeldung = nutzer, melde_anmeldung

    def anmelden(self):
        ereignis = self.freigabe.get(self.nutzer)
        if ereignis:
            self.melde_anmeldung({"verification_uri": "https://example.invalid/login", "user_code": f"CODE-{self.nutzer}"})
            ereignis.wait(5)
        if self.nutzer in self.fehler:
            raise RuntimeError(self.fehler[self.nutzer])


class Einlesen:
    """Ersetzt ingest(): zählt, wie viele gleichzeitig laufen, und schreibt am Ende stand.txt wie das Original."""
    def __init__(self):
        self.laeuft, self.maximal, self.reihenfolge = 0, 0, []
        self.sperre = threading.Lock()
        self.halten = threading.Event()
        self.halten.set()

    def __call__(self, source, neu=False, nutzer=None, graph=None):
        with self.sperre:
            self.laeuft += 1
            self.maximal = max(self.maximal, self.laeuft)
            self.reihenfolge.append(nutzer)
        self.halten.wait(5)
        schreibe_stand(nutzer)
        with self.sperre:
            self.laeuft -= 1
        return ["Teams"] if nutzer == CARLA else []


with tempfile.TemporaryDirectory() as ordner:
    config.DATA_DIR = Path(ordner)
    graph_client.GraphClient = FalscherClient
    falsches_einlesen = Einlesen()
    einlesen.ingest = falsches_einlesen

    print("Index erst nach Abschluss freigeben")
    config.db_path(ANNA).mkdir(parents=True)
    pruefe(config.index_nutzer(ANNA) == "demo", "Ordner ohne stand.txt (Einlesen läuft) -> kein halbfertiger Index")
    schreibe_stand(ANNA)
    pruefe(config.index_nutzer(ANNA) == ANNA, "mit stand.txt -> eigener Index")
    pruefe(config.index_nutzer(ANNA.upper()) == ANNA.upper(), "Groß-/Kleinschreibung der Adresse egal")
    pruefe(config.index_nutzer("") == "demo", "ohne Anmeldung Demo-Daten")

    print("Wann eingelesen wird")
    pruefe(not einlesen.noetig(ANNA), "frischer Index -> nichts zu tun")
    schreibe_stand(ANNA, alter_stunden=config.EINLESEN_ALLE_STUNDEN + 1)
    pruefe(einlesen.noetig(ANNA), "alter Index -> auffrischen")
    pruefe(einlesen.noetig("neu@firma.example"), "noch kein Index -> einlesen")

    print("Anmeldung hält die anderen nicht auf")
    FalscherClient.freigabe[ANNA] = threading.Event()
    pruefe(einlesen.starte(ANNA), "Auftrag startet")
    pruefe(not einlesen.starte(ANNA.lower()), "zweiter Start für dieselbe Person -> kein zweiter Lauf")
    pruefe(warte_auf(lambda: einlesen.auftrag(ANNA)["code"] == f"CODE-{ANNA}"), "Code liegt am Auftrag")
    pruefe(not einlesen.noetig(ANNA), "laufender Auftrag -> kein neuer beim nächsten Seitenaufbau")
    pruefe(einlesen.auftrag(BERT) is None, "fremder Nutzer sieht weder Auftrag noch Code")
    einlesen.starte(BERT)
    pruefe(warte_auf(lambda: zustand(BERT) == "fertig"), "Bert wird fertig, obwohl Anna ihren Code noch nicht eingegeben hat")
    pruefe(zustand(ANNA) == "anmeldung", "Anna wartet weiter auf die Anmeldung")

    print("Nur ein Einlesen gleichzeitig")
    falsches_einlesen.halten.clear()
    FalscherClient.freigabe[ANNA].set()
    pruefe(warte_auf(lambda: zustand(ANNA) == "laeuft"), "Anna läuft nach der Anmeldung")
    pruefe(einlesen.auftrag(ANNA)["code"] is None, "Code wird nach der Anmeldung gelöscht")
    einlesen.starte(CARLA)
    pruefe(warte_auf(lambda: zustand(CARLA) == "wartet"), "Carla wartet, solange Anna eingelesen wird")
    falsches_einlesen.halten.set()
    pruefe(warte_auf(lambda: zustand(ANNA) == zustand(CARLA) == "fertig"), "danach werden beide fertig")
    pruefe(falsches_einlesen.maximal == 1, "nie zwei gleichzeitig")
    pruefe(einlesen.auftrag(CARLA)["unvollstaendig"] == ["Teams"], "unvollständige Quellen kommen beim Nutzer an")

    print("Fehler")
    FalscherClient.fehler["dora@firma.example"] = "Falsches Konto angemeldet: x statt dora@firma.example."
    einlesen.starte("dora@firma.example")
    pruefe(warte_auf(lambda: zustand("dora@firma.example") == "fehler"), "Anmeldefehler landet im Auftrag")
    pruefe("Falsches Konto" in einlesen.auftrag("dora@firma.example")["meldung"], "mit Text für den Nutzer")
    pruefe(config.index_nutzer("dora@firma.example") == "demo", "kein Index ohne Einlesen")
    pruefe(not einlesen.noetig("dora@firma.example"), "kein automatischer Neustart bei jedem Klick")
    FalscherClient.fehler.clear()
    pruefe(einlesen.starte("dora@firma.example"), "Button startet neu")
    pruefe(warte_auf(lambda: zustand("dora@firma.example") == "fertig"), "zweiter Versuch klappt")


print("Anmeldecode im echten GraphClient")
import importlib  # noqa: E402

echter = importlib.reload(graph_client).GraphClient


class FalscheMsalApp:
    def __init__(self, konto):
        self.konto = konto

    def get_accounts(self):
        return []

    def initiate_device_flow(self, scopes):
        return {"message": "Code GEHEIM123 eingeben", "verification_uri": "https://example.invalid", "user_code": "GEHEIM123"}

    def acquire_token_by_device_flow(self, flow):
        return {"access_token": "t", "id_token_claims": {"preferred_username": self.konto}}


class FalscherCache:
    has_state_changed = True

    def serialize(self):
        return "{}"


def client(konto: str, melde=None, datei: Path | None = None):
    c = echter.__new__(echter)
    c.scopes, c.nutzer, c.melde_anmeldung = ["x"], ANNA.lower(), melde
    c.app, c.cache, c.cache_datei = FalscheMsalApp(konto), FalscherCache(), datei
    return c


with tempfile.TemporaryDirectory() as ordner:
    datei = Path(ordner) / "token.json"
    gemeldet, ausgabe = [], io.StringIO()
    with contextlib.redirect_stdout(ausgabe):
        client(ANNA, gemeldet.append, datei).anmelden()
    pruefe(gemeldet and gemeldet[0]["user_code"] == "GEHEIM123", "Code geht an die App")
    pruefe("GEHEIM123" not in ausgabe.getvalue(), "Code steht nicht in der Ausgabe (und damit nicht im Log)")
    pruefe(datei.exists(), "richtiges Konto -> Token gespeichert")

    datei2, ausgabe = Path(ordner) / "token2.json", io.StringIO()
    try:
        client(BERT, gemeldet.append, datei2).anmelden()
        pruefe(False, "falsches Konto wird abgelehnt")
    except RuntimeError as e:
        pruefe("Falsches Konto" in str(e), "falsches Konto wird abgelehnt")
    pruefe(not datei2.exists(), "falsches Konto -> kein Token gespeichert")

    ausgabe = io.StringIO()
    with contextlib.redirect_stdout(ausgabe):
        client(ANNA, None, Path(ordner) / "token3.json").anmelden()
    pruefe("GEHEIM123" in ausgabe.getvalue(), "ohne App (Kommandozeile) weiter im Terminal")

print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
sys.exit(1 if FEHLER else 0)
