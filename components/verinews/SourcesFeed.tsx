"use client";

import { AnimatePresence, motion } from "motion/react";
import { BookOpen, Database, ExternalLink } from "lucide-react";
import { useEffect } from "react";

import { formatSimilarity, percentSimilarity } from "@/lib/evidence";
import type { Article } from "@/lib/types";

const SENTIMENT_BADGE: Record<string, { label: string; classes: string }> = {
  POSITIVE: { label: "POSITIVE", classes: "text-emerald-400 bg-emerald-950/25 border-emerald-900/50" },
  NEGATIVE: { label: "NEGATIVE", classes: "text-red-400 bg-red-950/25 border-red-900/50" },
  NEUTRAL: { label: "NEUTRAL", classes: "text-slate-400 bg-slate-950 border-slate-900/80" },
};

export function SourcesFeed({
  articles, inspectedIndex, onInspect,
}: {
  articles: Article[];
  inspectedIndex: number | null;
  onInspect: (index: number | null) => void;
}) {
  useEffect(() => {
    if (inspectedIndex === null) return;
    const timer = setTimeout(() => {
      document.getElementById("source-full-content-inspector")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 150);
    return () => clearTimeout(timer);
  }, [inspectedIndex]);

  const inspected = inspectedIndex !== null ? articles[inspectedIndex] : null;

  return (
    <div className="bg-slate-900/60 border border-slate-900 rounded-xl p-4 flex-1 flex flex-col justify-between" id="scraped-articles-panel">
      <div className="w-full flex-1 flex flex-col">
        <span className="font-mono text-[10px] text-cyan-400 uppercase tracking-widest block mb-2 px-1">
          Ingested sources ({articles.length})
        </span>

        <div className="space-y-2 max-h-[480px] overflow-y-auto pr-1 flex-1" id="sources-infinite-feed">
          {articles.length === 0 && (
            <div className="font-sans text-xs text-slate-500 py-10 text-center">No sources in this cluster.</div>
          )}
          {articles.map((article, index) => {
            const isInspected = inspectedIndex === index;
            const badge = SENTIMENT_BADGE[article.sentiment] ?? SENTIMENT_BADGE.NEUTRAL;
            return (
              <div
                key={index}
                onClick={() => onInspect(isInspected ? null : index)}
                className={`text-left p-3 rounded-xl border cursor-pointer transition-all duration-150 relative overflow-hidden group ${
                  isInspected ? "bg-slate-900 border-slate-700 shadow shadow-cyan-900/20" : "bg-slate-950 border-slate-900/80 hover:bg-slate-900/40 hover:border-slate-800"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-[9px] font-semibold text-slate-200 tracking-wide flex items-center space-x-1">
                    <Database className="w-3 h-3 text-slate-500" />
                    <span className="truncate max-w-[110px]" title={article.publisher || article.source}>{article.source}</span>
                  </span>
                  <span className="font-mono text-[9px] text-slate-500">{article.pubDate}</span>
                </div>

                <h4 className="font-display font-medium text-[11.5px] text-slate-200 line-clamp-2 leading-tight mb-2 group-hover:text-cyan-300">
                  {article.title}
                </h4>

                <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-slate-900/60 select-none">
                  <span className={`font-mono text-[8px] border px-1.5 py-0.5 rounded font-medium ${badge.classes}`}>{badge.label}</span>
                  <div className="flex items-center space-x-1.5">
                    {article.bodyAvailable === false && (
                      <span className="font-mono text-[8px] text-amber-500/90 border border-amber-900/40 bg-amber-950/20 px-1 py-0.5 rounded" title="Article body could not be scraped; only the headline/snippet was ingested">
                        headline only
                      </span>
                    )}
                    <span className="font-mono text-[9px] text-slate-400 bg-slate-950/80 border border-slate-900 px-1 py-0.5 rounded">
                      Fidelity: {percentSimilarity(article)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <AnimatePresence>
        {inspected && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-slate-950 border border-slate-900 rounded-xl p-3.5 mt-4"
            id="source-full-content-inspector"
          >
            <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-slate-900">
              <span className="font-mono text-[9.5px] text-cyan-400 uppercase tracking-widest flex items-center space-x-1">
                <BookOpen className="w-3 h-3 text-cyan-500" />
                <span>Ingested snippet</span>
              </span>
              <button onClick={() => onInspect(null)} className="font-mono text-[9.5px] text-slate-500 hover:text-slate-300 uppercase tracking-wider select-none">
                Close [X]
              </button>
            </div>

            <span className="font-mono text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Source URL:</span>
            <a
              href={inspected.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1 font-mono text-[10px] text-cyan-400 hover:text-cyan-300 underline mb-3 truncate"
            >
              <span className="truncate">{inspected.url}</span>
              <ExternalLink className="w-2.5 h-2.5 flex-shrink-0" />
            </a>

            <p className="font-sans text-[11px] text-slate-300 leading-relaxed text-justify italic bg-slate-900/40 p-2.5 border border-slate-900 rounded-lg">
              &ldquo;{inspected.snippet}&rdquo;
            </p>

            <div className="mt-3 grid grid-cols-2 gap-2 bg-slate-900/20 p-2 rounded-lg border border-slate-900 font-mono text-[9.5px]">
              <div>
                <span className="text-slate-500 block">SBERT cosine match:</span>
                <strong className="text-slate-200">{formatSimilarity(inspected, 4)}</strong>
              </div>
              <div>
                <span className="text-slate-500 block">Sentiment score:</span>
                <strong className={inspected.sentimentScore > 0 ? "text-emerald-400" : inspected.sentimentScore < 0 ? "text-red-400" : "text-slate-400"}>
                  {inspected.sentimentScore.toFixed(3)}
                </strong>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
