"use client";

import { useState } from "react";
import { Gauge } from "lucide-react";

import { pairwiseAgreement } from "@/lib/evidence";
import { confidenceBand, consensusLabel } from "@/lib/tvs";
import type { Article, ScoreBreakdown } from "@/lib/types";

const TONE_CLASSES: Record<string, string> = {
  high: "text-emerald-400 bg-emerald-950/40 border-emerald-800",
  medium: "text-amber-400 bg-amber-950/40 border-amber-800",
  low: "text-red-400 bg-red-950/40 border-red-800",
};

const STROKE: Record<string, string> = { high: "#10b981", medium: "#f59e0b", low: "#ef4444" };

export function TvsGauge({ tvs, articles }: { tvs: ScoreBreakdown | null; articles: Article[] }) {
  const [expertMode, setExpertMode] = useState(false);
  const band = tvs ? confidenceBand(tvs.finalScore) : null;

  return (
    <div className="md:col-span-5 bg-slate-900/60 border border-slate-900 rounded-2xl p-5 flex flex-col justify-between" id="veracity-breakdown-card">
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-[10px] text-cyan-400 uppercase tracking-widest flex items-center space-x-1.5">
            <Gauge className="w-3.5 h-3.5" />
            <span>Triangulated veracity score</span>
          </span>
          <button
            id="expert-mode-toggle"
            onClick={() => setExpertMode((v) => !v)}
            className={`font-mono text-[9px] px-2.5 py-1 rounded-md transition-all duration-150 flex items-center space-x-1.5 select-none border uppercase tracking-wider ${
              expertMode ? "bg-cyan-950/80 text-cyan-400 border-cyan-700/55" : "bg-slate-950 text-slate-400 border-slate-900 hover:text-slate-200 hover:border-slate-800"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${expertMode ? "bg-cyan-400 animate-pulse" : "bg-slate-500"}`} />
            <span className="font-semibold">Matrix</span>
          </button>
        </div>

        {!tvs ? (
          <div className="bg-slate-950 border border-slate-900 rounded-xl p-4 text-center">
            <p className="font-sans text-xs text-slate-400 leading-relaxed">
              No triangulation evidence was exported for this cluster, so no score is shown.
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-center space-x-3.5 mb-5 bg-slate-950 p-3 rounded-xl border border-slate-900">
              <div className="relative flex items-center justify-center">
                <svg className="w-16 h-16 transform -rotate-90">
                  <circle cx="32" cy="32" r="28" fill="none" stroke="#10172a" strokeWidth="4.5" />
                  <circle
                    cx="32" cy="32" r="28" fill="none"
                    stroke={STROKE[band!.tone]}
                    strokeWidth="5.5"
                    strokeDasharray={2 * Math.PI * 28}
                    strokeDashoffset={2 * Math.PI * 28 * (1 - tvs.finalScore / 100)}
                    className="transition-all duration-1000"
                  />
                </svg>
                <span className="absolute font-mono text-[15px] font-bold text-slate-100 tracking-tight">{tvs.finalScore}</span>
              </div>
              <div>
                <span className="font-mono text-[8px] text-slate-500 uppercase tracking-widest leading-none block mb-0.5">Verification confidence</span>
                <span className="font-display font-semibold text-slate-200 text-sm leading-tight block mb-1">{band!.label}</span>
                <span className={`font-mono text-[9px] border px-2 py-0.5 rounded inline-block ${TONE_CLASSES[band!.tone]}`}>
                  {consensusLabel(tvs.nDomains)} · {tvs.nDomains} source{tvs.nDomains === 1 ? "" : "s"}
                </span>
              </div>
            </div>

            {!expertMode ? (
              <div className="space-y-4">
                <div>
                  <div className="flex items-center justify-between font-mono text-[10.5px] text-slate-400 mb-1">
                    <span>1. Semantic fidelity</span>
                    <span className="text-slate-200 font-semibold">{tvs.semanticScore.toFixed(1)}/100</span>
                  </div>
                  <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden border border-slate-900">
                    <div className="h-full bg-cyan-500 rounded-full" style={{ width: `${tvs.semanticScore}%` }} />
                  </div>
                  <span className="font-mono text-[8px] text-slate-500 tracking-wider uppercase block mt-0.5">
                    Mean top-3 cosine: <strong className="text-slate-300 font-medium">{tvs.avgSimilarity.toFixed(3)}</strong>
                  </span>
                </div>

                <div>
                  <div className="flex items-center justify-between font-mono text-[10.5px] text-slate-400 mb-1">
                    <span>2. Domain diversity</span>
                    <span className="text-slate-200 font-semibold">&times; {tvs.domainFactor.toFixed(2)}</span>
                  </div>
                  <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden border border-slate-900">
                    <div className="h-full bg-teal-500 rounded-full" style={{ width: `${tvs.domainFactor * 100}%` }} />
                  </div>
                  <div className="flex items-center justify-between mt-1 select-none">
                    <span className="font-mono text-[8.5px] text-slate-500 tracking-wider uppercase truncate max-w-[70%]" title={tvs.domains?.join(", ")}>
                      {tvs.domains?.length ? tvs.domains.slice(0, 3).join(", ") + (tvs.domains.length > 3 ? ` +${tvs.domains.length - 3}` : "") : `${tvs.nDomains} domains`}
                    </span>
                    {tvs.domainFactor < 1 && (
                      <span className="font-mono text-[8px] font-bold text-amber-400 bg-amber-950/20 border border-amber-900/40 px-1 rounded">Penalty</span>
                    )}
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between font-mono text-[10.5px] text-slate-400 mb-1">
                    <span>3. Inter-source coherence</span>
                    <span className="text-slate-200 font-semibold">&times; {tvs.coherenceFactor.toFixed(3)}</span>
                  </div>
                  <div className="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden border border-slate-900">
                    <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${((tvs.coherenceFactor - 0.7) / 0.3) * 100}%` }} />
                  </div>
                  <span className="font-mono text-[8.5px] text-slate-500 tracking-wider uppercase block mt-1">
                    Mean pairwise agreement:{" "}
                    <strong className={tvs.sourceCoherence > 0.6 ? "text-emerald-400 font-semibold" : "text-amber-400 font-semibold"}>{tvs.sourceCoherence.toFixed(3)}</strong>
                  </span>
                </div>
              </div>
            ) : (
              <div className="mt-2 border border-slate-900 rounded-xl overflow-hidden bg-slate-950/80 p-3" id="expert-matrix-container">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-[10px] text-cyan-400 uppercase tracking-wider">Agreement matrix M(i,j)</span>
                  <span className="font-mono text-[8px] text-slate-500">factor 3 evidence</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left font-mono text-[9px] border-collapse" id="pairwise-agreement-matrix-table">
                    <thead>
                      <tr className="border-b border-slate-900 text-slate-500">
                        <th className="py-1 px-1.5 font-medium">Source</th>
                        {articles.map((art, idx) => (
                          <th key={idx} className="py-1 px-1.5 text-center font-semibold text-slate-400" title={art.source}>S{idx + 1}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {articles.map((rowArt, rowIdx) => (
                        <tr key={rowIdx} className="border-b border-slate-900/60 hover:bg-slate-900/10 text-slate-300">
                          <td className="py-1.5 px-1 font-medium text-slate-400" title={rowArt.source}>
                            <span className="text-cyan-500 font-bold">S{rowIdx + 1}</span>{" "}
                            <span className="text-slate-500 text-[8px]">({rowArt.source.slice(0, 14)})</span>
                          </td>
                          {articles.map((_, colIdx) => {
                            const agreement = pairwiseAgreement(articles, rowIdx, colIdx);
                            const isSelf = rowIdx === colIdx;
                            return (
                              <td
                                key={colIdx}
                                className={`py-1 px-1.5 text-center font-mono text-[9.5px] ${
                                  isSelf ? "text-slate-600 bg-slate-900/10" : agreement === null ? "text-slate-700" : agreement > 0.75 ? "text-emerald-400 font-semibold" : agreement > 0.5 ? "text-cyan-400" : "text-amber-400"
                                }`}
                              >
                                {isSelf ? "1.000" : agreement === null ? "n/a" : agreement.toFixed(3)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="font-mono text-[7.5px] text-slate-500 mt-2.5 uppercase tracking-wide leading-normal">
                  M(i,j) = cosine similarity between source embeddings; factor 3 is the mean of the upper triangle.
                </p>
              </div>
            )}
          </>
        )}
      </div>

      <p className="font-mono text-[9px] text-slate-600 border-t border-slate-900/60 pt-3 mt-4 leading-normal select-none uppercase tracking-wide">
        Verification-confidence proxy (v3.1), capped 5–99. It measures source consistency, not factual truth.
      </p>
    </div>
  );
}
