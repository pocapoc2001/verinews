"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { PipelineJobStatus } from "@/lib/types";

const IDLE: PipelineJobStatus = {
  running: false, id: null, mode: null, topics: [], startedAt: null, finishedAt: null, exitCode: null, tail: [], allowed: false,
};

/**
 * Starts and follows a real pipeline job (POST /api/pipeline/run) — the
 * "Run live ingestion" feature. Polls the status every `pollMs` while a job
 * runs and calls `onFinished` once, so the caller can refresh the export.
 */
export function usePipelineJob(onFinished?: (status: PipelineJobStatus) => void, pollMs = 3000) {
  const [job, setJob] = useState<PipelineJobStatus>(IDLE);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const finishedIdRef = useRef<string | null>(null);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  const poll = useCallback(async () => {
    try {
      const res = await fetch("/api/pipeline/run", { cache: "no-store" });
      if (!res.ok) return;
      const status = (await res.json()) as PipelineJobStatus;
      setJob(status);
      if (!status.running && status.id && status.exitCode !== null && finishedIdRef.current !== status.id) {
        finishedIdRef.current = status.id;
        onFinishedRef.current?.(status);
      }
    } catch {
      // best-effort
    }
  }, []);

  // Subscribe to the job endpoint: one immediate read (scheduled, so the
  // effect body itself never setStates) plus polling while a job runs.
  useEffect(() => {
    const first = setTimeout(poll, 0);
    const interval = setInterval(poll, job.running ? pollMs : pollMs * 5);
    return () => {
      clearTimeout(first);
      clearInterval(interval);
    };
  }, [job.running, poll, pollMs]);

  const start = useCallback(
    async (topics: string[], mode: "stream" | "batch" = "stream", maxArticles?: number) => {
      setStarting(true);
      setError(null);
      try {
        const res = await fetch("/api/pipeline/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode, topics, maxArticles }),
        });
        const json = await res.json();
        if (!res.ok || !json.success) throw new Error(json.error || `Could not start the job (${res.status}).`);
        // mark the new job as not-yet-finished so onFinished fires for it
        finishedIdRef.current = null;
        await poll();
        return true;
      } catch (e) {
        setError((e as Error).message);
        return false;
      } finally {
        setStarting(false);
      }
    },
    [poll],
  );

  const stop = useCallback(async () => {
    try {
      const res = await fetch("/api/pipeline/run", { method: "DELETE" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error || "Could not stop the job.");
      await poll();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [poll]);

  return { job, starting, error, start, stop, refresh: poll };
}
