"""
Critical-API health monitor.

Calls a small list of business-critical Energy POD APIs and posts an alert
to a Microsoft Teams channel (via a Power Automate "webhook" workflow) for
any API that does not return its expected status code, times out, or
otherwise fails to respond. On success it prints a one-line status and
sends nothing to Teams, to keep the channel quiet.

Each API can list several request payloads to try (e.g. several test
accounts). The first one that succeeds marks the API healthy; Teams is
only alerted once every payload has failed, so one broken test account
doesn't get mistaken for a real API outage.

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

import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

REQUEST_TIMEOUT_SECONDS = 10

# UAT dummy accounts - not secret, so they live here instead of .env/GitHub secrets.
TEST_PHONE_NUMBERS = ["700081721", "808080808", "893761234"]


def build_critical_apis() -> list[dict]:
    """List-driven config so adding another critical API later is one entry."""
    base_url = os.environ["ENERGY_API_BASE_URL"]
    dial_code = os.environ.get("ENERGY_TEST_DIAL_CODE", "+254")
    password = os.environ["ENERGY_TEST_PASSWORD"]
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "DeviceId": "MAEI-ITL050",
        "apptype": "Android",
        "Appversion": "5.3",
        "Applang": "en",
        "X-Country": "Kenya",
        "Authkey": os.environ["ENERGY_AUTH_KEY"],
        "X-SPIRO-API-KEY": os.environ["ENERGY_API_KEY"],
    }
    return [
        {
            "name": "agent-login",
            "method": "POST",
            "url": f"{base_url}/api/agent/login",
            "headers": headers,
            "expected_status": 200,
            # One payload per test account - tried in order until one succeeds.
            "payloads": [
                {
                    "dial_code": dial_code,
                    "phone_number": phone,
                    "password": password,
                    "latitude": -1.2641123,
                    "longitude": 36.8056123,
                    "FCM_Device_Token": "dfghjkl45678",
                }
                for phone in TEST_PHONE_NUMBERS
            ],
        },
    ]


def check_api(api: dict) -> dict:
    """Try each payload in order; stop at the first success.

    Only reports unhealthy once every payload has failed, so a single bad
    test account doesn't get mistaken for a real API outage.
    """
    attempts = []
    for payload in api["payloads"]:
        label = payload.get("phone_number", f"attempt {len(attempts) + 1}") if payload else f"attempt {len(attempts) + 1}"
        try:
            response = requests.request(
                method=api["method"],
                url=api["url"],
                headers=api.get("headers"),
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == api["expected_status"]:
                return {"name": api["name"], "url": api["url"], "healthy": True, "attempts": attempts}
            attempts.append({"label": label, "status_code": response.status_code, "error": None})
        except requests.RequestException as exc:
            attempts.append({"label": label, "status_code": None, "error": str(exc)})

    return {"name": api["name"], "url": api["url"], "healthy": False, "attempts": attempts}


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
        facts.append({"title": f"Account {attempt['label']}", "value": detail})
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
                    f"(tried {len(result['attempts'])} accounts, all failed)"
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
        print(f"[FAIL] {result['name']} -> all {len(result['attempts'])} test accounts failed")
        for attempt in result["attempts"]:
            detail = attempt["status_code"] if attempt["error"] is None else attempt["error"]
            print(f"       {attempt['label']} -> {detail}")
        notify_teams(webhook_url, result)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
