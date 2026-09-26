import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

// The frontend polls this endpoint to detect fresh pipeline output
// (e.g. a `python Alex1.py --stream` incremental update) and hot-refresh
// without a manual reload. mtime works for both batch and streaming writes.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const filePath = path.join(process.cwd(), "public", "osint_output.json");
    const stat = await fs.stat(filePath);
    return NextResponse.json({
      version: Math.floor(stat.mtimeMs),
      updatedAt: stat.mtime.toISOString(),
    });
  } catch {
    return NextResponse.json({ version: 0, updatedAt: null });
  }
}
