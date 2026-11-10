"""Erzeugt aus kunden.py alle Testdaten für den Tenant KAMPilot: Dateien + plan.json je Nutzer.

Ausgabe (nicht im Repository, wird bei jedem Lauf identisch neu erzeugt):
    demo_tenant/ausgabe/
    ├─ dateien/<nutzer>/OneDrive/...      bewusst unordentliche Kundenordner der Nutzer
    ├─ dateien/_teams/<Kanal>/...         offizielle Ablage im Team "KAM-Pilot" (teils Duplikate)
    ├─ plan.json                          was seed_tenant.py bei welchem Nutzer anlegt
    └─ UEBERSICHT.md                      lesbare Zusammenfassung zur Freigabe

Realismus (absichtlich, damit der Agent wie im echten Leben gefordert ist):
    - Angebote in v1, v2, v3 mit unterschiedlichen Rabatten; v3 doppelt ("(1)", "final_neu")
    - Vertragsentwurf mit alten Konditionen neben dem unterschriebenen Vertrag
    - uneinheitliche Ordnernamen, lose Dateien in "Desktop-Ablage" und "Downloads"
    - dieselbe Mail als .eml im Ordner UND im Postfach; Excel/PowerPoint als Beiwerk (liest der Agent nicht)
    - gemeinsame Kunden mit abweichenden Angaben zwischen Nutzern (z. B. Übergabe Kessler)

Aufruf:  python demo_tenant/erzeuge.py
"""
import json
import random
import shutil
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from kunden import FIRMA, HEUTE, NUTZER, PRODUKTE, alle_kunden

AUSGABE = Path(__file__).parent / "ausgabe"
DATEIEN = AUSGABE / "dateien"


# =============================================================================
# Formatierung
# =============================================================================

def d(tag: date) -> str:
    return tag.strftime("%d.%m.%Y")


def pz(wert: float) -> str:
    """Prozentzahl mit deutschem Komma: 3.9 -> '3,9'."""
    return f"{wert:.1f}".replace(".", ",")


def eur(betrag: float) -> str:
    return f"{betrag:,.0f}".replace(",", ".") + " EUR"


def werktag(tag: date) -> date:
    while tag.weekday() >= 5:
        tag += timedelta(days=1)
    return tag


def person(schluessel: str) -> str:
    return NUTZER[schluessel]["name"]


def signatur(schluessel: str) -> str:
    n = NUTZER[schluessel]
    return f"Viele Grüße\n{n['name']}\n{n['rolle']}\n{FIRMA}\n{n['upn'].lower()}"


# =============================================================================
# Datei-Schreiber
# =============================================================================

def schreibe_docx(pfad: Path, titel: str, absaetze: list[str], tabelle: list[list[str]] | None = None) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading(titel, level=1)
    for a in absaetze:
        doc.add_paragraph(a)
    if tabelle:
        t = doc.add_table(rows=0, cols=len(tabelle[0]))
        t.style = "Table Grid"
        for zeile in tabelle:
            zellen = t.add_row().cells
            for z, wert in zip(zellen, zeile):
                z.text = wert
    doc.save(pfad)


def schreibe_pdf(pfad: Path, titel: str, absaetze: list[str], tabelle: list[list[str]] | None = None) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    stil = getSampleStyleSheet()
    teile = [Paragraph(titel, stil["Title"])]
    for a in absaetze:
        teile += [Paragraph(a.replace("&", "&amp;").replace("\n", "<br/>"), stil["BodyText"]), Spacer(1, 6)]
    if tabelle:
        teile.append(Table(tabelle))
    SimpleDocTemplate(str(pfad), pagesize=A4, title=titel).build(teile)


def schreibe_eml(pfad: Path, von: str, an: str, betreff: str, datum: date, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = von, an, betreff
    m["Date"] = format_datetime(datetime(datum.year, datum.month, datum.day, 10, 14))
    m.set_content(text)
    pfad.write_bytes(bytes(m))


def schreibe_xlsx(pfad: Path, zeilen: list[list]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    for z in zeilen:
        wb.active.append(z)
    wb.save(pfad)


def schreibe_pptx(pfad: Path, titel: str, punkte: list[str]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    p = Presentation()
    folie = p.slides.add_slide(p.slide_layouts[1])
    folie.shapes.title.text = titel
    folie.placeholders[1].text = "\n".join(punkte)
    p.save(pfad)


# =============================================================================
# Plan (was bei welchem Nutzer angelegt wird)
# =============================================================================

PLAN = {k: {"onenote": [], "inbox": [], "gesendet": [], "termine": [], "onedrive": [], "kanal_posts": [],
            "kanal_dateien": [], "chats": []} for k in NUTZER}


def onenote(nutzer: str, abschnitt: str, seite: str, datum: date, text: str) -> None:
    PLAN[nutzer]["onenote"].append({"abschnitt": abschnitt, "seite": seite, "datum": datum.isoformat(), "text": text})


def mail_extern(nutzer: str, von_name: str, von_mail: str, betreff: str, datum: date, text: str) -> None:
    PLAN[nutzer]["inbox"].append({"betreff": betreff, "von_name": von_name, "von_mail": von_mail,
                                  "datum": datum.isoformat(), "text": text})


def mail_intern(von: str, an: list[str], betreff: str, datum: date, text: str) -> None:
    """Interne Mail: liegt beim Absender in 'Gesendet' und bei jedem Empfänger im Posteingang."""
    eintrag = {"betreff": betreff, "von_name": person(von), "von_mail": NUTZER[von]["upn"],
               "an": [NUTZER[a]["upn"] for a in an], "datum": datum.isoformat(), "text": text}
    PLAN[von]["gesendet"].append(eintrag)
    for a in an:
        PLAN[a]["inbox"].append(eintrag)


def termin(organisator: str, teilnehmer: list[str], betreff: str, tag: date, von: str, bis: str, ort: str,
           text: str) -> None:
    PLAN[organisator]["termine"].append({"betreff": betreff, "tag": tag.isoformat(), "von": von, "bis": bis,
                                         "ort": ort, "teilnehmer": [NUTZER[t]["upn"] for t in teilnehmer
                                                                    if t != organisator], "text": text})


def post(nutzer: str, kanal: str, datum: date, text: str) -> None:
    PLAN[nutzer]["kanal_posts"].append({"kanal": kanal, "datum": datum.isoformat(), "text": text})


def chat(von: str, an: str, datum: date, text: str) -> None:
    PLAN[von]["chats"].append({"mit": NUTZER[an]["upn"], "datum": datum.isoformat(), "text": text})


def ablegen(nutzer: str, pfad: Path, ziel: str) -> None:
    """Datei für den OneDrive des Nutzers vormerken (ziel = Pfad im OneDrive)."""
    PLAN[nutzer]["onedrive"].append({"datei": str(pfad.relative_to(AUSGABE)), "ziel": ziel})


def teams_ablage(nutzer: str, kanal: str, quelle: Path, name: str) -> None:
    ziel = DATEIEN / "_teams" / kanal / name
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(quelle, ziel)
    PLAN[nutzer]["kanal_dateien"].append({"kanal": kanal, "datei": str(ziel.relative_to(AUSGABE)), "name": name})


# =============================================================================
# Inhalte je Kunde
# =============================================================================

def ordnerstil(k: dict, r: random.Random) -> dict:
    """Jeder Kundenordner ist anders unordentlich."""
    basis = r.choice([f"Kunden/{k['kurz']}", f"Kunden/{k['kurz'].upper()}", f"Kunden/{k['name']}",
                      f"Kunden/{k['kurz']}_neu", f"01_Kunden/{k['kurz']}"])
    return {"basis": basis,
            "angebote": r.choice([f"{basis}/Angebote", f"{basis}/Angebote 2026", f"{basis}/Preise", basis]),
            "alt": r.choice([f"{basis}/Angebote/alt", f"{basis}/_alt", f"{basis}/alt (nicht löschen)", basis]),
            "vertrag": r.choice([f"{basis}/Verträge", f"{basis}/Vertrag", f"{basis}/RV", basis]),
            "mails": r.choice([f"{basis}/Mails", f"{basis}/Korrespondenz", basis]),
            "lose": r.choice(["Desktop-Ablage", "Downloads", "Neuer Ordner", f"{basis}/sonstiges"])}


def angebot_text(k: dict, v: dict) -> tuple[str, list[str], list[list[str]]]:
    vh = k["verhandlung"]
    titel = f"Angebot {vh['angebot']} – Version {v['version']}"
    absaetze = [
        f"{k['name']}\nz. Hd. {k['kontakte'][0]['name']} ({k['kontakte'][0]['rolle']})\n{k['ort']}",
        f"Datum: {d(v['datum'])}\nIhr Ansprechpartner: {person(k['kam'])}",
        f"Sehr geehrte Damen und Herren,\nwir bedanken uns für Ihre Anfrage zur Belieferung im Jahr 2027 und bieten "
        f"Ihnen auf Basis des Rahmenvertrags {k['vertrag']['nr']} wie folgt an:",
        f"Listenpreiserhöhung zum 01.01.2027: {pz(v['preiserhoehung'])} %.\n"
        f"Rabatt auf Listenpreis: {v['rabatt']} % (bisher {k['vertrag']['rabatt']} % laut {k['vertrag']['nr']}).\n"
        f"Geschätztes Jahresvolumen: {eur(vh['volumen'])}.",
        f"Zahlungsbedingungen: {k['vertrag']['zahlungsziel']} Tage netto, {k['vertrag']['skonto']} % Skonto "
        f"bei Zahlung innerhalb 10 Tagen.\nGültigkeit des Angebots: 6 Wochen ab Angebotsdatum.",
        f"Mit freundlichen Grüßen\n{person(k['kam'])}\n{FIRMA}"]
    tabelle = [["Pos.", "Produkt", "Rabatt", "Preisanpassung 2027"]]
    for i, p in enumerate(k["produkte"], start=1):
        tabelle.append([str(i), PRODUKTE[p], f"{v['rabatt']} %", f"+{pz(v['preiserhoehung'])} %"])
    return titel, absaetze, tabelle


def kunde_erzeugen(k: dict) -> list[str]:
    """Alle Inhalte eines Kunden. Rückgabe: Liste der OneDrive-Dateien (für die Übersicht)."""
    r = random.Random(f"dateien-{k['kurz']}")
    kam, vh, vt = k["kam"], k["verhandlung"], k["vertrag"]
    o = ordnerstil(k, r)
    ein = k["kontakte"][0]
    roh = DATEIEN / kam / "OneDrive"
    dateien = []

    def lege(rel_ordner: str, name: str) -> Path:
        pfad = roh / rel_ordner / name
        pfad.parent.mkdir(parents=True, exist_ok=True)
        ablegen(kam, pfad, f"{rel_ordner}/{name}")
        dateien.append(f"{rel_ordner}/{name}")
        return pfad

    v1, v2, v3 = vh["versionen"]

    # --- 1. Kundenprofil (teils veraltet) ---
    profil = lege(o["basis"], r.choice([f"Kundenprofil {k['kurz']}.docx", f"{k['kurz']} Steckbrief (alt).docx",
                                        f"Profil_{k['kurz'].replace(' ', '_')}_2024.docx"]))
    schreibe_docx(profil, f"Kundenprofil {k['name']}", [
        f"Kundennummer: {k['kundennummer']} · Kunde seit {k['kunde_seit']} · Branche: {k['branche']} · Sitz: {k['ort']}",
        f"Umsatz 2025: ca. {k['umsatz_2025']:.2f} Mio. EUR. Produkte: {', '.join(PRODUKTE[p] for p in k['produkte'])}.",
        f"Verantwortlich bei {FIRMA}: {person(kam)}"
        + (f", weitere Ansprechpartner intern: {', '.join(person(t) for t in k['team'])}." if k["team"] else "."),
        "Ansprechpartner beim Kunden:"],
        [["Name", "Funktion", "E-Mail", "Telefon"]] + [[c["name"], c["rolle"], c["mail"], c["tel"]] for c in k["kontakte"]])

    # --- 2.-5. Angebote v1, v2, v3 + Duplikate ---
    t, a, tab = angebot_text(k, v1)
    schreibe_docx(lege(o["alt"], f"{vh['angebot']}_{k['kurz'].replace(' ', '_')}_v1.docx"), t, a, tab)
    t, a, tab = angebot_text(k, v2)
    schreibe_docx(lege(o["angebote"], f"{vh['angebot']}_{k['kurz'].replace(' ', '_')}_v2_überarbeitet.docx"), t, a, tab)
    t, a, tab = angebot_text(k, v3)
    v3_pdf = lege(o["angebote"], f"{vh['angebot']}_{k['kurz'].replace(' ', '_')}_v3_FINAL.pdf")
    schreibe_pdf(v3_pdf, t, a, tab)
    dup_name = r.choice([f"{vh['angebot']}_{k['kurz'].replace(' ', '_')}_v3_FINAL (1).pdf",
                         f"Angebot {k['kurz']} final_neu.pdf", f"Kopie von {vh['angebot']}_v3_FINAL.pdf"])
    shutil.copy2(v3_pdf, lege(o["lose"], dup_name))

    # --- 6. Kalkulation (Excel, liest der Agent nicht – Beiwerk wie im echten Ordner) ---
    schreibe_xlsx(lege(o["angebote"], f"Kalkulation {k['kurz']} 2027.xlsx"),
                  [["Version", "Datum", "Rabatt %", "Preiserhöhung %", "Volumen EUR"]]
                  + [[x["version"], d(x["datum"]), x["rabatt"], x["preiserhoehung"], vh["volumen"]] for x in vh["versionen"]])

    # --- 7.-9. Mails des Kunden zur Verhandlung (als .eml im Ordner UND im Postfach) ---
    von = f"{ein['name']} <{ein['mail']}>"
    mails = [
        (v1["datum"] + timedelta(days=r.randint(4, 9)), f"AW: Angebot {vh['angebot']}",
         f"Guten Tag {person(kam).split()[0]} {person(kam).split()[1]},\n\nvielen Dank für Ihr Angebot. Eine "
         f"Preiserhöhung von {pz(v1['preiserhoehung'])} % können wir für 2027 nicht akzeptieren. Wettbewerber liegen "
         f"deutlich darunter. Bitte prüfen Sie Rabatt und Erhöhung noch einmal.\n\nMit freundlichen Grüßen\n{ein['name']}\n"
         f"{ein['rolle']}, {k['name']}"),
        (v2["datum"] + timedelta(days=r.randint(3, 8)), f"AW: AW: Angebot {vh['angebot']} – Version 2",
         f"Hallo {person(kam).split()[0]},\n\ndie Version 2 geht in die richtige Richtung. Unser Vorschlag: "
         f"{v2['rabatt'] + 1} % Rabatt und maximal {pz(v3['preiserhoehung'])} % Preiserhöhung, dann können wir "
         f"das Volumen von {eur(vh['volumen'])} für 2027 zusagen.\n\nGruß\n{ein['name']}"),
        (v3["datum"] + timedelta(days=r.randint(2, 6)), f"Angebot {vh['angebot']} v3 – Rückmeldung",
         (f"Hallo {person(kam).split()[0]},\n\nwir nehmen Version 3 an: {v3['rabatt']} % Rabatt, Preisanpassung "
          f"{pz(v3['preiserhoehung'])} % zum 01.01.2027. Die Bestellung für Q1 folgt bis Ende November.\n\nGruß\n{ein['name']}")
         if v3["status"] == "angenommen" else
         (f"Hallo {person(kam).split()[0]},\n\nzu Version 3 ({v3['rabatt']} % Rabatt, {pz(v3['preiserhoehung'])} %) "
          f"brauchen wir noch eine interne Freigabe unserer Geschäftsführung. Rückmeldung voraussichtlich in KW 48.\n\n"
          f"Gruß\n{ein['name']}")),
    ]
    for datum, betreff, text in mails:
        datum = werktag(datum)
        mail_extern(kam, ein["name"], ein["mail"], betreff, datum, text)
        if r.random() < 0.75:  # nicht jede Mail wird im Ordner abgelegt – wie im echten Leben
            schreibe_eml(lege(o["mails"], f"{betreff.replace(':', '').replace('/', '-')}.eml"),
                         von, NUTZER[kam]["upn"], betreff, datum, text)

    # --- 10.-11. Rahmenvertrag unterschrieben + alter Entwurf mit anderen Konditionen ---
    vertrag_pdf = lege(o["vertrag"], f"{vt['nr']}_{k['kurz'].replace(' ', '_')}_unterschrieben.pdf")
    schreibe_pdf(vertrag_pdf, f"Rahmenvertrag {vt['nr']}", [
        f"zwischen {FIRMA} und {k['name']}, {k['ort']}",
        f"Laufzeit: {d(vt['beginn'])} bis {d(vt['ende'])}",
        f"Rabatt: {vt['rabatt']} % auf den jeweils gültigen Listenpreis für {', '.join(PRODUKTE[p] for p in k['produkte'])}",
        f"Zahlungsziel: {vt['zahlungsziel']} Tage netto, {vt['skonto']} % Skonto bei Zahlung innerhalb 10 Tagen",
        f"Kündigungsfrist: {vt['kuendigung_monate']} Monate zum Laufzeitende",
        "Preisanpassung: jährlich zum 01.01., Ankündigung mindestens 8 Wochen vorher",
        f"Unterzeichnet am {d(vt['beginn'] - timedelta(days=12))} von {vt['unterzeichnet']} ({k['name']}) und "
        f"{person('heinrich')} ({FIRMA})"])
    ent = k["vertrag_entwurf"]
    schreibe_docx(lege(o["alt"] if r.random() < 0.6 else o["vertrag"],
                       f"{vt['nr']}_Entwurf_v{r.choice([2, 3])}.docx"), f"ENTWURF Rahmenvertrag {vt['nr']}", [
        f"Stand: {d(ent['datum'])} – NICHT UNTERSCHRIEBEN",
        f"Laufzeit: {d(vt['beginn'])} bis {d(vt['ende'])}",
        f"Rabatt: {ent['rabatt']} % auf Listenpreis",
        f"Zahlungsziel: {ent['zahlungsziel']} Tage netto",
        f"Kündigungsfrist: {vt['kuendigung_monate']} Monate zum Laufzeitende",
        "Anmerkung Einkauf: Rabatt und Zahlungsziel noch offen, siehe Mail."])

    # --- 12. lose Telefonnotiz ---
    notiz_tag = werktag(v2["datum"] + timedelta(days=r.randint(10, 15)))
    notiz = lege(o["basis"] if r.random() < 0.5 else o["lose"],
                 r.choice([f"notiz telefonat {notiz_tag.day}.{notiz_tag.month}.txt", f"tel {k['kurz'].lower()}.txt",
                           f"Notizen {k['kurz']}.txt"]))
    notiz.parent.mkdir(parents=True, exist_ok=True)
    notiz.write_text(
        f"telefonat mit {ein['name'].split()[-1]} am {d(notiz_tag)}\n"
        f"- will {v2['rabatt'] + 1}% rabatt, sonst wechsel zu wettbewerb im gespräch\n"
        f"- volumen 2027 ca {vh['volumen'] // 1000}t eur\n"
        f"- {r.choice(['zahlungsziel bleibt', 'skonto egal', 'liefertreue wichtiger als preis'])}\n"
        f"- rückruf bis {d(werktag(notiz_tag + timedelta(days=7)))}\n", encoding="utf-8")

    # --- Geschichten ---
    for g in k["geschichte"]:
        dateien += geschichte(k, g, o, r, lege)

    # --- OneNote des KAM ---
    onenote(kam, k["name"], f"Kundenprofil {k['name']}", vt["beginn"] - timedelta(days=30),
            f"Kunde: {k['name']}, {k['ort']} ({k['branche']})\nKundennummer: {k['kundennummer']}\nKunde seit {k['kunde_seit']}\n\n"
            "Ansprechpartner:\n" + "\n".join(f"- {c['name']}, {c['rolle']}, {c['mail']}, Tel. {c['tel']}" for c in k["kontakte"])
            + f"\n\nRahmenvertrag {vt['nr']}: {d(vt['beginn'])} bis {d(vt['ende'])}, Rabatt {vt['rabatt']} %, "
            f"Zahlungsziel {vt['zahlungsziel']} Tage netto, Kündigungsfrist {vt['kuendigung_monate']} Monate.\n"
            f"Ablage Vertrag: OneDrive > {o['vertrag']}")
    onenote(kam, k["name"], "Preisverhandlung 2027", v3["datum"],
            f"Angebot {vh['angebot']}, Volumen ca. {eur(vh['volumen'])}\n"
            + "\n".join(f"- v{x['version']} vom {d(x['datum'])}: {x['rabatt']} % Rabatt, +{pz(x['preiserhoehung'])} % – {x['status']}"
                        for x in vh["versionen"])
            + f"\n\nStand {d(v3['datum'])}: Version 3 {'angenommen' if v3['status'] == 'angenommen' else 'noch offen, Kunde wartet auf GF-Freigabe'}.")

    # --- Teams-Kanal: offizielle Ablage (teilweise dieselben Dateien) + Nachrichten ---
    kanal = k["kurz"]
    teams_ablage(kam, kanal, vertrag_pdf, vertrag_pdf.name)
    if r.random() < 0.7:
        teams_ablage(kam, kanal, v3_pdf, v3_pdf.name)
    post(kam, kanal, werktag(v1["datum"]), f"Preisrunde 2027 für {k['kurz']} gestartet: Angebot {vh['angebot']} v1 ist raus "
         f"({v1['rabatt']} % Rabatt, +{pz(v1['preiserhoehung'])} %).")
    post(kam, kanal, werktag(v3["datum"] + timedelta(days=7)),
         f"Update {k['kurz']}: v3 mit {v3['rabatt']} % Rabatt und +{pz(v3['preiserhoehung'])} % – Status: {v3['status']}.")

    # --- Zusammenarbeit mit dem Innendienst ---
    if "sally" in k["team"]:
        mail_intern(kam, ["sally"], f"Angebot {vh['angebot']} v2 für {k['kurz']} anlegen", werktag(v2["datum"] - timedelta(days=2)),
                    f"Hallo Sally,\n\nbitte lege für {k['name']} die Version 2 von {vh['angebot']} an: {v2['rabatt']} % Rabatt, "
                    f"+{pz(v2['preiserhoehung'])} % Preisanpassung, Volumen {eur(vh['volumen'])}.\n\n" + signatur(kam))
        mail_intern("sally", [kam], f"AW: Angebot {vh['angebot']} v2 für {k['kurz']} anlegen", werktag(v2["datum"]),
                    f"Hallo {person(kam).split()[0]},\n\nist angelegt und an {ein['name']} raus. PDF liegt im Kanal "
                    f"{kanal}.\n\n" + signatur("sally"))
        onenote("sally", "Auftragsabwicklung", f"{k['kurz']} – Angebote 2027", v2["datum"],
                f"{vh['angebot']} für {k['name']} (KAM {person(kam)})\n- v1 {d(v1['datum'])}\n- v2 {d(v2['datum'])} angelegt "
                f"nach Mail von {person(kam).split()[0]}\n- v3 {d(v3['datum'])}\nKundennummer {k['kundennummer']}, "
                f"Bestellungen laufen über {r.choice(['EDI', 'das Kundenportal', 'Mail an den Innendienst'])}.")
    return dateien


def geschichte(k: dict, g: str, o: dict, r: random.Random, lege) -> list[str]:
    """Kundenspezifische Ereignisse, die mehrere Nutzer verbinden."""
    kam, ein, vh = k["kam"], k["kontakte"][0], k["verhandlung"]
    technik = next((c for c in k["kontakte"] if "Technik" in c["rolle"] or "Instandhaltung" in c["rolle"]), k["kontakte"][1])
    kanal = k["kurz"]
    neu = []

    if g == "reklamation":
        charge = f"{r.randint(24, 26)}-{r.randint(1000, 9999)}"
        tag = werktag(date(2026, r.choice([5, 6, 9]), r.randint(2, 26)))
        text = (f"Sehr geehrter Herr {person(kam).split()[1]},\n\nbei der Lieferung Charge {charge} "
                f"({PRODUKTE[k['produkte'][0]]}) sind {r.randint(6, 40)} Einheiten nach wenigen Betriebsstunden ausgefallen. "
                f"Wir fordern einen 8D-Bericht bis {d(tag + timedelta(days=14))} und Ersatzlieferung.\n\n{technik['name']}\n{technik['rolle']}")
        mail_extern(kam, technik["name"], technik["mail"], f"Reklamation Charge {charge}", tag, text)
        schreibe_eml(lege(o["mails"], f"Reklamation Charge {charge}.eml"), f"{technik['name']} <{technik['mail']}>",
                     NUTZER[kam]["upn"], f"Reklamation Charge {charge}", tag, text)
        mail_intern(kam, ["herbert"], f"WG: Reklamation Charge {charge} – {k['kurz']}", tag,
                    f"Hallo Herbert,\n\nbitte übernimm die Reklamation von {k['name']}, Charge {charge}. Kunde will 8D bis "
                    f"{d(tag + timedelta(days=14))}.\n\n" + signatur(kam))
        bericht = lege(f"{o['basis']}/Reklamation {charge}", f"8D-Bericht_{charge}_final.docx")
        schreibe_docx(bericht, f"8D-Bericht Charge {charge} – {k['name']}", [
            f"Erstellt von {person('herbert')} (Qualitätsmanagement), {d(tag + timedelta(days=12))}",
            "D4 Ursache: fehlerhafte Lötstelle am Leistungsteil durch neue Lötpaste eines Zulieferers.",
            "D5/D6 Maßnahme: Rückkehr zur alten Lötpaste, 100-%-Prüfung der Folgechargen bis Jahresende.",
            f"D8 Abschluss: Ersatzlieferung erfolgt am {d(werktag(tag + timedelta(days=9)))}, Gutschrift 4.800 EUR."])
        shutil.copy2(bericht, lege(o["lose"], f"8D_{charge} (2).docx"))  # Duplikat
        onenote("herbert", "Reklamationen", f"{k['kurz']} – Charge {charge}", tag,
                f"Kunde {k['name']}, gemeldet von {technik['name']} am {d(tag)} über {person(kam)}.\n"
                f"Ursache: Lötpaste Zulieferer. 8D am {d(tag + timedelta(days=12))} verschickt.\n"
                f"Gutschrift 4.800 EUR, Ersatzlieferung {d(werktag(tag + timedelta(days=9)))}.\nStatus: abgeschlossen.")
        post("herbert", kanal, tag + timedelta(days=12), f"8D-Bericht zu Charge {charge} ist an {technik['name']} raus. "
             "Ursache Lötpaste, Maßnahmen umgesetzt.")
        teams_ablage("herbert", kanal, bericht, bericht.name)

    elif g == "techniktermin":
        tag = werktag(HEUTE + timedelta(days=r.randint(6, 13)))
        termin(kam, [kam, "ingo"], f"Kundenbesuch {k['kurz']} – Technik {k['produkte'][-1]}", tag, "09:30", "12:00",
               f"{k['name']}, {k['ort']}",
               f"Mit {technik['name']} ({technik['rolle']}). Themen: Inbetriebnahme {PRODUKTE[k['produkte'][-1]]}, "
               "Schnittstellen, Schulung Instandhaltung.")
        mail_intern("ingo", [kam], f"Vorbereitung Besuch {k['kurz']}", werktag(HEUTE - timedelta(days=2)),
                    f"Hi {person(kam).split()[0]},\n\nich bringe für {k['kurz']} das Demo-Kit {k['produkte'][-1]} mit. "
                    f"Kannst du mit {technik['name']} klären, ob die Steuerung auf Firmware 3.2 ist?\n\n" + signatur("ingo"))
        onenote("ingo", "Technik Kunden", f"{k['kurz']} – Inbetriebnahme", werktag(HEUTE - timedelta(days=20)),
                f"{k['name']}: Ansprechpartner Technik {technik['name']}.\nFirmware-Stand unklar (3.1 oder 3.2?).\n"
                f"Besuch geplant am {d(tag)} mit {person(kam)}.")
        chat("ingo", kam, werktag(HEUTE - timedelta(days=1)), f"Steht der Termin bei {k['kurz']} am {d(tag)}? Dann buche ich das Hotel.")

    elif g == "projekt":
        projekt = r.choice(["Retrofit Linie 3", "Neubau Halle Süd", "Modernisierung Antriebe", "Pilot Condition Monitoring"])
        start = date(2026, r.choice([3, 4, 5]), r.randint(1, 25))
        doc = lege(f"{o['basis']}/Projekt {projekt}", f"Projektplan {projekt}.docx")
        schreibe_docx(doc, f"Projekt {projekt} – {k['name']}", [
            f"Projektstart: {d(start)}, Projektleitung Kunde: {technik['name']}, Vertrieb: {person(kam)}",
            f"Umfang: {r.randint(40, 300)} Einheiten {PRODUKTE[k['produkte'][0]]}, Projektvolumen ca. "
            f"{eur(r.randint(150, 900) * 1000)}",
            f"Meilensteine: Pflichtenheft {d(start + timedelta(days=30))}, Musterlieferung {d(start + timedelta(days=90))}, "
            f"Serienstart {d(start + timedelta(days=200))}"])
        schreibe_pptx(lege(f"{o['basis']}/Projekt {projekt}", f"Präsentation {projekt} Kick-off.pptx"),
                      f"{projekt} – Kick-off", ["Ziele", "Zeitplan", "Ansprechpartner", "Offene Punkte"])
        post(kam, kanal, start, f"Projekt {projekt} bei {k['kurz']} ist offiziell gestartet. Projektplan liegt in meinem "
             "OneDrive, schicke ich bei Bedarf.")
        termin(kam, [kam] + [t for t in k["team"] if t in ("ingo", "sally")], f"Projekt-Jour-fixe {k['kurz']} {projekt}",
               werktag(HEUTE + timedelta(days=r.randint(1, 8))), "14:00", "15:00", "Teams-Besprechung",
               f"Stand {projekt}, Musterlieferung, offene Punkte von {technik['name']}.")

    elif g == "lieferverzug":
        bestellung = f"45{r.randint(10, 99)}-{r.randint(1000, 9999)}"
        tag = werktag(HEUTE - timedelta(days=r.randint(8, 20)))
        text = (f"Hallo {person(kam).split()[0]},\n\nunsere Bestellung {bestellung} ({PRODUKTE[k['produkte'][0]]}) "
                f"ist seit {r.randint(2, 5)} Wochen überfällig. Wir brauchen einen verbindlichen Liefertermin, "
                f"sonst steht unsere Montage.\n\n{ein['name']}")
        mail_extern(kam, ein["name"], ein["mail"], f"Lieferverzug Bestellung {bestellung}", tag, text)
        mail_intern(kam, ["udo"], f"WG: Lieferverzug Bestellung {bestellung} ({k['kurz']})", tag,
                    f"Udo, kannst du mir bis morgen einen Termin für {bestellung} geben? Kunde macht Druck.\n\n" + signatur(kam))
        neuer = werktag(tag + timedelta(days=r.randint(10, 18)))
        mail_intern("udo", [kam], f"AW: WG: Lieferverzug Bestellung {bestellung} ({k['kurz']})", werktag(tag + timedelta(days=1)),
                    f"Hallo {person(kam).split()[0]},\n\nUrsache ist ein Engpass bei Leistungshalbleitern. Neuer Liefertermin "
                    f"für {bestellung}: {d(neuer)}, Teillieferung 50 % schon am {d(werktag(tag + timedelta(days=5)))}.\n\n"
                    + signatur("udo"))
        onenote("udo", "Lieferplanung", f"Rückstand {k['kurz']} {bestellung}", tag,
                f"Bestellung {bestellung} von {k['name']}, Engpass Leistungshalbleiter.\nTeillieferung 50 %: "
                f"{d(werktag(tag + timedelta(days=5)))}\nRest: {d(neuer)}\nKAM informiert: {person(kam)}")
        chat("udo", kam, werktag(tag + timedelta(days=4)), f"Teillieferung {bestellung} für {k['kurz']} geht morgen raus.")
        post("udo", kanal, werktag(tag + timedelta(days=1)), f"Lieferverzug {bestellung}: neuer Termin {d(neuer)}, Teillieferung vorher.")

    elif g == "kuendigung":
        tag = werktag(date(2026, 9, r.randint(1, 25)))
        text = (f"Sehr geehrte Damen und Herren,\n\nhiermit kündigen wir den Rahmenvertrag {k['vertrag']['nr']} fristgerecht "
                f"zum Laufzeitende {d(k['vertrag']['ende'])}. Gesprächen über einen neuen Vertrag zu angepassten "
                f"Konditionen stehen wir offen gegenüber.\n\n{ein['name']}\n{ein['rolle']}")
        mail_extern(kam, ein["name"], ein["mail"], f"Kündigung Rahmenvertrag {k['vertrag']['nr']}", tag, text)
        schreibe_eml(lege(o["vertrag"], f"Kündigung {k['vertrag']['nr']}.eml"), f"{ein['name']} <{ein['mail']}>",
                     NUTZER[kam]["upn"], f"Kündigung Rahmenvertrag {k['vertrag']['nr']}", tag, text)
        mail_intern(kam, ["ingrid"], f"{k['kurz']} hat {k['vertrag']['nr']} gekündigt", tag,
                    f"Hallo Ingrid,\n\n{k['name']} hat zum {d(k['vertrag']['ende'])} gekündigt, will aber neu verhandeln. "
                    "Vorschlag: Termin mit Einkauf im November.\n\n" + signatur(kam))
        onenote("ingrid", "Eskalationen", f"Kündigung {k['kurz']}", tag,
                f"{k['name']} kündigt {k['vertrag']['nr']} zum {d(k['vertrag']['ende'])}. KAM: {person(kam)}.\n"
                "Ziel: Neuvertrag 3 Jahre, Rabatt max. +1 Punkt.")

    elif g == "audit":
        tag = werktag(HEUTE + timedelta(days=r.randint(9, 20)))
        termin("herbert", ["herbert", kam], f"Lieferantenaudit durch {k['kurz']}", tag, "08:30", "16:00",
               f"{FIRMA}, Werk 1", f"Audit nach {r.choice(['ISO 13485', 'GMP-Anforderungen', 'ISO 9001'])} durch "
               f"{k['name']}. Auditor beim Kunden: {technik['name']}.")
        plan = lege(f"{o['basis']}/Audit", f"Auditplan {k['kurz']} {tag.year}.pdf")
        schreibe_pdf(plan, f"Auditplan {k['name']}", [f"Termin: {d(tag)}", "08:30 Eröffnung, 09:00 Wareneingang, "
                     "11:00 Fertigung SMD, 13:30 Prüffeld, 15:30 Abschlussgespräch", f"Ansprechpartner QM: {person('herbert')}"])
        onenote("herbert", "Audits", f"Audit {k['kurz']} {d(tag)}", werktag(HEUTE - timedelta(days=10)),
                f"Kundenaudit {k['name']} am {d(tag)}. Vorbereitung: Prüfprotokolle der letzten 12 Monate, "
                f"Rückverfolgbarkeit. KAM {person(kam)} kommt zum Abschlussgespräch.")
        teams_ablage("herbert", kanal, plan, plan.name)

    elif g == "preisfreigabe":
        v3 = vh["versionen"][2]
        tag = werktag(v3["datum"] - timedelta(days=3))
        mail_intern(kam, ["ingrid"], f"Freigabe Rabatt {k['kurz']} 2027", tag,
                    f"Hallo Ingrid,\n\nfür {k['name']} brauche ich deine Freigabe: {v3['rabatt']} % Rabatt bei "
                    f"+{pz(v3['preiserhoehung'])} % Preisanpassung, Volumen {eur(vh['volumen'])}.\n\n" + signatur(kam)
                    if kam != "ingrid" else f"Heinrich,\n\nfür {k['name']} bitte ich um Freigabe von {v3['rabatt']} % "
                    f"Rabatt (+{pz(v3['preiserhoehung'])} %).\n\n" + signatur("ingrid"))
        if kam == "ingrid":
            PLAN["ingrid"]["gesendet"][-1]["an"] = [NUTZER["heinrich"]["upn"]]
            PLAN["ingrid"]["inbox"].pop()  # an Heinrich, nicht an sich selbst
            PLAN["heinrich"]["inbox"].append(PLAN["ingrid"]["gesendet"][-1])
            freigeber, an = "heinrich", "ingrid"
        else:
            freigeber, an = "ingrid", kam
        grenze = v3["rabatt"] + (0 if r.random() < 0.5 else 1)
        mail_intern(freigeber, [an], f"AW: Freigabe Rabatt {k['kurz']} 2027", werktag(tag + timedelta(days=1)),
                    f"Freigegeben bis maximal {grenze} % Rabatt, Preisanpassung nicht unter {pz(v3['preiserhoehung'] - 0.5)} %.\n\n"
                    + signatur(freigeber))
        onenote(freigeber, "Preisfreigaben", f"{k['kurz']} 2027", tag,
                f"Anfrage {person(an if freigeber == 'heinrich' else kam)} am {d(tag)}: {v3['rabatt']} % Rabatt.\n"
                f"Freigabe bis {grenze} %, Preisanpassung mind. {pz(v3['preiserhoehung'] - 0.5)} %.")

    elif g == "uebergabe":
        # Kessler: Bella gibt an Peter ab. Peters Notiz ist neuer und weicht ab (neuer Einkäufer, Nachverhandlung).
        v3 = vh["versionen"][2]
        neuer_einkauf = "Dr. Simone Rautenberg"
        tag = werktag(date(2026, 10, 20))
        doc = lege(o["basis"], "Übergabe Kessler an Peter.docx")
        schreibe_docx(doc, f"Übergabeprotokoll {k['name']}", [
            f"Übergabe von {person('bella')} an {person('peter')} zum 01.01.2027 (Neuordnung Gebiete).",
            f"Ansprechpartner Einkauf: {ein['name']} ({ein['mail']}).",
            f"Laufende Preisverhandlung {vh['angebot']}: v3 mit {v3['rabatt']} % Rabatt, +{pz(v3['preiserhoehung'])} %, "
            f"Status {v3['status']}.",
            f"Rahmenvertrag {k['vertrag']['nr']} läuft bis {d(k['vertrag']['ende'])}."])
        teams_ablage("bella", kanal, doc, doc.name)
        mail_intern("bella", ["peter", "ingrid"], "Übergabe Kessler Antriebstechnik", tag,
                    f"Hallo Peter,\n\nanbei die Übergabe für Kessler (liegt auch im Kanal). Wichtig: {ein['name']} "
                    f"entscheidet im Einkauf, v3 steht bei {v3['rabatt']} %.\n\n" + signatur("bella"))
        termin("bella", ["bella", "peter", "ingrid"], "Übergabegespräch Kessler", werktag(date(2026, 10, 22)), "10:00",
               "11:00", "Teams-Besprechung", "Übergabe Kessler von Bella an Peter, Ingrid als Vertriebsleitung dabei.")
        termin("peter", ["peter", "bella"], "Antrittsbesuch Kessler Heilbronn", werktag(HEUTE + timedelta(days=11)),
               "10:00", "12:30", f"{k['name']}, Heilbronn", f"Vorstellung Peter Maier bei {neuer_einkauf} (neue Leitung Einkauf).")
        onenote("peter", k["name"], "Übernahme Kessler", werktag(date(2026, 10, 29)),
                f"Telefonat mit {neuer_einkauf}, seit 01.10.2026 neue Leitung Einkauf bei {k['name']} "
                f"(Nachfolge {ein['name']}, wechselt intern).\n"
                f"Sie will v3 nachverhandeln: Ziel {v3['rabatt'] + 1} % Rabatt statt {v3['rabatt']} %. "
                "Noch nichts zugesagt, Rücksprache mit Ingrid.")
        chat("peter", "bella", werktag(date(2026, 10, 29)), f"Wusstest du, dass {ein['name']} nicht mehr im Einkauf ist? "
             f"Jetzt ist {neuer_einkauf} zuständig.")
        chat("bella", "peter", werktag(date(2026, 10, 30)), "Oh, nein – das stand nirgends. Mein Stand war noch das alte Organigramm.")

    elif g == "strategisch":
        tag = werktag(HEUTE + timedelta(days=r.randint(3, 15)))
        termin("ingrid", ["ingrid", "heinrich"] + [t for t in k["team"] if t not in ("heinrich",)][:2],
               f"Strategiegespräch {k['kurz']} 2027–2029", tag, "13:00", "15:00", "Raum Vorstand",
               f"Vorbereitung Jahresgespräch {k['name']}: Volumen, Mehrjahresvertrag, Preisstrategie.")
        schreibe_pptx(lege(o["basis"], f"{k['kurz']} Account-Plan 2027.pptx"), f"Account-Plan {k['name']}",
                      [f"Umsatz 2025: {k['umsatz_2025']:.2f} Mio. EUR", "Ziel 2027: +12 %", "Risiken: Preisdruck, Second Source",
                       "Maßnahmen: Mehrjahresvertrag, technischer Support vor Ort"])
        onenote("heinrich", "Strategische Kunden", k["name"], werktag(HEUTE - timedelta(days=30)),
                f"{k['name']}: Umsatz 2025 {k['umsatz_2025']:.2f} Mio. EUR, Verantwortung {person('ingrid')}.\n"
                f"Ziel: Mehrjahresvertrag bis 2029. Strategiegespräch am {d(tag)}.")
        mail_intern("ingrid", ["heinrich"] + [t for t in k["team"] if t != "heinrich"][:1],
                    f"Vorbereitung Strategiegespräch {k['kurz']}", werktag(tag - timedelta(days=5)),
                    f"Hallo zusammen,\n\nzum Strategiegespräch {k['kurz']} am {d(tag)} bitte die Zahlen aus dem Account-Plan "
                    "prüfen. Offene Frage: Laufzeit 3 oder 5 Jahre?\n\n" + signatur("ingrid"))
    return neu


# =============================================================================
# Allgemeines (nicht kundenbezogen) und Hauptprogramm
# =============================================================================

def allgemeines() -> None:
    termin("ingrid", ["ingrid", "jonas", "bella", "peter", "sally"], "Forecast-Runde Vertrieb Q4/2026",
           werktag(HEUTE + timedelta(days=4)), "09:00", "10:30", "Raum 2.14", "Forecast je Kunde, Preisrunde 2027, Risiken.")
    termin("heinrich", ["heinrich", "ingrid", "udo", "herbert"], "Managementrunde Lieferfähigkeit",
           werktag(HEUTE + timedelta(days=7)), "11:00", "12:00", "Raum Vorstand", "Halbleiterengpass, Reklamationsquote, Audits.")
    mail_intern("ingrid", ["jonas", "bella", "peter"], "Preisrunde 2027 – Leitplanken", date(2026, 7, 1),
                "Hallo zusammen,\n\nfür die Preisrunde 2027 gilt: Listenpreiserhöhung 6,5 %, Untergrenze 3,9 %. "
                "Rabatterhöhungen über +2 Punkte nur mit meiner Freigabe, über +3 Punkte mit Heinrich.\n\n" + signatur("ingrid"))
    onenote("ingrid", "Preisfreigaben", "Leitplanken Preisrunde 2027", date(2026, 6, 28),
            "Listenpreis +6,5 %, Untergrenze +3,9 %.\nRabatt +2 Punkte: Freigabe Vertriebsleitung.\n"
            "Mehr als +3 Punkte: Geschäftsführung.")
    for kam in ("jonas", "bella", "peter"):
        chat("sally", kam, werktag(HEUTE - timedelta(days=3)), "Kurze Info: Preislisten 2027 sind im System, "
             "Angebote ab sofort mit neuem Listenpreis.")
        onenote(kam, "Allgemein", "Persönliche Notizen (privat)", werktag(HEUTE - timedelta(days=40)),
                f"Private Notiz von {person(kam)} – nur für mich.\nZiele 2027: Neukunden im Gebiet, weniger Reisetage.\n"
                "Urlaub: 22.12.–05.01.")


def main() -> None:
    if AUSGABE.exists():
        shutil.rmtree(AUSGABE)
    kunden = alle_kunden()
    uebersicht = ["# Testdaten Tenant KAMPilot", "", f"Erzeugt für {len(kunden)} Kunden. Alle Daten sind fiktiv.", ""]
    for k in kunden:
        dateien = kunde_erzeugen(k)
        vt, v = k["vertrag"], k["verhandlung"]["versionen"]
        uebersicht += [f"## {k['name']} ({k['ort']}) – KAM {person(k['kam'])}",
                       f"Team: {', '.join(person(t) for t in k['team']) or '–'} · Geschichten: {', '.join(k['geschichte']) or '–'}",
                       f"Vertrag {vt['nr']}: {d(vt['beginn'])}–{d(vt['ende'])}, {vt['rabatt']} % Rabatt, "
                       f"{vt['zahlungsziel']} Tage · Verhandlung: " + " → ".join(f"v{x['version']} {x['rabatt']} %" for x in v)
                       + f" ({v[2]['status']})", "", "OneDrive:"] + [f"- `{x}`" for x in sorted(dateien)] + [""]
    allgemeines()
    AUSGABE.mkdir(parents=True, exist_ok=True)
    (AUSGABE / "plan.json").write_text(json.dumps(PLAN, ensure_ascii=False, indent=1), encoding="utf-8")
    zeilen = ["| Nutzer | OneNote | Mails Eingang | Gesendet | Termine | OneDrive | Teams-Posts | Teams-Dateien | Chats |",
              "|---|---|---|---|---|---|---|---|---|"]
    for n, p in PLAN.items():
        zeilen.append(f"| {person(n)} | {len(p['onenote'])} | {len(p['inbox'])} | {len(p['gesendet'])} | {len(p['termine'])} | "
                      f"{len(p['onedrive'])} | {len(p['kanal_posts'])} | {len(p['kanal_dateien'])} | {len(p['chats'])} |")
    (AUSGABE / "UEBERSICHT.md").write_text("\n".join(uebersicht[:4] + zeilen + [""] + uebersicht[4:]) + "\n", encoding="utf-8")
    print("\n".join(zeilen))


if __name__ == "__main__":
    main()
