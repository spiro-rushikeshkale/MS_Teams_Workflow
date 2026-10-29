"""
Critical-API health monitor.

Calls a small list of business-critical Energy POD APIs and posts an alert
to a Microsoft Teams channel (via a Power Automate "webhook" workflow) for
any API that fails its own health rule. On success it prints a one-line
status and sends nothing to Teams, to keep the channel quiet.

Each API lists several request "attempts" to try (e.g. several test
accounts, or several vehicle IDs). The first attempt that passes the API's
own `is_healthy(status_code)` rule marks it healthy; Teams is only alerted
once every attempt has failed, so one bad test account/vehicle doesn't get
mistaken for a real API outage.

Usage:
    python scripts/api_health_check.py

Required environment variables (see .env.example):
    TEAMS_WEBHOOK_URL     - Power Automate webhook URL that posts into Teams
    ENERGY_API_BASE_URL   - e.g. https://qa-energy.spironet.com
    ENERGY_API_KEY        - value for the X-SPIRO-API-KEY header
    ENERGY_AUTH_KEY       - value for the Authkey header
    ENERGY_TEST_DIAL_CODE - test account dial code, e.g. +254
    ENERGY_TEST_PASSWORD  - test account password (shared by all test accounts)

Exits with status 1 if any check failed (so CI also shows a failed run),
0 if every check passed.
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

REQUEST_TIMEOUT_SECONDS = 10
SCRIPT_DIR = Path(__file__).resolve().parent

# UAT dummy accounts - not secret, so they live here instead of .env/GitHub secrets.
TEST_PHONE_NUMBERS = ["700081721", "808080808", "893761234"]


def load_vehicle_ids() -> list[tuple[str, str]]:
    """Read (country, vehicle_id) pairs from scripts/vehicles.csv."""
    with open(SCRIPT_DIR / "vehicles.csv", newline="") as f:
        return [(row["country"], row["vehicle_id"]) for row in csv.DictReader(f)]


def build_critical_apis() -> list[dict]:
    """List-driven config so adding another critical API later is one entry."""
    base_url = os.environ["ENERGY_API_BASE_URL"]
    dial_code = os.environ.get("ENERGY_TEST_DIAL_CODE", "+254")
    password = os.environ["ENERGY_TEST_PASSWORD"]
    api_key = os.environ["ENERGY_API_KEY"]

    login_headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "DeviceId": "MAEI-ITL050",
        "apptype": "Android",
        "Appversion": "5.3",
        "Applang": "en",
        "X-Country": "Kenya",
        "Authkey": os.environ["ENERGY_AUTH_KEY"],
        "X-SPIRO-API-KEY": api_key,
    }

    return [
        {
            "name": "agent-login",
            "method": "POST",
            "url": f"{base_url}/api/agent/login",
            "headers": login_headers,
            # Healthy only on an exact 200 - a wrong/expired password should
            # still count as a failed attempt, not a pass.
            "is_healthy": lambda status_code: status_code == 200,
            # One attempt per test account - tried in order until one succeeds.
            "attempts": [
                {
                    "label": phone,
                    "json": {
                        "dial_code": dial_code,
                        "phone_number": phone,
                        "password": password,
                        "latitude": -1.2641123,
                        "longitude": 36.8056123,
                        "FCM_Device_Token": "dfghjkl45678",
                    },
                }
                for phone in TEST_PHONE_NUMBERS
            ],
        },
        {
            "name": "vehicle-check",
            "method": "GET",
            "url": f"{base_url}/api/v1/swapping/vehicle/.../check",  # per-attempt URL below
            "headers": {"accept": "*/*", "X-SPIRO-API-KEY": api_key},
            # Only a genuine server/outage error (5xx) or a failed request
            # counts as unhealthy - a 4xx (e.g. vehicle not found) is not a
            # backend outage, so it still counts as the API being "up".
            "is_healthy": lambda status_code: status_code < 500,
            # One attempt per vehicle (scripts/vehicles.csv) - tried in order
            # until one comes back without a server error.
            "attempts": [
                {
                    "label": f"{country}:{vehicle_id}",
                    "url": f"{base_url}/api/v1/swapping/vehicle/{vehicle_id}/check?energySource=BATTERY_SWAP",
                }
                for country, vehicle_id in load_vehicle_ids()
            ],
        },
    ]


def check_api(api: dict) -> dict:
    """Try each attempt in order; stop at the first one that passes is_healthy.

    Only reports unhealthy once every attempt has failed, so a single bad
    test account/vehicle doesn't get mistaken for a real API outage.
    """
    attempts_result = []
    for attempt in api["attempts"]:
        try:
            response = requests.request(
                method=api["method"],
                url=attempt.get("url", api["url"]),
                headers=api.get("headers"),
                json=attempt.get("json"),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if api["is_healthy"](response.status_code):
                return {"name": api["name"], "url": api["url"], "healthy": True, "attempts": attempts_result}
            attempts_result.append({"label": attempt["label"], "status_code": response.status_code, "error": None})
        except requests.RequestException as exc:
            attempts_result.append({"label": attempt["label"], "status_code": None, "error": str(exc)})

    return {"name": api["name"], "url": api["url"], "healthy": False, "attempts": attempts_result}


def notify_teams(webhook_url: str, result: dict) -> None:
    """Post a failure Adaptive Card to the Teams webhook, listing every attempt."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    facts = [{"title": "API", "value": result["url"]}]
    for attempt in result["attempts"]:
        detail = (
            f"Status code: {attempt['status_code']}"
            if attempt["error"] is None
            else f"Error: {attempt['error']}"
        )
        facts.append({"title": attempt["label"], "value": detail})
    facts.append({"title": "Checked at", "value": timestamp})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": (
                    f"API health check FAILED: {result['name']} "
                    f"(tried {len(result['attempts'])}, all failed)"
                ),
                "weight": "bolder",
                "size": "medium",
                "color": "attention",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": facts,
            },
        ],
    }
    response = requests.post(webhook_url, json=card, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()


def main() -> int:
    webhook_url = os.environ["TEAMS_WEBHOOK_URL"]
    any_failed = False

    for api in build_critical_apis():
        result = check_api(api)
        if result["healthy"]:
            print(f"[OK]   {result['name']}")
            continue

        any_failed = True
        print(f"[FAIL] {result['name']} -> all {len(result['attempts'])} attempts failed")
        for attempt in result["attempts"]:
            detail = attempt["status_code"] if attempt["error"] is None else attempt["error"]
            print(f"       {attempt['label']} -> {detail}")
        notify_teams(webhook_url, result)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
