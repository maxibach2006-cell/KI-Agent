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
KEEP_ALIVE = "30m" # Modelle im VRAM halten -> kein Nachladen zwischen den Fragen

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
TOKEN_CACHE = BASE_DIR / ".token_cache.json"  # gespeichertes Microsoft-Anmeldetoken


def heute() -> date:
    """Heutiges Datum, auf das sich relative Zeitangaben ("nächste Woche") beziehen.

    Für Tests und Präsentationen lässt sich ein fester Stichtag setzen (in .env: HEUTE=2026-11-02).
    So liefern Zeitfragen an jedem Tag dasselbe, nachvollziehbare Ergebnis.
    """
    return date.fromisoformat(os.getenv("HEUTE")) if os.getenv("HEUTE") else date.today()


def db_path(user: str) -> Path:
    """Ordner der Vektor-Datenbank für einen Nutzer.

    Jeder Nutzer bekommt einen eigenen Index -> keine fremden Daten in den Antworten.
    Aus dem Nutzernamen (z. B. "max.muster@firma.de") wird ein gültiger Ordnername ("max_muster_firma_de").
    """
    safe = "".join(c if c.isalnum() else "_" for c in user.lower())
    return DATA_DIR / safe
