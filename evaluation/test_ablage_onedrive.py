"""Test des OneDrive-Abgleichs der Ablage (ablage_onedrive.py) OHNE Microsoft 365 und ohne Ollama.

Ein nachgebautes OneDrive im Speicher (FalschesOneDrive) beantwortet die Graph-Anfragen. Geprüft wird:
    - Erster Abgleich lädt alle Dateien hoch, der Stand (_onedrive.json) selbst bleibt auf dem Server.
    - Zweiter Abgleich ohne Änderung lädt nichts hoch (Prüfsummen).
    - Geänderte Dateien werden ersetzt, verschobene Dateien am alten Ort gelöscht.
    - Gelöscht wird nur, was der Abgleich selbst hochgeladen hat (eigene Dateien des Nutzers bleiben).
    - Große Dateien gehen über eine Upload-Sitzung in Teilen.
    - Wiederherstellen in eine leere Arbeitskopie, danach kein doppeltes Hochladen.
    - wiederherstellen_falls_noetig() lässt eine vorhandene Arbeitskopie in Ruhe, Demo-Nutzer werden nie abgeglichen.
    - Hintergrund-Abgleich: Anstoßen während eines laufenden Abgleichs führt genau einen weiteren aus.

Aufruf:  python evaluation/test_ablage_onedrive.py
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import ablage  # noqa: E402
import ablage_onedrive as od  # noqa: E402
import config  # noqa: E402

FEHLER = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  ok   " if bedingung else "  FEHLER ") + text)
    if not bedingung:
        FEHLER.append(text)


class Antwort:
    def __init__(self, status=200, inhalt=b""):
        self.status_code, self.content = status, inhalt


def http_fehler(status: int) -> requests.HTTPError:
    return requests.HTTPError(f"{status}", response=Antwort(status))


class FalschesOneDrive:
    """Versteht genau die Pfade, die ablage_onedrive.py benutzt. Dateien: Pfad im Drive -> Inhalt.
    Element-IDs sind der Pfad selbst, so bleibt die Nachbildung klein."""

    def __init__(self):
        self.dateien: dict[str, bytes] = {}
        self.hochgeladen: list[str] = []
        self.geloescht: list[str] = []
        self.sitzungen: dict[str, str] = {}

    @staticmethod
    def _drive_pfad(pfad: str) -> tuple[str, str]:
        """'/me/drive/root:/KAM-Ablage/a.md:/content?x' -> ('KAM-Ablage/a.md', '/content')"""
        if pfad.startswith("/me/drive/items/"):
            rest = pfad[len("/me/drive/items/"):]
            for endung in ("/children", "/content"):
                if rest.endswith(endung):
                    return unquote(rest[:-len(endung)]), endung
            return unquote(rest), ""
        innen, _, rest = pfad[len("/me/drive/root:/"):].partition(":")
        return unquote(innen), rest.split("?")[0]

    def _ist_ordner(self, pfad: str) -> bool:
        return any(d.startswith(pfad + "/") for d in self.dateien)

    def request(self, methode, pfad, **kwargs):
        ort, rest = self._drive_pfad(pfad)
        if methode == "PUT" and rest == "/content":
            self.dateien[ort] = kwargs["data"]
            self.hochgeladen.append(ort)
            return Antwort()
        if methode == "DELETE":
            if ort not in self.dateien:
                raise http_fehler(404)
            del self.dateien[ort]
            self.geloescht.append(ort)
            return Antwort(204)
        raise AssertionError(f"unerwartete Anfrage {methode} {pfad}")

    def post(self, pfad, **kwargs):
        ort, rest = self._drive_pfad(pfad)
        assert rest == "/createUploadSession"
        url = f"https://upload.example/{len(self.sitzungen)}"
        self.sitzungen[url] = ort
        self.dateien[ort] = b""
        return {"uploadUrl": url}

    def teil_hochladen(self, url, data, timeout, headers):
        """Ersatz für requests.put an die Upload-Adresse."""
        assert "Authorization" not in headers, "Upload-Adresse darf kein Token bekommen"
        ort = self.sitzungen[url]
        start = int(headers["Content-Range"].split()[1].split("-")[0])
        assert start == len(self.dateien[ort]), "Teile in falscher Reihenfolge"
        self.dateien[ort] += data
        if headers["Content-Range"].endswith(f"/{len(self.dateien[ort])}"):
            self.hochgeladen.append(ort)
        r = mock.Mock()
        r.raise_for_status = lambda: None
        return r

    def get(self, pfad, **kwargs):
        ort, _ = self._drive_pfad(pfad)
        if not self._ist_ordner(ort):
            raise http_fehler(404)
        return {"webUrl": f"https://onedrive.example/{ort}"}

    def get_all(self, pfad, **kwargs):
        ort, rest = self._drive_pfad(pfad)
        assert rest == "/children"
        if not self._ist_ordner(ort):
            raise http_fehler(404)
        kinder = {}
        for d in self.dateien:
            if d.startswith(ort + "/"):
                name = d[len(ort) + 1:].split("/")[0]
                voll = f"{ort}/{name}"
                kinder[name] = {"name": name, "id": voll, **({"file": {}} if voll in self.dateien else {"folder": {}})}
        return list(kinder.values())

    def get_bytes(self, pfad):
        ort, rest = self._drive_pfad(pfad)
        assert rest == "/content"
        return self.dateien[ort]


def schreibe(wurzel: Path, rel: str, inhalt: str | bytes) -> None:
    datei = wurzel / rel
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_bytes(inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    config.ABLAGE_DIR = tmp
    config.ABLAGE_ONEDRIVE = True
    config.ABLAGE_ONEDRIVE_ORDNER = "KAM-Ablage"
    nutzer = "anna@firma.de"
    wurzel = ablage.ablage_pfad(nutzer)
    drive = FalschesOneDrive()

    print("Erster Abgleich")
    schreibe(wurzel, ablage.REGISTER, '{"kunden": []}')
    schreibe(wurzel, ablage.UEBERSICHT, "# Meine Ablage")
    schreibe(wurzel, "Firma X/_Allgemein/2026-11-02_0930 Konditionen 8 %.md", "Antwort 1")
    schreibe(wurzel, "Firma X/_Allgemein/Quellen/Mail.md", "Auszug")
    ergebnis = od.abgleichen(wurzel, drive)
    pruefe(ergebnis["hochgeladen"] == 4, f"4 Dateien hochgeladen ({ergebnis['hochgeladen']})")
    pruefe("KAM-Ablage/Firma X/_Allgemein/2026-11-02_0930 Konditionen 8 %.md" in drive.dateien,
           "Pfad mit Leerzeichen und % kommt richtig an")
    pruefe(not any(d.endswith(od.STAND_DATEI) for d in drive.dateien), "Stand des Abgleichs bleibt auf dem Server")
    pruefe(ergebnis["link"] == "https://onedrive.example/KAM-Ablage", "Link zum Ordner für die Anzeige")

    print("Zweiter Abgleich ohne Änderung")
    drive.hochgeladen.clear()
    ergebnis = od.abgleichen(wurzel, drive)
    pruefe(ergebnis["hochgeladen"] == 0 and not drive.hochgeladen, "nichts doppelt hochgeladen")

    print("Änderung und Umzug aus _Allgemein")
    schreibe(wurzel, ablage.UEBERSICHT, "# Meine Ablage\n| Firma X |")
    (wurzel / "Firma X/_Allgemein/2026-11-02_0930 Konditionen 8 %.md").replace(
        wurzel / "Firma X/Rahmenvertrag.md")
    drive.dateien["KAM-Ablage/Eigene Notiz.docx"] = b"vom Nutzer selbst angelegt"
    ergebnis = od.abgleichen(wurzel, drive)
    pruefe(drive.dateien["KAM-Ablage/_Uebersicht.md"].endswith(b"| Firma X |"), "geänderte Übersicht ersetzt")
    pruefe("KAM-Ablage/Firma X/Rahmenvertrag.md" in drive.dateien, "Datei am neuen Ort")
    pruefe("KAM-Ablage/Firma X/_Allgemein/2026-11-02_0930 Konditionen 8 %.md" not in drive.dateien,
           "Datei am alten Ort gelöscht")
    pruefe(ergebnis["geloescht"] == 1, f"genau eine Datei gelöscht ({ergebnis['geloescht']})")
    pruefe("KAM-Ablage/Eigene Notiz.docx" in drive.dateien, "eigene Datei des Nutzers bleibt unangetastet")

    print("Vom Nutzer schon gelöschte Datei")
    del drive.dateien["KAM-Ablage/Firma X/_Allgemein/Quellen/Mail.md"]
    (wurzel / "Firma X/_Allgemein/Quellen/Mail.md").unlink()
    ergebnis = od.abgleichen(wurzel, drive)
    pruefe(ergebnis["geloescht"] == 1, "404 beim Löschen ist kein Fehler")

    print("Große Datei")
    gross = bytes(range(256)) * (od.EINFACH_BIS // 256 * 3 + 7)
    schreibe(wurzel, "Firma X/Quellen/Handbuch.pdf", gross)
    with mock.patch.object(od.requests, "put", drive.teil_hochladen):
        od.abgleichen(wurzel, drive)
    pruefe(drive.dateien.get("KAM-Ablage/Firma X/Quellen/Handbuch.pdf") == gross,
           f"{len(gross) // 1024 // 1024} MB in Teilen vollständig hochgeladen")

    print("Wiederherstellen nach verlorener Arbeitskopie")
    vorher = {d: v for d, v in drive.dateien.items()}
    import shutil
    shutil.rmtree(wurzel)
    with mock.patch.object(od, "_graph", lambda n: drive):
        hinweis = od.wiederherstellen_falls_noetig(nutzer)
    pruefe(hinweis is not None and "wiederhergestellt" in hinweis, f"Meldung: {hinweis}")
    pruefe((wurzel / ablage.REGISTER).read_text(encoding="utf-8") == '{"kunden": []}', "Register zurück")
    pruefe((wurzel / "Firma X/Quellen/Handbuch.pdf").read_bytes() == gross, "große Datei zurück")
    drive.hochgeladen.clear()
    ergebnis = od.abgleichen(wurzel, drive)
    pruefe(ergebnis["hochgeladen"] == 0 and ergebnis["geloescht"] == 0, "danach nichts doppelt hoch- oder weggeladen")
    pruefe(drive.dateien == vorher, "OneDrive unverändert")

    print("Vorhandene Arbeitskopie, leeres OneDrive, Demo")
    with mock.patch.object(od, "_graph", lambda n: (_ for _ in ()).throw(AssertionError("kein Graph-Aufruf"))):
        pruefe(od.wiederherstellen_falls_noetig(nutzer) is None, "vorhandene Arbeitskopie: kein Graph-Aufruf")
        pruefe(od.wiederherstellen_falls_noetig("demo") is None, "Demo: nie abgleichen")
        pruefe(od.anstossen("demo") is False, "Demo: kein Abgleich im Hintergrund")
    with mock.patch.object(od, "_graph", lambda n: FalschesOneDrive()):
        pruefe(od.wiederherstellen_falls_noetig("neu@firma.de") is None, "erste Ablage: nichts wiederherzustellen")

    print("Hintergrund-Abgleich")
    laeufe, freigabe = [], threading.Event()

    def langsam(w, g):
        laeufe.append(time.time())
        if len(laeufe) == 1:
            freigabe.wait(5)
        return {"hochgeladen": 1, "geloescht": 0, "link": "https://onedrive.example/x"}

    with mock.patch.object(od, "abgleichen", langsam), mock.patch.object(od, "_graph", lambda n: drive):
        od.anstossen(nutzer)
        time.sleep(0.1)
        od.anstossen(nutzer)
        od.anstossen(nutzer)  # beide während des ersten Laufs -> zusammen nur ein weiterer Lauf
        freigabe.set()
        for _ in range(50):
            if od.status(nutzer)["zustand"] == "fertig":
                break
            time.sleep(0.05)
    pruefe(len(laeufe) == 2, f"zwei Läufe statt drei ({len(laeufe)})")
    pruefe(od.status(nutzer)["link"] == "https://onedrive.example/x", "Status mit Link")

    with mock.patch.object(od, "_graph", lambda n: (_ for _ in ()).throw(RuntimeError("Token abgelaufen"))):
        od.anstossen(nutzer)
        for _ in range(50):
            if od.status(nutzer)["zustand"] != "laeuft":
                break
            time.sleep(0.05)
    pruefe(od.status(nutzer)["zustand"] == "fehler" and "Token" in od.status(nutzer)["meldung"],
           "Fehler landet im Status statt in der App")

    print()
    if FEHLER:
        print(f"{len(FEHLER)} Fehler")
        return 1
    print("Alle Prüfungen bestanden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
