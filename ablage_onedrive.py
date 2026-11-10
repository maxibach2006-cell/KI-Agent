"""Persönliche Ablage im OneDrive des Nutzers: Abgleich im Hintergrund nach jeder Ablage.

Idee:
    Die Ablage (ablage.py) gehört dem Nutzer und soll in SEINEM Microsoft 365 liegen, nicht nur auf dem Server.
    ablage.py arbeitet weiter auf einer Arbeitskopie (config.ABLAGE_DIR), denn es liest das Register bei jeder Frage,
    verschiebt Dateien und schreibt Übersichten neu. Das wäre über Graph zu langsam (jede Anfrage bis zu 1 s).
    Dieses Modul spiegelt die Arbeitskopie nach OneDrive:

        Arbeitskopie (Server)                      OneDrive des Nutzers
        <ABLAGE_DIR>/<nutzer>/...      ──────►     /<ABLAGE_ONEDRIVE_ORDNER>/...   (Standard: /KAM-Ablage)

    Die Arbeitskopie ist damit nur ein Zwischenspeicher: Fehlt sie (neuer Server, Volume gelöscht), holt
    wiederherstellen() die Ablage vor der nächsten Ablage aus OneDrive zurück. OneDrive ist das Original.

Arbeitskopie nur für die Dauer der Sitzung (config.ABLAGE_KOPIE_LOESCHEN, im Serverbetrieb an):
    Streamlit meldet nicht, wenn ein Browser-Tab geschlossen wird. Die App sendet deshalb jede Minute ein
    lebenszeichen(). Kommt ABLAGE_SITZUNG_ENDE_MINUTEN lang keines, gilt die Sitzung als beendet. aufraeumen()
    gleicht dann ein letztes Mal ab und löscht die Arbeitskopie, aber nur, wenn danach jede Datei mit derselben
    Prüfsumme in OneDrive liegt. Schlägt der Abgleich fehl (Netz, Token), bleibt die Kopie und es wird später erneut
    versucht: Daten gehen so nie verloren. Die nächste Ablage holt die Kopie wieder aus OneDrive.

Ablauf von anstossen() (nach jeder Ablage, blockiert die Antwort nicht):
    1. Unter ablage._SPERRE alle Dateien der Arbeitskopie lesen (Momentaufnahme, nie halb geschriebene Dateien).
    2. Mit dem Stand des letzten Abgleichs vergleichen (_onedrive.json: Pfad -> Prüfsumme).
    3. Neue und geänderte Dateien hochladen, lokal entfernte Dateien in OneDrive löschen (z. B. nach dem Umzug aus
       _Allgemein in einen Themenordner). Gelöscht wird nur, was dieses Modul selbst hochgeladen hat.
    4. Kommt während des Abgleichs eine neue Ablage, läuft danach genau ein weiterer Abgleich.

Berechtigung: delegiert "Files.ReadWrite" (nur das eigene OneDrive). Sie wird beim Einlesen mit angefragt
(einlesen.py), der Abgleich selbst meldet sich nie interaktiv an.

Nutzung:
    import ablage_onedrive
    ablage_onedrive.wiederherstellen_falls_noetig("anna@firma.de")   # vor ablage.ablegen()
    ablage_onedrive.anstossen("anna@firma.de")                       # nach ablage.ablegen()
    ablage_onedrive.status("anna@firma.de")   # {"zustand", "zeit", "meldung", "link"} für die Anzeige
    ablage_onedrive.lebenszeichen("anna@firma.de")                   # jede Minute, solange die Sitzung offen ist
    ablage_onedrive.starte_aufraeumen()        # einmal je Serverprozess: löscht Arbeitskopien beendeter Sitzungen

Test ohne Microsoft 365: python evaluation/test_ablage_onedrive.py
"""
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests

import ablage
import config

STAND_DATEI = "_onedrive.json"   # Stand des letzten Abgleichs in der Arbeitskopie (wird nicht hochgeladen):
                                 # {"nutzer": Konto, "dateien": {Pfad: Prüfsumme}}
NICHT_HOCHLADEN = {STAND_DATEI, ablage.REGISTER + ".tmp"}
EINFACH_BIS = 4 * 1024 * 1024    # bis 4 MB reicht ein PUT, größere Dateien brauchen eine Upload-Sitzung
TEIL = 320 * 1024 * 16           # 5 MB je Teil; Graph verlangt ein Vielfaches von 320 KiB

_sperre = threading.Lock()       # schützt _zustaende
_zustaende: dict[str, dict] = {}  # Schlüssel: Nutzer in Kleinschreibung
_lebenszeichen: dict[str, float] = {}  # Nutzer in Kleinschreibung -> Zeit des letzten Lebenszeichens
_START = time.time()             # nach einem Neustart zählt die Sitzung ab hier (es gibt noch kein Lebenszeichen)
_aufraeumen_gestartet = False


def aktiv(nutzer: str) -> bool:
    """Abgleich nur für echte Microsoft-365-Konten, nie für die Demo-Daten."""
    return config.ABLAGE_ONEDRIVE and bool(nutzer) and nutzer != "demo" and "@" in nutzer


def _graph(nutzer: str):
    from graph_client import GraphClient  # erst hier: Demo-Betrieb und Tests brauchen kein msal
    return GraphClient(config.ABLAGE_SCOPES, nutzer, interaktiv=False)


def _pfad(rel: str = "") -> str:
    """Graph-Pfad eines Elements im Ablageordner, z. B. /me/drive/root:/KAM-Ablage/Firma%20X/a.md:"""
    voll = config.ABLAGE_ONEDRIVE_ORDNER.strip("/") + (f"/{rel}" if rel else "")
    return f"/me/drive/root:/{quote(voll, safe='/')}:"


def _pruefsumme(daten: bytes) -> str:
    return hashlib.sha1(daten).hexdigest()


def _lade_stand(wurzel: Path) -> dict:
    datei = wurzel / STAND_DATEI
    stand = json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {}
    return {"nutzer": stand.get("nutzer"), "dateien": stand.get("dateien", {})}


def _speichere_stand(wurzel: Path, stand: dict) -> None:
    wurzel.mkdir(parents=True, exist_ok=True)
    tmp = wurzel / (STAND_DATEI + ".tmp")
    tmp.write_text(json.dumps(stand, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(wurzel / STAND_DATEI)


def _dateien(wurzel: Path) -> dict[str, bytes]:
    """Alle Dateien der Arbeitskopie (relativer Pfad mit "/" -> Inhalt). Aufrufer hält ablage._SPERRE."""
    if not wurzel.exists():
        return {}
    return {p.relative_to(wurzel).as_posix(): p.read_bytes() for p in sorted(wurzel.rglob("*"))
            if p.is_file() and p.name not in NICHT_HOCHLADEN}


def momentaufnahme(wurzel: Path) -> dict[str, bytes]:
    """Wie _dateien(), aber unter ablage._SPERRE gelesen, damit keine Datei mitten im Schreiben erwischt wird."""
    with ablage._SPERRE:
        return _dateien(wurzel)


# =============================================================================
# A. Hochladen und Löschen
# =============================================================================

def _hochladen(graph, rel: str, daten: bytes) -> None:
    """Eine Datei nach OneDrive (vorhandene wird ersetzt). Fehlende Ordner legt Graph selbst an."""
    if len(daten) <= EINFACH_BIS:
        graph.request("PUT", _pfad(rel) + "/content?@microsoft.graph.conflictBehavior=replace", data=daten,
                      headers={"Content-Type": "application/octet-stream"})
        return
    sitzung = graph.post(_pfad(rel) + "/createUploadSession",
                         json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
    for start in range(0, len(daten), TEIL):
        teil = daten[start:start + TEIL]
        # Die Upload-Adresse ist bereits berechtigt: kein Token mitschicken (Graph lehnt es dort sonst ab)
        r = requests.put(sitzung["uploadUrl"], data=teil, timeout=120, headers={
            "Content-Length": str(len(teil)),
            "Content-Range": f"bytes {start}-{start + len(teil) - 1}/{len(daten)}"})
        r.raise_for_status()


def _loeschen(graph, rel: str) -> None:
    """Datei in OneDrive löschen. Schon weg (404, z. B. vom Nutzer gelöscht) ist kein Fehler."""
    try:
        graph.request("DELETE", _pfad(rel))
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise


def abgleichen(wurzel: Path, graph, nutzer: str | None = None) -> dict:
    """Schritte 1-3: Arbeitskopie nach OneDrive spiegeln. Rückgabe: {"hochgeladen", "geloescht", "link"}.

    Der Stand wird nach jeder Datei gespeichert: Bricht der Abgleich ab (Netz, Token), lädt der nächste nur den Rest.
    nutzer wird im Stand vermerkt, damit aufraeumen() auch nach einem Neustart weiß, wem die Kopie gehört.
    """
    dateien = momentaufnahme(wurzel)
    stand = _lade_stand(wurzel)
    stand["nutzer"] = nutzer or stand["nutzer"]
    bekannt = stand["dateien"]
    hochgeladen, geloescht = 0, 0
    for rel, daten in dateien.items():
        summe = _pruefsumme(daten)
        if bekannt.get(rel) != summe:
            _hochladen(graph, rel, daten)
            bekannt[rel] = summe
            _speichere_stand(wurzel, stand)
            hochgeladen += 1
    for rel in [r for r in bekannt if r not in dateien]:
        _loeschen(graph, rel)
        del bekannt[rel]
        _speichere_stand(wurzel, stand)
        geloescht += 1
    link = None
    if dateien:
        link = graph.get(_pfad()).get("webUrl")  # Ordner im Browser öffnen (Anzeige in der App)
    return {"hochgeladen": hochgeladen, "geloescht": geloescht, "link": link}


# =============================================================================
# B. Wiederherstellen aus OneDrive
# =============================================================================

def _alle_dateien(graph, pfad: str, rel: str = "") -> list[tuple[str, dict]]:
    """Alle Dateien unterhalb eines Ordners in OneDrive (relativer Pfad, Element), Unterordner rekursiv."""
    ergebnis = []
    for elem in graph.get_all(pfad + "/children"):
        name = f"{rel}/{elem['name']}" if rel else elem["name"]
        if "folder" in elem:
            ergebnis += _alle_dateien(graph, f"/me/drive/items/{elem['id']}", name)
        elif "file" in elem:
            ergebnis.append((name, elem))
    return ergebnis


def wiederherstellen(wurzel: Path, graph, nutzer: str | None = None) -> int:
    """Holt die Ablage aus OneDrive in eine leere Arbeitskopie. Rückgabe: Anzahl Dateien (0 = nichts in OneDrive).
    Danach gilt alles als abgeglichen, der nächste Abgleich lädt also nichts doppelt hoch."""
    try:
        dateien = _alle_dateien(graph, _pfad())
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return 0  # Ordner gibt es (noch) nicht: erste Ablage dieses Nutzers
        raise
    stand = {}
    with ablage._SPERRE:
        for rel, elem in dateien:
            if Path(rel).name in NICHT_HOCHLADEN or ".." in Path(rel).parts:
                continue
            daten = graph.get_bytes(f"/me/drive/items/{elem['id']}/content")
            ziel = wurzel / rel
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_bytes(daten)
            stand[rel] = _pruefsumme(daten)
        if stand:
            _speichere_stand(wurzel, {"nutzer": nutzer, "dateien": stand})
    return len(stand)


def wiederherstellen_falls_noetig(nutzer: str) -> str | None:
    """Vor jeder Ablage aufrufen. Fehlt das Register in der Arbeitskopie, wird die Ablage aus OneDrive geholt, damit
    eine neue, leere Ablage die alte in OneDrive nie überschreibt. Billig, wenn das Register da ist (nur eine Prüfung).
    Rückgabe: Meldung für die Anzeige oder None. Fehler werfen eine Ausnahme: dann bitte NICHT ablegen."""
    if not aktiv(nutzer):
        return None
    wurzel = ablage.ablage_pfad(nutzer)
    if (wurzel / ablage.REGISTER).exists():
        return None
    anzahl = wiederherstellen(wurzel, _graph(nutzer), nutzer)
    return f"Ablage aus OneDrive wiederhergestellt ({anzahl} Dateien)." if anzahl else None


# =============================================================================
# C. Abgleich im Hintergrund
# =============================================================================

def status(nutzer: str) -> dict | None:
    """Stand des letzten Abgleichs (Kopie) oder None, wenn in diesem Serverprozess noch keiner lief."""
    with _sperre:
        z = _zustaende.get(nutzer.lower())
        return dict(z) if z else None


def anstossen(nutzer: str) -> bool:
    """Startet den Abgleich im Hintergrund. Läuft schon einer, wird danach genau ein weiterer ausgeführt (Schritt 4).
    Rückgabe: False, wenn für diesen Nutzer kein Abgleich vorgesehen ist."""
    if not aktiv(nutzer):
        return False
    schluessel = nutzer.lower()
    with _sperre:
        z = _zustaende.setdefault(schluessel, {"zustand": "neu", "zeit": None, "meldung": "", "link": None,
                                               "nochmal": False})
        if z["zustand"] == "laeuft":
            z["nochmal"] = True
            return True
        z["zustand"], z["nochmal"] = "laeuft", False
    threading.Thread(target=_arbeite, args=(nutzer,), daemon=True, name=f"onedrive-{schluessel}").start()
    return True


def _arbeite(nutzer: str) -> None:
    schluessel = nutzer.lower()
    while True:
        try:
            ergebnis = abgleichen(ablage.ablage_pfad(nutzer), _graph(nutzer), nutzer)
            werte = {"zustand": "fertig", "meldung": f"{ergebnis['hochgeladen']} hochgeladen, "
                                                     f"{ergebnis['geloescht']} entfernt"}
            if ergebnis["link"]:
                werte["link"] = ergebnis["link"]
        except Exception as e:  # nie die App stören; die Arbeitskopie bleibt, der nächste Abgleich holt nach
            print(f"OneDrive-Abgleich für {nutzer} fehlgeschlagen: {e}")
            werte = {"zustand": "fehler", "meldung": str(e)}
        with _sperre:
            z = _zustaende[schluessel]
            z.update(werte, zeit=time.time())
            if not z["nochmal"]:
                return
            z["zustand"], z["nochmal"] = "laeuft", False


# =============================================================================
# D. Arbeitskopie nur für die Dauer der Sitzung
# =============================================================================

def lebenszeichen(nutzer: str) -> None:
    """Die Sitzung dieses Nutzers ist noch offen. app.py ruft das jede Minute auf, solange der Tab offen ist."""
    if aktiv(nutzer):
        with _sperre:
            _lebenszeichen[nutzer.lower()] = time.time()


def _sitzung_offen(nutzer: str, jetzt: float) -> bool:
    with _sperre:
        letztes = max(_lebenszeichen.get(nutzer.lower(), 0.0), _START)
        laeuft = (_zustaende.get(nutzer.lower()) or {}).get("zustand") == "laeuft"
    return laeuft or jetzt - letztes < config.ABLAGE_SITZUNG_ENDE_MINUTEN * 60


def _loeschen_wenn_abgeglichen(wurzel: Path, nutzer: str, jetzt: float) -> bool:
    """Löscht die Arbeitskopie, wenn jede Datei mit derselben Prüfsumme in OneDrive liegt und die Sitzung noch immer
    beendet ist. Unter ablage._SPERRE: Eine gleichzeitige Ablage kann nichts dazwischenschreiben."""
    with ablage._SPERRE:
        if _sitzung_offen(nutzer, jetzt):
            return False  # der Nutzer ist während des letzten Abgleichs zurückgekommen (neues Lebenszeichen)
        bekannt = _lade_stand(wurzel)["dateien"]
        dateien = _dateien(wurzel)
        if set(dateien) != set(bekannt) or any(_pruefsumme(d) != bekannt[r] for r, d in dateien.items()):
            return False
        shutil.rmtree(wurzel)
    return True


def aufraeumen(jetzt: float | None = None) -> list[str]:
    """Ein Durchgang: Arbeitskopien beendeter Sitzungen abgleichen und löschen. Rückgabe: Nutzer, deren Kopie
    gelöscht wurde. Kopien ohne vermerkten Nutzer (Demo, nie abgeglichen) bleiben unangetastet."""
    if not (config.ABLAGE_ONEDRIVE and config.ABLAGE_KOPIE_LOESCHEN) or not config.ABLAGE_DIR.exists():
        return []
    jetzt = jetzt or time.time()
    geloescht = []
    for wurzel in sorted(p for p in config.ABLAGE_DIR.iterdir() if p.is_dir()):
        nutzer = _lade_stand(wurzel)["nutzer"]
        if not nutzer or not aktiv(nutzer) or wurzel != ablage.ablage_pfad(nutzer) or _sitzung_offen(nutzer, jetzt):
            continue
        try:
            abgleichen(wurzel, _graph(nutzer), nutzer)  # letzte Änderungen sicher in OneDrive
        except Exception as e:
            print(f"Arbeitskopie von {nutzer} bleibt, Abgleich fehlgeschlagen: {e}")
            continue
        if _loeschen_wenn_abgeglichen(wurzel, nutzer, jetzt):
            print(f"Sitzung von {nutzer} beendet: Arbeitskopie der Ablage gelöscht (liegt in OneDrive).")
            geloescht.append(nutzer)
    return geloescht


def starte_aufraeumen() -> None:
    """Startet aufraeumen() einmal je Minute im Hintergrund, höchstens einmal je Serverprozess."""
    global _aufraeumen_gestartet
    with _sperre:
        if _aufraeumen_gestartet or not (config.ABLAGE_ONEDRIVE and config.ABLAGE_KOPIE_LOESCHEN):
            return
        _aufraeumen_gestartet = True

    def schleife() -> None:
        while True:
            time.sleep(60)
            try:
                aufraeumen()
            except Exception as e:  # der Aufräumer darf nie sterben
                print(f"Aufräumen der Ablage fehlgeschlagen: {e}")

    threading.Thread(target=schleife, daemon=True, name="ablage-aufraeumen").start()
