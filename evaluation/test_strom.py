"""Test des Strom-Trackers (strom.py) OHNE Ollama und ohne Grafikkarte: Messwerte und Uhr werden ersetzt.

Aufruf:  python evaluation/test_strom.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import strom  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def nah(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def setze(uhr: list, watt: float | None) -> None:
    """Eine Messung zum aktuellen Stand der Uhr."""
    strom.gpu_watt = lambda: watt
    strom._messe_einmal()


def main() -> None:
    uhr = [1000.0]
    strom.time.monotonic = lambda: uhr[0]  # feste Uhr statt der echten Zeit
    config.STROM_REST_WATT = 60.0
    config.STROM_PREIS_EURO_KWH = 0.30

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ordner:
        config.DATA_DIR = Path(ordner)

        pruefe(strom.anfrage_beenden(strom.marke()) is None, "ohne Messwert gibt es kein Ergebnis")
        pruefe(strom.text_uebersicht() == "", "ohne Messwert bleibt die Seitenleiste leer")

        setze(uhr, 100.0)
        start = strom.marke()
        uhr[0] += 3600  # eine Stunde: wird von der Lücken-Regel gesperrt
        setze(uhr, 100.0)
        pruefe(strom._stand["gpu_wh"] == 0, "lange Lücke (Standby) zählt nicht")

        start = strom.marke()
        for _ in range(9):
            uhr[0] += 1
            setze(uhr, 100.0)
        uhr[0] += 0.5  # Rest bis zum Ende der Anfrage wird mit dem letzten Wert gerechnet
        m = strom.anfrage_beenden(start)
        pruefe(nah(m["sekunden"], 9.5), "Dauer der Anfrage wird bis zum Ende gezählt")
        pruefe(nah(m["gpu_wh"], 100 * 9.5 / 3600), "Grafikkarte: Leistung mal Zeit")
        pruefe(nah(m["gesamt_wh"], 160 * 9.5 / 3600), "Gesamt: Grafikkarte plus geschätzter Rest")
        pruefe(nah(m["euro"], m["gesamt_wh"] / 1000 * 0.30), "Umrechnung in Euro")
        pruefe(strom._stand["anfragen"] == 1, "Anfrage wird gezählt")

        text = strom.text_anfrage(m)
        pruefe("0,42 Wh" in text and "0,013 Cent" in text and "geschätzt" in text, "Anfragezeile in deutscher Schreibweise")
        uebersicht = strom.text_uebersicht()
        pruefe("Bereitschaft" not in uebersicht, "keine Hochrechnung, solange kaum Zeit ohne Anfrage vergangen ist")
        pruefe("1 Anfrage:" in uebersicht, "Einzahl bei einer Anfrage")
        pruefe("1 € reicht für ca. 7.895 Anfragen" in uebersicht, "Gefühl für den Preis: Anfragen je Euro")

        for _ in range(70):  # Bereitschaft ohne Anfrage: Grafikkarte 30 W, Rest 60 W
            setze(uhr, 30.0)
            uhr[0] += 1
        setze(uhr, 30.0)
        uebersicht = strom.text_uebersicht()
        pruefe("90 W" in uebersicht and "19 € im Monat" in uebersicht, "Hochrechnung nur aus der Zeit ohne Anfragen")

        vorher = dict(strom._stand)
        strom._speichere()
        strom._stand.update(sekunden=0.0, gpu_wh=0.0, rest_wh=0.0, anfragen=0, anfragen_wh=0.0, anfragen_sekunden=0.0)
        strom._lade()
        pruefe(strom._stand == vorher, "Stand übersteht einen Neustart")

        (config.DATA_DIR / "strom.json").write_text("kaputt", encoding="utf-8")
        strom._lade()
        pruefe(strom._stand == vorher, "beschädigte Datei führt nicht zum Absturz")

        setze(uhr, None)
        pruefe(strom.anfrage_beenden(strom.marke()) is None, "fällt die Messung aus, gibt es keinen erfundenen Wert")

    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)


if __name__ == "__main__":
    main()
