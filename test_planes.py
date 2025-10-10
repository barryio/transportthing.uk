#!/usr/bin/env python3
"""
Simple test script to verify OpenSky Network API integration for plane tracking
"""
import requests
import datetime

def test_opensky_api():
    """Test fetching aircraft data from OpenSky Network API"""
    url = "https://opensky-network.org/api/states/all"

    print("Fetching aircraft data from OpenSky Network...")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        states = data.get('states', [])
        print(f"Successfully fetched {len(states)} aircraft positions")

        if states:
            # Show first few aircraft as examples
            print("\nFirst 3 aircraft:")
            for i, state in enumerate(states[:3]):
                icao24 = state[0]
                callsign = state[1] or "Unknown"
                country = state[2]
                lon = state[5]
                lat = state[6]
                altitude = state[7]
                velocity = state[9]
                heading = state[10]

                print(f"  {i+1}. ICAO: {icao24}, Callsign: {callsign}, Country: {country}")
                print(f"      Position: {lat:.2f}, {lon:.2f}, Altitude: {altitude}m, Speed: {velocity} m/s, Heading: {heading}°")

        return True

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return False

if __name__ == "__main__":
    success = test_opensky_api()
    if success:
        print("\n✓ OpenSky API integration test passed!")
        print("The plane tracking script should work correctly.")
    else:
        print("\n✗ OpenSky API integration test failed!")