"use client";

import { BookOpen, Layers } from "lucide-react";

import type { PipelineMode, StressTestCase } from "@/lib/types";

interface TopicSidebarProps {
  mode: PipelineMode;
  topics: string[];
  selectedTopic: string | null;
  onSelectTopic: (topic: string) => void;
  stressCases: StressTestCase[];
  activeCaseId: string;
  onSelectCase: (id: string) => void;
  loading: boolean;
  generatedAt: string | null;
}

const CASE_STYLE: Record<string, { badge: string; color: string }> = {
  A: { badge: "Coherent", color: "text-emerald-400" },
  B: { badge: "Contradicting", color: "text-red-400" },
  C: { badge: "Mixed", color: "text-amber-400" },
};

export function TopicSidebar({
  mode, topics, selectedTopic, onSelectTopic, stressCases, activeCaseId, onSelectCase, loading, generatedAt,
}: TopicSidebarProps) {
  return (
    <>
      {mode === "osint" ? (
        <div className="bg-slate-900/60 border border-slate-900 rounded-xl p-4 shadow-sm" id="topic-list-panel">
          <div className="flex items-center justify-between mb-2.5">
            <span className="font-mono text-[10.5px] text-slate-500 uppercase tracking-widest">Export clusters</span>
            {generatedAt && (
              <span className="font-mono text-[9px] text-slate-600" title="Export generated at">
                {generatedAt.replace("T", " ").slice(0, 16)}
              </span>
            )}
          </div>
          <div className="space-y-1">
            {topics.length === 0 && (
              <p className="font-sans text-[11px] text-slate-500 leading-relaxed">
                No export yet. Run <code className="font-mono text-[10px] bg-slate-950 px-1 rounded text-slate-300">python Alex1.py</code> or start a job above.
              </p>
            )}
            {topics.map((topic) => {
              const isActive = selectedTopic === topic;
              return (
                <button
                  key={topic}
                  onClick={() => onSelectTopic(topic)}
                  disabled={loading}
                  className={`w-full text-left px-2.5 py-1.5 rounded-lg font-sans text-xs transition duration-150 flex items-center justify-between ${
                    isActive ? "bg-slate-900 border border-slate-850 text-cyan-400 font-semibold" : "text-slate-400 hover:bg-slate-900/40 hover:text-slate-200"
                  }`}
                >
                  <span className="truncate">{topic}</span>
                  {isActive && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />}
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="bg-slate-900/60 border border-slate-900 rounded-xl p-4 shadow-sm" id="stress-test-selector">
          <h3 className="font-display font-medium text-sm text-slate-200 tracking-tight mb-3 flex items-center space-x-2">
            <Layers className="w-4 h-4 text-cyan-400" />
            <span>Synthetic cohorts</span>
          </h3>
          <p className="font-sans text-xs text-slate-400 leading-relaxed mb-4">
            Three controlled clusters about the same Fed decision, five outlets each, so only the coherence of the sources varies. Scores are computed by the Python engine with the real SBERT model.
          </p>
          <div className="space-y-1.5">
            {stressCases.map((tc) => {
              const isActive = activeCaseId === tc.caseId;
              const style = CASE_STYLE[tc.caseId] ?? { badge: "Case", color: "text-slate-400" };
              return (
                <button
                  key={tc.caseId}
                  onClick={() => onSelectCase(tc.caseId)}
                  className={`w-full text-left p-2.5 rounded-lg border transition duration-150 ${
                    isActive ? "bg-slate-900 border-slate-800 text-white shadow-sm" : "border-transparent text-slate-400 hover:bg-slate-900/40 hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-[10px] text-slate-500 uppercase tracking-widest">Case {tc.caseId} · {tc.formulaBreakdown.finalScore}/99</span>
                    <span className={`font-mono text-[9px] uppercase tracking-wider font-semibold rounded px-1.5 py-0.5 bg-slate-950 ${style.color}`}>{style.badge}</span>
                  </div>
                  <span className="font-display text-xs font-medium block truncate">{tc.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="bg-slate-900/30 border border-slate-900/50 rounded-xl p-4" id="academic-note">
        <h4 className="font-mono text-[10.5px] text-slate-400 uppercase tracking-widest mb-2 flex items-center space-x-1.5">
          <BookOpen className="w-3.5 h-3.5 text-slate-500" />
          <span>How the score works</span>
        </h4>
        <div className="font-sans text-[11px] text-slate-400 space-y-2 leading-relaxed">
          <p>
            The <strong className="text-slate-300 font-medium">Triangulated Veracity Score</strong> is a verification-confidence proxy: it multiplies how faithful the summary is to its sources, how many independent outlets carry the story, and how much those outlets agree with each other.
          </p>
          <div className="p-2 border border-slate-900 bg-slate-950 rounded font-mono text-[10px] text-slate-400/90 leading-normal">
            V = clamp(S<sub>sem</sub> &times; F<sub>dom</sub> &times; F<sub>coh</sub>, 5, 99)
          </div>
          <p className="text-[10px] text-slate-500">It is not a fact-check: consistent repetition across outlets can still score high.</p>
        </div>
      </div>
    </>
  );
}
