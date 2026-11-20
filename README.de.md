# untis-google-calendar-sync

🇬🇧 [English version](README.md)

Überträgt deinen **WebUntis**-Stundenplan in den **Google Kalender** und hält ihn aktuell.
Läuft als kleiner Docker-Container auf amd64 und arm64 (PC, Server, Raspberry Pi, ...).

**Was du bekommst**

- Jede Stunde als Kalendereintrag mit Raum, Lehrkraft, Hausaufgaben, Lehrstoff und Notizen
- Ausgefallene Stunden sind markiert (grau, durchgestrichen), Klausuren sind rot und haben einen eigenen Abschnitt
- Änderungen (Raum, Lehrkraft, Vertretung, Hausaufgaben, ...) aktualisieren den Eintrag automatisch
- Optionale Push-Benachrichtigungen über [ntfy](https://ntfy.sh), die **genau zeigen, was sich geändert hat**:

  ```
  Fr 13.11. 08:00 · Englisch LK (E L2)
    + Ausfall eingetragen
    ~ Raum: A101 → B202
    + Hausaufgabe: Aufgabe 3 fertig machen
  ```

- Texte im Kalender und in den Benachrichtigungen auf Deutsch oder Englisch (`LANGUAGE=de|en`)
- Einstellbarer Zeitplan (alle X Minuten in einem Zeitfenster und/oder zu festen Uhrzeiten), Healthcheck, eigene Fachnamen

> Inoffizielles Projekt, nicht mit der Untis GmbH oder Google verbunden. Es meldet sich bei WebUntis an, so wie es die Anmeldeseite in deinem Browser tut.
> Die Nutzung geschieht auf eigene Verantwortung. Prüfe die Regeln deiner Schule und wähle einen rücksichtsvollen Abstand zwischen den Läufen
> (jeder Lauf fragt WebUntis nach jeder Stunde der kommenden Wochen, deshalb sind 15 Minuten oder mehr empfehlenswert).

## Voraussetzungen

- Docker mit Docker Compose (v2)
- Ein WebUntis-Konto, bei dem du dich mit **Benutzername und Passwort** anmeldest.
  Schulen mit Single Sign-on (z. B. Microsoft- oder IServ-Anmeldung) werden **nicht unterstützt**
- Ein Google-Konto und ein kostenloses Google-Cloud-Projekt (einmalige Einrichtung weiter unten)

## Schnellstart

### 1. Google Cloud (einmalig, etwa 10 Minuten)

Du brauchst ein **eigenes** Google-Cloud-Projekt. Die Kalenderberechtigung ist ein „sensibler Bereich" (*sensitive scope*), ein gemeinsames Projekt
wäre deshalb eingeschränkt und nicht verifiziert. Mit deinem eigenen Projekt ist niemand sonst beteiligt.

Die Google-Konsole zeigt ihre Menüs je nach Spracheinstellung deutsch oder englisch. Hier stehen die englischen Namen; wenn du dich nicht zurechtfindest,
stelle die Sprache deines Google-Kontos vorübergehend auf Englisch.

1. Öffne <https://console.cloud.google.com> und lege ein Projekt an. Gib ihm einen Namen und wähle es aus.
2. Öffne im linken Menü **APIs & Services** (*APIs & Dienste*), dann **Library** (*Bibliothek*). Suche nach **Google Calendar API**, öffne sie und klicke auf **Enable** (*Aktivieren*).
3. Öffne den **OAuth consent screen** (heißt jetzt **Google Auth Platform**). Wenn **Get started** erscheint, klicke darauf und folge den ersten Schritten: Gib einen App-Namen und deine E-Mail-Adresse ein, wähle die Zielgruppe **External**, trage deine E-Mail-Adresse als Kontakt ein und akzeptiere die Bedingungen.
4. Öffne im linken Menü **Branding** und trage die Links der App ein (Google verlangt sie unter Umständen, bevor du die App veröffentlichen kannst):
   - **Application home page**
   - **Application privacy policy link**
   - **Application terms of service link**

   Für den persönlichen Gebrauch können sie auf eine beliebige öffentliche Seite (oder auf dieses Repo) zeigen. Verlangt die Konsole mehr (zum Beispiel **Authorized domains** für die eingetragenen Links), folge ihren Hinweisen.
5. Öffne im linken Menü **Audience** und klicke auf **Publish app**. Der Status muss von „Testing" auf **„In production"** wechseln. Mache das **bevor** du dich anmeldest:
   Im Status „Testing" macht Google die Anmeldung nach 7 Tagen ungültig. Bietet Google eine Verifizierung an, kannst du sie überspringen, für den persönlichen Gebrauch ist sie nicht nötig.
6. Öffne im linken Menü **Clients** und klicke auf **Create client**. Der Anwendungstyp muss
   **„TVs and Limited Input devices"** sein (nicht „Desktop app"). Kopiere die **Client ID** und das **Client secret** sofort,
   Google zeigt das Secret später unter Umständen nicht mehr an. Beide trägst du in Schritt 2 unten in die `.env` ein.

### 2. Ordner einrichten

```bash
mkdir untis-sync && cd untis-sync
curl -fsSLO https://raw.githubusercontent.com/MyName-99a/untis-google-calendar-sync/main/compose.yaml
curl -fsSL https://raw.githubusercontent.com/MyName-99a/untis-google-calendar-sync/main/.env.example -o .env
mkdir data
```

Lege den Ordner `data` selbst an. Wenn Docker ihn anlegt, gehört er root und der Container kann nicht hineinschreiben.

Bearbeite die `.env` und trage mindestens `UNTIS_SERVER`, `UNTIS_USER`, `UNTIS_PASSWORD`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
und `TZ` ein. Setze außerdem `LANGUAGE=de`, wenn die Texte im Kalender und in den Benachrichtigungen deutsch sein sollen (Standard ist Englisch).
Unter Linux setzt du `PUID` und `PGID` auf die Ausgabe von `id -u` und `id -g`.

**Tipp:** Wenn du erst einmal mit einem separaten Testkalender ausprobieren möchtest, lege im Google Kalender einen an und trage seine ID in `CALENDAR_ID` ein. Sonst nimm `primary`. Außerdem: `.env` beginnt mit einem Punkt, deshalb zeigt `ls` die Datei nicht an. Mit `ls -a` siehst du sie, mit `nano .env` bearbeitest du sie.

### 3. Bei Google anmelden (einmalig)

```bash
docker compose run --rm untis-sync python auth.py
```

Das Programm zeigt einen Code an. Öffne <https://www.google.com/device> auf einem beliebigen Gerät (dein Handy genügt), gib den Code ein,
melde dich mit dem Google-Konto an, dem der Kalender gehört, und bestätige.

**Du siehst die Warnung „Google hat diese App nicht überprüft" („Google hasn't verified this app"). Das ist normal und zu erwarten** bei einem eigenen Projekt:
Klicke auf *Erweitert* (*Advanced*), dann auf *Weiter* (*Continue*). Du bist der Entwickler und der einzige Nutzer.

Die Anmeldung wird in `data/token.json` gespeichert und erneuert sich selbstständig.

### 4. Starten

```bash
docker compose up -d
docker compose logs -f untis-sync
```

Der erste Lauf legt alle Einträge an und dauert einige Minuten. Nach etwa 90 Sekunden zeigt `docker compose ps` den Status `healthy`.

## Konfiguration

Alle Einstellungen sind Umgebungsvariablen in der `.env`.

| Variable | Standard | Bedeutung |
|---|---|---|
| `UNTIS_SERVER` | | Adresse der Schule, z. B. `deine-schule.webuntis.com` |
| `UNTIS_USER`, `UNTIS_PASSWORD` | | WebUntis-Anmeldung |
| `UNTIS_SCHOOL` | | Anmeldename der Schule. Nur nötig, wenn das Programm meldet, dass es ihn nicht finden kann |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | | OAuth-Client vom Typ „TVs and Limited Input devices" |
| `CALENDAR_ID` | `primary` | Zielkalender (`primary` = Hauptkalender) |
| `LANGUAGE` | `en` | Sprache der Kalendereinträge und Push-Benachrichtigungen: `en` oder `de`. Die Logs sind immer englisch |
| `TZ` | `Europe/Berlin` | Zeitzone der Schule. Gilt für den Zeitplan, die Logs und die Kalendereinträge |
| `SYNC_WEEKS_AHEAD` | `12` | Wie viele Wochen im Voraus synchronisiert werden |
| `SYNC_INTERVAL_MINUTES` | `5` (`0`, wenn `SYNC_TIMES` gesetzt ist) | Minuten zwischen zwei Läufen (gezählt ab dem Start des letzten Laufs), `0` = kein Intervall |
| `SYNC_WINDOW` | | Das Intervall läuft nur in diesem Zeitfenster, z. B. `06:00-19:00` (leer = ganztägig) |
| `SYNC_TIMES` | | Zusätzliche Läufe zu festen Uhrzeiten, z. B. `21:00,21:30,22:00`. Sie laufen auch außerhalb des Zeitfensters |
| `SYNC_DAYS` | `1-7` | Wochentage für Intervall und feste Uhrzeiten, `1` = Montag ... `7` = Sonntag, z. B. `1-5` oder `1,3,5` |
| `SYNC_RUN_ON_START` | `true` | Beim Start des Containers sofort einmal laufen |
| `SYNC_TIMEOUT_MINUTES` | `15` | Ein hängender Lauf wird nach dieser Zeit beendet |
| `NTFY_TOPIC` | | ntfy-Topic für Benachrichtigungen (leer = keine) |
| `NTFY_SERVER` | `https://ntfy.sh` | Nimm deinen eigenen ntfy-Server, falls du einen hast |
| `CANCEL_KEYWORDS` | `eigenverantwortliches arbeiten` | Formulierungen (kommagetrennt, Groß-/Kleinschreibung egal), die eine Stunde als ausgefallen markieren, wenn sie in ihren Infotexten vorkommen. Siehe [Ausgefallene Stunden](#ausgefallene-stunden) |
| `FACH_MAP_USE_DEFAULTS` | `true` | `false` = nur deine eigene `fach_map.json` verwenden. **Setze es auf `false`, wenn deine Schule nicht die deutsche Schule ist, für die die eingebaute Tabelle gemacht wurde** (siehe [Fachnamen](#fachnamen)) |
| `PUID`, `PGID` | `1000` | Besitzer der Dateien in `./data` |

### Zeitplan

Du kannst ein Intervall, feste Uhrzeiten oder beides verwenden:

| Du möchtest | Einstellungen in der `.env` |
|---|---|
| Alle 5 Minuten, ganztägig | nichts (Standard) |
| Alle 5 Minuten zwischen 06:00 und 19:00 an Wochentagen | `SYNC_INTERVAL_MINUTES=5`, `SYNC_WINDOW=06:00-19:00`, `SYNC_DAYS=1-5` |
| Nur zu festen Uhrzeiten | `SYNC_TIMES=06:30,12:00,17:30` |
| Intervall tagsüber **und** ein paar Läufe am Abend | `SYNC_INTERVAL_MINUTES=4`, `SYNC_WINDOW=06:00-20:59`, `SYNC_TIMES=21:00,21:30,22:00,22:30` |
| Nichts automatisch, nur wenn du es startest | `SYNC_INTERVAL_MINUTES=0` (und kein `SYNC_TIMES`) |

Das Zeitfenster gilt nur für das Intervall, feste Uhrzeiten laufen zu ihrer Zeit. Ist nichts geplant, synchronisiert der Container einmal beim Start
(`SYNC_RUN_ON_START`) und wartet dann. Deinen Zeitplan prüfst du, ohne etwas zu starten, so:

```bash
docker compose run --rm untis-sync python run_loop.py --plan
```

Einen Lauf sofort ausführen (unabhängig vom Zeitplan), zum Beispiel zum Testen:

```bash
docker compose run --rm untis-sync python run_loop.py --once
```

### Fachnamen

WebUntis liefert Kürzel (`M`, `E-LK`, ...). Die eingebaute Tabelle ordnet ihnen **deutsche** Fachnamen zu und wurde für eine
deutsche Schule gemacht (diese Namen werden nicht übersetzt, `LANGUAGE` ändert sie nicht). Für eigene Namen kopierst du
`fach_map.example.json` nach `data/fach_map.json` und bearbeitest sie. Der Schlüssel ist der Anfang des Kürzels, deine Einträge haben Vorrang,
und längere Kürzel sollten vor kürzeren stehen.

Ist deine Schule **keine** deutsche Schule mit denselben Kürzeln, setze `FACH_MAP_USE_DEFAULTS=false` in der `.env`. Dann wird nur deine eigene
`data/fach_map.json` verwendet, und Kürzel, die dort nicht stehen, werden unverändert angezeigt. Ohne diese Einstellung würde ein Kürzel wie `M` oder `E`
trotzdem zu `Mathematik` oder `Englisch`.

Zeigt deine Schule im Stundenplan mehr als drei Positionsspalten (Raum, Lehrkraft, Fach, ...), muss der Code, der sie liest
(`process_positions` in `get_week_and_lesson_information.py`), erweitert werden.

### Ausgefallene Stunden

Eine Stunde gilt als ausgefallen (grau, durchgestrichen), wenn WebUntis sie als ausgefallen markiert. Manche Schulen tun das nicht, sie schreiben stattdessen
eine Formulierung wie „eigenverantwortliches Arbeiten" in den Info- oder Vertretungstext. Trage solche Formulierungen in `CANCEL_KEYWORDS` ein
(kommagetrennt, Groß-/Kleinschreibung egal), z. B. `CANCEL_KEYWORDS=Selbststudium,Raum frei`. Der Standard ist die Formulierung meiner deutschen Schule.

### Sprache

`LANGUAGE=en` (Standard) oder `LANGUAGE=de` bestimmt die Sprache von allem, was du im Kalender siehst (Titel, Abschnittsüberschriften,
„Keine Hausis", ...) und in den Benachrichtigungen. Wenn du sie später änderst, werden beim nächsten Lauf einmalig alle Einträge neu geschrieben, ohne
Benachrichtigung. Logs und Konsolenausgaben sind immer englisch. Weitere Sprachen lassen sich in `texts.py` ergänzen.

### Benachrichtigungen

Installiere die ntfy-App, abonniere einen schwer zu erratenden Topic-Namen und trage ihn in `NTFY_TOPIC` ein. Du bekommst pro Lauf eine Nachricht,
die Änderungen enthält, mit einer Zeile pro Änderung (`+` hinzugefügt, `−` entfernt, `~` geändert). Wichtige Änderungen
(Ausfälle, Klausuren, Raum, Lehrkraft, Hausaufgaben) haben hohe Priorität.

Außerdem bekommst du eine Nachricht, wenn etwas schiefgeht, zum Beispiel wenn WebUntis oder Google nicht erreichbar sind oder eine Anmeldung
abgelehnt wird. Dieselbe Art von Fehler wird einmal gemeldet und danach höchstens alle 6 Stunden (Anmeldeprobleme: einmal pro Tag), damit eine lange
Störung dein Handy nicht füllt. Läuft der Sync wieder, sagt dir eine weitere Nachricht Bescheid und seit wann er unterbrochen war.

## Aufräumen und deinstallieren

`cleanup.py` entfernt die Einträge, die der Sync angelegt hat, zum Beispiel um von vorn anzufangen, um Duplikate zu entfernen oder wenn du den
Sync nicht mehr nutzen möchtest. Es berührt nur Einträge, die von diesem Programm angelegt wurden (erkennbar an der Zeile `Untis-Sync-ID` bei zukünftigen
Einträgen und an der Abschlusszeile bei vergangenen Stunden), sonst nichts in deinem Kalender. Ohne Optionen zeigt es nur an, was es löschen würde.

```bash
docker compose stop                                              # damit der Sync die Einträge zwischendurch nicht neu anlegt
docker compose run --rm untis-sync python cleanup.py             # Probelauf: zeigt, was gelöscht würde
docker compose run --rm untis-sync python cleanup.py --delete    # löscht die zukünftigen Einträge (fragt vorher nach)
docker compose start
```

| Option | Bedeutung |
|---|---|
| `--duplicates` | Nur Duplikate (dieselbe Stunde mehrfach), pro Stunde bleibt ein Eintrag erhalten |
| `--weeks N` | N Wochen in die Zukunft suchen (Standard 52) |
| `--past-days N` | Auch N Tage in die Vergangenheit suchen |
| `--all` | Jeden Eintrag, den der Sync je angelegt hat, vergangene und zukünftige, und die gespeicherten Hashes werden zurückgesetzt |
| `--yes` | Keine Rückfrage (nötig ohne Terminal) |

So entfernst du alles und hörst auf, den Sync zu nutzen:

```bash
docker compose stop
docker compose run --rm untis-sync python cleanup.py --all --delete
docker compose down
```

Lösche danach den Projektordner (einschließlich `data/`) und entziehe den Zugriff unter <https://myaccount.google.com/permissions>.

## Update

```bash
docker compose pull
docker compose up -d
```

Releases sind getaggt (`1.0.0`, `1.0`, `latest`). Ersetze `latest` in der `compose.yaml` durch eine Version, um sie festzuhalten.

## Selbst bauen / ohne Docker

```bash
git clone https://github.com/MyName-99a/untis-google-calendar-sync.git
cd untis-google-calendar-sync
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Ohne Docker (Python 3.10+):

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # und ausfüllen
python auth.py                             # einmalig bei Google anmelden
python run_loop.py
```

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| „Google hat diese App nicht überprüft" („Google hasn't verified this app") | Normal. Klicke auf *Erweitert* (*Advanced*), dann auf *Weiter* (*Continue*) |
| Die Anmeldung funktioniert nach 7 Tagen nicht mehr | Der Zustimmungsbildschirm stand noch auf „Testing". Veröffentliche ihn („In production") und führe dann `python auth.py --force` erneut aus |
| ntfy-Nachricht „Google-Anmeldung ungültig" (englisch: „Google login invalid") | Der Zugriff wurde widerrufen oder ist abgelaufen. Führe `docker compose run --rm untis-sync python auth.py --force` aus |
| `invalid_client` bei der Anmeldung | Falsche Client-ID, oder der Client ist nicht vom Typ „TVs and Limited Input devices" |
| `Permission denied` in `/data` | Lege `data` selbst an und setze `PUID`/`PGID` auf deine Werte von `id -u` / `id -g` |
| Das WebUntis-Passwort enthält `$` | Setze es in der `.env` in einfache Anführungszeichen: `UNTIS_PASSWORD='...'` |
| Der Container ist `unhealthy` | Drei Läufe hintereinander sind fehlgeschlagen, oder die Schleife hängt. Siehe `docker compose logs --tail 100 untis-sync` und `data/sync_log.txt` |
| Die Anmeldung bei WebUntis schlägt fehl | Prüfe Server, Benutzername und Passwort (teste sie auf der Webseite). Schulen mit Single Sign-on werden nicht unterstützt. Nach einer fehlgeschlagenen Anmeldung wartet das Programm 30 Minuten, bevor es es erneut versucht, damit dein Konto nicht gesperrt wird. Eine geänderte `.env` beendet das Warten sofort. Funktioniert die Anmeldung für deine Schule nie, meldet sich das Image `ghcr.io/myname-99a/untis-google-calendar-sync:1.3` noch mit einem Browser an (`UNTIS_LOGIN=browser`). Bitte eröffne ein Issue |
| Einträge sind doppelt oder der Kalender ist durcheinander | `docker compose stop`, dann `python cleanup.py --duplicates --delete`, oder mit `--delete` von vorn anfangen. Siehe [Aufräumen und deinstallieren](#aufräumen-und-deinstallieren) |
| Falsche, fehlende oder deutsche Fachnamen | Trage sie in `data/fach_map.json` ein. Für eine nicht deutsche Schule setze außerdem `FACH_MAP_USE_DEFAULTS=false` |

## Hinweise

- Deine Zugangsdaten bleiben auf deinem Rechner. Das Programm spricht nur mit WebUntis, Google und (optional) ntfy.
- Die Google-Berechtigung ist der volle Kalenderzugriff (alle Kalender des Kontos lesen und schreiben), weil das Programm Einträge anlegt
  und aktualisiert. Halte `data/token.json` und `.env` geheim und erwäge, über `CALENDAR_ID` einen eigenen Kalender zu verwenden.
- Ein vollständiger Lauf dauert einige Minuten, weil die Details (Hausaufgaben, Lehrstoff, Klausuren) pro Stunde abgefragt werden.
