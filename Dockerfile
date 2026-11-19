# Die Version muss zu "playwright==..." in requirements.txt passen.
# Das Playwright-Image enthält Python, Chromium und alle Systempakete (amd64 und arm64).
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

LABEL org.opencontainers.image.source="https://github.com/MyName-99a/untis-google-calendar-sync" \
      org.opencontainers.image.description="Synchronisiert den WebUntis-Stundenplan mit Google Kalender"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Nur die Programmdateien, bewusst keine Zugangsdaten
COPY config.py auth.py changes.py notifications.py get_week_and_lesson_information.py main3.0.py run_loop.py ./

RUN mkdir -p /data
VOLUME /data

# Docker meldet "unhealthy", wenn die Schleife nicht mehr läuft oder dreimal hintereinander Fehler auftraten
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
  CMD ["python", "run_loop.py", "--healthcheck"]

CMD ["python", "run_loop.py"]