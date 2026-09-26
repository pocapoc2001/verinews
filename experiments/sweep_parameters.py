"""
sweep_parameters.py — empirical justification of the TVS constants.

Every constant in the score (the 30/70 of factor 1, the domain ladder, the
0.70/0.30 coherence mapping, the top-k, the flag threshold) is varied over the
*calibration* split of the ground truth, and each variant is scored against the
fact-checkers' verdicts. The chosen configuration is then the one the tables
show to be best — not a value asserted in the text.

Outputs (experiments/results/):
    table_parameter_variants.csv      variants x claims + the ground-truth row
    table_parameter_correlation.csv   one row per variant with all metrics
    table_parameter_counts.md         "GT 12 true/12 false -> variant predicts .."
    fig_parameter_sweep.png           metric vs parameter value, per family
    sweep_summary.json                machine-readable, consumed by the paper build

    .venv\\Scripts\\python.exe experiments\\sweep_parameters.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from verinews_common import DEFAULT_TVS_PARAMS, TVSParams, tvs_from_evidence, upper_triangle  # noqa: E402
from metrics import evaluate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_DIR = os.path.join(HERE, "evidence")
RESULTS_DIR = os.path.join(HERE, "results")


def load_bundles(split: str | None = None, min_articles: int = 2) -> list[dict]:
    bundles = []
    for path in sorted(glob.glob(os.path.join(EVIDENCE_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            bundle = json.load(fh)
        if bundle.get("n_articles", 0) < min_articles or not bundle.get("summary"):
            continue
        if split and bundle.get("split") != split:
            continue
        bundles.append(bundle)
    return bundles


def score(bundle: dict, params: TVSParams) -> float:
    result = tvs_from_evidence(
        bundle.get("similarities"), bundle.get("domains"),
        upper_triangle(bundle.get("pairwise")), params,
    )
    return float(result["final_score"])


def variant_families() -> dict[str, list[TVSParams]]:
    """The parameter families to sweep. Each variant is a full configuration,
    so a row of the table is reproducible from its label alone."""
    families: dict[str, list[TVSParams]] = {}

    # Four variants per family: the production value plus the extremes and one
    # intermediate step, which is what fits the IEEE column while still showing
    # the shape of each curve. The figure is drawn from the same entries.
    # Factor 1 — where the semantic scale starts and how much range it spans.
    families["semantic scale (base/range)"] = [
        DEFAULT_TVS_PARAMS.with_values(semantic_base=base, semantic_range=100 - base,
                                       label=f"{int(base)}/{int(100 - base)}")
        for base in (0, 20, 30, 50)
    ]
    # Factor 1 — how many sources define fidelity.
    families["top-k sources"] = [
        DEFAULT_TVS_PARAMS.with_values(top_k=k, label=f"top-{k if k else 'all'}")
        for k in (1, 3, 5, 0)
    ]
    # Factor 2 — shape of the diversity ladder.
    families["domain ladder"] = [
        DEFAULT_TVS_PARAMS.with_values(domain_ladder=ladder, label=name)
        for name, ladder in [
            ("flat", ((1, 1.00),)),
            ("mild", ((5, 1.00), (4, 0.98), (3, 0.95), (2, 0.90), (1, 0.85))),
            ("current", ((5, 1.00), (4, 0.95), (3, 0.85), (2, 0.72), (1, 0.60))),
            ("steep", ((5, 1.00), (4, 0.90), (3, 0.75), (2, 0.55), (1, 0.35))),
        ]
    ]
    # Factor 3 — how much inter-source agreement can move the score.
    families["coherence mapping (base/range)"] = [
        DEFAULT_TVS_PARAMS.with_values(coherence_base=base, coherence_range=round(1 - base, 2),
                                       label=f"{base:.2f}/{1 - base:.2f}")
        for base in (0.50, 0.70, 0.90, 1.00)
    ]
    # Reporting — where the warning flag fires. This constant changes no score,
    # only the decision drawn from it, so its AUC is flat by construction; it is
    # swept because it is one of the numbers the score is criticised for and the
    # predicted true/false counts are what it actually moves.
    families["flag threshold"] = [
        DEFAULT_TVS_PARAMS.with_values(flag_threshold=t, label=str(t))
        for t in (60, 70, 75, 85)
    ]
    return families


def write_variant_tables(bundles: list[dict], families: dict, threshold: int) -> dict:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    claim_ids = [b["claim_id"] for b in bundles]
    labels = [1 if b["verdict"] == "TRUE" else 0 for b in bundles]

    # --- Table in the supervisor's Table 1 layout: rows = variants, cols = claims
    rows = [{"variant": "Ground truth (fact-checker verdict)", "family": "-",
             **{cid: ("TRUE" if lab else "FALSE") for cid, lab in zip(claim_ids, labels)}}]
    correlation_rows, counts_lines, summary = [], [], {"families": {}, "threshold": threshold}

    n_true, n_false = sum(labels), len(labels) - sum(labels)
    counts_lines.append(f"Calibration split: **{n_true} true / {n_false} false** claims "
                        f"(fact-checker verdicts), decision threshold = {threshold}.\n")
    counts_lines.append("| Family | Variant | Predicted true | Predicted false | Correct | Accuracy | F1 | Pearson r |")
    counts_lines.append("|---|---|---|---|---|---|---|---|")

    for family, variants in families.items():
        summary["families"][family] = []
        for params in variants:
            scores = [score(b, params) for b in bundles]
            # A threshold variant changes no score, only the cut applied to it,
            # so it has to be judged at its own value or the family would look
            # inert in every column including the counts it actually moves.
            decision_threshold = float(params.flag_threshold)
            # At a FIXED threshold a variant that merely shifts the scale upward
            # looks better without discriminating better, so the fixed-threshold
            # decision is reported next to the variant's own best operating
            # point, and families are ranked by AUC, which needs no threshold.
            stats = evaluate(scores, labels, threshold=decision_threshold)
            tuned = evaluate(scores, labels)
            stats["f1_at_best_threshold"] = tuned.get("f1")
            stats["best_threshold"] = tuned.get("threshold")
            rows.append({"variant": params.label, "family": family,
                         **{cid: round(s, 1) for cid, s in zip(claim_ids, scores)}})
            correlation_rows.append({
                "family": family, "variant": params.label,
                "pearson_r": stats.get("pearson_r"), "pearson_p": stats.get("pearson_p"),
                "spearman_rho": stats.get("spearman_rho"), "roc_auc": stats.get("roc_auc"),
                "mean_true": stats.get("mean_true"), "mean_false": stats.get("mean_false"),
                "separation": stats.get("separation"), "accuracy": stats.get("accuracy"),
                "f1": stats.get("f1"), "f1_at_best_threshold": stats.get("f1_at_best_threshold"),
                "best_threshold": stats.get("best_threshold"),
                "predicted_true": stats.get("predicted_true"),
                "predicted_false": stats.get("predicted_false"),
                "is_default": params.label == _default_label(family),
            })
            counts_lines.append(
                f"| {family} | {params.label}{' **(chosen)**' if params.label == _default_label(family) else ''} "
                f"| {stats.get('predicted_true')} | {stats.get('predicted_false')} "
                f"| {stats.get('tp', 0) + stats.get('tn', 0)}/{len(labels)} "
                f"| {stats.get('accuracy')} | {stats.get('f1')} | {stats.get('pearson_r')} |")
            summary["families"][family].append({"variant": params.label, **stats})

    with open(os.path.join(RESULTS_DIR, "table_parameter_variants.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["family", "variant"] + claim_ids)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(RESULTS_DIR, "table_parameter_correlation.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(correlation_rows[0].keys()))
        writer.writeheader()
        writer.writerows(correlation_rows)
    with open(os.path.join(RESULTS_DIR, "table_parameter_counts.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(counts_lines) + "\n")
    return summary


def _rank_key(family: str):
    """How to judge a family: AUC everywhere, F1 for the decision threshold.

    The threshold changes no score, so all four of its variants share one AUC
    and ranking it that way would crown an arbitrary winner. What it does move
    is the decision, so it is judged by the quality of that decision."""
    if family == "flag threshold":
        return lambda e: ((e.get("f1") or 0), (e.get("accuracy") or 0))
    return lambda e: ((e.get("roc_auc") or 0), (e.get("pearson_r") or 0))


def _default_label(family: str) -> str:
    return {
        "semantic scale (base/range)": "30/70",
        "top-k sources": "top-3",
        "domain ladder": "current",
        "coherence mapping (base/range)": "0.70/0.30",
        "flag threshold": "75",
    }.get(family, "")


def plot_sweep(summary: dict, path: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not installed - skipping the figure")
        return

    families = list(summary["families"].keys())
    # A 2 x 3 grid rather than one wide strip: the strip had to span both IEEE
    # columns, and a spanning element needs its own section, which Word pushes
    # whole to the next page when it does not fit — that cost roughly a third of
    # a page in white space. Drawn large and scaled down to one column, so the
    # tick labels stay legible in print.
    cols = 3
    rows = (len(families) + cols - 1) // cols
    plt.rcParams.update({"font.size": 13})
    fig, axes_grid = plt.subplots(rows, cols, figsize=(6.0, 1.9 * rows))
    axes = list(axes_grid.flat) if hasattr(axes_grid, "flat") else [axes_grid]
    for spare in axes[len(families):]:
        spare.axis("off")
    for ax, family in zip(axes, families):
        entries = summary["families"][family]
        labels = [e["variant"] for e in entries]
        auc_values = [e.get("roc_auc") or 0 for e in entries]
        r_values = [e.get("pearson_r") or 0 for e in entries]
        x = range(len(labels))
        # AUC leads because it needs no threshold; the 0.5 line marks chance, so
        # a curve hugging it says the parameter cannot help on this task.
        ax.axhline(0.5, color="0.45", linewidth=0.8, linestyle=":")
        ax.plot(x, auc_values, marker="o", label="ROC-AUC")
        ax.plot(x, r_values, marker="s", linestyle="--", label="Pearson r")
        default = _default_label(family)
        if default in labels:
            ax.axvline(labels.index(default), color="crimson", linewidth=1, alpha=0.6)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=11)
        ax.set_title(family, fontsize=11)
        ax.set_ylim(0.0, 1.0)
        ax.grid(alpha=0.25)
        ax.tick_params(labelsize=11)
    axes[0].set_ylabel("vs fact-checker verdicts", fontsize=11)
    axes[len(families) - 1].legend(fontsize=10, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"  figure -> {path}")


def main():
    parser = argparse.ArgumentParser(description="Sweep the TVS constants against the ground truth.")
    parser.add_argument("--split", default="calibration", help="ground-truth split to calibrate on")
    parser.add_argument("--threshold", type=int, default=DEFAULT_TVS_PARAMS.flag_threshold)
    args = parser.parse_args()

    bundles = load_bundles(args.split)
    if len(bundles) < 6:
        sys.exit(f"only {len(bundles)} usable clusters in the '{args.split}' split — run build_evidence.py first")
    print(f"calibrating on {len(bundles)} clusters "
          f"({sum(1 for b in bundles if b['verdict'] == 'TRUE')} true / "
          f"{sum(1 for b in bundles if b['verdict'] == 'FALSE')} false)")

    summary = write_variant_tables(bundles, variant_families(), args.threshold)
    summary["split"] = args.split
    summary["n_clusters"] = len(bundles)
    plot_sweep(summary, os.path.join(RESULTS_DIR, "fig_parameter_sweep.png"))
    summary["n_true"] = sum(1 for b in bundles if b["verdict"] == "TRUE")
    summary["n_false"] = sum(1 for b in bundles if b["verdict"] == "FALSE")

    print("\nbest variant per family (ROC-AUC, threshold-free; F1 for the decision threshold):")
    for family, entries in summary["families"].items():
        best = max(entries, key=_rank_key(family))
        chosen = _default_label(family)
        current = next((e for e in entries if e["variant"] == chosen), {})
        marker = ("== production" if best["variant"] == chosen
                  else f"production {chosen}: AUC={current.get('roc_auc')} F1={current.get('f1')}")
        print(f"  {family:32} {best['variant']:>18}  AUC={best.get('roc_auc')}  F1={best.get('f1')}  {marker}")

    # What this study would recommend if the objective were claim-veracity
    # ranking. Reported beside production, never applied silently.
    calibrated = {f: max(e, key=_rank_key(f))["variant"] for f, e in summary["families"].items()}
    summary["calibrated_variants"] = calibrated
    print("\ncalibrated-for-this-task configuration:", calibrated)

    # Does that tuning survive contact with unseen claims? A sweep that is only
    # ever reported on the split it was fitted to would overstate the gain, so
    # the calibrated configuration is carried to the held-out split here and the
    # difference is published whichever way it falls.
    summary["transfer"] = transfer_check(bundles, calibrated, args.split)
    with open(os.path.join(RESULTS_DIR, "sweep_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    print(f"\ntables -> {RESULTS_DIR}")


def calibrated_params(calibrated: dict) -> TVSParams:
    """Rebuilds a full configuration from the winning variant label per family."""
    params = DEFAULT_TVS_PARAMS
    for family, variants in variant_families().items():
        chosen = calibrated.get(family)
        for variant in variants:
            if variant.label == chosen:
                if family == "semantic scale (base/range)":
                    params = params.with_values(semantic_base=variant.semantic_base,
                                                semantic_range=variant.semantic_range)
                elif family == "top-k sources":
                    params = params.with_values(top_k=variant.top_k)
                elif family == "domain ladder":
                    params = params.with_values(domain_ladder=variant.domain_ladder)
                elif family == "coherence mapping (base/range)":
                    params = params.with_values(coherence_base=variant.coherence_base,
                                                coherence_range=variant.coherence_range)
    return params.with_values(label="calibrated-for-veracity")


def transfer_check(calibration_bundles: list[dict], calibrated: dict, calibration_split: str) -> dict:
    """AUC of production vs calibrated parameters, on both splits."""
    from metrics import roc_auc

    tuned = calibrated_params(calibrated)
    out = {"calibrated_label": {k: v for k, v in calibrated.items()}}
    for split in (calibration_split, "evaluation"):
        bundles = calibration_bundles if split == calibration_split else load_bundles("evaluation")
        if len(bundles) < 4:
            continue
        labels = [1 if b["verdict"] == "TRUE" else 0 for b in bundles]
        if len(set(labels)) < 2:
            continue
        out[split] = {
            "n": len(bundles),
            "production_auc": round(roc_auc([score(b, DEFAULT_TVS_PARAMS) for b in bundles], labels), 4),
            "calibrated_auc": round(roc_auc([score(b, tuned) for b in bundles], labels), 4),
        }
    fitted, unseen = out.get(calibration_split, {}), out.get("evaluation", {})
    if fitted and unseen:
        print(f"\nparameter transfer: calibrated config gains "
              f"{unseen['calibrated_auc'] - unseen['production_auc']:+.4f} AUC on unseen claims "
              f"(vs {fitted['calibrated_auc'] - fitted['production_auc']:+.4f} on the split it was fitted to)")
    return out


if __name__ == "__main__":
    main()
