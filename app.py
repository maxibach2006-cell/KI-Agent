"""Streamlit-Oberfläche: Chat mit dem Informations-Agenten.

Start:  streamlit run app.py   (oder start_demo.bat)

Funktionsweise von Streamlit (wichtig zum Verständnis dieser Datei):
    Streamlit führt das GANZE Skript bei jeder Nutzeraktion (Klick, Eingabe) von oben nach unten neu aus.
    Was zwischen zwei Durchläufen erhalten bleiben soll (hier: der Chatverlauf), liegt in
    st.session_state. Teure Aktionen, die nur einmal passieren sollen (Modell laden), werden mit
    @st.cache_resource zwischengespeichert.

Aufbau der Seite:
    1. Seitenleiste:  Datenquelle, Nutzer, Sprachmodell, "Daten neu einlesen", "Neues Gespräch", Ablage an/aus
    2. Hauptbereich:  Beispielfragen, bisheriger Chatverlauf, Eingabefeld
    Im Serverbetrieb davor: Stand des automatischen Einlesens mit dem Anmeldecode (einlesen.py)
    3. Bei einer Frage: die Bausteine des Agenten aufrufen und Zwischenstände anzeigen
       (verstanden als ..., zusätzlich gesucht nach ..., gestreamte Antwort, Quellen, Textauszüge)
    4. Danach (falls eingeschaltet): Frage und Antwort in die persönliche Ablage einordnen (ablage.py)
"""
import time

import ollama
import streamlit as st

import ablage
import agent
import config
import einlesen
import strom
from ingest import ingest, oeffne_collection

st.set_page_config(page_title="KAM Informations-Agent", page_icon="🔎", layout="wide")
strom.starte()  # Strommessung im Hintergrund, läuft nur einmal je Serverprozess

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
    email = ""
    if config.SERVER_MODUS:
        # Auf dem Server bestimmt allein die Anmeldung den Nutzer (Cloudflare Access setzt diesen Header).
        # Keine Eingabe, keine Modellwahl: Das steht aus dem Internet niemandem offen. Eingelesen wird automatisch
        # und nur für diese Adresse (einlesen.py, Anzeige siehe einlese_status).
        email = st.context.headers.get("Cf-Access-Authenticated-User-Email", "")
        user, ablage_nutzer, model = config.index_nutzer(email), email or "demo", config.CHAT_MODEL
        st.caption(f"Angemeldet als **{email or 'Gast'}**")
        if user == email and email:
            st.caption(f"Stand der Daten: {time.strftime('%d.%m.%Y %H:%M', time.localtime(config.index_stand(email)))}")
    else:
        quelle = st.radio("Datenquelle", ["demo", "graph"],
                          format_func=lambda q: "Demo-Daten (lokal)" if q == "demo" else "Microsoft 365 (Graph)")
        # Der Nutzer bestimmt, welcher Index durchsucht wird (ein Index pro Nutzer, siehe config.db_path)
        user = "demo" if quelle == "demo" else st.text_input("Angemeldeter Nutzer (UPN)", value="")
        ablage_nutzer = user
        # alle installierten Sprachmodelle; das Embedding-Modell kann keine Antworten schreiben
        modelle = [m.model for m in ollama.list().models if not m.model.startswith(config.EMBED_MODEL)]
        model = st.selectbox("Sprachmodell", modelle,
                             index=modelle.index(config.CHAT_MODEL) if config.CHAT_MODEL in modelle else 0)
        if st.button("Daten neu einlesen"):
            # Microsoft-Anmeldung per Code: Link und Code erscheinen im Terminal, in dem die App läuft
            with st.spinner("Lese Daten ein … (bei Microsoft 365 ggf. Anmeldecode im Terminal)"):
                unvollstaendig = ingest(quelle, nutzer=user if quelle == "graph" and user else None)
            if unvollstaendig:
                st.warning(f"Nicht vollständig gelesen, bisherige Daten bleiben erhalten: {', '.join(unvollstaendig)}")
            else:
                st.success("Index aktualisiert")
    wartet_auf_index = config.AUTO_EINLESEN and email and user != email  # noch kein eigener Index, siehe Hauptbereich
    if user and not wartet_auf_index:
        st.caption(f"Abschnitte im Index von **{user}**: {oeffne_collection(user).count()}")
    if st.button("Neues Gespräch"):  # Folgefragen beziehen sich sonst auf die bisherigen Runden
        st.session_state.verlauf = []
    # Persönliche Ablage: Ordner je Kunde/Thema, die mit jeder Frage wachsen (ablage.py)
    ablage_an = st.toggle("Antworten in Ablage einordnen", value=config.ABLAGE_AKTIV,
                          help=f"Ab der {config.ABLAGE_MIN_FRAGEN}. Frage zu einem Kunden oder Projekt entsteht dafür "
                               "ein Ordner mit allen Antworten und Quellen.")
    if ablage_nutzer and not config.SERVER_MODUS:
        st.caption(f"📁 Ablage: `{ablage.ablage_pfad(ablage_nutzer)}`")
    st.divider()
    ort = "auf dem Server des Projekts" if config.SERVER_MODUS else "lokal auf diesem Rechner"
    st.caption(f"Alle Daten und das Sprachmodell bleiben {ort}. "
               "Es werden nur Daten des angemeldeten Nutzers durchsucht.")

@st.cache_resource(show_spinner="Lade Sprachmodell …")
def modell_laden(name: str) -> bool:
    """Lädt das gewählte Modell vorab in den Grafikspeicher (dank Cache nur einmal pro Modell)."""
    agent.aufwaermen(name)  # einmal pro Modell, damit schon die erste Frage schnell ist
    return True


def einlese_status(email: str, war_aktiv: bool) -> None:
    """Zeigt den Stand des Einlesens. Läuft als Fragment: Solange ein Auftrag aktiv ist, alle 5 s nur dieser Teil der
    Seite neu, damit ein laufender Chat nicht gestört wird. Der Code erscheint nur hier, also nur bei diesem Nutzer."""
    auftrag = einlesen.auftrag(email)
    if not auftrag:
        return
    zustand = auftrag["zustand"]
    if war_aktiv and zustand not in einlesen.AKTIV:
        st.rerun()  # fertig oder Fehler: ganze Seite neu aufbauen, das beendet die Abfrage und gibt den Chat frei
    erstmalig = config.index_stand(email) is None
    if auftrag["code"]:
        st.info(f"**Bitte gib den Zugriff auf deine Microsoft-365-Daten frei.** Melde dich dort als **{email}** an, "
                "am besten in einem privaten Browserfenster. Der Code gilt etwa 15 Minuten.")
        st.link_button("Microsoft-Anmeldung öffnen", auftrag["link"])
        st.code(auftrag["code"], language=None)
    elif zustand == "wartet" and erstmalig:
        st.info("Anmeldung erfolgreich. Gerade werden die Daten einer anderen Person eingelesen, danach bist du dran.")
    elif zustand == "laeuft" and erstmalig:
        st.info("Deine Daten werden eingelesen. Das dauert etwa 10 Minuten, du kannst die Seite so lange schließen.")
    elif zustand in einlesen.AKTIV and erstmalig:
        st.info("Anmeldung wird vorbereitet …")
    elif zustand in einlesen.AKTIV:
        st.caption("🔄 Deine Daten werden im Hintergrund aktualisiert. Bis dahin gilt der bisherige Stand.")
    elif zustand == "fehler":
        if erstmalig:
            st.error(f"Einlesen fehlgeschlagen: {auftrag['meldung']}")
        else:
            st.warning(f"Einlesen fehlgeschlagen, der bisherige Stand bleibt erhalten: {auftrag['meldung']}")
    elif auftrag["unvollstaendig"]:
        st.warning(f"Nicht vollständig gelesen, bisherige Daten bleiben erhalten: {', '.join(auftrag['unvollstaendig'])}")
    if zustand == "fehler" or (zustand == "fertig" and auftrag["unvollstaendig"]):
        if st.button("Erneut einlesen"):
            einlesen.starte(email)
            st.rerun()


# --- 2. Hauptbereich ---------------------------------------------------------
modell_laden(model)
st.title("🔎 Informations-Agent Key-Account-Management")
st.caption("Durchsucht OneNote „MBS 2“, Teams und Outlook – jede Aussage mit Quelle.")

# Beim ersten Öffnen und danach regelmäßig einlesen (einlesen.py). Ohne fertigen Index keine Fragen: Antworten aus den
# Demo-Daten sähen sonst aus wie Antworten aus den eigenen Daten.
if config.AUTO_EINLESEN and email:
    if einlesen.noetig(email):
        einlesen.starte(email)
    letzter_auftrag = einlesen.auftrag(email)
    aktiv = bool(letzter_auftrag) and letzter_auftrag["zustand"] in einlesen.AKTIV
    st.fragment(einlese_status, run_every=5 if aktiv else None)(email, aktiv)
    if wartet_auf_index and config.index_stand(email) is None:
        st.stop()

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
    # bisherige Runden (Frage + Antwort) für Folgefragen wie "Und bis wann läuft der?".
    # Nur direkt aufeinanderfolgende Paare: Nach einem Fehler kann eine Frage ohne Antwort im Verlauf stehen.
    eintraege = st.session_state.verlauf
    runden = [{"frage": f["text"], "antwort": a["text"]} for f, a in zip(eintraege, eintraege[1:])
              if f["rolle"] == "user" and a["rolle"] == "assistant"]
    st.session_state.verlauf.append({"rolle": "user", "text": frage})
    with st.chat_message("user"):
        st.markdown(frage)

    # Dieselben Bausteine wie agent.antworte(), aber mit Zwischenständen und gestreamter Antwort
    with st.chat_message("assistant"):
        start = time.perf_counter()
        strom_start = strom.marke()
        hinweis = st.empty()
        schritte = agent.vorbereite(frage, user, model, runden, melde=hinweis.caption)  # Schritte 0-2
        hinweis.empty()
        verstanden, treffer = schritte["verstanden"], schritte["treffer"]
        widersprueche = schritte["widersprueche"]
        if verstanden != frage:
            st.caption(f"🔁 Verstanden als: *{verstanden}*")
        if schritte["varianten"]:
            st.caption("🔎 Zusätzlich gesucht nach: " + " · ".join(f"*{v}*" for v in schritte["varianten"]))
        antwort = st.write_stream(agent.generiere(verstanden, treffer, widersprueche, model))  # Schritt 3: Antwort
        quellen = agent.anhang_markdown(treffer, widersprueche, antwort, verstanden)  # Schritt 4: Anhang aus dem Code
        st.markdown(quellen)
        dauer = time.perf_counter() - start
        st.caption(f"⏱️ Antwort in {dauer:.1f} s · {len(treffer)} Quellen durchsucht")

        # Aufklappbare Originaltexte: Der Nutzer kann jede Aussage selbst an der Quelle nachprüfen
        for i, t in enumerate(treffer, start=1):
            with st.expander(f"[{i}] {t['meta']['quelle']} – {t['meta']['titel']} "
                             f"(Ähnlichkeit {t['aehnlichkeit']:.2f})"):
                st.text(t["text"])

        # Schritt 5: in die persönliche Ablage einordnen
        if ablage_an and treffer:
            with st.spinner("Ordne in die Ablage ein …"):
                abgelegt = agent.ablage_sicher(frage, treffer, antwort + quellen, ablage_nutzer, model, verstanden)
            symbol = {"abgelegt": "📁", "fehler": "⚠️"}.get(abgelegt["status"], "📝")
            st.caption(f"{symbol} {abgelegt['meldung']}")

        # Verbrauch erst hier: Auch die Ablage nutzt das Sprachmodell
        messung = strom.anfrage_beenden(strom_start)
        if messung:
            st.caption(strom.text_anfrage(messung))

    st.session_state.verlauf.append({"rolle": "assistant", "text": antwort + quellen})
elif frage:
    st.warning("Bitte zuerst den angemeldeten Nutzer angeben und die Daten einlesen.")

# Am Ende des Skripts, damit die Seitenleiste die gerade beantwortete Frage schon mitzählt
if uebersicht := strom.text_uebersicht():
    st.sidebar.divider()
    st.sidebar.caption(uebersicht)
