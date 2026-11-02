#!/usr/bin/env bash
# =========================================================================
# Startablauf im Agent-Container (wie start_demo.bat unter Windows):
#   1. warten, bis Ollama antwortet, fehlende Modelle einmalig herunterladen
#   2. Demo-Daten neu einlesen (die Demo-Termine liegen relativ zum heutigen Tag)
#   3. Streamlit starten, im Container auf allen Adressen (0.0.0.0) statt nur localhost,
#      sonst wäre die App von außerhalb des Containers nicht erreichbar
# =========================================================================
set -euo pipefail

echo "== 1. Ollama und Modelle prüfen ($OLLAMA_HOST)"
python - <<'EOF'
import time

import ollama

import config

for versuch in range(60):
    try:
        vorhanden = {m.model for m in ollama.list().models}
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("Ollama nicht erreichbar")

for modell in (config.CHAT_MODEL, config.EMBED_MODEL):
    name = modell if ":" in modell else modell + ":latest"
    if name not in vorhanden:
        print(f"Lade Modell {modell} herunter (einmalig, einige GB) ...", flush=True)
        ollama.pull(modell)
print("Modelle vorhanden:", ", ".join(sorted(vorhanden | {config.CHAT_MODEL, config.EMBED_MODEL})))
EOF

echo "== 2. Demo-Daten einlesen"
python ingest.py --source demo

echo "== 3. Oberfläche starten (Port 8510)"
exec python -m streamlit run app.py --server.address 0.0.0.0 --server.headless true
