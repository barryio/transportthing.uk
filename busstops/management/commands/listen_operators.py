from django.db import connection
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging  # Import logging
import psycopg2

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Listens for new or updated operators and sends Discord webhooks."

    def handle(self, *args, **options):
        assert settings.NEW_OPERATOR_WEBHOOK_URL, "NEW_OPERATOR_WEBHOOK_URL is not set"
        session = requests.Session()

        with connection.cursor() as cursor:
            # Ensure the trigger and function are set up
            cursor.execute("""
                CREATE OR REPLACE FUNCTION notify_new_operator()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('new_operator', NEW.noc);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            cursor.execute("""
                CREATE OR REPLACE TRIGGER notify_new_operator
                AFTER INSERT OR UPDATE ON busstops_operator
                FOR EACH ROW
                EXECUTE PROCEDURE notify_new_operator();
            """)
            logger.info("PostgreSQL notify function and trigger ensured for operators.")

            cursor.execute("LISTEN new_operator")
            logger.info("Listening for 'new_operator' notifications...")

            gen = cursor.connection.notifies()

            for notify in gen:
                noc = notify.payload
                logger.info(f"Received notification for operator: {noc}")
                logger.info(f"Payload repr: {repr(noc)}")
                time.sleep(2)  # Wait for potential commit
                logger.info("About to fetch operator")

                try:
                    conn = psycopg2.connect(
                        database=settings.DATABASES['default']['NAME'],
                        user=settings.DATABASES['default']['USER'],
                        password=settings.DATABASES['default']['PASSWORD'],
                        host=settings.DATABASES['default']['HOST'] or 'localhost',
                        port=settings.DATABASES['default']['PORT'] or 5432,
                    )
                    with conn.cursor() as query_cursor:
                        query_cursor.execute("SELECT name, vehicle_mode, url, twitter, address, phone, email FROM busstops_operator WHERE noc = %s", [noc])
                        row = query_cursor.fetchone()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error fetching operator {noc}: {e}")
                    continue

                if not row:
                    logger.error(f"Operator {noc} not found in database")
                    continue

                logger.info(f"Row: {row}")
                name, vehicle_mode, url, twitter, address, phone, email = row
                logger.info(f"Fetched operator: {name}")

                operator_url = f"https://transportthing.uk/operators/{noc}"

                fields = [
                    {
                        "name": "NOC",
                        "value": noc,
                        "inline": True
                    },
                    {
                        "name": "Name",
                        "value": name,
                        "inline": True
                    },
                    {
                        "name": "Vehicle Mode",
                        "value": vehicle_mode or "N/A",
                        "inline": True
                    },
                    {
                        "name": "URL",
                        "value": url or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Twitter",
                        "value": twitter or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Address",
                        "value": address or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Phone",
                        "value": phone or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Email",
                        "value": email or "N/A",
                        "inline": True
                    }
                ]

                embed = {
                    "title": "New or Updated Operator",
                    "description": f"[View Operator]({operator_url})",
                    "color": 0x0000FF,  # Blue for operators
                    "fields": fields,
                    "thumbnail": {
                        "url": "https://assets.transportthing.uk/favicon.svg"
                    },
                    "footer": {
                        "text": "TT Operator Tracker"
                    }
                }

                logger.info(f"Sending webhook for {noc}")
                try:
                    response = session.post(
                        settings.NEW_OPERATOR_WEBHOOK_URL,
                        json={
                            "username": "Operator Tracker",
                            "embeds": [embed],
                        },
                        timeout=5,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully sent webhook for {noc}. Response: {response.text}")
                except requests.exceptions.Timeout:
                    logger.error(f"Webhook request timed out for {noc}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending webhook for {noc}: {e}")

                time.sleep(2)
