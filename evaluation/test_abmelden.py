"""Test: Knopf "Abmelden / Konto wechseln" im Serverbetrieb – OHNE Ollama, Cloudflare und Microsoft 365.

Geprüft wird:
    - ablage_onedrive.sitzung_beenden(): Sitzung gilt sofort als beendet (Arbeitskopie wird beim nächsten Aufräumen
      gelöscht), ein späteres Lebenszeichen aus einem zweiten Tab öffnet sie wieder
    - App (Streamlit AppTest, Anmeldung per Cloudflare-Header nachgestellt): Knopf nur mit angemeldetem Konto,
      Klick beendet die Sitzung, leert den Verlauf und leitet zu config.ABMELDEN_URL weiter

Aufruf:  python evaluation/test_abmelden.py
"""
import sys
import time
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import ablage_onedrive  # noqa: E402
import config  # noqa: E402

FEHLER = []
NUTZER = "anna@firma.example"


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def test_sitzung() -> None:
    print("Sitzung beenden (ablage_onedrive)")
    ablage_onedrive.aktiv = lambda nutzer: True
    jetzt = time.time()
    ablage_onedrive._START = 0.0
    ablage_onedrive.lebenszeichen(NUTZER)
    pruefe(ablage_onedrive._sitzung_offen(NUTZER, jetzt + 1), "mit frischem Lebenszeichen offen")
    ablage_onedrive.sitzung_beenden(NUTZER)
    pruefe(not ablage_onedrive._sitzung_offen(NUTZER, jetzt + 2), "nach Abmelden sofort beendet (nicht erst nach 10 Minuten)")
    time.sleep(0.01)
    ablage_onedrive.lebenszeichen(NUTZER.upper())
    pruefe(ablage_onedrive._sitzung_offen(NUTZER, time.time()), "Lebenszeichen aus einem zweiten Tab öffnet sie wieder")
    ablage_onedrive._zustaende[NUTZER] = {"zustand": "laeuft"}
    ablage_onedrive.sitzung_beenden(NUTZER)
    pruefe(ablage_onedrive._sitzung_offen(NUTZER, time.time()), "laufender Abgleich wird nicht unterbrochen")
    ablage_onedrive._zustaende.pop(NUTZER)


def test_app() -> None:
    print("Knopf in der Oberfläche (Streamlit AppTest)")
    try:
        import streamlit as st
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  übersprungen: streamlit nicht installiert")
        return
    import agent
    import ingest
    import ollama

    beendet = []
    kopf = {}
    type(st.context).headers = property(lambda self: kopf)  # Header, den sonst Cloudflare Access setzt
    config.SERVER_MODUS, config.AUTO_EINLESEN, config.ABMELDEN_URL = True, False, "/cdn-cgi/access/logout"
    config.index_nutzer = lambda email: email or "demo"
    config.index_stand = lambda email: time.time()
    ablage_onedrive.aktiv = lambda nutzer: False
    ablage_onedrive.sitzung_beenden = lambda nutzer: beendet.append(nutzer)
    ollama.list = lambda: types.SimpleNamespace(models=[])
    agent.aufwaermen = lambda name: None
    ingest.oeffne_collection = lambda user, neu=False: types.SimpleNamespace(count=lambda: 3)

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=30)
    app.run()
    pruefe(not any("Abmelden" in b.label for b in app.button), "ohne Anmeldung kein Knopf")

    kopf["Cf-Access-Authenticated-User-Email"] = NUTZER
    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=30)
    app.session_state["verlauf"] = [{"rolle": "user", "text": "alte Frage"}]
    app.run()
    knopf = [b for b in app.button if "Abmelden" in b.label]
    pruefe(len(knopf) == 1 and not app.exception, f"angemeldet: Knopf in der Seitenleiste ({app.exception})")
    knopf[0].click().run()
    pruefe(beendet == [NUTZER], f"Klick beendet die Sitzung dieses Nutzers ({beendet})")
    pruefe("verlauf" not in app.session_state, "Verlauf geleert")
    html = " ".join(m.value for m in app.markdown)
    pruefe('http-equiv="refresh"' in html and "/cdn-cgi/access/logout" in html, "Weiterleitung zur Cloudflare-Abmeldung")
    pruefe(not app.chat_input, "danach kein Chat mehr in dieser Sitzung")


if __name__ == "__main__":
    test_sitzung()
    test_app()
    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)
