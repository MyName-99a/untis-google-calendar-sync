# untis-google-calendar-sync

Syncs your **WebUntis** timetable to **Google Calendar** and keeps it up to date.
Runs as a small Docker container on amd64 and arm64 (PC, server, Raspberry Pi, ...).

**What you get**

- Every lesson as a calendar event with room, teacher(s), homework, teaching content and notes
- Cancelled lessons are marked (grey, struck through), exams are red and get their own section
- Changes (room, teacher, substitution, homework, ...) update the event automatically
- Optional push notifications via [ntfy](https://ntfy.sh) that show **exactly what changed**:

  ```
  Fri 13 Nov 08:00 · English (E L2)
    + Marked as cancelled
    ~ Room: A101 → B202
    + Homework: Finish exercise 3
  ```

- Calendar and notification texts in English or German (`LANGUAGE=en|de`)
- Configurable schedule (every X minutes inside a time window and/or at fixed times), healthcheck, custom subject names

> Unofficial project, not affiliated with Untis GmbH or Google. It logs in to WebUntis like your browser's login page does.
> Use it at your own risk, check your school's rules, and keep the interval polite
> (every run asks WebUntis for every lesson of the coming weeks, so 15 minutes or more is recommended).

## Requirements

- Docker with Docker Compose (v2)
- A WebUntis account that logs in with **username and password**.
  Schools that use single sign-on (e.g. Microsoft or IServ login) are **not supported**
- A Google account and a free Google Cloud project (one-time setup below)

## Quick start

### 1. Google Cloud (one time, about 10 minutes)

You need your **own** Google Cloud project. The calendar permission is a "sensitive scope", so a shared project
would be limited and unverified. With your own project nobody else is involved.

1. Open <https://console.cloud.google.com> and create a project. Give it a name and select it.
2. In the left menu open **APIs & Services**, then **Library**. Search for **Google Calendar API**, open it and click **Enable**.
3. Open the **OAuth consent screen** (now called **Google Auth Platform**). If you see **Get started**, click it and follow the first steps: enter an app name and your email, choose the audience **External**, add your email as contact and accept the terms.
4. Open **Branding** in the left menu and fill in the app links (Google may require them before you can publish the app):
   - **Application home page**
   - **Application privacy policy link**
   - **Application terms of service link**

   For personal use these can point to any public page (or this repo). If the console asks for more (for example **Authorized domains** for the links you entered), follow its hints.
5. Open **Audience** in the left menu and click **Publish app**. The status must change from "Testing" to **"In production"**. Do this **before** you sign in:
   in "Testing" status Google invalidates the login after 7 days. If Google offers a verification, you can skip it, it is not needed for personal use.
6. Open **Clients** in the left menu and click **Create client**. The application type must be
   **"TVs and Limited Input devices"** (not "Desktop app"). Copy the **Client ID** and the **Client secret** right away,
   Google may not show the secret again later. You will enter both into `.env` in step 2 below.

### 2. Set up the folder

```bash
mkdir untis-sync && cd untis-sync
curl -fsSLO https://raw.githubusercontent.com/MyName-99a/untis-google-calendar-sync/main/compose.yaml
curl -fsSL https://raw.githubusercontent.com/MyName-99a/untis-google-calendar-sync/main/.env.example -o .env
mkdir data
```

Create the `data` folder yourself. If Docker creates it, it belongs to root and the container cannot write to it.

Edit `.env` and fill in at least `UNTIS_SERVER`, `UNTIS_USER`, `UNTIS_PASSWORD`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
and `TZ`. On Linux set `PUID` and `PGID` to the output of `id -u` and `id -g`.

**Tip:** If you like to try it with a separate test calendar first. Create one in Google Calendar and put its ID into `CALENDAR_ID`. Otherwise use `primary`. Also: `.env` starts with a dot, so `ls` does not show it. Use `ls -a` to see it and `nano .env` to edit it.

### 3. Sign in to Google (once)

```bash
docker compose run --rm untis-sync python auth.py
```

The program shows a code. Open <https://www.google.com/device> on any device (your phone is fine), enter the code,
sign in with the Google account that owns the calendar and confirm.

**You will see the warning "Google hasn't verified this app". That is normal and expected** for your own project:
click *Advanced*, then *Continue*. You are the developer and the only user.

The login is stored in `data/token.json` and renews itself automatically.

### 4. Start

```bash
docker compose up -d
docker compose logs -f untis-sync
```

The first run creates all events and takes a few minutes. After about 90 seconds `docker compose ps` shows `healthy`.

## Configuration

All settings are environment variables in `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `UNTIS_SERVER` | | School address, e.g. `your-school.webuntis.com` |
| `UNTIS_USER`, `UNTIS_PASSWORD` | | WebUntis login |
| `UNTIS_LOGIN` | `http` | `http` = plain HTTP requests (fast, no browser). `browser` = headless Chromium, a fallback if `http` does not work for your school |
| `UNTIS_SCHOOL` | | Login name of the school. Only needed if the program says it cannot find it |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | | OAuth client of type "TVs and Limited Input devices" |
| `CALENDAR_ID` | `primary` | Target calendar (`primary` = main calendar) |
| `LANGUAGE` | `en` | Language of the calendar events and push notifications: `en` or `de`. Logs are always English |
| `TZ` | `Europe/Berlin` | Time zone of the school. Used for the schedule, logs and calendar events |
| `SYNC_WEEKS_AHEAD` | `12` | Weeks to sync in advance |
| `SYNC_INTERVAL_MINUTES` | `5` (`0` if `SYNC_TIMES` is set) | Minutes between two runs (counted from the start of the last run), `0` = no interval |
| `SYNC_WINDOW` | | The interval runs only in this window, e.g. `06:00-19:00` (empty = all day) |
| `SYNC_TIMES` | | Additional runs at fixed times, e.g. `21:00,21:30,22:00`. They also run outside the window |
| `SYNC_DAYS` | `1-7` | Weekdays for interval and fixed times, `1` = Monday ... `7` = Sunday, e.g. `1-5` or `1,3,5` |
| `SYNC_RUN_ON_START` | `true` | Run once immediately when the container starts |
| `SYNC_TIMEOUT_MINUTES` | `15` | A hanging run is stopped after this time |
| `NTFY_TOPIC` | | ntfy topic for notifications (empty = none) |
| `NTFY_SERVER` | `https://ntfy.sh` | Use your own ntfy server if you have one |
| `CANCEL_KEYWORDS` | `eigenverantwortliches arbeiten` | Phrases (comma separated, not case sensitive) that mark a lesson as cancelled when they appear in its info texts. See [Cancelled lessons](#cancelled-lessons) |
| `FACH_MAP_USE_DEFAULTS` | `true` | `false` = use only your own `fach_map.json`. **Set it to `false` if your school is not the German school the built-in table was made for** (see [Subject names](#subject-names)) |
| `PUID`, `PGID` | `1000` | Owner of the files in `./data` |

### Schedule

You can use an interval, fixed times, or both:

| You want | Settings in `.env` |
|---|---|
| Every 5 minutes, all day | nothing (default) |
| Every 5 minutes between 06:00 and 19:00 on weekdays | `SYNC_INTERVAL_MINUTES=5`, `SYNC_WINDOW=06:00-19:00`, `SYNC_DAYS=1-5` |
| Only at fixed times | `SYNC_TIMES=06:30,12:00,17:30` |
| Interval during the day **and** a few runs in the evening | `SYNC_INTERVAL_MINUTES=4`, `SYNC_WINDOW=06:00-20:59`, `SYNC_TIMES=21:00,21:30,22:00,22:30` |
| Nothing automatic, only when you start it | `SYNC_INTERVAL_MINUTES=0` (and no `SYNC_TIMES`) |

The window only applies to the interval, fixed times run at their time. If nothing is scheduled the container syncs once on start
(`SYNC_RUN_ON_START`) and then waits. Check your schedule without starting anything:

```bash
docker compose run --rm untis-sync python run_loop.py --plan
```

Run one sync right now (independent of the schedule), for example for testing:

```bash
docker compose run --rm untis-sync python run_loop.py --once
```

### Subject names

WebUntis delivers short codes (`M`, `E-LK`, ...). The built-in table maps them to **German** subject names and is made for one
German school (these names are not translated, `LANGUAGE` does not change them). To use your own, copy
`fach_map.example.json` to `data/fach_map.json` and edit it. The key is the beginning of the code, your entries win,
and longer codes should be listed before shorter ones.

If your school is **not** a German school with the same codes, set `FACH_MAP_USE_DEFAULTS=false` in `.env`. Then only your own
`data/fach_map.json` is used, and codes that are not in it are shown as they are. Without this setting a code like `M` or `E`
would still be turned into `Mathematik` or `Englisch`.

If your school shows more than three position columns (room, teacher, subject, ...) in the timetable, the code that reads
them (`process_positions` in `get_week_and_lesson_information.py`) needs to be extended.

### Cancelled lessons

A lesson counts as cancelled (grey, struck through) when WebUntis marks it as cancelled. Some schools do not do that, they write a
phrase like "work on your own" into the info or substitution text instead. Put such phrases into `CANCEL_KEYWORDS`
(comma separated, not case sensitive), e.g. `CANCEL_KEYWORDS=self-study,room free`. The default is the phrase of my German school.

### Language

`LANGUAGE=en` (default) or `LANGUAGE=de` sets the language of everything you see in the calendar (titles, section headers,
"No homework", ...) and in the notifications. If you change it later, all events are rewritten once on the next run, without a
notification. Logs and console output are always English. Another language can be added in `texts.py`.

### Notifications

Install the ntfy app, subscribe to a hard-to-guess topic name and put it into `NTFY_TOPIC`. You get one message per run
that contains changes, with a line per change (`+` added, `−` removed, `~` changed). Important changes
(cancellations, exams, room, teacher, homework) have high priority.

## Clean up and uninstall

`cleanup.py` removes the events the sync created, for example to start over, to remove duplicates, or when you do not want to use
the sync any more. It only touches events that were created by this program (recognized by the `Untis-Sync-ID` line in future
events and by the closing line of finished lessons), nothing else in your calendar. Without options it only shows what it would delete.

```bash
docker compose stop                                              # so the sync cannot recreate events meanwhile
docker compose run --rm untis-sync python cleanup.py             # dry run: shows what would be deleted
docker compose run --rm untis-sync python cleanup.py --delete    # deletes the future events (asks first)
docker compose start
```

| Option | Meaning |
|---|---|
| `--duplicates` | Only duplicates (the same lesson more than once), one event per lesson is kept |
| `--weeks N` | Look N weeks ahead (default 52) |
| `--past-days N` | Also look N days into the past |
| `--all` | Every event the sync ever created, past and future, and the saved hashes are reset |
| `--yes` | No confirmation prompt (needed without a terminal) |

To remove everything and stop using the sync:

```bash
docker compose stop
docker compose run --rm untis-sync python cleanup.py --all --delete
docker compose down
```

Then delete the project folder (including `data/`), and revoke the access at <https://myaccount.google.com/permissions>.

## Update

```bash
docker compose pull
docker compose up -d
```

Releases are tagged (`1.0.0`, `1.0`, `latest`). Replace `latest` in `compose.yaml` with a version to pin it.

## Build it yourself / without Docker

```bash
git clone https://github.com/MyName-99a/untis-google-calendar-sync.git
cd untis-google-calendar-sync
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Without Docker (Python 3.10+):

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium    # only for UNTIS_LOGIN=browser, --with-deps needs sudo on Linux
cp .env.example .env                       # and fill it in
python auth.py                             # sign in to Google once
python run_loop.py
```

## Troubleshooting

| Problem | Solution |
|---|---|
| "Google hasn't verified this app" | Normal. Click *Advanced*, then *Continue* |
| Login stops working after 7 days | The consent screen was still in "Testing". Publish it ("In production"), then run `python auth.py --force` again |
| ntfy message "Google login invalid" (German: "Google-Anmeldung ungültig") | Access was revoked or expired. Run `docker compose run --rm untis-sync python auth.py --force` |
| `invalid_client` during sign-in | Wrong client ID, or the client is not of type "TVs and Limited Input devices" |
| `Permission denied` in `/data` | Create `data` yourself and set `PUID`/`PGID` to your `id -u` / `id -g` |
| WebUntis password contains `$` | Put it in single quotes in `.env`: `UNTIS_PASSWORD='...'` |
| Container is `unhealthy` | Three runs in a row failed, or the loop is stuck. See `docker compose logs --tail 100 untis-sync` and `data/sync_log.txt` |
| Login to WebUntis fails | Check server, user and password (test them on the website). Single sign-on schools are not supported. After a failed login the program waits 30 minutes before it tries again, so your account is not locked. A changed `.env` ends the wait at once. If your school needs something else, try `UNTIS_LOGIN=browser` |
| Events are duplicated or the calendar is messy | `docker compose stop`, then `python cleanup.py --duplicates --delete`, or start over with `--delete`. See [Clean up and uninstall](#clean-up-and-uninstall) |
| Wrong, missing or German subject names | Add them to `data/fach_map.json`. For a non-German school also set `FACH_MAP_USE_DEFAULTS=false` |

## Notes

- Your credentials stay on your machine. The program only talks to WebUntis, Google and (optionally) ntfy.
- The Google permission is the full calendar scope (read and write all calendars of the account), because the program creates
  and updates events. Keep `data/token.json` and `.env` private, and consider using a dedicated calendar via `CALENDAR_ID`.
- A full run takes a few minutes, because details (homework, teaching content, exams) are fetched per lesson.