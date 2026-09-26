import { spawn } from "child_process";
import { promises as fs, openSync, closeSync, existsSync } from "fs";
import path from "path";
import { NextRequest, NextResponse } from "next/server";

import type { PipelineJobStatus } from "@/lib/types";

// Starts / inspects a real pipeline job (python Alex1.py [--stream] -t ...).
// Only one job runs at a time; its log is streamed to runs/<id>.log so the
// dashboard can show progress and hot-refresh when the export changes.
//
// Safety: spawning a process from an HTTP request is only allowed from the
// machine that runs the dashboard (localhost) unless VERINEWS_ALLOW_RUN=1.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const RUNS_DIR = path.join(process.cwd(), "runs");
const LOCK_FILE = path.join(RUNS_DIR, "current.json");
const TOPIC_RE = /^[\w .,'&()\-]{2,60}$/;
const MAX_TOPICS = 10;

interface JobRecord {
  id: string;
  pid: number;
  mode: "stream" | "batch";
  topics: string[];
  maxArticles: number | null;
  startedAt: string;
  finishedAt: string | null;
  exitCode: number | null;
  stoppedByUser?: boolean;
  logPath: string;
}

const STOPPED_EXIT_CODE = -15;

function pythonExecutable(): string {
  if (process.env.VERINEWS_PYTHON) return process.env.VERINEWS_PYTHON;
  return process.platform === "win32"
    ? path.join(process.cwd(), ".venv", "Scripts", "python.exe")
    : path.join(process.cwd(), ".venv", "bin", "python");
}

function isLocalRequest(req: NextRequest): boolean {
  if (process.env.VERINEWS_ALLOW_RUN === "1") return true;
  const host = (req.headers.get("host") || "").toLowerCase();
  return /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host);
}

function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function readLock(): Promise<JobRecord | null> {
  try {
    return JSON.parse(await fs.readFile(LOCK_FILE, "utf-8")) as JobRecord;
  } catch {
    return null;
  }
}

async function writeLock(record: JobRecord | null) {
  await fs.mkdir(RUNS_DIR, { recursive: true });
  if (record) await fs.writeFile(LOCK_FILE, JSON.stringify(record, null, 2), "utf-8");
  else await fs.rm(LOCK_FILE, { force: true });
}

async function logTail(logPath: string, lines = 40): Promise<string[]> {
  try {
    const text = await fs.readFile(logPath, "utf-8");
    return text
      .split(/\r?\n/)
      .map((l) => l.replace(/\r/g, "").trimEnd())
      .filter((l) => l.trim() && !/it\/s\]|s\/it\]|RuntimeWarning|with DDGS|ddgs = DDGS/.test(l))
      .slice(-lines);
  } catch {
    return [];
  }
}

async function currentStatus(allowed: boolean): Promise<PipelineJobStatus> {
  const record = await readLock();
  if (!record) {
    return { running: false, id: null, mode: null, topics: [], startedAt: null, finishedAt: null, exitCode: null, tail: [], allowed };
  }
  let { exitCode, finishedAt } = record;
  const alive = processAlive(record.pid);
  // If the dev server restarted we lost the 'exit' event: infer the outcome.
  if (!alive && exitCode === null) {
    const tail = await logTail(record.logPath, 200);
    exitCode = record.stoppedByUser
      ? STOPPED_EXIT_CODE
      : tail.some((l) => /SYSTEM COMPLETE|\[STREAM\] Complete|No new articles found/.test(l))
        ? 0
        : -1;
    finishedAt = new Date().toISOString();
    await writeLock({ ...record, exitCode, finishedAt });
  }
  return {
    running: alive && exitCode === null,
    id: record.id,
    mode: record.mode,
    topics: record.topics,
    startedAt: record.startedAt,
    finishedAt,
    exitCode,
    tail: await logTail(record.logPath),
    allowed,
  };
}

/** GET /api/pipeline/run — status of the current/last job. */
export async function GET(req: NextRequest) {
  return NextResponse.json(await currentStatus(isLocalRequest(req)));
}

/** POST /api/pipeline/run — { mode: "stream" | "batch", topics?: string[], maxArticles?: number } */
export async function POST(req: NextRequest) {
  if (!isLocalRequest(req)) {
    return NextResponse.json({ success: false, error: "Pipeline jobs can only be started from localhost (or set VERINEWS_ALLOW_RUN=1)." }, { status: 403 });
  }
  const body = await req.json().catch(() => ({}));
  const mode: "stream" | "batch" = body?.mode === "batch" ? "batch" : "stream";
  const topics: string[] = Array.isArray(body?.topics) ? body.topics.map((t: unknown) => String(t).trim()).filter(Boolean) : [];
  if (topics.length > MAX_TOPICS || topics.some((t) => !TOPIC_RE.test(t))) {
    return NextResponse.json({ success: false, error: `Topics must match ${TOPIC_RE} (max ${MAX_TOPICS}).` }, { status: 400 });
  }
  const maxArticles = Number.isInteger(body?.maxArticles) && body.maxArticles > 0 && body.maxArticles <= 50 ? body.maxArticles : null;

  const status = await currentStatus(true);
  if (status.running) {
    return NextResponse.json({ success: false, error: `A ${status.mode} job is already running (${status.id}).`, status }, { status: 409 });
  }

  const python = pythonExecutable();
  if (!existsSync(python)) {
    return NextResponse.json({ success: false, error: `Python interpreter not found: ${python} (set VERINEWS_PYTHON).` }, { status: 500 });
  }

  const id = `${mode}-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  await fs.mkdir(RUNS_DIR, { recursive: true });
  const logPath = path.join(RUNS_DIR, `${id}.log`);
  const args = ["Alex1.py", "--no-stress-test"];
  if (mode === "stream") args.push("--stream");
  for (const t of topics) args.push("-t", t);
  if (maxArticles) args.push("--max-articles", String(maxArticles));

  const logFd = openSync(logPath, "a");
  const child = spawn(python, args, {
    cwd: process.cwd(),
    detached: true,
    stdio: ["ignore", logFd, logFd],
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    windowsHide: true,
  });
  closeSync(logFd);

  const record: JobRecord = {
    id, pid: child.pid ?? -1, mode, topics, maxArticles,
    startedAt: new Date().toISOString(), finishedAt: null, exitCode: null, logPath,
  };
  await writeLock(record);

  child.on("exit", async (code) => {
    // Re-read the lock: a DELETE may have marked this job as stopped by the
    // user, and that must not be reported as a failure.
    const latest = await readLock().catch(() => null);
    const stoppedByUser = latest?.id === record.id && latest?.stoppedByUser === true;
    await writeLock({
      ...record,
      stoppedByUser,
      exitCode: stoppedByUser ? STOPPED_EXIT_CODE : code ?? -1,
      finishedAt: new Date().toISOString(),
    }).catch(() => undefined);
  });
  child.unref();

  return NextResponse.json({ success: true, job: { id, mode, topics, maxArticles, startedAt: record.startedAt } });
}

/** DELETE /api/pipeline/run — stop the running job. */
export async function DELETE(req: NextRequest) {
  if (!isLocalRequest(req)) {
    return NextResponse.json({ success: false, error: "Forbidden." }, { status: 403 });
  }
  const record = await readLock();
  if (!record || !processAlive(record.pid)) {
    return NextResponse.json({ success: false, error: "No running job." }, { status: 404 });
  }
  // Flag first: the child's exit handler reads this back so a deliberate stop
  // is never displayed as a crash.
  await writeLock({ ...record, stoppedByUser: true });
  try {
    process.kill(record.pid);
  } catch (error) {
    return NextResponse.json({ success: false, error: (error as Error).message }, { status: 500 });
  }
  await writeLock({ ...record, stoppedByUser: true, exitCode: STOPPED_EXIT_CODE, finishedAt: new Date().toISOString() });
  return NextResponse.json({ success: true });
}
