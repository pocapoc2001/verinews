"use client";

import { Download, FileText, MapPin } from "lucide-react";

import type { PipelineTopic } from "@/lib/types";

export function SummaryCard({
  dataset, onExportPdf,
}: {
  dataset: PipelineTopic;
  onExportPdf: () => void;
}) {
  const headlineOnly = dataset.articles.filter((a) => a.bodyAvailable === false).length;
  return (
    <div className="md:col-span-7 bg-slate-900/60 border border-slate-900 rounded-2xl p-5 flex flex-col justify-between" id="report-dossier-card">
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-[10px] text-cyan-400 uppercase tracking-widest flex items-center space-x-1">
            <FileText className="w-3.5 h-3.5" />
            <span>Cluster summary</span>
          </span>
          <div className="flex items-center space-x-2">
            <span className="font-mono text-[9.5px] text-slate-500 tracking-wider hidden sm:inline">{dataset.articles.length} sources</span>
            <button
              id="export-pdf-dossier-btn"
              onClick={onExportPdf}
              className="font-mono text-[9px] px-2.5 py-1 rounded-md bg-slate-950 text-slate-400 border border-slate-900 hover:text-cyan-400 hover:border-cyan-800/80 hover:bg-cyan-950/20 transition-all duration-150 flex items-center space-x-1.5 select-none font-semibold cursor-pointer uppercase tracking-wider"
              title="Export this briefing to PDF"
            >
              <Download className="w-3 h-3" />
              <span>Export PDF</span>
            </button>
          </div>
        </div>
        <h4 className="font-display font-medium text-slate-200 text-sm mb-3">{dataset.topic}</h4>
        <div className="border-l-2 border-cyan-800/80 pl-3 py-1 text-slate-300 font-sans text-xs leading-relaxed whitespace-pre-line text-justify" id="summary-text-block">
          {dataset.intelligenceSummary}
        </div>
        {headlineOnly > 0 && (
          <p className="mt-2 font-mono text-[9px] text-amber-400/90 uppercase tracking-wider">
            {headlineOnly} of {dataset.articles.length} sources are headline/snippet only (body not reachable)
          </p>
        )}
      </div>

      <div className="mt-5 pt-4 border-t border-slate-900/80">
        <div className="mb-2">
          <span className="font-mono text-[9px] text-slate-500 uppercase tracking-widest block mb-1.5">Keyphrases (KeyBERT):</span>
          <div className="flex flex-wrap gap-1.5">
            {dataset.keywords.slice(0, 12).map((kw, i) => (
              <span key={i} className="font-sans text-[10px] bg-slate-950 text-slate-300 border border-slate-900 px-2 py-0.5 rounded-full">#{kw}</span>
            ))}
          </div>
        </div>
        <div>
          <span className="font-mono text-[9px] text-slate-500 uppercase tracking-widest block mb-1.5">Locations (NER):</span>
          <div className="flex flex-wrap gap-1.5">
            {dataset.locations.slice(0, 12).map((loc, i) => (
              <span key={i} className="font-sans text-[10px] bg-slate-950 text-cyan-400 border border-cyan-950 px-2 py-0.5 rounded-md flex items-center space-x-1">
                <MapPin className="w-3 h-3 text-cyan-500" />
                <span>{loc}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
