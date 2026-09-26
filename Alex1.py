import argparse
import pandas as pd
import time
import random
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from dateutil import parser as dateutil_parser
from urllib.parse import urlparse
import os
import sys
import warnings
import logging
import gc
import re
import urllib3
import numpy as np

# Heavy dependencies (plotly, trafilatura, duckduckgo_search, transformers,
# sentence-transformers, keybert) are imported inside the functions that need
# them, so `import Alex1` stays cheap for the unit tests and for the streaming
# module. The SBERT model is loaded lazily via get_embedding_model().
from verinews_common import (
    REPO_ROOT, atomic_write_json, build_stop_words, build_topic_label, clean_topic_title,
    corpus_quality_report, export_envelope, publisher_domain, quality_warnings,
    is_informative_sentence, is_probably_english, looks_like_text, registrable_domain, resolve_public_dir,
    source_identity, strip_publisher_suffix, tvs_from_evidence, upper_triangle,
    DEFAULT_TVS_PARAMS, OSINT_EXPORT_FILENAME, TVSParams, enable_utf8_stdio,
)

# ==========================================
# 0. DISSERTATION CONFIGURATION
# ==========================================
# Before anything prints: the progress messages below contain emoji, and a
# redirected stdout defaults to the locale encoding (cp1252 on Windows), which
# used to raise UnicodeEncodeError inside scoring and silently degrade every
# cluster to a neutral 50.
enable_utf8_stdio()

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

log = logging.getLogger("verinews")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

TOPICS = [
    # 1. Geopolitics
    "US Elections 2026", "Donald Trump Administration", "JD Vance Statements",
    "Ukraine Russia War", "Israel Gaza Conflict", "China Taiwan Tensions",
    # 2. Technology
    "Artificial Intelligence News", "OpenAI ChatGPT Updates", "NVIDIA Stock Market",
    "DeepSeek AI China", "Tech Industry Layoffs", "Apple vs Samsung",
    # 3. Economy
    "Federal Reserve Interest Rates", "Bitcoin Price Analysis", "Global Recession 2026",
    "Oil Prices OPEC", "Gold Market Trends", "European Central Bank"
]

MAX_ARTICLES_PER_TOPIC = 15
FILENAME_EXCEL = "Dataset_Dissertation_Final.xlsx"
FILENAME_CHECKPOINT = "Checkpoint_Scraped_Data.csv"
FILENAME_REPORT = "Content_Ready_For_VERINEWS_EN.txt"
FILENAME_VIZ_HTML = "Viz_Dissertation_Topology.html"
FILENAME_VIZ_SCATTER = "Viz_Clusters_Scatter.html"
EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"   # 768-d unified SBERT space

# Directory that receives xlsx / txt / html artefacts (overridable via CLI).
OUTPUT_DIR = REPO_ROOT

# ------------------------------------------------------------------
# [IMPROVEMENT #6] Rotating User-Agent Pool
# A pool of realistic browser User-Agent strings. One is randomly
# selected per HTTP request to reduce fingerprinting and lower the
# probability of IP bans during long scraping runs.
# ------------------------------------------------------------------
USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 OPR/107.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


try:  # requests only decodes brotli when one of these is installed
    import brotli  # noqa: F401
    _BROTLI_OK = True
except ImportError:  # pragma: no cover
    try:
        import brotlicffi  # noqa: F401
        _BROTLI_OK = True
    except ImportError:
        _BROTLI_OK = False


def _get_random_headers(is_google=False):
    """Returns an HTTP headers dict with a randomly selected User-Agent and evasion settings."""
    ua = random.choice(USER_AGENT_POOL)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Advertising `br` without a decoder yields undecodable bodies that
        # used to end up as binary garbage in the corpus.
        "Accept-Encoding": "gzip, deflate, br" if _BROTLI_OK else "gzip, deflate",
        "Connection": "keep-alive"
    }
    if is_google:
        headers["Cookie"] = "CONSENT=YES+cb.20230501-14-p0.en+FX+410"
    return headers


# ==========================================
# GLOBAL AI MODEL LOADER (The Architecture Fix)
# ==========================================
# One embedding model instance is shared by every stage (dedup, clustering,
# KeyBERT, veracity scoring, JSON export) so all vectors live in the same
# 768-d space. It is loaded on first use, not at import time: the unit tests
# and the streaming module can import this file without pulling in torch.
_EMBEDDING_MODEL = None


def get_embedding_model():
    """Returns the shared SentenceTransformer, loading it on first call."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        print(f"⏳ Loading Unified SBERT Model ({EMBEDDING_MODEL_NAME})...")
        from sentence_transformers import SentenceTransformer

        _EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME, device='cpu')
        print(f"✅ Unified Model Loaded ({EMBEDDING_MODEL_NAME}, 768-dim). Ready for Pipeline.")
    return _EMBEDDING_MODEL


# ------------------------------------------------------------------
# [v4.0] Embedding memoization cache.
# The pipeline encodes overlapping text sets in several stages
# (dedup, clustering, veracity scoring, JSON export). Memoizing by
# exact string guarantees bit-identical vectors across stages while
# eliminating redundant CPU encodes.
# ------------------------------------------------------------------
_EMBEDDING_CACHE = {}


def encode_texts_cached(texts):
    """Encodes texts with the shared SBERT model, memoized per exact string."""
    missing = list(dict.fromkeys(t for t in texts if t not in _EMBEDDING_CACHE))
    if missing:
        vectors = get_embedding_model().encode(missing, show_progress_bar=False)
        for text, vec in zip(missing, vectors):
            _EMBEDDING_CACHE[text] = vec
    return np.array([_EMBEDDING_CACHE[t] for t in texts])


# ==========================================
# 1. DATA INGESTION
# ==========================================
def clean_text_logic(raw_text):
    if not raw_text:
        return ""
    
    # Process line-by-line first to keep matches bounded to their respective lines.
    # This prevents a boilerplate phrase from discarding subsequent valid paragraphs.
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue
            
        lower_line = stripped_line.lower()
        
        # Discard the entire line if it consists solely of standard boilerplate
        if lower_line in [
            "read more", "click here", "subscribe", "subscribe to", 
            "all rights reserved", "enable javascript", "loading", "loading..."
        ]:
            continue
            
        # Eliminate specific boilerplate signals and trailing junk inside a line,
        # but keep it strictly isolated to the current line!
        stripped_line = re.sub(r"\bRead more\b.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"\bClick here\b.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"\bSubscribe to\b.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"© \d{4}.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"\bAll rights reserved\b.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"\bEnable JavaScript\b.*", "", stripped_line, flags=re.IGNORECASE)
        stripped_line = re.sub(r"\bLoading\b.*", "", stripped_line, flags=re.IGNORECASE)
        
        final_line = stripped_line.strip()
        if final_line:
            cleaned_lines.append(final_line)
            
    # Combine lines and clean extra whitespaces
    text = " ".join(" ".join(cleaned_lines).split())
    return text.replace('\x00', '').strip()


# ------------------------------------------------------------------
# [IMPROVEMENT #4] Retry with Exponential Backoff
# Wraps requests.get() to recover from transient network errors and
# rate-limit responses (HTTP 429 / 5xx). Retries up to max_retries
# times with exponentially increasing delays (2s, 4s, 8s).
# ------------------------------------------------------------------
def _request_with_retry(url, max_retries=3, timeout=8):
    """
    Performs an HTTP GET with retry logic and exponential backoff.

    Retries on:
      - Network/connection errors (requests.exceptions.RequestException)
      - Server errors (HTTP 5xx)
      - Rate-limit responses (HTTP 429)

    Returns the Response object on success, or None after all retries fail.
    """
    import urllib3
    is_google = "google.com" in url or "google." in url
    for attempt in range(max_retries):
        try:
            headers = _get_random_headers(is_google=is_google)  # [IMPROVEMENT #6] Rotate UA per attempt
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=timeout if timeout is not None else 8,
                    verify=True,
                    allow_redirects=True
                )
            except requests.exceptions.SSLError:
                # Some regional news hosts ship broken certificate chains.
                # Retry once unverified rather than losing the source, but
                # verification stays on by default for everyone else.
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=timeout if timeout is not None else 8,
                    verify=False,
                    allow_redirects=True
                )

            # If server returned 429 (rate limit) or 5xx (server error), retry
            if response.status_code == 429 or response.status_code >= 500:
                wait_time = 2 ** (attempt + 1)  # 2s, 4s, 8s
                time.sleep(wait_time)
                continue

            return response  # Success (any 2xx/3xx/4xx except 429)

        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError, MemoryError) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                time.sleep(wait_time)
            continue
        except Exception:
            # Never swallow KeyboardInterrupt/SystemExit — Ctrl-C must work.
            continue

    return None  # All retries exhausted


# ------------------------------------------------------------------
# [IMPROVEMENT #3] Trafilatura Text Extraction with BS4 Fallback
# Trafilatura is purpose-built for article body extraction. It handles
# cookie banners, sidebars, navigation, ads, and boilerplate far
# better than raw BeautifulSoup get_text(). If trafilatura returns
# nothing (e.g., paywalled or JavaScript-heavy sites), we fall back
# to the original BeautifulSoup approach.
# ------------------------------------------------------------------
_CONSENT_URL_MARKERS = ("consent.google", "consent.youtube", "consent.yahoo", "guce.yahoo", "legal.yahoo")
_CONSENT_TEXT_MARKERS = (
    "before you continue to google", "înainte de a continua", "consent.google", "google uses cookies",
    "yahoo is part of the yahoo family of brands", "we, yahoo, are part of", "confidențialitatea dvs.",
    "folosim module cookie", "wir, yahoo, sind teil", "nous, yahoo, faisons partie",
)


def _is_consent_url(url):
    lower = str(url or "").lower()
    return any(marker in lower for marker in _CONSENT_URL_MARKERS)


def _is_consent_text(text):
    """Cookie/consent walls (Google, Yahoo — often served in the visitor's
    language) must never be mistaken for an article body."""
    lower = str(text or "")[:3000].lower()
    return any(marker in lower for marker in _CONSENT_TEXT_MARKERS)


def _scrape_full_text(url, timeout=8):
    """
    Downloads a URL and extracts clean article body text.

    Strategy:
      1. Fetch HTML using our evasive _request_with_retry which rotates UAs 
         and injects cookie consent bypass parameters.
      2. If successful, extract text using Trafilatura for precise article parsing.
      3. FALLBACK: BeautifulSoup get_text() on the same fetched html.
    """
    import urllib3
    if _is_consent_url(url):
        return ""

    try:
        response = _request_with_retry(url, max_retries=2, timeout=timeout)
        if response is None or response.status_code != 200:
            return ""

        # Check if we were redirected to a Consent/Cookie Wall
        if _is_consent_url(response.url):
            return ""

        # Use Trafilatura on the downloaded content
        try:
            import trafilatura

            extracted = trafilatura.extract(
                response.content,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )
            if extracted and len(extracted) >= 300 and looks_like_text(extracted):
                if _is_consent_text(extracted):
                    pass # Fall through to BeautifulSoup
                else:
                    return clean_text_logic(extracted)
        except Exception:
            pass

        # BeautifulSoup Fallback on downloaded content
        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove non-content elements that pollute the corpus
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "form", "iframe", "ads", "aside", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator=' ')
        text = clean_text_logic(text)
        
        # Verify content (consent walls, binary payloads)
        if _is_consent_text(text):
            return ""
        if not looks_like_text(text):   # binary payloads (e.g. undecoded brotli)
            return ""
        return text
    except (MemoryError, urllib3.exceptions.HTTPError, Exception):
        return ""


# ------------------------------------------------------------------
# [v4.0] Concurrent article-body fetching.
# Sequential per-article sleeps dominated ingestion wall-clock time.
# Bodies are fetched in parallel ACROSS distinct publisher domains
# (each URL is still a single request, jittered so bursts stay spread
# out). Output order matches input order exactly.
# ------------------------------------------------------------------
def _scrape_bodies_concurrent(urls, timeout=8, max_workers=6):
    if not urls:
        return []

    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(url):
        if not url:
            return ""
        time.sleep(random.uniform(0.1, 0.6))  # polite jitter
        try:
            return _scrape_full_text(url, timeout=timeout)
        except Exception:
            return ""

    workers = max(1, min(max_workers, len(urls)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_fetch_one, urls))


def _decode_gnews_url(gnews_url, decoder=None):
    """
    Resolves a Google News RSS redirect (news.google.com/rss/articles/...)
    to the publisher's direct URL.

      1. googlenewsdecoder (network round-trip to Google's batchexecute
         endpoint; handles the 2024+ 'CBMi…' payloads). Its result dict uses
         status=True — NOT 'success' — which is exactly what the previous
         version compared against, silently discarding every successful
         decode and leaving 94 % of the corpus on the raw redirect link.
      2. Legacy base64 payloads (pre-2024 links) decoded locally.

    Returns the redirect itself when nothing works; callers must then treat
    the row as unresolved (see publisher_domain / URL_Resolved).
    `decoder` is injectable for tests.
    """
    try:
        if "/articles/" not in gnews_url:
            return gnews_url

        if decoder is None:
            try:
                from googlenewsdecoder import gnewsdecoder as decoder
            except Exception:
                decoder = None

        if decoder is not None:
            for attempt in range(2):
                try:
                    res = decoder(gnews_url, interval=1)
                    ok = isinstance(res, dict) and str(res.get('status')).lower() in ('true', 'success')
                    decoded_url = res.get('decoded_url') if ok else None
                    if decoded_url and str(decoded_url).startswith('http'):
                        return str(decoded_url)
                    if isinstance(res, dict) and 'rate' in str(res.get('message', '')).lower():
                        time.sleep(2 + attempt)
                        continue
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                    log.debug("googlenewsdecoder failed for %s: %s", gnews_url[:60], e)

        # Legacy fallback: older links embed the target URL in base64.
        part = gnews_url.split("/articles/")[1].split("?")[0]
        # Pad with "=" to make length a multiple of 4
        padded = part + "=" * (-len(part) % 4)
        import base64
        import re
        
        # Robust URL safe conversion for both standard b64 and urlsafe b64
        cleaned = padded.replace('-', '+').replace('_', '/')
        try:
            decoded_bytes = base64.b64decode(cleaned)
        except Exception:
            decoded_bytes = base64.urlsafe_b64decode(padded)
            
        decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
        
        # Match only valid http/https URLs inside the decoded bytes
        match = re.search(r'https?://[a-zA-Z0-9.\-_~:/?#\[\]@!$&\'()*+,;=%]+', decoded_str)
        if match:
            return match.group(0)
    except Exception:
        pass
    return gnews_url


MIN_BODY_CHARS = 300   # below this a scrape is treated as "no body" (consent wall, paywall, block)


def _is_usable_candidate(cand, full_text=""):
    """Drops non-English articles (they used to leak foreign tokens into the
    cluster labels) — judged on title + snippet + body."""
    body = str(full_text or "")[:2000]
    if not looks_like_text(body):
        body = ""                       # a binary body says nothing about the language
    sample = " ".join(str(cand.get(k) or "") for k in ('title', 'snippet')) + " " + body
    return is_probably_english(sample)


def _assemble_row(topic, cand, full_text):
    """Builds one corpus row from a fetch candidate and its scraped body.

    Honest fallback: when the body could not be scraped the row keeps the
    feed snippet (or the headline) and is flagged Body_Available=False. The
    old versions appended a boilerplate sentence ("[Full report at direct
    source: news.google.com]") that leaked into clustering, labels and
    summaries. Publisher metadata from the feed is preserved so the TVS
    domain factor can count real outlets even when a redirect stays
    unresolved."""
    body_available = len(full_text or "") >= MIN_BODY_CHARS and looks_like_text(full_text)
    if body_available:
        text = full_text
    else:
        snippet = (cand.get('snippet') or "").strip()
        text = snippet if len(snippet) >= 50 and looks_like_text(snippet) else cand['title']

    url = cand['url']
    publisher_url = cand.get('publisher_url') or ""
    return {
        'Title': strip_publisher_suffix(cand['title'], cand.get('publisher')),
        'Text': text,
        'Topic_Source': topic,
        'Publish_Date': cand['date'],
        'URL': url,
        'Publisher': cand.get('publisher') or "",
        'Publisher_URL': publisher_url,
        'URL_Resolved': bool(publisher_domain(url)),
        'Body_Available': body_available,
    }


def _fetch_via_gnews(topic, max_articles):
    """
    FALLBACK SOURCE: Google News RSS search feed. Each <item> carries the
    redirect link, a description snippet and a <source url="…">Publisher</source>
    element; the redirect is resolved with _decode_gnews_url and the
    publisher metadata is kept for the domain-diversity factor.
    """
    results = []
    try:
        from datetime import datetime
        import urllib.parse
        encoded_topic = urllib.parse.quote_plus(topic)
        # Use US parameters to maximize retrieval index and avoid regional cookie filters
        feed_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-US&gl=US&ceid=US:en"

        response = _request_with_retry(feed_url, max_retries=3, timeout=10)
        if response is None or response.status_code != 200:
            return results

        soup = BeautifulSoup(response.content, 'xml') or BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item')
        if not items:
            return results

        # Phase 1: parse RSS metadata and resolve redirect URLs
        candidates = []
        for item in items:
            if len(candidates) >= max_articles:
                break

            try:
                title = item.title.text if item.title else "No Title"
                encoded_gnews_url = item.link.text if item.link else ""
                if not encoded_gnews_url:
                    continue

                pub_date_str = item.pubDate.text if item.pubDate else ""
                clean_date_str = datetime.now().strftime('%Y-%m-%d')
                if pub_date_str:
                    try:
                        dt_object = dateutil_parser.parse(pub_date_str)
                        if dt_object.year < 2024:
                            continue
                        clean_date_str = dt_object.strftime('%Y-%m-%d')
                    except Exception:
                        pass

                source_node = item.find('source')
                publisher = source_node.get_text(strip=True) if source_node else ""
                publisher_url = (source_node.get('url') or "") if source_node else ""

                direct_url = _decode_gnews_url(encoded_gnews_url)

                snippet = ""
                desc_node = item.find('description')
                if desc_node:
                    desc_soup = BeautifulSoup(desc_node.text, 'html.parser')
                    snippet = desc_soup.get_text(separator=' ').strip()
                    # the description repeats "<title>  Publisher" — not a real snippet
                    if snippet.replace(publisher, "").strip().rstrip("-–|").strip() == title.strip():
                        snippet = ""

                candidates.append({
                    'title': title,
                    'url': direct_url,
                    'date': clean_date_str,
                    'snippet': snippet,
                    'publisher': publisher,
                    'publisher_url': publisher_url,
                })
            except Exception:
                continue

        # Phase 2: fetch article bodies concurrently (parallel across domains);
        # unresolved redirects would only hit the consent wall, skip them.
        bodies = _scrape_bodies_concurrent([c['url'] if publisher_domain(c['url']) else "" for c in candidates])

        # Phase 3: assemble rows (snippet fallback, flagged — never boilerplate)
        for cand, full_text in zip(candidates, bodies):
            if len(results) >= max_articles:
                break
            if not _is_usable_candidate(cand, full_text):
                continue
            results.append(_assemble_row(topic, cand, full_text))

    except Exception as e:
        print(f"  [GNews RSS] Direct fetch error for '{topic}': {e}")

    return results


def _fetch_via_yahoo(topic, max_articles):
    """
    TERTIARY FALLBACK: Fetches news articles from Yahoo News Search.
    Extremely reliable, does not require API keys, cookies, or JavaScript.
    Bypasses DuckDuckGo rate limits and Google's GDPR consent barriers.
    """
    results = []
    try:
        from datetime import datetime
        import urllib.parse
        encoded_query = urllib.parse.quote_plus(topic)
        url = f"https://news.search.yahoo.com/search?p={encoded_query}"
        
        response = _request_with_retry(url, max_retries=3, timeout=12)
        if response is None or response.status_code != 200:
            return results
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Yahoo News Search results are typically h4 / h3 tags inside result divs
        links = soup.select('h4.fz-16 a, h3.title a, h4.fz-16.lh-20 a, div.compTitle h3 a') or soup.find_all('a')
        
        seen_urls = set()
        candidates = []
        for link in links:
            if len(candidates) >= max_articles:
                break
            article_url = link.get('href', '')
            title_text = link.get_text(strip=True)
            if not article_url or not title_text or len(title_text) < 12:
                continue

            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            # Evita pagini interne Yahoo
            if "news.search.yahoo.com" in article_url or "google.com" in article_url or "yahoo.com/style" in article_url:
                continue
            if "r.search.yahoo.com" not in article_url and "http" not in article_url:
                continue

            candidates.append({
                'title': title_text, 'url': article_url,
                'date': datetime.now().strftime('%Y-%m-%d'), 'snippet': "",
            })

        # Fetch article bodies concurrently (parallel across domains)
        bodies = _scrape_bodies_concurrent([c['url'] for c in candidates], timeout=12)

        for cand, full_text in zip(candidates, bodies):
            if len(results) >= max_articles:
                break
            if not _is_usable_candidate(cand, full_text):
                continue
            results.append(_assemble_row(topic, cand, full_text))
    except Exception as e:
        print(f"  [Yahoo] Error for '{topic}': {e}")
        
    return results


def _fetch_via_duckduckgo(topic, max_articles):
    """
    PRIMARY SOURCE: Fetches news articles from DuckDuckGo Search API
    via the open-source `duckduckgo_search` library. DDG provides
    direct publisher URLs (bypasses Google consent/cookie walls).

    To prevent DDG from rate-limiting (403 Forbidden blocks), we:
      1. Fetch max_results equal strictly to max_articles. By keeping it <= 30,
         we prevent the library from pagination and hitting secondary pages (s=30) which immediately flags IPs.
      2. Inject a polite, randomized delay before calling DDG.
      3. Support both context managers and traditional library constructor signatures.
    """
    results = []
    raw_results = None

    # Step 1: Polite initial delay between topics to evade rate limiting
    time.sleep(random.uniform(2.0, 4.0))

    # --- DDG API call with retry on rate limits ---
    for attempt in range(3):
        try:
            # Try via modern context manager first (recommended)
            try:
                from duckduckgo_search import DDGS
                with DDGS(timeout=20) as ddgs:
                    raw_results = list(ddgs.news(topic, max_results=max_articles))
            except Exception:
                try:
                    with DDGS() as ddgs:
                        raw_results = list(ddgs.news(topic, max_results=max_articles))
                except Exception:
                    # Traditional fallback if context manager is unsupported (older versions)
                    try:
                        ddgs = DDGS(timeout=20)
                    except Exception:
                        ddgs = DDGS()
                    
                    try:
                        raw_results = ddgs.news(keywords=topic, max_results=max_articles)
                    except Exception:
                        try:
                            raw_results = ddgs.news(topic, max_results=max_articles)
                        except Exception:
                            raw_results = ddgs.news(topic)
            break  # Success — exit retry loop

        except Exception as e:
            err_msg = str(e).lower()
            if any(term in err_msg for term in ['ratelimit', '429', 'too many', '403', 'forbidden', 'timeout']):
                wait = 6 * (2 ** attempt) + random.uniform(1, 3)  # exponential backoff with jitter
                print(f"  [DDG] Rate limited on '{topic}', retrying in {wait:.1f}s... (attempt {attempt + 1}/3)")
                time.sleep(wait)
            else:
                print(f"  [DDG] Error or block for '{topic}': {e}. Moving to next source or topic.")
                if attempt == 2:
                    return results

    if not raw_results:
        print(f"  [DDG] Topic '{topic}' deferred to alternative stream.")
        return results

    # Phase 1: parse/validate metadata for all candidates (cheap, local)
    candidates = []
    for item in raw_results:
        if len(candidates) >= max_articles:
            break
        try:
            # --- Parse and validate the publish date ---
            date_str = item.get('date', '')
            if not date_str:
                continue
            dt_object = dateutil_parser.parse(date_str)
            if dt_object.year < 2024:
                continue
            clean_date_str = dt_object.strftime('%Y-%m-%d')

            # --- Extract the article URL ---
            article_url = item.get('url', '')
            if not article_url:
                continue

            candidates.append({
                'title': item.get('title', 'No Title'),
                'url': article_url,
                'date': clean_date_str,
                'snippet': item.get('body', '') or item.get('snippet', ''),
                'publisher': item.get('source', '') or "",
                'publisher_url': article_url,
            })
        except Exception:
            continue

    # Phase 2: fetch article bodies concurrently (parallel across domains)
    bodies = _scrape_bodies_concurrent([c['url'] for c in candidates])

    # Phase 3: assemble rows; a failed scrape keeps the DDG snippet, flagged
    # Body_Available=False, and rows without even a snippet are dropped.
    for cand, full_text in zip(candidates, bodies):
        if len(results) >= max_articles:
            break
        if len(full_text) < MIN_BODY_CHARS and len(cand['snippet']) < 50:
            continue
        if not _is_usable_candidate(cand, full_text):
            continue
        results.append(_assemble_row(topic, cand, full_text))

    return results


# ------------------------------------------------------------------
# [IMPROVEMENT #1] Semantic Deduplication via SBERT
# Exact title dedup misses articles covering the same story with
# different headlines (e.g., "Fed Raises Rates by 0.25%" vs.
# "Federal Reserve Hikes Rates a Quarter Point"). This function
# encodes all titles into the shared SBERT vector space and drops
# articles whose titles have cosine similarity > threshold,
# keeping the one with the longer (richer) article body.
# ------------------------------------------------------------------
def _semantic_dedup(df, threshold=0.85):
    """
    Removes near-duplicate articles based on semantic title similarity.

    Algorithm:
      1. Encode all Title values with the shared SBERT model.
      2. Compute pairwise cosine similarity matrix across all titles.
      3. For each pair with similarity > threshold:
         - Mark the article with the SHORTER Text for removal.
         - Keep the article with the longer, richer body.
      4. Return the filtered DataFrame.

    Parameters:
      df        : DataFrame with 'Title' and 'Text' columns
      threshold : float, similarity cutoff (default 0.85)

    Returns:
      DataFrame with near-duplicates removed.
    """
    if len(df) < 2:
        return df

    from sklearn.metrics.pairwise import cosine_similarity

    titles = df['Title'].astype(str).tolist()
    title_embeddings = encode_texts_cached(titles)

    # Compute full pairwise similarity matrix (N x N)
    sim_matrix = cosine_similarity(title_embeddings)

    # Identify indices to drop (keep longer article in each duplicate pair).
    # Candidate pairs above the threshold are extracted in one vectorized
    # pass; np.where returns them in the same (i asc, j asc) order as the
    # old nested loop, so resolution semantics are unchanged.
    text_lengths = df['Text'].str.len().tolist()
    indices_to_drop = set()

    cand_i, cand_j = np.where(np.triu(sim_matrix, k=1) > threshold)
    for i, j in zip(cand_i.tolist(), cand_j.tolist()):
        if i in indices_to_drop or j in indices_to_drop:
            continue
        # Drop the article with the shorter text
        if text_lengths[i] >= text_lengths[j]:
            indices_to_drop.add(j)
        else:
            indices_to_drop.add(i)

    n_removed = len(indices_to_drop)
    if n_removed > 0:
        df = df.drop(df.index[list(indices_to_drop)]).reset_index(drop=True)
        print(f"  🧹 Semantic dedup removed {n_removed} near-duplicate articles.")

    return df


# Note: _generate_synthetic_corpus helper was removed entirely to meet strict real-data-only requirements for the dissertation.


def _out(filename):
    """Path of an artefact inside OUTPUT_DIR (set by the CLI, defaults to the repo root)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return os.path.join(OUTPUT_DIR, filename)


def fetch_topic(topic, max_articles):
    """Three-tier ingestion for one topic: DuckDuckGo -> Google News RSS -> Yahoo News."""
    articles = _fetch_via_duckduckgo(topic, max_articles)
    if len(articles) == 0:
        print(f"  ↳ [Resolver] Querying Google News RSS stream for '{topic}'...")
        articles = _fetch_via_gnews(topic, max_articles)
    if len(articles) == 0:
        print(f"  ↳ [Resolver] Querying Yahoo News Search index for '{topic}'...")
        articles = _fetch_via_yahoo(topic, max_articles)
    return articles


def report_corpus_quality(df, label="corpus"):
    """Prints the corpus quality report and returns it (also exported to JSON)."""
    report = corpus_quality_report(df)
    log.info(
        "%s quality: %d documents | resolved publisher domain %.0f%% | body available %.0f%% | "
        "median body %d chars | %d distinct domains",
        label, report["documents"], 100 * report["resolvedDomainShare"],
        100 * report["bodyAvailableShare"], report["medianBodyChars"], report["nDomains"],
    )
    for warning in quality_warnings(report):
        log.warning("%s", warning)
    return report


def step_1_scrape(topics=None, max_articles=None):
    """
    DATA INGESTION: Three-tier open-source scraping pipeline.
      - Primary:  DuckDuckGo Search (direct publisher URLs, no cookie walls)
      - Fallback: Google News RSS (redirects resolved, publisher kept)
      - Tertiary: Yahoo News Search
      - Full text: Trafilatura (primary) + BeautifulSoup (fallback)
      - Dedup:    Exact title match + SBERT semantic deduplication

    Output: DataFrame with columns [Title, Text, Topic_Source, Publish_Date, URL,
            Publisher, Publisher_URL, URL_Resolved, Body_Available]
    """
    topics = list(topics or TOPICS)
    max_articles = max_articles or MAX_ARTICLES_PER_TOPIC
    checkpoint_path = _out(FILENAME_CHECKPOINT)
    print(f"🔵 [1/5] Initiating Data Ingestion Protocol (Open-Source Mode) — {len(topics)} topics, "
          f"≤{max_articles} articles each...")

    # --- Checkpoint resume logic ---
    if os.path.exists(checkpoint_path):
        print("⚠️ Checkpoint found! Resuming from last saved state...")
        try:
            current_df = pd.read_csv(checkpoint_path)
            existing_topics = current_df['Topic_Source'].unique().tolist()
            news_list = current_df.to_dict('records')
        except Exception:
            news_list = []
            existing_topics = []
    else:
        news_list = []
        existing_topics = []

    for topic in tqdm(topics, desc="Harvesting News (Open-Source)"):
        if topic in existing_topics:
            continue

        articles = fetch_topic(topic, max_articles)
        news_list.extend(articles)
        resolved = sum(1 for a in articles if a.get('URL_Resolved'))
        bodies = sum(1 for a in articles if a.get('Body_Available'))
        print(f"  ✓ '{topic}': {len(articles)} articles ingested "
              f"({resolved} resolved publishers, {bodies} full bodies).")

        # --- Save checkpoint after each topic (crash resilience) ---
        # Append-only: writing just the new topic's rows avoids rewriting
        # the whole corpus after every topic (O(N^2) I/O across a run).
        try:
            if articles:
                pd.DataFrame(articles).to_csv(
                    checkpoint_path, mode='a', index=False,
                    header=not os.path.exists(checkpoint_path)
                )
        except Exception:
            pass

        gc.collect()

    # --- Build final DataFrame ---
    df = pd.DataFrame(news_list)

    if df.empty or len(df) == 0:
        print("\n" + "!" * 80)
        print("❌ [CRITICAL ERROR] Scraping blocked. 0 articles fetched from all search engines.")
        print("🚨 Please configure a VPN, change your IP address, or check your internet connection and try again.")
        print("!" * 80 + "\n")
        sys.exit("Scraping blocked. Please use a VPN.")

    # Stage 1: Exact title dedup (fast, catches identical headlines)
    before_exact = len(df)
    df = df.drop_duplicates(subset=['Title'])
    n_exact = before_exact - len(df)
    if n_exact > 0:
        print(f"  🧹 Exact dedup removed {n_exact} duplicate titles.")

    # Stage 2: Semantic dedup (catches same-story / different-headline)
    df = _semantic_dedup(df, threshold=0.85)

    print(f"✅ Ingestion Complete. Corpus Size: {len(df)} documents.")
    report_corpus_quality(df, label="Ingested corpus")
    return df


# ==========================================
# 2. NLP ENRICHMENT
# ==========================================
# ------------------------------------------------------------------
# [IMPROVEMENT #2] Batch NLP Processing
# HuggingFace pipelines natively support batch inference. Instead of
# calling sentiment_pipe(text) once per article in a loop, we pass
# ALL texts at once with batch_size=16. This amortizes the model
# overhead and provides ~3-5x speedup on CPU, more on GPU.
# KeyBERT is kept as-is (it already vectorizes internally).
# ------------------------------------------------------------------
def step_2_nlp_processing(df):
    print("\n⏳ Initializing NLP Modules...")
    from keybert import KeyBERT
    from transformers import pipeline

    print("🔵 [2/5] Executing Semantic Enrichment...")

    # Pass the shared SBERT model to KeyBERT to save RAM
    kw_model = KeyBERT(model=get_embedding_model())

    sentiment_pipe = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english", device=-1)
    ner_pipe = pipeline("ner", model="dslim/bert-base-NER", aggregation_strategy="simple", device=-1)

    # --- Prepare all short texts for batched inference ---
    all_short_texts = [text[:512] for text in df['Text']]

    # ==========================================
    # 1. Keywords (KeyBERT - stays per-article; already vectorized internally)
    # ==========================================
    kws_list = []
    try:
        # Batched extraction: one call over the whole corpus amortizes the
        # candidate-embedding overhead instead of paying it per article.
        batch_kws = kw_model.extract_keywords(
            [str(t) for t in df['Text']],
            keyphrase_ngram_range=(1, 2), stop_words='english', top_n=5
        )
        if batch_kws and isinstance(batch_kws[0], tuple):
            batch_kws = [batch_kws]  # single-doc call returns a flat list
        kws_list = [", ".join(k[0] for k in doc_kws) for doc_kws in batch_kws]
        if len(kws_list) != len(df):
            raise ValueError("KeyBERT batch length mismatch")
    except Exception:
        # Fallback: per-article loop for older KeyBERT versions
        kws_list = []
        for text in tqdm(df['Text'], desc="Extracting Keywords"):
            try:
                kws = kw_model.extract_keywords(text, keyphrase_ngram_range=(1, 2), stop_words='english', top_n=5)
                kws_list.append(", ".join([k[0] for k in kws]))
            except Exception:
                kws_list.append("")

    # ==========================================
    # 2. Sentiment (BATCHED - ~3-5x faster than per-article loop)
    # ==========================================
    print("  ⚡ Running batched sentiment analysis...")
    sent_labels = []
    sent_scores = []
    sent_values = []
    try:
        batch_results = sentiment_pipe(all_short_texts, batch_size=16, truncation=True)
        for res in batch_results:
            label = res['label']
            score = round(res['score'], 4)
            directional_score = score if label == "POSITIVE" else -score
            sent_labels.append(label)
            sent_scores.append(score)
            sent_values.append(directional_score)
    except Exception:
        # Fallback: if batched fails (e.g., OOM), process one-by-one.
        # Reset accumulators first — a mid-batch failure may have left
        # partial appends that would desynchronize column lengths.
        print("  ⚠️ Batch sentiment failed, falling back to sequential...")
        sent_labels, sent_scores, sent_values = [], [], []
        for short_text in tqdm(all_short_texts, desc="Sentiment (sequential)"):
            try:
                res = sentiment_pipe(short_text)[0]
                label = res['label']
                score = round(res['score'], 4)
                directional_score = score if label == "POSITIVE" else -score
                sent_labels.append(label)
                sent_scores.append(score)
                sent_values.append(directional_score)
            except Exception:
                sent_labels.append("NEUTRAL")
                sent_scores.append(0.0)
                sent_values.append(0.0)

    # ==========================================
    # 3. NER (BATCHED - ~3-5x faster than per-article loop)
    # ==========================================
    print("  ⚡ Running batched NER extraction...")
    locs_list = []
    try:
        batch_ner_results = ner_pipe(all_short_texts, batch_size=16)
        for ents in batch_ner_results:
            locs = {ent['word'] for ent in ents if ent['entity_group'] == 'LOC'}
            locs_list.append(", ".join(locs))
    except Exception:
        # Fallback: if batched fails, process one-by-one (reset first to
        # avoid partial-append desynchronization)
        print("  ⚠️ Batch NER failed, falling back to sequential...")
        locs_list = []
        for short_text in tqdm(all_short_texts, desc="NER (sequential)"):
            try:
                ents = ner_pipe(short_text)
                locs = {ent['word'] for ent in ents if ent['entity_group'] == 'LOC'}
                locs_list.append(", ".join(locs))
            except Exception:
                locs_list.append("")

    df['KeyBERT'] = kws_list
    df['Sentiment'] = sent_labels
    df['Sentiment_Score'] = sent_scores
    df['Sentiment_Value'] = sent_values
    df['NER_Location'] = locs_list

    del kw_model, sentiment_pipe, ner_pipe
    gc.collect()
    return df


# ==========================================
# 3. DYNAMIC TOPIC MODELING
# ==========================================
# [IMPROVEMENT #2c] Accept optional min_date / max_date to constrain
# the Plotly x-axis to the actual data range (no empty years).
def _write_viz_html(fig, filename):
    """Writes a Plotly figure to OUTPUT_DIR and to the dashboard's public dir.

    plotly.js is referenced from the CDN instead of being embedded, which
    turns each 4.8 MB file into ~100 KB (the dashboard loads them in iframes)."""
    written = []
    for directory in {OUTPUT_DIR, resolve_public_dir()}:
        dest_path = os.path.join(directory, filename)
        try:
            fig.write_html(dest_path, include_plotlyjs="cdn", full_html=True)
            written.append(dest_path)
        except Exception as e:
            print(f"  ⚠️ Failed to write visualization to {dest_path}: {e}")
    for dest_path in written:
        print(f"  ✅ Visualization saved to: '{dest_path}'")
    return written


def generate_dissertation_plot(topic_model, topics_over_time, min_date=None, max_date=None):
    import plotly.graph_objects as go

    print("📊 Generating Corrected Dissertation Visualization...")
    fig = go.Figure()

    topic_info = topic_model.get_topic_info()
    top_topics = topic_info[topic_info['Topic'] != -1].head(10)['Topic'].tolist()

    for topic_id in top_topics:
        topic_data = topics_over_time[topics_over_time['Topic'] == topic_id]
        if topic_data.empty: continue

        full_name = topic_info[topic_info['Topic'] == topic_id]['Name'].values[0]

        fig.add_trace(go.Scatter(
            x=topic_data['Timestamp'],
            y=topic_data['Frequency'],
            mode='lines+markers',
            name=full_name,
            marker=dict(size=8),
            line=dict(width=3)
        ))

    # [FIX] Dynamic axis title based on actual scraped data range
    if min_date is not None and max_date is not None:
        date_label = f"Timeline ({min_date.strftime('%b %Y')} – {max_date.strftime('%b %Y')})"
    else:
        date_label = "Timeline"

    fig.update_layout(
        title="<b>VeriNews Topology: Macro-Trends (Lines) vs. Flash Events (Dots)</b>",
        xaxis_title=date_label,
        yaxis_title="Article Frequency (Density)",
        template="plotly_white",
        legend=dict(title="Semantic Clusters"),
        hovermode="x unified"
    )

    # [FIX] Constrain x-axis to actual data span (no empty 2024 flatlines)
    if min_date is not None and max_date is not None:
        fig.update_xaxes(range=[min_date - pd.Timedelta(days=7),
                                max_date + pd.Timedelta(days=7)])

    _write_viz_html(fig, FILENAME_VIZ_HTML)


def step_3_dynamic_topics(df):
    """
    DYNAMIC TOPIC MODELING: Safely uses an optimized Scikit-Learn KMeans + 
    SBERT sentence embeddings + Class-based TF-IDF topic modeling engine.
    This guarantees JIT-free execution, zero native LLVM/Numba memory crashes,
    and ultra-precise clustering for cross-platform dissertation stability.
    """
    print("\n⏳ Initializing Hybrid SBERT + KMeans Topic Model...")
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.decomposition import TruncatedSVD
    import plotly.express as px

    print("🔵 [3/5] Computing Dynamic Topic Model via JIT-Safe Fallback...")

    # Use Clustering_Text for all clustering operations
    df['Clustering_Text'] = df['Title'].astype(str) + ". " + df['Text'].astype(str).str[:1200]
    docs = df['Clustering_Text'].tolist()

    # 1. ENCODE DOCUMENTS VIA SBERT
    print(f"  ⚡ Embedding documents using the shared SBERT model ({EMBEDDING_MODEL_NAME})...")
    embeddings = encode_texts_cached(docs)
    
    # 2. DETERMINISTIC K-MEANS CLUSTERING
    # Adaptively calculate the optimal cluster counts based on corpus size
    n_docs = len(docs)
    n_clusters = max(4, min(10, n_docs // 6)) if n_docs >= 10 else max(1, n_docs)
    print(f"  ⚡ Running KMeans Clustering (k={n_clusters})...")
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init='auto')
    topics = kmeans.fit_predict(embeddings)
    
    # 3. CLASS-BASED TF-IDF KEYWORD EXTRACTOR
    print("  ⚡ Extracting class-based TF-IDF terms per semantic cluster...")
    class_docs = []
    for c in range(n_clusters):
        c_docs = [docs[i] for i, label in enumerate(topics) if label == c]
        class_docs.append(" ".join(c_docs) if c_docs else "empty cluster")
        
    # Stop words: English + web/feed boilerplate + outlet names + the
    # publishers present in this corpus, so labels describe the story and
    # not the scraping path (no more "com_source google_report direct").
    corpus_domains = {
        publisher_domain(u, p)
        for u, p in zip(df['URL'].astype(str), df.get('Publisher_URL', pd.Series([None] * len(df))))
    }
    combined_stop_words = build_stop_words(d for d in corpus_domains if d)

    vectorizer = CountVectorizer(stop_words=combined_stop_words, min_df=1, ngram_range=(1, 2))
    try:
        X = vectorizer.fit_transform(class_docs)
        words = vectorizer.get_feature_names_out()
        tf = X.toarray()
        
        # DF: class document frequency representation
        df_classes = np.asarray(np.sum(X > 0, axis=0)).squeeze()
        avg_words = float(np.mean(np.sum(X, axis=1)))
        
        # Custom Class-based TF-IDF formula
        ctfidf = tf * np.log(1 + avg_words / (df_classes + 1e-5))
    except Exception as e:
        print(f"  ⚠️ Vectorizer had issue: {e}. Using fallback topic names...")
        ctfidf = np.eye(n_clusters)
        words = np.array([f"Topic_{i}" for i in range(n_clusters)])
        
    # Build topic information dataframe matching exact BERTopic format
    topic_map = {}
    topic_info_records = []
    
    for c in range(n_clusters):
        ranked_terms = []
        if ctfidf.shape[1] > 0:
            # rank a few more candidates than needed; select_label_terms drops
            # terms whose words are already covered (e.g. 'trump' + 'trump administration')
            top_word_indices = np.argsort(ctfidf[c])[-12:][::-1]
            ranked_terms = [str(words[idx]) for idx in top_word_indices if idx < len(words) and ctfidf[c][idx] > 0]

        full_name = build_topic_label(c, ranked_terms, n=4)
        topic_map[c] = full_name
        
        count = sum(1 for t in topics if t == c)
        topic_info_records.append({
            "Topic": c,
            "Name": full_name,
            "Count": count
        })
        
    # Append a mock outlier row for format matching
    topic_info_records.append({
        "Topic": -1,
        "Name": "-1_outliers",
        "Count": 0
    })
    
    info_df = pd.DataFrame(topic_info_records)
    df['Topic_ID'] = topics
    df['Topic_Name'] = df['Topic_ID'].map(topic_map)
    
    # 4. COMPUTE TOPICS OVER TIME METRICS FOR LINE CHART
    print("  ⚡ Computing dynamic topics over time frequency matrix...")
    date_series = pd.to_datetime(df['Publish_Date'], errors='coerce')
    min_date = date_series.min() if pd.notna(date_series.min()) else pd.Timestamp('2026-05-22')
    max_date = date_series.max() if pd.notna(date_series.max()) else pd.Timestamp('2026-05-22')
    if min_date == max_date:
        # Degenerate single-day corpus: widen the window so bin edges are
        # strictly increasing (pd.cut requires monotonic bins).
        max_date = max_date + pd.Timedelta(days=1)
    date_span_days = (max_date - min_date).days
    adaptive_bins = max(6, min(20, date_span_days // 7)) if date_span_days > 7 else 6

    bin_edges = pd.date_range(start=min_date, end=max_date, periods=adaptive_bins + 1)

    # Vectorized frequency matrix. pd.cut assigns each article to exactly
    # one bin (the old >=start & <=end slicing double-counted articles
    # landing precisely on a shared bin edge).
    bin_assign = pd.cut(date_series, bins=bin_edges, labels=False, include_lowest=True)
    freq_frame = pd.DataFrame({'bin': bin_assign, 'Topic': df['Topic_ID'].values}).dropna(subset=['bin'])
    freq_frame['bin'] = freq_frame['bin'].astype(int)
    freq_counts = freq_frame.groupby(['bin', 'Topic']).size()

    tot_records = []
    for b in range(adaptive_bins):
        start_b = bin_edges[b]
        end_b = bin_edges[b + 1]
        for c in range(n_clusters):
            tot_records.append({
                "Topic": c,
                "Frequency": int(freq_counts.get((b, c), 0)),
                "Timestamp": start_b + (end_b - start_b) / 2
            })

    topics_over_time = pd.DataFrame(tot_records)
    
    print("\n--- Top Semantic Clusters Identified (JIT-Safe Mode) ---")
    print(info_df[['Topic', 'Name', 'Count']].head(10))
    
    # 5. GENERATE GRAPHICAL VISUALIZATIONS
    class MockTopicModel:
        def __init__(self, info_df):
            self.info_df = info_df
        def get_topic_info(self):
            return self.info_df
            
    mock_model = MockTopicModel(info_df)
    generate_dissertation_plot(mock_model, topics_over_time, min_date, max_date)
    
    # Render clusters scatter plot matching dashboard slate style
    print("  ⚡ Rendering 2D cluster SVD projection plot...")
    pca = TruncatedSVD(n_components=2, random_state=42)
    embeddings_2d = pca.fit_transform(embeddings) if len(embeddings) >= 2 else np.zeros((len(embeddings), 2))
    
    scatter_df = pd.DataFrame({
        'x': embeddings_2d[:, 0] if len(embeddings) >= 2 else [0]*len(embeddings),
        'y': embeddings_2d[:, 1] if len(embeddings) >= 2 else [0]*len(embeddings),
        'Topic': df['Topic_Name'],
        'Title': df['Title']
    })
    
    fig_scatter = px.scatter(
        scatter_df, x='x', y='y', color='Topic', hover_data=['Title'],
        title="<b>VeriNews Semantic Topology (2D Embedding Space Projection)</b>",
        template="plotly_dark",
        labels={"x": "SVD Dimension 1", "y": "SVD Dimension 2"}
    )
    
    fig_scatter.update_layout(
        paper_bgcolor='rgba(13,18,29,1)',
        plot_bgcolor='rgba(13,18,29,1)',
        font=dict(color='#A5B4FC'),
        title_font=dict(color='#F8FAFC', size=16),
        legend=dict(font=dict(color='#818CF8'))
    )
    _write_viz_html(fig_scatter, FILENAME_VIZ_SCATTER)

    return df


# ==========================================
# 4. GENERATIVE AI & VERIFICATION (UPGRADED)
# ==========================================
def _extract_domain(url):
    """
    Extracts a clean root domain from a full URL for diversity counting.
    Examples:
        'https://www.reuters.com/world/...' -> 'reuters.com'
        'https://news.bbc.co.uk/sport/...'  -> 'bbc.co.uk'
        'https://edition.cnn.com/2026/...'  -> 'cnn.com'
    """
    return registrable_domain(url)


def _domains_for_frame(topic_df):
    """Publisher domains of a cluster, one entry per row ('' when unknown).

    Uses the feed-announced publisher URL, then the publisher *name*, when the
    article link is an aggregator redirect or a syndicated copy (msn.com), so
    an unresolved Google News link never counts as the single source
    'news.google.com' and a CBS story syndicated on MSN still counts as CBS."""
    urls = topic_df['URL'].astype(str).tolist() if 'URL' in topic_df.columns else []
    publisher_urls = topic_df['Publisher_URL'].tolist() if 'Publisher_URL' in topic_df.columns else [None] * len(urls)
    publishers = topic_df['Publisher'].tolist() if 'Publisher' in topic_df.columns else [None] * len(urls)
    return [
        source_identity(u, p if isinstance(p, str) else None, name if isinstance(name, str) else None)
        for u, p, name in zip(urls, publisher_urls, publishers)
    ]


def extract_evidence(summary_text, topic_df):
    """Embeds a cluster once and returns the raw evidence the TVS needs.

    Returns (similarities, pairwise_matrix, domains):
      similarities    cos(summary, source_i) for every source
      pairwise_matrix full source x source cosine matrix (None for <2 sources)
      domains         one source identity per row ('' when unidentifiable)

    Separating extraction from scoring lets the parameter study re-score the
    same clusters under different constants without touching the model."""
    from sklearn.metrics.pairwise import cosine_similarity

    source_texts = [str(t) for t in topic_df['Text'].tolist()]
    source_embeddings = encode_texts_cached(source_texts)
    summary_embedding = encode_texts_cached([str(summary_text)])

    similarities = cosine_similarity(summary_embedding, source_embeddings)[0]
    pairwise = cosine_similarity(source_embeddings, source_embeddings) if len(source_embeddings) >= 2 else None
    return similarities, pairwise, _domains_for_frame(topic_df)


def extract_claim_evidence(summary_text, topic_df):
    """Per-claim version of `extract_evidence`, used by the baseline study.

    Splits the summary into individual claim sentences and returns
    (claims, matrix) where matrix[i][j] = cos(claim_i, source_j). This is the
    evidence a claim-level verifier needs: whether *each* assertion in a
    briefing is independently backed, rather than whether the briefing as a
    whole resembles its sources. Frozen alongside the rest of the bundle so
    the comparison stays pure arithmetic."""
    from sklearn.metrics.pairwise import cosine_similarity

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', str(summary_text)) if s.strip()]
    claims = [s for s in sentences if is_informative_sentence(s)] or sentences
    if not claims:
        return [], None

    source_texts = [str(t) for t in topic_df['Text'].tolist()]
    if not source_texts:
        return claims, None
    matrix = cosine_similarity(encode_texts_cached(claims), encode_texts_cached(source_texts))
    return claims, matrix


def calculate_veracity_score_semantic(summary_text, topic_df, return_details=False, params=None):
    """
    =====================================================================
    TRIANGULATED VERACITY SCORE  (v3.1 - Dissertation Methodology)
    =====================================================================

    This function computes a Veracity Score (0-99) that measures how
    trustworthy a generated summary is, based on THREE independent factors.

    [UPGRADE v3.1] Now returns a full breakdown dict instead of a bare int,
    enabling the stress-test function to inspect each factor individually.

    FACTOR 1: Semantic Fidelity (SBERT Cosine Similarity)
    -----------------------------------------------------
    Measures whether the AI-generated summary is semantically aligned
    with the original source texts. Uses the shared SBERT model
    (all-mpnet-base-v2) to encode both the summary and each source
    document into 768-dimensional dense vectors, then computes cosine
    similarity between them.

    Formula:
        similarities[i] = cos(embed(summary), embed(source_i))
        avg_sim = mean(top-3 similarities)
        semantic_score = 30 + (avg_sim * 70)
        # Range: ~30 (no match) to ~100 (perfect alignment)

    We take the top-3 matches (not all) because a topic cluster may
    contain tangentially related articles. The top-3 approach focuses
    on the articles most relevant to the summary.

    FACTOR 2: Domain Diversity (Source Consensus)
    ----------------------------------------------
    Measures whether the information is corroborated across multiple
    independent news domains. A story confirmed by Reuters, BBC, AND
    Bloomberg is more trustworthy than one reported by a single outlet.

    We extract unique root domains from the URL column using urlparse,
    then apply a diversity multiplier:

        n_unique_domains >= 5  ->  factor = 1.00  (strong consensus)
        n_unique_domains == 4  ->  factor = 0.95  (good consensus)
        n_unique_domains == 3  ->  factor = 0.85  (moderate consensus)
        n_unique_domains == 2  ->  factor = 0.72  (weak - capped ~72)
        n_unique_domains == 1  ->  factor = 0.60  (single source - capped ~60)

    FACTOR 3: Source Coherence (Inter-Source Agreement)
    -----------------------------------------------------------------
    Measures whether the source texts AGREE WITH EACH OTHER, not just
    with the summary. If 5 different domains all report contradictory
    information, domain diversity alone would give a false sense of
    confidence. Source coherence corrects this.

    We compute pairwise cosine similarities among ALL source embeddings,
    extract the upper triangle of the similarity matrix (excluding the
    diagonal of self-similarity = 1.0), and take the mean:

        pairwise_sims = cosine_similarity(source_embeddings, source_embeddings)
        upper_triangle = pairwise_sims[triu_indices(n, k=1)]
        source_coherence = mean(upper_triangle)   # range: 0.0 - 1.0

    This is mapped to a multiplier via:
        coherence_factor = 0.70 + (source_coherence * 0.30)
        # Range: 0.70 (sources contradict) to 1.00 (sources fully agree)

    FINAL FORMULA:
        veracity = int(semantic_score * domain_factor * coherence_factor)
        # Capped at 99, floored at 5

    This THREE-FACTOR model ensures:
      - High score (80-100) requires semantic match + multi-domain + agreement
      - Single-source claims cap at ~60 regardless of similarity
      - Contradictory multi-source clusters are penalized even with 5+ domains

    Returns:
        dict with keys: final_score, semantic_score, avg_similarity,
                        domain_factor, n_domains, coherence_factor,
                        source_coherence
    =====================================================================
    """
    # [UPGRADE v3.1] Neutral fallback as a dict (was: bare int 50)
    _neutral = {
        'final_score': 50, 'semantic_score': 50.0, 'avg_similarity': 0.0,
        'domain_factor': 1.0, 'n_domains': 0, 'domains': [],
        'coherence_factor': 0.85, 'source_coherence': 0.5,
        'similarities': [], 'pairwise_matrix': None
    }

    if len(topic_df) < 1:
        return _neutral  # Insufficient data -> neutral score

    try:
        # -------------------------------------------------------------
        # 1. Extract the evidence (this is the only part that needs the
        #    embedding model): summary-to-source similarities, the pairwise
        #    source matrix, and the identity of every source.
        # -------------------------------------------------------------
        similarities, pairwise_sims, domains = extract_evidence(summary_text, topic_df)

        # -------------------------------------------------------------
        # 2. Apply the formula. The maths lives in verinews_common so the
        #    parameter study can re-score the same evidence under different
        #    constants without re-embedding anything.
        # -------------------------------------------------------------
        result = tvs_from_evidence(
            similarities, domains, upper_triangle(pairwise_sims), params or DEFAULT_TVS_PARAMS
        )
        result.pop('flagged', None)   # kept out of the pipeline payload (v3.1 shape)

        if return_details:
            # [v4.0] Per-article evidence consumed by the JSON export so
            # the dashboard renders the REAL computed values, not placeholders.
            result['similarities'] = [round(float(s), 4) for s in similarities]
            result['pairwise_matrix'] = (
                [[round(float(v), 4) for v in row] for row in pairwise_sims]
                if pairwise_sims is not None else None
            )
        return result

    except Exception as error:
        # Returning a neutral score keeps one bad cluster from killing a batch,
        # but a silent 50 is indistinguishable from a real 50, and that is how
        # an stdout encoding fault once degraded an entire run unnoticed. The
        # fallback therefore stays, and the reason is always reported.
        import traceback
        print(f"[TVS] scoring failed, returning a neutral score: {error!r}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return _neutral


def _extractive_summarize(text, max_sentences=3):
    """
    JIT-secure and offline extractive summarizer using TF-IDF sentence extraction.
    Guarantees mathematically relevant bullet sentence selection with zero runtime downloads.
    """
    import re
    from sklearn.feature_extraction.text import TfidfVectorizer
    raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 15]
    # Prefer reporting sentences; fall back to the raw split only when the
    # filter leaves nothing (very short clusters).
    sentences = [s for s in raw_sentences if is_informative_sentence(s)] or raw_sentences
    if not sentences:
        return text[:400] + "..."
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
        
    try:
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(sentences)
        sentence_scores = np.asarray(tfidf_matrix.sum(axis=1)).ravel()
        
        # Select best indices, sort to preserve chronological flow
        top_indices = np.argsort(sentence_scores)[-max_sentences:]
        top_indices = sorted(top_indices)
        return " ".join([sentences[idx] for idx in top_indices])
    except Exception:
        return " ".join(sentences[:max_sentences])


# ------------------------------------------------------------------
# [IMPROVEMENT #7] Report Domain Breakdown Transparency
# The report now shows WHICH domains contributed to the veracity
# score and a human-readable consensus label. This makes the score
# interpretable and defensible in the dissertation.
# ------------------------------------------------------------------
def _get_consensus_label(n_domains):
    """Maps domain count to a human-readable consensus label."""
    if n_domains >= 5:
        return "STRONG"
    elif n_domains == 4:
        return "GOOD"
    elif n_domains == 3:
        return "MODERATE"
    elif n_domains == 2:
        return "WEAK"
    else:
        return "SINGLE-SOURCE"


def step_4_generate_content(df):
    print("\n⏳ Initializing BART-Large (BART) Summarizer...")
    from transformers import pipeline
    print("🔵 [4/5] Generating Intelligence Reports...")

    summarizer = None
    try:
        # Request the model on CPU
        summarizer = pipeline("summarization", model="facebook/bart-large-cnn", device=-1)
    except Exception as model_load_err:
        print(f"  ⚠️ facebook/bart-large-cnn could not be loaded unauthenticated ({model_load_err}).")
        print("  ⚡ Dynamic Activation: Switched to JIT-safe TF-IDF Extractive Sentence summarizer!")

    # Helper function that falls back to tf-idf extractive summary
    def make_summary(text, max_len_or_sentences=3):
        if summarizer is not None:
            try:
                limited_text = text[:3000]
                summary_res = summarizer(limited_text, max_length=300, min_length=100, do_sample=False)
                if summary_res and len(summary_res) > 0:
                    return summary_res[0].get('summary_text', '')
            except Exception:
                pass # Fall through to extractive summary
        
        # Use our pre-built robust offline sentence TF-IDF summarizer
        return _extractive_summarize(text, max_sentences=max_len_or_sentences)

    all_topics = df['Topic_ID'].unique().tolist()
    if -1 in all_topics: all_topics.remove(-1)

    report_path = _out(FILENAME_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=== VERINEWS INTELLIGENCE DOSSIER ===\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Total Clusters Processed: {len(all_topics)}\n\n")

        for topic_id in tqdm(all_topics, desc="Writing Reports"):
            topic_df = df[df['Topic_ID'] == topic_id]
            if len(topic_df) < 2: continue

            clean_title = clean_topic_title(str(topic_df['Topic_Name'].iloc[0]))
            combined_text = " ".join(topic_df['Text'].astype(str).iloc[:5].tolist())

            try:
                article_body = make_summary(combined_text, max_len_or_sentences=3)

                # USE TRIANGULATED VERACITY (v3.1) — now returns breakdown dict
                veracity_result = calculate_veracity_score_semantic(article_body, topic_df)
                veracity = veracity_result['final_score']
                ver_icon = "✅" if veracity > 70 else "⚠️"

                avg_sent_val = topic_df['Sentiment_Value'].mean()
                if avg_sent_val > 0.2:
                    sent_icon = "🟢 Positive"
                elif avg_sent_val < -0.2:
                    sent_icon = "🔴 Negative"
                else:
                    sent_icon = "⚪ Neutral"

                # [IMPROVEMENT #7] Domains for transparent reporting (same
                # publisher logic as the TVS domain factor)
                domains = veracity_result.get('domains') or sorted({d for d in _domains_for_frame(topic_df) if d})
                n_domains = len(domains)
                consensus_label = _get_consensus_label(n_domains)
                domains_display = ', '.join(domains[:8])  # Show up to 8 domains

                output = (
                    f"📢 SUBJECT: {clean_title}\n"
                    f"SENTIMENT: {sent_icon} (Score: {round(avg_sent_val, 2)}) | "
                    f"VERACITY: {veracity}/100 {ver_icon}\n"
                    f"CONSENSUS: {consensus_label} ({n_domains} domains: {domains_display})\n"
                    f"--------------------------------------------------\n"
                    f"{article_body}\n\n"
                    f"🏷️ KEYWORDS: {topic_df['KeyBERT'].iloc[0]}\n"
                    f"🌍 GEO-TAGS: {topic_df['NER_Location'].iloc[0]}\n"
                    f"🔗 SOURCES: {domains_display}\n"
                    f"==================================================\n\n"
                )
                f.write(output)
            except Exception as report_item_err:
                print(f"  ⚠️ Error preparing report item: {report_item_err}")
                continue

    print(f"\n🎉 SUCCESS. Dissertation Report Generated: '{report_path}'")


# ==================================================================
# [IMPROVEMENT #3c] VERACITY SCORE STRESS TEST
# Validates the Triangulated Veracity Score formula using synthetic
# clusters with known ground truth. This proves that Factor 3
# (Source Coherence) correctly differentiates agreeing vs.
# contradictory multi-source clusters — the mathematical proof
# required for the Evaluation chapter of the dissertation.
# ==================================================================
def evaluate_veracity_stress_test():
    """
    Stress-tests calculate_veracity_score_semantic() with three synthetic
    clusters that control for domain diversity (all have 5 unique domains)
    so that ONLY Factor 3 (Source Coherence) varies:

      Cluster A — High Coherence:  5 sources report the same fact.
      Cluster B — Low Coherence:   5 sources contradict each other.
      Cluster C — Mixed Coherence: 3 agree + 2 contradict.

    Prints a formatted comparison table with per-factor breakdowns.
    """
    print("\n" + "=" * 70)
    print("   VERACITY SCORE STRESS TEST  (Synthetic Ground-Truth Evaluation)")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Cluster A: HIGH COHERENCE — all 5 sources agree on the same fact
    # ------------------------------------------------------------------
    cluster_a_texts = [
        "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation and a softening labor market.",
        "The Fed announced a quarter-point rate cut on Wednesday, lowering the benchmark rate to support economic growth amid slowing inflation.",
        "Interest rates were reduced by 25 basis points by the Federal Reserve, as policymakers responded to declining consumer price pressures.",
        "The US central bank lowered its key interest rate by 0.25% in its latest policy decision, signaling confidence that inflation is easing.",
        "Federal Reserve officials voted to cut rates by a quarter point, marking the first reduction this year as inflation trends downward.",
    ]
    cluster_a_urls = [
        "https://www.reuters.com/economy/fed-cuts-rates",
        "https://www.bbc.co.uk/news/business-fed-rate-cut",
        "https://edition.cnn.com/2026/03/fed-rate-decision",
        "https://www.bloomberg.com/news/fed-quarter-point-cut",
        "https://www.nytimes.com/2026/03/federal-reserve-rates",
    ]
    summary_a = "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation and a weakening labor market."

    # ------------------------------------------------------------------
    # Cluster B: LOW COHERENCE — 5 sources contradict each other
    # ------------------------------------------------------------------
    cluster_b_texts = [
        "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation.",
        "The Fed unexpectedly raised interest rates by half a percentage point, surprising markets with a hawkish stance.",
        "The Federal Reserve kept interest rates unchanged in its latest meeting, adopting a wait-and-see approach to inflation.",
        "Central bank policymakers announced an emergency 0.75% rate hike to combat surging inflation and a weakening dollar.",
        "The Fed signaled it would begin cutting rates aggressively next quarter, with markets pricing in a full percentage point of easing.",
    ]
    cluster_b_urls = [
        "https://www.reuters.com/economy/fed-rate-decision",
        "https://www.bbc.co.uk/news/business-fed-surprise-hike",
        "https://edition.cnn.com/2026/03/fed-holds-steady",
        "https://www.bloomberg.com/news/fed-emergency-hike",
        "https://www.nytimes.com/2026/03/fed-signals-cuts",
    ]
    summary_b = "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation."

    # ------------------------------------------------------------------
    # Cluster C: MIXED — 3 agree, 2 contradict
    # ------------------------------------------------------------------
    cluster_c_texts = [
        "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation and a softening labor market.",
        "The Fed announced a quarter-point rate cut on Wednesday, lowering the benchmark rate to support economic growth.",
        "Interest rates were reduced by 25 basis points by the Federal Reserve, as policymakers responded to declining price pressures.",
        "The Fed unexpectedly raised interest rates by half a percentage point, surprising markets with a hawkish stance.",
        "The Federal Reserve kept interest rates unchanged in its latest meeting, adopting a wait-and-see approach.",
    ]
    cluster_c_urls = [
        "https://www.reuters.com/economy/fed-cuts-rates",
        "https://www.bbc.co.uk/news/business-fed-rate-cut",
        "https://edition.cnn.com/2026/03/fed-rate-decision",
        "https://www.bloomberg.com/news/fed-surprise-hike",
        "https://www.nytimes.com/2026/03/fed-holds-steady",
    ]
    summary_c = "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation."

    # ------------------------------------------------------------------
    # Build synthetic DataFrames and run the veracity function
    # ------------------------------------------------------------------
    test_cases = [
        ("A: High Coherence (5 agree)", cluster_a_texts, cluster_a_urls, summary_a),
        ("B: Low Coherence (5 contradict)", cluster_b_texts, cluster_b_urls, summary_b),
        ("C: Mixed (3 agree + 2 contradict)", cluster_c_texts, cluster_c_urls, summary_c),
    ]

    results = []
    for label, texts, urls, summary in test_cases:
        synthetic_df = pd.DataFrame({
            'Title': [f"Article {i+1}" for i in range(len(texts))],
            'Text': texts,
            'URL': urls,
        })
        result = calculate_veracity_score_semantic(summary, synthetic_df)
        result['label'] = label
        results.append(result)

    # ------------------------------------------------------------------
    # Print formatted comparison table
    # ------------------------------------------------------------------
    print(f"\n{'Cluster':<42} {'Score':>6} {'Semantic':>10} {'Domains':>9} {'Coherence':>11} {'Src Agree':>11}")
    print("-" * 92)
    for r in results:
        print(
            f"  {r['label']:<40} {r['final_score']:>5}/99 "
            f"{r['semantic_score']:>9.1f} "
            f"{r['n_domains']:>5} ({r['domain_factor']:.2f}) "
            f"{r['coherence_factor']:>9.4f}  "
            f"{r['source_coherence']:>9.4f}"
        )

    # ------------------------------------------------------------------
    # Print interpretation
    # ------------------------------------------------------------------
    delta_ab = results[0]['final_score'] - results[1]['final_score']
    delta_ac = results[0]['final_score'] - results[2]['final_score']
    print(f"\n--- Interpretation ---")
    print(f"  Score gap A vs B:  {delta_ab:+d} points  (coherent vs contradictory)")
    print(f"  Score gap A vs C:  {delta_ac:+d} points  (coherent vs mixed)")
    print(f"  Domain factor:     identical across all clusters ({results[0]['n_domains']} domains each)")
    print(f"  Discriminator:     Factor 3 (Source Coherence) is the differentiating variable.")

    if delta_ab > 0:
        print(f"\n  PASS: Coherent cluster scores higher than contradictory cluster.")
    else:
        print(f"\n  FAIL: Coherent cluster did NOT score higher. Review formula calibration.")

    print("=" * 70 + "\n")


# ==========================================
# DIAGNOSTIC TEST FUNCTION (STANDALONE ENTRY)
# ==========================================
def run_diagnostic_scraping_test(test_url="https://raw.githubusercontent.com/about/main/README.md"):
    """
    Lightweight, isolated diagnostic routine to test request performance, 
    redirect behavior, clean_text_logic sanity, and prevent regressions.
    
    Can be executed directly to verify connection capability.
    """
    print("\n" + "="*80)
    print("🔍 VERINEWS PIPELINE DIAGNOSTIC SYSTEM")
    print("="*80)
    print(f"Target URL:    {test_url}")
    
    # 1. Test Network Connection & Redirect Resolution
    print("\n[Step 1/3] Initiating raw request with retry + redirect tracking...")
    try:
        import urllib3
        # Quiet the insecure request warnings
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except:
        pass
        
    response = _request_with_retry(test_url, max_retries=3, timeout=10)
    if not response:
        print("❌ FAILED: Connection timed out or retries exhausted (None returned).")
        return False
        
    print("✅ SUCCESS: Web connection established!")
    print(f"   Status Code:   {response.status_code}")
    print(f"   Effective URL: {response.url}")
    print(f"   Response Size: {len(response.content)} bytes")
    
    # 2. Test bs4 / trafilatura text extraction
    print("\n[Step 2/3] Extracting plain-text payload...")
    trafilatura_worked = False
    raw_text = ""
    
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(test_url)
        if downloaded:
            extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if extracted:
                raw_text = extracted
                trafilatura_worked = True
                print("✅ Primary body extraction (Trafilatura) succeeded.")
    except Exception as te:
        print(f"⚠️ Primary extractor encountered note: {te}")
        
    if not trafilatura_worked:
        print("⚠️ Falling back to BeautifulSoup HTML parser...")
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            for tag in soup(["script", "style", "nav", "footer", "header", "form", "iframe", "ads", "aside", "noscript"]):
                tag.decompose()
            raw_text = soup.get_text(separator=' ')
            print("✅ Fallback BeautifulSoup extractor succeeded.")
        except Exception as be:
            print(f"❌ FAILED: Fallback text extraction crash: {be}")
            return False
            
    print(f"   Raw text len:  {len(raw_text)} characters")
    
    # 3. Test clean_text_logic preservation behavior
    print("\n[Step 3/3] Running text purification logic (clean_text_logic)...")
    try:
        test_preservation = (
            "First Paragraph content which is highly descriptive.\n"
            "Read more: PM visits site.\n"
            "Second Paragraph and valuable closing news content."
        )
        cleaned_preservation = clean_text_logic(test_preservation)
        if "Second Paragraph" not in cleaned_preservation:
            print("❌ REGRESSION DETECTED: clean_text_logic wiped paragraphs following standard boilerplate!")
            print(f"   Result was: {repr(cleaned_preservation)}")
            return False
        else:
            print("✅ Regression test: clean_text_logic safely preserved content following 'Read more' indicators.")
            
        final_cleaned_content = clean_text_logic(raw_text)
        print(f"   Cleaned len:   {len(final_cleaned_content)} characters")
        print("\n--- SAMPLE EXTRACTED CONTENT (SNEAK PEEK) ---")
        preview = final_cleaned_content[:400] + "..." if len(final_cleaned_content) > 400 else final_cleaned_content
        print(preview)
        print("---------------------------------------------")
        print("\n🎉 DIAGNOSIS RESULT: PIPELINE INGESTION STACK IS SAFE AND RUNNING HEALTHILY!")
        return True
    except Exception as e:
        print(f"❌ FAILED: Parsing/Cleaning text threw an error: {e}")
        return False


# ==========================================
# DASHBOARD EXPORT (osint_output.json, schema v2)
# ==========================================
def _row_sentiment(row):
    """(label, directional score) for one corpus row, tolerant to missing columns."""
    score = 0.0
    for col in ('Sentiment_Value', 'Sentiment_Score'):
        if col in row and pd.notna(row[col]):
            score = float(row[col])
            break
    label = str(row['Sentiment']).upper() if 'Sentiment' in row and pd.notna(row['Sentiment']) else ""
    if label not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
        label = "POSITIVE" if score > 0.2 else "NEGATIVE" if score < -0.2 else "NEUTRAL"
    return label, score


def _row_date(row):
    raw = row.get('Publish_Date', '')
    if pd.notna(raw) and str(raw):
        return raw.strftime('%Y-%m-%d') if hasattr(raw, 'strftime') else str(raw)[:10]
    return ""


def build_topic_node(t_df, topic_name):
    """One dashboard topic: summary, keywords, locations, per-article evidence
    and the REAL TVS breakdown (identical math to the TXT dossier)."""
    clean_title = clean_topic_title(topic_name)

    # Summarize from documents that actually have a scraped body: headline-only
    # rows would otherwise be spliced into the summary as bare titles.
    if 'Body_Available' in t_df.columns and t_df['Body_Available'].fillna(False).any():
        summary_source = t_df[t_df['Body_Available'].fillna(False).astype(bool)]
    else:
        summary_source = t_df
    combined_cluster_text = " ".join(summary_source['Text'].dropna().astype(str).iloc[:4].tolist())
    intelligence_summary = (
        _extractive_summarize(combined_cluster_text, max_sentences=3)
        if combined_cluster_text else "No articles available for this cluster."
    )

    keywords = []
    if 'KeyBERT' in t_df.columns:
        for val in t_df['KeyBERT'].dropna():
            keywords.extend(k.strip() for k in str(val).split(',') if k.strip())
    keywords = sorted(set(keywords)) or [w for w in str(topic_name).split("_")[1:] if w] or ["OSINT"]

    locations = []
    if 'NER_Location' in t_df.columns:
        for val in t_df['NER_Location'].dropna():
            locations.extend(l.strip() for l in str(val).split(',') if l.strip())
    locations = sorted(set(locations)) or ["Global"]

    details = calculate_veracity_score_semantic(intelligence_summary, t_df, return_details=True)
    sims = details.get('similarities') or []
    pairwise = details.get('pairwise_matrix')
    row_domains = _domains_for_frame(t_df)

    articles = []
    for pos, (_, row) in enumerate(t_df.iterrows()):
        raw_url = str(row.get('URL', '') or '')
        publisher_name = str(row.get('Publisher', '') or '') if pd.notna(row.get('Publisher', '')) else ''
        domain = row_domains[pos] if pos < len(row_domains) else ''
        label, score = _row_sentiment(row)
        coherence_row = []
        if pairwise is not None and pos < len(pairwise):
            coherence_row = [float(v) for col, v in enumerate(pairwise[pos]) if col != pos]
        body_available = row.get('Body_Available', None)
        display_source = publisher_name if (not domain or domain.startswith("name:")) else domain
        articles.append({
            "title": str(row.get('Title', 'Untitled Article')),
            "snippet": str(row.get('Text', ''))[:240],
            "url": raw_url,
            "source": display_source or "unresolved-source",
            "sourceKey": domain,
            "publisher": publisher_name,
            "urlResolved": bool(domain),
            "bodyAvailable": bool(body_available) if pd.notna(body_available) and body_available is not None else None,
            "pubDate": _row_date(row),
            "sentiment": label,
            "sentimentScore": score,
            "similarityToSummary": float(sims[pos]) if pos < len(sims) else None,
            "coherenceScores": coherence_row,
        })

    return {
        "topic": clean_title,
        "topicName": str(topic_name),
        "intelligenceSummary": intelligence_summary,
        "keywords": keywords,
        "locations": locations,
        "articles": articles,
        "formulaBreakdown": {
            "finalScore": details['final_score'],
            "semanticScore": details['semantic_score'],
            "avgSimilarity": details['avg_similarity'],
            "domainFactor": details['domain_factor'],
            "nDomains": details['n_domains'],
            "domains": details.get('domains', []),
            "coherenceFactor": details['coherence_factor'],
            "sourceCoherence": details['source_coherence'],
        },
    }


def build_export_payload(df, generated_by="batch"):
    topics = []
    for topic_id in sorted(int(t) for t in df['Topic_ID'].dropna().unique() if int(t) != -1):
        t_df = df[df['Topic_ID'] == topic_id]
        if len(t_df) == 0:
            continue
        topics.append(build_topic_node(t_df, str(t_df['Topic_Name'].iloc[0])))
    return export_envelope(topics, corpus_quality_report(df), generated_by)


def export_dashboard_json(df, generated_by="batch"):
    """Writes the dashboard payload atomically to the single canonical
    location (public/osint_output.json, or VERINEWS_PUBLIC_DIR)."""
    payload = build_export_payload(df, generated_by)
    dest = atomic_write_json(payload, os.path.join(resolve_public_dir(), OSINT_EXPORT_FILENAME))
    print(f"  ✅ Dashboard export written: '{dest}' ({len(payload['topics'])} topics)")
    return dest


# ==========================================
# BATCH PIPELINE
# ==========================================
def run_batch_pipeline(topics=None, max_articles=None, run_stress_test=True, excel_out=None):
    start_time = time.time()

    if run_stress_test:
        # [IMPROVEMENT #3d] Veracity stress test (independent of pipeline data)
        evaluate_veracity_stress_test()

    # Step 1: Scrape (resumes from the checkpoint if a previous run crashed)
    df = step_1_scrape(topics=topics, max_articles=max_articles)

    if len(df) <= 5:
        print("❌ Insufficient data.")
        return None

    # Step 2: NLP
    df = step_2_nlp_processing(df)

    # Step 3: Topics
    df = step_3_dynamic_topics(df)

    # Save Final Excel
    excel_path = excel_out or _out(FILENAME_EXCEL)
    print(f"\n💾 Archiving Dataset to Excel: '{excel_path}'")
    # Clean any invalid XML control characters from strings to prevent openpyxl IllegalCharacterError
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(lambda x: re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', x) if isinstance(x, str) else x)
    os.makedirs(os.path.dirname(os.path.abspath(excel_path)), exist_ok=True)
    df.to_excel(excel_path, index=False, engine='openpyxl')

    # Step 4: Report
    step_4_generate_content(df)

    # Step 5: Dashboard payload
    print("\n⚙️ Exporting synchronized dashboard payload for Next.js UI...")
    try:
        export_dashboard_json(df, generated_by="batch")
    except Exception as json_export_error:
        print(f"❌ Failed to build JSON dashboard export: {json_export_error}")

    report_corpus_quality(df, label="Final corpus")

    checkpoint_path = _out(FILENAME_CHECKPOINT)
    if os.path.exists(checkpoint_path):
        try:
            os.remove(checkpoint_path)
        except OSError:
            pass

    print(f"\n⏱️ SYSTEM COMPLETE. Runtime: {int(time.time() - start_time)}s.")
    return df


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="Alex1.py",
        description="VeriNews Engine v4.1 — OSINT ingestion, geometric topic modeling and "
                    "Triangulated Veracity Scoring.",
    )
    parser.add_argument("--stream", action="store_true",
                        help="incremental online-learning update (MiniBatchKMeans.partial_fit) instead of a full batch run")
    parser.add_argument("-t", "--topic", dest="topics", action="append", metavar="TOPIC",
                        help="restrict ingestion to this topic (repeatable); default: the built-in TOPICS list")
    parser.add_argument("--max-articles", type=int, default=None, metavar="N",
                        help=f"articles per topic (default {MAX_ARTICLES_PER_TOPIC})")
    parser.add_argument("--no-stress-test", action="store_true", help="skip the synthetic TVS stress test")
    parser.add_argument("--excel-out", default=None, metavar="PATH",
                        help=f"where to write the enriched corpus (default <output-dir>/{FILENAME_EXCEL})")
    parser.add_argument("--output-dir", default=None, metavar="DIR",
                        help="directory for xlsx/txt/html artefacts and the checkpoint (default: repository root)")
    parser.add_argument("--diagnose", action="store_true", help="run the ingestion self-test and exit")
    return parser


def main(argv=None):
    global OUTPUT_DIR
    args = build_arg_parser().parse_args(argv)
    if args.output_dir:
        OUTPUT_DIR = os.path.abspath(args.output_dir)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    if args.diagnose:
        return 0 if run_diagnostic_scraping_test() else 1

    if args.stream:
        # [v4.0] --stream: new articles are embedded and absorbed via
        # MiniBatchKMeans.partial_fit without refitting the whole model.
        from streaming_topic_model import run_stream_update
        run_stream_update(sys.modules[__name__], topics=args.topics, max_articles=args.max_articles)
        return 0

    df = run_batch_pipeline(
        topics=args.topics,
        max_articles=args.max_articles,
        run_stress_test=not args.no_stress_test,
        excel_out=args.excel_out,
    )
    return 0 if df is not None else 2


if __name__ == "__main__":
    sys.exit(main())
