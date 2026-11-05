# Testdaten für den Tenant KAMPilot

Fiktive Daten für **alle aktiven Testnutzer** (außer dem Admin, der die bisherigen Demo-Daten aus `demo_data/` hat):
20 Kunden, je ca. 10–14 Dateien in bewusst unordentlichen OneDrive-Ordnern, dazu OneNote „MBS 2“, Mails,
Termine, Teams-Kanäle (Team „KAM-Pilot“) und Chats. Nutzer sind über gemeinsame Kunden, Mails, Termine und
Chats verbunden. `demo_data/` wird nicht verändert.

| Datei | Aufgabe |
|---|---|
| `kunden.py` | Nutzer, 20 Kunden, Geschichten (Reklamation, Übergabe, Audit …), feste Fakten |
| `erzeuge.py` | erzeugt Dateien und `ausgabe/plan.json` (nicht im Repo, jederzeit identisch neu erzeugbar) |
| `seed_tenant.py` | lädt den Plan für einen Nutzer hoch (Login per Gerätecode als dieser Nutzer) |

```bash
python demo_tenant/erzeuge.py              # Übersicht: demo_tenant/ausgabe/UEBERSICHT.md
python demo_tenant/seed_tenant.py jonas    # für jeden Nutzer einmal, Kürzel siehe kunden.NUTZER
```

Absichtliche Fallen für den Agenten: Angebote v1/v2/v3 mit verschiedenen Rabatten, Duplikate („(1)“, „final_neu“),
Vertragsentwürfe mit alten Konditionen, veraltete Kundenprofile, abweichende Angaben zwischen Nutzern
(Kessler: neuer Einkauf und Nachverhandlung nur in Peters Notiz).
