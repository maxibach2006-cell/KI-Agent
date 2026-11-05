"""Test der Datumsprüfung (agent.unbelegte_daten) OHNE Ollama: Die Prüfung liegt komplett im Code.

Aufruf:  python evaluation/test_datumspruefung.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import config  # noqa: E402

FEHLER = []
config.heute = lambda: date(2026, 11, 4)  # fester Stichtag (Mittwoch), damit Zeitfragen reproduzierbar sind


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def quelle(text: str, datum: str = "2026-11-04") -> dict:
    return {"text": text, "meta": {"quelle": "Teams", "titel": "Nachricht", "ort": "Firma X", "absender": "",
                                   "datum": datum, "link": "", "termine": ""}}


def main() -> None:
    relativ = [quelle("Am Dienstag ist wieder Betriebsfest.")]
    pruefe(agent.unbelegte_daten("Das Fest ist am 07.11.2026 [1].", "Wann ist das Fest?", relativ) == [date(2026, 11, 7)],
           "erfundenes Datum aus relativer Angabe wird gemeldet")
    pruefe(agent.unbelegte_daten("Das Fest ist am Dienstag [1].", "Wann ist das Fest?", relativ) == [],
           "Wochentag ohne Datum wird nicht gemeldet")
    pruefe(agent.unbelegte_daten("Termin am 20.11.2026 [1].", "Wann?", [quelle("Termin am 20.11.2026.")]) == [],
           "Datum aus dem Quelltext ist belegt")
    pruefe(agent.unbelegte_daten("Termin am 20.11.2026 [1].", "Wann?", [quelle("Termin am 2026-11-20.")]) == [],
           "anderes Datumsformat in der Quelle ist belegt")
    pruefe(agent.unbelegte_daten("Stand 03.05.2024 [1].", "Wann?", [quelle("Text", datum="2024-05-03")]) == [],
           "Datum aus den Metadaten ist belegt")
    pruefe(agent.unbelegte_daten("Heute ist der 04.11.2026.", "Was gibt es?", relativ) == [], "heutiges Datum ist belegt")
    pruefe(agent.unbelegte_daten("Am 13.11.2026 nichts [1].", "Was ist am 13.11.2026?", relativ) == [],
           "Datum aus der Frage ist belegt")
    pruefe(agent.unbelegte_daten("Vom 09.11.2026 bis 15.11.2026 [1].", "Was steht nächste Woche an?", relativ) == [],
           "berechnete Grenzen des Zeitraums sind belegt")
    pruefe(agent.unbelegte_daten("Termin am 10.11.2026 [1].", "Was steht nächste Woche an?", relativ) == [date(2026, 11, 10)],
           "Datum innerhalb des Zeitraums braucht trotzdem eine Quelle")

    anhang = agent.anhang_markdown(relativ, [], "Das Fest ist am 07.11.2026 [1].", "Wann ist das Fest?")
    pruefe("### Bitte prüfen" in anhang and "07.11.2026" in anhang, "Anhang nennt das Datum unter „Bitte prüfen“")
    pruefe(anhang.index("### Widersprüche") < anhang.index("### Bitte prüfen") < anhang.index("### Quellen"),
           "Hinweis steht zwischen Widersprüchen und Quellen")
    pruefe("### Bitte prüfen" not in agent.anhang_markdown(relativ, [], "Das Fest ist am Dienstag [1].", "Wann?"),
           "kein Hinweis ohne unbelegtes Datum")
    pruefe("### Bitte prüfen" not in agent.anhang_markdown(relativ, []), "bisheriger Aufruf ohne Antworttext bleibt gültig")

    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)


if __name__ == "__main__":
    main()
