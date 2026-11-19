# Small image: Python and the packages from requirements.txt (amd64 and arm64), no browser.
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/MyName-99a/untis-google-calendar-sync" \
      org.opencontainers.image.description="Syncs the WebUntis timetable to Google Calendar"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    TZ=Europe/Berlin

# tzdata: the system time zones, so that TZ (also changed in .env) is applied to the log and the sync
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Only the program files, deliberately no credentials
COPY config.py texts.py auth.py changes.py notifications.py untis_login.py get_week_and_lesson_information.py main3.0.py run_loop.py cleanup.py ./

RUN mkdir -p /data
VOLUME /data

# Docker reports "unhealthy" if the loop stops running or three runs in a row failed
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
  CMD ["python", "run_loop.py", "--healthcheck"]

CMD ["python", "run_loop.py"]
