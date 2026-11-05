"""Test des Vertrags-Steckbriefs (steckbrief.py und Einbindung in ablage.py) OHNE Ollama.

Die Extraktion durch das Modell (steckbrief.extrahiere) wird durch feste Antworten ersetzt. Geprüft wird alles,
was der Code entscheidet: Belegprüfung gegen die Originalquelle, Zusammenführen nach Quelldatum, Widersprüche,
Fristen und dass jede Quelle des Steckbriefs im Ordner Quellen/ liegt und verlinkt ist.

Aufruf:  python evaluation/test_steckbrief.py
"""
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ablage  # noqa: E402
import config  # noqa: E402
import steckbrief  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def quelle(quelle_: str, titel: str, datum: str, text: str, link: str = "") -> dict:
    return {"text": f"{titel} | MBS 2 / Firma X GmbH | {datum}\n{text}",
            "meta": {"quelle": quelle_, "titel": titel, "ort": "MBS 2 / Firma X GmbH", "absender": "",
                     "datum": datum, "link": link or f"onenote:MBS 2/Firma X/{titel}"}}


VERTRAG = quelle("OneNote", "Rahmenvertrag RV-100", "2023-04-03",
                 "Rahmenvertrag RV-100 mit Firma X GmbH\nUnterzeichnet am 28.03.2023 von Dr. Anna Weber.\n\n"
                 "Konditionen:\n- Laufzeit: 01.04.2023 bis 31.03.2027\n- Rabatt: 8 % auf Listenpreis\n"
                 "- Zahlungsziel: 30 Tage netto\n- Kündigungsfrist: 6 Monate zum Laufzeitende")
MAIL_NEU = quelle("Outlook", "AW: Zahlungsziel RV-100", "2025-05-12",
                  "Betreff: AW: Zahlungsziel\n\nWir bestätigen das neue Zahlungsziel von 45 Tagen netto ab 01.06.2025.",
                  "https://outlook.example/mail/1")
MAIL_ALT = quelle("Outlook", "Angebot", "2022-11-08", "Angebot mit Zahlungsziel 14 Tage netto.")
MAIL_GLEICH = quelle("Teams", "Notiz Rabatt", "2023-04-03", "Rabatt laut Gespräch 10 %.")


def main():
    print("Belegprüfung gegen die Originalquelle")
    t = [VERTRAG]
    belegt = steckbrief.belege([
        {"feld": "Laufzeit", "wert": "01.04.2023 – 31.03.2027", "quelle": 1},   # anders geschrieben, gleiche Daten
        {"feld": "Rabatt", "wert": "8 %", "quelle": 1},
        {"feld": "Ansprechpartner", "wert": "Dr. Anna Weber", "quelle": 1},
        {"feld": "Vertragsnummer", "wert": "RV-100", "quelle": 1},
    ], t)
    pruefe({b["feld"] for b in belegt} == {"Laufzeit", "Rabatt", "Ansprechpartner", "Vertragsnummer"},
           f"belegte Werte übernommen ({sorted(b['feld'] for b in belegt)})")
    pruefe(not steckbrief.belege([{"feld": "Zahlungsziel", "wert": "8 %", "quelle": 1}], t),
           "Rabattwert als Zahlungsziel verworfen (Schlüsselwort fehlt in der Zeile)")
    pruefe(not steckbrief.belege([{"feld": "Rabatt", "wert": "12 %", "quelle": 1}], t), "erfundener Wert verworfen")
    pruefe(len(steckbrief.belege([{"feld": "Rabatt", "wert": "8 %", "quelle": 7}], t)) == 1,
           "falsche Quellennummer: Wert trotzdem in anderer Quelle gefunden")

    print("Zusammenführen nach Datum der Quelle")
    stand = steckbrief.leer()
    steckbrief.zusammenfuehren(stand, steckbrief.belege(
        [{"feld": "Zahlungsziel", "wert": "30 Tage netto", "quelle": 1}], [VERTRAG]), "2026-11-01T10:00:00")
    m = steckbrief.zusammenfuehren(stand, steckbrief.belege(
        [{"feld": "Zahlungsziel", "wert": "30 Tage", "quelle": 1}], [VERTRAG]), "2026-11-02T10:00:00")
    pruefe(m == [] and stand["felder"]["Zahlungsziel"]["wert"] == "30 Tage netto", "gleicher Wert -> keine Änderung")
    m = steckbrief.zusammenfuehren(stand, steckbrief.belege(
        [{"feld": "Zahlungsziel", "wert": "45 Tagen netto", "quelle": 1}], [MAIL_NEU]), "2026-11-03T10:00:00")
    pruefe(m == ["Zahlungsziel geändert"] and stand["felder"]["Zahlungsziel"]["wert"] == "45 Tagen netto",
           "neuere Quelle ersetzt den Wert")
    pruefe(stand["aenderungen"][0]["alt"] == "30 Tage netto", "alter Wert steht unter Änderungen")
    steckbrief.zusammenfuehren(stand, steckbrief.belege(
        [{"feld": "Zahlungsziel", "wert": "14 Tage netto", "quelle": 1}], [MAIL_ALT]), "2026-11-03T11:00:00")
    pruefe(stand["felder"]["Zahlungsziel"]["wert"] == "45 Tagen netto", "ältere Quelle ändert nichts")
    steckbrief.zusammenfuehren(stand, steckbrief.belege([{"feld": "Rabatt", "wert": "8 %", "quelle": 1}], [VERTRAG]), "x")
    m = steckbrief.zusammenfuehren(stand, steckbrief.belege(
        [{"feld": "Rabatt", "wert": "10 %", "quelle": 1}], [MAIL_GLEICH]), "y")
    pruefe(m == ["Rabatt widersprüchlich"] and stand["felder"]["Rabatt"]["widerspruch"],
           "gleich alte Quelle mit anderem Wert -> Widerspruch")

    print("Fristen")
    stand = steckbrief.leer()
    steckbrief.zusammenfuehren(stand, steckbrief.belege([
        {"feld": "Laufzeit", "wert": "01.04.2023 bis 31.03.2027", "quelle": 1},
        {"feld": "Kündigungsfrist", "wert": "6 Monate zum Laufzeitende", "quelle": 1}], [VERTRAG]), "z")
    fr = steckbrief.fristen(stand, date(2026, 11, 3))
    pruefe((date(2027, 3, 31), "Laufzeit: 01.04.2023 bis 31.03.2027") in fr, "Laufzeitende als Frist")
    kuendigung = [f for f in fr if f[1].startswith("Letzter Kündigungstermin")]
    pruefe(kuendigung and kuendigung[0][0] == date(2026, 9, 30) and "verstrichen" in kuendigung[0][1],
           f"Kündigungstermin 30.09.2026 berechnet und als verstrichen markiert ({kuendigung})")

    print("Einbindung in die Ablage: Steckbrief + Originalquellen im Themenordner")
    antworten = iter([
        [{"feld": "Rabatt", "wert": "8 %", "quelle": 1}, {"feld": "Laufzeit", "wert": "01.04.2023 bis 31.03.2027", "quelle": 1}],
        [{"feld": "Zahlungsziel", "wert": "45 Tagen netto", "quelle": 2}],
    ])
    steckbrief.extrahiere = lambda antwort, model=None: next(antworten)
    ablage._analysiere = lambda frage, treffer, bekannte, model: {"kunde": "Firma X", "thema": "Rahmenvertrag RV-100",
                                                                  "art": "Vertrag"}
    ablage._vektor = lambda text: [1.0, 0.0]
    with tempfile.TemporaryDirectory() as tmp:
        config.ABLAGE_DIR = Path(tmp)
        e1 = ablage.ablegen("Welchen Rabatt hat Firma X?", [VERTRAG], "8 % [1]", user="test")
        pruefe(e1["status"] == "vorgemerkt", "1. Frage vorgemerkt, Stand schon gesammelt")
        e2 = ablage.ablegen("Welches Zahlungsziel hat Firma X?", [VERTRAG, MAIL_NEU], "45 Tage [2]", user="test")
        pruefe("Zahlungsziel neu" in e2["meldung"], f"Meldung nennt Änderung ({e2['meldung']})")
        ordner = ablage.ablage_pfad("test") / "Firma X GmbH" / "Rahmenvertrag RV-100"
        stand_md = (ordner / "_Stand.md").read_text(encoding="utf-8")
        pruefe("8 %" in stand_md and "45 Tagen netto" in stand_md and "31.03.2027" in stand_md,
               "Steckbrief enthält Werte aus beiden Fragen")
        links = [unquote(l) for l in re.findall(r"\]\((Quellen/[^)]+)\)", stand_md)]
        pruefe(links and all((ordner / l).exists() for l in links),
               f"alle {len(links)} Quellenlinks zeigen auf abgelegte Originalquellen")
        pruefe((ordner / "Quellen").glob("*.url") and any((ordner / "Quellen").glob("*.url")),
               "Web-Quelle zusätzlich als Verknüpfung zum Original")
        pruefe("Aktueller Stand" in (ordner.parent / "_Uebersicht.md").read_text(encoding="utf-8"),
               "Kundenübersicht verlinkt den Steckbrief")

    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)


if __name__ == "__main__":
    main()
