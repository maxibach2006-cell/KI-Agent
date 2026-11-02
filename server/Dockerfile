# =========================================================================
# Container des Agenten: Streamlit-App (app.py) mit Suche, Index und Ablage.
# Das Sprachmodell läuft NICHT hier, sondern im Container "ollama" (siehe docker-compose.yml).
# Gebaut wird aus dem Projektordner: docker compose -f server/docker-compose.yml build
# =========================================================================
FROM python:3.12-slim

# Python-Ausgaben sofort in die Logs schreiben, keine .pyc-Dateien im Container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# tzdata: Ohne Zeitzonendaten rechnet der Container in UTC, dann wäre "heute" für Zeitfragen
# zwischen 0 und 1 Uhr (bzw. 2 Uhr im Sommer) noch der Vortag.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Erst nur die Paketliste kopieren: Docker baut die (langsame) Paketinstallation dann nur neu,
# wenn sich requirements.txt ändert, nicht bei jeder Codeänderung.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Eigener Benutzer statt root: Eine Lücke in der Web-App gäbe so keine Root-Rechte im Container.
# Die Ordner für Index und Ablage gehören ihm, damit die Volumes beschreibbar sind.
RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /app/data /daten/ablage \
    && chown -R agent:agent /app/data /daten
USER agent

EXPOSE 8510
CMD ["bash", "server/agent_start.sh"]
