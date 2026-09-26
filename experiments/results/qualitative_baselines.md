# VeriNews compared with existing veracity tools

The three tools named by the reviewers are closed products: none publishes its
model, its training data or an API that would return a score for our clusters,
so a like-for-like metric comparison against *their* outputs is not possible.
What each of them does publish is a methodology description, and that is the
basis of this comparison. The quantitative table (`table_baseline_metrics.md`)
compares VeriNews against the methods *replicated* from those descriptions and
from the literature they belong to — most importantly NewsGuard's nine
criteria, whose weights are public.

## Positioning

| Dimension | **VeriNews (this work)** | **NewsGuard** | **Justificat.ro** | **isitfake.app** |
|---|---|---|---|---|
| Unit of analysis | Cluster of articles covering one event | Website (publisher) | A single claim, text, image or video | The claims inside a URL or YouTube video |
| Core signal | Geometry of the sources: summary–source fidelity, independent-publisher diversity, inter-source agreement | Nine journalistic criteria scored by trained journalists | Advanced AI models combined with web search engines, reasoning over sources retrieved in real time | Gemini, OpenAI and Anthropic; extracts claims, cross-references them against independent outlets, checks the cited sources exist |
| Output | 5–99 verification-confidence score, decomposed into its three factors | 0–100 trust score + written "Nutrition Label"; 75+ favourable, 60–74 "Credible with Exceptions", 40–59 "Proceed with Caution" | One of three verdicts (Adevărat / Fals / Înșelător) with a 0–100% confidence | Trust Score 0–100% plus Verified / Partially Verified / Debunked, with a claim-by-claim breakdown |
| Human in the loop | Analyst reads the factor breakdown and the agreement matrix | Rating produced and reviewed by journalists | Not documented on the site | Not in the loop, but results are stated to be "indicative, not definitive" |
| Update latency | Per run: rescored as soon as new coverage is ingested | Manual re-review by analysts | Per query | Per query |
| Transparency | Open source; every number traceable to the sources and reproducible from the repository | Criteria and weights published; individual ratings proprietary | Method described publicly; models and prompts closed | Method described publicly; models and prompts closed |
| Explainability | Factor decomposition + per-source cosine + pairwise agreement matrix, all inspectable | Written rationale per site | Verdict with cited sources and a confidence | Trust score with per-claim substantiation and source list |
| Failure mode it targets | AI-generated summaries drifting from their sources; single-source and mutually contradictory reporting | Unreliable *publishers* | Individual false claims | Unsupported claims and fabricated citations inside a page |
| Languages | English (multilingual SBERT is future work) | Multiple | Accepts any language; answers in Romanian or English | English |
| Cost | Free, self-hosted, no API keys required | Commercial licence / subscription | Free tier, closed service | Free tier, closed service |

## What VeriNews adds

1. **It scores a cluster, not a page or a publisher.** NewsGuard answers "is
   this outlet generally reliable?" and isitfake.app answers "is this URL
   trustworthy?". Neither answers the question an analyst actually faces —
   *given everything published about this event, how well corroborated is it?*
   Corroboration across independent outlets is a property of the set, and it is
   exactly what factors 2 and 3 measure.
2. **It audits the generated summary, not only the sources.** The score falls
   when the abstractive summary drifts from the documents it was built from, so
   the metric covers the failure mode introduced by the summarisation step
   itself. None of the three tools scores machine-generated summaries against
   their own evidence.
3. **The score is decomposable and inspectable.** Every point is attributable to
   semantic fidelity, source diversity or inter-source agreement, and the
   pairwise agreement matrix is shown. Commercial trust scores are a single
   number with prose attached.
4. **It is reproducible.** The pipeline, the parameters, the ground truth and
   the evaluation scripts are in this repository; a reviewer can regenerate
   every figure. The constants of the formula are justified by the sweep in
   `table_parameter_correlation.csv` rather than asserted.
5. **It needs no proprietary service.** No API key, no subscription, no rate
   limit: it runs offline against any corpus, which matters for the OSINT
   setting where queries themselves can be sensitive.

## What it does not do (and where the baselines are stronger)

- It is **not a fact-checker**. It measures how well sourced and mutually
  consistent a narrative is. Coordinated or repeatedly syndicated
  misinformation can be internally consistent and will score accordingly —
  this is why the evaluation reports the retrieved stance mix per cluster.
- It has **no publisher reputation memory**. NewsGuard's central asset is a
  human-maintained history of how outlets behave over time; VeriNews only sees
  the sources retrieved for the current event. The two signals are
  complementary, which is why the source-reputation baseline (B1) is included.
- It does **not adjudicate a single claim** the way Justificat.ro does, and it
  does not analyse images or video.
- It is currently **English-only**.

## What the measurement showed

The qualitative case above is the positioning argument. The quantitative study
that accompanies it (`table_baseline_metrics.md`) does **not** support a claim
that VeriNews ranks claim veracity better than these baselines, and the paper
says so:

- On the 36 pooled clusters the TVS reaches ROC-AUC 0.640, 95% CI 0.446-0.826,
  permutation p = 0.154 — not distinguishable from chance against fact-checker
  verdicts.
- The lexical sensationalism baseline (B2) is the strongest method at AUC 0.796
  (p = 0.0015), followed by the factor-1 ablation (B5, 0.719) and TF-IDF
  overlap (B3, 0.705).
- Against the replications of the three named tools, the TVS (0.640) ranks
  above the NewsGuard-style B1 (0.423) and the Justificat.ro-style B7 (0.387)
  and below the isitfake.app-style B6 (0.651, CI 0.466-0.830, p = 0.135). All
  four intervals overlap, so this ordering is not evidence that any of them is
  better; it is stated because it is the honest part of the answer to "does
  VeriNews beat the tools?".
- A stance-weighted fourth factor was tried and rejected by its own
  calibration. The stance flag only detects refutation (`stance_of` never
  returns "promote"), and B7, which scores it alone, is the weakest method.
- Method ranking is unstable at this sample size: B1 scores AUC 0.159 on one
  half of the set and 0.813 on the other. This is why the pooled figure with
  its interval is the reported result and the per-split numbers are printed
  beside it rather than being chosen between.
- The clusters explain why. True and false claims retrieve near-identical
  coverage (9.7 vs 11.0 articles, 8.9 vs 9.3 publishers, 31% vs 26%
  debunk-leaning), so source geometry carries no verdict signal by
  construction: a well-debunked falsehood is well corroborated.

The honest conclusion is therefore about *scope*, not superiority. The TVS
measures verification confidence and sourcing quality — where the human study
found r = 0.7951 — and this benchmark is the evidence that it should not be
read as a veracity classifier.

## Sources

Every claim in the table above was read off the tool's own pages on 2026-09-23;
where a detail is not published, the cell says so rather than guessing.

- NewsGuard, "Rating Process and Criteria" — https://www.newsguardtech.com/ratings/rating-process-criteria/
  (the nine criteria and their weights: 22, 18, 12.5, 12.5, 10, 7.5, 7.5, 5, 5, and the score bands)
- NewsGuard, "How it works" — https://www.newsguardtech.com/how-it-works/
- Justificat.ro — https://justificat.ro/ (FAQ: "modele AI avansate combinate cu motoare de
  căutare web"; verdicts Adevărat / Fals / Înșelător with a 0–100% confidence)
- Is it Fake?, "How it works" — https://get.isitfake.app/ (Gemini, OpenAI and Anthropic; claim
  extraction, cross-referencing, source-existence checks; Trust Score and three classes)
