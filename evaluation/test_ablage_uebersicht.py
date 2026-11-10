"""Test: Übersicht "Meine Ablage" in der Seitenleiste (ablage.uebersicht + app.py) – OHNE Ollama und Microsoft 365.

Legt mit ablage.ablegen() eine kleine Ablage an (Modellaufrufe durch feste Antworten ersetzt) und prüft:
    - uebersicht(): Kunden mit Ordner, vorgemerkte Kunden, Ordner mit neuesten Dateien, Quellen, Steckbrief
    - App (Streamlit AppTest): Bereich "Meine Ablage", Kundenauswahl, Dateien zum Herunterladen, leere Ablage,
      Ablage nur in OneDrive -> Knopf "Aus OneDrive laden"

Aufruf:  python evaluation/test_ablage_uebersicht.py
"""
import sys
import tempfile
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import ablage  # noqa: E402
import config  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def treffer(kunde: str, titel: str, text: str) -> dict:
    return {"text": f"{titel} | MBS 2 / {kunde}\n{text}",
            "meta": {"quelle": "OneNote", "titel": titel, "ort": f"MBS 2 / {kunde}", "absender": "",
                     "datum": "2026-01-10", "link": f"onenote:{kunde}/{titel}"}}


ANTWORTEN = {}
ablage._analysiere = lambda frage, t, bekannte, model: ANTWORTEN[frage]
ablage._vektor = lambda text: [1.0, 0.0] if "Rahmenvertrag" in text else [0.0, 1.0]
ablage.steckbrief.extrahiere = lambda antwort, model=None: [{"feld": "Rabatt", "wert": "8 %", "quelle": 1}]


def frage(text: str, kunde: str, thema: str, art: str, t: list[dict]) -> None:
    ANTWORTEN[text] = {"kunde": kunde, "thema": thema, "art": art}
    ablage.ablegen(text, t, f"### Kurzantwort\nAntwort auf {text} [1]", user="test")


def baue_ablage() -> None:
    x = [treffer("Firma X GmbH", "Rahmenvertrag RV-100", "Rahmenvertrag RV-100 mit Firma X GmbH\nRabatt: 8 % auf Listenpreis")]
    y = [treffer("Firma Y AG", "Kundenprofil", "Firma Y AG, Ansprechpartner Anna Weber")]
    frage("Welchen Rabatt hat Firma X?", "Firma X", "Rahmenvertrag RV-100", "Vertrag", x)
    frage("Bis wann läuft der Vertrag mit Firma X?", "Firma X", "Rahmenvertrag RV-100", "Vertrag", x)
    frage("Wer ist bei Firma X Ansprechpartner?", "Firma X", "Allgemein", "Allgemein", x)
    frage("Wer ist bei Firma Y zuständig?", "Firma Y", "Allgemein", "Allgemein", y)  # nur eine Frage -> vorgemerkt


def test_uebersicht() -> None:
    print("Übersicht aus Register und Ordnern")
    u = ablage.uebersicht("test")
    pruefe([k["name"] for k in u["kunden"]] == ["Firma X GmbH"], f"Kunde mit Ordner ({[k['name'] for k in u['kunden']]})")
    pruefe(u["vorgemerkt"] == ["Firma Y AG"], f"Kunde mit einer Frage nur vorgemerkt ({u['vorgemerkt']})")
    pruefe(u["fragen"] == 4, f"alle Fragen gezählt ({u['fragen']})")
    ordner = u["kunden"][0]["ordner"]
    pruefe([o["name"] for o in ordner] == ["Rahmenvertrag RV-100", "Allgemein"], f"Themenordner vor Allgemein ({[o['name'] for o in ordner]})")
    vertrag = ordner[0]
    pruefe(len(vertrag["dateien"]) == 2 and all(d.suffix == ".md" and not d.name.startswith("_") for d in vertrag["dateien"]),
           "Antworten des Themenordners, ohne _Stand/_Uebersicht")
    pruefe(vertrag["stand"] is not None and vertrag["stand"].name == ablage.STAND, "Steckbrief des Vertrags gefunden")
    pruefe(vertrag["quellen"] >= 1, f"Quellen gezählt ({vertrag['quellen']})")
    pruefe(ablage.uebersicht("niemand") == {"wurzel": ablage.ablage_pfad("niemand"), "kunden": [], "vorgemerkt": [], "fragen": 0},
           "leere Ablage ohne Fehler")


def test_app() -> None:
    print("Anzeige in der Seitenleiste (Streamlit AppTest)")
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  übersprungen: streamlit nicht installiert")
        return
    import ablage_onedrive
    import agent
    import ingest
    import ollama
    ollama.list = lambda: types.SimpleNamespace(models=[types.SimpleNamespace(model="qwen2.5:7b")])
    agent.aufwaermen = lambda name: None
    ingest.oeffne_collection = lambda user, neu=False: types.SimpleNamespace(count=lambda: 3)
    ablage_onedrive.aktiv = lambda nutzer: False
    config.SERVER_MODUS = False

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=30)
    app.run()
    app.sidebar.radio[0].set_value("graph").run()
    app.sidebar.text_input[0].set_value("test").run()
    pruefe(not app.exception, f"App läuft ({app.exception})")
    pruefe(any(e.label == "📁 Meine Ablage" for e in app.sidebar.expander), "Bereich „Meine Ablage“ in der Seitenleiste")
    pruefe(app.sidebar.selectbox(key="ablage_kunde").options == ["Firma X GmbH"], "Kundenauswahl")
    knoepfe = [b for b in app.sidebar.get("download_button")]
    pruefe(len(knoepfe) == 4, f"Steckbrief + 3 Antworten zum Herunterladen ({len(knoepfe)})")
    texte = " ".join(c.value for c in app.sidebar.caption)
    pruefe("Firma Y AG" in texte and "Vorgemerkt" in texte, "vorgemerkter Kunde wird genannt")

    app.sidebar.text_input[0].set_value("niemand").run()
    pruefe(any("Noch nichts abgelegt" in c.value for c in app.sidebar.caption), "leere Ablage: Hinweis statt Fehler")

    ablage_onedrive.aktiv = lambda nutzer: True
    geladen = []
    ablage_onedrive.wiederherstellen_falls_noetig = lambda nutzer: geladen.append(nutzer) or "Ablage aus OneDrive wiederhergestellt (3 Dateien)."
    app.run()
    knopf = [b for b in app.sidebar.button if b.label == "Aus OneDrive laden"]
    pruefe(len(knopf) == 1, "nur in OneDrive: Knopf „Aus OneDrive laden“")
    knopf[0].click().run()
    pruefe(geladen == ["niemand"] and any("wiederhergestellt" in c.value for c in app.sidebar.caption),
           "Klick holt die Ablage aus OneDrive und meldet das Ergebnis")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        config.ABLAGE_DIR = Path(tmp)
        baue_ablage()
        test_uebersicht()
        test_app()
    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)
