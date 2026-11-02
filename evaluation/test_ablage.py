"""Test der persönlichen Ablage (ablage.py) OHNE Ollama.

Die beiden Modellaufrufe (_analysiere = Kunde/Thema beschreiben, _vektor = Embedding) werden durch feste
Antworten ersetzt. Geprüft wird alles, was der Code entscheidet: Namensvergleich, Themenzuordnung,
"Ordner erst ab der 2. Frage", Umzug aus _Allgemein, Kopieren der Quellen und die Übersichten.
Die Einordnung durch das echte Modell prüft das nicht, dafür einige Fragen in der App stellen.

Aufruf:  python evaluation/test_ablage.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ablage  # noqa: E402
import config  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def treffer(quelle: str, titel: str, ort: str, link: str, text: str = "Inhalt") -> dict:
    return {"text": f"{titel} | {ort}\n{text}", "meta": {"quelle": quelle, "titel": titel, "ort": ort,
                                                         "absender": "", "datum": "2025-01-15", "link": link}}


# Feste "Modellantworten": Frage -> (Kunde, Thema)
ANTWORTEN = {}
VEKTOREN = {}  # Text -> Vektor; ähnliche Themen bekommen ähnliche Vektoren


def falsche_analyse(frage, treffer_, bekannte, model):
    kunde, thema = ANTWORTEN[frage]
    return {"kunde": kunde, "thema": thema, "art": "Vertrag"}


def falscher_vektor(text):
    for schluessel, v in VEKTOREN.items():
        if schluessel in text:
            return v
    return [0.0, 0.0, 1.0]


ablage._analysiere = falsche_analyse
ablage._vektor = falscher_vektor


def frage(text, kunde, thema, t):
    ANTWORTEN[text] = (kunde, thema)
    return ablage.ablegen(text, t, f"Antwort auf: {text} [1]\n\n### Quellen\n- [1] ...", user="test")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        config.ABLAGE_DIR = Path(tmp)
        wurzel = ablage.ablage_pfad("test")
        demo_datei = next((config.DEMO_DIR / "sharepoint").rglob("*.eml"))
        t_vertrag = [treffer("OneNote", "Rahmenvertrag RV-100", "MBS 2 / Firma X GmbH", "onenote:MBS 2/x",
                             "Firma X: Rabatt 8 %"),
                     treffer("Datei", demo_datei.name, "SharePoint > X", str(demo_datei.relative_to(config.BASE_DIR))),
                     treffer("Outlook", "AW: Konditionen", "Postfach", "https://outlook.example/mail/1", "Firma X Mail")]
        VEKTOREN.update({"Rahmenvertrag": [1.0, 0.0, 0.0], "Ansprechpartner": [0.0, 1.0, 0.0]})

        print("Namensvergleich")
        pruefe(ablage.gleicher_kunde("Firma X", "Firma X GmbH"), "'Firma X' = 'Firma X GmbH'")
        pruefe(ablage.gleicher_kunde("Meier", "Meier Bau AG"), "'Meier' = 'Meier Bau AG'")
        pruefe(not ablage.gleicher_kunde("Meier Bau", "Meier Logistik"), "'Meier Bau' ≠ 'Meier Logistik'")
        pruefe(ablage.ordnername('Konditionen: 8 %/Jahr?') == "Konditionen 8 %-Jahr", "Ordnername ohne verbotene Zeichen")

        print("1. Frage: nur vormerken")
        e = frage("Welchen Rabatt hat Firma X?", "Firma X", "Rahmenvertrag RV-100", t_vertrag)
        pruefe(e["status"] == "vorgemerkt", f"Status vorgemerkt ({e['status']})")
        pruefe(e["kunde"] == "Firma X GmbH", f"Kundenname aus der Ablage übernommen ({e['kunde']})")
        pruefe(not (wurzel / "Firma X GmbH").exists(), "noch kein Kundenordner")

        print("2. Frage, anderes Thema: Kundenordner entsteht, beide Einträge in _Allgemein")
        e = frage("Wer ist bei Firma X Ansprechpartner?", "Firma X GmbH", "Allgemein", t_vertrag)
        kunde = wurzel / "Firma X GmbH"
        pruefe(e["status"] == "abgelegt", f"Status abgelegt ({e['status']})")
        pruefe(len(list((kunde / "_Allgemein").glob("*.md"))) == 2, "2 Einträge in _Allgemein")
        pruefe((kunde / "_Uebersicht.md").exists() and (wurzel / "_Uebersicht.md").exists(), "Übersichten erzeugt")

        print("3. Frage, gleiches Thema anders benannt: Themenordner entsteht, 1. Eintrag zieht um")
        e = frage("Bis wann läuft der Vertrag mit X?", "X", "Rahmenvertrag", t_vertrag)
        thema = kunde / "Rahmenvertrag RV-100"
        pruefe(e["thema"] == "Rahmenvertrag RV-100", f"als bekanntes Thema erkannt ({e['thema']})")
        pruefe(len(list(thema.glob("*.md"))) == 2, "2 Einträge im Themenordner")
        pruefe(len(list((kunde / "_Allgemein").glob("*.md"))) == 1, "nur noch 1 Eintrag in _Allgemein")
        pruefe((thema / "Quellen" / demo_datei.name).exists(), "lokale Quelldatei kopiert")
        auszuege = list((thema / "Quellen").glob("*OneNote*.md"))
        pruefe(len(auszuege) == 1 and "Rabatt 8 %" in auszuege[0].read_text(encoding="utf-8"), "OneNote-Auszug gespeichert")
        pruefe(len(list((thema / "Quellen").glob("*.url"))) == 1, "Verknüpfung zum Web-Original")
        pruefe("Rahmenvertrag RV-100" in (kunde / "_Uebersicht.md").read_text(encoding="utf-8"), "Thema in Kundenübersicht")

        print("Andere Vertragsnummer = anderes Thema")
        ANTWORTEN["RV-200?"] = ("Firma X", "Rahmenvertrag RV-200")
        einordnung = ablage.einordnen("RV-200?", t_vertrag, ablage.lade_register(wurzel))
        pruefe(einordnung["thema_neu"], "RV-200 nicht mit RV-100 zusammengelegt")

        print("Erfundener Kunde und Fragen ohne Kunde")
        e = frage("Welche Termine habe ich nächste Woche?", "", "", t_vertrag)
        pruefe(e["status"] == "übersprungen", f"ohne Kunde/Thema übersprungen ({e['status']})")
        ANTWORTEN["Rabatt?"] = ("Gibtsnicht AG", "Rahmenvertrag")
        pruefe(ablage.einordnen("Rabatt?", t_vertrag, ablage.lade_register(wurzel))["kunde"] == ablage.OHNE_KUNDE,
               "Kunde, der in Frage und Quellen nicht vorkommt, wird verworfen")
        pruefe(ablage.ablegen("x", [], "x", user="test")["status"] == "übersprungen", "ohne Quellen übersprungen")

    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)


if __name__ == "__main__":
    main()
