"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, BarChart3, ExternalLink } from "lucide-react";

interface MethodMetrics {
  method: string;
  pearson_r?: number;
  spearman_rho?: number;
  roc_auc?: number;
  auc_lo?: number;
  auc_hi?: number;
  auc_p?: number;
  mean_true?: number;
  mean_false?: number;
  separation?: number;
  accuracy?: number;
  f1?: number;
  threshold?: number;
}

interface SweepEntry {
  variant: string;
  roc_auc?: number;
  pearson_r?: number;
  f1?: number;
  separation?: number;
  predicted_true?: number;
  predicted_false?: number;
}

interface BenchmarkData {
  success: boolean;
  error?: string;
  generatedAt?: string;
  groundTruth?: {
    source?: string;
    pooled?: { n: number; true: number; false: number };
    evaluation?: { n: number; true: number; false: number };
    calibration?: { n: number; threshold: number };
  };
  methods?: MethodMetrics[];
  splitStability?: Record<string, Record<string, number>>;
  parameterSweep?: Record<string, SweepEntry[]>;
  clusters?: { claim_id: string; verdict: string; n_articles: number; n_domains: number; n_debunk: number; split?: string; claim_text: string; factcheck_url: string }[];
}

const CHOSEN: Record<string, string> = {
  "semantic scale (base/range)": "30/70",
  "top-k sources": "top-3",
  "domain ladder": "current",
  "coherence mapping (base/range)": "0.70/0.30",
  "flag threshold": "75",
};

function fmt(value: number | undefined, digits = 3): string {
  return value === undefined || value === null || Number.isNaN(value) ? "n/a" : value.toFixed(digits);
}

/** Sweep curve drawn inline — no chart dependency, readable in the dark theme. */
function SweepChart({ family, entries }: { family: string; entries: SweepEntry[] }) {
  const width = 300;
  const height = 130;
  const padX = 34;
  const padY = 16;
  const chosen = CHOSEN[family];
  // Mirrors Fig. 3 of the paper: AUC leads because it needs no threshold, and
  // the 0.5 rule marks chance, so a flat curve reads as "this constant does not
  // decide the outcome" rather than as a tuning opportunity.
  const series = [
    { key: "roc_auc" as const, color: "#22d3ee", label: "ROC-AUC" },
    { key: "pearson_r" as const, color: "#34d399", label: "Pearson r" },
  ];
  const values = entries.flatMap((e) => series.map((s) => e[s.key] ?? 0));
  const min = Math.min(0, ...values);
  const max = Math.max(1, ...values);
  const x = (i: number) => padX + (i * (width - padX - 8)) / Math.max(1, entries.length - 1);
  const y = (v: number) => height - padY - ((v - min) / (max - min || 1)) * (height - 2 * padY);

  return (
    <div className="bg-slate-950 border border-slate-900 rounded-lg p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[9.5px] text-slate-300 uppercase tracking-wider">{family}</span>
        <span className="font-mono text-[8px] text-slate-500">chosen: {chosen}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[130px]">
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line x1={padX} y1={y(tick)} x2={width - 8} y2={y(tick)} stroke="#1e293b" strokeWidth="0.5" strokeDasharray="3 3" />
            <text x={padX - 4} y={y(tick) + 3} fill="#64748b" fontSize="7" textAnchor="end" fontFamily="monospace">
              {tick.toFixed(1)}
            </text>
          </g>
        ))}
        {entries.map((entry, i) =>
          entry.variant === chosen ? (
            <line key={`c${i}`} x1={x(i)} y1={padY - 6} x2={x(i)} y2={height - padY} stroke="#f43f5e" strokeWidth="1" opacity="0.55" />
          ) : null,
        )}
        {series.map((s) => (
          <polyline
            key={s.key}
            fill="none"
            stroke={s.color}
            strokeWidth="1.5"
            points={entries.map((e, i) => `${x(i)},${y(e[s.key] ?? 0)}`).join(" ")}
          />
        ))}
        {series.map((s) =>
          entries.map((e, i) => <circle key={`${s.key}${i}`} cx={x(i)} cy={y(e[s.key] ?? 0)} r="2.2" fill={s.color} />),
        )}
        {entries.map((entry, i) => (
          <text key={`l${i}`} x={x(i)} y={height - 3} fill="#64748b" fontSize="6.5" textAnchor="middle" fontFamily="monospace">
            {entry.variant.length > 10 ? entry.variant.slice(0, 9) + "…" : entry.variant}
          </text>
        ))}
      </svg>
      <div className="flex items-center space-x-3 mt-1">
        {series.map((s) => (
          <span key={s.key} className="font-mono text-[8px] flex items-center space-x-1" style={{ color: s.color }}>
            <span className="w-2 h-[2px] inline-block" style={{ background: s.color }} />
            <span>{s.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function BenchmarkPanel() {
  const [data, setData] = useState<BenchmarkData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/benchmark", { cache: "no-store" });
        setData(await res.json());
      } catch (error) {
        setData({ success: false, error: (error as Error).message });
      } finally {
        setLoading(false);
      }
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  if (loading) {
    return (
      <div className="flex-1 min-h-[450px] flex flex-col items-center justify-center bg-slate-900/20 border border-slate-900 rounded-2xl">
        <div className="w-12 h-12 rounded-full border-2 border-cyan-800 border-t-cyan-400 animate-spin mb-4" />
        <p className="font-mono text-[10.5px] text-cyan-500/80 uppercase tracking-widest">Loading benchmark results</p>
      </div>
    );
  }

  if (!data?.success) {
    return (
      <div className="flex-1 min-h-[450px] flex flex-col items-center justify-center p-8 bg-slate-900/20 border border-dashed border-amber-900 rounded-2xl">
        <AlertTriangle className="w-10 h-10 text-amber-500 mb-3" />
        <h3 className="font-display text-sm font-medium text-slate-100">No benchmark results yet</h3>
        <p className="font-sans text-[12px] text-slate-400 text-center max-w-md mt-2 leading-relaxed">{data?.error}</p>
      </div>
    );
  }

  const gt = data.groundTruth;
  const tvs = data.methods?.find((m) => m.method.startsWith("VeriNews"));

  return (
    <div className="flex flex-col space-y-6">
      <div className="bg-slate-900/60 border border-slate-900 rounded-2xl p-5">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-display font-medium text-sm text-slate-100 tracking-tight flex items-center space-x-2">
              <BarChart3 className="w-4 h-4 text-cyan-400" />
              <span>Benchmark against baseline methods</span>
            </h3>
            <p className="font-mono text-[9px] text-slate-500 uppercase tracking-widest mt-0.5">
              pooled: {gt?.pooled?.n ?? "?"} clusters · {gt?.pooled?.true ?? "?"} true /{" "}
              {gt?.pooled?.false ?? "?"} false · reference: {gt?.source ?? "fact-checker verdicts"}
            </p>
          </div>
          {data.generatedAt && (
            <span className="font-mono text-[9px] text-slate-600">{data.generatedAt.replace("T", " ").slice(0, 16)}</span>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-[10px] border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500">
                <th className="py-1.5 px-2 font-medium">Method</th>
                {["AUC", "95% CI", "p", "AUC cal.", "AUC eval."].map((h) => (
                  <th key={h} className="py-1.5 px-2 text-center font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.methods?.map((method) => {
                const ours = method.method.startsWith("VeriNews");
                // An interval straddling 0.5 means the method is indistinguishable
                // from chance here; it is greyed rather than silently ranked.
                const chance = method.auc_lo !== undefined && method.auc_lo <= 0.5 && (method.auc_hi ?? 0) >= 0.5;
                const cal = data.splitStability?.calibration?.[method.method];
                const evalAuc = data.splitStability?.evaluation?.[method.method];
                return (
                  <tr
                    key={method.method}
                    className={`border-b border-slate-900/60 ${ours ? "bg-cyan-950/20 text-cyan-200" : "text-slate-300 hover:bg-slate-900/20"}`}
                  >
                    <td className={`py-1.5 px-2 ${ours ? "font-semibold" : ""}`}>{method.method}</td>
                    <td className={`py-1.5 px-2 text-center ${chance ? "text-slate-500" : ""}`}>{fmt(method.roc_auc)}</td>
                    <td className="py-1.5 px-2 text-center text-slate-400">
                      {method.auc_lo === undefined ? "n/a" : `${fmt(method.auc_lo)}–${fmt(method.auc_hi)}`}
                    </td>
                    <td className={`py-1.5 px-2 text-center ${chance ? "text-slate-500" : "text-emerald-400"}`}>
                      {fmt(method.auc_p)}
                    </td>
                    <td className="py-1.5 px-2 text-center text-slate-400">{fmt(cal, 2)}</td>
                    <td className="py-1.5 px-2 text-center text-slate-400">{fmt(evalAuc, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {tvs && (
          <p className="font-sans text-[11px] text-slate-400 leading-relaxed mt-3 border-t border-slate-900/70 pt-3">
            Mean score on clusters whose claim was rated true: <strong className="text-slate-200">{fmt(tvs.mean_true, 1)}</strong>;
            on clusters whose claim was rated false: <strong className="text-slate-200">{fmt(tvs.mean_false, 1)}</strong>. The score
            measures how well corroborated a narrative is, not whether the underlying claim is true — a false claim whose debunks
            dominate the retrieved coverage is itself well sourced. The two right-hand columns give the AUC on each half of the set
            separately; where they disagree sharply, the split is too small to rank methods, so read the interval, not the order.
          </p>
        )}
      </div>

      {data.parameterSweep && Object.keys(data.parameterSweep).length > 0 && (
        <div className="bg-slate-900/60 border border-slate-900 rounded-2xl p-5">
          <h3 className="font-display font-medium text-sm text-slate-100 tracking-tight mb-1">Parameter sensitivity</h3>
          <p className="font-mono text-[9px] text-slate-500 uppercase tracking-widest mb-3">
            calibration split: {gt?.calibration?.n ?? "?"} clusters · threshold {gt?.calibration?.threshold ?? "?"} · red line = value used in production
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(data.parameterSweep).map(([family, entries]) => (
              <SweepChart key={family} family={family} entries={entries} />
            ))}
          </div>
        </div>
      )}

      {data.clusters && data.clusters.length > 0 && (
        <div className="bg-slate-900/60 border border-slate-900 rounded-2xl p-5">
          <h3 className="font-display font-medium text-sm text-slate-100 tracking-tight mb-3">
            Ground-truth claims <span className="font-mono text-[9px] text-slate-500">({data.clusters.length} scored)</span>
          </h3>
          <div className="space-y-1.5 max-h-[320px] overflow-y-auto pr-1">
            {data.clusters.map((cluster) => (
              <div key={cluster.claim_id} className="bg-slate-950 border border-slate-900/80 rounded-lg p-2.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-[9px] text-slate-500">
                    {cluster.claim_id} · {cluster.split ?? "?"} · {cluster.n_articles} articles · {cluster.n_domains} sources ·{" "}
                    {cluster.n_debunk} debunk-leaning
                  </span>
                  <span
                    className={`font-mono text-[8px] px-1.5 py-0.5 rounded border ${
                      cluster.verdict === "TRUE"
                        ? "text-emerald-400 bg-emerald-950/25 border-emerald-900/50"
                        : "text-red-400 bg-red-950/25 border-red-900/50"
                    }`}
                  >
                    {cluster.verdict}
                  </span>
                </div>
                <p className="font-sans text-[11px] text-slate-300 leading-snug">{cluster.claim_text}</p>
                <a
                  href={cluster.factcheck_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-[9px] text-cyan-400 hover:text-cyan-300 inline-flex items-center space-x-1 mt-1"
                >
                  <span>fact-check</span>
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
