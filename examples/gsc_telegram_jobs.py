#!/usr/bin/env python3
"""Two scheduled Search Console jobs that report to Telegram.

    python gsc_telegram_jobs.py report    weekly report sent to a Telegram chat
    python gsc_telegram_jobs.py sitemap   resubmit your sitemap once per new,
                                          successfully deployed commit

Run it with the Python that has gws-marketing installed, e.g.
``~/gws-marketing/.venv/bin/python``. Everything comes from environment
variables; see ``gsc-jobs.env.example`` and the systemd units next to this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from gws_marketing.report import build_report
from gws_marketing.server import get_client
from gws_marketing.tools import handle_submit_sitemap


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"{name} is not set")
    return value


def telegram(text: str) -> None:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    for i in range(0, len(text), 4000):  # Telegram's message limit is 4096
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 4000], "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=30).read()


def report() -> None:
    inspect = [u.strip() for u in os.environ.get("GSC_INSPECT", "").split(",") if u.strip()]
    try:
        client = get_client("gsc_search_analytics", account=os.environ.get("GSC_ACCOUNT", "default"))
        text = build_report(client, env("GSC_SITE"), inspect)
    except Exception as exc:  # the chat should hear about a broken job, not just the journal
        telegram(f"Weekly Search Console report failed: {exc}")
        raise
    telegram(text)


def github(path: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:  # fall back to a logged-in gh CLI, so private repos work without a stored token
        try:
            token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            token = ""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/{path}", headers=headers)
    return json.load(urllib.request.urlopen(request, timeout=30))


def sitemap() -> None:
    repo, branch = env("DEPLOY_REPO"), os.environ.get("DEPLOY_BRANCH", "main")
    state = Path(os.environ.get("GSC_STATE_FILE", Path.home() / ".local/state/gsc-sitemap-last-sha"))
    sha = github(f"repos/{repo}/commits/{branch}")["sha"]
    if state.exists() and state.read_text().strip() == sha:
        return
    status = github(f"repos/{repo}/commits/{sha}/status")
    # Hosts like Vercel and Netlify report deploys as commit statuses. With no
    # statuses at all there is nothing to wait for.
    if status["total_count"] and status["state"] != "success":
        print(f"{sha[:7]} deploy is {status['state']}; will check again")
        return
    client = get_client("gsc_submit_sitemap", account=os.environ.get("GSC_WRITE_ACCOUNT", "default"))
    handle_submit_sitemap(client, site_url=env("GSC_SITE"), sitemap_url=env("GSC_SITEMAP"))
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(sha)
    print(f"sitemap resubmitted for {sha[:7]}")


if __name__ == "__main__":
    jobs = {"report": report, "sitemap": sitemap}
    if len(sys.argv) != 2 or sys.argv[1] not in jobs:
        sys.exit(f"usage: {sys.argv[0]} report|sitemap")
    jobs[sys.argv[1]]()
