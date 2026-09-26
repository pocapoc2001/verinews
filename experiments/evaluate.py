"""
evaluate.py — TVS against the replicated baselines on the fact-checked claims.

Reporting protocol (fixed before the numbers were read, and kept):

* The *held-out* split is reported because the parameter sweep touched only the
  calibration split, so it is the clean test of the production configuration.
* The *pooled* set is the headline, because neither split alone is large enough
  to rank methods: in this study B1 scored AUC 0.159 on the calibration half and
  0.813 on the evaluation half. Every pooled AUC carries a bootstrap 95%
  interval and a permutation p-value, so a gap between two methods can be read
  as significant or not instead of being asserted.
* The per-split AUCs are printed side by side precisely so that this
  instability stays visible instead of hiding behind the flattering split.

The 3-factor TVS uses its production constants and no baseline is fitted. The
one thing calibrated here is the weight of the experimental stance factor, on
the calibration split only; if it does not raise the calibration AUC it is
left off and no extended row is reported (the current outcome).

Outputs (experiments/results/):
    table_baseline_scores.csv      per-claim score, every method
    table_baseline_metrics.csv     one row per method (AUC, CI, p, r, F1, ...)
    table_baseline_metrics.md      the same tables, ready to read
    summary.json                   consumed by the dashboard and the paper build

    .venv\\Scripts\\python.exe experiments\\evaluate.py [--offline]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from verinews_common import DEFAULT_TVS_PARAMS, tvs_from_evidence, upper_triangle  # noqa: E402
import baselines  # noqa: E402
from metrics import evaluate as evaluate_method, roc_auc, with_uncertainty  # noqa: E402
from sweep_parameters import RESULTS_DIR, load_bundles  # noqa: E402

TVS_NAME = "VeriNews TVS (3 factors)"
TVS_STANCE_NAME = "VeriNews TVS + stance (v4.2 preview)"


def stance_support(bundle: dict) -> float:
    """Share of the retrieved coverage that supports rather than refutes.

    Read from the stance flag `build_evidence.stance_of` already records, so
    the extension costs no new retrieval and no new model."""
    articles = bundle.get("articles") or []
    if not articles:
        return 0.5
    weights = {"debunk": 0.0, "neutral": 0.5, "promote": 1.0}
    return sum(weights.get(a.get("stance", "neutral"), 0.5) for a in articles) / len(articles)


def tvs_scores(bundles: list[dict], params=DEFAULT_TVS_PARAMS) -> dict[str, float]:
    out = {}
    for bundle in bundles:
        result = tvs_from_evidence(bundle.get("similarities"), bundle.get("domains"),
                                   upper_triangle(bundle.get("pairwise")), params,
                                   stance_support=stance_support(bundle))
        out[bundle["claim_id"]] = float(result["final_score"])
    return out


def score_every_method(bundles: list[dict], offline: bool, stance_base: float | None = None) -> dict:
    """The shipped 3-factor score, the labelled stance extension, and B1-B7.

    The extension is reported as its own row rather than folded into the TVS:
    the paper's method is the 3-factor score the supervisor already has, and a
    change to it has to be argued, not slipped in."""
    methods = {TVS_NAME: tvs_scores(bundles)}
    if stance_base is not None and stance_base < 1.0:
        tuned = DEFAULT_TVS_PARAMS.with_values(stance_base=stance_base)
        methods[TVS_STANCE_NAME] = tvs_scores(bundles, tuned)
    methods.update(baselines.score_all(bundles, offline=offline))
    return methods


def metrics_for(methods: dict, bundles: list[dict], threshold: int, uncertainty: bool) -> list[dict]:
    claim_ids = [b["claim_id"] for b in bundles]
    labels = [1 if b["verdict"] == "TRUE" else 0 for b in bundles]
    rows = []
    for name, scores in methods.items():
        ordered = [scores.get(c, float("nan")) for c in claim_ids]
        # each method keeps its own best operating point: a baseline on a
        # different scale must not be judged at the TVS threshold
        stats = evaluate_method(ordered, labels,
                                threshold=float(threshold) if name == TVS_NAME else None)
        if uncertainty:
            with_uncertainty(ordered, labels, stats)
        rows.append({"method": name, **stats})
    rows.sort(key=lambda r: (-(r.get("roc_auc") or 0), -(r.get("f1") or 0)))
    return rows


def split_auc(methods: dict, bundles: list[dict], split: str) -> dict:
    subset = [b for b in bundles if b.get("split") == split]
    labels = [1 if b["verdict"] == "TRUE" else 0 for b in subset]
    if len(set(labels)) < 2:
        return {}
    return {name: round(roc_auc([scores.get(b["claim_id"], float("nan")) for b in subset], labels), 4)
            for name, scores in methods.items()}


def markdown_table(rows: list[dict], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        cells = []
        for key in columns:
            if key == "auc_ci":
                lo, hi = row.get("auc_lo"), row.get("auc_hi")
                cells.append("[%.3f, %.3f]" % (lo, hi) if lo is not None else "n/a")
            else:
                cells.append(str(row.get(key, "")))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def calibrate_stance(every: list[dict], held_out_split: str) -> float | None:
    """Picks stance_base by AUC on the calibration split; None if it never helps."""
    calibration = [b for b in every if b.get("split") != held_out_split]
    labels = [1 if b["verdict"] == "TRUE" else 0 for b in calibration]
    if len(calibration) < 6 or len(set(labels)) < 2:
        return None
    baseline_auc = roc_auc([s for s in tvs_scores(calibration).values()], labels)
    best, best_auc = None, baseline_auc
    for candidate in (0.9, 0.8, 0.7, 0.6, 0.5, 0.3, 0.0):
        params = DEFAULT_TVS_PARAMS.with_values(stance_base=candidate)
        auc = roc_auc(list(tvs_scores(calibration, params).values()), labels)
        if auc > best_auc:
            best, best_auc = candidate, auc
    if best is None:
        print("stance factor: calibration prefers it OFF (AUC %.4f); not reported" % baseline_auc)
        return None
    print("stance factor: calibrated stance_base=%.1f (calibration AUC %.4f vs %.4f without)"
          % (best, best_auc, baseline_auc))
    return best


def main():
    parser = argparse.ArgumentParser(description="Compare the TVS with the replicated baselines.")
    parser.add_argument("--split", default="evaluation", help="the held-out split to report separately")
    parser.add_argument("--threshold", type=int, default=DEFAULT_TVS_PARAMS.flag_threshold)
    parser.add_argument("--offline", action="store_true",
                        help="skip live domain probing for B1 (uses the cached profiles only)")
    args = parser.parse_args()

    every = load_bundles(None)
    held_out = [b for b in every if b.get("split") == args.split]
    if len(held_out) < 4:
        sys.exit("only %d usable clusters in '%s' — run build_evidence.py first" % (len(held_out), args.split))

    n_true = sum(1 for b in every if b["verdict"] == "TRUE")
    print("pooled: %d clusters (%d true / %d false) | held-out '%s': %d"
          % (len(every), n_true, len(every) - n_true, args.split, len(held_out)))

    # The stance weight is chosen on the calibration split and then frozen, so
    # the held-out column is a real test of it rather than a restatement of the
    # fit. Calibrating on everything would make the extension look better than
    # it is, which is the whole failure this study is trying to avoid.
    stance_base = calibrate_stance(every, args.split)
    print("running baselines (B1 probes publisher domains; cached after the first run)...")
    methods = score_every_method(every, args.offline, stance_base)

    pooled_rows = metrics_for(methods, every, args.threshold, uncertainty=True)
    held_rows = metrics_for(methods, held_out, args.threshold, uncertainty=False)
    per_split = {s: split_auc(methods, every, s) for s in ("calibration", args.split)}

    # --- per-claim score table (supervisor's Table 4 layout) ---
    os.makedirs(RESULTS_DIR, exist_ok=True)
    claim_ids = [b["claim_id"] for b in every]
    labels = {b["claim_id"]: (1 if b["verdict"] == "TRUE" else 0) for b in every}
    rows = [{"method": "Ground truth (fact-checker)",
             **{c: ("TRUE" if labels[c] else "FALSE") for c in claim_ids}}]
    for name, scores in methods.items():
        rows.append({"method": name, **{c: round(scores.get(c, float("nan")), 1) for c in claim_ids}})
    with open(os.path.join(RESULTS_DIR, "table_baseline_scores.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["method"] + claim_ids)
        writer.writeheader()
        writer.writerows(rows)

    fields = ["method", "n", "roc_auc", "auc_lo", "auc_hi", "auc_p", "pearson_r", "pearson_p",
              "spearman_rho", "mean_true", "mean_false", "separation", "threshold", "accuracy",
              "precision", "recall", "f1", "predicted_true", "predicted_false", "tp", "fp", "fn", "tn"]
    with open(os.path.join(RESULTS_DIR, "table_baseline_metrics.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pooled_rows)

    pooled_cols = ["method", "n", "roc_auc", "auc_ci", "auc_p", "pearson_r", "separation", "accuracy", "f1"]
    pooled_lines = markdown_table(pooled_rows, pooled_cols)
    held_lines = markdown_table(held_rows, ["method", "roc_auc", "pearson_r", "mean_true",
                                            "mean_false", "separation", "accuracy", "f1"])
    stability = ["| method | AUC calibration | AUC held-out |", "|---|---|---|"]
    for row in pooled_rows:
        name = row["method"]
        stability.append("| %s | %s | %s |" % (name,
                                               per_split.get("calibration", {}).get(name, "n/a"),
                                               per_split.get(args.split, {}).get(name, "n/a")))

    with open(os.path.join(RESULTS_DIR, "table_baseline_metrics.md"), "w", encoding="utf-8") as fh:
        fh.write("## Pooled ground truth (%d clusters, %d true / %d false)\n\n"
                 % (len(every), n_true, len(every) - n_true))
        fh.write("Headline table. The 95% CI is a percentile bootstrap over clusters; p is a two-sided\n"
                 "permutation test against AUC = 0.5. An interval containing 0.500 means the method is\n"
                 "not distinguishable from chance on this ground truth.\n\n")
        fh.write("\n".join(pooled_lines) + "\n\n")
        fh.write("## Held-out split only (%d clusters)\n\n" % len(held_out))
        fh.write("\n".join(held_lines) + "\n\n")
        fh.write("## Split stability\n\nThe same method evaluated on each half. Large swings show that a\n"
                 "single split of this size cannot rank methods, which is why the pooled table leads.\n\n")
        fh.write("\n".join(stability) + "\n")

    sweep_path = os.path.join(RESULTS_DIR, "sweep_summary.json")
    sweep = json.load(open(sweep_path, encoding="utf-8")) if os.path.exists(sweep_path) else {}
    with open(os.path.join(RESULTS_DIR, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "groundTruth": {
                "source": "Snopes ClaimReview (schema.org) verdicts",
                "pooled": {"n": len(every), "true": n_true, "false": len(every) - n_true},
                "evaluation": {"n": len(held_out),
                               "true": sum(1 for b in held_out if b["verdict"] == "TRUE"),
                               "false": sum(1 for b in held_out if b["verdict"] == "FALSE")},
                "calibration": {"n": sweep.get("n_clusters"), "threshold": sweep.get("threshold")},
            },
            "methods": pooled_rows,
            "heldOutMethods": held_rows,
            "splitStability": per_split,
            "perClaim": rows,
            "parameterSweep": sweep.get("families", {}),
            "parameterTransfer": sweep.get("transfer", {}),
            "clusters": [{"claim_id": b["claim_id"], "verdict": b["verdict"], "n_articles": b["n_articles"],
                          "n_domains": b["n_domains"], "n_debunk": b["n_debunk"], "split": b.get("split"),
                          "claim_text": b["claim_text"][:160], "factcheck_url": b["factcheck_url"]}
                         for b in every],
        }, fh, indent=1)

    print("\n" + "\n".join(pooled_lines))
    print("\nsplit stability:\n" + "\n".join(stability))
    print("\nresults -> %s" % RESULTS_DIR)


if __name__ == "__main__":
    main()
