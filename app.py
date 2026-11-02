"""Streamlit-Oberfläche: Chat mit dem Informations-Agenten.

Start:  streamlit run app.py   (oder start_demo.bat)

Funktionsweise von Streamlit (wichtig zum Verständnis dieser Datei):
    Streamlit führt das GANZE Skript bei jeder Nutzeraktion (Klick, Eingabe) von oben nach unten neu aus.
    Was zwischen zwei Durchläufen erhalten bleiben soll (hier: der Chatverlauf), liegt in
    st.session_state. Teure Aktionen, die nur einmal passieren sollen (Modell laden), werden mit
    @st.cache_resource zwischengespeichert.

Aufbau der Seite:
    1. Seitenleiste:  Datenquelle, Nutzer, Sprachmodell, "Daten neu einlesen", "Neues Gespräch"
    2. Hauptbereich:  Beispielfragen, bisheriger Chatverlauf, Eingabefeld
    3. Bei einer Frage: die Agent-Schritte einzeln aufrufen und Zwischenstände anzeigen
       (verstanden als ..., zusätzlich gesucht nach ..., gestreamte Antwort, Quellen, Textauszüge)
"""
import time

import ollama
import streamlit as st

import agent
import config
import verstehen
from ingest import ingest, oeffne_collection

st.set_page_config(page_title="KAM Informations-Agent", page_icon="🔎", layout="wide")

# Feste Fragen für die Präsentation (siehe Demo-Ablauf im README)
BEISPIELFRAGEN = [
    "Welche Konditionen gelten im Rahmenvertrag mit Hoffmann Maschinenbau und bis wann läuft er?",
    "Was haben wir 2019 mit NordWerk im Projekt Billbrook vereinbart?",
    "Wann findet die Bedarfsanalyse Hannover mit NordWerk statt?",
    "Welche Termine habe ich nächste Woche?",
]

# --- 1. Seitenleiste -------------------------------------------------------
with st.sidebar:
    st.header("Einstellungen")
    quelle = st.radio("Datenquelle", ["demo", "graph"],
                      format_func=lambda q: "Demo-Daten (lokal)" if q == "demo" else "Microsoft 365 (Graph)")
    # Der Nutzer bestimmt, welcher Index durchsucht wird (ein Index pro Nutzer, siehe config.db_path)
    user = "demo" if quelle == "demo" else st.text_input("Angemeldeter Nutzer (UPN)", value="")
    modelle = [m.model for m in ollama.list().models]  # alle lokal installierten Ollama-Modelle
    model = st.selectbox("Sprachmodell", modelle,
                         index=modelle.index(config.CHAT_MODEL) if config.CHAT_MODEL in modelle else 0)
    if st.button("Daten neu einlesen"):
        with st.spinner("Lese Daten ein …"):
            ingest(quelle)
        st.success("Index aktualisiert")
    if user:
        st.caption(f"Abschnitte im Index von **{user}**: {oeffne_collection(user).count()}")
    if st.button("Neues Gespräch"):  # Folgefragen beziehen sich sonst auf die bisherigen Runden
        st.session_state.verlauf = []
    st.divider()
    st.caption("Alle Daten und das Sprachmodell bleiben lokal auf diesem Rechner. "
               "Es werden nur Daten des angemeldeten Nutzers durchsucht.")

@st.cache_resource(show_spinner="Lade Sprachmodell …")
def modell_laden(name: str) -> bool:
    """Lädt das gewählte Modell vorab in den Grafikspeicher (dank Cache nur einmal pro Modell)."""
    agent.aufwaermen(name)  # einmal pro Modell, damit schon die erste Frage schnell ist
    return True


# --- 2. Hauptbereich ---------------------------------------------------------
modell_laden(model)
st.title("🔎 Informations-Agent Key-Account-Management")
st.caption("Durchsucht OneNote „MBS 2“, Teams und Outlook – jede Aussage mit Quelle.")

# Chatverlauf: Liste von {"rolle": "user"|"assistant", "text": ...}, abwechselnd Frage und Antwort
if "verlauf" not in st.session_state:
    st.session_state.verlauf = []

# Beispielfragen als Buttons (praktisch für die Demo)
spalten = st.columns(len(BEISPIELFRAGEN))
geklickt = None
for spalte, frage in zip(spalten, BEISPIELFRAGEN):
    if spalte.button(frage, use_container_width=True):
        geklickt = frage

# bisherigen Verlauf anzeigen (wird bei jedem Durchlauf neu gezeichnet)
for eintrag in st.session_state.verlauf:
    with st.chat_message(eintrag["rolle"]):
        st.markdown(eintrag["text"])

# --- 3. Neue Frage beantworten -----------------------------------------------
frage = st.chat_input("Ihre Frage …") or geklickt  # getippte Frage oder geklickte Beispielfrage
if frage and user:
    # bisherige Runden (Frage + Antwort) für Folgefragen wie "Und bis wann läuft der?"
    # [::2] = alle Fragen, [1::2] = alle Antworten -> paarweise zu Runden zusammenfassen
    eintraege = st.session_state.verlauf
    runden = [{"frage": f["text"], "antwort": a["text"]}
              for f, a in zip(eintraege[::2], eintraege[1::2]) if f["rolle"] == "user"]
    st.session_state.verlauf.append({"rolle": "user", "text": frage})
    with st.chat_message("user"):
        st.markdown(frage)

    # Dieselben Schritte wie agent.antworte(), aber einzeln, um Zwischenstände anzuzeigen
    with st.chat_message("assistant"):
        start = time.perf_counter()
        with st.spinner("Verstehe die Frage …"):                      # Schritt 0: Folgefrage auflösen
            verstanden = verstehen.umschreiben(frage, runden, model)
        if verstanden != frage:
            st.caption(f"🔁 Verstanden als: *{verstanden}*")
        with st.spinner("Suche in Ihren Quellen …"):                  # Schritt 1: Suche
            treffer, varianten = agent.suche_verstanden(verstanden, user, model)
        if varianten:
            st.caption("🔎 Zusätzlich gesucht nach: " + " · ".join(f"*{v}*" for v in varianten))
        with st.spinner("Prüfe Quellen auf Widersprüche …"):          # Schritt 2: Widersprüche
            widersprueche = agent.pruefe_widersprueche(verstanden, treffer, model)
        antwort = st.write_stream(agent.generiere(verstanden, treffer, widersprueche, model))  # Schritt 3: Antwort
        quellen = agent.anhang_markdown(treffer, widersprueche)        # Schritt 4: Anhang aus dem Code
        st.markdown(quellen)
        dauer = time.perf_counter() - start
        st.caption(f"⏱️ Antwort in {dauer:.1f} s · {len(treffer)} Quellen durchsucht")

        # Aufklappbare Originaltexte: Der Nutzer kann jede Aussage selbst an der Quelle nachprüfen
        for i, t in enumerate(treffer, start=1):
            with st.expander(f"[{i}] {t['meta']['quelle']} – {t['meta']['titel']} "
                             f"(Ähnlichkeit {t['aehnlichkeit']:.2f})"):
                st.text(t["text"])

    st.session_state.verlauf.append({"rolle": "assistant", "text": antwort + quellen})
elif frage:
    st.warning("Bitte zuerst den angemeldeten Nutzer angeben und die Daten einlesen.")
