import type { Article } from "./types";

/** Cosine similarity of an article to the cluster summary, or null when the exporter had none. */
export function similarityOf(article: Article): number | null {
  const v = article.similarityToSummary;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function formatSimilarity(article: Article, digits = 3): string {
  const v = similarityOf(article);
  return v === null ? "n/a" : v.toFixed(digits);
}

export function percentSimilarity(article: Article): string {
  const v = similarityOf(article);
  return v === null ? "n/a" : `${Math.round(v * 100)}%`;
}

/**
 * Agreement between source i and source j from the exporter's per-article
 * rows (each row lists agreement with every OTHER source, self skipped).
 * Returns null when the evidence is missing — never a made-up default.
 */
export function pairwiseAgreement(articles: Article[], i: number, j: number): number | null {
  if (i === j) return 1;
  const row = articles[i]?.coherenceScores;
  if (!Array.isArray(row) || row.length === 0) return null;
  const idx = j > i ? j - 1 : j;
  const v = row[idx];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function sentimentTone(sentiment: string): "positive" | "negative" | "neutral" {
  if (sentiment === "POSITIVE") return "positive";
  if (sentiment === "NEGATIVE") return "negative";
  return "neutral";
}
