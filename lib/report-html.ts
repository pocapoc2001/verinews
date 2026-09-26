// Printable intelligence briefing (Export PDF). Pure function: builds the
// HTML for a topic; `printReport` renders it in a hidden iframe and prints.
import { confidenceBand, consensusLabel } from "./tvs";
import { formatSimilarity } from "./evidence";
import type { PipelineTopic } from "./types";

// Escape untrusted strings (scraped content) before interpolation.
export const escapeHtml = (value: unknown): string =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");

const safeHref = (value: unknown): string => {
  const s = String(value ?? "");
  return /^https?:\/\//i.test(s) ? escapeHtml(s) : "#";
};

export function reportReferenceId(topic: string): string {
  let sum = 0;
  for (let i = 0; i < topic.length; i++) sum += topic.charCodeAt(i);
  return `VNS-${(sum % 100000).toString().padStart(5, "0")}-${topic.substring(0, 3).toUpperCase()}`;
}

export function buildReportHtml(dataset: PipelineTopic, generatedAt?: string | null): string {
  const tvs = dataset.formulaBreakdown;
  const band = tvs ? confidenceBand(tvs.finalScore) : null;
  const statusColor = !tvs ? "#64748b" : band?.tone === "high" ? "#10b981" : band?.tone === "medium" ? "#f59e0b" : "#ef4444";
  const timestamp = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
  const docRefId = reportReferenceId(dataset.topic || "");

  const referenceRows = dataset.articles
    .map((art, idx) => {
      const snippet = art.snippet ? escapeHtml(art.snippet) : "No context snippet available.";
      const bodyNote = art.bodyAvailable === false ? " (headline/snippet only)" : "";
      return `
        <tr style="border-bottom: 1px solid #e2e8f0; page-break-inside: avoid;">
          <td style="padding: 10px 12px; font-weight: bold; color: #0f172a; width: 30px; font-family: 'JetBrains Mono', monospace; font-size: 10px; vertical-align: top;">S${idx + 1}</td>
          <td style="padding: 10px 12px; color: #334155; line-height: 1.4; vertical-align: top;">
            <div style="font-weight: 600; font-size: 11px; color: #0f172a; margin-bottom: 3px;">${escapeHtml(art.title || "Untitled Document")}${bodyNote}</div>
            <div style="font-size: 9px; color: #64748b; font-family: 'JetBrains Mono', monospace; word-break: break-all; margin-bottom: 4px;">
              <a href="${safeHref(art.url)}" target="_blank" style="color: #0284c7; text-decoration: none;">${escapeHtml(art.url || "N/A")}</a>
            </div>
            <div style="font-size: 9.5px; color: #475569; font-style: italic; margin-top: 4px; line-height: 1.4; background: #f8fafc; padding: 6px 10px; border-left: 2px solid #cbd5e1; border-radius: 0 4px 4px 0;">
              &ldquo;${snippet.length > 200 ? snippet.substring(0, 197) + "..." : snippet}&rdquo;
            </div>
          </td>
          <td style="padding: 10px 12px; font-weight: 600; color: #1e293b; white-space: nowrap; font-size: 10px; vertical-align: top;">${escapeHtml(art.publisher || art.source || "Unknown source")}</td>
          <td style="padding: 10px 12px; color: #64748b; white-space: nowrap; font-family: 'JetBrains Mono', monospace; font-size: 9px; vertical-align: top;">${escapeHtml(art.pubDate || "N/A")}</td>
          <td style="padding: 10px 12px; text-align: center; font-weight: bold; color: #0284c7; font-family: 'JetBrains Mono', monospace; font-size: 10px; vertical-align: top;">${formatSimilarity(art)}</td>
        </tr>`;
    })
    .join("");

  const domains = tvs?.domains?.length ? tvs.domains.map((d) => `<span class="tag-badge">${escapeHtml(d)}</span>`).join("") : "";

  return `<!DOCTYPE html>
<html>
<head>
  <title>VeriNews OSINT Intelligence Briefing - ${escapeHtml(dataset.topic)}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
    @page { size: A4; margin: 18mm; }
    body { font-family: 'Inter', system-ui, -apple-system, sans-serif; color: #1e293b; background: #fff; line-height: 1.5; font-size: 11px; margin: 0; padding: 0; }
    .confidential-header { text-align: center; border-bottom: 2px solid #0f172a; padding-bottom: 10px; margin-bottom: 20px; }
    .confidential-badge { display: inline-block; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 9px; letter-spacing: .15em; color: #0369a1; border: 1.5px solid #0369a1; padding: 3px 12px; margin-bottom: 6px; text-transform: uppercase; border-radius: 2px; }
    .header-title { font-family: 'Space Grotesk', sans-serif; font-size: 18px; font-weight: 700; letter-spacing: -.02em; color: #0f172a; margin: 0 0 3px; text-transform: uppercase; }
    .header-subtitle { font-family: 'JetBrains Mono', monospace; font-size: 8px; color: #64748b; letter-spacing: .08em; margin: 0; text-transform: uppercase; }
    .meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 14px; margin-bottom: 20px; }
    .meta-item { display: flex; flex-direction: column; }
    .meta-label { font-family: 'JetBrains Mono', monospace; font-size: 7.5px; text-transform: uppercase; color: #64748b; letter-spacing: .05em; margin-bottom: 1px; }
    .meta-value { font-size: 11px; font-weight: 600; color: #0f172a; }
    .meta-value-mono { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #334155; }
    .section-title { font-family: 'Space Grotesk', sans-serif; font-size: 12px; font-weight: 700; color: #0f172a; border-bottom: 1.5px solid #0f172a; padding-bottom: 3px; margin: 24px 0 10px; text-transform: uppercase; display: flex; justify-content: space-between; align-items: center; }
    .section-tag { font-family: 'JetBrains Mono', monospace; font-size: 8px; color: #64748b; font-weight: normal; }
    .summary-card { font-size: 11px; line-height: 1.55; color: #334155; text-align: justify; background: #fdfdfd; border-left: 3px solid #0284c7; padding: 2px 0 2px 14px; margin-bottom: 20px; }
    .veracity-assessment-box { display: flex; align-items: center; gap: 20px; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px 16px; background: #f8fafc; margin-bottom: 20px; }
    .veracity-large-score { display: flex; flex-direction: column; align-items: center; justify-content: center; border-right: 1px solid #cbd5e1; padding-right: 20px; min-width: 90px; }
    .large-score-num { font-family: 'Space Grotesk', sans-serif; font-size: 36px; font-weight: 700; line-height: 1; color: ${statusColor}; }
    .large-score-label { font-family: 'JetBrains Mono', monospace; font-size: 7.5px; font-weight: bold; text-transform: uppercase; letter-spacing: .05em; color: ${statusColor}; margin-top: 4px; text-align: center; max-width: 110px; }
    .veracity-details-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; flex-grow: 1; }
    .veracity-detail-card { display: flex; flex-direction: column; text-align: center; }
    .veracity-factor-val { font-family: 'Space Grotesk', sans-serif; font-size: 14px; font-weight: 700; color: #0f172a; }
    .veracity-factor-title { font-family: 'JetBrains Mono', monospace; font-size: 7.5px; text-transform: uppercase; color: #64748b; margin-top: 3px; letter-spacing: .02em; }
    .badge-container { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
    .tag-badge { font-size: 9px; background: #f1f5f9; border: 1px solid #cbd5e1; color: #334155; padding: 3px 6px; border-radius: 4px; font-weight: 500; font-family: 'JetBrains Mono', monospace; }
    .tag-badge-geo { font-size: 9px; background: #ecfeff; border: 1px solid #a5f3fc; color: #0369a1; padding: 3px 6px; border-radius: 4px; font-weight: 500; font-family: 'Space Grotesk', sans-serif; }
    .caveat { font-size: 9.5px; color: #475569; background: #fffbeb; border: 1px solid #fde68a; border-radius: 4px; padding: 8px 10px; margin-bottom: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 9.5px; }
    th { background: #f1f5f9; color: #0f172a; font-family: 'Space Grotesk', sans-serif; font-weight: 700; text-transform: uppercase; font-size: 8px; letter-spacing: .05em; border-bottom: 2px solid #94a3b8; padding: 8px 10px; text-align: left; }
    .footer-notes { margin-top: 40px; padding-top: 14px; border-top: 1px dashed #cbd5e1; text-align: center; font-family: 'JetBrains Mono', monospace; font-size: 7px; color: #94a3b8; text-transform: uppercase; letter-spacing: .06em; line-height: 1.5; }
    @media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
  </style>
</head>
<body>
  <div class="confidential-header">
    <div class="confidential-badge">OSINT narrative briefing</div>
    <h1 class="header-title">VeriNews Intelligence Briefing</h1>
    <h2 class="header-subtitle">Similar-news cluster // triangulated veracity score</h2>
  </div>

  <div class="meta-grid">
    <div class="meta-item"><span class="meta-label">Subject cluster</span><span class="meta-value" style="color:#0284c7;">${escapeHtml(dataset.topic)}</span></div>
    <div class="meta-item"><span class="meta-label">Reference ID</span><span class="meta-value-mono">${escapeHtml(docRefId)}</span></div>
    <div class="meta-item"><span class="meta-label">Report generated</span><span class="meta-value-mono">${timestamp}</span></div>
    <div class="meta-item"><span class="meta-label">Pipeline export</span><span class="meta-value-mono">${escapeHtml(generatedAt ? String(generatedAt).replace("T", " ") : "n/a")} · SBERT all-mpnet-base-v2 · TVS v3.1</span></div>
  </div>

  <div class="section-title"><span>I. Cluster summary</span><span class="section-tag">abstractive / extractive synthesis of the sources</span></div>
  <div class="summary-card">${escapeHtml(dataset.intelligenceSummary)}</div>

  <div class="section-title"><span>II. Triangulated veracity score</span><span class="section-tag">verification-confidence proxy</span></div>
  ${
    tvs
      ? `<div class="veracity-assessment-box">
    <div class="veracity-large-score"><span class="large-score-num">${tvs.finalScore}</span><span class="large-score-label">${escapeHtml(band?.label ?? "")}</span></div>
    <div class="veracity-details-grid">
      <div class="veracity-detail-card"><span class="veracity-factor-val">${tvs.semanticScore.toFixed(1)}/100</span><span class="veracity-factor-title">Semantic fidelity (top-3 cos ${tvs.avgSimilarity.toFixed(3)})</span></div>
      <div class="veracity-detail-card"><span class="veracity-factor-val">&times; ${tvs.domainFactor.toFixed(2)}</span><span class="veracity-factor-title">${tvs.nDomains} independent sources (${consensusLabel(tvs.nDomains)})</span></div>
      <div class="veracity-detail-card"><span class="veracity-factor-val">&times; ${tvs.coherenceFactor.toFixed(3)}</span><span class="veracity-factor-title">Inter-source coherence (${tvs.sourceCoherence.toFixed(3)})</span></div>
    </div>
  </div>
  ${domains ? `<div class="badge-container">${domains}</div>` : ""}`
      : `<div class="caveat">No triangulation evidence was exported for this cluster.</div>`
  }
  <div class="caveat">The TVS is an automated proxy for narrative consistency and verification confidence, not a fact-checking verdict: a high score means the summary is faithful to several mutually consistent, independent sources. Coordinated or systematically repeated misinformation across sources could still score high.</div>

  <div style="display:grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-top: 15px;">
    <div><div style="font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:9.5px; text-transform:uppercase; color:#0f172a; margin-bottom:6px;">Keyphrases</div>
      <div class="badge-container">${dataset.keywords.map((kw) => `<span class="tag-badge">#${escapeHtml(kw)}</span>`).join("")}</div></div>
    <div><div style="font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:9.5px; text-transform:uppercase; color:#0f172a; margin-bottom:6px;">Locations (NER)</div>
      <div class="badge-container">${dataset.locations.map((loc) => `<span class="tag-badge-geo">${escapeHtml(loc)}</span>`).join("")}</div></div>
  </div>

  <div style="page-break-before: always;"></div>
  <div class="section-title" style="margin-top:5px;"><span>III. Source ledger</span><span class="section-tag">${dataset.articles.length} ingested documents</span></div>
  <table>
    <thead><tr><th style="width:30px; text-align:center;">Ref</th><th>Document &amp; ingested snippet</th><th>Publisher</th><th>Date</th><th style="text-align:center; width:68px;">Cosine fidelity</th></tr></thead>
    <tbody>${referenceRows}</tbody>
  </table>

  <div class="footer-notes">*** End of briefing ${escapeHtml(docRefId)} *** Generated by the VeriNews Engine v4.1 from the pipeline export; all figures are computed from the listed sources.</div>
</body>
</html>`;
}

/** Renders the report in a hidden iframe and opens the print dialog. */
export function printReport(dataset: PipelineTopic, generatedAt?: string | null) {
  const iframe = document.createElement("iframe");
  iframe.style.position = "absolute";
  iframe.style.width = "0px";
  iframe.style.height = "0px";
  iframe.style.border = "none";
  document.body.appendChild(iframe);
  const doc = iframe.contentWindow?.document || iframe.contentDocument;
  if (!doc) return;
  doc.open();
  doc.write(buildReportHtml(dataset, generatedAt));
  doc.close();
  setTimeout(() => {
    iframe.contentWindow?.focus();
    iframe.contentWindow?.print();
    setTimeout(() => document.body.removeChild(iframe), 5000);
  }, 500);
}
