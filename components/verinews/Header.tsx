"use client";

import { BarChart3, Compass, Cpu, Globe } from "lucide-react";

import type { PipelineMode, QualityReport } from "@/lib/types";

interface HeaderProps {
  mode: PipelineMode;
  onModeChange: (mode: PipelineMode) => void;
  status: string;
  quality: QualityReport | null;
  generatedAt: string | null;
  jobRunning: boolean;
}

function qualityTone(q: QualityReport): { label: string; classes: string } {
  const share = q.knownSourceShare ?? q.resolvedDomainShare;
  if (share >= 0.8 && q.bodyAvailableShare >= 0.5) {
    return { label: "Data quality: good", classes: "text-emerald-400 bg-emerald-950/40 border-emerald-900/60" };
  }
  if (share >= 0.5) {
    return { label: "Data quality: partial", classes: "text-amber-400 bg-amber-950/40 border-amber-900/60" };
  }
  return { label: "Data quality: weak", classes: "text-red-400 bg-red-950/40 border-red-900/60" };
}

export function Header({ mode, onModeChange, status, quality, generatedAt, jobRunning }: HeaderProps) {
  const tone = quality ? qualityTone(quality) : null;
  const share = quality ? Math.round(100 * (quality.knownSourceShare ?? quality.resolvedDomainShare)) : null;
  return (
    <header className="border-b border-slate-900 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3" id="brand-logo-container">
          <div className="p-2 bg-gradient-to-tr from-cyan-600 via-teal-500 to-cyan-400 rounded-lg shadow-lg shadow-cyan-900/20 flex items-center justify-center">
            <Compass className="w-5 h-5 text-slate-950 animate-pulse-slow" />
          </div>
          <div>
            <span className="font-display font-semibold tracking-wide text-white text-lg block">VERINEWS</span>
            <span className="font-mono text-[10px] text-cyan-400/80 uppercase tracking-widest block leading-tight">Automated OSINT Lab</span>
          </div>
        </div>

        <div className="hidden md:flex items-center space-x-3">
          <div className="flex items-center space-x-2 bg-slate-900/50 border border-slate-900 rounded-full px-3 py-1 font-mono text-[11px] text-slate-400">
            <span className={`w-2 h-2 rounded-full ${jobRunning ? "bg-amber-400" : "bg-cyan-400"} animate-pulse`} />
            <span>
              Status: <strong className="text-cyan-300">{jobRunning ? "Pipeline job running…" : status}</strong>
            </span>
          </div>
          {tone && quality && (
            <div
              className={`flex items-center space-x-2 border rounded-full px-3 py-1 font-mono text-[10px] ${tone.classes}`}
              title={`${quality.documents} documents · ${share}% identifiable publishers · ${Math.round(100 * quality.bodyAvailableShare)}% full bodies · ${quality.nDomains} distinct sources${generatedAt ? ` · export ${generatedAt.replace("T", " ")}` : ""}`}
            >
              <span>{tone.label}</span>
              <span className="opacity-70">
                {share}% sources · {Math.round(100 * quality.bodyAvailableShare)}% bodies
              </span>
            </div>
          )}
        </div>

        <div className="flex bg-slate-900/80 p-1 border border-slate-800 rounded-lg">
          <button
            id="btn-mode-osint"
            onClick={() => onModeChange("osint")}
            className={`px-3 py-1.5 rounded-md font-display font-medium text-xs transition duration-200 flex items-center space-x-1.5 ${
              mode === "osint" ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/10 font-semibold" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Globe className="w-3.5 h-3.5" />
            <span>OSINT Export</span>
          </button>
          <button
            id="btn-mode-test"
            onClick={() => onModeChange("stress_test")}
            className={`px-3 py-1.5 rounded-md font-display font-medium text-xs transition duration-200 flex items-center space-x-1.5 ${
              mode === "stress_test" ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/10 font-semibold" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>Stress-Test Matrix</span>
          </button>
          <button
            id="btn-mode-benchmark"
            onClick={() => onModeChange("benchmark")}
            className={`px-3 py-1.5 rounded-md font-display font-medium text-xs transition duration-200 flex items-center space-x-1.5 ${
              mode === "benchmark" ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/10 font-semibold" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Benchmark</span>
          </button>
        </div>
      </div>
    </header>
  );
}
