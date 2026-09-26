"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { pairwiseAgreement, similarityOf } from "@/lib/evidence";
import type { Article, PipelineTopic } from "@/lib/types";

type VizTab = "cluster" | "fidelity" | "analytics" | "scatter" | "topology";

const TABS: { id: VizTab; label: string; caption: string }[] = [
  { id: "cluster", label: "Cluster", caption: "Sources around the summary centroid (distance = 1 − cosine similarity)" },
  { id: "fidelity", label: "Fidelity", caption: "Per-source fidelity with inter-source agreement links" },
  { id: "analytics", label: "Analytics", caption: "Fidelity distribution and sentiment split of the ingested sources" },
  { id: "scatter", label: "Scatter map", caption: "SBERT embedding projection of the whole corpus (Plotly)" },
  { id: "topology", label: "Dynamic topology", caption: "Cluster frequency over time: macro-trends vs flash events (Plotly)" },
];

function nodeColor(article: Article) {
  if (article.sentiment === "POSITIVE") return { fill: "fill-emerald-400 stroke-emerald-200", line: "stroke-emerald-500" };
  if (article.sentiment === "NEGATIVE") return { fill: "fill-red-400 stroke-red-200", line: "stroke-red-500" };
  return { fill: "fill-indigo-400 stroke-indigo-200", line: "stroke-indigo-500" };
}

export function VizPanel({
  dataset, inspectedIndex, onInspect,
}: {
  dataset: PipelineTopic;
  inspectedIndex: number | null;
  onInspect: (index: number | null) => void;
}) {
  const [tab, setTab] = useState<VizTab>("cluster");
  const articles = dataset.articles;
  const tvs = dataset.formulaBreakdown;
  const caption = TABS.find((t) => t.id === tab)?.caption ?? "";

  return (
    <div className="bg-slate-900/60 border border-slate-900 rounded-2xl p-5 shadow-sm" id="visual-workspace-canvas">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-2 border-b border-slate-900/60">
        <div>
          <h3 className="font-display font-medium text-sm text-slate-100 tracking-tight">Analytical visualization space</h3>
          <p className="font-mono text-[9px] text-slate-500 uppercase tracking-widest">{caption}</p>
        </div>
        <div className="flex flex-wrap bg-slate-950 p-1 border border-slate-900 rounded-lg select-none gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-2 py-1 rounded font-mono text-[10px] uppercase tracking-wider transition duration-150 cursor-pointer ${
                tab === t.id ? "bg-cyan-950/60 border border-cyan-900 text-cyan-400 font-semibold" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative aspect-[16/9] w-full bg-slate-950/80 border border-slate-900 rounded-xl overflow-hidden flex items-center justify-center min-h-[360px]" id="svg-topology-window">
        {tab === "cluster" && (
          <>
            <div className="absolute top-3 left-3 font-mono text-[9px] text-slate-600 uppercase tracking-widest">Orbit distance = semantic distance to the summary</div>
            <svg className="w-full h-full p-4" viewBox="0 0 500 250">
              <g transform="translate(250, 125)">
                <circle cx="0" cy="0" r="10" fill="rgba(6, 182, 212, 0.12)" stroke="rgba(6, 182, 212, 0.6)" strokeWidth="1.5" />
                <circle cx="0" cy="0" r="3" fill="#22d3ee" />
              </g>
              <text x="250" y="108" fill="#22d3ee" className="font-mono text-[8px] tracking-wider uppercase" textAnchor="middle">Summary</text>
              {articles.map((article, index) => {
                const sim = similarityOf(article);
                const angle = (index * 2 * Math.PI) / (articles.length || 1);
                // Unknown similarity parks the node on the outer ring instead of faking a value.
                const r = sim === null ? 135 : Math.max(25, Math.min(130, (1 - sim) * 200 + 40));
                const cx = 250 + Math.cos(angle) * r;
                const cy = 125 + Math.sin(angle) * r;
                const isInspected = inspectedIndex === index;
                const color = nodeColor(article);
                return (
                  <g key={index} className="cursor-pointer group" onClick={() => onInspect(index)}>
                    {isInspected && <circle cx={cx} cy={cy} r="16" fill="none" className="stroke-cyan-400 stroke-[1.5]" />}
                    <circle cx={cx} cy={cy} r={isInspected ? 7 : 5.5} className={`${color.fill} stroke-[1] transition-all`} opacity={sim === null ? 0.45 : 1} />
                    <line x1="250" y1="125" x2={cx} y2={cy} className={`${color.line} stroke-[0.5] opacity-30 group-hover:opacity-75`} strokeDasharray="1 1" />
                    <text x={cx} y={cy - 12} fill="#f1f5f9" className="font-mono text-[7.5px] font-semibold opacity-0 group-hover:opacity-100 transition duration-150" textAnchor="middle">
                      {article.source} ({sim === null ? "n/a" : `${Math.round(sim * 100)}%`})
                    </text>
                  </g>
                );
              })}
            </svg>
          </>
        )}

        {tab === "fidelity" && (
          <svg className="w-full h-full p-4" viewBox="0 0 500 250">
            <g stroke="#1b233a" strokeWidth="0.5">
              <line x1="50" y1="20" x2="50" y2="210" stroke="#1e293b" strokeWidth="1" />
              <line x1="50" y1="210" x2="470" y2="210" stroke="#1e293b" strokeWidth="1" />
              <line x1="50" y1="162.5" x2="470" y2="162.5" strokeDasharray="2 2" />
              <line x1="50" y1="115" x2="470" y2="115" strokeDasharray="2 2" />
              <line x1="50" y1="67.5" x2="470" y2="67.5" strokeDasharray="2 2" />
            </g>
            <text x="45" y="24" fill="#64748b" className="font-mono text-[7px]" textAnchor="end">1.0</text>
            <text x="45" y="118.5" fill="#64748b" className="font-mono text-[7px]" textAnchor="end">0.5</text>
            <text x="45" y="213" fill="#64748b" className="font-mono text-[7px]" textAnchor="end">0.0</text>
            <text x="260" y="224" fill="#64748b" className="font-mono text-[8px] font-semibold" textAnchor="middle">Ingested sources (cosine fidelity to the summary)</text>
            {tvs && (
              <line x1="50" y1={210 - tvs.avgSimilarity * 190} x2="470" y2={210 - tvs.avgSimilarity * 190} stroke="rgba(34, 211, 238, 0.25)" strokeWidth="1.25" strokeDasharray="4 2" />
            )}
            {articles.map((artI, i) =>
              articles.map((artJ, j) => {
                if (j <= i) return null;
                const simI = similarityOf(artI);
                const simJ = similarityOf(artJ);
                const agreement = pairwiseAgreement(articles, i, j);
                if (simI === null || simJ === null || agreement === null) return null;
                const xI = 60 + (i / (articles.length - 1 || 1)) * 380;
                const xJ = 60 + (j / (articles.length - 1 || 1)) * 380;
                const stroke = agreement > 0.85 ? "rgba(16, 185, 129, 0.2)" : agreement < 0.4 ? "rgba(239, 68, 68, 0.2)" : "rgba(148, 163, 184, 0.08)";
                return <line key={`${i}-${j}`} x1={xI} y1={210 - simI * 190} x2={xJ} y2={210 - simJ * 190} stroke={stroke} strokeWidth={agreement > 0.85 || agreement < 0.4 ? 0.75 : 0.5} />;
              }),
            )}
            {articles.map((article, index) => {
              const sim = similarityOf(article);
              const cx = 60 + (index / (articles.length - 1 || 1)) * 380;
              const cy = sim === null ? 215 : 210 - sim * 190;
              const isInspected = inspectedIndex === index;
              return (
                <g key={index} className="cursor-pointer group" onClick={() => onInspect(index)}>
                  {isInspected && <circle cx={cx} cy={cy} r="13" fill="none" className="stroke-cyan-400 stroke-[1.2] opacity-80" />}
                  <circle cx={cx} cy={cy} r={isInspected ? 7 : 5} className={`${nodeColor(article).fill} stroke-[1]`} opacity={sim === null ? 0.4 : 1} />
                  <text x={cx} y={cy - 12} fill="#f1f5f9" className="font-mono text-[7px] font-semibold opacity-0 group-hover:opacity-100 transition" textAnchor="middle">
                    {article.source}: {sim === null ? "n/a" : sim.toFixed(2)}
                  </text>
                </g>
              );
            })}
          </svg>
        )}

        {tab === "analytics" && (
          <div className="w-full h-full p-4 overflow-y-auto text-slate-100 flex flex-col justify-between font-mono text-[10px] space-y-3 absolute inset-0 bg-slate-950/90">
            <div className="grid grid-cols-3 gap-2.5 select-none">
              {[
                { label: "Mean top-3 fidelity", value: tvs ? tvs.avgSimilarity.toFixed(3) : "n/a", tone: "text-cyan-400" },
                { label: "Inter-source coherence", value: tvs ? tvs.sourceCoherence.toFixed(3) : "n/a", tone: "text-emerald-400" },
                { label: "Independent sources", value: tvs ? `${tvs.nDomains}` : "n/a", tone: "text-indigo-400" },
              ].map((kpi) => (
                <div key={kpi.label} className="bg-slate-900/80 border border-slate-900 rounded-lg p-2.5">
                  <span className="text-slate-500 uppercase text-[8px] tracking-wider block">{kpi.label}</span>
                  <strong className={`${kpi.tone} text-base leading-tight mt-1 ml-0.5 block`}>{kpi.value}</strong>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 flex-grow min-h-[170px]">
              <div className="bg-slate-900/40 border border-slate-900 rounded-lg p-2.5 flex flex-col justify-between">
                <div>
                  <span className="text-slate-400 font-bold block text-[9.5px] uppercase">Fidelity per source</span>
                  <span className="text-slate-500 text-[8px] uppercase">Cosine similarity to the cluster summary</span>
                </div>
                <div className="space-y-1.5 mt-2">
                  {articles.slice(0, 5).map((article, idx) => {
                    const sim = similarityOf(article);
                    return (
                      <div key={idx} className="space-y-0.5">
                        <div className="flex justify-between text-[8px] text-slate-400">
                          <span className="truncate max-w-[150px]">{idx + 1}. {article.source}</span>
                          <span>{sim === null ? "n/a" : `${Math.round(sim * 100)}%`}</span>
                        </div>
                        <div className="w-full bg-slate-950 h-2 rounded overflow-hidden border border-slate-900/60 flex">
                          <div className="h-full bg-cyan-500 rounded" style={{ width: `${sim === null ? 0 : Math.round(sim * 100)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="bg-slate-900/40 border border-slate-900 rounded-lg p-2.5 flex flex-col justify-between">
                <div>
                  <span className="text-slate-400 font-bold block text-[9.5px] uppercase">Sentiment split</span>
                  <span className="text-slate-500 text-[8px] uppercase">DistilBERT SST-2 polarity per document</span>
                </div>
                {(() => {
                  const total = articles.length || 1;
                  const pos = articles.filter((a) => a.sentiment === "POSITIVE").length;
                  const neg = articles.filter((a) => a.sentiment === "NEGATIVE").length;
                  const posPct = Math.round((pos / total) * 100);
                  const negPct = Math.round((neg / total) * 100);
                  const neuPct = 100 - posPct - negPct;
                  return (
                    <div className="my-2 space-y-2.5">
                      <div className="w-full bg-slate-950 h-3.5 rounded overflow-hidden flex border border-slate-900">
                        <div className="h-full bg-emerald-500/80" style={{ width: `${posPct}%` }} />
                        <div className="h-full bg-indigo-500/80" style={{ width: `${neuPct}%` }} />
                        <div className="h-full bg-red-500/80" style={{ width: `${negPct}%` }} />
                      </div>
                      <div className="grid grid-cols-3 gap-1 text-[7.5px] text-center font-bold">
                        <div className="bg-emerald-950/20 text-emerald-400 px-1 py-0.5 border border-emerald-900/30 rounded">POS {posPct}%</div>
                        <div className="bg-indigo-950/20 text-indigo-400 px-1 py-0.5 border border-indigo-900/30 rounded">NEU {neuPct}%</div>
                        <div className="bg-red-950/20 text-red-400 px-1 py-0.5 border border-red-900/30 rounded">NEG {negPct}%</div>
                      </div>
                    </div>
                  );
                })()}
                <div className="pt-2 border-t border-slate-900">
                  <span className="text-slate-400 text-[8px] uppercase font-semibold block mb-0.5">Reading</span>
                  <p className="font-sans text-[10px] text-slate-400 leading-normal">
                    {tvs
                      ? `Coherence ${tvs.sourceCoherence.toFixed(3)}: the sources ${tvs.sourceCoherence > 0.6 ? "largely corroborate each other" : "diverge — treat the cluster with care"}.`
                      : "No triangulation evidence was exported for this cluster."}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {(tab === "scatter" || tab === "topology") && (
          <div className="absolute inset-0 w-full h-full bg-slate-950 flex flex-col items-center justify-center">
            <iframe
              src={tab === "scatter" ? "/Viz_Clusters_Scatter.html" : "/Viz_Dissertation_Topology.html"}
              className="w-full h-full border-none"
              title={tab === "scatter" ? "Semantic clusters map" : "Dynamic topic topology"}
              referrerPolicy="no-referrer"
            />
            <div className="absolute bottom-2 right-2 flex items-center space-x-1.5 opacity-40 hover:opacity-100 transition duration-150 z-20">
              <a
                href={tab === "scatter" ? "/Viz_Clusters_Scatter.html" : "/Viz_Dissertation_Topology.html"}
                target="_blank"
                rel="noreferrer"
                className="bg-slate-900/90 border border-slate-800 text-cyan-400 hover:text-cyan-200 font-mono text-[9px] px-2.5 py-1 rounded flex items-center space-x-1 z-20 cursor-pointer"
              >
                <span>Open in new tab</span>
                <ExternalLink className="w-2.5 h-2.5" />
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
