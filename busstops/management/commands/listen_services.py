from django.db import connection
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging  # Import logging
import psycopg2

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Listens for new or updated services and sends Discord webhooks."

    def handle(self, *args, **options):
        assert settings.NEW_SERVICE_WEBHOOK_URL, "NEW_SERVICE_WEBHOOK_URL is not set"
        session = requests.Session()

        with connection.cursor() as cursor:
            # Ensure the trigger and function are set up
            cursor.execute("""
                CREATE OR REPLACE FUNCTION notify_new_service()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('new_service', NEW.id::text);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            cursor.execute("""
                CREATE OR REPLACE TRIGGER notify_new_service
                AFTER INSERT OR UPDATE ON busstops_service
                FOR EACH ROW
                EXECUTE PROCEDURE notify_new_service();
            """)
            logger.info("PostgreSQL notify function and trigger ensured for services.")

            cursor.execute("LISTEN new_service")
            logger.info("Listening for 'new_service' notifications...")

            gen = cursor.connection.notifies()

            for notify in gen:
                service_id = notify.payload
                logger.info(f"Received notification for service: {service_id}")
                logger.info(f"Payload repr: {repr(service_id)}")
                time.sleep(2)  # Wait for potential commit
                logger.info("About to fetch service")

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
                            SELECT service_code, line_name, description, mode, current, modified_at
                            FROM busstops_service
                            WHERE id = %s
                        """, [service_id])
                        row = query_cursor.fetchone()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error fetching service {service_id}: {e}")
                    continue

                if not row:
                    logger.error(f"Service {service_id} not found in database")
                    continue

                logger.info(f"Row: {row}")
                service_code, line_name, description, mode, current, modified_at = row
                logger.info(f"Fetched service: {line_name}")

                service_url = f"https://transportthing.uk/services/{service_id}"

                fields = [
                    {
                        "name": "Service Code",
                        "value": service_code or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Line Name",
                        "value": line_name or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Mode",
                        "value": mode or "bus",
                        "inline": True
                    },
                    {
                        "name": "Status",
                        "value": "Active" if current else "Inactive",
                        "inline": True
                    },
                    {
                        "name": "Modified",
                        "value": modified_at.strftime("%Y-%m-%d %H:%M") if modified_at else "N/A",
                        "inline": True
                    }
                ]

                # Add description if it exists
                if description:
                    fields.append({
                        "name": "Description",
                        "value": description,
                        "inline": False
                    })

                embed = {
                    "title": "New or Updated Service",
                    "description": f"[View Service]({service_url})",
                    "color": 0x00FF00,  # Green for services
                    "fields": fields,
                    "thumbnail": {
                        "url": "https://assets.transportthing.uk/favicon.svg"
                    },
                    "footer": {
                        "text": "TT Service Tracker"
                    }
                }

                logger.info(f"Sending webhook for service {service_id}")
                try:
                    response = session.post(
                        settings.NEW_SERVICE_WEBHOOK_URL,
                        json={
                            "username": "Service Tracker",
                            "embeds": [embed],
                        },
                        timeout=5,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully sent webhook for service {service_id}. Response: {response.text}")
                except requests.exceptions.Timeout:
                    logger.error(f"Webhook request timed out for service {service_id}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending webhook for service {service_id}: {e}")

                time.sleep(2)
