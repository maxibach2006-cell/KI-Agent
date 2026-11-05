# Testplan: mehrere Nutzer gleichzeitig auf dem Server

Ziel: belegen, dass der Server mehrere angemeldete Nutzer gleichzeitig bedient, **ohne Daten zu vermischen**, und
messen, wie lange Antworten bei gleichzeitigen Fragen dauern. Grundlage sind die fiktiven Daten im Tenant KAMPilot
(`demo_tenant/`, 9 Testnutzer, Team „KAM-Pilot“). Dauer: etwa 1 Stunde, davon 30 Minuten Einlesen.

## Voraussetzungen

1. **Merge-Reihenfolge:** zuerst `jonas/token-pro-nutzer` (Token-Cache je Nutzer, E28), sonst bekommt beim Einlesen
   der zweite Nutzer die Daten des ersten.
2. **Zugang:** Die Testnutzer sind Mitglied im Team, das Cloudflare Access zulässt (derzeit „Key Account - Kunden“).
   Für Test T6 bleibt **ein** Konto bewusst draußen (Vorschlag: Heinrich Frei).
3. **Index je Nutzer** auf dem Server einlesen, einzeln und jeweils im privaten Browserfenster anmelden:
   ```bash
   docker compose exec agent python ingest.py --source graph --nutzer Joki@KAMPilot.onmicrosoft.com
   docker compose exec agent python ingest.py --source graph --nutzer Bella@KAMPilot.onmicrosoft.com
   docker compose exec agent python ingest.py --source graph --nutzer Peter@KAMPilot.onmicrosoft.com
   ```
   Erwartung: jeweils „Angemeldet als …“ mit genau diesem Konto. Wird ein anderes Konto angemeldet, bricht das
   Einlesen mit „Falsches Konto angemeldet“ ab (das ist Test T5).
4. Kein Testlauf und kein 14B-Gutachter parallel (CLAUDE.md, GPU).

## Testfälle

| Nr | Was | Ablauf | Erwartung |
|---|---|---|---|
| T1 | **Trennung der Daten** | Jonas fragt: „Was steht in meinen persönlichen Notizen zu den Zielen 2027?“ Danach Bella dieselbe Frage. | Jeder bekommt nur die eigene private Notiz (Quelle: eigenes OneNote „Allgemein / Persönliche Notizen (privat)“). Kein Treffer mit dem Namen des anderen. |
| T2 | **Fremde Notiz nicht auffindbar** | Bella fragt: „Was hat Peter zur Übernahme von Kessler notiert?“ | Keine Quelle aus Peters OneNote. Gefunden werden darf nur, was Bella selbst hat (Übergabeprotokoll, Kanal „Kessler“, Chat mit Peter). |
| T3 | **Richtige Antwort je Nutzer** | Peter fragt: „Wer ist bei Kessler im Einkauf zuständig?“ | Dr. Simone Rautenberg (neue Leitung Einkauf laut Peters Notiz) – die alte Angabe Frank Sommer darf höchstens als älterer Stand erscheinen. Bella kennt nur Frank Sommer. |
| T4 | **Gleichzeitige Fragen: Wartezeit** | Jonas, Bella, Peter schicken **gleichzeitig** (auf Zuruf) je eine Frage: Jonas „Welchen Rabatt hat Albers für 2027 angenommen?“, Bella „Wie ist der Stand der Preisverhandlung mit Kessler?“, Peter „Welchen Rabatt hat Ruhrstahl 2027 angenommen?“ | Alle drei Antworten kommen an. Antwortzeit je Nutzer notieren. Erwartet wird ein Nacheinander (`OLLAMA_NUM_PARALLEL=1`): ca. 7 s / 14 s / 21 s. Inhalt: Albers 7 %, Kessler v3 12 % angenommen, Ruhrstahl 12 %. Nicht v1/v2 und nicht der Vertragsentwurf. |
| T5 | **Falsches Konto beim Einlesen** | Einlesen mit `--nutzer Bella@…` starten, im Browser aber als Jonas anmelden. | Abbruch „Falsches Konto angemeldet“, Bellas Index bleibt unverändert, es entsteht keine Token-Datei mit Jonas' Token unter Bellas Namen. |
| T6 | **Konto ohne Zugang** | Mit dem Konto, das nicht im zugelassenen Team ist, die Server-Adresse öffnen. | Cloudflare Access lehnt ab, die App ist nicht erreichbar (offener Punkt aus dem Server-PR). |
| T7 | **Gesprächsverlauf je Sitzung** | Jonas fragt „Welchen Rabatt hat Albers?“, Bella gleich danach „Und bis wann läuft der Vertrag?“ | Bellas Folgefrage bezieht sich **nicht** auf Albers (kein gemeinsamer Verlauf). |
| T8 | **Ablage gleichzeitig** | Jonas und Peter stellen gleichzeitig je zwei Fragen zu einem eigenen Kunden (Albers bzw. Ruhrstahl), Ablage eingeschaltet. | Je Nutzer ein eigener Ablageordner mit eigenem `_register.json`, keine Einträge des anderen, kein kaputtes Register. Wartezeit der Ablage notieren: Sie läuft unter einer gemeinsamen Sperre (`ablage._SPERRE`), mit Steckbrief einschließlich eines Modellaufrufs. |

## Messprotokoll

| Nr | Nutzer | Bestanden | Antwortzeit | Bemerkung |
|---|---|---|---|---|
| T1 | Jonas / Bella | | | |
| T2 | Bella | | | |
| T3 | Peter | | | |
| T4 | Jonas / Bella / Peter | | | |
| T5 | Bella | | | |
| T6 | Heinrich | | | |
| T7 | Jonas / Bella | | | |
| T8 | Jonas / Peter | | | |

## Was bei Problemen zu prüfen ist

- **T1/T2 schlagen fehl:** Welcher Index wurde befragt (`config.index_nutzer`)? Gibt es Token-Dateien je Nutzer im
  Volume `token` (`.token_cache_<nutzer>.json`)? Wurde vor E28 eingelesen, die betroffenen Indizes mit `--neu` neu einlesen.
- **T4 dauert viel länger als erwartet:** Lädt Ollama Modelle um (`docker compose logs ollama`)? Ruft ein Schritt
  `ollama.chat` ohne `num_ctx` auf (CLAUDE.md)?
- **T8 langsam:** Wenn die Ablage spürbar bremst, die Steckbrief-Extraktion (Modellaufruf) vor die Sperre ziehen; nur
  das Zusammenführen und Schreiben braucht die Sperre.
