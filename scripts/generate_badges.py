"""Generate aggregate-only profile badges alongside the existing SVG cards.

The input JSON contains private repository metadata and email addresses. Keep it
in RUNNER_TEMP; only the seven SVG badges belong on the public generated branch.
Contribution totals use the same GitHub contribution counts as overview.svg.
Repos means owned repositories (including private repos and forks), Gists means
public gists, and Years means completed years since the account was created.
"""

import argparse
from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ACCOUNT_QUERY = """
query {
  viewer {
    login
    createdAt
    repositories(first: 1, ownerAffiliations: [OWNER]) { totalCount }
    gists(first: 1, privacy: PUBLIC) { totalCount }
  }
}
"""


def get_account(token):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": ACCOUNT_QUERY}).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "github-stats-profile-badges",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if payload.get("errors"):
                messages = "; ".join(error["message"] for error in payload["errors"])
                raise RuntimeError("GitHub account query failed: " + messages)
            return payload["data"]["viewer"]
        except HTTPError as error:
            if attempt == 2 or (error.code != 429 and error.code < 500):
                raise RuntimeError(f"GitHub account query failed (HTTP {error.code})") from None
        except URLError:
            if attempt == 2:
                raise RuntimeError("Could not connect to the GitHub API") from None
        time.sleep(2 ** attempt)


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer count")
    return value


def badge_values(stats, account, now=None):
    if stats["user"].casefold() != account["login"].casefold():
        raise ValueError("Stats and access token belong to different accounts")
    created = datetime.fromisoformat(account["createdAt"].replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    if created > now:
        raise ValueError("Account creation date is in the future")
    years = now.year - created.year - (
        (now.month, now.day) < (created.month, created.day)
    )
    commits = count(stats["commit_contributions"])
    issues = count(stats["issue_contributions"])
    prs = count(stats["pr_contributions"])
    contributions = sum(count(stats[key]) for key in (
        "repo_contributions", "issue_contributions", "commit_contributions",
        "pr_contributions", "review_contributions",
    ))
    return [
        ("years", "Years", years, "Completed years on GitHub"),
        ("repos", "Repos", count(account["repositories"]["totalCount"]),
         "Owned repositories, including private repositories and forks"),
        ("gists", "Gists", count(account["gists"]["totalCount"]), "Public gists"),
        ("contributions", "All contributions", contributions,
         "All-time contributions reported by GitHub, matching the overview card"),
        ("commits", "All commits", commits,
         "All-time commit contributions reported by GitHub"),
        ("issues", "All issues", issues, "All-time issues opened"),
        ("prs", "All PRs", prs, "All-time pull requests opened"),
    ]


def text_width(text):
    # Approximate Verdana advances, then set textLength so labels cannot clip.
    widths = {char: 3 for char in "ilI.,:;'|! "}
    widths.update({char: 4 for char in "frt()[]"})
    widths.update({char: 9 for char in "MW@"})
    return math.ceil(sum(widths.get(char, 7 if char.isupper() else 6.5)
                         for char in text))


def badge_svg(label, value, description):
    number = f"{count(value):,}"
    label_text_width = text_width(label)
    number_text_width = text_width(number)
    left = label_text_width + 12
    right = number_text_width + 12
    width = left + right
    title = escape(f"{description}: {number}", quote=True)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  <linearGradient id="shade" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="round"><rect width="{width}" height="20" rx="3"/></clipPath>
  <g clip-path="url(#round)">
    <rect width="{left}" height="20" fill="#555"/>
    <rect x="{left}" width="{right}" height="20" fill="#F2A687"/>
    <rect width="{width}" height="20" fill="url(#shade)"/>
  </g>
  <g font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <text x="{left / 2}" y="14" fill="#fff" textLength="{label_text_width}" lengthAdjust="spacingAndGlyphs">{escape(label)}</text>
    <text x="{left + right / 2}" y="14" fill="#1f2328" textLength="{number_text_width}" lengthAdjust="spacingAndGlyphs">{number}</text>
  </g>
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("ACCESS_TOKEN")
    if not token:
        raise ValueError("ACCESS_TOKEN is required")
    stats = json.loads(args.stats_file.read_text())
    values = badge_values(stats, get_account(token))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, label, value, description in values:
        (args.output_dir / f"{filename}.svg").write_text(
            badge_svg(label, value, description), encoding="utf-8"
        )
    print("Generated profile badges: " + ", ".join(
        f"{label}={value:,}" for _, label, value, _ in values
    ))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, OSError) as error:
        print(f"Badge generation failed: {error}", file=sys.stderr)
        sys.exit(1)
