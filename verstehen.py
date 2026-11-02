"""Frageverständnis: Folgefragen und abweichende Formulierungen.

Die Suche (agent.suche) findet nur, was zur Frage passt. Zwei Fälle scheitern dabei:
  1. Rückbezüge:   "Und bis wann läuft der?" – ohne Gesprächsverlauf weiß die Suche nicht, wer "der" ist.
                   -> umschreiben(): macht aus der Folgefrage eine eigenständige Frage.
  2. Umschreibungen: "Warum kamen die Steuerungen zu spät?" – in den Daten heißt es "Lieferverzug Steuermodule".
                   -> varianten(): formuliert die Frage in Fachsprache um; gesucht wird mit allen Varianten.
Dazu eine Schutzfunktion:
  3. unbekannte_begriffe(): erkennt Namen in der Frage, die es in den Daten gar nicht gibt (z. B. "Siemens").
                   Dann wird NICHT umformuliert, damit keine Antwort zu einem falschen Kunden entsteht.

Alle Modellaufrufe hier nutzen temperature=0 (deterministisch) und format="json" (Ollama erzwingt
gültiges JSON), damit das Ergebnis maschinell zuverlässig auswertbar ist.
"""
import json
import re

import ollama

import config

# Few-Shot-Prompt: Die Beispiele zeigen dem Modell, wann es umschreiben soll und wann nicht (Themenwechsel).
UMSCHREIBEN_PROMPT = """Du bekommst einen Gesprächsverlauf und eine neue Frage. Schreibe die neue Frage so um, dass sie
OHNE den Verlauf verständlich ist: Ersetze Rückbezüge ("der", "die", "dort", "das", "und ...", "wie sieht es aus
mit ...") durch die gemeinten Kunden, Verträge, Personen oder Termine aus dem Verlauf.
Ist die Frage schon eigenständig oder geht es um ein neues Thema, gib sie UNVERÄNDERT zurück.
Achte auf das Geschlecht: "sie"/"ihr" meint eine Frau, "er"/"ihm" einen Mann. Werden im Verlauf mehrere
Personen genannt, nimm die, nach der zuletzt gefragt wurde.
Erfinde nichts dazu, beantworte die Frage nicht. Antworte nur mit JSON {"frage": "..."}.

Beispiele:
Verlauf: "Welche Konditionen hat Hoffmann?" / Neue Frage: "Und bis wann läuft der Vertrag?"
-> {"frage": "Bis wann läuft der Rahmenvertrag mit Hoffmann?"}
Verlauf: "Wer ist bei Firma X zuständig?" Antwort: "Anna Weber (Technik), im Einkauf Peter Klein." / Neue Frage: "Wie erreiche ich sie?"
-> {"frage": "Wie erreiche ich Anna Weber von Firma X?"}
Verlauf: "Welche Termine habe ich nächste Woche?" / Neue Frage: "Was muss ich für den mit Brenner vorbereiten?"
-> {"frage": "Was muss ich für den Termin mit Brenner nächste Woche vorbereiten?"}
Verlauf: "Wie hoch ist der Rabatt für Hoffmann?" / Neue Frage: "Und bei Brenner?"
-> {"frage": "Wie hoch ist der Rabatt für Brenner?"}
Verlauf: "Wie hoch ist der Rabatt für Hoffmann?" / Neue Frage: "Wann ist die Hausmesse?"
-> {"frage": "Wann ist die Hausmesse?"}"""

VARIANTEN_PROMPT = """Formuliere die Frage für eine Suche in Geschäftsunterlagen (Key-Account-Management) zweimal
anders: Ersetze Umgangssprache durch typische Fachbegriffe aus Vertrieb, Einkauf und Logistik (z. B. Ärger ->
Reklamation, zu spät -> Lieferverzug, Zeit zum Bezahlen -> Zahlungsziel, Vereinbarung -> Rahmenvertrag,
Steuerungen -> Steuermodule). Behalte alle Namen, Orte und Jahreszahlen der Frage bei.
Füge KEINE Kunden, Orte, Produkte oder Personen hinzu, die nicht in der Frage stehen.
Antworte nur mit JSON {"varianten": ["...", "..."]}."""


def _json(antwort, schluessel: str, ersatz):
    """Wert `schluessel` aus der JSON-Antwort des Modells; bei kaputtem JSON der Ersatzwert.
    So führt eine fehlerhafte Modellantwort nie zum Absturz, sondern nur zum Verzicht auf den Schritt."""
    try:
        return json.loads(antwort.message.content).get(schluessel, ersatz)
    except (json.JSONDecodeError, AttributeError):
        return ersatz


def umschreiben(frage: str, verlauf: list[dict], model: str = config.CHAT_MODEL) -> str:
    """Macht aus einer Folgefrage eine eigenständige Frage.

    Parameter:
        frage:   neue Frage des Nutzers, z. B. "Und bis wann läuft der?"
        verlauf: bisherige Fragen und Antworten [{"frage": ..., "antwort": ...}], älteste zuerst
    Rückgabe:
        eigenständige Frage, z. B. "Bis wann läuft der Rahmenvertrag mit Hoffmann?".
        Ohne Verlauf (erste Frage) wird die Frage ohne Modellaufruf unverändert zurückgegeben.
    """
    if not verlauf:
        return frage
    # Nur die letzten Runden, Antworten gekürzt auf die Kurzantwort -> kurzer, schneller Prompt
    zeilen = []
    for runde in verlauf[-config.VERLAUF_RUNDEN:]:
        kurz = runde["antwort"].split("### Details")[0].replace("### Kurzantwort", "").strip()[:300]
        zeilen.append(f"Frage: {runde['frage']}\nAntwort: {kurz}")
    antwort = ollama.chat(model=model, format="json", options={"temperature": 0, "num_ctx": config.NUM_CTX}, keep_alive=config.KEEP_ALIVE,
                          messages=[{"role": "system", "content": UMSCHREIBEN_PROMPT},
                                    {"role": "user", "content": "Verlauf:\n" + "\n\n".join(zeilen)
                                     + f"\n\nNeue Frage: {frage}"}])
    neu = str(_json(antwort, "frage", frage)).strip()
    return neu or frage  # leere Modellantwort -> Originalfrage verwenden


def varianten(frage: str, model: str = config.CHAT_MODEL) -> list[str]:
    """Bis zu zwei Umformulierungen der Frage in Fachsprache (z. B. "zu spät" -> "Lieferverzug").
    Varianten, die mit der Originalfrage identisch oder leer sind, werden verworfen."""
    antwort = ollama.chat(model=model, format="json", options={"temperature": 0, "num_ctx": config.NUM_CTX}, keep_alive=config.KEEP_ALIVE,
                          messages=[{"role": "system", "content": VARIANTEN_PROMPT},
                                    {"role": "user", "content": frage}])
    liste = _json(antwort, "varianten", [])
    return [str(v).strip() for v in liste if str(v).strip() and str(v).strip() != frage][:2]


def unbekannte_begriffe(frage: str, korpus: str) -> list[str]:
    """Großgeschriebene Begriffe der Frage, die in den Daten nirgends vorkommen (auch nicht als Wortanfang),
    z. B. "Siemens" oder "WLAN-Passwort". Dann wird die Frage NICHT erweitert: Eine Variante ohne den
    unbekannten Begriff würde sonst Treffer zu einem anderen Kunden liefern.

    Parameter:
        frage:  Frage des Nutzers
        korpus: gesamter Text aller Abschnitte im Index, kleingeschrieben
    Rückgabe:
        Liste der unbekannten Begriffe (kleingeschrieben); leer = alles bekannt
    """
    unbekannt = []
    # Großgeschriebene Wörter ab 3 Buchstaben = Kandidaten für Namen und Fachbegriffe
    for treffer in re.finditer(r"\b[A-ZÄÖÜ][\wäöüß-]{2,}", frage):
        if treffer.start() == 0:
            continue  # nur wegen des Satzanfangs großgeschrieben
        w = treffer.group().lower()
        # Wortanfang (6 Zeichen) genügt als Treffer: "Bestellungen" gilt als bekannt, wenn "bestel..." vorkommt
        if w not in korpus and w[:6] not in korpus:
            unbekannt.append(w)
    return unbekannt
