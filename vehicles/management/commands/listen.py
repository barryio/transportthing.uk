from django.db import connection
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging # Import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Listens for new vehicle additions and sends Discord webhooks, ignoring 'NS' NOC."

    def handle(self, *args, **options):
        assert settings.NEW_VEHICLE_WEBHOOK_URL, "NEW_VEHICLE_WEBHOOK_URL is not set"
        assert settings.NEW_TRAIN_WEBHOOK_URL, "NEW_TRAIN_WEBHOOK_URL is not set"
        session = requests.Session()

        with connection.cursor() as cursor:
            # Ensure the trigger and function are set up
            cursor.execute("""
                CREATE OR REPLACE FUNCTION notify_new_vehicle()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('new_vehicle', NEW.slug);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            cursor.execute("""
                CREATE OR REPLACE TRIGGER notify_new_vehicle
                AFTER INSERT ON vehicles_vehicle
                FOR EACH ROW
                EXECUTE PROCEDURE notify_new_vehicle();
            """)
            logger.info("PostgreSQL notify function and trigger ensured.")


            cursor.execute("LISTEN new_vehicle")
            logger.info("Listening for 'new_vehicle' notifications...")

            gen = cursor.connection.notifies()
            Bee_NOCs = [
                "BNML", "BNSM", "BNDB", "BNGN", "BNVB", "BNFM"
            ]
            NCTR_NOCs = ["NCTR"]
            tfl_nocs = ["TFLO", "LGEN", "FLON", "AVLO", "MTLN", "GAHL", "ELBG", "LONC", "DLBU", "BTRI"]
            tfi_nocs = ["ULB", "FY-", "GLE", "MET", "ACAH", "IE-", "I-"]
            midlands = ["ADER", "AMID", "AMMO", "TBTN", "KBUS", "TMTL", "NDTR", "MDCL", "BULI", "HIPK", "NOCT", "LTLS"]
            trains = ["VT", "CS", "CH", "XC", "EM", "ES", "GX", "GN", "GW", "LE", "HX", "IL", "GR", "LULD", "LD", "ME", "NT", "SR", "SW", "SE", "SN", "SX", "XR", "TL", "TP", "AW", "WM", "LM", "CC"]

            COLORS = {
                "bee": 0xFFD700,    # Gold
                "nctr": 0x1E90FF,   # Dodger Blue
                "tfl": 0xFF0000,    # Purple
                "tfi": 0x228B22,    # Forest Green
                "midland": 0xDE8122, # Red
                "default": 0xCCCCCC # Grey
            }

            for notify in gen:
                slug = notify.payload
                logger.info(f"Received notification for slug: {slug}")

                # Split slug into NOC and FN
                if '-' in slug:
                    noc, fn = slug.split('-', 1)
                else:
                    noc, fn = slug, ""

                noc_code = noc.upper()

                # --- NEW CONDITION ADDED HERE ---
                if noc_code == "NS":
                    logger.info(f"Skipping webhook for spammy NOC 'NS': {slug}")
                    continue # Skip to the next notification
                # --- END NEW CONDITION ---

                group = "default"
                role_id = None

                if noc_code in Bee_NOCs:
                    group = "bee"
                    role_id = "1365027753501659157"
                elif noc_code in NCTR_NOCs:
                    group = "nctr"
                    role_id = "1365028004216180786"
                elif noc_code in tfl_nocs:
                    group = "tfl"
                    role_id = "1365031195737329674"
                elif noc_code in midlands:
                     group = "midland"
                     role_id = "1393283118596886548"
                elif noc_code in tfi_nocs:
                    group = "tfi"
                    role_id = "1367127895696216104"

                vehicle_url = f"https://transportthing.uk/vehicles/{slug}"
                content = f"<@&{role_id}>" if role_id else " "
                allowed_mentions = (
                    {"roles": [role_id]} if role_id else {"parse": []}
                )

                embed = {
                    "title": "New Vehicle Added",
                    "description": f"[View Vehicle]({vehicle_url})",
                    "color": COLORS.get(group, COLORS["default"]),
                    "fields": [
                        {
                            "name": "NOC",
                            "value": noc_code,
                            "inline": True
                        },
                        {
                            "name": "FN",
                            "value": fn,
                            "inline": True
                        }
                    ],
                    "thumbnail": {
                        "url": "https://assets.transportthing.uk/favicon.svg"
                    },
                    "footer": {
                        "text": "TT Fleet Tracker"
                    }
                }

                try:
                    if noc_code in trains: # checks if its a train tracking or not
                        response = session.post(
                            "https://discord.com/api/webhooks/1397044102666649842/mtBiSIA-2taZ2T5aWjn3D1_I1JZlvGmBbMyZFc1FOrraOiEur_-M8SnnbDGNNvJNDRdY",
                            json={
                                "username": "Train Tracker",
                                "content": content,
                                "allowed_mentions": allowed_mentions,
                                "embeds": [embed],
                            },
                            timeout=5,
                        )
                    else:
                        response = session.post(
                            settings.NEW_VEHICLE_WEBHOOK_URL,
                            json={
                                "username": "Vehicle Tracker",
                                "content": content,
                                "allowed_mentions": allowed_mentions,
                                "embeds": [embed],
                            },
                            timeout=5,
                        )
                    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    logger.info(f"Successfully sent webhook for {slug}. Response: {response.text}")
                except requests.exceptions.Timeout:
                    logger.error(f"Webhook request timed out for {slug}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error sending webhook for {slug}: {e}")

                time.sleep(2)
