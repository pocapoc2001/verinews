"""
metrics.py — scoring helpers shared by the parameter sweep and the evaluation.

Ground truth is binary (TRUE / FALSE as published by the fact-checker). A
method outputs a 0-100 credibility-style score, so we report both:

* rank agreement with the ground truth (Pearson r, Spearman rho, ROC-AUC),
  which does not depend on where a threshold is placed, and
* decision quality at the operating threshold (accuracy, precision, recall,
  F1, and the predicted true/fake counts the supervisor's table asks for).
"""
from __future__ import annotations

import math
from statistics import mean


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else float("nan")


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(_ranks(x), _ranks(y))


def pearson_p_value(r: float, n: int) -> float:
    """Two-sided p-value for a Pearson correlation (t distribution, n-2 df)."""
    if n < 3 or math.isnan(r) or abs(r) >= 1:
        return float("nan")
    t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
    df = n - 2
    # regularised incomplete beta via continued fraction (no scipy dependency)
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 200):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + numerator / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-10:
            break
    return front * (f - 1.0)


def roc_auc(scores: list[float], labels: list[int]) -> float:
    """Probability that a random TRUE claim outranks a random FALSE one."""
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return float("nan")
    ranks = _ranks(scores)
    rank_sum = sum(r for r, l in zip(ranks, labels) if l == 1)
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def classification(scores: list[float], labels: list[int], threshold: float) -> dict:
    """Predict TRUE when score >= threshold; returns the counts the
    supervisor's table asks for plus the usual rates."""
    tp = sum(1 for s, l in zip(scores, labels) if s >= threshold and l == 1)
    fp = sum(1 for s, l in zip(scores, labels) if s >= threshold and l == 0)
    fn = sum(1 for s, l in zip(scores, labels) if s < threshold and l == 1)
    tn = sum(1 for s, l in zip(scores, labels) if s < threshold and l == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = max(1, tp + fp + fn + tn)
    return {
        "threshold": threshold,
        "predicted_true": tp + fp,
        "predicted_false": fn + tn,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": round((tp + tn) / total, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def best_threshold(scores: list[float], labels: list[int], candidates=None) -> dict:
    """Operating point with the highest F1 (ties broken by accuracy)."""
    candidates = candidates if candidates is not None else range(5, 100)
    best = None
    for threshold in candidates:
        result = classification(scores, labels, float(threshold))
        key = (result["f1"], result["accuracy"])
        if best is None or key > (best["f1"], best["accuracy"]):
            best = result
    return best or {}


def evaluate(scores: list[float], labels: list[int], threshold: float | None = None) -> dict:
    """Full metric set for one method against the binary ground truth."""
    clean = [(s, l) for s, l in zip(scores, labels) if s is not None and not math.isnan(s)]
    if len(clean) < 3:
        return {"n": len(clean)}
    xs = [s for s, _ in clean]
    ys = [float(l) for _, l in clean]
    labels_clean = [l for _, l in clean]
    r = pearson(xs, ys)
    result = {
        "n": len(clean),
        "pearson_r": round(r, 4),
        "pearson_p": round(pearson_p_value(r, len(clean)), 6),
        "spearman_rho": round(spearman(xs, ys), 4),
        "roc_auc": round(roc_auc(xs, labels_clean), 4),
        "mean_true": round(mean([s for s, l in clean if l == 1] or [float("nan")]), 2),
        "mean_false": round(mean([s for s, l in clean if l == 0] or [float("nan")]), 2),
    }
    result["separation"] = round(result["mean_true"] - result["mean_false"], 2)
    decision = classification(xs, labels_clean, threshold) if threshold is not None else best_threshold(xs, labels_clean)
    result.update({f"{k}": v for k, v in decision.items()})
    return result


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------
# A ground-truth set of a few dozen clusters produces AUC values whose sampling
# error is larger than the gaps between methods: in this study one baseline
# scored 0.159 on one half of the claims and 0.813 on the other. Reporting a
# bare AUC would therefore invite a conclusion the data cannot support, so
# every headline figure is published with a bootstrap interval and a
# permutation p-value against the null "this score is unrelated to the verdict".
BOOTSTRAP_SAMPLES = 2000
PERMUTATION_SAMPLES = 2000


def _clean(scores: list[float], labels: list[int]) -> tuple[list[float], list[int]]:
    pairs = [(s, l) for s, l in zip(scores, labels) if s == s]  # drops NaN
    return [p[0] for p in pairs], [p[1] for p in pairs]


def bootstrap_auc_ci(scores, labels, samples: int = BOOTSTRAP_SAMPLES, seed: int = 7) -> dict:
    """Percentile bootstrap 95% CI for the ROC-AUC (resampling clusters)."""
    import random

    scores, labels = _clean(scores, labels)
    if len(scores) < 4 or len(set(labels)) < 2:
        return {"auc_lo": None, "auc_hi": None}
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        idx = [rng.randrange(len(scores)) for _ in scores]
        resampled = [labels[i] for i in idx]
        if 0 < sum(resampled) < len(resampled):
            draws.append(roc_auc([scores[i] for i in idx], resampled))
    if not draws:
        return {"auc_lo": None, "auc_hi": None}
    draws.sort()
    return {"auc_lo": round(draws[int(0.025 * len(draws))], 4),
            "auc_hi": round(draws[int(0.975 * len(draws))], 4)}


def permutation_p(scores, labels, samples: int = PERMUTATION_SAMPLES, seed: int = 7) -> float | None:
    """Two-sided permutation p-value for AUC != 0.5 (labels shuffled)."""
    import random

    scores, labels = _clean(scores, labels)
    if len(scores) < 4 or len(set(labels)) < 2:
        return None
    observed = abs(roc_auc(scores, labels) - 0.5)
    rng = random.Random(seed)
    shuffled = list(labels)
    hits = 0
    for _ in range(samples):
        rng.shuffle(shuffled)
        if abs(roc_auc(scores, shuffled) - 0.5) >= observed:
            hits += 1
    return round(hits / samples, 4)


def with_uncertainty(scores: list[float], labels: list[int], stats: dict) -> dict:
    """Adds the bootstrap interval and permutation p-value to a metrics dict."""
    stats.update(bootstrap_auc_ci(scores, labels))
    stats["auc_p"] = permutation_p(scores, labels)
    return stats
