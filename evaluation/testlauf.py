"""Automatischer Testlauf: Jede Frage aus testkatalog.json wird beantwortet und doppelt geprüft.

  1. Regelprüfung (Code, objektiv):
     - Fakten:      enthält die Antwort die Pflichtangaben? (z. B. "45 Tage")
     - Quellen:     wurden die erwarteten Quellen gefunden?
     - Zitate:      stehen [n]-Verweise in der Antwort und zeigen sie auf existierende Quellen?
     - Format:      sind die Abschnitte des Ausgabekonzepts vorhanden?
     - Verbote:     keine Angaben, die nicht in die Antwort gehören (z. B. andere Kunden)
     - Keine Quelle: bei unbeantwortbaren Fragen darf nichts gefunden/erfunden werden
  2. KI-Gutachter (zweites, größeres Modell, z. B. qwen2.5:14b): vergleicht die Antwort mit der Sollantwort
     und den Quelltexten und bewertet Korrektheit, Vollständigkeit und Halluzinationen.

Aufruf (aus dem Projektordner):
    python evaluation/testlauf.py                 # Antworten erzeugen + prüfen
    python evaluation/testlauf.py --nur-gutachter # nur prüfen (Antworten aus letztem Lauf); setzt nach Abbruch fort
    python evaluation/testlauf.py --gutachter qwen2.5:7b  # kleiner Gutachter, falls wenig Speicher

Speicher: Agent und Gutachter laufen nacheinander, nie gleichzeitig. Vor dem Gutachter werden die
Agent-Modelle entladen; bei < 5 GB freiem RAM wird statt qwen2.5:14b das kleine Modell genommen.
Hinweis: Ein 7B-Gutachter bewertet das 7B-Agentenmodell unzuverlässig (wertet z. B. Rückfragen als Halluzination).
    python evaluation/testlauf.py --kategorie Zeitfrage
Ergebnis: evaluation/testlauf_bericht.md

Ablauf von main():
    Phase 1  erzeuge_antworten()  Agent beantwortet alle Fragen -> testlauf_antworten.json
    Phase 2  regelpruefung()      objektive Prüfregeln im Code
             gutachten()          Bewertung durch das Gutachter-Modell
    Bericht  bericht()            Markdown-Bericht mit Übersicht je Kategorie und Details zu Fehlern
Eine Frage gilt als bestanden, wenn ALLE Regeln erfüllt sind UND der Gutachter sie als korrekt
und halluzinationsfrei bewertet.

Aufbau eines Eintrags in testkatalog.json:
    frage, kategorie, soll (Sollantwort für den Gutachter), fakten (Liste von Alternativ-Gruppen,
    je Gruppe muss eine Schreibweise vorkommen), quellen (erwartete Titel/Links), optional:
    vorher (Vorfragen für Rückbezüge), keine_quelle, widerspruch, darf_nicht, verstanden, verstanden_nicht
"""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import ollama  # noqa: E402

import agent  # noqa: E402
import config  # noqa: E402
from zeitraum import beschreibe_heute  # noqa: E402

ORDNER = Path(__file__).parent
ANTWORTEN = ORDNER / "testlauf_antworten.json"
GUTACHTER_MODELL = "qwen2.5:14b"

GUTACHTER_PROMPT = """Du bist ein strenger Prüfer für einen KI-Agenten im Key-Account-Management.
Du bekommst: die Frage, eine Sollantwort (was korrekt ist), die Quelltexte, die der Agent gesehen hat,
und die Antwort des Agenten. Bewerte NUR inhaltlich (Formatierung egal):

- korrekt: Stimmen alle Aussagen der Antwort mit Sollantwort und Quelltexten überein? Eine Antwort, die
  sagt "dazu gibt es keine Information", ist NUR korrekt, wenn auch die Sollantwort sagt, dass es dazu
  keine Information gibt. Nennt die Sollantwort konkrete Fakten, ist "keine Information" FALSCH.
- vollstaendig: Enthält die Antwort die wesentlichen Punkte der Sollantwort?
- halluzination: Behauptet die Antwort etwas, das weder in den Quelltexten noch in der Sollantwort steht
  (erfundene Zahlen, Termine, Personen, Zusagen)? Allgemeine Höflichkeit und Rückfragen zählen nicht.
- note: 1 (sehr gut) bis 5 (unbrauchbar).

WICHTIG – das gehört zum vorgeschriebenen Antwortformat und ist KEINE Halluzination und kein Fehler:
der Abschnitt "Vorschläge für präzisere Rückfragen", eine Tabelle "Termine im Zeitraum", ein Abschnitt
"Widersprüche" (wenn Quellen sich unterscheiden) und zusätzliche Details, die in den Quelltexten stehen.
Eine Halluzination ist nur eine Tatsachenbehauptung, die in KEINEM Quelltext und nicht in der Sollantwort steht.
Bewerte die GESAMTE Antwort (Kurzantwort UND Details): Steht ein Punkt der Sollantwort in den Details, ist er enthalten.
Sagt die Antwort ausdrücklich, dass es zum Gefragten keine Angabe gibt, und nennt Ähnliches nur als Hinweis,
ist das korrekt und keine Halluzination.

Antworte nur mit JSON:
{"korrekt": true, "vollstaendig": true, "halluzination": false, "note": 1, "begruendung": "ein Satz"}"""


# --- Phase 1: Antworten erzeugen -------------------------------------------
def erzeuge_antworten(tests: list[dict]) -> list[dict]:
    """Lässt den Agenten jede Testfrage beantworten und speichert Antwort, Treffer und Zwischenergebnisse,
    damit die Prüfung (Phase 2) später ohne erneutes Beantworten laufen kann."""
    ergebnisse = []
    for i, t in enumerate(tests, start=1):
        # Rückbezug-Tests: Vorfragen echt durchspielen, damit der Gesprächsverlauf realistisch ist
        verlauf = []
        for vorfrage in t.get("vorher", []):
            vorher = agent.antworte(vorfrage, verlauf=verlauf)
            verlauf.append({"frage": vorfrage, "antwort": vorher["antwort"]})
        e = agent.antworte(t["frage"], verlauf=verlauf)
        ergebnisse.append({**t, "antwort": e["antwort"], "sekunden": round(e["sekunden"], 1),
                           "widersprueche": e["widersprueche"], "verstanden_als": e["verstanden_als"],
                           "varianten": e["varianten"],
                           "treffer": [{"meta": x["meta"], "text": x["text"]} for x in e["treffer"]]})
        print(f"[{i:2}/{len(tests)}] {e['sekunden']:5.1f}s  {t['frage']}")
    return ergebnisse


# --- Regelprüfung ------------------------------------------------------------
def _norm(text: str) -> str:
    """Für Vergleiche vereinheitlichen: schmale/geschützte Leerzeichen -> normale Leerzeichen, alles klein."""
    return text.replace(" ", " ").replace("\xa0", " ").lower()


def regelpruefung(e: dict) -> dict[str, tuple[bool, str]]:
    """Objektive Prüfregeln für eine Antwort.

    Rückgabe: {Regelname: (bestanden, Erläuterung)}, z. B. {"Fakten": (False, "fehlt: 45 Tage")}.
    Welche Regeln geprüft werden, hängt vom Testfall ab (z. B. "Widerspruch" nur bei widerspruch=true).
    """
    antwort, treffer = e["antwort"], e["treffer"]
    rumpf = _norm(antwort.split("### Widersprüche")[0])  # Antworttext inkl. Terminliste, ohne Quellenliste
    titel = " ".join(_norm(x["meta"]["titel"] + " " + x["meta"]["link"]) for x in treffer)
    p = {}

    if e.get("keine_quelle"):
        p["Keine Quelle"] = (not treffer, "nichts gefunden" if not treffer else f"{len(treffer)} Quellen gefunden")
        return p

    # Jede Faktengruppe enthält erlaubte Schreibweisen (z. B. ["45 Tage", "45 Tagen"]); eine muss vorkommen
    fehlend = [g[0] for g in e["fakten"] if not any(_norm(alt) in rumpf for alt in g)]
    p["Fakten"] = (not fehlend, "alle enthalten" if not fehlend else "fehlt: " + ", ".join(fehlend))

    nicht_gefunden = [q for q in e["quellen"] if _norm(q) not in titel]
    p["Quellen"] = (not nicht_gefunden, "gefunden" if not nicht_gefunden else "fehlt: " + ", ".join(nicht_gefunden))

    # alle Quellenverweise einsammeln, auch zusammengefasste wie "[1, 3]"
    zitate = {int(n) for gruppe in re.findall(r"\[([\d,\s]+)\]", rumpf) for n in re.findall(r"\d+", gruppe)}
    ungueltig = [n for n in zitate if not 1 <= n <= len(treffer)]
    zitate_ok = (bool(zitate) or not treffer) and not ungueltig
    p["Zitate"] = (zitate_ok, f"{len(zitate)} Verweise" + (f", ungültig: {ungueltig}" if ungueltig else ""))

    abschnitte = ["### Kurzantwort", "### Details", "### Quellen"] if treffer else ["### Kurzantwort"]
    fehlt = [a for a in abschnitte if a not in antwort]
    p["Format"] = (not fehlt, "vollständig" if not fehlt else "fehlt: " + ", ".join(fehlt))

    verboten = [v for v in e.get("darf_nicht", []) if _norm(v) in rumpf]
    if e.get("darf_nicht") is not None:
        p["Verbote"] = (not verboten, "ok" if not verboten else "enthält: " + ", ".join(verboten))

    if e.get("widerspruch"):
        p["Widerspruch"] = (bool(e["widersprueche"]), f"{len(e['widersprueche'])} erkannt")

    # Rückbezug: Wurde die Folgefrage richtig verstanden (mind. ein erwartetes Wort) bzw. bei
    # Themenwechsel NICHT mit dem alten Thema vermischt?
    verstanden = _norm(e.get("verstanden_als", e["frage"]))
    if e.get("verstanden"):
        p["Verstanden"] = (any(w in verstanden for w in e["verstanden"]), f"als: {e.get('verstanden_als')}")
    if e.get("verstanden_nicht"):
        p["Verstanden"] = (not any(w in verstanden for w in e["verstanden_nicht"]), f"als: {e.get('verstanden_als')}")
    return p


# --- Phase 2: KI-Gutachter ----------------------------------------------------
def entlade(*modelle: str) -> None:
    """Modell sofort aus GPU/RAM nehmen (keep_alive=0)."""
    for m in modelle:
        try:
            if m == config.EMBED_MODEL:  # Embedding-Modelle kennen kein generate(); leerer Input entlädt nicht
                ollama.embed(model=m, input="x", keep_alive=0)
            else:
                ollama.generate(model=m, prompt="", keep_alive=0)
        except ollama.ResponseError:
            pass


def waehle_gutachter(wunsch: str) -> str:
    """Zwei große Modelle gleichzeitig sprengen 8 GB VRAM + 16 GB RAM (Absturz im zweiten Testlauf).
    Darum: Agent-Modelle vorher entladen und bei wenig freiem RAM auf das kleine Modell ausweichen."""
    entlade(config.CHAT_MODEL, config.EMBED_MODEL)
    for _ in range(15):  # Ollama entlädt verzögert -> bis zu 15 s warten
        geladen = [m.model for m in ollama.ps().models]
        if not geladen:
            break
        time.sleep(1)
    if geladen:
        print(f"Achtung, noch geladen: {geladen} -> kleiner Gutachter, um den Speicher nicht zu überlasten")
        return config.CHAT_MODEL
    try:
        import psutil
        frei_gb = psutil.virtual_memory().available / 1024 ** 3
    except ImportError:
        return wunsch
    # 14B (~9 GB) liegt bei leerer 8-GB-GPU zu ~7 GB im VRAM, ~2-3 GB im RAM -> 5 GB frei reichen mit Reserve
    if "14b" in wunsch and frei_gb < 5:
        print(f"Nur {frei_gb:.1f} GB RAM frei -> Gutachter {config.CHAT_MODEL} statt {wunsch}")
        return config.CHAT_MODEL
    return wunsch


def gutachten(e: dict, modell: str) -> dict:
    """Lässt das Gutachter-Modell eine Antwort bewerten.

    Der Gutachter sieht Frage, Sollantwort, die Quelltexte des Agenten (je max. 700 Zeichen) und die
    Antwort ohne Quellenliste. Rückgabe: {"korrekt", "vollstaendig", "halluzination", "note", "begruendung"}.
    """
    quelltexte = "\n\n".join(f"[{i}] {x['text'][:700]}" for i, x in enumerate(e["treffer"], start=1)) or "(keine)"
    # Ohne das heutige Datum kann der Gutachter "nächste Woche" & Co. nicht prüfen
    heute = config.heute()
    nutzer = (f"HEUTE IST: {beschreibe_heute(heute)}. Nächste Woche = "
              f"{heute + timedelta(days=7 - heute.weekday()):%d.%m.%Y} bis "
              f"{heute + timedelta(days=13 - heute.weekday()):%d.%m.%Y}.\n\n"
              f"FRAGE:\n{e['frage']}\n\nSOLLANTWORT:\n{e['soll']}\n\nQUELLTEXTE:\n{quelltexte}\n\n"
              f"ANTWORT DES AGENTEN:\n{e['antwort'].split('### Quellen')[0]}")
    # num_ctx 6144 statt 8192: kleinerer Speicherbedarf, reicht für Frage + Soll + Quellen + Antwort
    r = ollama.chat(model=modell, format="json", options={"temperature": 0, "num_ctx": 6144},
                    messages=[{"role": "system", "content": GUTACHTER_PROMPT},
                              {"role": "user", "content": nutzer}])
    try:
        return json.loads(r.message.content)
    except json.JSONDecodeError:
        return {"korrekt": False, "vollstaendig": False, "halluzination": False, "note": 5,
                "begruendung": "Gutachter-Antwort war kein JSON"}


# --- Bericht -----------------------------------------------------------------
def bericht(ergebnisse: list[dict], modell: str) -> str:
    """Markdown-Bericht: Gesamtergebnis, Ergebnis je Kategorie, Tabelle aller Fragen und
    Details (Regeln, Gutachterurteil, Sollantwort, Antwort) zu jeder nicht bestandenen Frage.
    Setzt nebenbei e["bestanden"] für jede Frage."""
    pro_kat = defaultdict(lambda: [0, 0])
    zeilen, details = [], []
    for e in ergebnisse:
        regeln, g = e["regeln"], e["gutachten"]
        regeln_ok = all(ok for ok, _ in regeln.values())
        ki_ok = bool(g.get("korrekt")) and not g.get("halluzination")
        e["bestanden"] = regeln_ok and ki_ok
        pro_kat[e["kategorie"]][0] += e["bestanden"]
        pro_kat[e["kategorie"]][1] += 1
        regel_text = " ".join(("✅" if ok else "❌") + name for name, (ok, _) in regeln.items())
        frage = " → ".join(e.get("vorher", []) + [e["frage"]])  # Dialoge vollständig zeigen
        zeilen.append(f"| {'✅' if e['bestanden'] else '❌'} | {e['kategorie']} | {frage} | {regel_text} | "
                      f"{g.get('note', '?')} {'⚠️Halluzination' if g.get('halluzination') else ''} | {e['sekunden']} s |")
        if not e["bestanden"]:
            gruende = [f"{n}: {txt}" for n, (ok, txt) in regeln.items() if not ok]
            details.append(f"#### ❌ {e['frage']}\n- **Regeln:** {'; '.join(gruende) or 'ok'}\n"
                           f"- **Gutachter:** korrekt={g.get('korrekt')}, vollständig={g.get('vollstaendig')}, "
                           f"Halluzination={g.get('halluzination')}, Note {g.get('note')} – {g.get('begruendung')}\n"
                           f"- **Soll:** {e['soll']}\n\n<details><summary>Antwort des Agenten</summary>\n\n"
                           f"{e['antwort']}\n\n</details>\n")

    bestanden = sum(e["bestanden"] for e in ergebnisse)
    noten = [e["gutachten"].get("note", 5) for e in ergebnisse]
    halluz = sum(bool(e["gutachten"].get("halluzination")) for e in ergebnisse)
    zeit = sum(e["sekunden"] for e in ergebnisse) / len(ergebnisse)
    text = [
        "# Testlauf Informations-Agent", "",
        f"Agent: `{config.CHAT_MODEL}` · Gutachter: `{modell}` · Stichtag: {config.heute():%d.%m.%Y}", "",
        f"- **Bestanden: {bestanden}/{len(ergebnisse)} ({bestanden / len(ergebnisse):.0%})**",
        f"- Durchschnittsnote Gutachter: {sum(noten) / len(noten):.1f} (1 = sehr gut)",
        f"- Antworten mit Halluzination: {halluz}",
        f"- Durchschnittliche Antwortzeit: {zeit:.1f} s", "",
        "| Kategorie | Bestanden |", "|---|---|",
        *[f"| {k} | {b}/{n} |" for k, (b, n) in pro_kat.items()], "",
        "## Alle Fragen", "",
        "| | Kategorie | Frage | Regelprüfung | Note Gutachter | Zeit |", "|---|---|---|---|---|---|",
        *zeilen, "",
        "## Details zu nicht bestandenen Fragen", "", *(details or ["Keine – alle Fragen bestanden."]),
    ]
    return "\n".join(text)


def main() -> None:
    """Kommandozeile auswerten und Phase 1 (Antworten), Phase 2 (Prüfung) und Bericht ausführen."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--nur-gutachter", action="store_true", help="Antworten aus dem letzten Lauf neu prüfen")
    parser.add_argument("--kategorie", help="nur eine Kategorie testen")
    parser.add_argument("--gutachter", default=GUTACHTER_MODELL, help="Modell für die KI-Prüfung")
    parser.add_argument("--ohne-gutachter", action="store_true", help="nur Regelprüfung (schnell, für Zwischentests)")
    args = parser.parse_args()

    if args.nur_gutachter:
        ergebnisse = json.loads(ANTWORTEN.read_text(encoding="utf-8"))
    else:
        tests = json.loads((ORDNER / "testkatalog.json").read_text(encoding="utf-8"))
        if args.kategorie:
            tests = [t for t in tests if t["kategorie"] == args.kategorie]
        print(f"Phase 1: {len(tests)} Fragen beantworten ({config.CHAT_MODEL})")
        entlade(args.gutachter)
        ergebnisse = erzeuge_antworten(tests)
        if args.kategorie and ANTWORTEN.exists():
            # nur eine Kategorie getestet: deren Fragen im letzten Gesamtlauf ersetzen, Rest behalten
            neu = {e["frage"]: e for e in ergebnisse}
            alt = [e for e in json.loads(ANTWORTEN.read_text(encoding="utf-8")) if e["frage"] not in neu]
            ergebnisse = alt + ergebnisse
        ANTWORTEN.write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.ohne_gutachter:
        nur_neu = [e for e in ergebnisse if not args.kategorie or e["kategorie"] == args.kategorie]
        for e in nur_neu:
            fehler = [f"{n}: {t}" for n, (ok, t) in regelpruefung(e).items() if not ok]
            print(("OK  " if not fehler else "FEHL"), f"{e['sekunden']:5.1f}s", " → ".join(e.get("vorher", []) + [e["frage"]]),
                  f"| verstanden als: {e.get('verstanden_als')}" if e.get("vorher") else "", "| " + "; ".join(fehler) if fehler else "")
        print(f"Regelprüfung: {sum(all(ok for ok, _ in regelpruefung(e).values()) for e in nur_neu)}/{len(nur_neu)}")
        return

    modell = waehle_gutachter(args.gutachter)
    print(f"Phase 2: Regelprüfung + Gutachter ({modell})")
    # Version aus Modell + Prompt: Nach einer Prompt-Änderung wird neu geprüft, nach einem Abbruch fortgesetzt
    version = f"{modell}:{hashlib.sha1(GUTACHTER_PROMPT.encode()).hexdigest()[:8]}"
    for i, e in enumerate(ergebnisse, start=1):
        e["regeln"] = regelpruefung(e)
        if e.get("gutachten", {}).get("version") != version:
            e["gutachten"] = {**gutachten(e, modell), "version": version}
            # nach jeder Frage speichern -> ein Abbruch verliert nichts, --nur-gutachter setzt fort
            ANTWORTEN.write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1), encoding="utf-8")
        ok = all(o for o, _ in e["regeln"].values()) and e["gutachten"].get("korrekt") \
            and not e["gutachten"].get("halluzination")
        print(f"[{i:2}/{len(ergebnisse)}] {'OK  ' if ok else 'FEHL'} Note {e['gutachten'].get('note')}  {e['frage']}")
    entlade(modell)

    (ORDNER / "testlauf_bericht.md").write_text(bericht(ergebnisse, modell), encoding="utf-8")
    bestanden = sum(e["bestanden"] for e in ergebnisse)
    print(f"\nBestanden: {bestanden}/{len(ergebnisse)} -> evaluation/testlauf_bericht.md")


if __name__ == "__main__":
    main()
