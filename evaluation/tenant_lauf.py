"""Testlauf auf den Indizes der Testkonten im Tenant: Verwechselt der Agent Kunden, vermischt er Nutzer?

Der Testlauf mit testkatalog.json nutzt die Demo-Daten mit wenigen, gut unterscheidbaren Kunden. Eine Verwechslung
ähnlicher Verträge fällt dort nicht auf, im Tenant mit 20 Kunden schon. Geprüft wird nur mit Regeln, ohne Gutachter:
    Fremdquellen  Frage zu einem Kunden: Keine Quelle darf nur einen anderen Kunden nennen.
    Fakten        Die Pflichtangaben stehen in der Antwort (je Gruppe eine Schreibweise).
    Verbote       Die Antwort enthält keine Angabe eines anderen Kunden.
    Keine Quelle  Bei keine_quelle darf nichts gefunden werden.

Läuft auf dem Server, weil dort die Indizes liegen, und schreibt nichts (auch nicht in die Ablage):
    docker compose -f server/docker-compose.yml exec agent python evaluation/tenant_lauf.py
Konten ohne eingelesenen Index werden übersprungen. Rückgabewert 1, wenn eine Frage nicht besteht.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import config  # noqa: E402
from ingest import index_daten  # noqa: E402

KATALOG = Path(__file__).with_name("tenant_katalog.json")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def pruefe(eintrag: dict, antwort: str, treffer: list[dict], alle_kunden: set[str]) -> list[str]:
    """Liste der Verstöße; leer = bestanden."""
    if eintrag.get("keine_quelle"):
        return [f"{len(treffer)} Quellen gefunden, erwartet keine"] if treffer else []
    fehler = []
    kunde = {eintrag["kunde"].lower()} if eintrag.get("kunde") else set()
    fremd = [t["meta"]["titel"][:45] for t in treffer if kunde and agent._gehoert_anderem(t["text"], kunde, alle_kunden)]
    if fremd:
        fehler.append(f"{len(fremd)} von {len(treffer)} Quellen eines anderen Kunden: " + "; ".join(fremd[:3]))
    text = _norm(antwort.split("### Quellen")[0])
    for gruppe in eintrag["fakten"]:
        if not any(_norm(g) in text for g in gruppe):
            fehler.append("fehlt: " + " / ".join(gruppe))
    fehler += [f"enthält: {v}" for v in eintrag["darf_nicht"] if _norm(v) in text]
    return fehler


def main() -> None:
    bestanden, gelaufen, uebersprungen = 0, 0, set()
    for eintrag in json.loads(KATALOG.read_text(encoding="utf-8")):
        nutzer = eintrag["nutzer"]
        if config.index_stand(nutzer) is None:
            uebersprungen.add(nutzer)
            continue
        start = time.perf_counter()
        ergebnis = agent.antworte(eintrag["frage"], nutzer)
        alle_kunden = agent._kunden_im_index(index_daten(nutzer)["metadatas"])
        fehler = pruefe(eintrag, ergebnis["antwort"], ergebnis["treffer"], alle_kunden)
        gelaufen += 1
        bestanden += not fehler
        print(f"{'OK  ' if not fehler else 'FEHL'} {time.perf_counter() - start:5.1f}s "
              f"{nutzer.split('@')[0]}: {eintrag['frage']}" + "".join(f"\n       - {f}" for f in fehler))
    print(f"\nBestanden: {bestanden}/{gelaufen}")
    if uebersprungen:
        print("Übersprungen, kein Index:", ", ".join(sorted(uebersprungen)))
    sys.exit(0 if bestanden == gelaufen else 1)


if __name__ == "__main__":
    main()
