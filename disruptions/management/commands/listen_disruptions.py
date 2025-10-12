from django.db import connection
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging  # Import logging
import psycopg2

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Listens for new or updated service disruptions and sends Discord webhooks."

    def handle(self, *args, **options):
        assert settings.NEW_DISRUPTION_WEBHOOK_URL, "NEW_DISRUPTION_WEBHOOK_URL is not set"
        session = requests.Session()

        with connection.cursor() as cursor:
            # Ensure the trigger and function are set up
            cursor.execute("""
                CREATE OR REPLACE FUNCTION notify_new_disruption()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('new_disruption', NEW.id::text);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            cursor.execute("""
                CREATE OR REPLACE TRIGGER notify_new_disruption
                AFTER INSERT OR UPDATE ON disruptions_situation
                FOR EACH ROW
                EXECUTE PROCEDURE notify_new_disruption();
            """)
            logger.info("PostgreSQL notify function and trigger ensured for disruptions.")

            cursor.execute("LISTEN new_disruption")
            logger.info("Listening for 'new_disruption' notifications...")

            gen = cursor.connection.notifies()

            for notify in gen:
                situation_id = notify.payload
                logger.info(f"Received notification for disruption: {situation_id}")
                logger.info(f"Payload repr: {repr(situation_id)}")
                time.sleep(2)  # Wait for potential commit
                logger.info("About to fetch disruption")

                try:
                    conn = psycopg2.connect(
                        database=settings.DATABASES['default']['NAME'],
                        user=settings.DATABASES['default']['USER'],
                        password=settings.DATABASES['default']['PASSWORD'],
                        host=settings.DATABASES['default']['HOST'] or 'localhost',
                        port=settings.DATABASES['default']['PORT'] or 5432,
                    )
                    with conn.cursor() as query_cursor:
                        query_cursor.execute("""
                            SELECT situation_number, reason, summary, text, created_at, current
                            FROM disruptions_situation
                            WHERE id = %s
                        """, [situation_id])
                        row = query_cursor.fetchone()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error fetching disruption {situation_id}: {e}")
                    continue

                if not row:
                    logger.error(f"Disruption {situation_id} not found in database")
                    continue

                logger.info(f"Row: {row}")
                situation_number, reason, summary, text, created_at, current = row
                logger.info(f"Fetched disruption: {summary}")

                disruption_url = f"https://transportthing.uk/disruptions/{situation_id}"

                # Format the reason nicely
                nice_reason = reason
                if reason:
                    # Simple camel case to spaces conversion
                    nice_reason = ''.join(' ' + c.lower() if c.isupper() else c for c in reason).strip()

                fields = [
                    {
                        "name": "Situation Number",
                        "value": situation_number or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Reason",
                        "value": nice_reason or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Summary",
                        "value": summary or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Status",
                        "value": "Active" if current else "Resolved",
                        "inline": True
                    },
                    {
                        "name": "Created",
                        "value": created_at.strftime("%Y-%m-%d %H:%M") if created_at else "N/A",
                        "inline": True
                    }
                ]

                # Add text field if it exists and is not too long
                if text and len(text) <= 1000:
                    fields.append({
                        "name": "Details",
                        "value": text[:1000],
                        "inline": False
                    })

                embed = {
                    "title": "Service Disruption Alert",
                    "description": f"[View Disruption]({disruption_url})",
                    "color": 0xFF0000,  # Red for disruptions
                    "fields": fields,
                    "thumbnail": {
                        "url": "https://assets.transportthing.uk/favicon.svg"
                    },
                    "footer": {
                        "text": "TT Disruption Tracker"
                    }
                }

                logger.info(f"Sending webhook for disruption {situation_id}")
                try:
                    response = session.post(
                        settings.NEW_DISRUPTION_WEBHOOK_URL,
                        json={
                            "username": "Disruption Tracker",
                            "embeds": [embed],
                        },
                        timeout=5,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully sent webhook for disruption {situation_id}. Response: {response.text}")
                except requests.exceptions.Timeout:
                    logger.error(f"Webhook request timed out for disruption {situation_id}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending webhook for disruption {situation_id}: {e}")

                time.sleep(2)
