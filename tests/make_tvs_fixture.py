"""
Generates lib/fixtures/tvs_stress_test.json from the canonical Python TVS
implementation (Alex1.py) using the REAL SBERT model, so that:

  * the dashboard's "Stress-Test Matrix" shows the same 85/99, 71/99, 79/99
    reported in the dissertation/paper instead of hand-typed similarities;
  * tests/tvs.test.ts can assert that lib/tvs.ts reproduces the Python
    breakdown bit-for-bit from the exported evidence.

Run once (needs the cached all-mpnet-base-v2 model):
    .venv\\Scripts\\python.exe tests\\make_tvs_fixture.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import Alex1  # noqa: E402

CASES = [
    {
        "caseId": "A", "label": "Cohort A: High Coherence", "description": "Five outlets report the same fact.",
        "summary": "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation and a weakening labor market.",
        "texts": [
            "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation and a softening labor market.",
            "The Fed announced a quarter-point rate cut on Wednesday, lowering the benchmark rate to support economic growth amid slowing inflation.",
            "Interest rates were reduced by 25 basis points by the Federal Reserve, as policymakers responded to declining consumer price pressures.",
            "The US central bank lowered its key interest rate by 0.25% in its latest policy decision, signaling confidence that inflation is easing.",
            "Federal Reserve officials voted to cut rates by a quarter point, marking the first reduction this year as inflation trends downward.",
        ],
        "urls": [
            "https://www.reuters.com/economy/fed-cuts-rates", "https://www.bbc.co.uk/news/business-fed-rate-cut",
            "https://edition.cnn.com/2026/03/fed-rate-decision", "https://www.bloomberg.com/news/fed-quarter-point-cut",
            "https://www.nytimes.com/2026/03/federal-reserve-rates",
        ],
    },
    {
        "caseId": "B", "label": "Cohort B: Low Coherence", "description": "Five outlets contradict each other.",
        "summary": "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation.",
        "texts": [
            "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation.",
            "The Fed unexpectedly raised interest rates by half a percentage point, surprising markets with a hawkish stance.",
            "The Federal Reserve kept interest rates unchanged in its latest meeting, adopting a wait-and-see approach to inflation.",
            "Central bank policymakers announced an emergency 0.75% rate hike to combat surging inflation and a weakening dollar.",
            "The Fed signaled it would begin cutting rates aggressively next quarter, with markets pricing in a full percentage point of easing.",
        ],
        "urls": [
            "https://www.reuters.com/economy/fed-rate-decision", "https://www.bbc.co.uk/news/business-fed-surprise-hike",
            "https://edition.cnn.com/2026/03/fed-holds-steady", "https://www.bloomberg.com/news/fed-emergency-hike",
            "https://www.nytimes.com/2026/03/fed-signals-cuts",
        ],
    },
    {
        "caseId": "C", "label": "Cohort C: Mixed Coherence", "description": "Three outlets agree, two contradict.",
        "summary": "The Federal Reserve cut interest rates by 0.25% today, responding to cooling inflation.",
        "texts": [
            "The Federal Reserve cut interest rates by 0.25 percentage points today, citing cooling inflation and a softening labor market.",
            "The Fed announced a quarter-point rate cut on Wednesday, lowering the benchmark rate to support economic growth.",
            "Interest rates were reduced by 25 basis points by the Federal Reserve, as policymakers responded to declining price pressures.",
            "The Fed unexpectedly raised interest rates by half a percentage point, surprising markets with a hawkish stance.",
            "The Federal Reserve kept interest rates unchanged in its latest meeting, adopting a wait-and-see approach.",
        ],
        "urls": [
            "https://www.reuters.com/economy/fed-cuts-rates", "https://www.bbc.co.uk/news/business-fed-rate-cut",
            "https://edition.cnn.com/2026/03/fed-rate-decision", "https://www.bloomberg.com/news/fed-surprise-hike",
            "https://www.nytimes.com/2026/03/fed-holds-steady",
        ],
    },
]

SOURCES = ["Reuters", "BBC News", "CNN", "Bloomberg", "The New York Times"]


def main():
    out_cases = []
    for case in CASES:
        df = pd.DataFrame({"Title": [f"Article {i + 1}" for i in range(5)], "Text": case["texts"], "URL": case["urls"]})
        details = Alex1.calculate_veracity_score_semantic(case["summary"], df, return_details=True)
        pairwise = np.array(details["pairwise_matrix"])
        upper = [float(pairwise[i][j]) for i in range(5) for j in range(i + 1, 5)]
        articles = []
        for i in range(5):
            articles.append({
                "title": f"{SOURCES[i]}: {case['texts'][i][:60].rstrip('.,')}…",
                "snippet": case["texts"][i],
                "url": case["urls"][i],
                "source": Alex1._extract_domain(case["urls"][i]),
                "publisher": SOURCES[i],
                "urlResolved": True,
                "bodyAvailable": True,
                "pubDate": "2026-03-20",
                "sentiment": "NEUTRAL",
                "sentimentScore": 0.0,
                "similarityToSummary": float(details["similarities"][i]),
                "coherenceScores": [float(v) for j, v in enumerate(pairwise[i]) if j != i],
            })
        out_cases.append({
            "caseId": case["caseId"], "label": case["label"], "description": case["description"],
            "summary": case["summary"], "articles": articles,
            "pairwiseUpperTriangle": upper,
            "formulaBreakdown": {
                "finalScore": int(details["final_score"]), "semanticScore": float(details["semantic_score"]),
                "avgSimilarity": float(details["avg_similarity"]), "domainFactor": float(details["domain_factor"]),
                "nDomains": int(details["n_domains"]), "domains": list(details["domains"]),
                "coherenceFactor": float(details["coherence_factor"]), "sourceCoherence": float(details["source_coherence"]),
            },
        })
        print(f"  {case['caseId']}: {details['final_score']}/99 (semantic {details['semantic_score']}, "
              f"coherence {details['coherence_factor']})")

    dest = os.path.join(ROOT, "lib", "fixtures", "tvs_stress_test.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({"generatedBy": f"Alex1.py / {Alex1.EMBEDDING_MODEL_NAME}", "cases": out_cases}, fh, indent=2)
    print(f"fixture written: {dest}")


if __name__ == "__main__":
    main()
