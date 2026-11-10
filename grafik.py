"""Grafik zu Zahlen in einer Antwort: anbieten, auf Wunsch erstellen, mit Quellen belegen.

Ablauf (in app.py):
    1. bietet_grafik()  Der CODE erkennt Fragen bzw. Antworten mit Zahlen (Umsatz, Kosten, Preise, Rabatte …).
                        Dann bietet die App eine Grafik an; erstellt wird sie erst, wenn der Nutzer sie anfordert.
    2. erstelle()       Das Modell liest Antwort und Quellen und nennt die Datenpunkte als JSON (Reihe, x, Wert,
                        Quellennummer). Der CODE prüft jeden Punkt gegen die Originalquelle: Die Zahl muss dort
                        stehen, ebenso die Beschriftung (Jahr, Version, Datum …). Sonst wird der Punkt verworfen.
    3. diagramm()       Der CODE zeichnet: Linie für Verläufe (Jahre, Daten, Versionen), Balken für Vergleiche.

Gestaltung (geprüfte Palette, siehe Doku): feste Farbreihenfolge Blau, Orange, Türkis, Gelb (höchstens 4 Reihen),
eigene Stufen für den dunklen Modus, 2-px-Linien mit Punkten, schmale Balken mit abgerundetem Ende, dezentes
Raster, eine einzige y-Achse, Werte direkt beschriftet, Legende ab zwei Reihen, Tabelle und Quellen darunter.
Beschriftungen tragen nie die Reihenfarbe, sondern die Textfarbe.

Datenformat (JSON-fähig, liegt im Chatverlauf):
    {"titel", "einheit", "reihen": [{"name", "punkte": [{"x", "wert": float, "anzeige": "1,72", "quelle": n}]}],
     "verworfen": int, "fehler": str | None}
"""
import json
import re

import altair as alt
import ollama
import pandas as pd

import config
from zeitraum import MONATE

# Kategoriale Palette (validiert: Helligkeit, Sättigung, Farbsehschwäche, Kontrast), hell und dunkel getrennt gestuft
FARBEN_HELL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
FARBEN_DUNKEL = ["#3987e5", "#d95926", "#199e70", "#c98500"]
TEXT = {"hell": "#52514e", "dunkel": "#c3c2b7"}       # Beschriftungen (Textfarbe, nie Reihenfarbe)
RASTER = {"hell": "#e1e0d9", "dunkel": "#2c2c2a"}     # Haarlinien-Raster
MAX_REIHEN, MAX_PUNKTE = 4, 12

ZAHLWOERTER = re.compile(r"umsatz|kosten|preis|rabatt|volumen|menge|stück|anzahl|wie ?viel|wie hoch|entwicklung|"
                         r"verlauf|vergleich|prozent|euro|eur\b|budget|gutschrift|betrag|summe|kalkulation|"
                         r"bonus|skonto|zahlen|kennzahl|forecast|absatz|abruf", re.I)
EINHEIT_ZAHL = re.compile(r"\d[\d.,]*\s*(?:%|prozent|eur\b|euro|€|mio\.?|millionen|tsd\.?|stück|t eur)", re.I)

# Beispiel mit neutralen Namen (CLAUDE.md: keine Demo-Daten in Prompts)
DATEN_PROMPT = """Du bereitest Zahlen aus einer Antwort für ein Diagramm auf. Die Quellen sind nummeriert [1], [2], ...
Gib die Datenpunkte als JSON zurück:
{"titel": "kurzer Titel", "einheit": "z. B. %, EUR, Mio. EUR, Stück",
 "reihen": [{"name": "Name der Reihe", "punkte": [{"x": "Beschriftung", "wert": "Zahl wie in der Quelle", "quelle": n}]}]}
Regeln:
- Nur Zahlen, die wörtlich in den Quellen stehen, jeweils mit der Nummer dieser Quelle.
- "x" ist ein Jahr, Datum, Quartal, eine Version oder eine Kategorie (z. B. Produkt) – so wie in der Quelle.
- Alle Werte in EINER Einheit. Werte mit anderer Einheit weglassen.
- Höchstens 4 Reihen und 12 Punkte. Mehrere Reihen nur, wenn sie dieselbe Größe für verschiedene Dinge zeigen.
- Gibt es keine passenden Zahlen, antworte {"reihen": []}.

Beispiel: Antwort "Firma X: Rabatt im Angebot v1 6 % [1], in v2 7 % [2]." ->
{"titel": "Rabatt in den Angebotsversionen – Firma X", "einheit": "%",
 "reihen": [{"name": "Rabatt", "punkte": [{"x": "v1", "wert": "6", "quelle": 1}, {"x": "v2", "wert": "7", "quelle": 2}]}]}"""


# =============================================================================
# 1. Angebot erkennen (Code)
# =============================================================================

def _ohne_anhang(antwort: str) -> str:
    return re.split(r"\n#+ (?:Termine im Zeitraum|Widersprüche|Bitte prüfen|Quellen)\b", antwort)[0]


def bietet_grafik(frage: str, antwort: str, treffer: list[dict]) -> bool:
    """Grafik anbieten? Nur mit Quellen und mindestens zwei Zahlen in der Antwort, dazu eine Frage nach Zahlen
    oder mindestens drei Zahlen mit Einheit (%, EUR, Mio., Stück) in der Antwort."""
    if not treffer:
        return False
    text = _ohne_anhang(antwort)
    mit_einheit = len(EINHEIT_ZAHL.findall(text))
    zahlen = len(re.findall(r"\d+(?:[.,]\d+)?", re.sub(r"\[\d+\]", "", text)))
    return zahlen >= 2 and (bool(ZAHLWOERTER.search(frage)) or mit_einheit >= 3)


# =============================================================================
# 2. Daten erstellen (Modell nennt Punkte, Code prüft sie)
# =============================================================================

def zahl(text: str) -> float | None:
    """Deutsche Zahl -> float: '1,72' -> 1.72, '892.000' -> 892000, '8' -> 8, '3.9' -> 3.9. Sonst None."""
    t = str(text).strip().replace(" ", "").replace(" ", "").lstrip("+")
    t = re.sub(r"(%|eur|euro|€|mio\.?|stück|tsd\.?)$", "", t, flags=re.I)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):        # 892.000 / 1.250.000,50
        return float(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+,\d+", t):                           # 1,72
        return float(t.replace(",", "."))
    if re.fullmatch(r"-?\d+(\.\d+)?", t):                       # 8 / 3.9
        return float(t)
    return None


def anzeige(wert: float) -> str:
    """float -> deutsche Schreibweise ohne unnötige Nachkommastellen: 892000 -> '892.000', 1.72 -> '1,72'."""
    text = f"{wert:,.2f}".rstrip("0").rstrip(".") if wert != int(wert) else f"{int(wert):,}"
    return text.replace(",", "#").replace(".", ",").replace("#", ".")


def _zahlen_in(text: str) -> set[float]:
    gefunden = set()
    for z in re.findall(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?", text):
        w = zahl(z)
        if w is not None:
            gefunden.add(round(w, 6))
    return gefunden


def _x_belegt(x: str, text: str) -> bool:
    """Steht die Beschriftung in der Quelle? Zahlen darin (Jahr, Version, Datum) müssen alle vorkommen,
    sonst mindestens ein Wort ab 4 Buchstaben. 'v3' passt auch zu 'Version 3'."""
    klein = text.lower()
    ziffern = re.findall(r"\d+", x)
    if ziffern:
        return all(re.search(rf"(?<!\d){z}(?!\d)", klein) for z in ziffern)
    woerter = [w for w in re.findall(r"[a-zäöüß]{4,}", x.lower())]
    return bool(woerter) and any(w in klein for w in woerter)


def pruefe_daten(roh: dict, treffer: list[dict]) -> dict:
    """Behält nur belegte Punkte (Zahl UND Beschriftung in der genannten oder einer anderen Quelle)."""
    texte = [t["text"] + "\n" + t["meta"].get("titel", "") for t in treffer]
    reihen, verworfen = [], 0
    for r in (roh.get("reihen") or [])[:MAX_REIHEN]:
        punkte = []
        for p in (r.get("punkte") or [])[:MAX_PUNKTE]:
            wert, x = zahl(p.get("wert", "")), str(p.get("x", "")).strip()
            try:
                genannt = [int(p.get("quelle")) - 1]
            except (TypeError, ValueError):
                genannt = []
            reihenfolge = [i for i in genannt if 0 <= i < len(texte)] + list(range(len(texte)))
            beleg = next((i for i in reihenfolge if wert is not None and x
                          and round(wert, 6) in _zahlen_in(texte[i]) and _x_belegt(x, texte[i])), None)
            if beleg is None:
                verworfen += 1
                continue
            punkte.append({"x": x, "wert": wert, "anzeige": anzeige(wert), "quelle": beleg + 1})
        if punkte:
            reihen.append({"name": str(r.get("name") or "Wert").strip()[:40], "punkte": punkte})
    anzahl = sum(len(r["punkte"]) for r in reihen)
    return {"titel": str(roh.get("titel") or "Zahlen aus der Antwort").strip()[:90],
            "einheit": str(roh.get("einheit") or "").strip()[:20], "reihen": reihen, "verworfen": verworfen,
            "fehler": None if anzahl >= 2 else "Zu wenige belegbare Zahlen für eine Grafik gefunden."}


def erstelle(frage: str, antwort: str, treffer: list[dict], model: str = config.CHAT_MODEL) -> dict:
    """Schritt 2: Datenpunkte vom Modell holen und prüfen. Fehler -> Daten mit "fehler" (die App zeigt den Hinweis)."""
    quellen = "\n\n".join(f"[{i}] {t['meta']['quelle']} – {t['meta']['titel']}\n{t['text'][:700]}"
                          for i, t in enumerate(treffer, start=1))
    try:
        ergebnis = ollama.chat(model=model, format="json", keep_alive=config.KEEP_ALIVE,
                               options={"temperature": 0, "num_ctx": config.NUM_CTX},
                               messages=[{"role": "system", "content": DATEN_PROMPT},
                                         {"role": "user", "content": f"Frage: {frage}\n\nAntwort:\n{_ohne_anhang(antwort)}"
                                                                     f"\n\nQuellen:\n{quellen}"}])
        roh = json.loads(ergebnis.message.content)
        if not isinstance(roh, dict):
            raise ValueError("kein JSON-Objekt")
    except Exception as e:
        return {"titel": "", "einheit": "", "reihen": [], "verworfen": 0, "fehler": f"Grafik nicht möglich ({e})."}
    return pruefe_daten(roh, treffer)


# =============================================================================
# 3. Zeichnen (Code)
# =============================================================================

def _ordnung(x: str) -> tuple | None:
    """Sortierschlüssel für Verläufe: Datum, Monat Jahr, Quartal, Jahr, Version. None = Kategorie (keine Reihenfolge)."""
    s = x.lower().strip()
    if m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s):
        return (int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        return (int(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"q([1-4])\s*/?\s*(\d{4})", s) or re.fullmatch(r"(\d{4})\s*/?\s*q([1-4])", s):
        a, b = int(m[1]), int(m[2])
        return (b, a * 3, 0) if a <= 4 else (a, b * 3, 0)
    if m := re.fullmatch(rf"({'|'.join(MONATE)})\s*(\d{{4}})", s):
        return (int(m[2]), MONATE.index(m[1]) + 1, 0)
    if m := re.fullmatch(r"(\d{4})", s):
        return (int(m[1]), 0, 0)
    if m := re.fullmatch(r"(?:v|version|angebot v|stand v)\s*(\d+)", s):
        return (0, int(m[1]), 0)
    return None


def ist_verlauf(daten: dict) -> bool:
    """Alle Beschriftungen haben eine Reihenfolge (Zeit oder Version) -> Verlauf."""
    xs = [p["x"] for r in daten["reihen"] for p in r["punkte"]]
    return bool(xs) and all(_ordnung(x) is not None for x in xs)


def empfohlene_art(daten: dict) -> str:
    """Linie für Verläufe mit mindestens drei Zeitpunkten, sonst Balken."""
    xs = {p["x"] for r in daten["reihen"] for p in r["punkte"]}
    return "linie" if ist_verlauf(daten) and len(xs) >= 3 else "balken"


def tabelle(daten: dict) -> pd.DataFrame:
    zeilen = [{"Reihe": r["name"], "Beschriftung": p["x"], "Wert": p["anzeige"] + (f" {daten['einheit']}" if daten["einheit"] else ""),
               "Quelle": f"[{p['quelle']}]"} for r in daten["reihen"] for p in r["punkte"]]
    return pd.DataFrame(zeilen)


def diagramm(daten: dict, art: str = "auto", dunkel: bool = False, breite: int | str = "container") -> alt.Chart:
    """Altair-Diagramm. art: "linie", "balken" oder "auto" (empfohlene_art). breite: Pixel oder volle Breite."""
    art = empfohlene_art(daten) if art == "auto" else art
    modus = "dunkel" if dunkel else "hell"
    farben = (FARBEN_DUNKEL if dunkel else FARBEN_HELL)[:len(daten["reihen"])]
    einheit = daten["einheit"]
    zeilen = [{"x": p["x"], "wert": p["wert"], "reihe": r["name"], "quelle": f"Quelle [{p['quelle']}]",
               "beschriftung": p["anzeige"] + (" %" if einheit == "%" else ""),
               "tipp": f"{p['anzeige']} {einheit}".strip()}
              for r in daten["reihen"] for p in r["punkte"]]
    df = pd.DataFrame(zeilen)
    xs = list(dict.fromkeys(df["x"]))
    if ist_verlauf(daten):
        xs.sort(key=_ordnung)
    mehrere = len(daten["reihen"]) > 1
    # Reihenfolge der Farben folgt der Reihe, nicht ihrem Rang (feste Zuordnung über domain)
    farbe = alt.Color("reihe:N", title=None, sort=[r["name"] for r in daten["reihen"]],
                      scale=alt.Scale(domain=[r["name"] for r in daten["reihen"]], range=farben),
                      legend=alt.Legend(orient="top", labelColor=TEXT[modus], labelFontSize=13, symbolSize=120)
                      if mehrere else None)
    # y-Achse in deutscher Schreibweise (1.234,5); eine einzige Achse, Titel = Einheit
    deutsch = ("replace(replace(replace(format(datum.value, ',.4~f'), regexp(',', 'g'), '#'), "
               "regexp('[.]', 'g'), ','), regexp('#', 'g'), '.')")
    y = alt.Y("wert:Q", title=einheit or None, scale=alt.Scale(zero=art == "balken", nice=True),
              axis=alt.Axis(labelExpr=deutsch, gridColor=RASTER[modus], gridWidth=1, domain=False, tickCount=5,
                            labelColor=TEXT[modus], titleColor=TEXT[modus], labelFontSize=12, titleFontSize=12))
    x = alt.X("x:N", title=None, sort=xs, axis=alt.Axis(labelAngle=0, labelColor=TEXT[modus], domainColor=RASTER[modus],
                                                       ticks=False, grid=False, labelLimit=140, labelPadding=6,
                                                       labelFontSize=12))
    tooltip = [alt.Tooltip("reihe:N", title="Reihe"), alt.Tooltip("x:N", title="Wann/Was"),
               alt.Tooltip("tipp:N", title="Wert"), alt.Tooltip("quelle:N", title="Beleg")]
    basis = alt.Chart(df).encode(x=x, y=y)

    if art == "linie":
        linie = basis.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round").encode(color=farbe)
        # Punkte >= 8 px mit Ring in Hintergrundfarbe, damit sie sich an Kreuzungen abheben; großer Hover-Bereich
        punkte = basis.mark_point(filled=True, size=90, strokeWidth=2,
                                  stroke="#1a1a19" if dunkel else "#fcfcfb", opacity=1).encode(color=farbe, tooltip=tooltip)
        # Direkte Beschriftung: nur der letzte Wert jeder Reihe und das Maximum (nie jeder Punkt)
        letzte = df.assign(_o=df["x"].map(xs.index)).sort_values("_o").groupby("reihe").tail(1)
        hoechste = df.loc[df.groupby("reihe")["wert"].idxmax()]
        markiert = pd.concat([letzte, hoechste]).drop_duplicates(subset=["reihe", "x"])
        text = alt.Chart(markiert).mark_text(dy=-14, fontSize=13, fontWeight="bold", color=TEXT[modus]).encode(
            x=x, y=y, text="beschriftung:N")
        chart = linie + punkte + text
    else:
        # Balken schmal (<= 24 px) mit 2 px Luft; bei mehreren Reihen nebeneinander (xOffset). Die Wertebeschriftung
        # ist eine eigene Ebene mit denselben Kodierungen, sonst verrutscht sie gegenüber den gruppierten Balken.
        gruppe = alt.XOffset("reihe:N", sort=[r["name"] for r in daten["reihen"]],
                             scale=alt.Scale(paddingInner=0.08)) if mehrere else None
        kodierung = {"x": x, "y": y, **({"xOffset": gruppe} if mehrere else {})}
        balkenbreite = 22 if not mehrere else max(10, 22 - 3 * len(daten["reihen"]))
        balken = alt.Chart(df).mark_bar(size=balkenbreite, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            color=farbe, tooltip=tooltip, **kodierung)
        text = alt.Chart(df).mark_text(dy=-9, fontSize=13, color=TEXT[modus]).encode(text="beschriftung:N", **kodierung)
        chart = alt.layer(balken, text)

    return chart.properties(height=340, width=breite, title=alt.TitleParams(daten["titel"], anchor="start", fontSize=16,
                                                              color="#f0efec" if dunkel else "#0b0b0b")
                            ).configure_view(strokeWidth=0, stroke=None)


def quellen_text(daten: dict, treffer: list[dict]) -> str:
    """Belegzeile unter der Grafik: welche Quelle welche Punkte liefert."""
    nummern = sorted({p["quelle"] for r in daten["reihen"] for p in r["punkte"]})
    teile = [f"[{n}] {treffer[n - 1]['meta']['quelle']} – {treffer[n - 1]['meta']['titel']}" for n in nummern
             if 0 < n <= len(treffer)]
    hinweis = f" · {daten['verworfen']} Wert(e) ohne Beleg weggelassen" if daten.get("verworfen") else ""
    return "Belege: " + "; ".join(teile) + hinweis
