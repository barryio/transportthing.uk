#!/usr/bin/env python3
"""
Script to run timetable updates and send notifications to Discord.

Usage:
    python update_timetables.py

Requires:
    - DISCORD_WEBHOOK_URL environment variable set to your Discord webhook URL
    - Django environment set up (run from project root)
"""

import os
import subprocess
import sys
import requests
from datetime import datetime
tnds_email = os.getenv('TNDS_EMAIL')
tnds_pass = os.getenv("TNDS_PASS")
bods_api_key = os.getenv("BODS_API_KEY")

def send_discord_message(message: str):
    """Send a message to Discord webhook."""
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord notification")
        return
    payload = {
        "content": message,
        "username": "Timetable Updater"
    }

    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print("Discord notification sent")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Discord message: {e}")

def run_command(command: list, description: str) -> tuple[bool, str]:
    """Run a command and return success status and output."""
    print(f"Running: {description}")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=116700  # 1 hour timeout
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        if success:
            print(f"✓ {description} completed successfully")
        else:
            print(f"✗ {description} failed with return code {result.returncode}")
        return success, output
    except subprocess.TimeoutExpired:
        print(f"✗ {description} timed out")
        return False, "Command timed out"
    except Exception as e:
        print(f"✗ {description} failed: {e}")
        return False, str(e)

def main():
    """Main function to run timetable updates."""
    start_time = datetime.now()

    # Check if we're in the right directory
    if not os.path.exists('manage.py'):
        print("Error: manage.py not found. Run this script from the Django project root.")
        sys.exit(1)

    # Commands to run (based on import.sh)
    commands = [
        (["./manage.py", "nptg_new"], "Update NPTG regions"),
        (["./manage.py", "naptan_new"], "Update NaPTAN stops"),
        (["./manage.py", "naptan_new", "Irish NaPTAN"], "Update Irish NaPTAN stops"),
        (["./manage.py", "import_noc"], "Import NOC operators"),
        (["./manage.py", "update_search_indexes"], "Update search indexes"),
        (["./manage.py", "import_vosa"], "Update VOSA Licences"),
        (["./manage.py", "import_bod_timetables", "ticketer"], "Update Ticketer"),
        (["./manage.py", "import_bod_timetables", "stagecoach"], "Update Stagecoach"),
        (["./manage.py", "import_passenger"], "Update Passenger Sources"),
        (["./manage.py", "import_gtfs", "Realtime Transport Operators"], "Update IE Timetables"),
        (["./manage.py", "import_bod_timetables", bods_api_key], "Update BODS Timetables"),
        (["./manage.py", "import_tnds", tnds_email, tnds_pass], "Import Traveline")
    ]

    # Note: import_tnds and import_transxchange require data files and credentials
    # You may need to run those separately or modify this script

    results = []
    all_success = True

    for command, description in commands:
        success, output = run_command(command, description)
        results.append((description, success, output))
        if not success:
            all_success = False

    end_time = datetime.now()
    duration = end_time - start_time

    # Prepare Discord message
    message_lines = [f"**Timetable Update Completed** - {end_time.strftime('%Y-%m-%d %H:%M:%S')}"]
    message_lines.append(f"Duration: {duration}")

    if all_success:
        message_lines.append("✅ All updates completed successfully")
    else:
        message_lines.append("⚠️ Some updates failed")

    for desc, success, output in results:
        status = "✅" if success else "❌"
        message_lines.append(f"{status} {desc}")

    # Truncate if too long (Discord has 2000 char limit)
    message = "\n".join(message_lines)
    if len(message) > 1900:
        message = message[:1900] + "\n... (truncated)"

    send_discord_message(message)

    # Print summary
    print("\n" + "="*50)
    print("UPDATE SUMMARY")
    print("="*50)
    for desc, success, output in results:
        print(f"{'✓' if success else '✗'} {desc}")
        if not success and output:
            print(f"  Error: {output[:200]}...")
    print(f"\nTotal duration: {duration}")

    if not all_success:
        sys.exit(1)

if __name__ == "__main__":
    main()
