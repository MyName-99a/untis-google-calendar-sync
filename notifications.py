import login
import logging
import requests

NTFY_TOPIC = login.ntfy_topic
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

def send_push(message, title="Untis Sync", priority="default"):
    try:
        requests.post(
            NTFY_URL,
            data=message.encode('utf-8'),
            headers={
                "Title": title,
                "Priority": priority
            },
            timeout=10
        )
    except Exception as e:
        logging.error(f"Push-Fehler: {e}")

def send_update_notification(new, updated, skip, deleted, change_details):
    if new == 0 and updated == 0 and deleted == 0:
        return

    if change_details:
        details_msg = "\n".join(change_details)
        priority = "high" if "AUSFALL" in details_msg else "default"
        send_push(details_msg, title="Aktualisierung-Details", priority=priority)

    summary = f"Fertig! Neu: {new}, Updates: {updated}, Unverändert: {skip}, Gelöscht: {deleted}"
    send_push(summary, title="Sync Statistik")

def send_error_notification(error):
    send_push(error, title="Error-Sync")