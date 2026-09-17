#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone

# Environment
REPO = os.environ["GITHUB_REPOSITORY"]
GH_TOKEN = os.environ["GH_TOKEN"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
EVENT_NAME = os.environ.get("EVENT_NAME", "")
EVENT_ACTION = os.environ.get("EVENT_ACTION", "")
PR_NUMBER = os.environ.get("PR_NUMBER", "")

TEAM_FILE = os.environ.get("TEAM_FILE", ".github/pr-review-team.txt")
MIN_REVIEWS = 2
REMINDER_DELAY_HOURS = 2 # Don't remind if the PR was updated/created recently

def github_api(path):
    url = f"https://api.github.com/{path.lstrip('/')}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GH_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    })
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))

def discord_message(content):
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": ["users", "everyone"]}})
    
    request = urllib.request.Request(DISCORD_WEBHOOK, data=payload.encode("utf-8"), headers={
        "Content-Type": "application/json",
        "User-Agent": "github-pr-review-bot" 
    })

    urllib.request.urlopen(request)

def load_team():
    team = {}
    if os.path.exists(TEAM_FILE):
        with open(TEAM_FILE, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    gh, discord = line.strip().split("=", 1)
                    team[gh.strip()] = discord.strip()
    return team

TEAM = load_team()

def get_approvers(pr_number):
    reviews = github_api(f"repos/{REPO}/pulls/{pr_number}/reviews")
    return {r["user"]["login"] for r in reviews if r["state"] == "APPROVED"}

def handle_pr_event():
    pr = github_api(f"repos/{REPO}/pulls/{PR_NUMBER}")
    if pr.get("draft"): return

    discord_message(
        f"**PR #{PR_NUMBER} needs {MIN_REVIEWS} reviews**\n\n"
        f"**{pr['title']}**\n@everyone\n\n<{pr['html_url']}>"
    )

def handle_reminders():
    prs = github_api(f"repos/{REPO}/pulls?state=open")
    now = datetime.now(timezone.utc)
    
    for pr in prs:
        if pr.get("draft"): continue
        
        # Parse GitHub's ISO timestamp (e.g. 2023-10-12T15:30:00Z)
        updated_at = datetime.strptime(pr["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_in_hours = (now - updated_at).total_seconds() / 3600
        
        # Skip if the PR it is too recent
        if age_in_hours < REMINDER_DELAY_HOURS:
            continue
            
        author = pr["user"]["login"]
        approvers = get_approvers(pr["number"])
        
        if len(approvers) >= MIN_REVIEWS:
            continue
            
        # Find team members who are not the author and haven't approved
        slacking_members = [
            gh_user for gh_user in TEAM 
            if gh_user != author and gh_user not in approvers
        ]
        
        mentions = " ".join([f"<@{TEAM[u]}>" for u in slacking_members])
        needed = MIN_REVIEWS - len(approvers)
        
        if mentions:
            discord_message(
                f"**Reminder: PR #{pr['number']} still needs {needed} review(s)**\n\n"
                f"**{pr['title']}**\nWaiting on: {mentions}\n\n<{pr['html_url']}>"
            )

if __name__ == "__main__":
    if EVENT_NAME == "schedule":
        handle_reminders()
    elif EVENT_NAME in ("pull_request", "pull_request_target") and EVENT_ACTION in ("opened", "ready_for_review", "synchronize"):
        if PR_NUMBER: handle_pr_event()