"""Stromverbrauch und Kosten: wie viel kosten eine Anfrage und der laufende Betrieb des Modells?

Was gemessen und was geschätzt wird:
    gemessen:  Leistung der Grafikkarte (nvidia-smi, einmal pro Sekunde). Dort läuft das Sprachmodell.
    geschätzt: der übrige PC (CPU, RAM, Netzteil) als fester Wert config.STROM_REST_WATT. Ohne Messgerät an der
               Steckdose lässt er sich hier nicht messen. Die Summe ist deshalb eine Größenordnung, kein Zählerstand.

Eine Anfrage zählt, was der PC während ihrer Laufzeit verbraucht, einschließlich des Grundverbrauchs. Laufen zwei
Anfragen gleichzeitig, zählt die gemeinsame Zeit bei beiden. Gemessen wird nur, solange die App läuft und seit sie
zum ersten Mal geöffnet wurde. Der Stand liegt in data/strom.json und übersteht einen Neustart.

Nutzung:
    strom.starte()                          # einmal beim Start der App
    marke = strom.marke()                   # vor der Anfrage
    messung = strom.anfrage_beenden(marke)  # danach; None, wenn keine Messung möglich ist
"""
import json
import subprocess
import threading
import time

import config

INTERVALL = 1.0        # Sekunden zwischen zwei Messungen
SPEICHERN_ALLE = 60    # Sekunden zwischen zwei Sicherungen des Stands
TAGE_JE_MONAT = 30
MINDESTZEIT_BEREITSCHAFT = 60  # Sekunden ohne Anfrage, ab denen die Hochrechnung auf den Monat aussagekräftig ist

_sperre = threading.Lock()
_stand = {"sekunden": 0.0, "gpu_wh": 0.0, "rest_wh": 0.0, "anfragen": 0, "anfragen_wh": 0.0, "anfragen_sekunden": 0.0}
_letzte_zeit = None    # Zeitpunkt der letzten Messung
_letzte_watt = None    # letzter Messwert; None = keine Messung möglich
_gestartet = False


def gpu_watt() -> float | None:
    """Aktuelle Leistung der Grafikkarte in Watt, None ohne NVIDIA-Karte oder ohne Messwert."""
    try:
        ausgabe = subprocess.run(["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, check=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return float(ausgabe.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _zaehle_bis(jetzt: float) -> None:
    """Energie seit der letzten Messung aufaddieren. Lange Lücken (z. B. Standby) zählen nicht."""
    global _letzte_zeit
    if _letzte_zeit is not None and _letzte_watt is not None:
        dauer = jetzt - _letzte_zeit
        if 0 < dauer <= 10 * INTERVALL:
            _stand["sekunden"] += dauer
            _stand["gpu_wh"] += _letzte_watt * dauer / 3600
            _stand["rest_wh"] += config.STROM_REST_WATT * dauer / 3600
    _letzte_zeit = jetzt


def _messe_einmal() -> None:
    global _letzte_watt
    watt = gpu_watt()  # außerhalb der Sperre: Der Aufruf dauert rund 0,1 s
    with _sperre:
        _zaehle_bis(time.monotonic())
        _letzte_watt = watt


def _datei():
    return config.DATA_DIR / "strom.json"


def _speichere() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _sperre:
        inhalt = json.dumps(_stand)
    tmp = _datei().with_suffix(".tmp")
    tmp.write_text(inhalt, encoding="utf-8")
    tmp.replace(_datei())


def _lade() -> None:
    try:
        _stand.update(json.loads(_datei().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass  # noch kein Stand oder beschädigte Datei: bei null beginnen


def _messschleife() -> None:
    letzte_sicherung = time.monotonic()
    while True:
        _messe_einmal()
        if time.monotonic() - letzte_sicherung >= SPEICHERN_ALLE:
            _speichere()
            letzte_sicherung = time.monotonic()
        time.sleep(INTERVALL)


def starte() -> None:
    """Messung im Hintergrund starten; weitere Aufrufe ändern nichts."""
    global _gestartet
    with _sperre:
        if _gestartet:
            return
        _gestartet = True
        _lade()
    threading.Thread(target=_messschleife, daemon=True, name="strom").start()


def _zaehler() -> dict:
    """Aktueller Stand, bis zu diesem Moment gerechnet."""
    with _sperre:
        _zaehle_bis(time.monotonic())
        return dict(_stand)


def marke() -> dict:
    """Stand vor einer Anfrage, für anfrage_beenden()."""
    return _zaehler()


def anfrage_beenden(start: dict) -> dict | None:
    """Verbrauch seit `start` als {"sekunden", "gpu_wh", "gesamt_wh", "euro"}; None ohne Messwerte."""
    if _letzte_watt is None:
        return None
    jetzt = _zaehler()
    gpu = jetzt["gpu_wh"] - start["gpu_wh"]
    gesamt = gpu + jetzt["rest_wh"] - start["rest_wh"]
    sekunden = jetzt["sekunden"] - start["sekunden"]
    with _sperre:
        _stand["anfragen"] += 1
        _stand["anfragen_wh"] += gesamt
        _stand["anfragen_sekunden"] += sekunden
    _speichere()
    return {"sekunden": sekunden, "gpu_wh": gpu, "gesamt_wh": gesamt, "euro": euro(gesamt)}


def euro(wh: float) -> float:
    return wh / 1000 * config.STROM_PREIS_EURO_KWH


def _zahl(wert: float, stellen: int) -> str:
    """Deutsche Schreibweise: 1234.5 -> "1.234,5"."""
    return f"{wert:,.{stellen}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def text_anfrage(messung: dict) -> str:
    """Zeile unter einer Antwort."""
    return (f"⚡ Diese Anfrage: ca. {_zahl(messung['gesamt_wh'], 2)} Wh ≈ {_zahl(messung['euro'] * 100, 3)} Cent "
            f"(Grafikkarte gemessen: {_zahl(messung['gpu_wh'], 2)} Wh, übriger PC geschätzt)")


def text_uebersicht() -> str:
    """Block für die Seitenleiste. Leer, solange es keine Messwerte gibt."""
    s = _zaehler()
    if _letzte_watt is None or s["sekunden"] <= 0:
        return ""
    gesamt = s["gpu_wh"] + s["rest_wh"]
    zeilen = [f"**⚡ Stromkosten** (bei {_zahl(config.STROM_PREIS_EURO_KWH * 100, 0)} Cent/kWh)",
              f"- Betrieb bisher: {_zahl(gesamt / 1000, 3)} kWh ≈ {_zahl(euro(gesamt) * 100, 2)} Cent "
              f"in {_zahl(s['sekunden'] / 3600, 1)} h"]
    # Hochrechnung nur aus der Zeit ohne Anfragen, sonst bestimmen kurz nach dem Start wenige Anfragen das Ergebnis
    bereit_sekunden = s["sekunden"] - s["anfragen_sekunden"]
    if bereit_sekunden >= MINDESTZEIT_BEREITSCHAFT:
        watt = (gesamt - s["anfragen_wh"]) / (bereit_sekunden / 3600)
        zeilen.append(f"- Bereitschaft ohne Anfragen: ca. {_zahl(watt, 0)} W ≈ "
                      f"{_zahl(euro(watt * 24 * TAGE_JE_MONAT), 0)} € im Monat")
    if s["anfragen"]:
        schnitt = s["anfragen_wh"] / s["anfragen"]
        name = "Anfrage" if s["anfragen"] == 1 else "Anfragen"
        zeilen.append(f"- {s['anfragen']} {name}: im Schnitt {_zahl(schnitt, 2)} Wh ≈ "
                      f"{_zahl(euro(schnitt) * 100, 3)} Cent")
        if schnitt > 0:
            zeilen.append(f"- 1 € reicht für ca. {_zahl(1 / euro(schnitt), 0)} Anfragen")
    zeilen.append("\nGrafikkarte gemessen, übriger PC geschätzt.")
    return "\n".join(zeilen)
