"""
Critical-API health monitor.

Calls a small list of business-critical Energy POD APIs and posts an alert
to a Microsoft Teams channel (via a Power Automate "webhook" workflow) for
any API that does not return its expected status code, times out, or
otherwise fails to respond. On success it prints a one-line status and
sends nothing to Teams, to keep the channel quiet.

Usage:
    python scripts/api_health_check.py

Required environment variables (see .env.example):
    TEAMS_WEBHOOK_URL     - Power Automate webhook URL that posts into Teams
    ENERGY_API_BASE_URL   - e.g. https://qa-energy.spironet.com
    ENERGY_API_KEY        - value for the X-SPIRO-API-KEY header
    ENERGY_AUTH_KEY       - value for the Authkey header
    ENERGY_TEST_DIAL_CODE - test account dial code, e.g. +254
    ENERGY_TEST_PHONE     - test account phone number
    ENERGY_TEST_PASSWORD  - test account password

Exits with status 1 if any check failed (so CI also shows a failed run),
0 if every check passed.
"""

import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

REQUEST_TIMEOUT_SECONDS = 10


def build_critical_apis() -> list[dict]:
    """List-driven config so adding another critical API later is one entry."""
    base_url = os.environ["ENERGY_API_BASE_URL"]
    return [
        {
            "name": "agent-login",
            "method": "POST",
            "url": f"{base_url}/api/agent/login",
            "headers": {
                "accept": "application/json",
                "Content-Type": "application/json",
                "DeviceId": "MAEI-ITL050",
                "apptype": "Android",
                "Appversion": "5.3",
                "Applang": "en",
                "X-Country": "Kenya",
                "Authkey": os.environ["ENERGY_AUTH_KEY"],
                "X-SPIRO-API-KEY": os.environ["ENERGY_API_KEY"],
            },
            "json": {
                "dial_code": os.environ.get("ENERGY_TEST_DIAL_CODE", "+254"),
                "phone_number": os.environ["ENERGY_TEST_PHONE"],
                "password": os.environ["ENERGY_TEST_PASSWORD"],
                "latitude": -1.2641123,
                "longitude": 36.8056123,
                "FCM_Device_Token": "dfghjkl45678",
            },
            "expected_status": 200,
        },
    ]


def check_api(api: dict) -> dict:
    """Call one API and report whether it returned its expected status."""
    try:
        response = requests.request(
            method=api["method"],
            url=api["url"],
            headers=api.get("headers"),
            json=api.get("json"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return {
            "name": api["name"],
            "url": api["url"],
            "healthy": response.status_code == api["expected_status"],
            "status_code": response.status_code,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "name": api["name"],
            "url": api["url"],
            "healthy": False,
            "status_code": None,
            "error": str(exc),
        }


def notify_teams(webhook_url: str, result: dict) -> None:
    """Post a failure Adaptive Card to the Teams webhook."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    detail = (
        f"Status code: {result['status_code']}"
        if result["error"] is None
        else f"Error: {result['error']}"
    )
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"API health check FAILED: {result['name']}",
                "weight": "bolder",
                "size": "medium",
                "color": "attention",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "API", "value": result["url"]},
                    {"title": "Detail", "value": detail},
                    {"title": "Checked at", "value": timestamp},
                ],
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
            print(f"[OK]   {result['name']} -> {result['status_code']}")
            continue

        any_failed = True
        detail = result["status_code"] or result["error"]
        print(f"[FAIL] {result['name']} -> {detail}")
        notify_teams(webhook_url, result)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
