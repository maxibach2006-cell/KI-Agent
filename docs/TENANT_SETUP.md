# Test-Tenant für Microsoft Graph einrichten

Ziel ist eine eigene Microsoft-365-Umgebung mit Teams, Outlook, OneNote und SharePoint, in der du Admin bist. Dort legt `seed_graph.py` die fiktiven Kundendaten an.

## 1. Tenant besorgen (kostenlos)

**Option A: Microsoft 365 Developer Program (zuerst probieren)**
1. Auf https://developer.microsoft.com/microsoft-365/dev-program mit einem Microsoft-Konto anmelden.
2. „Join now“ und dann „Set up E5 subscription“ (Instant Sandbox).
3. Wird keine Sandbox angeboten (seit 2024 meist nur mit Visual-Studio-Abo), weiter mit Option B.

**Option B: Microsoft 365 Business Basic, 1 Monat Testversion**
1. Auf https://www.microsoft.com/microsoft-365/business/microsoft-365-business-basic den Link „Einen Monat kostenlos testen“ öffnen.
2. Neuen Tenant anlegen, z. B. `kam-pilot.onmicrosoft.com`. Du bist dann Global Admin.
3. Eine Kreditkarte ist nötig. **Im Admin Center unter „Abrechnung > Ihre Produkte“ die automatische Verlängerung sofort abschalten.**

## 2. Team anlegen
1. Unter https://teams.microsoft.com mit dem Admin-Konto des Tenants anmelden.
2. Neues Team **„Key Account - Kunden“** anlegen (Typ: Privat). Die Kanäle pro Kunde legt das Seed-Skript selbst an.
3. Einmal https://outlook.office.com und https://www.onenote.com öffnen, damit Postfach und OneDrive bereitgestellt werden. Beim ersten Mal kann das ein paar Minuten dauern.

## 3. App registrieren (Entra ID)
1. Auf https://entra.microsoft.com zu **Anwendungen > App-Registrierungen > Neue Registrierung** gehen.
   - Name: `KAM Informations-Agent`
   - Kontotypen: „Nur Konten in diesem Organisationsverzeichnis“
   - Umleitungs-URI: Plattform **„Öffentlicher Client/nativ (mobil & Desktop)“**, `https://login.microsoftonline.com/common/oauth2/nativeclient`
2. Unter **Authentifizierung** „Öffentliche Clientflows zulassen“ auf **Ja** setzen (nötig für den Device-Code-Login).
3. Unter **API-Berechtigungen > Berechtigung hinzufügen > Microsoft Graph > Delegierte Berechtigungen** diese Rechte hinzufügen:

   | Zweck | Berechtigungen |
   |---|---|
   | Lesen (Agent) | `User.Read`, `Notes.Read`, `Mail.Read`, `Calendars.Read`, `Chat.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `Files.Read.All`, `Sites.Read.All` |
   | Befüllen (nur Seed) | `Notes.ReadWrite`, `Mail.ReadWrite`, `Calendars.ReadWrite`, `ChannelMessage.Send`, `Channel.Create`, `Files.ReadWrite.All` |

4. **„Administratorzustimmung für … erteilen“** klicken. Als Admin des Test-Tenants darfst du das selbst.
5. Auf der Übersichtsseite **Anwendungs-ID (Client)** und **Verzeichnis-ID (Tenant)** kopieren.

## 4. Konfigurieren und befüllen
```bash
copy .env.example .env      # CLIENT_ID und TENANT_ID eintragen
python seed_graph.py        # Login per Code, legt Demo-Daten an
python ingest.py --source graph
streamlit run app.py        # in der Seitenleiste "Microsoft 365 (Graph)" wählen
```

## Hinweise
- Es gibt nur **delegierte** Rechte. Der Agent sieht deshalb genau das, was das angemeldete Konto sehen darf, und keine fremden Postfächer. Das setzt die Datenschutz-Vorgabe technisch um.
- Mails und OneNote-Seiten werden mit ihrem Originaldatum angelegt, z. B. 2019. Teams-Nachrichten lassen sich nicht rückdatieren. Das Seed-Skript schreibt deshalb `[Datum – Absender]` in die Nachricht, und `connectors/teams.py` liest das wieder aus.
- `.msg`-Dateien werden genauso unterstützt wie `.eml`. Für echte `.msg`-Dateien kannst du in Outlook (Desktop) eine Mail auf den Desktop ziehen und in die Team-Dateiablage hochladen.
