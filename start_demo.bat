@echo off
rem =========================================================================
rem Startet die Demo: Daten neu einlesen und Streamlit-Oberflaeche oeffnen.
rem Nutzt immer die virtuelle Umgebung, egal welches Python sonst installiert ist.
rem
rem Ablauf:
rem   1. in den Projektordner wechseln
rem   2. beim ersten Start: virtuelle Umgebung anlegen und Pakete installieren
rem   3. Demo-Daten in den Suchindex einlesen (ingest.py)
rem   4. Oberflaeche starten (app.py), erreichbar unter http://localhost:8510
rem =========================================================================

rem %~dp0 = Ordner dieser .bat-Datei -> funktioniert auch per Doppelklick
cd /d "%~dp0"
rem Virtuelle Umgebung ausserhalb von OneDrive, damit OneDrive nicht tausende Dateien synchronisiert
set VENV=%USERPROFILE%\.venvs\ki-agent
rem Umlaute in der Konsolenausgabe korrekt darstellen
set PYTHONIOENCODING=utf-8

if not exist "%VENV%\Scripts\python.exe" (
    echo Virtuelle Umgebung fehlt - wird einmalig eingerichtet ...
    python -m venv "%VENV%"
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
)

echo Lese Demo-Daten ein ...
"%VENV%\Scripts\python.exe" ingest.py --source demo
rem Haeufigste Fehlerursache: Ollama laeuft nicht oder die Modelle fehlen
if errorlevel 1 (
    echo.
    echo Fehler beim Einlesen. Laeuft Ollama? Modelle vorhanden? ^(ollama pull qwen2.5:7b / ollama pull bge-m3^)
    pause
    exit /b 1
)

echo Starte Oberflaeche unter http://localhost:8510 ...
"%VENV%\Scripts\python.exe" -m streamlit run app.py
