"use client";

import { useCallback, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { BenchmarkPanel } from "@/components/verinews/BenchmarkPanel";
import { Header } from "@/components/verinews/Header";
import { RunPipelinePanel } from "@/components/verinews/RunPipelinePanel";
import { SourcesFeed } from "@/components/verinews/SourcesFeed";
import { SummaryCard } from "@/components/verinews/SummaryCard";
import { TopicSidebar } from "@/components/verinews/TopicSidebar";
import { TvsGauge } from "@/components/verinews/TvsGauge";
import { VizPanel } from "@/components/verinews/VizPanel";
import { usePipelineData } from "@/hooks/use-pipeline-data";
import { usePipelineJob } from "@/hooks/use-pipeline-job";
import { printReport } from "@/lib/report-html";
import type { PipelineTopic } from "@/lib/types";

export default function VeriNewsDashboard() {
  const [inspectedIndex, setInspectedIndex] = useState<number | null>(null);
  const [activeCaseId, setActiveCaseId] = useState("A");

  const [jobRunning, setJobRunning] = useState(false);
  const data = usePipelineData({ jobRunning });
  const onJobFinished = useCallback(() => {
    data.refresh();
  }, [data]);
  const jobs = usePipelineJob(onJobFinished);
  if (jobs.job.running !== jobRunning) setJobRunning(jobs.job.running);

  // The stress-test cohorts are rendered through the same components as a
  // real cluster, so the maths on screen is the maths of the pipeline.
  const activeDataset: PipelineTopic | null = useMemo(() => {
    if (data.mode === "benchmark") return null;
    if (data.mode === "osint") return data.topicData;
    const testCase = data.stressCases.find((tc) => tc.caseId === activeCaseId) ?? data.stressCases[0];
    if (!testCase) return null;
    return {
      topic: testCase.label,
      intelligenceSummary: testCase.summary,
      keywords: ["Federal Reserve", "interest rates", "synthetic cohort"],
      locations: ["Washington"],
      articles: testCase.articles,
      formulaBreakdown: testCase.formulaBreakdown,
    };
  }, [data.mode, data.topicData, data.stressCases, activeCaseId]);

  const selectTopic = (topic: string) => {
    setInspectedIndex(null);
    data.setSelectedTopic(topic);
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col font-sans selection:bg-cyan-500/25 selection:text-cyan-300">
      <Header
        mode={data.mode}
        onModeChange={(mode) => {
          setInspectedIndex(null);
          data.setMode(mode);
        }}
        status={data.status}
        quality={data.meta.qualityReport}
        generatedAt={data.meta.generatedAt}
        jobRunning={jobs.job.running}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col lg:grid lg:grid-cols-12 lg:gap-6">
        <section className={`${data.mode === "benchmark" ? "hidden lg:hidden" : "lg:col-span-3"} flex flex-col space-y-5`} aria-label="Controls">
          {data.mode === "osint" && (
            <RunPipelinePanel job={jobs.job} starting={jobs.starting} error={jobs.error} onStart={jobs.start} onStop={jobs.stop} />
          )}
          <TopicSidebar
            mode={data.mode}
            topics={data.meta.topics}
            selectedTopic={data.selectedTopic}
            onSelectTopic={selectTopic}
            stressCases={data.stressCases}
            activeCaseId={activeCaseId}
            onSelectCase={(id) => {
              setInspectedIndex(null);
              setActiveCaseId(id);
            }}
            loading={data.loading}
            generatedAt={data.meta.generatedAt}
          />
        </section>

        <section
          className={`${data.mode === "benchmark" ? "lg:col-span-12" : "lg:col-span-6"} flex flex-col space-y-6 mt-6 lg:mt-0`}
          aria-label="Analytical workspace"
        >
          {data.mode === "benchmark" && <BenchmarkPanel />}
          <AnimatePresence mode="wait">
            {data.loading ? (
              <motion.div
                key="loader"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex-1 min-h-[450px] flex flex-col items-center justify-center p-8 bg-slate-900/20 border border-slate-900 rounded-2xl"
              >
                <div className="w-12 h-12 rounded-full border-2 border-cyan-800 border-t-cyan-400 animate-spin mb-4" />
                <h3 className="font-display text-sm font-medium text-slate-200">Reading the pipeline export</h3>
                <p className="font-mono text-[10.5px] text-cyan-500/80 uppercase tracking-widest mt-1">{data.status}</p>
              </motion.div>
            ) : data.error ? (
              <motion.div
                key="error"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex-1 min-h-[450px] flex flex-col items-center justify-center p-8 bg-slate-900/20 border border-dashed border-amber-900 rounded-2xl"
              >
                <AlertTriangle className="w-10 h-10 text-amber-500 mb-3" />
                <h3 className="font-display text-sm font-medium text-slate-100">
                  {data.exportMissing ? "No pipeline export yet" : "Could not load this cluster"}
                </h3>
                <p className="font-sans text-[12px] text-slate-400 text-center max-w-md mt-2 leading-relaxed">{data.error}</p>
                <button
                  onClick={() => data.refresh()}
                  className="mt-6 px-4 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-850 rounded-lg text-xs font-display font-medium text-white tracking-wide transition flex items-center space-x-1.5"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry</span>
                </button>
              </motion.div>
            ) : activeDataset ? (
              <motion.div key="dashboard-content" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex flex-col space-y-6">
                <VizPanel dataset={activeDataset} inspectedIndex={inspectedIndex} onInspect={setInspectedIndex} />
                <div className="grid grid-cols-1 md:grid-cols-12 gap-5" id="dossier-veracity-grid">
                  <SummaryCard dataset={activeDataset} onExportPdf={() => printReport(activeDataset, data.meta.generatedAt)} />
                  <TvsGauge tvs={activeDataset.formulaBreakdown} articles={activeDataset.articles} />
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </section>

        <section
          className={`${data.mode === "benchmark" ? "hidden lg:hidden" : "lg:col-span-3"} flex flex-col space-y-5 mt-6 lg:mt-0`}
          aria-label="Ingested sources"
        >
          <SourcesFeed articles={activeDataset?.articles ?? []} inspectedIndex={inspectedIndex} onInspect={setInspectedIndex} />
        </section>
      </main>

      <footer className="border-t border-slate-900 bg-slate-950 py-4 select-none">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row justify-between items-center font-mono text-[10px] text-slate-500">
          <span>&copy; 2026 VeriNews — open-source intelligence verification engine.</span>
          <span className="mt-1.5 sm:mt-0 flex items-center space-x-3 uppercase tracking-wide">
            <span>SBERT &times; K-Means &times; triangulation</span>
            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-ping" />
          </span>
        </div>
      </footer>
    </div>
  );
}
