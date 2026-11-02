"""Alle Anweisungen (Prompts) an das Sprachmodell und das Ausgabekonzept.

Der System-Prompt ist aus dem bestehenden Copilot-Agenten übernommen und an RAG angepasst:
Das Modell sieht nur die Quellen, die die Suche gefunden hat, und muss jede Aussage mit [n] belegen.

Das Ausgabekonzept (AUSGABE_VORLAGE) sorgt dafür, dass jede Antwort gleich aufgebaut ist.
Die Quellenliste schreibt NICHT das Modell, sondern der Code aus den Metadaten (agent.py).
So können Links und Datumsangaben nicht falsch "erfunden" werden.

Übersicht der Prompts:
    SYSTEM_PROMPT       Rolle und Regeln für die eigentliche Antwort        -> agent.generiere()
    AUSGABE_VORLAGE     vorgeschriebener Aufbau der Antwort                 -> in SYSTEM_PROMPT eingesetzt
    KEINE_QUELLE        feste Antwort, wenn die Suche nichts findet (ohne Sprachmodell)
    WIDERSPRUCH_PROMPT  Quellen auf Widersprüche prüfen (JSON-Ausgabe)      -> agent.pruefe_widersprueche()
    GLEICH_PROMPT       Betreffen zwei Werte dieselbe Sache? (JSON-Ausgabe) -> agent._gleicher_sachverhalt()
    BESCHREIBE_PROMPT   Worauf bezieht sich ein Wert? (JSON-Ausgabe)        -> agent._beschreibe()
Die Prompts zum Frageverständnis (Folgefragen, Umformulierungen) stehen in verstehen.py.
"""

# Platzhalter {heute} und {vorlage} werden in build_system_prompt() ersetzt.
SYSTEM_PROMPT = """Rolle:
Du bist mein persönlicher Informations-Agent. Du beantwortest Fragen, indem du Informationen aus
mehreren Unternehmensquellen findest, zusammenfasst und mit exakten Quellenangaben zurückgibst.

Ziel:
Beantworte die Frage vollständig, indem du die Informationen aus OneNote ("MBS 2"), Teams und
Outlook/.msg-Dateien zusammenträgst und konsolidierst. Jede Information muss mit Quelle belegt sein.

Kontext:
- Heute ist {heute}. Rechne relative Angaben wie "morgen" oder "nächste Woche" von diesem Datum aus.
- Du bekommst unten nummerierte Quellen [1], [2], ... Nutze AUSSCHLIESSLICH diese Quellen.
- OneNote "MBS 2" hat Vorrang. Teams, Outlook-Mails und der Outlook-Kalender ergänzen.
- Kommuniziere professionell, freundlich und immer auf Deutsch (außer anders gefordert).

Regeln:
- Hänge an JEDE Aussage die Nummer der Quelle an, z. B. "Der Rabatt beträgt 8 % [2]."
- Stelle keine Information ohne Quelle als gesichert dar. Erfinde nichts.
- Steht die Antwort nicht in den Quellen, schreibe das ausdrücklich.
- Beantworte genau das Gefragte. Belegen die Quellen nur etwas Ähnliches (z. B. Ersatzteile statt
  Neuteile, ein anderes Jahr, eine andere Person), sage klar, dass es zum Gefragten keine Angabe gibt,
  und nenne das Ähnliche nur als Hinweis.
- Verwechsle keine Begriffe: Ein Rabatt ist keine Gutschrift, eine Preisobergrenze ist keine Preiserhöhung.
- Ordne jede Angabe nur dem Kunden zu, zu dem ihre Quelle gehört (siehe "Ablage" im Quellenkopf).
- Bei Fragen nach Ansprechpartnern oder Zuständigen: Nenne ALLE in den Quellen genannten aktuellen
  Personen mit ihrer Rolle, nicht nur eine.
- Ist ein "Inhaltsverzeichnis der Ablage" dabei, ist es für Aufzählungen (z. B. alle Kunden) vollständig
  und maßgeblich: nenne alle dort aufgeführten Kunden.
- Betrifft ein geprüfter Widerspruch genau das Gefragte, übernimm nicht stillschweigend einen Wert,
  sondern nenne in der Kurzantwort beide Werte mit Quelle und sage, welche Quelle neuer ist.
- Keine Vermutungen ("möglicherweise", "könnte bedeuten") über Zusammenhänge, die nicht in den Quellen
  stehen. Bleib beim gefragten Thema und lass Angaben zu anderen Themen weg.
- Ist nach einer Gutschrift gefragt, nenne sie Gutschrift (nicht Rabatt) – übernimm die Begriffe der Quelle.
- Schreibe KEINE eigenen Abschnitte "Widersprüche" oder "Quellen"; die werden automatisch angehängt.

{vorlage}"""

# Teil 1-3 der Antwort (vom Modell geschrieben). Teil 4 "Widersprüche" und Teil 5 "Quellen"
# hängt agent.anhang_markdown() danach aus geprüften Daten an.
AUSGABE_VORLAGE = """Antworte immer genau in diesem Format (Markdown):

### Kurzantwort
Ein bis drei Sätze mit der direkten Antwort und Quellennummern.

### Details
- Stichpunkte mit allen relevanten Fakten, jeder Punkt mit [n].

### Vorschläge für präzisere Rückfragen
- Zwei bis drei konkrete Folgefragen, mit denen man gezielter suchen kann."""

# Wird OHNE Sprachmodell ausgegeben, wenn die Suche nichts ausreichend Ähnliches findet.
# So kann an dieser Stelle garantiert nichts erfunden werden.
KEINE_QUELLE = """### Kurzantwort
Zu dieser Frage wurde in Ihren Daten (OneNote "MBS 2", Teams, Outlook) **keine passende Quelle gefunden**.
Ich gebe daher keine ungesicherte Antwort.

### Vorschläge für präzisere Rückfragen
- Nennen Sie den Kundennamen, z. B. "Was wurde mit Hoffmann Maschinenbau zu ... vereinbart?"
- Grenzen Sie den Zeitraum ein, z. B. "... im Jahr 2019".
- Nennen Sie die Quelle, z. B. "Was steht in OneNote im Abschnitt ... dazu?"
"""


def _datum(d) -> str:
    """date -> "TT.MM.JJJJ"."""
    return d.strftime("%d.%m.%Y")


def keine_quelle(zeitraum=None) -> str:
    """Antworttext für "nichts gefunden". Bei Zeitfragen mit dem konkreten Zeitraum, damit der Nutzer
    sieht, welcher Zeitraum durchsucht wurde (zeitraum = (von, bis, Beschreibung) aus zeitraum.py)."""
    if not zeitraum:
        return KEINE_QUELLE
    von, bis, name = zeitraum
    return (f"### Kurzantwort\nFür **{name}** ({_datum(von)} – {_datum(bis)}) wurden in Ihrem Kalender, "
            "Ihren Mails, Teams und OneNote **keine Termine oder Einträge gefunden**.\n\n"
            "### Vorschläge für präzisere Rückfragen\n"
            "- Erweitern Sie den Zeitraum, z. B. \"in den nächsten 14 Tagen\" oder \"diesen Monat\".\n"
            "- Fragen Sie nach einem Kunden, z. B. \"Wann ist der nächste Termin mit Hoffmann?\"\n")


def build_system_prompt(heute) -> str:
    """Fertiger System-Prompt mit heutigem Datum und Ausgabevorlage."""
    from zeitraum import beschreibe_heute
    return SYSTEM_PROMPT.format(heute=beschreibe_heute(heute), vorlage=AUSGABE_VORLAGE)


# Erste Stufe der Widerspruchsprüfung: Das Modell meldet KANDIDATEN. Ob sie stimmen, prüft danach der Code.
WIDERSPRUCH_PROMPT = """Du prüfst Quellen auf Widersprüche. Ein Widerspruch liegt vor, wenn zwei Quellen zum SELBEN
Sachverhalt (z. B. Vertragsende, Termin, Preis, Menge) unterschiedliche Werte nennen – auch wenn eine neuere Quelle die
ältere ändert. Verschiedene Produkte (z. B. PA-50 und PA-70) oder verschiedene Jahre sind kein Widerspruch.
Übernimm die Werte wörtlich aus dem Text der Quellen.

Beispiel: [1] "Laufzeit: 01.01.2024 bis 31.12.2026" und [2] "wir verlängern den Vertrag bis zum 31.03.2027"
-> {"widersprueche": [{"thema": "Vertragsende", "wert_a": "31.12.2026", "quelle_a": 1, "wert_b": "31.03.2027", "quelle_b": 2}]}

Antworte nur mit JSON:
{"widersprueche": [{"thema": "...", "wert_a": "...", "quelle_a": 1, "wert_b": "...", "quelle_b": 2}]}
Gibt es keine, antworte {"widersprueche": []}."""

# Gegenprüfung, gemeinsamer Teil: beide Sätze sehen und je benennen, worauf sich der Wert bezieht.
# Das Feld "gleich" wird vom Code NICHT ausgewertet (zu unzuverlässig), nur die Beschreibungen.
# Die Beispiele ("Few-Shot") zeigen dem Modell echte und falsche Widersprüche.
GLEICH_PROMPT = """Du entscheidest, ob zwei Angaben dieselbe Sache betreffen. Benenne zuerst kurz, worauf sich
jeder Wert bezieht, dann entscheide. Antworte nur mit JSON {"a_betrifft": "...", "b_betrifft": "...", "gleich": true/false}.

Beispiele:
A: "Laufzeit: 01.01.2024 bis 31.12.2026" / B: "wir verlängern den Vertrag bis zum 31.03.2027"
-> {"a_betrifft": "Vertragsende", "b_betrifft": "Vertragsende (verlängert)", "gleich": true}
A: "Kick-off am 10.03." / B: "Kick-off auf den 12.03. verschoben"
-> {"a_betrifft": "Datum Kick-off", "b_betrifft": "Datum Kick-off (verschoben)", "gleich": true}
A: "Preisanpassung jährlich max. +4 %" / B: "Listenpreise steigen 2027 um 3,5 %"
-> {"a_betrifft": "Obergrenze Preisanpassung", "b_betrifft": "Listenpreiserhöhung 2027", "gleich": false}
A: "Montag 14:00 Forecast-Runde" / B: "Mittwoch 16:00 Abstimmung Supply Chain"
-> {"a_betrifft": "Termin Forecast-Runde", "b_betrifft": "Termin Supply-Chain-Abstimmung", "gleich": false}"""

# Gegenprüfung, getrennter Teil: jeder Satz wird EINZELN beschrieben, damit das Modell die
# Beschreibung des einen Werts nicht einfach für den anderen kopieren kann.
BESCHREIBE_PROMPT = """Beschreibe in 2 bis 5 Wörtern, worauf sich der Wert im Satz bezieht (was genau er angibt).
Antworte nur mit JSON {"betrifft": "..."}.

Beispiele:
Satz: "Laufzeit: 01.01.2024 bis 31.12.2026" / Wert: "31.12.2026" -> {"betrifft": "Enddatum des Vertrags"}
Satz: "wir verlängern den Vertrag bis zum 31.03.2027" / Wert: "31.03.2027" -> {"betrifft": "Neues Enddatum des Vertrags"}
Satz: "Kick-off auf den 12.03. verschoben" / Wert: "12.03." -> {"betrifft": "Termin Kick-off"}
Satz: "Preisanpassung jährlich max. +4 %" / Wert: "+4 %" -> {"betrifft": "Obergrenze Preisanpassung"}
Satz: "Listenpreise steigen 2027 um 3,5 %" / Wert: "3,5 %" -> {"betrifft": "Listenpreiserhöhung 2027"}
Satz: "Angebot gültig bis 30.06." / Wert: "30.06." -> {"betrifft": "Gültigkeit des Angebots"}
Satz: "Können Sie uns bis 31.03. ein Angebot schicken?" / Wert: "31.03." -> {"betrifft": "Frist für Angebotsabgabe"}"""


def build_user_prompt(frage: str, quellen: list[dict], widersprueche: list[dict] | None = None,
                      zeitraum=None) -> str:
    """Baut den Kontext für das Modell: jede gefundene Textstelle mit Nummer und Herkunft, dann die Frage.

    Aufbau des Ergebnisses:
        Quellen:
        [1] OneNote | Rahmenvertrag | Ablage: MBS 2 / Hoffmann | Datum: 2023-04-01
        <Text des Abschnitts>
        ---
        [2] ...
        ---
        Frage: ...
        (optional) Hinweis zum gefragten Zeitraum
        (optional) Liste der vom Code bestätigten Widersprüche

    Die Nummern [n] entsprechen der Reihenfolge in `quellen`; dieselbe Nummerierung nutzt die
    Quellenliste in agent.anhang_markdown(). So passen die Verweise im Text und die Liste zusammen.
    """
    teile = []
    for i, q in enumerate(quellen, start=1):
        m = q["meta"]
        # Der Ablageort (z. B. "MBS 2 / Brenner Medizintechnik") zeigt dem Modell, zu welchem Kunden eine Quelle gehört
        kopf = (f"[{i}] {m['quelle']} | {m.get('titel', '')} | Ablage: {m.get('ort', '')} | "
                f"Datum: {m.get('datum') or 'unbekannt'}")
        teile.append(f"{kopf}\n{q['text']}")
    kontext = "\n\n---\n\n".join(teile)
    prompt = f"Quellen:\n\n{kontext}\n\n---\n\nFrage: {frage}"
    if zeitraum:
        # Bei Zeitfragen: dem Modell sagen, dass ALLE Quellen in den Zeitraum fallen und wie viele es sind
        von, bis, name = zeitraum
        kalender = sum(q["meta"]["quelle"] == "Kalender" for q in quellen)
        prompt += (f"\n\nGefragter Zeitraum: {name} = {_datum(von)} bis {_datum(bis)}. Alle Quellen oben haben ein "
                   f"Datum in diesem Zeitraum: {kalender} Kalendertermin(e) und {len(quellen) - kalender} weitere "
                   "Einträge aus Mails, Teams oder OneNote. Nenne diese Anzahl in der Kurzantwort und die "
                   "wichtigsten Termine. In den Details: chronologisch je Termin Wochentag, Datum, Uhrzeit, "
                   "Ort und worum es geht (Vorbereitung, offene Punkte). Eine vollständige Terminliste wird "
                   "automatisch angehängt.")
    if widersprueche:
        # Kleine Modelle beachten Hinweise am Ende des Prompts am zuverlässigsten
        liste = "\n".join(f"- {w['thema']}: \"{w['wert_a']}\" [{w['quelle_a']}] vs. \"{w['wert_b']}\" [{w['quelle_b']}]"
                          for w in widersprueche)
        prompt += ("\n\nGeprüfte Widersprüche zwischen den Quellen (stehen automatisch im Abschnitt "
                   "\"Widersprüche\"; in der Kurzantwort NUR erwähnen, wenn sie genau das Gefragte betreffen):\n"
                   f"{liste}")
    return prompt
