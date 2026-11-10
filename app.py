"""Streamlit-Oberfläche: Chat mit dem Informations-Agenten.

Start:  streamlit run app.py   (oder start_demo.bat)

Funktionsweise von Streamlit (wichtig zum Verständnis dieser Datei):
    Streamlit führt das GANZE Skript bei jeder Nutzeraktion (Klick, Eingabe) von oben nach unten neu aus.
    Was zwischen zwei Durchläufen erhalten bleiben soll (hier: der Chatverlauf), liegt in
    st.session_state. Teure Aktionen, die nur einmal passieren sollen (Modell laden), werden mit
    @st.cache_resource zwischengespeichert.

Aufbau der Seite:
    1. Seitenleiste:  Datenquelle, Nutzer, Sprachmodell, "Daten neu einlesen", "Neues Gespräch", Ablage an/aus;
                      im Serverbetrieb stattdessen das angemeldete Konto und "Abmelden / Konto wechseln"
    2. Hauptbereich:  Beispielfragen, bisheriger Chatverlauf, Eingabefeld
    Im Serverbetrieb davor: Stand des automatischen Einlesens mit dem Anmeldecode (einlesen.py)
    3. Bei einer Frage: die Bausteine des Agenten aufrufen und Zwischenstände anzeigen
       (verstanden als ..., zusätzlich gesucht nach ..., gestreamte Antwort, Quellen, Textauszüge).
       Wurde dieselbe Frage im Gespräch schon gestellt, verweist der Agent darauf und schlägt ähnliche Fragen vor
       (wiederholung.py); neu beantworten geht per Knopf.
       Enthält die Antwort Zahlen, bietet er eine Grafik an, die auf Wunsch erstellt wird (grafik.py).
    4. Danach (falls eingeschaltet): Frage und Antwort in die persönliche Ablage einordnen (ablage.py)
"""
import html
import time

import ollama
import streamlit as st

import ablage
import ablage_onedrive
import agent
import config
import einlesen
import grafik
import strom
import wiederholung
from ingest import ingest, oeffne_collection

st.set_page_config(page_title="KAM Informations-Agent", page_icon="🔎", layout="wide")
strom.starte()  # Strommessung im Hintergrund, läuft nur einmal je Serverprozess
ablage_onedrive.starte_aufraeumen()  # löscht Arbeitskopien der Ablage nach dem Ende einer Sitzung, einmal je Prozess

# Feste Fragen für die Präsentation (siehe Demo-Ablauf im README)
BEISPIELFRAGEN = [
    "Welche Konditionen gelten im Rahmenvertrag mit Hoffmann Maschinenbau und bis wann läuft er?",
    "Was haben wir 2019 mit NordWerk im Projekt Billbrook vereinbart?",
    "Wann findet die Bedarfsanalyse Hannover mit NordWerk statt?",
    "Welche Termine habe ich nächste Woche?",
]

def abmelden(email: str) -> None:
    """Knopf-Rückruf "Abmelden": Sitzung sofort beenden (die Arbeitskopie der Ablage wird beim nächsten Aufräumen
    gesichert und gelöscht) und den Verlauf leeren. Die Weiterleitung zu Cloudflare folgt im nächsten Durchlauf.
    Das Microsoft-Token für das Einlesen bleibt: Sonst müsste der Nutzer den Datenzugriff jedes Mal neu freigeben."""
    ablage_onedrive.sitzung_beenden(email)
    st.session_state.clear()
    st.session_state.abgemeldet = True


def weiterleitung_abmelden() -> None:
    """Seite zur Abmeldung von Cloudflare Access umleiten (config.ABMELDEN_URL) und hier nichts mehr ausführen.
    Weiterleitung per meta-refresh, dazu ein Link, falls der Browser sie blockiert."""
    ziel = html.escape(config.ABMELDEN_URL, quote=True)
    st.markdown(f'<meta http-equiv="refresh" content="0; url={ziel}">', unsafe_allow_html=True)
    st.info("Du wirst abgemeldet … Zum Anmelden mit einem anderen Konto danach die Seite neu öffnen und bei Microsoft "
            "„Anderes Konto verwenden“ wählen.")
    st.markdown(f'<a href="{ziel}" target="_self">Weiter zur Abmeldung</a>', unsafe_allow_html=True)
    st.stop()


if st.session_state.get("abgemeldet"):
    weiterleitung_abmelden()

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
        if email:
            st.button("🚪 Abmelden / Konto wechseln", on_click=abmelden, args=(email,), width="stretch",
                      help="Beendet die Anmeldung in dieser App. Danach kannst du dich mit einem anderen Konto anmelden.")
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
    if ablage_onedrive.aktiv(ablage_nutzer):
        # Lebenszeichen bei jedem Seitenaufbau und jede Minute, solange der Tab offen ist (nur dieser Teil läuft neu).
        # Bleibt es aus, gilt die Sitzung als beendet und die Arbeitskopie der Ablage wird gelöscht.
        st.fragment(ablage_onedrive.lebenszeichen, run_every=60)(ablage_nutzer)
        # Die Ablage gehört dem Nutzer: Sie liegt in seinem OneDrive, der Server hält nur eine Arbeitskopie
        abgleich = ablage_onedrive.status(ablage_nutzer)
        ordner = f"OneDrive / {config.ABLAGE_ONEDRIVE_ORDNER}"
        if abgleich and abgleich.get("link"):
            ordner = f"[{ordner}]({abgleich['link']})"
        st.caption(f"📁 Ablage: {ordner}")
        if abgleich and abgleich["zustand"] == "fehler":
            st.caption(f"⚠️ OneDrive-Abgleich fehlgeschlagen, wird bei der nächsten Ablage nachgeholt: "
                       f"{abgleich['meldung']}")
    elif ablage_nutzer and not config.SERVER_MODUS:
        st.caption(f"📁 Ablage: `{ablage.ablage_pfad(ablage_nutzer)}`")
    st.divider()
    ort = "auf dem Server des Projekts" if config.SERVER_MODUS else "lokal auf diesem Rechner"
    if ablage_onedrive.aktiv(ablage_nutzer):
        st.caption(f"Suchindex und Sprachmodell bleiben {ort}, die Ablage liegt in deinem OneDrive. "
                   "Es werden nur Daten des angemeldeten Nutzers durchsucht.")
    else:
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
        st.info("Deine Daten werden eingelesen. Das dauert meist ein bis zwei Minuten, du kannst die Seite so lange schließen.")
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


def frage_stellen(text: str, neu_beantworten: bool = False) -> None:
    """Knopf-Rückruf: Vorschlag oder 'Trotzdem neu beantworten' wird beim nächsten Durchlauf als Frage gestellt."""
    st.session_state.naechste_frage = text
    st.session_state.neu_beantworten = neu_beantworten


def zeige_extras(i: int, e: dict) -> None:
    """Knöpfe unter einer Antwort: ähnliche Fragen, neu beantworten, Grafik anbieten/erstellen/anzeigen.
    i = Position im Verlauf (eindeutige Schlüssel für Streamlit), e = Eintrag der Antwort."""
    if e.get("vorschlaege"):
        st.markdown("**Ähnliche Fragen** – zum Stellen anklicken:")
        for n, v in enumerate(e["vorschlaege"]):  # untereinander, damit lange Fragen lesbar bleiben
            st.button(f"💬 {v}", key=f"vorschlag_{i}_{n}", on_click=frage_stellen, args=(v,))
    if e.get("wiederholung"):
        st.button("🔄 Trotzdem neu beantworten", key=f"neu_{i}", on_click=frage_stellen, args=(e["frage"], True),
                  type="tertiary", help="Sucht erneut in den Quellen, z. B. wenn sich die Daten inzwischen geändert haben.")
    if not e.get("grafik_angebot"):
        return
    daten = e.get("grafik")
    if daten is None:
        # Angebot: Der Nutzer wählt die Darstellung und bestätigt; erst dann rechnet das Modell
        with st.container(border=True):
            st.markdown("📊 **Diese Antwort enthält Zahlen.** Soll ich sie als Grafik darstellen?")
            links, rechts = st.columns([3, 1])
            art = links.segmented_control("Darstellung", ["Automatisch", "Verlauf (Linie)", "Vergleich (Balken)"],
                                          default="Automatisch", key=f"grafik_art_{i}", label_visibility="collapsed")
            if rechts.button("Grafik erstellen", key=f"grafik_los_{i}", type="primary", width="stretch"):
                with st.spinner("Lese die Zahlen aus den Quellen …"):
                    e["grafik"] = grafik.erstelle(e["verstanden"], e["text"], e["treffer"], model)
                e["grafik_art"] = {"Verlauf (Linie)": "linie", "Vergleich (Balken)": "balken"}.get(art or "", "auto")
                st.rerun()
        return
    if daten["fehler"]:
        st.info(f"📊 {daten['fehler']} Es werden nur Zahlen gezeigt, die wörtlich in den Quellen stehen.")
        return
    dunkel = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
    st.altair_chart(grafik.diagramm(daten, e.get("grafik_art", "auto"), dunkel), width="stretch")
    st.caption(grafik.quellen_text(daten, e["treffer"]))
    with st.expander("Werte als Tabelle"):
        st.dataframe(grafik.tabelle(daten), hide_index=True, width="stretch")


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

# bisherigen Verlauf anzeigen (wird bei jedem Durchlauf neu gezeichnet), mit Vorschlägen und Grafik
for i, eintrag in enumerate(st.session_state.verlauf):
    with st.chat_message(eintrag["rolle"]):
        st.markdown(eintrag["text"])
        if eintrag["rolle"] == "assistant":
            zeige_extras(i, eintrag)

# --- 3. Neue Frage beantworten -----------------------------------------------
# getippte Frage, geklickte Beispielfrage oder ein angeklickter Vorschlag / "Trotzdem neu beantworten"
frage = st.chat_input("Ihre Frage …") or geklickt or st.session_state.pop("naechste_frage", None)
neu_beantworten = st.session_state.pop("neu_beantworten", False)
if frage and user:
    # bisherige Runden (Frage + Antwort) für Folgefragen wie "Und bis wann läuft der?".
    # Nur direkt aufeinanderfolgende Paare: Nach einem Fehler kann eine Frage ohne Antwort im Verlauf stehen.
    # Hinweise auf wiederholte Fragen sind keine Antworten und zählen nicht als Runde.
    eintraege = st.session_state.verlauf
    runden = [{"frage": f["text"], "antwort": a["text"]} for f, a in zip(eintraege, eintraege[1:])
              if f["rolle"] == "user" and a["rolle"] == "assistant" and not a.get("wiederholung")]
    frueher = None if neu_beantworten else wiederholung.finde_wiederholung(frage, eintraege)
    st.session_state.verlauf.append({"rolle": "user", "text": frage, "zeit": time.strftime("%H:%M"),
                                     "wiederholung": frueher is not None})
    with st.chat_message("user"):
        st.markdown(frage)

if frage and user and frueher is not None:
    # Schon gefragt: auf die frühere Antwort verweisen und ähnliche Fragen vorschlagen statt neu zu suchen
    with st.chat_message("assistant"):
        antwort_frueher = next((e for e in eintraege[frueher + 1:] if e["rolle"] == "assistant"), None)
        gestellt = [e["text"] for e in eintraege if e["rolle"] == "user"]
        with st.spinner("Suche ähnliche Fragen …"):
            vorschlaege = wiederholung.vorschlaege(frage, (antwort_frueher or {}).get("treffer", []), gestellt, model)
        nummer = sum(1 for e in eintraege[:frueher + 1] if e["rolle"] == "user" and not e.get("wiederholung"))
        # Vorschläge erscheinen als Knöpfe (zeige_extras), nicht zusätzlich als Liste im Text
        text = wiederholung.hinweis_markdown(eintraege[frueher]["text"], antwort_frueher, nummer,
                                             eintraege[frueher].get("zeit"), [])
        st.markdown(text)
        eintrag = {"rolle": "assistant", "text": text, "frage": frage, "wiederholung": True, "vorschlaege": vorschlaege}
        st.session_state.verlauf.append(eintrag)
        zeige_extras(len(st.session_state.verlauf) - 1, eintrag)
elif frage and user:
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
                try:
                    # Fehlt die Arbeitskopie auf dem Server, erst aus OneDrive holen: Eine neue, leere Ablage
                    # würde sonst beim Abgleich die alte im OneDrive überschreiben
                    if hinweis := ablage_onedrive.wiederherstellen_falls_noetig(ablage_nutzer):
                        st.caption(f"☁️ {hinweis}")
                    abgelegt = agent.ablage_sicher(frage, treffer, antwort + quellen, ablage_nutzer, model, verstanden)
                except Exception as e:
                    abgelegt = {"status": "fehler", "meldung": f"Nicht abgelegt: OneDrive nicht erreichbar ({e})"}
            if abgelegt["status"] in ("abgelegt", "vorgemerkt"):
                ablage_onedrive.anstossen(ablage_nutzer)  # im Hintergrund, die Antwort steht schon
            symbol = {"abgelegt": "📁", "fehler": "⚠️"}.get(abgelegt["status"], "📝")
            st.caption(f"{symbol} {abgelegt['meldung']}")

        # Verbrauch erst hier: Auch die Ablage nutzt das Sprachmodell
        messung = strom.anfrage_beenden(strom_start)
        if messung:
            st.caption(strom.text_anfrage(messung))

        # Grafik nur anbieten; erstellt wird sie erst nach Bestätigung (zeige_extras)
        eintrag = {"rolle": "assistant", "text": antwort + quellen, "frage": frage, "verstanden": verstanden,
                   "treffer": [{"text": t["text"], "meta": t["meta"]} for t in treffer],
                   "grafik_angebot": grafik.bietet_grafik(verstanden, antwort, treffer)}
        st.session_state.verlauf.append(eintrag)
        zeige_extras(len(st.session_state.verlauf) - 1, eintrag)
elif frage:
    st.warning("Bitte zuerst den angemeldeten Nutzer angeben und die Daten einlesen.")

# Am Ende des Skripts, damit die Seitenleiste die gerade beantwortete Frage schon mitzählt
if uebersicht := strom.text_uebersicht():
    st.sidebar.divider()
    st.sidebar.caption(uebersicht)
