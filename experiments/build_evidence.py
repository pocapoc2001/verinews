"""
build_evidence.py — retrieves news coverage for every ground-truth claim and
freezes the evidence the scoring stages need.

For each claim in ground_truth/claims.csv this runs the production ingestion
(`Alex1.fetch_topic`), builds the cluster summary with the same extractive
summarizer the pipeline uses, then stores the *raw* evidence:

    similarities   cos(summary, source_i)
    pairwise       full source x source cosine matrix
    domains        source identity per article (verinews_common.source_identity)
    stance         per-article debunk / neutral flag (see stance_of)
    claims         the summary's claim sentences, and claim_similarities
                   cos(claim_i, source_j), for claim-level verification

Everything downstream (parameter sweep, baselines, evaluation) reads these
bundles, so a sweep over hundreds of parameter settings costs no network calls
and no re-embedding, and the study is reproducible from the cache.

    .venv\\Scripts\\python.exe experiments\\build_evidence.py [--limit N] [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import Alex1  # noqa: E402
from verinews_common import source_identity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CLAIMS_CSV = os.path.join(HERE, "ground_truth", "claims.csv")
RETRIEVAL_DIR = os.path.join(HERE, "cache", "retrieval")
EVIDENCE_DIR = os.path.join(HERE, "evidence")

# Domains whose business is verification rather than reporting. Their presence
# in a cluster is itself a signal, and it is recorded rather than filtered.
FACTCHECK_DOMAINS = {
    "snopes.com", "politifact.com", "factcheck.org", "fullfact.org", "afp.com",
    "factcheck.afp.com", "leadstories.com", "checkyourfact.com", "truthorfiction.com",
    "reuters.com/fact-check", "apnews.com/hub/ap-fact-check", "usatoday.com/story/news/factcheck",
    "verifythis.com", "factual.ro", "misbar.com", "boomlive.in", "logicallyfacts.com",
}

DEBUNK_RE = re.compile(
    r"\b(false|fake|hoax|debunk\w*|misinform\w*|disinform\w*|misleading|no evidence|"
    r"did not|does not|didn'?t|doesn'?t|untrue|baseless|unfounded|fact[- ]check\w*|"
    r"conspiracy|rumou?r|altered|manipulated|ai[- ]generated|doctored|out of context)\b",
    re.IGNORECASE,
)


def load_claims(path: str = CLAIMS_CSV) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fetch_tiers(query: str, max_articles: int, gnews_first: bool) -> list[dict]:
    """Ingestion for one claim, using the pipeline's own tier functions.

    `gnews_first` only permutes the order in which the same three tiers are
    tried. DuckDuckGo rate-limits bulk experimental runs and each blocked query
    costs ~50 s of backoff before the pipeline falls through to Google News
    anyway; querying Google News first makes the study tractable without
    changing which retrieval code paths produce the corpus. The permutation is
    recorded in the bundle so the deviation from production order is visible.
    """
    if not gnews_first:
        return Alex1.fetch_topic(query, max_articles)
    for fetcher in (Alex1._fetch_via_gnews, Alex1._fetch_via_duckduckgo, Alex1._fetch_via_yahoo):
        try:
            articles = fetcher(query, max_articles)
        except Exception as error:
            print(f"    {fetcher.__name__} failed: {error}")
            continue
        if articles:
            return articles
    return []


def retrieve(claim: dict, max_articles: int, refresh: bool, gnews_first: bool = False) -> list[dict]:
    """Runs the ingestion for one claim, cached on disk."""
    os.makedirs(RETRIEVAL_DIR, exist_ok=True)
    path = os.path.join(RETRIEVAL_DIR, f"{claim['claim_id']}.json")
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    articles = fetch_tiers(claim["query"], max_articles, gnews_first)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(articles, fh, ensure_ascii=False, indent=1)
    return articles


def stance_of(article: dict, domain: str) -> str:
    """debunk | neutral for one retrieved article.

    A false claim usually retrieves a mix of the claim itself and the pieces
    debunking it; recording that mix is what lets the study interpret the
    coherence factor honestly instead of quietly assuming it.

    Only refutation is detected. A lexical cue can tell "this article says it
    is false" from "this article says nothing of the kind", but not whether an
    article affirms the claim, so "promote" is accepted by the consumers
    (baselines.B7, evaluate.stance_support) and never produced here. The paper
    describes the signal as "does not refute", not "supports", for that reason."""
    if any(domain == d or domain.endswith("." + d) for d in FACTCHECK_DOMAINS):
        return "debunk"
    head = f"{article.get('Title', '')} {str(article.get('Text', ''))[:400]}"
    return "debunk" if DEBUNK_RE.search(head) else "neutral"


RETRIEVAL_ORDER = ["duckduckgo,gnews,yahoo"]   # set by main(); recorded in each bundle


def build_bundle(claim: dict, articles: list[dict]) -> dict:
    import pandas as pd

    frame = pd.DataFrame(articles)
    summary = ""
    similarities, pairwise, domains = [], None, []
    claims, claim_similarities = [], None
    if len(frame) > 0:
        body_col = frame["Body_Available"] if "Body_Available" in frame.columns else None
        source_frame = frame[body_col.fillna(False).astype(bool)] if body_col is not None and body_col.any() else frame
        combined = " ".join(source_frame["Text"].dropna().astype(str).iloc[:4].tolist())
        summary = Alex1._extractive_summarize(combined, max_sentences=3) if combined else ""
        if summary:
            sims, pair, doms = Alex1.extract_evidence(summary, frame)
            similarities = [round(float(s), 6) for s in sims]
            pairwise = [[round(float(v), 6) for v in row] for row in pair] if pair is not None else None
            domains = list(doms)
            # Claim-level evidence: needed to replicate a verifier that checks
            # each assertion separately rather than the briefing as a whole.
            claims, claim_matrix = Alex1.extract_claim_evidence(summary, frame)
            claim_similarities = (
                [[round(float(v), 6) for v in row] for row in claim_matrix]
                if claim_matrix is not None else None
            )

    records = []
    for i, article in enumerate(articles):
        url = str(article.get("URL", "") or "")
        domain = domains[i] if i < len(domains) else source_identity(
            url, article.get("Publisher_URL"), article.get("Publisher"))
        records.append({
            "title": article.get("Title", ""),
            "url": url,
            "publisher": article.get("Publisher", ""),
            "domain": domain,
            "body_available": bool(article.get("Body_Available", False)),
            "url_resolved": bool(article.get("URL_Resolved", False)),
            "pub_date": article.get("Publish_Date", ""),
            "text": str(article.get("Text", ""))[:4000],
            "stance": stance_of(article, domain),
            "similarity": similarities[i] if i < len(similarities) else None,
        })

    return {
        "claim_id": claim["claim_id"],
        "claim_text": claim["claim_text"],
        "query": claim["query"],
        "verdict": claim["verdict"],
        "split": claim["split"],
        "topic": claim["topic"],
        "fact_checker": claim["fact_checker"],
        "factcheck_url": claim["factcheck_url"],
        "verdict_date": claim["verdict_date"],
        "summary": summary,
        "n_articles": len(records),
        "n_domains": len({r["domain"] for r in records if r["domain"]}),
        "n_debunk": sum(1 for r in records if r["stance"] == "debunk"),
        "retrieval_order": RETRIEVAL_ORDER[0],
        "articles": records,
        "similarities": similarities,
        "pairwise": pairwise,
        "domains": domains,
        "claims": claims,
        "claim_similarities": claim_similarities,
    }


def main():
    parser = argparse.ArgumentParser(description="Retrieve coverage and freeze TVS evidence per claim.")
    parser.add_argument("--limit", type=int, default=0, help="process only the first N claims")
    parser.add_argument("--max-articles", type=int, default=Alex1.MAX_ARTICLES_PER_TOPIC)
    parser.add_argument("--refresh", action="store_true", help="ignore the retrieval cache")
    parser.add_argument("--redo", action="store_true", help="rebuild bundles that already exist")
    parser.add_argument("--gnews-first", action="store_true",
                        help="try Google News RSS before DuckDuckGo (avoids bulk-run rate limiting)")
    parser.add_argument("--max-minutes", type=float, default=0.0,
                        help="stop cleanly after this many minutes (re-run to resume)")
    args = parser.parse_args()

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    RETRIEVAL_ORDER[0] = "gnews,duckduckgo,yahoo" if args.gnews_first else "duckduckgo,gnews,yahoo"
    claims = load_claims()
    if args.limit:
        claims = claims[: args.limit]

    started = time.time()
    summary_rows = []
    for index, claim in enumerate(claims, start=1):
        # Resumable: a claim that already has a bundle is loaded, not refetched,
        # so the study can be built in short runs.
        bundle_path = os.path.join(EVIDENCE_DIR, f"{claim['claim_id']}.json")
        if os.path.exists(bundle_path) and not args.redo:
            with open(bundle_path, encoding="utf-8") as fh:
                summary_rows.append(json.load(fh))
            continue
        if args.max_minutes and (time.time() - started) / 60 >= args.max_minutes:
            print(f"\nstopped after {args.max_minutes} min as requested — re-run to resume")
            break
        print(f"[{index}/{len(claims)}] {claim['claim_id']} ({claim['verdict']}) {claim['query'][:60]}")
        try:
            articles = retrieve(claim, args.max_articles, args.refresh, args.gnews_first)
        except Exception as error:
            print(f"    retrieval failed: {error}")
            articles = []
        bundle = build_bundle(claim, articles)
        with open(bundle_path, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, ensure_ascii=False, indent=1)
        print(f"    {bundle['n_articles']} articles | {bundle['n_domains']} sources | "
              f"{bundle['n_debunk']} debunk-leaning")
        summary_rows.append(bundle)

    usable = [b for b in summary_rows if b["n_articles"] >= 2 and b["summary"]]
    done = len([p for p in os.listdir(EVIDENCE_DIR) if p.endswith(".json")])
    print(f"\n{len(usable)}/{len(summary_rows)} loaded clusters usable | "
          f"{done}/{len(claims)} claims have evidence ({int(time.time() - started)}s this run) -> {EVIDENCE_DIR}")


if __name__ == "__main__":
    main()
