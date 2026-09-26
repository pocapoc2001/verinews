import { NextRequest, NextResponse } from "next/server";

import { findTopic, loadExport } from "@/lib/pipeline-data";
import type { StressTestCase } from "@/lib/types";
import stressFixture from "@/lib/fixtures/tvs_stress_test.json";

// The dashboard only ever shows what the Python pipeline actually produced.
// There is deliberately no simulator and no LLM "enrichment": a veracity tool
// must never display articles it invented.
export const dynamic = "force-dynamic";

function noExport() {
  return NextResponse.json(
    {
      success: false,
      error: "No pipeline export found. Run `python Alex1.py` (or start a job from the dashboard) to generate public/osint_output.json.",
    },
    { status: 503 },
  );
}

/** GET /api/pipeline — export metadata: topic list, generation time, quality report. */
export async function GET() {
  try {
    const data = await loadExport();
    if (!data) return noExport();
    return NextResponse.json({
      success: true,
      generatedAt: data.generatedAt,
      generatedBy: data.generatedBy,
      schemaVersion: data.schemaVersion,
      qualityReport: data.qualityReport,
      topics: data.topics.map((t) => t.topic),
    });
  } catch (error) {
    return NextResponse.json({ success: false, error: (error as Error).message }, { status: 500 });
  }
}

/** POST /api/pipeline — { mode: "osint", topic } | { mode: "stress_test" } */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const mode = body?.mode === "stress_test" ? "stress_test" : "osint";

    if (mode === "stress_test") {
      const cases = (stressFixture as { cases: StressTestCase[] }).cases;
      return NextResponse.json({
        success: true,
        mode,
        generatedBy: (stressFixture as { generatedBy?: string }).generatedBy ?? null,
        timestamp: new Date().toISOString(),
        testCases: cases,
      });
    }

    const topicQuery = String(body?.topic ?? "").trim();
    if (!topicQuery) {
      return NextResponse.json({ success: false, error: "Missing `topic`." }, { status: 400 });
    }

    const data = await loadExport();
    if (!data) return noExport();

    const topic = findTopic(data, topicQuery);
    if (!topic) {
      return NextResponse.json(
        {
          success: false,
          error: `Topic "${topicQuery}" is not present in the current export. Run a live ingestion for it or pick a listed topic.`,
          availableTopics: data.topics.map((t) => t.topic),
        },
        { status: 404 },
      );
    }

    return NextResponse.json({
      success: true,
      mode: "export",
      generatedAt: data.generatedAt,
      generatedBy: data.generatedBy,
      qualityReport: data.qualityReport,
      timestamp: new Date().toISOString(),
      ...topic,
    });
  } catch (error) {
    // Honest failure: never dress a server fault up as a successful analysis.
    console.error("OSINT pipeline route error", error);
    return NextResponse.json({ success: false, error: (error as Error).message || "Pipeline route error." }, { status: 500 });
  }
}
