"""
baselines.py — reference methods the TVS is compared against.

The three tools the reviewers named (NewsGuard, Justificat.ro, isitfake.app)
are closed products, so their scores cannot be obtained for our clusters. All
three do, however, publish how they work, and B1, B6 and B7 reproduce those
published *methods*:

  B1  NewsGuard      nine apolitical criteria with published point weights
                     summing to 100, scored per publisher.
  B6  isitfake.app   extract each claim, cross-reference it against
                     independent sources, check the cited sources exist;
                     report a 0-100 trust score.
  B7  Justificat.ro  judge the claim against evidence retrieved live rather
                     than against pre-trained knowledge; report a confidence.

Each substitutes an automated signal for the part of the vendor's pipeline we
cannot run — staff journalists for B1, an LLM ensemble for B6 and B7. They
therefore reproduce the *approach*, and none of them is the vendor's own
output; the paper states this limitation rather than hiding it.

The remaining baselines are the families this literature actually compares
against: lexical sensationalism cues, lexical overlap verification, a
source-count heuristic, and the semantic-only ablation of our own score.

All methods read the same frozen evidence bundles, so the comparison is
like-for-like, and all return a 0-100 credibility-style score (higher = more
trustworthy) so they share an axis with the TVS.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from verinews_common import registrable_domain  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DOMAIN_CACHE = os.path.join(HERE, "cache", "domain_profiles.json")

# ---------------------------------------------------------------------------
# B1 — NewsGuard-style source reputation
# ---------------------------------------------------------------------------
# The nine criteria and their published weights (newsguardtech.com, "Rating
# Process and Criteria"). Criteria that require editorial judgement over time
# (repeatedly publishes false content, responsible gathering, corrections) are
# approximated by the transparency artefacts a site publishes; this is stated
# as a limitation in the paper rather than hidden.
NEWSGUARD_CRITERIA = [
    ("no_repeated_false_content", 22.0),
    ("responsible_gathering", 18.0),
    ("corrections_policy", 12.5),
    ("news_opinion_separation", 12.5),
    ("no_deceptive_headlines", 10.0),
    ("ownership_financing_disclosed", 7.5),
    ("advertising_labelled", 7.5),
    ("who_is_in_charge", 5.0),
    ("content_creators_named", 5.0),
]

# Probed pages: a credible outlet publishes these; they are the machine-checkable
# half of NewsGuard's transparency criteria.
PROBE_PATHS = {
    "about": ["/about", "/about-us", "/about/", "/aboutus"],
    "corrections": ["/corrections", "/corrections-policy", "/accuracy", "/ethics", "/standards", "/editorial-standards"],
    "staff": ["/staff", "/team", "/authors", "/contributors", "/masthead", "/people"],
    "contact": ["/contact", "/contact-us", "/contacts"],
}

SENSATIONAL_LEXICON = {
    "shocking", "shocked", "stunning", "unbelievable", "incredible", "insane", "outrageous",
    "bombshell", "explosive", "slams", "slammed", "destroys", "destroyed", "obliterates",
    "secret", "secrets", "exposed", "reveals", "revealed", "truth", "hoax", "conspiracy",
    "banned", "censored", "silenced", "miracle", "cure", "terrifying", "horrifying",
    "you won't believe", "what happened next", "doctors hate", "they don't want you to know",
    "wake up", "sheeple", "mainstream media", "msm", "plandemic", "scandal", "busted",
}


def _load_domain_cache() -> dict:
    if os.path.exists(DOMAIN_CACHE):
        try:
            with open(DOMAIN_CACHE, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def _save_domain_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(DOMAIN_CACHE), exist_ok=True)
    with open(DOMAIN_CACHE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)


def profile_domain(domain: str, cache: dict, offline: bool = False) -> dict:
    """Checks the transparency artefacts of one publisher domain (cached)."""
    if domain in cache:
        return cache[domain]
    profile = {key: False for key in PROBE_PATHS}
    profile["reachable"] = False
    if not offline and domain and not domain.startswith("name:"):
        import Alex1  # local import: keeps this module importable without the pipeline

        base = f"https://{domain}"
        response = Alex1._request_with_retry(base, max_retries=1, timeout=12)
        if response is not None and response.status_code < 400:
            profile["reachable"] = True
            html = response.text[:400000]
            links = {m.lower() for m in re.findall(r'href=["\']([^"\']+)["\']', html)}
            for key, paths in PROBE_PATHS.items():
                profile[key] = any(any(p in link for p in paths) for link in links)
            profile["has_bylines"] = bool(
                re.search(r'rel=["\']author', html, re.I)
                or re.search(r'class=["\'][^"\']*(author|byline)', html, re.I)
            )
            profile["labels_ads"] = bool(re.search(r"(sponsored|advertisement|promoted content)", html, re.I))
            profile["labels_opinion"] = bool(re.search(r"\b(opinion|editorial|commentary)\b", html, re.I))
        time.sleep(0.4)
    cache[domain] = profile
    return profile


def newsguard_style_score(bundle: dict, cache: dict | None = None, offline: bool = False) -> float:
    """B1: mean source-level reputation across the cluster's publishers, using
    NewsGuard's published criteria weights."""
    cache = cache if cache is not None else _load_domain_cache()
    domains = sorted({a["domain"] for a in bundle["articles"] if a.get("domain")})
    if not domains:
        return 0.0

    scores = []
    for domain in domains:
        profile = profile_domain(domain, cache, offline=offline)
        earned = 0.0
        for criterion, weight in NEWSGUARD_CRITERIA:
            if criterion == "ownership_financing_disclosed":
                ok = profile.get("about", False)
            elif criterion == "corrections_policy":
                ok = profile.get("corrections", False)
            elif criterion == "who_is_in_charge":
                ok = profile.get("staff", False) or profile.get("contact", False)
            elif criterion == "content_creators_named":
                ok = profile.get("has_bylines", False) or profile.get("staff", False)
            elif criterion == "advertising_labelled":
                ok = profile.get("labels_ads", False)
            elif criterion == "news_opinion_separation":
                ok = profile.get("labels_opinion", False)
            elif criterion == "no_deceptive_headlines":
                titles = [a["title"] for a in bundle["articles"] if a.get("domain") == domain]
                ok = not any(_sensational_hits(t) >= 2 for t in titles)
            else:
                # criteria needing longitudinal editorial review: credited when
                # the site is reachable and publishes its standards
                ok = profile.get("reachable", False) and (profile.get("about", False) or profile.get("corrections", False))
            earned += weight if ok else 0.0
        scores.append(earned)
    return round(sum(scores) / len(scores), 2)


# ---------------------------------------------------------------------------
# B2 — sensationalism lexicon
# ---------------------------------------------------------------------------
def _sensational_hits(text: str) -> int:
    low = str(text or "").lower()
    hits = sum(1 for term in SENSATIONAL_LEXICON if term in low)
    words = low.split()
    if words:
        caps = sum(1 for w in str(text).split() if len(w) > 3 and w.isupper())
        hits += min(3, caps)
    hits += min(3, str(text or "").count("!"))
    return hits


def sensational_lexicon_score(bundle: dict) -> float:
    """B2: the classic lexical-cue baseline — more sensational language across
    the cluster, lower credibility."""
    articles = bundle["articles"]
    if not articles:
        return 0.0
    per_article = []
    for article in articles:
        text = f"{article.get('title', '')} {str(article.get('text', ''))[:600]}"
        density = _sensational_hits(text) / max(1, len(text.split()) / 100)
        per_article.append(min(1.0, density / 6.0))
    mean_sensationalism = sum(per_article) / len(per_article)
    return round(100.0 * (1.0 - mean_sensationalism), 2)


# ---------------------------------------------------------------------------
# B3 — TF-IDF overlap (VeriNews v1.9 ancestor)
# ---------------------------------------------------------------------------
def tfidf_overlap_score(bundle: dict) -> float:
    """B3: lexical verification — cosine between the summary and its sources in
    TF-IDF space, i.e. the pre-SBERT version of factor 1."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    summary = bundle.get("summary") or ""
    texts = [str(a.get("text", "")) for a in bundle["articles"] if str(a.get("text", "")).strip()]
    if not summary or not texts:
        return 0.0
    try:
        matrix = TfidfVectorizer(stop_words="english", max_features=20000).fit_transform([summary] + texts)
    except ValueError:
        return 0.0
    sims = cosine_similarity(matrix[0:1], matrix[1:])[0]
    top = sorted(sims, reverse=True)[: min(3, len(sims))]
    return round(100.0 * (sum(top) / len(top)), 2)


# ---------------------------------------------------------------------------
# B4 — source-count heuristic
# ---------------------------------------------------------------------------
def source_count_score(bundle: dict) -> float:
    """B4: what simple aggregators do — trust grows with the number of outlets."""
    n_domains = len({a["domain"] for a in bundle["articles"] if a.get("domain")})
    return float(min(99, max(0, 45 + 10 * n_domains)))


# ---------------------------------------------------------------------------
# B5 — semantic-only ablation
# ---------------------------------------------------------------------------
def semantic_only_score(bundle: dict, params=None) -> float:
    """B5: factor 1 alone — no diversity, no coherence (ablation of our model)."""
    from verinews_common import DEFAULT_TVS_PARAMS

    params = params or DEFAULT_TVS_PARAMS
    sims = [float(s) for s in (bundle.get("similarities") or [])]
    if not sims:
        return 0.0
    top = sorted(sims, reverse=True)[: min(params.top_k or len(sims), len(sims))]
    return round(params.semantic_base + (sum(top) / len(top)) * params.semantic_range, 2)


# ---------------------------------------------------------------------------
# B6 — claim-level substantiation (isitfake.app-style)
# ---------------------------------------------------------------------------
# Their published method is three steps: extract the individual claims, cross
# reference each against independent sources and established outlets, then
# check that the quoted sources actually exist and support the claim. The
# output is a 0-100 Trust Score plus a claim-by-claim breakdown. B6 reproduces
# that shape over the frozen bundles, with a cosine threshold standing in for
# their LLM ensemble's judgement of support.
CLAIM_SUPPORT_THRESHOLD = 0.55


def claim_substantiation_score(bundle: dict) -> float:
    """B6: share of the summary's claims backed by an independent publisher."""
    claims = bundle.get("claims") or []
    matrix = bundle.get("claim_similarities")
    articles = bundle.get("articles") or []
    if not claims or not matrix:
        return 0.0

    substantiated = 0
    for row in matrix:
        # "independent" = distinct publishers, so one outlet syndicated five
        # times cannot substantiate a claim on its own.
        backers = {
            articles[j].get("domain")
            for j, value in enumerate(row)
            if j < len(articles) and float(value) >= CLAIM_SUPPORT_THRESHOLD and articles[j].get("domain")
        }
        if len(backers) >= 2:
            substantiated += 1
    share = substantiated / len(claims)

    # Their third step: do the cited sources resolve to something real? The
    # bundles already record whether each URL resolved and yielded a body.
    if articles:
        real = sum(1 for a in articles if a.get("url_resolved") and a.get("body_available"))
        existence = real / len(articles)
    else:
        existence = 0.0
    return round(100.0 * (0.75 * share + 0.25 * existence), 2)


# ---------------------------------------------------------------------------
# B7 — evidence-conditioned verdict (Justificat.ro-style)
# ---------------------------------------------------------------------------
# Their published method combines AI models with live web search: queries are
# formulated, source content is extracted in real time, and the verdict is
# grounded in that retrieved evidence rather than in pre-trained knowledge,
# reported with a 0-100% confidence. B7 keeps the structure - judge the claim
# against what retrieval actually returned - and substitutes the stance signal
# already recorded per source for their model's reading of it.
def evidence_verdict_score(bundle: dict) -> float:
    """B7: confidence that retrieved coverage supports rather than refutes."""
    articles = bundle.get("articles") or []
    if not articles:
        return 0.0

    weighted_support, weight_total = 0.0, 0.0
    for article in articles:
        # A source that was actually read counts for more than a headline,
        # which is what "extracts content from sources" buys them.
        weight = 1.0 if article.get("body_available") else 0.5
        stance = article.get("stance", "neutral")
        support = {"debunk": 0.0, "neutral": 0.5, "promote": 1.0}.get(stance, 0.5)
        weighted_support += weight * support
        weight_total += weight

    confidence = weighted_support / weight_total if weight_total else 0.5
    # Thin evidence lowers confidence rather than producing a bold verdict.
    coverage = min(1.0, len({a.get("domain") for a in articles if a.get("domain")}) / 5.0)
    return round(100.0 * confidence * (0.6 + 0.4 * coverage), 2)


BASELINES = {
    "B1 source reputation (NewsGuard-style)": newsguard_style_score,
    "B2 sensationalism lexicon": sensational_lexicon_score,
    "B3 TF-IDF overlap": tfidf_overlap_score,
    "B4 source count": source_count_score,
    "B5 semantic fidelity only": semantic_only_score,
    "B6 claim substantiation (isitfake-style)": claim_substantiation_score,
    "B7 evidence verdict (Justificat-style)": evidence_verdict_score,
}


def score_all(bundles: list[dict], offline: bool = False) -> dict:
    """Runs every baseline over every bundle -> {method: {claim_id: score}}."""
    cache = _load_domain_cache()
    out: dict[str, dict[str, float]] = {name: {} for name in BASELINES}
    for bundle in bundles:
        for name, fn in BASELINES.items():
            try:
                value = fn(bundle, cache, offline) if fn is newsguard_style_score else fn(bundle)
            except Exception as error:
                print(f"    {name} failed on {bundle['claim_id']}: {error}")
                value = math.nan
            out[name][bundle["claim_id"]] = value
    _save_domain_cache(cache)
    return out
