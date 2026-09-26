"""
verinews_common.py
==================
Helpers shared by the batch pipeline (Alex1.py) and the streaming extension
(streaming_topic_model.py) so that both produce identical labels, domains,
export files and quality metrics.

Nothing in here imports torch / transformers, so the module (and the unit
tests built on it) load in milliseconds.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field, replace
from statistics import median
from urllib.parse import urlparse

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def enable_utf8_stdio() -> None:
    """Make stdout/stderr tolerate the non-ASCII characters the pipeline prints.

    Python picks the *locale* encoding when stdout is a pipe or a redirect
    rather than a console, which is cp1252 on a default Windows install. The
    progress messages contain emoji, so `python Alex1.py > log.txt`, a CI step
    and any `| tail` raised UnicodeEncodeError deep inside scoring — where a
    broad `except` turned it into a neutral score of 50 for every cluster
    instead of a visible crash. Reconfiguring here fixes all of those call
    sites at once; `errors="replace"` keeps a terminal that genuinely cannot
    render a glyph from taking the pipeline down with it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass        # already UTF-8, detached, or not a real stream


# ---------------------------------------------------------------------------
# Triangulated Veracity Score — parameters and pure-maths core
# ---------------------------------------------------------------------------
# The constants live in one place so the parameter study
# (experiments/sweep_parameters.py) can vary them without touching the
# pipeline, and so the values used in the paper are traceable to a single
# definition. The defaults are the published v3.1 configuration; changing them
# changes the production score, so they are only ever overridden per call.
@dataclass(frozen=True)
class TVSParams:
    """Configuration of the three factors of the TVS."""

    # Factor 1 — semantic fidelity: score = base + range * mean(top-k cosine)
    semantic_base: float = 30.0
    semantic_range: float = 70.0
    top_k: int = 3                      # 0 or None = use every source
    # Factor 2 — domain diversity: multiplier per number of independent sources
    domain_ladder: tuple = ((5, 1.00), (4, 0.95), (3, 0.85), (2, 0.72), (1, 0.60))
    # Factor 3 — inter-source coherence: multiplier = base + range * mean pairwise cosine
    coherence_base: float = 0.70
    coherence_range: float = 0.30
    lone_source_coherence: float = 0.50  # a single source cannot agree with anyone
    # Factor 4 (experimental, OFF by default) — stance of the retrieved coverage.
    # 1.0 disables the factor entirely, so the production score is unchanged and
    # bit-identical to v3.1. The baseline study calibrates this on its own split
    # and reports the result as a clearly separate row; it is never applied to
    # the pipeline without that evidence.
    stance_base: float = 1.0
    # Reporting
    score_min: int = 5
    score_max: int = 99
    flag_threshold: int = 75             # below this the cluster is flagged for review
    label: str = "default (v3.1)"

    def domain_factor(self, n_domains: int) -> float:
        for threshold, factor in sorted(self.domain_ladder, reverse=True):
            if n_domains >= threshold:
                return float(factor)
        return float(min(self.domain_ladder, key=lambda pair: pair[0])[1])

    def with_values(self, **changes) -> "TVSParams":
        return replace(self, **changes)


DEFAULT_TVS_PARAMS = TVSParams()


def tvs_from_evidence(similarities, domains, pairwise_upper, params: TVSParams | None = None,
                      stance_support: float | None = None) -> dict:
    """Computes the TVS from pre-extracted evidence — no model, no I/O.

    similarities   : cosine(summary, source_i) for every source
    domains        : one source identity per source ('' = unidentifiable)
    pairwise_upper : upper triangle of the source x source cosine matrix
    stance_support : optional 0-1 share of retrieved coverage that supports
                     rather than refutes the claim. Ignored unless the caller
                     also lowers `params.stance_base` below 1.0, so passing it
                     can never change a production score by accident.
    """
    params = params or DEFAULT_TVS_PARAMS
    sims = [float(s) for s in (similarities if similarities is not None else [])]
    top_k = len(sims) if not params.top_k else min(params.top_k, len(sims))
    top = sorted(sims, reverse=True)[:top_k]
    avg_sim = sum(top) / len(top) if top else 0.0
    semantic_score = params.semantic_base + avg_sim * params.semantic_range

    unique_domains = sorted({d for d in (domains if domains is not None else []) if d})
    domain_factor = params.domain_factor(len(unique_domains))

    upper = [float(v) for v in (pairwise_upper if pairwise_upper is not None else [])]
    source_coherence = sum(upper) / len(upper) if upper else params.lone_source_coherence
    coherence_factor = params.coherence_base + source_coherence * params.coherence_range

    # Factor 4 is inert at stance_base = 1.0, which is the shipped default.
    stance_factor = 1.0
    if params.stance_base < 1.0:
        support = 0.5 if stance_support is None else max(0.0, min(1.0, float(stance_support)))
        stance_factor = params.stance_base + (1.0 - params.stance_base) * support

    raw = semantic_score * domain_factor * coherence_factor * stance_factor
    return {
        "final_score": max(params.score_min, min(params.score_max, int(raw))),
        "semantic_score": round(semantic_score, 2),
        "avg_similarity": round(avg_sim, 4),
        "domain_factor": domain_factor,
        "n_domains": len(unique_domains),
        "domains": unique_domains,
        "coherence_factor": round(coherence_factor, 4),
        "source_coherence": round(source_coherence, 4),
        "flagged": int(raw) < params.flag_threshold,
    }


def upper_triangle(matrix) -> list:
    """Upper triangle (i<j) of a square similarity matrix."""
    if matrix is None:
        return []
    n = len(matrix)
    return [float(matrix[i][j]) for i in range(n) for j in range(i + 1, n)]

# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------
# Hosts that merely redirect to or aggregate publishers. They never count as
# an independent source for the domain-diversity factor of the TVS.
AGGREGATOR_HOSTS = {
    "news.google.com", "google.com", "r.search.yahoo.com", "news.search.yahoo.com",
    "bing.com", "duckduckgo.com", "msn.com", "feedproxy.google.com",
}

_HOST_PREFIX_RE = re.compile(r"^(www\.|news\.|edition\.|feeds\.|amp\.|m\.)")


def registrable_domain(url: str) -> str:
    """'https://www.reuters.com/x' -> 'reuters.com'; '' when unparsable."""
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return ""
    return _HOST_PREFIX_RE.sub("", host)


def is_aggregator(url_or_host: str) -> bool:
    host = registrable_domain(url_or_host) if "//" in str(url_or_host) else str(url_or_host).lower()
    host = _HOST_PREFIX_RE.sub("", host)
    return host in AGGREGATOR_HOSTS or host.endswith(".google.com")


def publisher_domain(url: str, publisher_url: str | None = None) -> str:
    """Domain that should count as the article's source.

    Prefers the publisher URL announced by the feed (Google News RSS
    <source url="...">), then the article URL itself, and returns '' when
    only an aggregator/redirect host is known — an unresolved redirect must
    never masquerade as an independent source."""
    for candidate in (publisher_url, url):
        if not candidate:
            continue
        domain = registrable_domain(candidate)
        if domain and not is_aggregator(candidate):
            return domain
    return ""


# Publisher names that search engines report for syndicated copies (MSN,
# Yahoo) mapped to the outlet's own domain, so a wire story syndicated on
# msn.com still counts as the outlet that wrote it.
PUBLISHER_DOMAIN_HINTS = {
    "associated press": "apnews.com", "associated press news": "apnews.com", "ap news": "apnews.com",
    "reuters": "reuters.com", "bloomberg": "bloomberg.com", "cnbc": "cnbc.com", "cnn": "cnn.com",
    "cbs news": "cbsnews.com", "nbc news": "nbcnews.com", "abc news": "abcnews.go.com", "fox news": "foxnews.com",
    "fox business": "foxbusiness.com", "npr": "npr.org", "bbc": "bbc.co.uk", "bbc news": "bbc.co.uk",
    "the guardian": "theguardian.com", "the new york times": "nytimes.com", "new york times": "nytimes.com",
    "the wall street journal": "wsj.com", "wall street journal": "wsj.com", "the washington post": "washingtonpost.com",
    "washington post": "washingtonpost.com", "usa today": "usatoday.com", "financial times": "ft.com",
    "forbes": "forbes.com", "fortune": "fortune.com", "business insider": "businessinsider.com",
    "the motley fool": "fool.com", "motley fool": "fool.com", "marketwatch": "marketwatch.com",
    "investopedia": "investopedia.com", "yahoo finance": "finance.yahoo.com", "the hill": "thehill.com",
    "politico": "politico.com", "axios": "axios.com", "al jazeera": "aljazeera.com", "newsweek": "newsweek.com",
    "the independent": "independent.co.uk", "the telegraph": "telegraph.co.uk", "sky news": "news.sky.com",
    "the economist": "economist.com", "techcrunch": "techcrunch.com", "the verge": "theverge.com",
    "wired": "wired.com", "ars technica": "arstechnica.com", "engadget": "engadget.com", "zdnet": "zdnet.com",
    "coindesk": "coindesk.com", "cointelegraph": "cointelegraph.com", "kitco": "kitco.com",
    "european central bank": "ecb.europa.eu", "federal reserve": "federalreserve.gov",
}


def source_identity(url: str, publisher_url: str | None = None, publisher: str | None = None) -> str:
    """Identity of the independent source behind an article, for the TVS
    domain-diversity factor and the quality report.

    1. a real publisher domain (feed publisher URL, then article URL);
    2. otherwise the outlet's domain inferred from the publisher *name*
       reported by the feed/search engine (syndicated copies on msn.com);
    3. otherwise a name key ('name:cbs news') — still one identifiable outlet;
    4. '' when nothing but an aggregator host is known."""
    domain = publisher_domain(url, publisher_url)
    if domain:
        return domain
    name = re.sub(r"\s+", " ", str(publisher or "").strip().casefold())
    if not name:
        return ""
    if name in PUBLISHER_DOMAIN_HINTS:
        return PUBLISHER_DOMAIN_HINTS[name]
    return f"name:{name}"


# ---------------------------------------------------------------------------
# Text sanity (binary / language guards)
# ---------------------------------------------------------------------------
_ENGLISH_MARKERS = {
    "the", "and", "of", "to", "in", "is", "for", "on", "with", "that", "as", "by", "at", "from",
    "it", "are", "was", "has", "have", "this", "be", "an", "or", "its", "will", "said", "not",
}
_RO_DIACRITICS = set("șțăâîȘȚĂÂÎ")
_WORD_RE = re.compile(r"[a-zA-Z']+")


def looks_like_text(text: str) -> bool:
    """False for binary payloads that slipped through the HTTP layer
    (e.g. brotli bodies decoded as UTF-8): too many replacement/control
    characters or too few letters for the length."""
    s = str(text or "")
    if len(s) < 20:
        return bool(s.strip())
    replacement = s.count("�")
    control = sum(1 for ch in s if ord(ch) < 32 and ch not in "\n\r\t")
    letters = sum(1 for ch in s if ch.isalpha())
    if replacement / len(s) > 0.01 or control / len(s) > 0.01:
        return False
    return letters / len(s) >= 0.45


def is_probably_english(text: str, min_tokens: int = 12) -> bool:
    """Cheap language guard: English function-word density on the text
    (non-English rows used to leak Romanian tokens into cluster labels)."""
    s = str(text or "")
    if any(ch in _RO_DIACRITICS for ch in s) and sum(ch in _RO_DIACRITICS for ch in s) > len(s) * 0.004:
        return False
    tokens = [t.lower() for t in _WORD_RE.findall(s)]
    if len(tokens) < min_tokens:
        return True          # too short to judge: keep the row
    hits = sum(1 for t in tokens if t in _ENGLISH_MARKERS)
    return hits / len(tokens) >= 0.04


_BOILERPLATE_SENTENCE_RE = re.compile(
    r"(editorial polic|getty images|afp\b|updated \w+ \d{1,2}, \d{4}|subscribe|sign up|sign in|newsletter|"
    r"read more|click here|advertisement|cookie|privacy policy|terms of (use|service)|all rights reserved|"
    r"live blog|photo:|image:|\bvia\b .*\bnews\b|follow us|share this|watch:|listen:|©)",
    re.IGNORECASE,
)


def is_informative_sentence(sentence: str, min_words: int = 8, max_words: int = 70) -> bool:
    """Sentence filter for the extractive summarizer: drops site chrome,
    captions and credits so summaries are built from reporting sentences."""
    s = str(sentence or "").strip()
    words = s.split()
    if not (min_words <= len(words) <= max_words):
        return False
    if _BOILERPLATE_SENTENCE_RE.search(s):
        return False
    letters = sum(1 for ch in s if ch.isalpha())
    if letters / max(1, len(s)) < 0.6:
        return False
    if s.count("|") + s.count("•") > 0:
        return False
    return looks_like_text(s)


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------
_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+([^-–—|]{2,60})$")

KNOWN_OUTLETS = {
    "reuters", "bloomberg", "bbc", "bbc news", "cnn", "cnbc", "msn", "yahoo", "yahoo finance", "google",
    "ap", "ap news", "associated press", "axios", "politico", "the guardian", "guardian", "the new york times",
    "new york times", "nytimes", "wsj", "the wall street journal", "wall street journal", "ft",
    "financial times", "forbes", "fortune", "business insider", "insider", "investopedia", "marketwatch",
    "barron's", "kitco", "coindesk", "cointelegraph", "wion", "ndtv", "al jazeera", "hindustan times",
    "livemint", "mint", "the economic times", "economic times", "moneycontrol", "newsweek", "the hill",
    "npr", "abc news", "nbc news", "cbs news", "fox news", "fox business", "usa today", "los angeles times",
    "the washington post", "washington post", "the seattle times", "seattle times", "geekwire", "techcrunch",
    "the verge", "wired", "ars technica", "engadget", "zdnet", "the register", "tom's hardware",
    "european central bank", "federal reserve", "the economist", "time", "euronews", "dw", "france 24",
    "sky news", "the independent", "the telegraph", "daily mail", "the times", "express", "mirror",
}


def strip_publisher_suffix(title: str, publisher: str | None = None) -> str:
    """Removes a trailing ' - Publisher' that Google News appends to headlines.

    Only strips when the suffix is the announced publisher or a known outlet,
    so headlines that legitimately end with ' - something' survive."""
    text = str(title or "").strip()
    match = _SUFFIX_RE.search(text)
    if not match:
        return text
    suffix = match.group(1).strip()
    suffix_key = suffix.casefold()
    publisher_key = (publisher or "").strip().casefold()
    if publisher_key and (suffix_key == publisher_key or suffix_key in publisher_key or publisher_key in suffix_key):
        return text[: match.start()].strip()
    if suffix_key in KNOWN_OUTLETS:
        return text[: match.start()].strip()
    return text


# ---------------------------------------------------------------------------
# Topic labels (c-TF-IDF vocabulary hygiene)
# ---------------------------------------------------------------------------
# Web/feed boilerplate that used to leak into cluster names such as
# "9_com_source google_google_report direct".
WEB_BOILERPLATE_STOP_WORDS = [
    "español", "english", "français", "deutsch", "italiano", "română",
    "read", "more", "subscribe", "news", "share", "advertisement", "newsletter",
    "united", "states", "com", "www", "http", "https", "html", "source", "sources",
    "google", "report", "reports", "reporting", "direct", "says", "said", "say",
    "live", "latest", "update", "updates", "updated", "video", "watch", "breaking",
    "exclusive", "opinion", "analysis", "explained", "explainer", "coverage", "story",
    "stories", "full", "hosted", "portal", "details", "topic", "today", "yesterday",
    "week", "month", "year", "time", "day", "2024", "2025", "2026",
]

_OUTLET_TOKENS = {tok for name in KNOWN_OUTLETS for tok in re.findall(r"[a-z0-9]+", name) if len(tok) > 2}
# Generic words that also occur inside outlet names must stay available as
# topic terms ("bank", "times", "post", "central" ...).
_OUTLET_TOKENS -= {"news", "times", "post", "bank", "central", "european", "federal", "reserve",
                   "business", "economic", "financial", "daily", "street", "wall", "york", "new",
                   "los", "angeles", "seattle", "washington", "hill", "express", "mirror", "time",
                   "independent", "register", "verge", "insider", "economist", "hardware"}


def build_stop_words(publisher_domains: "list[str] | set[str] | None" = None) -> list[str]:
    """English stop words + web boilerplate + outlet names + the registrable
    labels of the publishers present in the corpus (e.g. 'cnbc', 'wbaltv')."""
    words = set(ENGLISH_STOP_WORDS) | set(WEB_BOILERPLATE_STOP_WORDS) | _OUTLET_TOKENS
    for domain in publisher_domains or ():
        label = str(domain).split(".")[0].lower()
        if len(label) > 2:
            words.add(label)
    return sorted(words)


_LABEL_STOP_TOKENS = set(ENGLISH_STOP_WORDS) | set(WEB_BOILERPLATE_STOP_WORDS) | _OUTLET_TOKENS


def select_label_terms(ranked_terms: list[str], n: int = 4, stop_words=None) -> list[str]:
    """Greedy, order-preserving selection of distinct c-TF-IDF terms.

    Given terms ranked by score (unigrams and bigrams mixed) it drops terms
    made only of stop/boilerplate words, drops terms whose words are already
    covered, and prefers a bigram over a previously chosen unigram it contains:
        ['trump', 'trump administration', 'administration', 'source'] ->
        ['trump administration']
    """
    stop = _LABEL_STOP_TOKENS if stop_words is None else set(stop_words) | _LABEL_STOP_TOKENS

    def stem(word: str) -> str:   # 'rates' ~ 'rate', 'elections' ~ 'election'
        return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word

    chosen: list[str] = []
    for term in ranked_terms:
        words = [w for w in str(term).lower().split() if w]
        if not words or any(len(w) < 2 for w in words):
            continue
        if all(w in stop for w in words):
            continue
        stems = [stem(w) for w in words]
        # skip a term fully covered by what we already have
        covered = {stem(w) for t in chosen for w in t.split()}
        if all(s in covered for s in stems):
            continue
        # a bigram absorbs a unigram it contains
        chosen = [t for t in chosen if not (len(t.split()) == 1 and stem(t) in stems)]
        chosen.append(" ".join(words))
        if len(chosen) >= n:
            break
    return chosen


def build_topic_label(cluster_id: int, ranked_terms: list[str], n: int = 4) -> str:
    terms = select_label_terms(ranked_terms, n=n) or [f"cluster {cluster_id}"]
    return f"{cluster_id}_" + "_".join(terms)


def clean_topic_title(topic_name: str) -> str:
    """'8_election_primary_2026_midterm' -> 'Election Primary 2026 Midterm'.

    Drops the numeric prefix, splits on '_' and whitespace, removes repeated
    words (case-insensitive) and title-cases the remainder."""
    name = str(topic_name or "").strip()
    parts = name.split("_")
    if len(parts) > 1 and parts[0].lstrip("-").isdigit():
        parts = parts[1:]
    words, seen = [], set()
    for part in parts:
        for word in part.split():
            key = word.casefold()
            if key in seen:
                continue
            seen.add(key)
            words.append(word)
    return " ".join(w if w.isupper() else w.capitalize() for w in words) or name


# ---------------------------------------------------------------------------
# Corpus quality report
# ---------------------------------------------------------------------------
def corpus_quality_report(df) -> dict:
    """Summarises how trustworthy the ingested corpus is.

    resolvedDomainShare : share of rows whose URL (or feed publisher URL) is a real publisher domain
    knownSourceShare    : share of rows whose outlet is identifiable (domain or publisher name)
    bodyAvailableShare  : share of rows with a scraped article body
    medianBodyChars     : median length of the Text column
    nDomains            : number of distinct identifiable sources
    """
    n = int(len(df))
    if n == 0:
        return {"documents": 0, "resolvedDomainShare": 0.0, "knownSourceShare": 0.0, "bodyAvailableShare": 0.0,
                "medianBodyChars": 0, "nDomains": 0, "aggregatorRows": 0}

    publisher_urls = df["Publisher_URL"].tolist() if "Publisher_URL" in df.columns else [None] * n
    publishers = df["Publisher"].tolist() if "Publisher" in df.columns else [None] * n
    urls = df["URL"].astype(str).tolist()
    resolved = [bool(publisher_domain(u, p if isinstance(p, str) else None)) for u, p in zip(urls, publisher_urls)]
    domains = [
        source_identity(u, p if isinstance(p, str) else None, name if isinstance(name, str) else None)
        for u, p, name in zip(urls, publisher_urls, publishers)
    ]

    if "Body_Available" in df.columns:
        body_available = [bool(v) for v in df["Body_Available"].fillna(False)]
    else:  # legacy corpora: infer from length and the old stub marker
        texts = df["Text"].astype(str)
        body_available = [len(t) >= 300 and "[Full report at direct source" not in t for t in texts]

    return {
        "documents": n,
        "resolvedDomainShare": round(sum(resolved) / n, 4),
        "knownSourceShare": round(sum(1 for d in domains if d) / n, 4),
        "bodyAvailableShare": round(sum(body_available) / n, 4),
        "medianBodyChars": int(median(len(str(t)) for t in df["Text"])),
        "nDomains": len({d for d in domains if d}),
        "aggregatorRows": int(n - sum(resolved)),
    }


def quality_warnings(report: dict) -> list[str]:
    warnings = []
    if report.get("documents", 0) and report.get("knownSourceShare", 0) < 0.5:
        warnings.append(
            f"only {report['knownSourceShare']:.0%} of documents have an identifiable publisher — "
            "the domain-diversity factor of the TVS is unreliable for this corpus"
        )
    if report.get("documents", 0) and report.get("bodyAvailableShare", 0) < 0.5:
        warnings.append(
            f"only {report['bodyAvailableShare']:.0%} of documents have a scraped body — "
            "summaries, sentiment and NER run on headlines/snippets"
        )
    return warnings


# ---------------------------------------------------------------------------
# Export locations & atomic JSON writes
# ---------------------------------------------------------------------------
EXPORT_SCHEMA_VERSION = 2
OSINT_EXPORT_FILENAME = "osint_output.json"


def resolve_public_dir() -> str:
    """Single canonical export directory (the Next.js `public/` folder).

    Override with VERINEWS_PUBLIC_DIR. Resolved relative to this file, not the
    current working directory, so a pipeline spawned from elsewhere still
    feeds the dashboard."""
    configured = os.environ.get("VERINEWS_PUBLIC_DIR")
    directory = os.path.abspath(configured) if configured else os.path.join(REPO_ROOT, "public")
    os.makedirs(directory, exist_ok=True)
    return directory


def _json_default(obj):
    import numpy as np

    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def atomic_write_json(payload, dest_path: str) -> str:
    """Temp file + os.replace: readers never observe a half-written file."""
    directory = os.path.dirname(dest_path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=_json_default)
        os.replace(tmp_path, dest_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return dest_path


def export_envelope(topics: list, quality_report: dict, generated_by: str) -> dict:
    """Top-level shape of osint_output.json (schema v2).

    The dashboard also accepts the legacy bare list of topics."""
    import time

    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generatedBy": generated_by,
        "qualityReport": quality_report,
        "topics": topics,
    }
