# The version must match "playwright==..." in requirements.txt.
# The Playwright image contains Python, Chromium and all system packages (amd64 and arm64).
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

LABEL org.opencontainers.image.source="https://github.com/MyName-99a/untis-google-calendar-sync" \
      org.opencontainers.image.description="Syncs the WebUntis timetable to Google Calendar"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Only the program files, deliberately no credentials
COPY config.py texts.py auth.py changes.py notifications.py get_week_and_lesson_information.py main3.0.py run_loop.py cleanup.py ./

RUN mkdir -p /data
VOLUME /data

# Docker reports "unhealthy" if the loop stops running or three runs in a row failed
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
  CMD ["python", "run_loop.py", "--healthcheck"]

CMD ["python", "run_loop.py"]
