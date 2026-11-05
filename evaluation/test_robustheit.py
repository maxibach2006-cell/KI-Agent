"""Test der Fehlerfälle beim Einlesen und bei Modellantworten OHNE Ollama und ohne Microsoft 365.

Geprüft wird: Ein Ausfall einer Quelle löscht nichts aus dem Index, doppelte Abschnitte brechen das Einlesen nicht
ab, einzelne defekte Dateien oder gesperrte Kanäle kosten nicht die ganze Quelle, und unerwartetes JSON sowie
unmögliche Zeitangaben führen nicht zum Absturz. Modellaufrufe werden durch feste Antworten ersetzt.

Aufruf:  python evaluation/test_robustheit.py
"""
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import config  # noqa: E402
import ingest as ingest_modul  # noqa: E402
import parsers  # noqa: E402
import verstehen  # noqa: E402
from connectors import files, onenote, teams  # noqa: E402
from zeitraum import erkenne_zeitraum  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def doc(quelle: str, text: str, link: str) -> dict:
    return {"text": text, "meta": {"quelle": quelle, "titel": "Titel", "ort": f"Ablage / Firma {quelle}",
                                   "absender": "", "datum": "2026-01-15", "link": link}}


def antwort(inhalt: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=inhalt))


class FalscherGraph:
    """Ersetzt GraphClient: `fehler` = Pfade, die mit HTTP 403 scheitern, `listen`/`dateien` = feste Antworten."""

    def __init__(self, listen: dict, fehler: tuple = (), dateien: dict | None = None):
        self.listen, self.fehler, self.dateien, self.probleme = listen, fehler, dateien or {}, []

    def melde_problem(self, text: str) -> None:
        self.probleme.append(text)

    def get_all(self, pfad: str) -> list[dict]:
        if pfad in self.fehler:
            raise requests.HTTPError("403 Forbidden")
        return self.listen.get(pfad, [])

    def get(self, pfad: str) -> dict:
        return {"id": "LW"}

    def get_bytes(self, pfad: str) -> bytes:
        return self.dateien[pfad]


def quellen_im_index(user: str) -> dict:
    metas = ingest_modul.oeffne_collection(user).get(include=["metadatas"])["metadatas"]
    ergebnis = {}
    for m in metas:
        ergebnis[m["quelle"]] = ergebnis.get(m["quelle"], 0) + 1
    return ergebnis


def teste_index() -> None:
    print("Index:")
    stand = {}
    ingest_modul.lade_dokumente = lambda source: ("test", list(stand["docs"]), list(stand["fehlt"]))
    # Festes Embedding: Für diese Prüfungen zählt nur, welche Abschnitte im Index liegen
    ingest_modul.ollama.embed = lambda model, input: SimpleNamespace(embeddings=[[1.0, 0.0, 0.0] for _ in input])

    a, b = doc("OneNote", "Seite A", "link-a"), doc("Teams", "Nachricht B", "link-b")
    stand.update(docs=[a, b], fehlt=[])
    pruefe(ingest_modul.ingest("graph") == [], "vollständiger Lauf meldet nichts")
    pruefe(quellen_im_index("test") == {"OneNote": 1, "Teams": 1, "Übersicht": 1}, "alle Abschnitte im Index")

    stand.update(docs=[b], fehlt=["OneNote"])
    pruefe(ingest_modul.ingest("graph") == ["OneNote"], "ausgefallene Quelle wird gemeldet")
    pruefe(quellen_im_index("test").get("OneNote") == 1, "ausgefallene Quelle bleibt im Index")
    pruefe(quellen_im_index("test").get("Übersicht") == 1, "bisherige Übersicht bleibt erhalten")

    stand.update(docs=[], fehlt=["OneNote", "Teams"])
    ingest_modul.ingest("graph", neu=True)
    pruefe(quellen_im_index("test") == {"OneNote": 1, "Teams": 1, "Übersicht": 1},
           "Totalausfall mit --neu löscht nichts")

    stand.update(docs=[b], fehlt=[])
    ingest_modul.ingest("graph")
    pruefe("OneNote" not in quellen_im_index("test"), "ohne Fehler wird eine gelöschte Seite entfernt")

    stand.update(docs=[b, b, doc("Teams", "ok", ""), doc("Teams", "ok", "")], fehlt=[])
    ingest_modul.ingest("graph")
    pruefe(quellen_im_index("test").get("Teams") == 2, "doppelte Abschnitte werden einmal gespeichert")

    def ausfall(model, input):
        raise ConnectionError("Ollama nicht erreichbar")
    ingest_modul.ollama.embed = ausfall
    stand.update(docs=[doc("Teams", "Ganz neuer Text", "link-c")], fehlt=[])
    try:
        ingest_modul.ingest("graph")
    except ConnectionError:
        pass
    pruefe(quellen_im_index("test").get("Teams") == 2, "Ausfall der Embeddings lässt den alten Stand bestehen")


def teste_connectoren() -> None:
    print("Connectoren:")
    antwort_text = {"id": "2", "body": {"content": "Antwort"}, "messageType": "message", "createdDateTime": "2026-01-16"}
    nachricht = {"id": "1", "body": {"content": "Inhalt"}, "messageType": "message", "createdDateTime": "2026-01-15",
                 "replies": [antwort_text]}
    gesperrt = "/teams/T/channels/K2/messages?$expand=replies"
    graph = FalscherGraph({"/me/joinedTeams": [{"id": "T", "displayName": "Team"}],
                           "/teams/T/channels": [{"id": "K1", "displayName": "Eins"}, {"id": "K2", "displayName": "Zwei"}],
                           "/teams/T/channels/K1/messages?$expand=replies": [nachricht]},
                          fehler=(gesperrt, "/me/chats"))
    docs = teams.lade(graph)
    pruefe(len(docs) == 2 and docs[0]["meta"]["ort"] == "Team > Eins", "gesperrter Kanal kostet nicht die übrigen")
    pruefe(docs[1]["text"] == "Antwort", "Antworten im Thread werden mitgelesen")
    pruefe(len(graph.probleme) == 2, "gesperrter Kanal und gesperrte Chats werden gemeldet")

    eintrag = {"webUrl": "http://x", "lastModifiedDateTime": "2026-01-15T00:00:00Z"}
    graph = FalscherGraph({"/drives/LW/items/R/children": [{"id": "A", "name": "defekt.pdf", **eintrag},
                                                           {"id": "B", "name": "gut.txt", **eintrag}]},
                          dateien={"/drives/LW/items/A/content": b"keine pdf", "/drives/LW/items/B/content": b"Text"})
    docs = []
    files._durchlaufe(graph, "LW", "R", "Ablage", docs)
    pruefe([d["meta"]["titel"] for d in docs] == ["gut.txt"], "defekte Datei kostet nicht die übrigen")
    pruefe(len(graph.probleme) == 1, "defekte Datei wird gemeldet")

    item = {"id": "B", "name": "gut.txt", "eTag": "v1", **eintrag}
    graph = FalscherGraph({"/drives/LW/items/R/children": [item]}, dateien={})  # Herunterladen würde scheitern
    alt, neu, docs = {"B": {"etag": "v1", "doc": {"text": "aus dem Speicher"}}}, {}, []
    files._durchlaufe(graph, "LW", "R", "Ablage", docs, alt, neu)
    pruefe(docs == [{"text": "aus dem Speicher"}] and "B" in neu, "unveränderte Datei wird nicht neu geladen")

    graph = FalscherGraph({"/N/sections": [{"id": "A"}], "/N/sectionGroups": [{"id": "G"}],
                           "/me/onenote/sectionGroups/G/sections": [{"id": "B"}]})
    pruefe([a["id"] for a in onenote._alle_abschnitte(graph, "/N")] == ["A", "B"], "Abschnittsgruppen werden gelesen")

    mail = parsers.lies_eml(b"Subject: Test\r\nDate: kein Datum\r\n\r\nText")
    pruefe(mail["datum"] == "" and "Text" in mail["text"], "Mail mit unlesbarem Datum bleibt nutzbar")


def teste_modellantworten() -> None:
    print("Modellantworten:")
    pruefe(verstehen.json_wert(antwort("[]"), "x", "ersatz") == "ersatz", "Liste statt Objekt -> Ersatzwert")
    pruefe(verstehen.json_wert(antwort("kein json"), "x", []) == [], "kaputtes JSON -> Ersatzwert")
    pruefe(verstehen.json_wert(antwort('{"x": 5}'), "x", "") == "", "falscher Typ -> Ersatzwert")
    pruefe(verstehen.json_wert(antwort('{"x": ["a"]}'), "x", []) == ["a"], "gültiger Wert wird übernommen")

    meta = {"quelle": "Teams", "titel": "Titel", "ort": "Ablage", "datum": "2026-01-15"}
    treffer = [{"text": "Kopf\nInhalt eins", "meta": meta}, {"text": "Kopf\nInhalt zwei", "meta": meta}]
    for inhalt in ("[]", '{"widersprueche": "keine"}', '{"widersprueche": ["31.03."]}', "null", "kein json"):
        agent.ollama.chat = lambda **kwargs: antwort(inhalt)
        try:
            pruefe(agent.pruefe_widersprueche("Frage", treffer) == [], f"Widerspruchsprüfung übersteht {inhalt}")
        except Exception as e:
            pruefe(False, f"Widerspruchsprüfung stürzt bei {inhalt} ab: {e}")
    agent.ollama.chat = lambda **kwargs: antwort("[]")
    pruefe(agent._gleicher_sachverhalt("a", "t1", "b", "t2", "modell-test") is False, "Gegenprüfung übersteht []")
    pruefe(agent._beschreibe("a", "Satz", "modell-test") == "", "Beschreibung übersteht []")


def teste_nutzer_und_ausgabe() -> None:
    print("Nutzer und Ausgabe:")
    pruefe(config.db_path("a.b@firma.de") != config.db_path("a_b@firma.de"), "ähnliche Nutzernamen bleiben getrennt")
    pruefe(config.db_path("demo").name == "demo", "Demo-Index behält seinen Namen")
    pruefe(config.index_nutzer("") == "demo", "ohne Anmeldung nur Demo-Daten")
    pruefe(config.index_nutzer("fremd@firma.de") == "demo", "Adresse ohne eigenen Index bekommt Demo-Daten")
    pruefe(list(agent._ohne_bilder(iter(["Text ![x](http://a)"])))[0] == "Text [x](http://a)", "Bild wird zum Link")
    pruefe("".join(agent._ohne_bilder(iter(["Text !", "[x](http://a)"]))) == "Text [x](http://a)",
           "Bild über zwei Teile verteilt wird erkannt")
    pruefe("".join(agent._ohne_bilder(iter(["Achtung!", " Weiter!"]))) == "Achtung! Weiter!", "Ausrufezeichen bleiben")
    quellen = [{"text": "Kopf\nEnde 31.12.2026", "meta": {}}]
    pruefe(agent._beleg("31.12.2026", 0, quellen) == 1, "Quellennummer 0 wird nicht als Beleg übernommen")
    pruefe(agent._beleg("31.12.2026", -1, quellen) == 1, "negative Quellennummer wird korrigiert")
    termin = {"text": "Kopf\nCall 09:30 Uhr, Frist", "meta": {"quelle": "Outlook", "datum": "2026-01-01", "titel": "T"},
              "tage": [date(2026, 11, 10)]}
    pruefe("09:30" not in agent.terminliste_markdown([termin]), "Mail bekommt keine fremde Uhrzeit")
    termin["meta"]["quelle"] = "Kalender"
    pruefe("09:30" in agent.terminliste_markdown([termin]), "Kalendertermin behält die Uhrzeit")
    pruefe("Firma Hoffmann" not in str(ingest_modul.inhaltsverzeichnis([])), "Inhaltsverzeichnis ohne Daten bleibt leer")
    verzeichnis = ingest_modul.inhaltsverzeichnis([{"text": "", "meta": {"quelle": "Datei", "ort": "Teams: Team/Firma X"}}])
    pruefe("Ablageordner: Firma X." in verzeichnis["text"], "Kunde wird auch aus Graph-Pfaden erkannt")


def teste_zeitangaben() -> None:
    print("Zeitangaben:")
    heute = date(2026, 11, 4)
    for frage in ("Was steht in KW 60 an?", "Was war in KW 0?", "Was steht in KW 53 an?",
                  "Was ist in den nächsten 99999999999 Tagen?", "Was war im März 0000?", "Was ist im Dezember 9999?"):
        try:
            erkenne_zeitraum(frage, heute)
            pruefe(True, f"kein Absturz: {frage}")
        except Exception as e:
            pruefe(False, f"Absturz bei {frage}: {e}")
    pruefe(erkenne_zeitraum("Was steht in KW 60 an?", heute) is None, "unmögliche KW gilt als normale Frage")
    pruefe(erkenne_zeitraum("Was steht in KW 47 an?", heute)[0] == date(2026, 11, 16), "gültige KW funktioniert weiter")
    pruefe(erkenne_zeitraum("Was steht nächste Woche an?", heute)[0] == date(2026, 11, 9), "nächste Woche funktioniert weiter")


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ordner:
        config.DATA_DIR = Path(ordner)
        teste_index()
    teste_connectoren()
    teste_modellantworten()
    teste_nutzer_und_ausgabe()
    teste_zeitangaben()
    print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
    sys.exit(1 if FEHLER else 0)


if __name__ == "__main__":
    main()
