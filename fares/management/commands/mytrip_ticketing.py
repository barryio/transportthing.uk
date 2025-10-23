import requests
from django.core.management.base import BaseCommand

from busstops.models import DataSource, Operator, OperatorCode


class Command(BaseCommand):
    help = "Fetch operator topup data from the MyTrip API (no API key required)"

    def handle(self, **options):
        # Create or get the data source
        source, _ = DataSource.objects.get_or_create(name="MyTrip")

        session = requests.Session()

        # Call the new API endpoint (no headers or API key)
        response = session.get("https://mytrip.arcticapi.com/")
        response.raise_for_status()  # make sure we catch HTTP errors early

        data = response.json()
        items = data.get("_embedded", {}).get("topup:category", [])

        for item in items:
            name = item["title"]
            code = item["id"]

            if OperatorCode.objects.filter(code=code, source=source).exists():
                print("✔️ ", name)
                continue

            try:
                operator = Operator.objects.get(name=name)
            except (Operator.DoesNotExist, Operator.MultipleObjectsReturned) as e:
                operator_id = input(f"{e} {name}. Manually enter NOC: ").upper()
                try:
                    OperatorCode.objects.create(
                        operator_id=operator_id, code=code, source=source
                    )
                except Exception as e:
                    print(e)
            else:
                print("✔️ ", operator, name)
                OperatorCode.objects.create(operator=operator, code=code, source=source)

        # Clean up removed codes
        codes = [item["id"] for item in items]
        to_delete = OperatorCode.objects.filter(source=source).exclude(code__in=codes)
        if to_delete.exists():
            print(f"Deleting {to_delete.count()} old codes...")
            to_delete.delete()
