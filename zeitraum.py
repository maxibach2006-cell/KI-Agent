"""Zeitangaben verstehen: "nächste Woche", "morgen", "im November", "KW 47", "am 20.11." ...

Problem:
    Die Vektorsuche findet Texte nach Bedeutung, kann aber nicht rechnen: "nächste Woche" ähnelt keinem
    Text, in dem "20.11.2026" steht.
Lösung:
    Ein Zeitraum in der Frage wird hier mit festen Regeln (reguläre Ausdrücke) erkannt und in ein
    konkretes Von-Bis-Datum umgerechnet. agent.py sucht dann gezielt nach Quellen mit Datum in diesem
    Zeitraum. Regeln statt Sprachmodell, weil Datumsrechnung exakt sein muss und ein kleines Modell
    sich dabei leicht verrechnet.

Funktionen:
    erkenne_zeitraum()  Frage -> (von, bis, Beschreibung) oder None
    daten_im_text()     alle Datumsangaben in einem Text (wird beim Einlesen jedes Abschnitts genutzt)
    beschreibe_heute()  "Montag, 02.11.2026 (KW 45)" für den System-Prompt
"""
import re
from datetime import date, timedelta

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
          "september", "oktober", "november", "dezember"]


def _monat(jahr: int, monat: int) -> tuple[date, date]:
    """Erster und letzter Tag eines Monats (letzter Tag = Erster des Folgemonats minus einen Tag)."""
    start = date(jahr, monat, 1)
    ende = date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1)
    return start, ende


def erkenne_zeitraum(frage: str, heute: date) -> tuple[date, date, str] | None:
    """Erkennt eine Zeitangabe in der Frage und rechnet sie in einen konkreten Zeitraum um.

    Parameter:
        frage:  Frage des Nutzers, z. B. "Welche Termine habe ich nächste Woche?"
        heute:  Bezugsdatum (config.heute())
    Rückgabe:
        (von, bis, Beschreibung), z. B. (09.11.2026, 15.11.2026, "nächste Woche"),
        oder None, wenn die Frage keinen Zeitraum enthält.

    Die Regeln werden von speziell nach allgemein geprüft (die erste passende gewinnt), damit z. B.
    "übernächste Woche" nicht schon von der Regel für "nächste Woche" erfasst wird.
    """
    f = frage.lower()
    montag = heute - timedelta(days=heute.weekday())  # Montag der laufenden Woche (Wochenbeginn)

    # "heute" heißt oft nur "aktuell" ("Wer ist heute unser Ansprechpartner?") -> nur bei Terminbezug als Tag werten
    terminbezug = re.search(r"termin|anstehen|steht .*an|habe ich|geplant|meeting|besprechung|"
                            r"kalender|frist|fällig|treffen|call|zu tun", f)
    if not terminbezug:
        f = re.sub(r"\b(heute|morgen|übermorgen|gestern)\b", "", f)

    # --- einzelne Tage ---
    if "übermorgen" in f:
        d = heute + timedelta(days=2)
        return d, d, "übermorgen"
    if "morgen" in f and "morgens" not in f:  # "morgens" ist eine Tageszeit, kein Datum
        d = heute + timedelta(days=1)
        return d, d, "morgen"
    if "heute" in f:
        return heute, heute, "heute"
    if "gestern" in f:
        d = heute - timedelta(days=1)
        return d, d, "gestern"

    # --- Wochen und Tageszeiträume ---
    if m := re.search(r"(?:in den )?(?:nächsten|kommenden) (\d+) tage", f):
        return heute, heute + timedelta(days=int(m[1])), f"die nächsten {m[1]} Tage"
    if re.search(r"übernächste[nr]? woche", f):
        s = montag + timedelta(weeks=2)
        return s, s + timedelta(days=6), "übernächste Woche"
    if re.search(r"(nächste[nr]?|kommende[nr]?) woche", f):
        s = montag + timedelta(weeks=1)
        return s, s + timedelta(days=6), "nächste Woche"
    if re.search(r"(letzte[nr]?|vergangene[nr]?|vorige[nr]?) woche", f):
        s = montag - timedelta(weeks=1)
        return s, s + timedelta(days=6), "letzte Woche"
    if re.search(r"(diese[nr]?|aktuelle[nr]?) woche", f):
        return montag, montag + timedelta(days=6), "diese Woche"

    # --- Kalenderwoche: "KW 47" ---
    if m := re.search(r"\bkw ?(\d{1,2})\b", f):
        kw = int(m[1])
        # Liegt die KW mehr als ein halbes Jahr zurück, ist vermutlich die KW im nächsten Jahr gemeint
        jahr = heute.year if kw >= heute.isocalendar().week - 26 else heute.year + 1
        s = date.fromisocalendar(jahr, kw, 1)  # Montag dieser KW nach ISO 8601
        return s, s + timedelta(days=6), f"KW {kw}/{jahr}"

    # --- Monate relativ zu heute ---
    if re.search(r"(nächste[nr]?|kommende[nr]?) monat", f):
        j, mo = (heute.year + 1, 1) if heute.month == 12 else (heute.year, heute.month + 1)
        return *_monat(j, mo), "nächsten Monat"
    if re.search(r"(diese[nr]?|aktuelle[nr]?) monat", f):
        return *_monat(heute.year, heute.month), "diesen Monat"

    # --- konkretes Datum: "am 20.11.2026" oder "am 20.11." ---
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", f):
        jahr = int(m[3]) if m[3] else heute.year
        try:
            d = date(jahr, int(m[2]), int(m[1]))
            return d, d, d.strftime("%d.%m.%Y")
        except ValueError:
            pass  # kein gültiges Datum (z. B. "31.02."), dann weiter mit den übrigen Regeln

    # --- Monatsname: "im November", "im März 2027" ---
    for i, name in enumerate(MONATE, start=1):
        if m := re.search(rf"\b{name}\b(?: (\d{{4}}))?", f):
            # ohne Jahr: der nächste November (oder der laufende)
            jahr = int(m[1]) if m[1] else (heute.year if i >= heute.month else heute.year + 1)
            return *_monat(jahr, i), f"{name.capitalize()} {jahr}"
    return None


def daten_im_text(text: str) -> list[date]:
    """Alle vollständigen Datumsangaben im Text, sortiert und ohne Duplikate.

    Erkannt werden deutsches Format (20.11.2026) und ISO-Format (2026-11-20).
    Unvollständige Angaben ohne Jahr ("20.11.") werden bewusst ignoriert, weil das Jahr unklar ist.
    """
    gefunden = []
    for t, mo, j in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        gefunden.append((int(j), int(mo), int(t)))
    for j, mo, t in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        gefunden.append((int(j), int(mo), int(t)))
    daten = []
    for j, mo, t in gefunden:
        try:
            daten.append(date(j, mo, t))
        except ValueError:
            pass  # Zahlenfolge sieht aus wie ein Datum, ist aber keines (z. B. Versionsnummer "12.34.5678")
    return sorted(set(daten))


def beschreibe_heute(heute: date) -> str:
    """Lesbares heutiges Datum mit Wochentag und KW, z. B. "Montag, 02.11.2026 (KW 45)"."""
    return f"{WOCHENTAGE[heute.weekday()]}, {heute.strftime('%d.%m.%Y')} (KW {heute.isocalendar().week})"
