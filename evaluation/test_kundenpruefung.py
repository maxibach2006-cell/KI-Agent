"""Test: Nennt die Frage einen Kunden, fallen die Abschnitte anderer Kunden weg (ohne Ollama und ohne Index).

Hintergrund: Verträge verschiedener Kunden klingen ähnlich. Die Suche brachte zu einer Frage nach Kunde A den Vertrag
von Kunde B, und das Modell nannte dessen Daten als Antwort. Gegenprobe auf echten Daten: evaluation/tenant_lauf.py

Aufruf:  python evaluation/test_kundenpruefung.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def meta(quelle: str, ort: str) -> dict:
    return {"quelle": quelle, "ort": ort, "titel": "", "absender": ""}


METAS = [meta("OneNote", "MBS 2 / Alpha Maschinenbau GmbH"), meta("OneNote", "MBS 2 / Beta Logistik AG"),
         meta("OneNote", "MBS 2 / Allgemein"), meta("OneNote", "Allgemein / Persönliche Notizen (privat)"),
         meta("Teams", "Pilot > Gamma Pharma"), meta("Teams", "Pilot > General"), meta("Teams", "Chat: Chat"),
         meta("Datei", "Teams: Pilot/Delta Medical"), meta("Datei", "OneDrive/Kunden/Epsilon_neu/Mails"),
         meta("Outlook", "Postfach"), meta("Kalender", "Raum 2")]

print("Kunden im Index")
kunden = agent._kunden_im_index(METAS)
pruefe(kunden == {"alpha", "beta", "gamma", "delta"}, f"aus OneNote, Teams und Team-Ordnern: {sorted(kunden)}")

print("Kunde in der Frage")
for frage, soll in [("Welchen Rabatt hat Alpha?", {"alpha"}), ("beta rabatt?", {"beta"}),
                    ("Alphas Vertrag und Liefertreue", {"alpha"}), ("Vergleiche Alpha und Beta", {"alpha", "beta"}),
                    ("Welcher Vertrag läuft als nächstes aus?", set()), ("Wie läuft es in der Logistik?", set()),
                    ("Welche Pharma-Kunden gibt es?", set()), ("Wer ist Alphabet?", set())]:
    pruefe(agent._genannte_kunden(frage, METAS) == soll, f"{frage!r} -> {sorted(soll) or 'kein Kunde'}")

print("Abschnitt gehört zum Kunden")
pruefe(agent._nennt_kunden("RV-100_Alpha_unterschrieben.pdf\nLaufzeit", {"alpha"}), "Dateiname mit _ zählt")
pruefe(agent._nennt_kunden("Alpha Maschinenbau | MBS 2\nText", {"alpha"}), "Kopfzeile zählt")
pruefe(agent._nennt_kunden("Bestellung von ALPHA", {"alpha"}), "Groß-/Kleinschreibung egal")
pruefe(not agent._nennt_kunden("RV-200_Beta_unterschrieben.pdf\nLaufzeit", {"alpha"}), "Vertrag eines anderen Kunden zählt nicht")
pruefe(not agent._nennt_kunden("Das Alphabet", {"alpha"}), "Wortteil zählt nicht")
pruefe(agent._nennt_kunden("Termin mit Beta", {"alpha", "beta"}), "bei zwei Kunden genügt einer")

print("Abschnitt eines anderen Kunden")
ALLE = {"alpha", "beta", "gamma"}
pruefe(agent._gehoert_anderem("RV-200_Beta\nLaufzeit", {"alpha"}, ALLE), "Vertrag von Beta fällt bei Frage nach Alpha weg")
pruefe(not agent._gehoert_anderem("Alpha\nLaufzeit", {"alpha"}, ALLE), "eigener Abschnitt bleibt")
pruefe(not agent._gehoert_anderem("Mail von Alpha an Beta", {"alpha"}, ALLE), "nennt beide Kunden -> bleibt")
pruefe(not agent._gehoert_anderem("Herr X ist nicht mehr im Einkauf", {"alpha"}, ALLE), "ohne Kundennamen -> bleibt")

print("Suchvarianten dürfen den Kunden nicht verlieren")
VARIANTE_FREMD = {"text": "RV-200_Beta\nLaufzeit 01.04.2022", "meta": meta("Datei", "Teams: Pilot/Beta"), "aehnlichkeit": 0.5, "score": 0.5}
ORIGINAL = {"text": "Alpha\nZahlungsziel", "meta": meta("Datei", "Teams: Pilot/Alpha"), "aehnlichkeit": 0.4, "score": 0.4}
agent.suche = lambda frage, user="demo": [ORIGINAL] if "Alpha" in frage else [VARIANTE_FREMD]
agent.index_daten = lambda user: {"metadatas": [meta("OneNote", "MBS 2 / Alpha"), meta("OneNote", "MBS 2 / Beta")], "korpus": "alpha beta vertrag"}
agent.verstehen.varianten = lambda frage, model: ["Vertragslaufzeit Rahmenvertrag"]
treffer, _ = agent.suche_verstanden("Bis wann läuft der Vertrag mit Alpha?", "test")
pruefe([t["text"] for t in treffer] == [ORIGINAL["text"]], "Treffer einer Variante zu einem anderen Kunden werden verworfen")
treffer, _ = agent.suche_verstanden("Bis wann läuft der Vertrag?", "test")
pruefe(VARIANTE_FREMD["text"] in [t["text"] for t in treffer], "ohne genannten Kunden wie bisher")

print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
sys.exit(1 if FEHLER else 0)
