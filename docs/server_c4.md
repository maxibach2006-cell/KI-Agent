# So ist der KAM-Agent aufgebaut

Der KAM-Agent beantwortet Fragen aus den eigenen Microsoft-365-Daten, jede Aussage mit Quelle. Die beiden Bilder zeigen
den Aufbau nach dem C4-Modell: erst aus großer Entfernung, dann mit einem Blick ins Innere des Servers.

## Ebene 1: Das Gesamtbild

Wer nutzt das System, und mit welchen Diensten arbeitet es zusammen?

```mermaid
flowchart LR
    nutzer(["<b>Mitarbeitende</b><br/>stellen Fragen<br/>im Browser"])
    cloudflare["<b>Cloudflare</b><br/>Pförtner im Internet:<br/>lässt nur das Team hinein"]
    agent["<b>KAM-Agent</b><br/>findet passende Stellen<br/>und antwortet mit Quelle"]
    microsoft["<b>Microsoft 365</b><br/>Anmeldung, Mails, Kalender,<br/>OneNote, Teams, Dateien"]

    nutzer -- "öffnet die Seite" --> cloudflare
    cloudflare -- "prüft die Anmeldung" --> microsoft
    cloudflare -- "leitet weiter" --> agent
    agent -- "liest die Daten<br/>nach Freigabe" --> microsoft

    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef extern fill:#6b7280,stroke:#4b5563,color:#ffffff
    class nutzer person
    class agent system
    class cloudflare,microsoft extern
```

| Baustein | Aufgabe |
|---|---|
| **Mitarbeitende** | Stellen ihre Fragen im Browser und sehen nur die eigenen Daten. |
| **Cloudflare** | Prüft am Eingang, wer hineindarf. So ist der Server nicht offen im Internet erreichbar. |
| **KAM-Agent** | Unser System: Es sucht die passenden Textstellen und formuliert daraus die Antwort. |
| **Microsoft 365** | Bestätigt die Anmeldung und liefert die Daten. Jede Person gibt den Zugriff einmal selbst frei. |

## Ebene 2: Ein Blick in den Server

Woraus besteht der KAM-Agent? Jeder blaue Kasten ist ein eigener, abgetrennter Baustein auf dem Server.

```mermaid
flowchart LR
    nutzer(["<b>Mitarbeitende</b><br/>im Browser"])
    cloudflare["<b>Cloudflare</b><br/>Pförtner im Internet"]
    microsoft["<b>Microsoft 365</b><br/>Daten und Anmeldung"]

    subgraph server["Server: PC mit Grafikkarte, darauf eine abgeschirmte Linux-Umgebung"]
        direction LR
        tunnel["<b>Tunnel</b><br/>sichere Leitung<br/>zu Cloudflare"]
        app["<b>Agent-App</b><br/>Webseite, Suche<br/>und Einlesen"]
        modell["<b>Sprachmodell</b><br/>versteht und formuliert<br/>auf der Grafikkarte"]
        speicher[("<b>Speicher</b><br/>Suchindex und Ablage<br/>je Person, Anmeldetoken")]
    end

    nutzer -- "öffnet die Seite" --> cloudflare
    cloudflare -- "leitet weiter" --> tunnel
    tunnel -- "reicht die Frage durch" --> app
    app -- "schickt Stellen und Frage,<br/>bekommt die Antwort" --> modell
    app -- "sucht und speichert" --> speicher
    app -- "liest neue Daten" --> microsoft

    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef baustein fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef extern fill:#6b7280,stroke:#4b5563,color:#ffffff
    class nutzer person
    class tunnel,app,modell,speicher baustein
    class cloudflare,microsoft extern
    style server fill:#eef4fb,stroke:#1168bd,stroke-dasharray:6 4,color:#0b4884
```

| Baustein | Aufgabe |
|---|---|
| **Tunnel** | Baut die Verbindung von innen nach außen auf. Am Router ist deshalb kein Eingang offen. |
| **Agent-App** | Das Herzstück: zeigt die Webseite, sucht die passenden Stellen und liest neue Daten ein. |
| **Sprachmodell** | Läuft auf dem Server selbst, Fragen und Daten gehen an keinen KI-Anbieter. Aus dem Tunnel ist es nicht erreichbar. |
| **Speicher** | Hält je Person einen eigenen Suchindex und eine eigene Ablage. So bleiben die Daten getrennt. |

**Beispiel einer Frage:** Die Frage läuft über Cloudflare und den Tunnel zur Agent-App. Diese sucht im Speicher der
angemeldeten Person die passenden Stellen und gibt sie dem Sprachmodell. Die fertige Antwort geht mit Quellen zurück.
Bei Microsoft 365 wird dafür nicht nachgefragt: Die Daten liegen schon vorab eingelesen im Speicher.
