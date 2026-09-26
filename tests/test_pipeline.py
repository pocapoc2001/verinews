"""Offline unit tests for the VeriNews backend (no network, no models)."""
import base64
import json
import os

import pandas as pd
import pytest

import verinews_common as vc


# ---------------------------------------------------------------------------
# verinews_common: domains, titles, labels, quality report
# ---------------------------------------------------------------------------
def test_publisher_domain_prefers_feed_publisher_and_ignores_aggregators():
    gnews = "https://news.google.com/rss/articles/CBMiXYZ?oc=5"
    assert vc.publisher_domain(gnews, "https://www.cnbc.com") == "cnbc.com"
    assert vc.publisher_domain(gnews) == ""                       # unresolved redirect is NOT a source
    assert vc.publisher_domain("https://edition.cnn.com/2026/x") == "cnn.com"
    assert vc.publisher_domain("https://www.msn.com/en-us/x") == ""
    assert vc.publisher_domain("https://r.search.yahoo.com/x", "https://www.reuters.com/y") == "reuters.com"
    assert vc.registrable_domain("not a url") == ""


def test_strip_publisher_suffix_only_for_publishers_and_known_outlets():
    assert vc.strip_publisher_suffix("Oil prices ease after Iran statement - CNBC", "CNBC") == \
        "Oil prices ease after Iran statement"
    assert vc.strip_publisher_suffix("Monetary developments: May 2026 - European Central Bank",
                                     "European Central Bank") == "Monetary developments: May 2026"
    assert vc.strip_publisher_suffix("Rates decision explained - Reuters") == "Rates decision explained"
    assert vc.strip_publisher_suffix("Some headline - not an outlet") == "Some headline - not an outlet"


def test_select_label_terms_dedupes_and_drops_boilerplate():
    ranked = ["com", "source google", "trump", "trump administration", "administration",
              "report direct", "election primary", "election", "2026 midterm"]
    assert vc.select_label_terms(ranked, n=4) == ["trump administration", "election primary", "2026 midterm"]
    assert vc.build_topic_label(9, ["com", "google", "source"]) == "9_cluster 9"


def test_clean_topic_title_removes_id_and_repeated_words():
    assert vc.clean_topic_title("8_election_primary_2026_midterm") == "Election Primary 2026 Midterm"
    assert vc.clean_topic_title("6_trump administration_election primary_election") == \
        "Trump Administration Election Primary"
    assert vc.clean_topic_title("Federal Reserve Interest Rates") == "Federal Reserve Interest Rates"


def test_build_stop_words_includes_boilerplate_publishers_but_keeps_topic_words():
    words = set(vc.build_stop_words(["cnbc.com", "wbaltv.com", "nytimes.com"]))
    assert {"com", "source", "google", "report", "direct", "cnbc", "wbaltv", "nytimes"} <= words
    assert not {"bank", "times", "election", "inflation"} & words


def test_corpus_quality_report_and_warnings():
    df = pd.DataFrame({
        "URL": ["https://news.google.com/rss/articles/A", "https://www.reuters.com/x", "https://www.bbc.co.uk/y"],
        "Publisher_URL": ["", "https://www.reuters.com", None],
        "Text": ["short headline", "x" * 400, "y" * 350],
        "Body_Available": [False, True, True],
    })
    report = vc.corpus_quality_report(df)
    assert report == {"documents": 3, "resolvedDomainShare": 0.6667, "knownSourceShare": 0.6667,
                      "bodyAvailableShare": 0.6667, "medianBodyChars": 350, "nDomains": 2, "aggregatorRows": 1}
    assert vc.quality_warnings(report) == []
    bad = vc.corpus_quality_report(pd.DataFrame({
        "URL": ["https://news.google.com/rss/articles/A"] * 4, "Text": ["stub"] * 4}))
    assert bad["resolvedDomainShare"] == 0.0 and len(vc.quality_warnings(bad)) == 2
    assert vc.corpus_quality_report(pd.DataFrame())["documents"] == 0


def test_export_envelope_shape(tmp_path):
    payload = vc.export_envelope([{"topic": "t"}], {"documents": 1}, "batch")
    assert payload["schemaVersion"] == 2 and payload["topics"] == [{"topic": "t"}]
    dest = vc.atomic_write_json(payload, str(tmp_path / "out.json"))
    assert json.load(open(dest, encoding="utf8"))["generatedBy"] == "batch"
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


# ---------------------------------------------------------------------------
# Alex1: decoder, rows, domains, TVS
# ---------------------------------------------------------------------------
def test_decode_gnews_url_accepts_boolean_status_and_retries(pipeline):
    calls = []

    def decoder(url, interval=None):
        calls.append(url)
        return {"status": True, "decoded_url": "https://www.theguardian.com/a"}

    url = "https://news.google.com/rss/articles/CBMiXYZ?oc=5"
    assert pipeline._decode_gnews_url(url, decoder=decoder) == "https://www.theguardian.com/a"
    assert calls == [url]

    failing = lambda url, interval=None: {"status": False, "message": "no"}
    assert pipeline._decode_gnews_url(url, decoder=failing) == url            # unresolved stays a redirect
    assert pipeline._decode_gnews_url("https://www.reuters.com/x", decoder=failing) == "https://www.reuters.com/x"


def test_decode_gnews_url_legacy_base64_fallback(pipeline):
    payload = base64.urlsafe_b64encode(b"\x08\x13\x22https://www.bbc.co.uk/news/1\xd2\x01").decode().rstrip("=")
    url = f"https://news.google.com/rss/articles/{payload}?oc=5"
    assert pipeline._decode_gnews_url(url, decoder=lambda u, interval=None: {"status": False}) == \
        "https://www.bbc.co.uk/news/1"


def test_assemble_row_flags_missing_body_without_boilerplate(pipeline):
    cand = {"title": "Fed cuts rates - CNBC", "url": "https://news.google.com/rss/articles/X", "date": "2026-07-01",
            "snippet": "The Federal Reserve cut its benchmark rate by a quarter point on Wednesday afternoon.",
            "publisher": "CNBC", "publisher_url": "https://www.cnbc.com"}
    row = pipeline._assemble_row("Fed", cand, "")
    assert row["Title"] == "Fed cuts rates"
    assert row["Text"] == cand["snippet"] and "Full report" not in row["Text"]
    assert row["Body_Available"] is False and row["URL_Resolved"] is False
    assert row["Publisher"] == "CNBC" and row["Publisher_URL"] == "https://www.cnbc.com"

    row = pipeline._assemble_row("Fed", dict(cand, url="https://www.cnbc.com/a"), "body " * 100)
    assert row["Body_Available"] is True and row["URL_Resolved"] is True and row["Text"].startswith("body")


def test_domains_for_frame_counts_publishers_not_redirects(pipeline):
    df = pd.DataFrame({
        "URL": ["https://news.google.com/rss/articles/A", "https://news.google.com/rss/articles/B",
                "https://www.bloomberg.com/c"],
        "Publisher_URL": ["https://www.reuters.com", "https://www.reuters.com", None],
    })
    assert pipeline._domains_for_frame(df) == ["reuters.com", "reuters.com", "bloomberg.com"]
    assert pipeline._domains_for_frame(pd.DataFrame({"URL": ["https://news.google.com/x"]})) == [""]
    syndicated = pd.DataFrame({"URL": ["https://www.msn.com/en-us/a", "https://www.msn.com/en-us/b"],
                               "Publisher": ["CBS News", "Some Local Paper"]})
    assert pipeline._domains_for_frame(syndicated) == ["cbsnews.com", "name:some local paper"]


def test_source_identity_and_known_source_share():
    assert vc.source_identity("https://www.msn.com/x", None, "Associated Press News") == "apnews.com"
    assert vc.source_identity("https://news.google.com/rss/articles/A", "https://www.cnbc.com", "CNBC") == "cnbc.com"
    assert vc.source_identity("https://news.google.com/rss/articles/A", None, None) == ""
    df = pd.DataFrame({"URL": ["https://www.msn.com/x", "https://news.google.com/rss/articles/A"],
                       "Publisher": ["CBS News", ""], "Text": ["x" * 400, "y"], "Body_Available": [True, False]})
    report = vc.corpus_quality_report(df)
    assert report["resolvedDomainShare"] == 0.0 and report["knownSourceShare"] == 0.5 and report["nDomains"] == 1


AGREE = [
    "The Federal Reserve cut interest rates by 0.25 percentage points today citing cooling inflation",
    "The Fed announced a quarter point rate cut today lowering the benchmark rate amid cooling inflation",
    "Interest rates were reduced by 25 basis points by the Federal Reserve as inflation cooled today",
    "The US central bank lowered its key interest rate by 0.25 percent today as inflation is cooling",
    "Federal Reserve officials voted to cut rates by a quarter point today as inflation trends down",
]
CONTRADICT = [
    "The Federal Reserve cut interest rates by 0.25 percentage points today citing cooling inflation",
    "The Fed unexpectedly raised interest rates by half a percentage point surprising markets with a hawkish stance",
    "The central bank kept policy unchanged in its latest meeting adopting a wait and see approach",
    "Policymakers announced an emergency 0.75 percent hike to combat surging prices and a weakening dollar",
    "Officials signaled aggressive easing next quarter with markets pricing a full percentage point of cuts",
]
URLS = ["https://www.reuters.com/a", "https://www.bbc.co.uk/b", "https://edition.cnn.com/c",
        "https://www.bloomberg.com/d", "https://www.nytimes.com/e"]
SUMMARY = "The Federal Reserve cut interest rates by 0.25 percent today responding to cooling inflation"


def _frame(texts, urls):
    return pd.DataFrame({"Title": [f"Article {i}" for i in range(len(texts))], "Text": texts, "URL": urls})


def test_tvs_stress_test_monotonic_and_factor_structure(pipeline):
    a = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(AGREE, URLS))
    b = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(CONTRADICT, URLS))
    c = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(AGREE[:3] + CONTRADICT[1:3], URLS))
    for res in (a, b, c):
        assert res["n_domains"] == 5 and res["domain_factor"] == 1.0
        assert 5 <= res["final_score"] <= 99
        assert 0.70 <= res["coherence_factor"] <= 1.0
        assert res["domains"] == sorted({"reuters.com", "bbc.co.uk", "cnn.com", "bloomberg.com", "nytimes.com"})
    assert a["source_coherence"] > c["source_coherence"] > b["source_coherence"]
    assert a["final_score"] > c["final_score"] > b["final_score"]
    expected = a["semantic_score"] * a["domain_factor"] * a["coherence_factor"]
    assert a["final_score"] == max(5, min(99, int(expected)))


@pytest.mark.parametrize("n_domains,factor", [(5, 1.0), (4, 0.95), (3, 0.85), (2, 0.72), (1, 0.60)])
def test_tvs_domain_ladder(pipeline, n_domains, factor):
    urls = [URLS[i % n_domains] for i in range(5)]
    res = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(AGREE, urls))
    assert res["n_domains"] == n_domains and res["domain_factor"] == factor


def test_tvs_unresolved_redirects_use_feed_publisher(pipeline):
    redirects = [f"https://news.google.com/rss/articles/{i}" for i in range(5)]
    without = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(AGREE, redirects))
    assert without["n_domains"] == 0 and without["domain_factor"] == 0.60
    df = _frame(AGREE, redirects)
    df["Publisher_URL"] = URLS
    with_publisher = pipeline.calculate_veracity_score_semantic(SUMMARY, df)
    assert with_publisher["n_domains"] == 5 and with_publisher["domain_factor"] == 1.0


def test_tvs_returns_details_and_neutral_on_empty(pipeline):
    res = pipeline.calculate_veracity_score_semantic(SUMMARY, _frame(AGREE, URLS), return_details=True)
    assert len(res["similarities"]) == 5 and len(res["pairwise_matrix"]) == 5
    assert pipeline.calculate_veracity_score_semantic(SUMMARY, _frame([], []))["final_score"] == 50


# ---------------------------------------------------------------------------
# Alex1: dashboard export
# ---------------------------------------------------------------------------
def test_build_export_payload_schema_and_sources(pipeline, tmp_path, monkeypatch):
    df = _frame(AGREE, ["https://news.google.com/rss/articles/0"] + URLS[1:])
    df["Publisher_URL"] = ["https://www.reuters.com"] + [None] * 4
    df["Publisher"] = ["Reuters"] + [""] * 4
    df["Body_Available"] = [False, True, True, True, True]
    df["Publish_Date"] = "2026-07-01"
    df["Topic_ID"] = 0
    df["Topic_Name"] = "0_fed_rate cut_inflation"
    df["Sentiment"] = "NEGATIVE"
    df["Sentiment_Value"] = -0.5
    df["KeyBERT"] = "rate cut, inflation"
    df["NER_Location"] = "Washington"

    payload = pipeline.build_export_payload(df, generated_by="test")
    assert payload["schemaVersion"] == 2 and payload["generatedBy"] == "test"
    assert payload["qualityReport"]["resolvedDomainShare"] == 1.0
    topic = payload["topics"][0]
    assert topic["topic"] == "Fed Rate Cut Inflation"
    assert topic["formulaBreakdown"]["nDomains"] == 5 and "domains" in topic["formulaBreakdown"]
    first = topic["articles"][0]
    assert first["source"] == "reuters.com" and first["publisher"] == "Reuters"
    assert first["urlResolved"] is True and first["bodyAvailable"] is False
    assert first["sentiment"] == "NEGATIVE" and first["pubDate"] == "2026-07-01"
    assert isinstance(first["similarityToSummary"], float) and len(first["coherenceScores"]) == 4

    monkeypatch.setenv("VERINEWS_PUBLIC_DIR", str(tmp_path))
    dest = pipeline.export_dashboard_json(df, generated_by="test")
    assert dest == str(tmp_path / "osint_output.json")
    assert json.load(open(dest, encoding="utf8"))["topics"][0]["topic"] == "Fed Rate Cut Inflation"


def test_cli_parser(pipeline):
    args = pipeline.build_arg_parser().parse_args(["-t", "A", "-t", "B", "--max-articles", "5", "--no-stress-test"])
    assert args.topics == ["A", "B"] and args.max_articles == 5 and args.no_stress_test and not args.stream


def test_pipeline_prints_survive_a_non_utf8_stdout():
    """Regression: a redirected stdout used to take the whole score down.

    Python falls back to the locale encoding when stdout is a pipe, which is
    cp1252 on a default Windows install. The pipeline's progress messages
    contain emoji, so every redirected run raised UnicodeEncodeError inside
    scoring, where a broad `except` converted it into a neutral 50 for every
    cluster. The child process below reproduces exactly that environment.
    """
    import subprocess
    import sys as _sys

    script = (
        "import Alex1\n"
        "print('\u23f3 loading', '\u2705 done')\n"
        "print('ok')\n"
    )
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "TRANSFORMERS_OFFLINE": "1"}
    # The child is asked for cp1252 and the guard upgrades it to UTF-8, so the
    # parent must decode UTF-8; decoding as cp1252 here would fail on the very
    # bytes whose survival this test is asserting.
    result = subprocess.run(
        [_sys.executable, "-c", script], cwd=vc.REPO_ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, f"non-UTF-8 stdout broke the pipeline:\n{result.stderr[-2000:]}"
    assert "ok" in result.stdout


def test_neutral_fallback_reports_why_instead_of_scoring_silently(monkeypatch, capsys):
    """A neutral 50 must never be indistinguishable from a real 50."""
    import Alex1

    monkeypatch.setattr(Alex1, "extract_evidence", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    frame = pd.DataFrame({"Title": ["t"], "Text": ["some body text"], "URL": ["https://a.com/x"]})
    result = Alex1.calculate_veracity_score_semantic("a summary", frame)

    assert result["final_score"] == 50
    assert "boom" in capsys.readouterr().err
