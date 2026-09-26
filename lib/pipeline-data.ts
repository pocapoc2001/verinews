// Server-side access to the pipeline export (public/osint_output.json).
// The file is written atomically by Alex1.py / streaming_topic_model.py.
// Both the v2 envelope and the legacy bare array are accepted, so an older
// export keeps working while the pipeline is upgraded.

import { promises as fs } from "fs";
import path from "path";

import type { PipelineExport, PipelineTopic, ScoreBreakdown } from "./types";
import { calculateVeracityScore, upperTriangleFromRows } from "./tvs";

export const EXPORT_FILENAME = "osint_output.json";

export function exportPath(): string {
  const dir = process.env.VERINEWS_PUBLIC_DIR || path.join(process.cwd(), "public");
  return path.join(dir, EXPORT_FILENAME);
}

function normalizeTopic(raw: Record<string, unknown>): PipelineTopic {
  const articles = Array.isArray(raw.articles) ? (raw.articles as PipelineTopic["articles"]) : [];
  let breakdown = (raw.formulaBreakdown as ScoreBreakdown | null | undefined) ?? null;

  // Legacy exports carried per-article evidence but no breakdown: recompute
  // from REAL evidence only — never from placeholder defaults.
  if (!breakdown && articles.length > 0) {
    const sims = articles.map((a) => a.similarityToSummary);
    const rows = articles.map((a) => (Array.isArray(a.coherenceScores) ? a.coherenceScores : []));
    if (sims.every((s) => typeof s === "number")) {
      breakdown = calculateVeracityScore(
        sims as number[],
        articles.map((a) => a.source || ""),
        upperTriangleFromRows(rows),
      );
    }
  }

  return {
    topic: String(raw.topic ?? ""),
    topicName: typeof raw.topicName === "string" ? raw.topicName : undefined,
    intelligenceSummary: String(raw.intelligenceSummary ?? raw.summary ?? ""),
    keywords: Array.isArray(raw.keywords) ? (raw.keywords as string[]) : [],
    locations: Array.isArray(raw.locations) ? (raw.locations as string[]) : [],
    articles,
    formulaBreakdown: breakdown,
  };
}

export function normalizeExport(parsed: unknown): PipelineExport {
  if (Array.isArray(parsed)) {
    return {
      schemaVersion: 1,
      generatedAt: null,
      generatedBy: null,
      qualityReport: null,
      topics: parsed.map((t) => normalizeTopic(t as Record<string, unknown>)),
    };
  }
  const obj = (parsed ?? {}) as Record<string, unknown>;
  const topics = Array.isArray(obj.topics) ? obj.topics : [];
  return {
    schemaVersion: Number(obj.schemaVersion ?? 2),
    generatedAt: typeof obj.generatedAt === "string" ? obj.generatedAt : null,
    generatedBy: typeof obj.generatedBy === "string" ? obj.generatedBy : null,
    qualityReport: (obj.qualityReport as PipelineExport["qualityReport"]) ?? null,
    topics: topics.map((t) => normalizeTopic(t as Record<string, unknown>)),
  };
}

/** Reads and normalizes the export; returns null when no export exists yet. */
export async function loadExport(): Promise<PipelineExport | null> {
  try {
    const raw = await fs.readFile(exportPath(), "utf-8");
    return normalizeExport(JSON.parse(raw));
  } catch (error) {
    if ((error as NodeJS.ErrnoException)?.code === "ENOENT") return null;
    throw error;
  }
}

export function findTopic(data: PipelineExport, query: string): PipelineTopic | null {
  const needle = query.trim().toLowerCase();
  if (!needle) return null;
  return (
    data.topics.find((t) => t.topic.toLowerCase() === needle) ??
    data.topics.find((t) => t.topic.toLowerCase().includes(needle) || needle.includes(t.topic.toLowerCase())) ??
    null
  );
}
