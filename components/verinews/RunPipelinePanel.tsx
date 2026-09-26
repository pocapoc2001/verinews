"use client";

import { useState } from "react";
import { ArrowRight, Play, Square, Terminal } from "lucide-react";

import type { PipelineJobStatus } from "@/lib/types";

interface RunPipelinePanelProps {
  job: PipelineJobStatus;
  starting: boolean;
  error: string | null;
  onStart: (topics: string[], mode: "stream" | "batch", maxArticles?: number) => Promise<boolean>;
  onStop: () => Promise<void>;
}

/**
 * "Run live ingestion": starts a real `python Alex1.py` job for a custom
 * topic (streaming update by default) and shows the log tail. This replaces
 * the old search box that only filtered the static export.
 */
export function RunPipelinePanel({ job, starting, error, onStart, onStop }: RunPipelinePanelProps) {
  const [keyword, setKeyword] = useState("");
  const [mode, setMode] = useState<"stream" | "batch">("stream");
  const [showLog, setShowLog] = useState(false);
  const canRun = job.allowed && !job.running && !starting;
  const stopped = job.exitCode === -15;   // user pressed Stop, not a failure

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const topic = keyword.trim();
    if (!topic) return;
    const ok = await onStart([topic], mode, 15);
    if (ok) setShowLog(true);
  };

  return (
    <div className="bg-slate-900/60 border border-slate-900 rounded-xl p-4 shadow-sm" id="run-pipeline-panel">
      <h3 className="font-display font-medium text-sm text-slate-200 tracking-tight mb-3 flex items-center space-x-2">
        <Play className="w-4 h-4 text-cyan-400" />
        <span>Run live ingestion</span>
      </h3>
      <form onSubmit={submit} className="space-y-2">
        <div className="relative">
          <input
            id="input-custom-keyword"
            type="text"
            placeholder="Topic, e.g. Gold Market Trends"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            disabled={!canRun}
            maxLength={60}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-3 pr-10 py-2 font-sans text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/80 focus:ring-1 focus:ring-cyan-500/20 transition-all disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!canRun || keyword.trim() === ""}
            title="Start the Python pipeline for this topic"
            className="absolute right-1.5 top-1.5 p-1 bg-cyan-950 border border-cyan-800 text-cyan-400 hover:text-cyan-200 rounded-md disabled:opacity-50 transition"
          >
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex bg-slate-950 p-0.5 border border-slate-900 rounded-md">
            {(["stream", "batch"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`px-2 py-0.5 rounded font-mono text-[9px] uppercase tracking-wider transition ${
                  mode === m ? "bg-cyan-950/70 text-cyan-300 border border-cyan-900" : "text-slate-500 hover:text-slate-300"
                }`}
                title={m === "stream" ? "Incremental update via MiniBatchKMeans.partial_fit (needs one batch run first)" : "Full batch run: scrape → NLP → K-Means → summaries → TVS"}
              >
                {m}
              </button>
            ))}
          </div>
          <p className="font-mono text-[9px] text-slate-500 uppercase tracking-wider">
            {job.allowed ? "python Alex1.py -t <topic>" : "localhost only"}
          </p>
        </div>
      </form>

      {(job.running || job.id) && (
        <div className="mt-3 border border-slate-900 bg-slate-950 rounded-lg p-2.5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[9.5px] uppercase tracking-wider flex items-center space-x-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${job.running ? "bg-amber-400 animate-pulse" : job.exitCode === 0 ? "bg-emerald-400" : stopped ? "bg-slate-500" : "bg-red-400"}`} />
              <span className={job.running ? "text-amber-300" : job.exitCode === 0 ? "text-emerald-300" : stopped ? "text-slate-300" : "text-red-300"}>
                {job.running
                  ? `${job.mode} job running`
                  : job.exitCode === 0
                    ? "last job finished"
                    : stopped
                      ? "last job stopped"
                      : `last job failed (${job.exitCode})`}
              </span>
            </span>
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => setShowLog((v) => !v)}
                className="font-mono text-[9px] text-slate-400 hover:text-cyan-300 uppercase tracking-wider flex items-center space-x-1"
              >
                <Terminal className="w-3 h-3" />
                <span>{showLog ? "hide log" : "log"}</span>
              </button>
              {job.running && (
                <button
                  type="button"
                  onClick={onStop}
                  className="font-mono text-[9px] text-red-400 hover:text-red-300 uppercase tracking-wider flex items-center space-x-1"
                >
                  <Square className="w-3 h-3" />
                  <span>stop</span>
                </button>
              )}
            </div>
          </div>
          {job.topics.length > 0 && (
            <p className="font-sans text-[10px] text-slate-400 mt-1 truncate" title={job.topics.join(", ")}>
              {job.topics.join(", ")}
            </p>
          )}
          {showLog && (
            <pre className="mt-2 max-h-40 overflow-y-auto font-mono text-[9px] leading-snug text-slate-400 whitespace-pre-wrap break-words bg-slate-950 border border-slate-900 rounded p-2">
              {job.tail.length ? job.tail.join("\n") : "(waiting for output…)"}
            </pre>
          )}
        </div>
      )}
      {error && <p className="mt-2 font-mono text-[10px] text-red-400 leading-snug">{error}</p>}
    </div>
  );
}
