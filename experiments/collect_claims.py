"""
collect_claims.py — builds the ground-truth claim set for the TVS parameter study.

Verdicts are NOT authored here: every row is taken from a fact-checker's own
ClaimReview structured data (schema.org), so each claim keeps its published
rating, date and verdict URL and a reviewer can re-run this script to obtain
the same set.

    .venv\\Scripts\\python.exe experiments\\collect_claims.py --per-verdict 25

Output: experiments/ground_truth/claims.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import Alex1  # noqa: E402  (reuses the pipeline's polite, retrying fetcher)

HERE = os.path.dirname(os.path.abspath(__file__))
GT_DIR = os.path.join(HERE, "ground_truth")
CLAIMS_CSV = os.path.join(GT_DIR, "claims.csv")
CACHE_DIR = os.path.join(HERE, "cache", "factchecks")

# Fact-checker listing pages to harvest. Each entry yields article URLs whose
# pages carry a ClaimReview block.
SOURCES = [
    {
        "name": "Snopes",
        "listing": "https://www.snopes.com/fact-check/rating/{rating}/?pagenum={page}",
        "ratings": {"TRUE": ["true"], "FALSE": ["false"]},
        "article_re": r"snopes\.com/fact-check/[a-z0-9-]+/?$",
        "base": "https://www.snopes.com",
    },
]

# ClaimReview textual ratings mapped to the binary ground truth. Anything not
# listed (Mixture, Unproven, Outdated, Legend, Satire, ...) is skipped: the
# study needs unambiguous labels.
VERDICT_MAP = {
    "true": "TRUE",
    "mostly true": "TRUE",
    "correct attribution": "TRUE",
    "false": "FALSE",
    "mostly false": "FALSE",
    "fake": "FALSE",
    "scam": "FALSE",
    "labeled satire": None,
    "miscaptioned": None,
    "mixture": None,
    "unproven": None,
    "outdated": None,
    "legend": None,
    "research in progress": None,
}

TOPIC_HINTS = [
    ("politics", r"\b(president|senate|congress|election|governor|minister|parliament|vote|campaign|trump|biden|vance)\b"),
    ("conflict", r"\b(war|military|troops|missile|strike|gaza|israel|ukraine|russia|iran|nato)\b"),
    ("economy", r"\b(economy|inflation|tariff|tax|stock|market|price|fed|bank|dollar|job)\b"),
    ("health", r"\b(vaccine|covid|health|hospital|doctor|cancer|drug|fda|virus)\b"),
    ("technology", r"\b(ai\b|artificial intelligence|chatgpt|robot|software|app|tech|nvidia|apple|google)\b"),
    ("science", r"\b(climate|nasa|space|scientist|study|research|species|earth)\b"),
]


def _cache_path(url: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:]
    return os.path.join(CACHE_DIR, f"{key}.html")


def fetch(url: str, timeout: int = 25) -> str:
    """Fetch with the pipeline's retrying fetcher, cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    response = Alex1._request_with_retry(url, max_retries=3, timeout=timeout)
    html = response.text if response is not None and response.status_code == 200 else ""
    with open(path, "w", encoding="utf-8", errors="ignore") as fh:
        fh.write(html)
    time.sleep(1.0)  # politeness between fact-checker requests
    return html


def article_links(html: str, pattern: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base, anchor["href"]).split("?")[0]
        if re.search(pattern, href) and href not in seen:
            seen.add(href)
            out.append(href)
    return out


def claim_review(html: str, url: str) -> dict | None:
    """Extracts the ClaimReview node published by the fact-checker."""
    soup = BeautifulSoup(html, "html.parser")
    for block in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(block.string or "{}")
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        nodes += data.get("@graph", []) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict) or node.get("@type") != "ClaimReview":
                continue
            rating = node.get("reviewRating") or {}
            claim = BeautifulSoup(str(node.get("claimReviewed") or ""), "html.parser").get_text(" ", strip=True)
            author = node.get("author") or {}
            return {
                "claim": claim,
                "rating": str(rating.get("alternateName") or "").strip(),
                "date": str(node.get("datePublished") or "")[:10],
                "url": node.get("url") or url,
                "author": (author.get("name") if isinstance(author, dict) else None) or "",
            }
    return None


def topic_of(text: str) -> str:
    low = text.lower()
    for name, pattern in TOPIC_HINTS:
        if re.search(pattern, low):
            return name
    return "general"


def to_query(claim: str, max_words: int = 12) -> str:
    """Turns a fact-checker's claim sentence into a news-search query.

    Claim statements are written for readers ("In August 2026, U.S. President
    Donald Trump posted an image showing..."), which makes a poor query. We
    drop leading temporal/context clauses and attributions, keep the entities
    and the predicate, and cut at a word boundary so the query is never a
    truncated fragment.
    """
    text = BeautifulSoup(str(claim or ""), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip().strip('"“”')

    # leading context clause: "In August 2026, ...", "As of 2026, ...", "During the ... ,"
    text = re.sub(r"^(in|as of|during|on|by|after|before|amid|following)[^,]{0,60},\s*", "", text, flags=re.I)
    # attributions: "X said (that) ...", "According to X, ..."
    text = re.sub(r"^according to [^,]{1,60},\s*", "", text, flags=re.I)
    attribution = re.match(r"^(.{3,60}?)\s+(?:said|claimed|stated|wrote|posted|announced|told)\s+(?:that\s+)?(.+)$", text, flags=re.I)
    if attribution and len(attribution.group(2).split()) >= 5:
        # keep the speaker (news coverage names them) plus the substance
        speaker = " ".join(attribution.group(1).split()[-4:])
        text = f"{speaker} {attribution.group(2)}"
    # drop hedges that describe the artefact rather than the event
    text = re.sub(r"^(a |an |the )?(video|photo|image|post|screenshot|meme|clip)[^,]{0,40}(showed|shows|depicts|circulating[^,]{0,30})\s*", "", text, flags=re.I)
    text = re.sub(r"(authentically|genuinely|reportedly|allegedly)", " ", text, flags=re.I)
    text = re.sub(r"[\"“”'’]", "", text)
    text = re.sub(r"[^\w\s%$.-]", " ", text)

    words = [w for w in text.split() if w]
    query = " ".join(words[:max_words]).rstrip(" .,-")
    return query or " ".join(str(claim).split()[:max_words])


def collect(per_verdict: int, max_pages: int) -> list[dict]:
    rows, seen_claims = [], set()
    for source in SOURCES:
        for verdict, ratings in source["ratings"].items():
            kept = 0
            for rating in ratings:
                for page in range(1, max_pages + 1):
                    if kept >= per_verdict:
                        break
                    listing = source["listing"].format(rating=rating, page=page)
                    html = fetch(listing)
                    if not html:
                        break
                    links = article_links(html, source["article_re"], source["base"])
                    if not links:
                        break
                    print(f"  [{source['name']}/{rating}] page {page}: {len(links)} articles")
                    for link in links:
                        if kept >= per_verdict:
                            break
                        review = claim_review(fetch(link), link)
                        if not review or not review["claim"]:
                            continue
                        mapped = VERDICT_MAP.get(review["rating"].lower().strip())
                        if mapped != verdict:
                            continue
                        key = review["claim"].lower()[:90]
                        if key in seen_claims:
                            continue
                        seen_claims.add(key)
                        rows.append({
                            "claim_id": "",
                            "claim_text": review["claim"],
                            "query": to_query(review["claim"]),
                            "verdict": verdict,
                            "fact_checker": review["author"] or source["name"],
                            "rating_label": review["rating"],
                            "factcheck_url": re.sub(r"(?<!:)//", "/", review["url"]),
                            "verdict_date": review["date"],
                            "topic": topic_of(review["claim"]),
                            "language": "en",
                            "split": "",
                            "notes": "",
                        })
                        kept += 1
            print(f"  [{source['name']}] {verdict}: {kept} claims")
    return rows


def assign_ids_and_split(rows: list[dict]) -> list[dict]:
    """Stratified 60/40 calibration/evaluation split, balanced per verdict and
    interleaved by topic so neither split is dominated by one subject."""
    rows = sorted(rows, key=lambda r: (r["verdict"], r["topic"], r["verdict_date"]))
    by_verdict: dict[str, list[dict]] = {}
    for row in rows:
        by_verdict.setdefault(row["verdict"], []).append(row)

    out = []
    for verdict, group in by_verdict.items():
        n_cal = round(len(group) * 0.6)
        for i, row in enumerate(group):
            row["split"] = "calibration" if i % 5 < 3 and sum(1 for r in group[:i] if r["split"] == "calibration") < n_cal else "evaluation"
            out.append(row)
    out = sorted(out, key=lambda r: (r["verdict"], r["verdict_date"], r["claim_text"][:40]))
    for i, row in enumerate(out, start=1):
        row["claim_id"] = f"C{i:03d}"
    return out


def main():
    parser = argparse.ArgumentParser(description="Harvest fact-checked claims (ClaimReview) as ground truth.")
    parser.add_argument("--per-verdict", type=int, default=20, help="claims per verdict class")
    parser.add_argument("--max-pages", type=int, default=12, help="listing pages to scan per rating")
    args = parser.parse_args()

    os.makedirs(GT_DIR, exist_ok=True)
    print(f"Collecting up to {args.per_verdict} claims per verdict...")
    rows = assign_ids_and_split(collect(args.per_verdict, args.max_pages))

    with open(CLAIMS_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                                ["claim_id", "claim_text", "query", "verdict", "fact_checker", "rating_label",
                                 "factcheck_url", "verdict_date", "topic", "language", "split", "notes"])
        writer.writeheader()
        writer.writerows(rows)

    true_n = sum(1 for r in rows if r["verdict"] == "TRUE")
    cal_n = sum(1 for r in rows if r["split"] == "calibration")
    print(f"\nwrote {len(rows)} claims -> {CLAIMS_CSV}")
    print(f"  TRUE {true_n} | FALSE {len(rows) - true_n}")
    print(f"  calibration {cal_n} | evaluation {len(rows) - cal_n}")
    if rows:
        print(f"  date range: {min(r['verdict_date'] for r in rows)} .. {max(r['verdict_date'] for r in rows)}")


if __name__ == "__main__":
    main()
