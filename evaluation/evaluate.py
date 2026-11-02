"""Misst, wie gut der Agent die richtigen Quellen findet und wie schnell er antwortet.

Aufruf (aus dem Projektordner):
    python evaluation/evaluate.py              # nur Suche (schnell)
    python evaluation/evaluate.py --antwort    # zusätzlich komplette Antworten erzeugen und Zeit messen

Kennzahlen:
  - Quellen-Trefferquote: Anteil der Fragen, bei denen eine erwartete Quelle unter den Top-k ist
    (bei Fragen ohne erwartete Quelle: richtig, wenn der Agent "keine Quelle" meldet)
  - Antwortzeit des Agenten im Vergleich zur manuellen Suche ("manuell_sek" in testfragen.json
    selbst mit der Stoppuhr messen und eintragen)
Das Ergebnis wird als Markdown-Tabelle in evaluation/ergebnisse.md gespeichert.

Abgrenzung zu testlauf.py: Dieses Skript ist die schnelle Messung für Suche und Zeitersparnis
(wenige Fragen, testfragen.json). testlauf.py prüft die Antwortqualität ausführlich (testkatalog.json).
"""
import argparse
import json
import sys
import time
from pathlib import Path

# Projektordner in den Suchpfad aufnehmen, damit "import agent" aus dem Unterordner evaluation/ funktioniert
sys.path.insert(0, str(Path(__file__).parent.parent))
import agent  # noqa: E402

ORDNER = Path(__file__).parent


def bewerte(test: dict, treffer: list[dict]) -> bool:
    """Richtig, wenn mindestens eine erwartete Quelle (Teil von Titel oder Link) gefunden wurde.
    Ist keine Quelle erwartet (unbeantwortbare Frage), ist "nichts gefunden" richtig."""
    if not test["erwartet"]:
        return len(treffer) == 0
    gefunden = " ".join(t["meta"]["titel"] + " " + t["meta"]["link"] for t in treffer)
    return any(e in gefunden for e in test["erwartet"])


def main(mit_antwort: bool, user: str) -> None:
    """Alle Testfragen durchlaufen, bewerten, Zeit messen und den Bericht schreiben."""
    tests = json.loads((ORDNER / "testfragen.json").read_text(encoding="utf-8"))
    zeilen, richtig, zeiten, manuell = [], 0, [], []

    for test in tests:
        start = time.perf_counter()
        if mit_antwort:
            ergebnis = agent.antworte(test["frage"], user)
            treffer = ergebnis["treffer"]
        else:
            treffer = agent.suche(test["frage"], user)
        sek = time.perf_counter() - start
        ok = bewerte(test, treffer)
        richtig += ok  # True zählt als 1
        zeiten.append(sek)
        if test.get("manuell_sek"):
            manuell.append(test["manuell_sek"])
        beste = treffer[0]["meta"]["titel"] if treffer else "– keine Quelle –"
        m = f"{test['manuell_sek']} s" if test.get("manuell_sek") else "–"
        zeilen.append(f"| {test['frage']} | {'✅' if ok else '❌'} | {beste} | {sek:.1f} s | {m} |")
        print(("OK  " if ok else "FEHL"), f"{sek:5.1f}s", test["frage"])

    # --- Kennzahlen und Bericht ---
    quote = richtig / len(tests)
    avg = sum(zeiten) / len(zeiten)
    bericht = [
        f"# Evaluation ({'Suche + Antwort' if mit_antwort else 'nur Suche'})",
        "",
        f"- Quellen-Trefferquote: **{richtig}/{len(tests)} = {quote:.0%}**",
        f"- Durchschnittliche Zeit Agent: **{avg:.1f} s**",
    ]
    if manuell:
        avg_m = sum(manuell) / len(manuell)
        bericht.append(f"- Durchschnittliche Zeit manuelle Suche: **{avg_m:.0f} s** "
                       f"(Zeitersparnis ca. {1 - avg / avg_m:.0%})")
    bericht += ["", "| Frage | Quelle gefunden | Beste Quelle | Zeit Agent | Zeit manuell |",
                "|---|---|---|---|---|", *zeilen]
    (ORDNER / "ergebnisse.md").write_text("\n".join(bericht), encoding="utf-8")
    print(f"\nTrefferquote {quote:.0%}, Ø {avg:.1f} s -> evaluation/ergebnisse.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--antwort", action="store_true", help="komplette Antworten erzeugen")
    parser.add_argument("--user", default="demo")
    args = parser.parse_args()
    main(args.antwort, args.user)
