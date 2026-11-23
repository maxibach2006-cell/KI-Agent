"""Fiktive Stammdaten für den Test-Tenant KAMPilot: Nutzer, 20 Kunden und ihre Geschichten.

ALLE Firmen, Personen, Adressen und Zahlen sind erfunden. Mailadressen externer Personen enden auf .example
(reservierte Domain, kann nie echt sein). Die bisherigen Demo-Daten (demo_data/) werden hier NICHT verwendet.

Aufbau:
    NUTZER    die Konten im Tenant (Kürzel -> Name, Anmeldename, Rolle)
    KUNDEN    32 Kunden (20 + 12 im Gebiet Ost) mit Branche, Ort, betreuenden Nutzern und Besonderheiten ("geschichte")
    fakten()  ergänzt jeden Kunden um abgeleitete, aber feste Fakten (Kundennummer, Ansprechpartner, Vertrag,
              Preisverhandlung in 3 Versionen …). Zufall mit festem Startwert -> jeder Lauf erzeugt dasselbe.
"""
import random
from datetime import date, timedelta

DOMAIN = "KAMPilot.onmicrosoft.com"
FIRMA = "KAM-Pilot GmbH"

NUTZER = {
    "ingrid":   {"name": "Ingrid Heller",   "upn": f"Ingrid@{DOMAIN}",   "rolle": "Vertriebsleitung"},
    "jonas":    {"name": "Jonas Hechler",   "upn": f"Joki@{DOMAIN}",     "rolle": "Key-Account-Manager Nord"},
    "bella":    {"name": "Bella Froh",      "upn": f"Bella@{DOMAIN}",    "rolle": "Key-Account-Managerin Süd"},
    "peter":    {"name": "Peter Maier",     "upn": f"Peter@{DOMAIN}",    "rolle": "Key-Account-Manager West"},
    "sally":    {"name": "Sally Mongo",     "upn": f"Sally@{DOMAIN}",    "rolle": "Vertriebsinnendienst"},
    "ingo":     {"name": "Ingo Bauer",      "upn": f"Ingo@{DOMAIN}",     "rolle": "Anwendungstechnik"},
    "udo":      {"name": "Udo Heußer",      "upn": f"Udo@{DOMAIN}",      "rolle": "Supply Chain / Disposition"},
    "herbert":  {"name": "Herbert Heiner",  "upn": f"Herbert@{DOMAIN}",  "rolle": "Qualitätsmanagement"},
    "heinrich": {"name": "Heinrich Frei",   "upn": f"Heinrich@{DOMAIN}", "rolle": "Geschäftsführung"},
    "sven":     {"name": "Sven Seidenstricker", "upn": f"Sven_Seidenstricker@{DOMAIN}", "rolle": "Key-Account-Manager Ost"},
}

PRODUKTE = {
    "SM-400": "Steuermodule Serie SM-400",
    "SR-200": "Servoregler SR-200",
    "PA-50": "Pumpenantriebe PA-50",
    "PA-70": "Pumpenantriebe PA-70 (neue Baureihe)",
    "SensPak": "Sensorpaket SensPak-S",
    "Service": "Wartungs- und Servicevertrag",
}

# kam = verantwortlich (Ordner liegt in dessen OneDrive); team = weitere Nutzer mit Kontakt zum Kunden
KUNDEN = [
    # --- Nord: Jonas ---
    {"kurz": "Albers", "name": "Albers Fördertechnik GmbH", "ort": "Bremen", "branche": "Fördertechnik",
     "kam": "jonas", "team": ["ingo", "herbert", "sally"], "produkte": ["SM-400", "SR-200"],
     "geschichte": ["reklamation", "techniktermin"]},
    {"kurz": "Hanse Verpackung", "name": "Hanse Verpackung AG", "ort": "Hamburg", "branche": "Verpackungsmaschinen",
     "kam": "jonas", "team": ["sally"], "produkte": ["SM-400", "SensPak"], "geschichte": ["projekt"]},
    {"kurz": "Kruse", "name": "Kruse Lebensmitteltechnik KG", "ort": "Cuxhaven", "branche": "Lebensmitteltechnik",
     "kam": "jonas", "team": ["udo"], "produkte": ["PA-50"], "geschichte": ["lieferverzug"]},
    {"kurz": "Weser Agrar", "name": "Weser Agrartechnik AG", "ort": "Nienburg", "branche": "Landmaschinen",
     "kam": "jonas", "team": [], "produkte": ["SR-200", "Service"], "geschichte": []},
    {"kurz": "Lindholm", "name": "Lindholm Windservice GmbH", "ort": "Husum", "branche": "Windenergie-Service",
     "kam": "jonas", "team": ["ingo"], "produkte": ["SensPak", "Service"], "geschichte": ["projekt"]},
    {"kurz": "Brandt Mühlenbau", "name": "Brandt & Söhne Mühlenbau GmbH", "ort": "Oldenburg", "branche": "Mühlenbau",
     "kam": "jonas", "team": [], "produkte": ["PA-50", "SM-400"], "geschichte": ["kuendigung"]},
    # --- Süd: Bella ---
    {"kurz": "Lechner", "name": "Lechner Präzisionsteile GmbH", "ort": "Augsburg", "branche": "Zerspanung",
     "kam": "bella", "team": ["sally"], "produkte": ["SR-200"], "geschichte": []},
    {"kurz": "Kessler", "name": "Kessler Antriebstechnik GmbH", "ort": "Heilbronn", "branche": "Antriebstechnik",
     "kam": "bella", "team": ["peter", "ingrid"], "produkte": ["SM-400", "PA-70"],
     "geschichte": ["uebergabe"]},
    {"kurz": "Alpina", "name": "Alpina Fördersysteme GmbH", "ort": "Kempten", "branche": "Seil- und Fördersysteme",
     "kam": "bella", "team": ["ingo"], "produkte": ["SR-200", "SensPak"], "geschichte": ["techniktermin"]},
    {"kurz": "Riedl", "name": "Donau Kunststoffwerk Riedl GmbH", "ort": "Regensburg", "branche": "Kunststoffverarbeitung",
     "kam": "bella", "team": ["herbert"], "produkte": ["PA-50"], "geschichte": ["reklamation"]},
    {"kurz": "Merz", "name": "Merz Feinwerktechnik GmbH", "ort": "Villingen-Schwenningen", "branche": "Feinwerktechnik",
     "kam": "bella", "team": [], "produkte": ["SM-400"], "geschichte": []},
    {"kurz": "Bodensee Medical", "name": "Bodensee Medizinprodukte AG", "ort": "Konstanz", "branche": "Medizintechnik",
     "kam": "bella", "team": ["herbert"], "produkte": ["PA-70", "SensPak"], "geschichte": ["audit"]},
    {"kurz": "Isar Robotics", "name": "Isar Robotics GmbH", "ort": "München", "branche": "Robotik",
     "kam": "bella", "team": ["ingo", "sally"], "produkte": ["SR-200", "SM-400"], "geschichte": ["projekt"]},
    # --- West: Peter ---
    {"kurz": "Rheintal Pharma", "name": "Rheintal Pharma AG", "ort": "Mannheim", "branche": "Pharma",
     "kam": "peter", "team": ["herbert", "ingrid"], "produkte": ["PA-50", "PA-70"],
     "geschichte": ["audit", "preisfreigabe"]},
    {"kurz": "Moselland", "name": "Moselland Getränketechnik GmbH", "ort": "Trier", "branche": "Getränkeabfüllung",
     "kam": "peter", "team": ["sally"], "produkte": ["SM-400", "PA-50"], "geschichte": []},
    {"kurz": "Ruhrstahl", "name": "Ruhrstahl Komponenten GmbH", "ort": "Bochum", "branche": "Stahlverarbeitung",
     "kam": "peter", "team": ["udo"], "produkte": ["SR-200"], "geschichte": ["lieferverzug"]},
    {"kurz": "Schuster Papier", "name": "Eifel Papierfabrik Schuster KG", "ort": "Düren", "branche": "Papierherstellung",
     "kam": "peter", "team": [], "produkte": ["PA-70", "Service"], "geschichte": ["kuendigung"]},
    {"kurz": "Niederrhein Logistik", "name": "Niederrhein Logistiksysteme GmbH", "ort": "Krefeld",
     "branche": "Intralogistik", "kam": "peter", "team": ["udo", "sally"], "produkte": ["SM-400", "SensPak"],
     "geschichte": ["lieferverzug"]},
    # --- strategische Kunden: Vertriebsleitung ---
    {"kurz": "Vossberg", "name": "Vossberg Fahrzeugtechnik SE", "ort": "Braunschweig", "branche": "Automotive (Tier 1)",
     "kam": "ingrid", "team": ["jonas", "heinrich", "ingo"], "produkte": ["SM-400", "SR-200", "SensPak"],
     "geschichte": ["strategisch", "preisfreigabe"]},
    {"kurz": "Talheim Chemie", "name": "Talheim Chemie AG", "ort": "Ludwigshafen", "branche": "Chemie",
     "kam": "ingrid", "team": ["peter", "herbert"], "produkte": ["PA-50", "PA-70", "Service"],
     "geschichte": ["strategisch", "audit"]},
    # --- Ost: Sven (später ergänzt, deutlich mehr Daten: Besuchsberichte seit 2019, Altprojekte, Wettbewerb, Messe) ---
    # Am Ende angehängt, damit Kundennummern und Zufallswerte der bisherigen Kunden unverändert bleiben.
    {"kurz": "Elbtal", "name": "Elbtal Anlagenbau GmbH", "ort": "Dresden", "branche": "Anlagenbau",
     "kam": "sven", "team": ["herbert", "sally"], "produkte": ["SM-400", "SR-200"],
     "geschichte": ["reklamation", "besuchsberichte", "altprojekt"]},
    {"kurz": "Saale Kunststoff", "name": "Saale Kunststofftechnik GmbH", "ort": "Halle (Saale)",
     "branche": "Kunststoffverarbeitung", "kam": "sven", "team": ["udo"], "produkte": ["PA-50"],
     "geschichte": ["lieferverzug", "besuchsberichte"]},
    {"kurz": "Lausitz Energie", "name": "Lausitz Energiesysteme AG", "ort": "Cottbus", "branche": "Energietechnik",
     "kam": "sven", "team": ["ingo", "ingrid"], "produkte": ["PA-70", "SensPak", "Service"],
     "geschichte": ["projekt", "preisfreigabe", "besuchsberichte"]},
    {"kurz": "Erzgebirge Feinmechanik", "name": "Erzgebirge Feinmechanik KG", "ort": "Annaberg-Buchholz",
     "branche": "Feinmechanik", "kam": "sven", "team": [], "produkte": ["SM-400"],
     "geschichte": ["kuendigung", "wettbewerb"]},
    {"kurz": "Spree Automation", "name": "Spree Automation GmbH", "ort": "Berlin", "branche": "Automatisierungstechnik",
     "kam": "sven", "team": ["ingo", "sally"], "produkte": ["SR-200", "SensPak"],
     "geschichte": ["techniktermin", "projekt", "besuchsberichte"]},
    {"kurz": "Ilm Glas", "name": "Thüringer Glaswerke Ilm GmbH", "ort": "Ilmenau", "branche": "Glasherstellung",
     "kam": "sven", "team": ["herbert"], "produkte": ["PA-50", "PA-70"], "geschichte": ["audit", "besuchsberichte"]},
    {"kurz": "Havelland", "name": "Havelland Lebensmittelwerke GmbH", "ort": "Brandenburg an der Havel",
     "branche": "Lebensmittelindustrie", "kam": "sven", "team": ["herbert", "sally"], "produkte": ["PA-50", "Service"],
     "geschichte": ["reklamation", "wettbewerb"]},
    {"kurz": "Oder Logistik", "name": "Oder Logistiksysteme GmbH", "ort": "Frankfurt (Oder)", "branche": "Intralogistik",
     "kam": "sven", "team": ["udo"], "produkte": ["SM-400", "SensPak"], "geschichte": ["lieferverzug", "messe"]},
    {"kurz": "Vogtland Textil", "name": "Vogtland Textilmaschinen GmbH", "ort": "Plauen", "branche": "Textilmaschinen",
     "kam": "sven", "team": [], "produkte": ["SR-200"], "geschichte": ["altprojekt", "besuchsberichte"]},
    {"kurz": "Magdeburger Pumpen", "name": "Magdeburger Pumpenwerk AG", "ort": "Magdeburg", "branche": "Pumpenbau",
     "kam": "sven", "team": ["ingo", "ingrid", "sally"], "produkte": ["PA-50", "PA-70", "SM-400"],
     "geschichte": ["preisfreigabe", "techniktermin", "besuchsberichte"]},
    {"kurz": "Chemnitzer Werkzeugbau", "name": "Chemnitzer Werkzeugbau GmbH", "ort": "Chemnitz", "branche": "Werkzeugbau",
     "kam": "sven", "team": ["ingo"], "produkte": ["SR-200", "SM-400"], "geschichte": ["projekt", "wettbewerb"]},
    {"kurz": "Warnow Schiffstechnik", "name": "Warnow Schiffstechnik GmbH", "ort": "Rostock", "branche": "Schiffbau-Zulieferer",
     "kam": "sven", "team": ["sally"], "produkte": ["PA-70", "Service"], "geschichte": ["messe", "besuchsberichte"]},
]

VORNAMEN = ["Anke", "Bernd", "Carola", "Dirk", "Elke", "Frank", "Gabriele", "Holger", "Ines", "Jörg", "Karin",
            "Lars", "Monika", "Nils", "Olga", "Ralf", "Sabine", "Thorsten", "Ute", "Volker", "Wiebke", "Yvonne",
            "Matthias", "Stefanie", "Tobias", "Miriam", "Andreas", "Kerstin", "Sven", "Doris"]
NACHNAMEN = ["Böttcher", "Claasen", "Dreyer", "Engel", "Fischer", "Gerdes", "Hartmann", "Imhoff", "Jansen",
             "Kühne", "Lorenz", "Mertens", "Neumann", "Oltmanns", "Petersen", "Quast", "Rademacher", "Seidel",
             "Tiedemann", "Ulbrich", "Vogel", "Wendt", "Zimmer", "Brückner", "Haas", "Krämer", "Pohl", "Sommer"]
ROLLEN = ["Leitung Einkauf", "Strategischer Einkauf", "Leitung Technik", "Konstruktion", "Geschäftsführung",
          "Qualitätsmanagement", "Instandhaltung", "Werksleitung"]

HEUTE = date(2026, 11, 5)

# Listenpreise (EUR je Stück bzw. je Jahr beim Servicevertrag) 2023 und die jährlichen Erhöhungen für ALLE Kunden.
# 2027 = Leitplanke der Preisrunde (+6,5 %), siehe Mail "Preisrunde 2027 – Leitplanken" von Ingrid Heller.
LISTENPREISE_2023 = {"SM-400": 1240, "SR-200": 860, "PA-50": 2150, "PA-70": 2980, "SensPak": 420, "Service": 18500}
PREISERHOEHUNG = {2024: 4.0, 2025: 3.5, 2026: 4.2, 2027: 6.5}


def listenpreise() -> dict[str, dict[int, int]]:
    """Listenpreis je Produkt und Jahr 2023–2027, auf ganze Euro gerundet (für alle Kunden gleich)."""
    preise = {}
    for produkt, preis in LISTENPREISE_2023.items():
        jahre = {2023: preis}
        for jahr, prozent in PREISERHOEHUNG.items():
            jahre[jahr] = round(jahre[jahr - 1] * (1 + prozent / 100))
        preise[produkt] = jahre
    return preise


def _mail(vor: str, nach: str, kurz: str) -> str:
    domain = "".join(c for c in kurz.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")
                     .replace("ß", "ss") if c.isalnum())
    nach = nach.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    return f"{vor.lower()[0]}.{nach}@{domain}.example"


def fakten(k: dict, nr: int) -> dict:
    """Feste Fakten eines Kunden ableiten. Gleicher Kunde -> immer dieselben Werte (fester Zufallsstartwert)."""
    r = random.Random(f"kampilot-{k['kurz']}")
    k = dict(k)
    k["kundennummer"] = f"K-{20400 + nr * 37}"
    k["umsatz_2025"] = round(r.uniform(0.3, 4.8), 2)  # Mio. EUR
    kontakte = []
    nachnamen = r.sample(NACHNAMEN, 3)  # verschiedene Nachnamen innerhalb eines Kunden
    for rolle, nach in zip(r.sample(ROLLEN, 3), nachnamen):
        vor = r.choice(VORNAMEN)
        kontakte.append({"name": f"{vor} {nach}", "rolle": rolle, "mail": _mail(vor, nach, k["kurz"]),
                         "tel": f"0{r.randint(30, 99)}{r.randint(1, 9)} {r.randint(10000, 99999)}-{r.randint(10, 99)}"})
    # Einkauf zuerst: mit dieser Person wird verhandelt
    kontakte.sort(key=lambda c: "Einkauf" not in c["rolle"])
    k["kontakte"] = kontakte

    beginn = date(r.choice([2022, 2023, 2024]), r.choice([1, 4, 7, 10]), 1)
    jahre = r.choice([3, 4, 5])
    while beginn.year + jahre < 2027 or (beginn.year + jahre == 2027 and beginn.month < 4):
        jahre += 1  # aktiver Vertrag: läuft mindestens bis ins Frühjahr 2027
    k["vertrag"] = {"nr": f"RV-{beginn.year}-{r.randint(100, 399)}", "beginn": beginn,
                    "ende": date(beginn.year + jahre, beginn.month, 1) - timedelta(days=1),
                    "rabatt": r.choice([5, 6, 7, 8, 9, 10]), "zahlungsziel": r.choice([30, 45, 60]),
                    "skonto": r.choice([2, 2, 3]), "kuendigung_monate": r.choice([3, 6, 6, 12]),
                    "unterzeichnet": kontakte[0]["name"]}
    # Entwurf vor der Unterschrift mit anderen (älteren) Konditionen -> realistische Falle
    k["vertrag_entwurf"] = {"rabatt": k["vertrag"]["rabatt"] - r.choice([1, 2]),
                            "zahlungsziel": r.choice([14, 30]) if k["vertrag"]["zahlungsziel"] != 30 else 14,
                            "datum": beginn - timedelta(days=r.randint(40, 80))}

    # Preisverhandlung 2027 in drei Versionen
    basis = k["vertrag"]["rabatt"]
    ang_nr = f"ANG-2026-{r.randint(1000, 1999)}"
    start = date(2026, r.choice([7, 8]), r.randint(3, 25))
    v = [{"version": 1, "datum": start, "rabatt": basis, "preiserhoehung": 6.5, "status": "abgelehnt"},
         {"version": 2, "datum": start + timedelta(days=r.randint(18, 30)), "rabatt": basis + 1,
          "preiserhoehung": 5.0, "status": "Gegenangebot Kunde"},
         {"version": 3, "datum": start + timedelta(days=r.randint(45, 70)), "rabatt": basis + r.choice([1, 2]),
          "preiserhoehung": r.choice([3.9, 4.2, 4.5]), "status": r.choice(["angenommen", "angenommen", "offen"])}]
    k["verhandlung"] = {"angebot": ang_nr, "versionen": v, "volumen": r.randint(80, 900) * 1000}
    k["kunde_seit"] = r.choice([2009, 2012, 2015, 2017, 2019, 2021])

    # Kennzahlen für Grafiken (eigener Zufallsstartwert: alle Werte oben bleiben unverändert, sie sind schon im Tenant)
    z = random.Random(f"kennzahlen-{k['kurz']}")
    umsatz = {2025: k["umsatz_2025"]}
    for jahr in range(2024, max(2020, k["kunde_seit"]) , -1):  # rückwärts aus dem Umsatz 2025, ab Kundenbeginn
        umsatz[jahr] = round(umsatz[jahr + 1] / (1 + z.uniform(-0.06, 0.14)), 2)
    k["umsatz"] = dict(sorted(umsatz.items()))                                  # Mio. EUR, Ist
    plan_2026 = round(umsatz[2025] * (1 + z.uniform(0.02, 0.09)), 2)
    k["plan"] = {2026: plan_2026, 2027: round(plan_2026 * (1 + z.uniform(0.03, 0.08)), 2)}
    k["umsatz_2026_bis_oktober"] = round(plan_2026 * z.uniform(0.74, 0.86), 2)
    reklamation = "reklamation" in k["geschichte"]
    k["kosten"] = {jahr: {"Fracht": round(umsatz.get(jahr, umsatz[2025]) * 1000 * z.uniform(0.011, 0.022), 1),
                          "Service vor Ort": round(z.uniform(3, 18), 1),
                          "Reklamationen": round(z.uniform(6, 14) if reklamation and jahr == 2025 else z.uniform(0, 3.5), 1)}
                   for jahr in (2023, 2024, 2025)}                                # Tsd. EUR
    return k


def alle_kunden() -> list[dict]:
    return [fakten(k, i) for i, k in enumerate(KUNDEN)]
