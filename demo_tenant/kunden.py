"""Fiktive Stammdaten für den Test-Tenant KAMPilot: Nutzer, 20 Kunden und ihre Geschichten.

ALLE Firmen, Personen, Adressen und Zahlen sind erfunden. Mailadressen externer Personen enden auf .example
(reservierte Domain, kann nie echt sein). Die bisherigen Demo-Daten (demo_data/) werden hier NICHT verwendet.

Aufbau:
    NUTZER    die Konten im Tenant (Kürzel -> Name, Anmeldename, Rolle)
    KUNDEN    20 Kunden mit Branche, Ort, betreuenden Nutzern und Besonderheiten ("geschichte")
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
    return k


def alle_kunden() -> list[dict]:
    return [fakten(k, i) for i, k in enumerate(KUNDEN)]
