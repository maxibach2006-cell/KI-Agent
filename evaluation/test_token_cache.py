"""Test: Einlesen mehrerer Nutzer auf einem Rechner/Server verwechselt keine Konten (ohne Microsoft-Anmeldung).

Hintergrund: GraphClient nahm früher immer das erste Konto im Token-Cache. Las der Server erst für Nutzer A und
dann für Nutzer B ein, bekam B still die Daten von A. Geprüft werden die Regeln, die das jetzt verhindern.

Aufruf:  python evaluation/test_token_cache.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from graph_client import pruefe_anmeldung, waehle_konto  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


def wirft(funktion, *args) -> bool:
    try:
        funktion(*args)
    except RuntimeError:
        return True
    return False


anna, bert = {"username": "Anna@firma.example"}, {"username": "bert@firma.example"}

print("Kontowahl im Token-Cache")
pruefe(waehle_konto([anna, bert], "bert@firma.example") is bert, "mit Nutzer: genau dieses Konto")
pruefe(waehle_konto([anna, bert], "anna@FIRMA.example") is anna, "Groß-/Kleinschreibung egal")
pruefe(waehle_konto([anna], "bert@firma.example") is None, "anderes Konto im Cache -> neu anmelden statt fremdes Token")
pruefe(wirft(waehle_konto, [anna, bert], None), "ohne Nutzer und mehrere Konten -> Abbruch statt erstes Konto")
pruefe(waehle_konto([anna], None) is anna, "ohne Nutzer und ein Konto -> wie bisher (Einzelplatz)")
pruefe(waehle_konto([], None) is None, "leerer Cache -> neu anmelden")

print("Prüfung nach der Anmeldung")
pruefe(wirft(pruefe_anmeldung, {"id_token_claims": {"preferred_username": "anna@firma.example"}}, "bert@firma.example"),
       "falsches Konto angemeldet -> Abbruch")
pruefe(not wirft(pruefe_anmeldung, {"id_token_claims": {"preferred_username": "Bert@firma.example"}}, "bert@firma.example"),
       "richtiges Konto -> ok")
pruefe(not wirft(pruefe_anmeldung, {}, None), "ohne Nutzerangabe keine Prüfung (Einzelplatz)")

print("Cache-Dateien")
a, b = config.token_cache("anna@firma.example"), config.token_cache("bert@firma.example")
pruefe(a != b and a.parent == b.parent == config.TOKEN_CACHE.parent, "eigene Datei je Nutzer im selben Ordner")
pruefe(config.token_cache(None) == config.TOKEN_CACHE, "ohne Nutzer die bisherige Datei")
pruefe(a.name.startswith(".token_cache"), "Name passt zu .gitignore/.dockerignore (.token_cache*.json)")

print(f"\n{'Alle Prüfungen bestanden' if not FEHLER else f'{len(FEHLER)} Prüfung(en) fehlgeschlagen'}")
sys.exit(1 if FEHLER else 0)
