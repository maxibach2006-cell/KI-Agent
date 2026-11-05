"""Text aus verschiedenen Dateiformaten holen.

Rolle im System:
    Die Quellen liefern Inhalte in unterschiedlichen Formaten (OneNote und Outlook als HTML, abgelegte
    Mails als .msg/.eml, Dokumente als .docx/.pdf). Für die Suche zählt nur der reine Text. Dieses
    Modul wandelt alle Formate in Klartext um.
    Genutzt von den Graph-Connectoren (connectors/) UND vom lokalen Demo-Loader (local_loader.py),
    damit beide Wege exakt dieselben Texte erzeugen.
"""
import email
import io
import tempfile
from email import policy
from pathlib import Path

from bs4 import BeautifulSoup


def html_zu_text(html: str) -> str:
    """HTML -> Klartext: Tags entfernen, leere Zeilen weglassen, Zeilenumbrüche erhalten."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):  # Programmcode und Formatierung sind kein Inhalt
        tag.decompose()
    zeilen = [z.strip() for z in soup.get_text("\n").splitlines()]
    return "\n".join(z for z in zeilen if z)


def lies_msg(daten: bytes) -> dict:
    """Outlook-.msg-Datei -> {"betreff", "absender", "datum", "text"}."""
    import extract_msg  # erst hier importiert: wird nur gebraucht, wenn es .msg-Dateien gibt
    # extract_msg braucht eine Datei auf der Platte -> Bytes in eine temporäre Datei schreiben
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as f:
        f.write(daten)
        pfad = f.name
    msg = None
    try:
        msg = extract_msg.Message(pfad)
        return {"betreff": msg.subject or "", "absender": msg.sender or "",
                "datum": str(msg.date or "")[:10], "text": msg.body or ""}
    finally:
        if msg:
            msg.close()
        Path(pfad).unlink(missing_ok=True)  # temporäre Datei wieder löschen


def lies_eml(daten: bytes) -> dict:
    """Standard-E-Mail-Datei (.eml) -> {"betreff", "absender", "datum", "text"}."""
    msg = email.message_from_bytes(daten, policy=policy.default)
    # Mails enthalten oft Text- UND HTML-Fassung; bevorzugt wird die einfache Textfassung
    teil = msg.get_body(preferencelist=("plain", "html"))
    text = teil.get_content() if teil else ""
    if teil is not None and teil.get_content_type() == "text/html":
        text = html_zu_text(text)
    # Ein unlesbarer Date-Header ergibt datetime=None, die Mail bleibt trotzdem nutzbar
    datum = msg["Date"].datetime.date().isoformat() if msg["Date"] and msg["Date"].datetime else ""
    return {"betreff": str(msg["Subject"] or ""), "absender": str(msg["From"] or ""),
            "datum": datum, "text": text}


def lies_docx(daten: bytes) -> str:
    """Word-Dokument -> Text aller Absätze und Tabellen (Tabellenzellen mit " | " getrennt)."""
    from docx import Document
    doc = Document(io.BytesIO(daten))
    zeilen = [p.text for p in doc.paragraphs]
    for tabelle in doc.tables:
        for zeile in tabelle.rows:
            zeilen.append(" | ".join(zelle.text for zelle in zeile.cells))
    return "\n".join(z for z in zeilen if z.strip())


def lies_pdf(daten: bytes) -> str:
    """PDF -> Text aller Seiten (nur eingebetteter Text; gescannte Bilder werden nicht erkannt)."""
    from pypdf import PdfReader
    return "\n".join(seite.extract_text() or "" for seite in PdfReader(io.BytesIO(daten)).pages)


def datei_zu_dokument(name: str, daten: bytes, ort: str, link: str, datum: str = "") -> dict | None:
    """Wandelt eine Datei in das einheitliche Dokumentformat des Projekts um.

    Parameter:
        name:   Dateiname, die Endung bestimmt das Format
        daten:  Inhalt der Datei als Bytes
        ort:    Speicherort (z. B. "SharePoint > Key Account - Kunden > Hoffmann")
        link:   Link oder Pfad zur Datei, erscheint später in der Quellenangabe
        datum:  Änderungsdatum als Ersatz, falls die Datei selbst kein Datum enthält
    Rückgabe:
        {"text": ..., "meta": {...}} oder None, wenn das Format nicht unterstützt wird
    """
    endung = Path(name).suffix.lower()
    meta = {"quelle": "Datei", "titel": name, "ort": ort, "link": link, "datum": datum, "absender": ""}
    if endung in (".msg", ".eml"):
        mail = lies_msg(daten) if endung == ".msg" else lies_eml(daten)
        meta.update(absender=mail["absender"], datum=mail["datum"] or datum)
        # Betreff/Absender/Datum in den Text übernehmen, damit die Suche auch danach findet
        text = f"Betreff: {mail['betreff']}\nVon: {mail['absender']}\nDatum: {mail['datum']}\n\n{mail['text']}"
    elif endung == ".docx":
        text = lies_docx(daten)
    elif endung == ".pdf":
        text = lies_pdf(daten)
    elif endung in (".txt", ".md"):
        text = daten.decode("utf-8", errors="ignore")
    else:
        return None
    return {"text": text, "meta": meta}
