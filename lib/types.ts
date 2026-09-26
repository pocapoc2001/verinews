// Shared contract between the Python exporter (Alex1.py::build_export_payload),
// the API routes and the dashboard components.

export interface Article {
  title: string;
  snippet: string;
  url: string;
  /** Publisher domain (or name key) that counts for the diversity factor. */
  source: string;
  /** Publisher name as reported by the feed/search engine, may be "". */
  publisher?: string;
  /** Whether the article URL resolved to a real publisher page. */
  urlResolved?: boolean;
  /** Whether the article body was scraped (false = headline/snippet only). */
  bodyAvailable?: boolean | null;
  pubDate: string;
  sentiment: "POSITIVE" | "NEGATIVE" | "NEUTRAL" | string;
  sentimentScore: number;
  /** Cosine similarity between the article and the cluster summary; null when not computed. */
  similarityToSummary: number | null;
  /** Agreement with every OTHER source (N-1 entries, self excluded). */
  coherenceScores: number[];
}

export interface ScoreBreakdown {
  finalScore: number;
  semanticScore: number;
  avgSimilarity: number;
  domainFactor: number;
  nDomains: number;
  domains?: string[];
  coherenceFactor: number;
  sourceCoherence: number;
}

export interface PipelineTopic {
  topic: string;
  topicName?: string;
  intelligenceSummary: string;
  keywords: string[];
  locations: string[];
  articles: Article[];
  /** null when the exporter could not compute real evidence for this cluster. */
  formulaBreakdown: ScoreBreakdown | null;
}

export interface QualityReport {
  documents: number;
  resolvedDomainShare: number;
  knownSourceShare?: number;
  bodyAvailableShare: number;
  medianBodyChars: number;
  nDomains: number;
  aggregatorRows: number;
}

/** osint_output.json, schema v2 (the loader also upgrades the legacy bare array). */
export interface PipelineExport {
  schemaVersion: number;
  generatedAt: string | null;
  generatedBy: string | null;
  qualityReport: QualityReport | null;
  topics: PipelineTopic[];
}

export interface StressTestCase {
  caseId: string;
  label: string;
  description: string;
  summary: string;
  articles: Article[];
  formulaBreakdown: ScoreBreakdown;
}

export type PipelineMode = "osint" | "stress_test" | "benchmark";

export interface PipelineJobStatus {
  running: boolean;
  id: string | null;
  mode: "stream" | "batch" | null;
  topics: string[];
  startedAt: string | null;
  finishedAt: string | null;
  exitCode: number | null;
  tail: string[];
  allowed: boolean;
}
