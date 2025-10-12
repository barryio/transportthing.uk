from django.db import connection
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging  # Import logging
import psycopg2
from vosa.models import TrafficArea

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Listens for new or updated licences and sends Discord webhooks."

    def handle(self, *args, **options):
        assert settings.NEW_LICENCE_WEBHOOK_URL, "NEW_LICENCE_WEBHOOK_URL is not set"
        session = requests.Session()

        with connection.cursor() as cursor:
            # Ensure the trigger and function are set up
            cursor.execute("""
                CREATE OR REPLACE FUNCTION notify_new_licence()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('new_licence', NEW.licence_number);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            cursor.execute("""
                CREATE OR REPLACE TRIGGER notify_new_licence
                AFTER INSERT OR UPDATE ON vosa_licence
                FOR EACH ROW
                EXECUTE PROCEDURE notify_new_licence();
            """)
            logger.info("PostgreSQL notify function and trigger ensured for licences.")

            cursor.execute("LISTEN new_licence")
            logger.info("Listening for 'new_licence' notifications...")

            gen = cursor.connection.notifies()

            for notify in gen:
                licence_number = notify.payload
                logger.info(f"Received notification for licence: {licence_number}")
                logger.info(f"Payload repr: {repr(licence_number)}")
                time.sleep(2)  # Wait for potential commit
                logger.info("About to fetch licence")

                try:
                    conn = psycopg2.connect(
                        database=settings.DATABASES['default']['NAME'],
                        user=settings.DATABASES['default']['USER'],
                        password=settings.DATABASES['default']['PASSWORD'],
                        host=settings.DATABASES['default']['HOST'] or 'localhost',
                        port=settings.DATABASES['default']['PORT'] or 5432,
                    )
                    with conn.cursor() as query_cursor:
                        query_cursor.execute("SELECT name, trading_name, traffic_area, description, licence_status, expiry_date, discs, authorised_discs FROM vosa_licence WHERE licence_number = %s", [licence_number])
                        row = query_cursor.fetchone()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error fetching licence {licence_number}: {e}")
                    continue

                if not row:
                    logger.error(f"Licence {licence_number} not found in database")
                    continue

                logger.info(f"Row: {row}")
                licence_name, trading_name, traffic_area, description, licence_status, expiry_date, discs, authorised_discs = row
                logger.info(f"Fetched licence: {licence_name}")

                licence_url = f"https://transportthing.uk/licences/{licence_number}"

                # Get display for traffic_area
                traffic_area_display = dict(TrafficArea.choices).get(traffic_area, traffic_area)

                fields = [
                    {
                        "name": "Licence Number",
                        "value": licence_number,
                        "inline": True
                    },
                    {
                        "name": "Name",
                        "value": licence_name,
                        "inline": True
                    },
                    {
                        "name": "Trading Name",
                        "value": trading_name or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Traffic Area",
                        "value": traffic_area_display,
                        "inline": True
                    },
                    {
                        "name": "Description",
                        "value": description,
                        "inline": True
                    },
                    {
                        "name": "Status",
                        "value": licence_status or "N/A",
                        "inline": True
                    },
                    {
                        "name": "Expiry Date",
                        "value": expiry_date.strftime("%Y-%m-%d") if expiry_date else "N/A",
                        "inline": True
                    },
                    {
                        "name": "Discs",
                        "value": f"{discs}/{authorised_discs}",
                        "inline": True
                    }
                ]

                embed = {
                    "title": "New or Updated Licence",
                    "description": f"[View Licence]({licence_url})",
                    "color": 0x00FF00,  # Green for licences
                    "fields": fields,
                    "thumbnail": {
                        "url": "https://assets.transportthing.uk/favicon.svg"
                    },
                    "footer": {
                        "text": "TT Licence Tracker"
                    }
                }

                logger.info(f"Sending webhook for {licence_number}")
                try:
                    response = session.post(
                        settings.NEW_LICENCE_WEBHOOK_URL,
                        json={
                            "username": "Licence Tracker",
                            "embeds": [embed],
                        },
                        timeout=5,
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully sent webhook for {licence_number}. Response: {response.text}")
                except requests.exceptions.Timeout:
                    logger.error(f"Webhook request timed out for {licence_number}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending webhook for {licence_number}: {e}")

                time.sleep(2)
