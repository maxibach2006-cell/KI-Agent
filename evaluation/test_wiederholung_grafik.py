"""Test: wiederholte Fragen (wiederholung.py) und Grafik zu Zahlen (grafik.py) – OHNE Ollama.

Geprüft wird alles, was der Code entscheidet, und der Ablauf in der Oberfläche (Streamlit AppTest):
    - gleiche / fast gleiche / verschiedene Fragen, Vorschläge ohne erfundene Namen
    - Zahlen lesen, Datenpunkte gegen die Quelle prüfen, Darstellung wählen, Diagramm bauen
    - App: Antwort mit Grafik-Angebot -> Grafik erstellen -> dieselbe Frage nochmal -> Hinweis + Vorschläge
      -> Vorschlag anklicken -> 'Trotzdem neu beantworten'
Die Modellaufrufe (Antwort, Vorschläge, Datenpunkte) werden durch feste Antworten ersetzt.

Aufruf:  python evaluation/test_wiederholung_grafik.py
"""
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import grafik  # noqa: E402
import wiederholung  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def treffer(quelle: str, titel: str, text: str) -> dict:
    return {"text": f"{titel} | Ablage\n{text}", "meta": {"quelle": quelle, "titel": titel, "ort": "MBS 2 / Firma X",
                                                          "absender": "", "datum": "2026-01-10", "link": "x"}}


T = [treffer("OneNote", "Jahresgespräch Firma X", "Umsatz 2023: 1,31 Mio. EUR\nUmsatz 2024: 1,55 Mio. EUR\n"
             "Umsatz 2025 voraussichtlich 1,72 Mio. EUR"),
     treffer("Datei", "Angebot ANG-1 Version 2", "Rabatt auf Listenpreis: 9 % (Version 2)")]


def test_wiederholung() -> None:
    print("Wiederholte Fragen erkennen")
    g = wiederholung.gleiche_frage
    pruefe(g("Welchen Rabatt hat Firma X?", "welchen rabatt hat firma x"), "gleiche Frage, andere Schreibung")
    pruefe(g("Welchen Rabatt hat Firma X?", "Welchen Rabatt hat eigentlich Firma X ?"), "Füllwort und Leerzeichen egal")
    pruefe(not g("Welchen Rabatt hat Firma X?", "Welchen Rabatt hat Firma Y?"), "anderer Kunde = andere Frage")
    pruefe(not g("Umsatz 2024 von Firma X?", "Umsatz 2025 von Firma X?"), "anderes Jahr = andere Frage")
    pruefe(not g("Welchen Rabatt hat Firma X?", "Bis wann läuft der Vertrag mit Firma X?"), "anderes Thema")
    verlauf = [{"rolle": "user", "text": "Welchen Rabatt hat Firma X?"}, {"rolle": "assistant", "text": "8 %"},
               {"rolle": "user", "text": "Bis wann läuft der Vertrag?"}, {"rolle": "assistant", "text": "2027"}]
    pruefe(wiederholung.finde_wiederholung("welchen Rabatt hat Firma X", verlauf) == 0, "findet die frühere Frage")
    pruefe(wiederholung.finde_wiederholung("Wer ist Ansprechpartner?", verlauf) is None, "neue Frage -> None")
    pruefe(wiederholung.kurzantwort("### Kurzantwort\n8 % Rabatt [1].\n\n### Details\nlang …") == "8 % Rabatt [1].",
           "Kurzantwort ohne Details")

    print("Vorschläge prüfen")
    gut = wiederholung.pruefe_vorschlaege(
        ["Wie hoch war der Umsatz 2024 bei Firma X?", "Welchen Rabatt gibt Siemens?", "Welchen Rabatt hat Firma X?",
         "Wie hoch war der Umsatz 2024 bei Firma X?"], "Welchen Rabatt hat Firma X?", T, ["Welchen Rabatt hat Firma X?"])
    pruefe(gut == ["Wie hoch war der Umsatz 2024 bei Firma X?"],
           f"erfundener Name, schon gestellte und doppelte Fragen verworfen ({gut})")
    fest = wiederholung._feste_vorschlaege(T, [])
    pruefe(len(fest) == 2 and "Jahresgespräch Firma X" in fest[0], f"feste Vorschläge aus echten Titeln ({fest})")
    text = wiederholung.hinweis_markdown("Welchen Rabatt hat Firma X?", {"text": "### Kurzantwort\n8 % [1]"}, 1, "10:14",
                                         ["Bis wann läuft der Vertrag?"])
    pruefe("bereits gestellt" in text and "10:14" in text and "8 % [1]" in text and "Bis wann" in text,
           "Hinweis nennt Zeitpunkt, frühere Kurzantwort und Vorschläge")


def test_grafik() -> None:
    print("Zahlen und Belegprüfung")
    pruefe([grafik.zahl(x) for x in ["1,72", "892.000", "8", "3.9", "+4,5 %", "abc"]] == [1.72, 892000, 8, 3.9, 4.5, None],
           "deutsche Zahlen lesen")
    pruefe(grafik.anzeige(892000) == "892.000" and grafik.anzeige(1.72) == "1,72" and grafik.anzeige(3.9) == "3,9",
           "deutsche Schreibweise")
    roh = {"titel": "Umsatz Firma X", "einheit": "Mio. EUR", "reihen": [{"name": "Umsatz", "punkte": [
        {"x": "2023", "wert": "1,31", "quelle": 1}, {"x": "2024", "wert": "1,55", "quelle": 1},
        {"x": "2025", "wert": "1,72", "quelle": 1},
        {"x": "2026", "wert": "1,9", "quelle": 1},     # erfunden
        {"x": "2022", "wert": "1,55", "quelle": 1}]}]}  # Zahl existiert, aber nicht für 2022
    d = grafik.pruefe_daten(roh, T)
    pruefe([p["x"] for p in d["reihen"][0]["punkte"]] == ["2023", "2024", "2025"] and d["verworfen"] == 2,
           f"erfundener Wert und falsche Beschriftung verworfen (verworfen={d['verworfen']})")
    pruefe(d["fehler"] is None and grafik.empfohlene_art(d) == "linie", "Jahresverlauf -> Liniendiagramm")
    v = grafik.pruefe_daten({"titel": "Rabatt", "einheit": "%", "reihen": [{"name": "Rabatt", "punkte": [
        {"x": "v2", "wert": "9", "quelle": 2}]}]}, T)
    pruefe(v["fehler"] is not None, "ein einzelner Punkt reicht nicht für eine Grafik")
    k = {"titel": "t", "einheit": "", "reihen": [{"name": "a", "punkte": [{"x": "Pumpen", "wert": 1, "anzeige": "1", "quelle": 1},
                                                                           {"x": "Antriebe", "wert": 2, "anzeige": "2", "quelle": 1}]}]}
    pruefe(grafik.empfohlene_art(k) == "balken", "Kategorien -> Balkendiagramm")
    pruefe(grafik._ordnung("Q2 2026") < grafik._ordnung("Q1 2027") and grafik._ordnung("v1") < grafik._ordnung("v3"),
           "Quartale und Versionen werden richtig sortiert")

    print("Angebot erkennen")
    pruefe(grafik.bietet_grafik("Wie hat sich der Umsatz entwickelt?", "2024: 1,55 Mio. EUR [1], 2025: 1,72 Mio. EUR [1]", T),
           "Frage nach Umsatz mit Zahlen -> Angebot")
    pruefe(not grafik.bietet_grafik("Wer ist Ansprechpartner?", "Anna Weber [1].", T), "keine Zahlen -> kein Angebot")
    pruefe(not grafik.bietet_grafik("Wie hoch ist der Umsatz?", "1,72 Mio. EUR, 1,55 Mio. EUR", []), "ohne Quellen -> kein Angebot")

    print("Diagramm bauen")
    for art in ("linie", "balken"):
        for dunkel in (False, True):
            spec = grafik.diagramm(d, art, dunkel).to_dict()
            pruefe("layer" in spec and spec.get("config", {}).get("view", {}).get("stroke") is None,
                   f"{art} ({'dunkel' if dunkel else 'hell'}) lässt sich erzeugen")
    zwei = {**d, "reihen": d["reihen"] + [{"name": "Plan", "punkte": d["reihen"][0]["punkte"]}]}
    spec = grafik.diagramm(zwei, "balken").to_dict()
    pruefe("xOffset" in str(spec) and "legend" in str(spec), "zwei Reihen: Balken nebeneinander, mit Legende")
    pruefe(list(grafik.tabelle(d).columns) == ["Reihe", "Beschriftung", "Wert", "Quelle"], "Tabellenansicht")


def test_app() -> None:
    print("Ablauf in der Oberfläche (Streamlit AppTest)")
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  übersprungen: streamlit nicht installiert")
        return
    import types

    import agent
    import ingest
    import ollama
    aufrufe = {"vorbereite": 0}

    def vorbereite(frage, user, model, runden, melde=None):
        aufrufe["vorbereite"] += 1
        return {"verstanden": frage, "treffer": [dict(t, aehnlichkeit=0.8) for t in T], "varianten": [], "widersprueche": []}

    ollama.list = lambda: types.SimpleNamespace(models=[types.SimpleNamespace(model="qwen2.5:7b")])
    agent.aufwaermen = lambda name: None
    agent.vorbereite = vorbereite
    agent.generiere = lambda *a, **k: iter(["### Kurzantwort\nUmsatz 2024: 1,55 Mio. EUR [1], 2025: 1,72 Mio. EUR [1]."])
    agent.anhang_markdown = lambda *a, **k: "\n\n### Quellen\n- [1] OneNote"
    ingest.oeffne_collection = lambda user, neu=False: types.SimpleNamespace(count=lambda: 2)
    wiederholung.vorschlaege = lambda frage, treffer, gestellt, model=None: ["Welchen Rabatt bietet Version 2?"]
    grafik.erstelle = lambda frage, antwort, treffer, model=None: grafik.pruefe_daten(
        {"titel": "Umsatz Firma X", "einheit": "Mio. EUR", "reihen": [{"name": "Umsatz", "punkte": [
            {"x": "2024", "wert": "1,55", "quelle": 1}, {"x": "2025", "wert": "1,72", "quelle": 1}]}]}, treffer)

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=30)
    app.session_state["verlauf"] = []
    app.run()
    pruefe(not app.exception, f"App startet ({app.exception})")
    app.chat_input[0].set_value("Wie hat sich der Umsatz von Firma X entwickelt?").run()
    pruefe(any("1,72 Mio" in m.value for m in app.markdown), "Antwort erscheint")
    pruefe(any("enthält Zahlen" in m.value for m in app.markdown), "Grafik wird angeboten")
    los = [b for b in app.button if b.label == "Grafik erstellen"]
    pruefe(len(los) == 1, "Knopf 'Grafik erstellen'")
    los[0].click().run()
    pruefe(len(app.get("vega_lite_chart")) == 1 and not app.exception, f"Grafik wird angezeigt ({app.exception})")
    pruefe(any("Belege:" in c.value for c in app.caption), "Belegzeile unter der Grafik")

    app.chat_input[0].set_value("wie hat sich der umsatz von firma x entwickelt").run()
    pruefe(aufrufe["vorbereite"] == 1, "wiederholte Frage startet keine neue Suche")
    pruefe(any("bereits gestellt" in m.value for m in app.markdown), "Hinweis auf die frühere Frage")
    knoepfe = [b.label for b in app.button]
    pruefe("💬 Welchen Rabatt bietet Version 2?" in knoepfe and "🔄 Trotzdem neu beantworten" in knoepfe,
           "Vorschlag und 'Trotzdem neu beantworten' als Knöpfe")
    pruefe(len(app.get("vega_lite_chart")) == 1, "frühere Grafik bleibt im Verlauf sichtbar")

    next(b for b in app.button if b.label == "💬 Welchen Rabatt bietet Version 2?").click().run()
    pruefe(aufrufe["vorbereite"] == 2 and app.session_state["verlauf"][-2]["text"] == "Welchen Rabatt bietet Version 2?",
           "Vorschlag anklicken stellt die Frage")
    next(b for b in app.button if b.label == "🔄 Trotzdem neu beantworten").click().run()
    pruefe(aufrufe["vorbereite"] == 3 and not app.session_state["verlauf"][-1].get("wiederholung"),
           "'Trotzdem neu beantworten' beantwortet die Frage neu")
    pruefe(not app.exception, f"keine Fehler im Ablauf ({app.exception})")


if __name__ == "__main__":
    test_wiederholung()
    test_grafik()
    test_app()
    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)
