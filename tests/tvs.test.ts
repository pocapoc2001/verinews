import { describe, expect, it } from "vitest";

import fixture from "../lib/fixtures/tvs_stress_test.json";
import { normalizeExport } from "../lib/pipeline-data";
import {
  calculateVeracityScore, clampScore, coherenceFactor, confidenceBand, consensusLabel,
  domainFactor, isAggregator, publisherDomain, registrableDomain, semanticScore, upperTriangleFromRows,
} from "../lib/tvs";

interface FixtureCase {
  caseId: string;
  articles: { source: string; similarityToSummary: number; coherenceScores: number[] }[];
  pairwiseUpperTriangle: number[];
  formulaBreakdown: {
    finalScore: number; semanticScore: number; avgSimilarity: number; domainFactor: number;
    nDomains: number; domains: string[]; coherenceFactor: number; sourceCoherence: number;
  };
}

const cases = (fixture as { cases: FixtureCase[] }).cases;

describe("lib/tvs parity with the Python implementation", () => {
  it.each(cases.map((c) => [c.caseId, c] as const))(
    "reproduces the Python breakdown for cohort %s",
    (_id, testCase) => {
      const result = calculateVeracityScore(
        testCase.articles.map((a) => a.similarityToSummary),
        testCase.articles.map((a) => a.source),
        testCase.pairwiseUpperTriangle,
      );
      const expected = testCase.formulaBreakdown;
      expect(result.finalScore).toBe(expected.finalScore);
      expect(result.nDomains).toBe(expected.nDomains);
      expect(result.domainFactor).toBe(expected.domainFactor);
      expect(result.semanticScore).toBeCloseTo(expected.semanticScore, 1);
      expect(result.avgSimilarity).toBeCloseTo(expected.avgSimilarity, 3);
      expect(result.coherenceFactor).toBeCloseTo(expected.coherenceFactor, 3);
      expect(result.sourceCoherence).toBeCloseTo(expected.sourceCoherence, 3);
      expect(result.domains).toEqual(expected.domains);
    },
  );

  it("rebuilds the upper triangle from the exported per-article rows", () => {
    for (const testCase of cases) {
      const rebuilt = upperTriangleFromRows(testCase.articles.map((a) => a.coherenceScores));
      expect(rebuilt).toHaveLength(testCase.pairwiseUpperTriangle.length);
      rebuilt.forEach((v, i) => expect(v).toBeCloseTo(testCase.pairwiseUpperTriangle[i], 6));
    }
  });

  it("ranks the cohorts coherent > mixed > contradictory", () => {
    const score = (id: string) => cases.find((c) => c.caseId === id)!.formulaBreakdown.finalScore;
    expect(score("A")).toBeGreaterThan(score("C"));
    expect(score("C")).toBeGreaterThan(score("B"));
  });
});

describe("factor helpers", () => {
  it("maps the domain ladder exactly as the Python code", () => {
    expect([6, 5, 4, 3, 2, 1, 0].map(domainFactor)).toEqual([1, 1, 0.95, 0.85, 0.72, 0.6, 0.6]);
  });

  it("maps semantic fidelity from the top-3 similarities", () => {
    const { semanticScore: s, avgSimilarity } = semanticScore([0.9, 0.8, 0.7, 0.1]);
    expect(avgSimilarity).toBeCloseTo(0.8, 6);
    expect(s).toBeCloseTo(86, 6);
    expect(semanticScore([]).semanticScore).toBe(30);
  });

  it("maps coherence to 0.70–1.00 and defaults a single source to 0.5", () => {
    expect(coherenceFactor([1, 1]).coherenceFactor).toBeCloseTo(1, 6);
    expect(coherenceFactor([0, 0]).coherenceFactor).toBeCloseTo(0.7, 6);
    expect(coherenceFactor([]).sourceCoherence).toBe(0.5);
  });

  it("clamps to 5–99 and truncates like int()", () => {
    expect(clampScore(120)).toBe(99);
    expect(clampScore(1)).toBe(5);
    expect(clampScore(84.99)).toBe(84);
  });

  it("never counts aggregator hosts as sources", () => {
    expect(registrableDomain("https://www.reuters.com/x")).toBe("reuters.com");
    expect(publisherDomain("https://news.google.com/rss/articles/A", "https://www.cnbc.com")).toBe("cnbc.com");
    expect(publisherDomain("https://news.google.com/rss/articles/A")).toBe("");
    expect(isAggregator("https://www.msn.com/a")).toBe(true);
    expect(isAggregator("https://www.bbc.co.uk/a")).toBe(false);
  });

  it("labels consensus tiers and confidence bands", () => {
    expect([5, 4, 3, 2, 1].map(consensusLabel)).toEqual(["STRONG", "GOOD", "MODERATE", "WEAK", "SINGLE-SOURCE"]);
    expect(confidenceBand(85).tone).toBe("high");
    expect(confidenceBand(76).tone).toBe("medium");
    expect(confidenceBand(40).tone).toBe("low");
  });
});

describe("export normalization", () => {
  it("accepts the v2 envelope", () => {
    const data = normalizeExport({
      schemaVersion: 2, generatedAt: "2026-09-22T10:00:00", generatedBy: "batch",
      qualityReport: { documents: 39, resolvedDomainShare: 1, bodyAvailableShare: 0.67, medianBodyChars: 3528, nDomains: 25, aggregatorRows: 0 },
      topics: [{ topic: "T", intelligenceSummary: "s", keywords: [], locations: [], articles: [], formulaBreakdown: null }],
    });
    expect(data.schemaVersion).toBe(2);
    expect(data.qualityReport?.nDomains).toBe(25);
    expect(data.topics[0].formulaBreakdown).toBeNull();
  });

  it("upgrades the legacy array and recomputes a missing breakdown from real evidence", () => {
    const testCase = cases[0];
    const data = normalizeExport([
      {
        topic: "Legacy", intelligenceSummary: "s", keywords: [], locations: [],
        articles: testCase.articles.map((a) => ({ ...a, coherenceScores: a.coherenceScores })),
      },
    ]);
    expect(data.schemaVersion).toBe(1);
    expect(data.topics[0].formulaBreakdown?.finalScore).toBe(testCase.formulaBreakdown.finalScore);
  });

  it("leaves the breakdown null when similarities are missing", () => {
    const data = normalizeExport([
      { topic: "T", intelligenceSummary: "s", keywords: [], locations: [], articles: [{ source: "a.com", similarityToSummary: null, coherenceScores: [] }] },
    ]);
    expect(data.topics[0].formulaBreakdown).toBeNull();
  });
});
