"""Daten einlesen (Indexaufbau): Quellen laden -> in Abschnitte teilen -> Embeddings -> ChromaDB.

Rolle im System:
    Dies ist der "Offline"-Teil des RAG-Verfahrens. Er läuft VOR den Fragen (per Kommandozeile oder
    über den Button "Daten neu einlesen") und legt einen lokalen Suchindex an. agent.py durchsucht
    später nur noch diesen Index; die Originalquellen werden bei einer Frage nicht mehr abgefragt.

Ablauf von ingest():
    1. lade_dokumente()     Dokumente aus Demo-Daten oder Microsoft Graph holen
    2. inhaltsverzeichnis() ein zusätzliches Übersichtsdokument über alle Kunden erzeugen
    3. teile_text()         lange Texte in Abschnitte (Chunks) von ca. 800 Zeichen teilen
    4. ollama.embed()       jeden neuen Abschnitt in einen Bedeutungsvektor umwandeln
    5. collection.add()     Text + Vektor + Metadaten in ChromaDB speichern

Aufruf:
    python ingest.py --source demo      # fiktive Daten aus demo_data/
    python ingest.py --source graph     # echte Daten über Microsoft Graph
    python ingest.py --source demo --neu   # Index vorher löschen

Jedes Dokument hat dieses einheitliche Format (egal aus welcher Quelle):
    {"text": "...", "meta": {"quelle": "OneNote|Outlook|Teams|Kalender|Datei",
                             "titel": ..., "ort": ..., "absender": ..., "datum": ..., "link": ...}}
"""
import argparse
import hashlib
import re
import time
from collections import Counter
from functools import lru_cache

import chromadb
import ollama

import config
from zeitraum import daten_im_text

# Metadaten, die zu jedem Abschnitt gespeichert werden (für Quellenangabe, Filter und Gewichtung)
META_FELDER = ["quelle", "titel", "ort", "absender", "datum", "link"]


def lade_dokumente(source: str, nutzer: str | None = None, graph=None) -> tuple[str, list[dict], list[str]]:
    """Lädt alle Dokumente aus der gewählten Quelle.

    Parameter:
        source: "demo" (lokale Beispieldaten) oder "graph" (Microsoft 365 des angemeldeten Nutzers)
        nutzer: erwartetes Microsoft-Konto (UPN) bei "graph"; eigener Token-Cache, falsches Konto wird abgelehnt
        graph: bereits angemeldeter GraphClient (einlesen.py); sonst wird hier einer erzeugt
    Rückgabe:
        (Nutzername, Dokumente, unvollständige Quellen). Der Nutzername bestimmt, in welchen Index geschrieben
        wird. Unvollständig = Quelle konnte nicht oder nur teilweise gelesen werden (Werte wie meta["quelle"]).
    """
    if source == "demo":
        import local_loader
        return "demo", local_loader.lade_alle(config.DEMO_DIR), []

    # Erst hier importiert: Der Demo-Modus braucht weder msal noch eine Internetverbindung
    from graph_client import GraphClient
    from connectors import files, kalender, onenote, outlook, teams

    graph = graph or GraphClient(config.EINLESE_SCOPES, nutzer)
    user = graph.get("/me")["userPrincipalName"]  # z. B. "max.muster@firma.de"
    if nutzer and user.lower() != nutzer.lower():  # doppelte Absicherung: nie in einen fremden Index schreiben
        raise RuntimeError(f"Token gehört zu {user}, erwartet {nutzer} – Einlesen abgebrochen")
    graph.dateien_cache = config.db_path(user) / "dateien_cache.json"
    print(f"Angemeldet als {user}")
    docs, unvollstaendig = [], []
    for name, quelle, connector in [("OneNote", "OneNote", onenote), ("Outlook", "Outlook", outlook),
                                    ("Kalender", "Kalender", kalender), ("Teams", "Teams", teams),
                                    ("Dateien", "Datei", files)]:
        probleme_vorher = len(graph.probleme)
        try:
            gefunden = connector.lade(graph)
            print(f"  {name}: {len(gefunden)} Dokumente")
            docs += gefunden
            if len(graph.probleme) > probleme_vorher:  # z. B. ein gesperrter Kanal oder eine defekte Datei
                unvollstaendig.append(quelle)
        except Exception as e:  # eine fehlende Berechtigung soll nicht alles abbrechen
            print(f"  {name}: übersprungen ({e})")
            unvollstaendig.append(quelle)
    return user, docs, unvollstaendig


def teile_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Zerlegt langen Text in überlappende Abschnitte, möglichst an Absatzgrenzen.

    Warum Abschnitte? Ein Embedding beschreibt die Bedeutung des GANZEN Textes. Bei einer langen
    OneNote-Seite mit vielen Themen würde die gesuchte Einzelinformation darin "untergehen".
    Kurze Abschnitte liefern präzisere Treffer und passen in das Kontextfenster des Modells.

    Beispiel (size=800, overlap=150): Zeichen 0-800, dann ab 650-1450 usw. Die Überlappung sorgt dafür,
    dass ein Satz an der Schnittstelle in mindestens einem Abschnitt vollständig enthalten ist.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        ende = min(start + size, len(text))
        if ende < len(text):
            # Letzten Zeilenumbruch in der zweiten Hälfte des Fensters suchen und dort schneiden
            umbruch = text.rfind("\n", start + size // 2, ende)  # lieber am Absatz schneiden
            if umbruch != -1:
                ende = umbruch
        chunks.append(text[start:ende].strip())
        if ende >= len(text):
            break
        start = ende - overlap  # nächster Abschnitt beginnt etwas vor dem Ende des vorigen
    return [c for c in chunks if c]


def kopfzeile(meta: dict) -> str:
    """Titel/Absender/Datum kommen mit in den Abschnitt, damit die Suche sie auch findet.

    Beispiel: "Rahmenvertrag | MBS 2 / Hoffmann Maschinenbau | 2023-04-01"
    Ohne Kopfzeile wüsste ein Abschnitt aus der Mitte einer Seite nicht, zu welchem Kunden er gehört.
    """
    teile = [meta.get("titel"), meta.get("ort"), meta.get("absender"), meta.get("datum")]
    return " | ".join(t for t in teile if t)


def oeffne_collection(user: str, neu: bool = False):
    """Öffnet (bzw. erstellt) die Vektor-Datenbank des Nutzers.

    ChromaDB speichert die Daten als Dateien unter data/<nutzer>/ (kein Datenbankserver nötig).
    "hnsw:space": "cosine" legt fest, dass Ähnlichkeit über den Kosinus der Vektoren gemessen wird.
    neu=True löscht vorher den kompletten Index.
    """
    client = chromadb.PersistentClient(path=str(config.db_path(user)))
    # list_collections() liefert je nach ChromaDB-Version Namen (str) oder Objekte -> beides abdecken
    if neu and "wissen" in [c if isinstance(c, str) else c.name for c in client.list_collections()]:
        client.delete_collection("wissen")
    return client.get_or_create_collection("wissen", metadata={"hnsw:space": "cosine"})


@lru_cache(maxsize=8)
def _lies_index(user: str, stand: int) -> dict:
    daten = oeffne_collection(user).get(include=["metadatas", "documents"])
    return {"ids": daten["ids"], "documents": daten["documents"], "metadatas": daten["metadatas"],
            "korpus": " ".join(daten["documents"]).lower()}


def index_daten(user: str) -> dict:
    """Alle Abschnitte eines Index plus Gesamttext, zwischengespeichert bis zum nächsten Einlesen.

    Die Suche braucht sie bei jeder Frage mehrfach. Die Stand-Datei schreibt ingest() am Ende; so bemerkt auch
    ein laufender Server, dass ein anderer Prozess neu eingelesen hat.
    """
    datei = config.db_path(user) / "stand.txt"
    return _lies_index(user, datei.stat().st_mtime_ns if datei.exists() else 0)


def inhaltsverzeichnis(docs: list[dict]) -> dict:
    """Zusätzliches Dokument aus der Ablagestruktur (OneNote-Abschnitte, Teams-Kanäle, Ordner).

    Damit kann der Agent Überblicksfragen wie "Welche Kunden betreue ich?" belegt beantworten –
    aus einzelnen Textabschnitten allein übersieht ein kleines Modell leicht einen Kunden.
    Das Dokument wird mit der Quelle "Übersicht" in den Index gelegt und wie jede andere Quelle gefunden.
    """
    def orte(quelle: str) -> Counter:
        # letzter Teil des Ablageorts = Kunde, z. B. "MBS 2 / Hoffmann Maschinenbau" -> "Hoffmann Maschinenbau"
        return Counter(re.split(r"[/>]", d["meta"]["ort"])[-1].strip() for d in docs if d["meta"]["quelle"] == quelle)
    onenote, teams, ordner = orte("OneNote"), orte("Teams"), orte("Datei")
    # eine Zeile je Kunde/Thema – eine lange Aufzählung überliest ein kleines Modell leicht
    zeilen = [f"- {name}: {onenote[name]} OneNote-Seiten, {teams[name]} Teams-Nachrichten"
              for name in sorted(set(onenote) | set(teams))]
    text = ("Inhaltsverzeichnis der eigenen Ablage: Welche Kunden (Key Accounts) und Themen betreue ich? "
            f"Automatisch erzeugt aus den Abschnitten des OneNote-Notizbuchs {config.NOTEBOOK_NAME} und den "
            f"Teams-Kanälen. Es gibt {len(zeilen)} Abschnitte:\n" + "\n".join(zeilen) + "\n"
            f"Kunden mit eigenem Ablageordner: {', '.join(sorted(ordner)) or '–'}.\n"
            f"Dazu {sum(d['meta']['quelle'] == 'Outlook' for d in docs)} E-Mails und "
            f"{sum(d['meta']['quelle'] == 'Kalender' for d in docs)} Kalendertermine.")
    return {"text": text, "meta": {"quelle": "Übersicht", "titel": "Inhaltsverzeichnis der Ablage",
                                   "ort": "automatisch erzeugt", "link": "uebersicht"}}


def ingest(source: str, neu: bool = False, nutzer: str | None = None, graph=None) -> list[str]:
    """Kompletter Indexaufbau (siehe Ablauf oben). Arbeitet inkrementell: Nur neue oder geänderte
    Abschnitte werden neu berechnet, nicht mehr vorhandene werden gelöscht.

    Eine Quelle, die nicht vollständig gelesen werden konnte, behält ihre bisherigen Abschnitte: Fehlende
    Dokumente heißen dann nicht "gelöscht", sondern "nicht erreichbar" (z. B. vorübergehender Fehler 401).
    Rückgabe: unvollständige Quellen (leer = alles aktuell).
    """
    user, docs, unvollstaendig = lade_dokumente(source, nutzer, graph)
    if neu and unvollstaendig:
        print(f"Index wird nicht gelöscht, weil unvollständig gelesen wurde: {', '.join(unvollstaendig)}")
        neu = False
    collection = oeffne_collection(user, neu)
    bisher = collection.get(include=["metadatas"])
    # Das Inhaltsverzeichnis wäre ohne die fehlende Quelle falsch -> dann das bisherige behalten
    geschuetzt = set(unvollstaendig)
    if unvollstaendig and any(m["quelle"] == "Übersicht" for m in bisher["metadatas"]):
        geschuetzt.add("Übersicht")
    else:
        docs.append(inhaltsverzeichnis(docs))

    # --- Schritt 1: alle Dokumente in Abschnitte zerlegen und vorbereiten ---
    ids, texte, metas, gesehen = [], [], [], set()
    for doc in docs:
        # ChromaDB erlaubt in Metadaten nur einfache Werte -> alles als Text, fehlende Felder als ""
        meta = {f: str(doc["meta"].get(f) or "") for f in META_FELDER}
        for i, chunk in enumerate(teile_text(doc["text"])):
            text = f"{kopfzeile(meta)}\n{chunk}"
            # Alle im Abschnitt genannten Daten merken -> Fragen wie "nächste Woche" lassen sich danach filtern
            termine = ",".join(d.isoformat() for d in daten_im_text(chunk))
            # Die ID ergibt sich aus dem Inhalt -> unveränderte Abschnitte werden nicht neu berechnet.
            id_ = hashlib.sha1((text + meta["link"]).encode()).hexdigest()
            if id_ in gesehen:
                continue  # gleicher Text mit gleichem Link (z. B. zweimal "ok" im Chat): nur einmal speichern
            gesehen.add(id_)
            ids.append(id_)
            texte.append(text)
            metas.append({**meta, "termine": termine})

    # --- Schritt 2: Index mit dem aktuellen Stand abgleichen ---
    # Entfernt werden Abschnitte, die es in den Quellen nicht mehr gibt (gelöscht, geändert, verschobene Termine)
    alt = {i for i, m in zip(bisher["ids"], bisher["metadatas"]) if m["quelle"] not in geschuetzt} - gesehen
    vorhanden = set(bisher["ids"])
    neu_idx = [i for i, id_ in enumerate(ids) if id_ not in vorhanden]  # Positionen der neuen Abschnitte
    print(f"{len(docs)} Dokumente -> {len(ids)} Abschnitte, davon {len(neu_idx)} neu, {len(alt)} entfernt")

    # --- Schritt 3: Embeddings nur für neue Abschnitte berechnen und speichern ---
    for start in range(0, len(neu_idx), 32):  # in Paketen, damit der Speicher reicht
        stapel = neu_idx[start:start + 32]
        vektoren = ollama.embed(model=config.EMBED_MODEL, input=[texte[i] for i in stapel]).embeddings
        collection.add(ids=[ids[i] for i in stapel], documents=[texte[i] for i in stapel],
                       metadatas=[metas[i] for i in stapel], embeddings=vektoren)
    # Erst löschen, wenn das Neue gespeichert ist: Fällt Ollama vorher aus, bleibt der alte Stand erhalten
    if alt:
        collection.delete(ids=list(alt))
    (config.db_path(user) / "stand.txt").write_text(str(time.time()), encoding="utf-8")  # siehe index_daten()

    # Zusammenfassung: wie viele Abschnitte je Quelle jetzt im Index liegen
    zaehler = Counter(m["quelle"] for m in collection.get(include=["metadatas"])["metadatas"])
    print("Index für", user, "->", dict(zaehler))
    if unvollstaendig:
        print(f"Unvollständig gelesen, bisherige Abschnitte bleiben erhalten: {', '.join(unvollstaendig)}")
    return unvollstaendig


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daten in den lokalen Index einlesen")
    parser.add_argument("--source", choices=["demo", "graph"], default="demo")
    parser.add_argument("--neu", action="store_true", help="Index vorher löschen")
    parser.add_argument("--nutzer", help="Microsoft-Konto (UPN), für das eingelesen wird; Pflicht, sobald mehrere "
                                         "Nutzer auf diesem Rechner/Server einlesen")
    args = parser.parse_args()
    ingest(args.source, args.neu, args.nutzer)
