"""Offline tests for the TVS parameterisation, the metrics and the baselines."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experiments"))

import verinews_common as vc  # noqa: E402
import metrics  # noqa: E402
import baselines  # noqa: E402


# ---------------------------------------------------------------------------
# TVSParams / tvs_from_evidence
# ---------------------------------------------------------------------------
SIMS = [0.9, 0.8, 0.7, 0.2]
DOMAINS = ["reuters.com", "bbc.co.uk", "cnn.com", "bloomberg.com"]
UPPER = [0.8, 0.8, 0.8, 0.8, 0.8, 0.8]


def test_defaults_reproduce_the_published_formula():
    result = vc.tvs_from_evidence(SIMS, DOMAINS, UPPER)
    # S = 30 + 70*mean(0.9,0.8,0.7) = 86.0 ; F_dom(4) = 0.95 ; F_coh = 0.70+0.30*0.8 = 0.94
    assert result["semantic_score"] == pytest.approx(86.0, abs=0.01)
    assert result["domain_factor"] == 0.95
    assert result["coherence_factor"] == pytest.approx(0.94, abs=0.001)
    assert result["final_score"] == int(86.0 * 0.95 * 0.94)
    assert result["n_domains"] == 4 and result["domains"] == sorted(DOMAINS)


@pytest.mark.parametrize("n,factor", [(7, 1.0), (5, 1.0), (4, 0.95), (3, 0.85), (2, 0.72), (1, 0.60), (0, 0.60)])
def test_domain_ladder(n, factor):
    assert vc.DEFAULT_TVS_PARAMS.domain_factor(n) == factor


def test_parameter_overrides_change_the_score_predictably():
    base = vc.tvs_from_evidence(SIMS, DOMAINS, UPPER)
    flat = vc.tvs_from_evidence(SIMS, DOMAINS, UPPER, vc.DEFAULT_TVS_PARAMS.with_values(
        semantic_base=0.0, semantic_range=100.0))
    assert flat["semantic_score"] == pytest.approx(80.0, abs=0.01)
    assert flat["final_score"] < base["final_score"]

    top1 = vc.tvs_from_evidence(SIMS, DOMAINS, UPPER, vc.DEFAULT_TVS_PARAMS.with_values(top_k=1))
    assert top1["avg_similarity"] == pytest.approx(0.9, abs=1e-6)
    all_k = vc.tvs_from_evidence(SIMS, DOMAINS, UPPER, vc.DEFAULT_TVS_PARAMS.with_values(top_k=0))
    assert all_k["avg_similarity"] == pytest.approx(0.65, abs=1e-6)

    steep = vc.tvs_from_evidence(SIMS, DOMAINS[:2], UPPER[:1], vc.DEFAULT_TVS_PARAMS.with_values(
        domain_ladder=((5, 1.0), (4, 0.9), (3, 0.75), (2, 0.55), (1, 0.35))))
    assert steep["domain_factor"] == 0.55


def test_clamp_and_flag():
    high = vc.tvs_from_evidence([1.0] * 5, DOMAINS + ["nytimes.com"], [1.0] * 10)
    assert high["final_score"] == 99 and high["flagged"] is False
    low = vc.tvs_from_evidence([0.0], [""], [])
    assert low["final_score"] >= 5 and low["flagged"] is True


def test_single_source_uses_the_neutral_coherence():
    one = vc.tvs_from_evidence([0.9], ["reuters.com"], [])
    assert one["source_coherence"] == 0.5
    assert one["coherence_factor"] == pytest.approx(0.85, abs=1e-6)
    assert one["domain_factor"] == 0.60


def test_upper_triangle():
    matrix = [[1.0, 0.8, 0.6], [0.8, 1.0, 0.4], [0.6, 0.4, 1.0]]
    assert vc.upper_triangle(matrix) == [0.8, 0.6, 0.4]
    assert vc.upper_triangle(None) == []


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_correlations_and_auc():
    scores = [90.0, 85.0, 80.0, 40.0, 30.0, 20.0]
    labels = [1, 1, 1, 0, 0, 0]
    assert metrics.pearson(scores, [float(l) for l in labels]) > 0.9
    # perfect separation, but the binary labels are tied, so Spearman peaks
    # below 1.0; what matters is that it is high and positive
    assert metrics.spearman(scores, [float(l) for l in labels]) > 0.85
    assert metrics.spearman(scores[::-1], [float(l) for l in labels]) < -0.85
    assert metrics.roc_auc(scores, labels) == 1.0
    assert metrics.roc_auc(scores[::-1], labels) == 0.0


def test_pearson_p_value_matches_known_case():
    # r = 0.7951 with n = 20 -> p = 0.000028 (the value reported in the thesis)
    assert metrics.pearson_p_value(0.7951, 20) == pytest.approx(0.000028, abs=5e-6)
    assert metrics.pearson_p_value(0.2542, 20) == pytest.approx(0.2795, abs=5e-4)


def test_classification_counts_and_best_threshold():
    scores = [90.0, 80.0, 70.0, 60.0]
    labels = [1, 1, 0, 0]
    result = metrics.classification(scores, labels, 75.0)
    assert (result["tp"], result["fp"], result["fn"], result["tn"]) == (2, 0, 0, 2)
    assert result["predicted_true"] == 2 and result["accuracy"] == 1.0
    assert metrics.best_threshold(scores, labels)["f1"] == 1.0


def test_evaluate_reports_separation():
    stats = metrics.evaluate([90.0, 85.0, 40.0, 35.0], [1, 1, 0, 0], threshold=75.0)
    assert stats["n"] == 4 and stats["separation"] == 50.0 and stats["f1"] == 1.0


# ---------------------------------------------------------------------------
# baselines
# ---------------------------------------------------------------------------
def _bundle(**overrides):
    bundle = {
        "claim_id": "C001",
        "summary": "The central bank raised interest rates by a quarter point on Wednesday.",
        "similarities": [0.9, 0.8, 0.7],
        "articles": [
            {"title": "Central bank raises rates by quarter point", "domain": "reuters.com",
             "text": "The central bank raised interest rates by a quarter point on Wednesday, citing inflation."},
            {"title": "Rates go up as inflation persists", "domain": "bbc.co.uk",
             "text": "Policymakers lifted the benchmark rate by 25 basis points this week."},
            {"title": "Quarter-point hike confirmed", "domain": "apnews.com",
             "text": "The bank confirmed a 0.25 percentage point increase in its policy rate."},
        ],
    }
    bundle.update(overrides)
    return bundle


def test_source_count_baseline():
    assert baselines.source_count_score(_bundle()) == 75.0
    assert baselines.source_count_score(_bundle(articles=[])) == 45.0


def test_semantic_only_baseline_matches_factor_one():
    expected = vc.tvs_from_evidence([0.9, 0.8, 0.7], ["a.com"], [])["semantic_score"]
    assert baselines.semantic_only_score(_bundle()) == pytest.approx(expected, abs=0.01)


def test_sensational_lexicon_penalises_clickbait():
    calm = baselines.sensational_lexicon_score(_bundle())
    loud = baselines.sensational_lexicon_score(_bundle(articles=[
        {"title": "SHOCKING!!! The TRUTH they don't want you to know — EXPOSED!", "domain": "x.com",
         "text": "Unbelievable bombshell! Doctors hate this secret miracle cure! WAKE UP sheeple!!!"},
    ]))
    assert calm > loud


def test_tfidf_overlap_rewards_lexical_agreement():
    aligned = baselines.tfidf_overlap_score(_bundle())
    unrelated = baselines.tfidf_overlap_score(_bundle(articles=[
        {"title": "Football results", "domain": "x.com", "text": "The striker scored twice in the derby last night."},
    ]))
    assert aligned > unrelated


def test_newsguard_style_scores_from_cached_profiles_only():
    cache = {
        "reuters.com": {"reachable": True, "about": True, "corrections": True, "staff": True,
                        "contact": True, "has_bylines": True, "labels_ads": True, "labels_opinion": True},
        "bbc.co.uk": {"reachable": True, "about": True, "corrections": True, "staff": True,
                      "contact": True, "has_bylines": True, "labels_ads": True, "labels_opinion": True},
        "apnews.com": {"reachable": True, "about": True, "corrections": True, "staff": True,
                       "contact": True, "has_bylines": True, "labels_ads": True, "labels_opinion": True},
        "opaque.example": {"reachable": False, "about": False, "corrections": False, "staff": False,
                           "contact": False, "has_bylines": False, "labels_ads": False, "labels_opinion": False},
    }
    full = baselines.newsguard_style_score(_bundle(), cache=cache, offline=True)
    assert full == pytest.approx(100.0, abs=0.01)   # all nine criteria satisfied
    opaque = baselines.newsguard_style_score(
        _bundle(articles=[{"title": "x", "domain": "opaque.example", "text": "y"}]), cache=cache, offline=True)
    assert opaque == pytest.approx(10.0, abs=0.01)  # only the headline criterion is earned
    assert sum(weight for _, weight in baselines.NEWSGUARD_CRITERIA) == 100.0
