import { promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";

// Serves the outputs of experiments/ (parameter sweep + baseline comparison).
// The dashboard never recomputes them: it shows exactly what the committed
// study produced, so the demo and the paper cannot disagree.
export const dynamic = "force-dynamic";

function resultsDir(): string {
  return process.env.VERINEWS_RESULTS_DIR || path.join(process.cwd(), "experiments", "results");
}

export async function GET() {
  try {
    const raw = await fs.readFile(path.join(resultsDir(), "summary.json"), "utf-8");
    return NextResponse.json({ success: true, ...JSON.parse(raw) });
  } catch (error) {
    if ((error as NodeJS.ErrnoException)?.code === "ENOENT") {
      return NextResponse.json(
        {
          success: false,
          error:
            "No benchmark results yet. Run experiments/build_evidence.py, then sweep_parameters.py and evaluate.py.",
        },
        { status: 503 },
      );
    }
    return NextResponse.json({ success: false, error: (error as Error).message }, { status: 500 });
  }
}
