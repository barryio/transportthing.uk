import datetime
import requests
from django.contrib.gis.geos import Point

from ...models import Vehicle, VehicleJourney, VehicleLocation
from busstops.models import Operator
from ..import_live_vehicles import ImportLiveVehiclesCommand


class Command(ImportLiveVehiclesCommand):
    source_name = "OpenSky Network"
    url = "https://opensky-network.org/api/states/all"

    def do_source(self):
        # Create/get "Airlines" operator
        self.operator, created = Operator.objects.get_or_create(
            noc="ICAO",
            defaults={"name": "International Civil Aviation Organization"}
        )
        if created:
            self.stdout.write(f"Created operator: {self.operator}")
        return super().do_source()

    def get_items(self):
        try:
            response = requests.get(self.url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            self.stderr.write(f"Error fetching plane data: {e}")
            return []

        items = []
        for state in data.get('states', []):
            # Map OpenSky state vector to our format
            # OpenSky returns: [icao24, callsign, origin_country, time_position, last_contact,
            #                   longitude, latitude, baro_altitude, on_ground, velocity,
            #                   true_track, vertical_rate, ...]
            if state[5] and state[6]:  # Only include if position available
                item = {
                    'icao24': state[0],
                    'callsign': state[1],
                    'country': state[2],
                    'timestamp': state[3] or state[4],  # time_position or last_contact
                    'lon': state[5],
                    'lat': state[6],
                    'altitude': state[7],  # baro_altitude
                    'velocity': state[9],
                    'heading': state[10],  # true_track
                    'vertical_rate': state[11],
                    'on_ground': state[8],
                }
                items.append(item)

        self.stdout.write(f"Fetched {len(items)} aircraft positions")
        return items

    def get_vehicle(self, item) -> tuple[Vehicle, bool]:
        icao24 = item['icao24']
        defaults = {
            'operator': self.operator,
            'source': self.source,
            'fleet_code': icao24,
        }
        vehicle, created = Vehicle.objects.get_or_create(
            code=icao24,
            defaults=defaults
        )
        # Update callsign as name if available
        if item.get('callsign') and vehicle.name != item['callsign'].strip():
            vehicle.name = item['callsign'].strip()
            vehicle.save(update_fields=['name'])
        return vehicle, created

    def get_journey(self, item, vehicle):
        callsign = item.get('callsign', '').strip()
        if not callsign:
            callsign = f"ICAO-{item['icao24']}"

        # Create journey based on callsign (flight number)
        # Group by callsign for the same flight
        journey_datetime = self.get_datetime(item)

        # Try to find existing journey for this callsign today
        existing_journey = vehicle.vehiclejourney_set.filter(
            code=callsign,
            datetime__date=journey_datetime.date()
        ).first()

        if existing_journey:
            return existing_journey

        # Create new journey
        journey = VehicleJourney(
            vehicle=vehicle,
            route_name=callsign,
            destination=item.get('country', 'Unknown'),
            code=callsign,
            datetime=journey_datetime,
        )
        return journey

    @staticmethod
    def get_datetime(item):
        return datetime.datetime.fromtimestamp(item['timestamp'], datetime.timezone.utc)

    def create_vehicle_location(self, item):
        return VehicleLocation(
            latlong=Point(float(item['lon']), float(item['lat'])),
            heading=item.get('heading'),
        )