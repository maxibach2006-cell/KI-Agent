"""Zentrale Einstellungen des Informations-Agenten.

Rolle im System:
    Jede andere Datei importiert dieses Modul ("import config") und liest von hier Modellnamen,
    Schwellwerte der Suche und Dateipfade. Damit stehen alle Stellschrauben an EINER Stelle und
    man muss für ein Experiment (z. B. ein anderes Sprachmodell) keinen Programmcode ändern.

Herkunft der Werte:
    - Feste Werte stehen direkt unten im Code.
    - Geheime oder umgebungsabhängige Werte (Client-ID, Tenant-ID, Modellname, Stichtag) kommen
      aus der Datei .env im Projektordner. Vorlage: .env.example. Die .env wird nicht weitergegeben.
"""
import hashlib
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Projektordner = Ordner, in dem diese Datei liegt. Alle Pfade werden relativ dazu gebildet,
# damit das Programm unabhängig vom aktuellen Arbeitsverzeichnis funktioniert.
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")  # Werte aus .env als Umgebungsvariablen verfügbar machen

# =============================================================================
# Sprachmodelle (laufen lokal über Ollama, siehe https://ollama.com)
# =============================================================================
# Chat-Modell: schreibt die Antworten und übernimmt Hilfsaufgaben (Umschreiben, Widerspruchsprüfung).
# qwen2.5:7b passt mit ~4,7 GB in 8 GB VRAM (RTX 2070 Super) und kann gut Deutsch.
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b")
# Embedding-Modell: wandelt Text in einen Zahlenvektor um, damit man Texte nach Bedeutung vergleichen kann.
# bge-m3 ist ein mehrsprachiges Embedding-Modell und funktioniert gut mit deutschen Texten.
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
TEMPERATURE = 0.1  # Zufälligkeit der Textgenerierung; niedrig = sachliche, reproduzierbare Antworten
NUM_CTX = 8192     # Kontextfenster in Tokens (Prompt + Antwort); 10-12 Quellen brauchen ca. 4.500
# Modelle im VRAM halten -> kein Nachladen zwischen den Fragen. Auf dem Server dauerhaft (siehe docker-compose.yml)
KEEP_ALIVE = os.getenv("KEEP_ALIVE", "30m")

# =============================================================================
# Microsoft Graph (Zugriff auf die echten Microsoft-365-Daten, nur im Modus "graph")
# =============================================================================
CLIENT_ID = os.getenv("CLIENT_ID", "")                     # ID der App-Registrierung in Entra ID
TENANT_ID = os.getenv("TENANT_ID", "organizations")        # Firmen-Tenant; "organizations" = beliebiger Firmen-Account
NOTEBOOK_NAME = os.getenv("NOTEBOOK_NAME", "MBS 2")        # OneNote-Notizbuch, das durchsucht wird
TEAM_NAME = os.getenv("TEAM_NAME", "Key Account - Kunden") # Team, das seed_graph.py im Test-Tenant befüllt

# Berechtigungen ("Scopes"), die der Nutzer beim Anmelden erteilt.
# Nur lesende, delegierte Rechte: Graph liefert nur Daten, auf die der angemeldete Nutzer Zugriff hat.
# "Delegiert" heißt: Die App handelt im Namen des Nutzers und kann nie mehr sehen als er selbst.
READ_SCOPES = [
    "User.Read",               # eigenes Profil (Name, E-Mail-Adresse)
    "Notes.Read",              # OneNote
    "Mail.Read",               # Outlook-Postfach
    "Calendars.Read",          # Outlook-Kalender
    "Chat.Read",               # persönliche Teams-Chats
    "Team.ReadBasic.All",      # Liste der eigenen Teams
    "Channel.ReadBasic.All",   # Kanäle dieser Teams
    "ChannelMessage.Read.All", # Nachrichten in den Kanälen
    "Files.Read.All",          # Dateien in OneDrive
    "Sites.Read.All",          # Dateien in SharePoint (Teams-Ablagen)
]
# Schreibrecht für die persönliche Ablage im eigenen OneDrive (ablage_onedrive.py). Nur das eigene OneDrive, keine
# fremden Dateien und kein SharePoint. Wird beim Einlesen mit angefragt, damit eine Anmeldung für beides reicht.
ABLAGE_SCOPES = ["User.Read", "Files.ReadWrite"]
# Zusätzliche Schreibrechte nur für seed_graph.py (Befüllen eines Test-Tenants mit Demo-Daten).
SEED_SCOPES = [
    "User.Read",
    "Notes.ReadWrite",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "ChannelMessage.Send",
    "Channel.Create",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "Files.ReadWrite.All",
]

# =============================================================================
# Suche (Retrieval) – alle Schwellwerte, die über "gefunden / nicht gefunden" entscheiden
# =============================================================================
# Ähnlichkeitswerte sind Kosinus-Ähnlichkeiten zwischen Frage- und Textvektor:
# 1,0 = gleiche Bedeutung, 0 = kein Zusammenhang.
CHUNK_SIZE = 800        # Zeichen pro Textabschnitt ("Chunk"); kurz genug für präzise Treffer
CHUNK_OVERLAP = 150     # Überlappung, damit Sätze an Grenzen nicht verloren gehen
TOP_K = 6               # so viele Abschnitte bekommt das Modell als Kontext
ONENOTE_BOOST = 0.05    # Bonus auf die Ähnlichkeit: OneNote "MBS 2" wird priorisiert (fachliche Vorgabe)
# Kalibriert mit evaluation/testfragen.json: beantwortbare Fragen >= 0,59, unbeantwortbare <= 0,53
MIN_SIMILARITY = 0.56   # bester Treffer darunter -> "keine passende Quelle gefunden" (Schutz vor Halluzination)
KONTEXT_MIN = 0.45      # weitere Abschnitte ab dieser Ähnlichkeit kommen mit in den Kontext
STICHWORT_GEWICHT = 0.25  # Einfluss der Stichwortsuche (Anteil gefundener Fragewörter) auf die Rangfolge
UEBERBLICK_TOP_K = 10   # "Fasse zusammen", "Welche Kunden ...": mehr Quellen
GLEICH_SCHWELLE = 0.6   # Widerspruch nur, wenn beide Werte zu >= 60 % gleich beschrieben werden
VARIANTEN_SCHWELLE = 0.6  # bester Treffer darunter -> zusätzlich mit umformulierten Suchvarianten suchen
VERLAUF_RUNDEN = 3      # so viele vorherige Fragen/Antworten nutzt das Umschreiben von Folgefragen
ZEIT_TOP_K = 12         # Zeitfragen ("nächste Woche"): max. so viele Einträge aus dem Zeitraum
KALENDER_BOOST = 0.1    # bei Zeitfragen sind Kalendertermine meist das Gesuchte

# =============================================================================
# Pfade
# =============================================================================
DATA_DIR = BASE_DIR / "data"           # Vektor-Datenbank (ChromaDB), getrennt pro Nutzer
DEMO_DIR = BASE_DIR / "demo_data"      # fiktive Beispieldaten für den Demo-Modus
# Gespeichertes Microsoft-Anmeldetoken; im Container auf einem Volume, weil /app dort nicht beschreibbar ist
TOKEN_CACHE = Path(os.getenv("TOKEN_CACHE", str(BASE_DIR / ".token_cache.json")))


def token_cache(nutzer: str | None = None) -> Path:
    """Token-Cache-Datei. Mit Nutzer: eine eigene Datei je Konto im selben Ordner wie TOKEN_CACHE
    (z. B. .token_cache_jonas_firma_de.json). So kann ein Einlesen nie das Token eines anderen Nutzers verwenden."""
    if not nutzer:
        return TOKEN_CACHE
    return TOKEN_CACHE.parent / f".token_cache_{sicherer_name(nutzer)}.json"  # eindeutig wie der Index (E24)

# Serverbetrieb (docker-compose.yml): Der Nutzer kommt aus der Anmeldung, Modell und Einlesen sind nicht wählbar
SERVER_MODUS = os.getenv("SERVER_MODUS", "0") == "1"
# Einlesen bei der Anmeldung (einlesen.py). Ohne CLIENT_ID oder mit AUTO_EINLESEN=0 bleibt es bei den Demo-Daten
# und dem Einlesen von Hand, z. B. für die Vorführung, wenn der befristete Test-Tenant abgelaufen ist.
AUTO_EINLESEN = SERVER_MODUS and bool(CLIENT_ID) and os.getenv("AUTO_EINLESEN", "1") != "0"
# Daten höchstens so oft auffrischen; 8 Stunden entsprechen der Sitzungsdauer von Cloudflare Access
EINLESEN_ALLE_STUNDEN = float(os.getenv("EINLESEN_ALLE_STUNDEN", "8"))

# =============================================================================
# Persönliche Ablage (ablage.py): Ordner je Kunde und Thema, wächst mit jeder Frage
# =============================================================================
# Bewusst außerhalb des Projektordners (keine Kundendaten im Repository) und standardmäßig nicht in OneDrive.
ABLAGE_DIR = Path(os.getenv("ABLAGE_DIR", str(Path.home() / "KAM-Ablage")))
ABLAGE_AKTIV = os.getenv("ABLAGE_AKTIV", "1") != "0"  # Voreinstellung des Schalters in der App
# Ablage zusätzlich im OneDrive des Nutzers (ablage_onedrive.py). Nur mit App-Registrierung und nur für Graph-Konten.
ABLAGE_ONEDRIVE = bool(CLIENT_ID) and os.getenv("ABLAGE_ONEDRIVE", "1") != "0"
ABLAGE_ONEDRIVE_ORDNER = os.getenv("ABLAGE_ONEDRIVE_ORDNER", "KAM-Ablage")  # Ordner im Stamm des OneDrive
# Arbeitskopie der Ablage nur für die Dauer der Sitzung (ablage_onedrive.aufraeumen). Im Serverbetrieb an: Danach
# liegt die Ablage nur noch im OneDrive des Nutzers. Ende der Sitzung = so lange kein Lebenszeichen der App.
ABLAGE_KOPIE_LOESCHEN = os.getenv("ABLAGE_KOPIE_LOESCHEN", "1" if SERVER_MODUS else "0") == "1"
ABLAGE_SITZUNG_ENDE_MINUTEN = float(os.getenv("ABLAGE_SITZUNG_ENDE_MINUTEN", "10"))
# Rechte beim Anmelden zum Einlesen: mit Ablage in OneDrive gleich das Schreibrecht dafür, eine Anmeldung für beides
EINLESE_SCOPES = list(dict.fromkeys(READ_SCOPES + (ABLAGE_SCOPES if ABLAGE_ONEDRIVE else [])))
ABLAGE_MIN_FRAGEN = 2       # Ordner für Kunde bzw. Thema erst ab so vielen Fragen (vorher nur vorgemerkt)
# Frage ohne Kundennamen: Kunde aus den Quellen nur übernehmen, wenn mindestens dieser Anteil der Quellen zu ihm gehört
ABLAGE_KUNDE_ANTEIL = 0.5
# Ab dieser Embedding-Ähnlichkeit gilt ein Thema als bereits bekannt (z. B. "Rahmenvertrag" ~ "Rahmenvertrag RV-1").
# Vorläufiger Wert, noch nicht mit echten Fragen kalibriert.
ABLAGE_THEMA_SCHWELLE = 0.8


# =============================================================================
# Strom-Tracker (strom.py)
# =============================================================================
STROM_PREIS_EURO_KWH = float(os.getenv("STROM_PREIS_EURO_KWH", "0.35"))  # Annahme, eigenen Tarif in .env eintragen
STROM_REST_WATT = float(os.getenv("STROM_REST_WATT", "60"))  # geschätzter Verbrauch des PCs ohne Grafikkarte


def heute() -> date:
    """Heutiges Datum, auf das sich relative Zeitangaben ("nächste Woche") beziehen.

    Für Tests und Präsentationen lässt sich ein fester Stichtag setzen (in .env: HEUTE=2026-11-02).
    So liefern Zeitfragen an jedem Tag dasselbe, nachvollziehbare Ergebnis.
    """
    return date.fromisoformat(os.getenv("HEUTE")) if os.getenv("HEUTE") else date.today()


def sicherer_name(user: str) -> str:
    """Gültiger Ordnername für einen Nutzer, z. B. "max.muster@firma.de" -> "max_muster_firma_de_1a2b3c4d".

    Der Prüfwert hält ähnliche Namen auseinander ("a.b@firma.de" und "a_b@firma.de"), sonst teilten
    sich zwei Personen Index und Ablage.
    """
    name = user.lower()
    safe = "".join(c if c.isalnum() else "_" for c in name)
    return safe if safe == name else f"{safe}_{hashlib.sha1(name.encode()).hexdigest()[:8]}"


def db_path(user: str) -> Path:
    """Ordner der Vektor-Datenbank für einen Nutzer.
    Jeder Nutzer bekommt einen eigenen Index -> keine fremden Daten in den Antworten."""
    return DATA_DIR / sicherer_name(user)


def index_stand(user: str) -> float | None:
    """Zeitpunkt des letzten abgeschlossenen Einlesens (Sekunden seit 1970), None = noch nie abgeschlossen.
    ingest() schreibt stand.txt ganz am Ende. Der Ordner allein sagt nichts: Er entsteht schon beim Start des Einlesens."""
    datei = db_path(user) / "stand.txt"
    return datei.stat().st_mtime if datei.exists() else None


def index_nutzer(email: str) -> str:
    """Index für eine angemeldete Adresse im Serverbetrieb: der eigene, falls fertig eingelesen, sonst die Demo-Daten.
    Die Adresse kommt aus der Anmeldung, ohne Anmeldung gibt es nur die Demo-Daten."""
    return email if email and index_stand(email) is not None else "demo"
