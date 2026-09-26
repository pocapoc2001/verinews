"""
VeriNews Streaming Topic Model (v4.0)
=====================================

Incremental online-learning extension for the batch pipeline in Alex1.py.

Usage
-----
    python Alex1.py             -> classic full batch run (unchanged)
    python Alex1.py --stream    -> incremental update via MiniBatchKMeans.partial_fit

Design
------
* Cold start: the persisted state is bootstrapped from the master corpus
  (stream_corpus.csv, or Dataset_Dissertation_Final.xlsx on the very first
  run). A deterministic KMeans solves the initial geometry, then its
  centroids warm-start a MiniBatchKMeans so cluster IDs stay stable across
  every subsequent partial_fit call.
* Embeddings are L2-normalized before clustering so Euclidean K-Means
  approximates the cosine geometry the TVS formula already assumes.
* c-TF-IDF topic labels are maintained incrementally: a frozen-vocabulary
  CountVectorizer transforms only the NEW documents and their counts are
  accumulated into a per-cluster sparse matrix (same weighting formula as
  step_3_dynamic_topics in Alex1.py).
* Drift monitor: the mean centroid distance of newly assigned points is
  tracked against the cold-start baseline. Sustained excess triggers a full
  re-fit whose cluster IDs are re-mapped onto the previous model's IDs via
  Hungarian assignment on centroid cosine similarity, so dashboard topic
  identities survive re-clustering.
* osint_output.json is rewritten atomically (temp file + os.replace) with
  REAL per-article similarities/coherence; the Next.js frontend polls
  /api/pipeline/version and hot-refreshes when the file changes.
"""

import os
import sys
import time

import numpy as np
import pandas as pd
import joblib
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.preprocessing import normalize

from verinews_common import (
    OSINT_EXPORT_FILENAME, atomic_write_json, build_stop_words, build_topic_label,
    corpus_quality_report, export_envelope, publisher_domain, resolve_public_dir,
)

STATE_DIR = "model_state"
STATE_PATH = os.path.join(STATE_DIR, "streaming_state.joblib")
CORPUS_PATH = "stream_corpus.csv"
DRIFT_WINDOW = 200   # newest point-to-centroid distances kept for drift stats
DRIFT_RATIO = 1.5    # refit trigger: recent mean distance vs cold-start baseline

class StreamingTopicModel:
    """MiniBatchKMeans-based online topic model with stable public cluster IDs."""

    def __init__(self, n_clusters, random_state=42):
        self.n_clusters = int(n_clusters)
        self.random_state = random_state
        self.kmeans = None
        self.vectorizer = None            # frozen vocabulary after cold start
        self.cluster_term_counts = None   # sparse (k, |vocab|), public-ID rows
        self.id_alias = {}                # raw kmeans label -> stable public ID
        self.version = 0
        self.baseline_distance = None
        self.recent_distances = []
        self.updated_at = None
        self.publisher_domains = set()   # feeds the stop-word list at cold start

    # ---------------- geometry helpers ----------------
    @staticmethod
    def _normalize(embeddings):
        return normalize(np.asarray(embeddings, dtype=np.float64))

    def _stop_words(self):
        # Same vocabulary hygiene as the batch pipeline (verinews_common)
        return build_stop_words(self.publisher_domains)

    def public_labels(self, raw_labels):
        """Maps raw estimator labels to stable, dashboard-facing topic IDs."""
        return np.array([self.id_alias.get(int(l), int(l)) for l in raw_labels])

    def _aggregate_counts(self, labels, counts):
        """Sums term counts per cluster: indicator (k, n) @ counts (n, |V|)."""
        k = self.n_clusters
        n = counts.shape[0]
        indicator = sparse.csr_matrix(
            (np.ones(n), (np.asarray(labels), np.arange(n))), shape=(k, n)
        )
        return sparse.csr_matrix(indicator @ counts)

    # ---------------- lifecycle ----------------
    def cold_start(self, docs, embeddings):
        """Fits the initial geometry and freezes the c-TF-IDF vocabulary."""
        X = self._normalize(embeddings)

        # Deterministic full KMeans solves the initial geometry...
        seed_km = KMeans(
            n_clusters=self.n_clusters, random_state=self.random_state, n_init='auto'
        ).fit(X)

        # ...then warm-starts the online estimator so subsequent partial_fit
        # calls keep centroid indices (=> topic IDs) stable.
        self.kmeans = MiniBatchKMeans(
            n_clusters=self.n_clusters,
            init=seed_km.cluster_centers_,
            n_init=1,
            random_state=self.random_state,
            batch_size=256,
        )
        self.kmeans.partial_fit(X)
        labels = self.public_labels(self.kmeans.predict(X))

        # Frozen-vocabulary vectorizer enables cheap incremental c-TF-IDF
        self.vectorizer = CountVectorizer(
            stop_words=self._stop_words(), min_df=1, ngram_range=(1, 2)
        ).fit(docs)
        self.cluster_term_counts = self._aggregate_counts(
            labels, self.vectorizer.transform(docs)
        )

        distances = self.kmeans.transform(X).min(axis=1)
        self.baseline_distance = float(distances.mean())
        self.recent_distances = []
        self.version += 1
        self.updated_at = time.strftime('%Y-%m-%d %H:%M:%S')
        return labels

    def partial_update(self, docs, embeddings):
        """ONLINE LEARNING STEP: absorb new documents without refitting.

        MiniBatchKMeans.partial_fit nudges only the centroids nearest to the
        incoming mini-batch, then the batch is labeled against the updated
        geometry. Complexity is O(batch * k) — independent of corpus size.
        """
        if self.kmeans is None:
            raise RuntimeError("Model not initialized — run cold_start first.")
        X = self._normalize(embeddings)

        self.kmeans.partial_fit(X)  # <-- the incremental-learning core
        labels = self.public_labels(self.kmeans.predict(X))

        # Incremental c-TF-IDF bookkeeping (frozen vocabulary, sparse adds)
        self.cluster_term_counts = self.cluster_term_counts + self._aggregate_counts(
            labels, self.vectorizer.transform(docs)
        )

        # Drift bookkeeping: distance of new points to their centroid
        distances = self.kmeans.transform(X).min(axis=1)
        self.recent_distances.extend(float(d) for d in distances)
        self.recent_distances = self.recent_distances[-DRIFT_WINDOW:]

        self.version += 1
        self.updated_at = time.strftime('%Y-%m-%d %H:%M:%S')
        return labels

    # ---------------- topic labeling ----------------
    def topic_names(self, top_n=4):
        """Class-based TF-IDF names (same weighting as step_3_dynamic_topics)."""
        if self.cluster_term_counts is None:
            return {}
        tf = np.asarray(self.cluster_term_counts.todense(), dtype=np.float64)
        words = self.vectorizer.get_feature_names_out()
        df_classes = (tf > 0).sum(axis=0)
        avg_words = float(tf.sum(axis=1).mean()) if tf.size else 0.0
        ctfidf = tf * np.log(1 + avg_words / (df_classes + 1e-5))

        names = {}
        for c in range(self.n_clusters):
            ranked = []
            if ctfidf.shape[1] > 0:
                top_idx = np.argsort(ctfidf[c])[-max(top_n * 3, 12):][::-1]
                ranked = [str(words[i]) for i in top_idx if ctfidf[c][i] > 0]
            names[c] = build_topic_label(c, ranked, n=top_n)
        return names

    # ---------------- drift & refit support ----------------
    def drift_status(self):
        """Returns (recent_mean_distance, baseline, is_drifting)."""
        if not self.recent_distances or self.baseline_distance is None:
            return None, self.baseline_distance, False
        mean_recent = float(np.mean(self.recent_distances))
        drifting = (
            len(self.recent_distances) >= 20
            and mean_recent > DRIFT_RATIO * self.baseline_distance
        )
        return mean_recent, self.baseline_distance, drifting

    def align_ids_to(self, previous_model):
        """Re-maps this freshly refit model's public IDs onto the previous
        model's topics (Hungarian assignment on centroid cosine similarity)
        so dashboard topic identities stay stable across full re-fits."""
        if previous_model is None or previous_model.kmeans is None:
            return
        new_centers = self._normalize(self.kmeans.cluster_centers_)
        old_centers = self._normalize(previous_model.kmeans.cluster_centers_)
        similarity = new_centers @ old_centers.T          # (k_new, k_old)
        rows, cols = linear_sum_assignment(-similarity)

        k = self.n_clusters
        proposed = {int(r): int(c) for r, c in zip(rows, cols) if int(c) < k}
        self.id_alias = self._build_alias(proposed, k)

        # Reorder the count matrix rows into public-ID space
        permutation = np.zeros(k, dtype=int)
        for raw_id, public_id in self.id_alias.items():
            permutation[public_id] = raw_id
        dense_counts = np.asarray(self.cluster_term_counts.todense())
        self.cluster_term_counts = sparse.csr_matrix(dense_counts[permutation])

    @staticmethod
    def _build_alias(proposed, k):
        used = set(proposed.values())
        free = [i for i in range(k) if i not in used]
        alias = {}
        for raw_id in range(k):
            if raw_id in proposed:
                alias[raw_id] = proposed[raw_id]
            else:
                alias[raw_id] = free.pop(0) if free else raw_id
        return alias

    # ---------------- persistence ----------------
    def save(self, path=STATE_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path=STATE_PATH):
        return joblib.load(path)


# ======================================================================
# STREAM ORCHESTRATION
# ======================================================================
def _clustering_docs(frame):
    """Same clustering text recipe as the batch pipeline (Title + 1200 chars)."""
    return (frame['Title'].astype(str) + ". " + frame['Text'].astype(str).str[:1200]).tolist()


def _adaptive_k(n_docs):
    """Same adaptive cluster-count heuristic as step_3_dynamic_topics."""
    return max(4, min(10, n_docs // 6)) if n_docs >= 10 else max(1, n_docs)


def _load_master_corpus(pipeline):
    if os.path.exists(CORPUS_PATH):
        return pd.read_csv(CORPUS_PATH)
    if os.path.exists(pipeline.FILENAME_EXCEL):
        print(f"  ℹ️ [STREAM] Bootstrapping master corpus from '{pipeline.FILENAME_EXCEL}'...")
        return pd.read_excel(pipeline.FILENAME_EXCEL)
    sys.exit(
        "❌ [STREAM] No corpus found. Run the batch pipeline first "
        "(python Alex1.py) to create the initial dataset."
    )


def _corpus_domains(frame):
    publisher_urls = frame['Publisher_URL'] if 'Publisher_URL' in frame.columns else [None] * len(frame)
    return {
        d for d in (publisher_domain(u, p if isinstance(p, str) else None)
                    for u, p in zip(frame['URL'].astype(str), publisher_urls)) if d
    }


def _load_or_cold_start(corpus, pipeline):
    if os.path.exists(STATE_PATH):
        try:
            model = StreamingTopicModel.load()
            if not hasattr(model, "publisher_domains"):
                model.publisher_domains = set()
            print(f"  ✅ [STREAM] Loaded persisted model (k={model.n_clusters}, version={model.version}).")
            return model
        except Exception as load_err:
            print(f"  ⚠️ [STREAM] Could not load persisted state ({load_err}). Re-initializing...")

    docs = _clustering_docs(corpus)
    embeddings = pipeline.encode_texts_cached(docs)
    model = StreamingTopicModel(_adaptive_k(len(docs)), random_state=42)
    model.publisher_domains = _corpus_domains(corpus)
    labels = model.cold_start(docs, embeddings)
    names = model.topic_names()
    corpus['Topic_ID'] = labels
    corpus['Topic_Name'] = [names.get(int(t), f"{t}_cluster") for t in labels]
    model.save()
    print(f"  ✅ [STREAM] Cold start complete (k={model.n_clusters}, {len(docs)} documents).")
    return model


def _full_refit(previous_model, corpus, pipeline):
    """Full re-clustering with stable ID re-mapping (drift recovery path)."""
    docs = _clustering_docs(corpus)
    embeddings = pipeline.encode_texts_cached(docs)
    fresh = StreamingTopicModel(_adaptive_k(len(docs)), random_state=42)
    fresh.publisher_domains = _corpus_domains(corpus)
    fresh.cold_start(docs, embeddings)
    fresh.align_ids_to(previous_model)
    return fresh


def _export_osint_json(corpus, names, pipeline):
    """Rebuilds osint_output.json (schema v2) with REAL per-article TVS
    evidence, using the same topic-node builder as the batch pipeline."""
    topics = []
    valid_ids = sorted({int(t) for t in corpus['Topic_ID'].dropna() if int(t) != -1})
    for topic_id in valid_ids:
        t_df = corpus[corpus['Topic_ID'] == topic_id]
        if len(t_df) == 0:
            continue
        topic_name = names.get(topic_id) or (
            str(t_df['Topic_Name'].iloc[0]) if 'Topic_Name' in t_df.columns else f"{topic_id}_cluster"
        )
        topics.append(pipeline.build_topic_node(t_df, topic_name))

    payload = export_envelope(topics, corpus_quality_report(corpus), generated_by="stream")
    dest = atomic_write_json(payload, os.path.join(resolve_public_dir(), OSINT_EXPORT_FILENAME))
    print(f"  ✅ [STREAM] Atomically refreshed '{dest}' ({len(topics)} topics)")


def run_stream_update(pipeline=None, topics=None, max_articles=None):
    """Entry point for `python Alex1.py --stream [-t TOPIC ...] [--max-articles N]`.

    `pipeline` is the already-loaded Alex1 module (passed from main() to
    avoid a double import that would reload the SBERT model)."""
    if pipeline is None:
        import Alex1 as pipeline  # standalone invocation of this module
    topics = list(topics or pipeline.TOPICS)
    max_articles = max_articles or pipeline.MAX_ARTICLES_PER_TOPIC

    print("\n" + "=" * 70)
    print("  🌊 VERINEWS STREAMING UPDATE  (online learning via partial_fit)")
    print("=" * 70)
    start = time.time()

    corpus = _load_master_corpus(pipeline)
    model = _load_or_cold_start(corpus, pipeline)

    # ---- Scrape only unseen articles (delta ingestion) ----------
    seen = set(corpus['URL'].astype(str)) | set(corpus['Title'].astype(str))
    new_rows = []
    for topic in topics:
        try:
            articles = pipeline.fetch_topic(topic, max_articles)
        except Exception as fetch_err:
            print(f"  ⚠️ [STREAM] '{topic}' fetch failed: {fetch_err}")
            continue

        fresh = []
        for article in articles:
            key_url = str(article.get('URL'))
            key_title = str(article.get('Title'))
            if key_url in seen or key_title in seen:
                continue
            seen.add(key_url)
            seen.add(key_title)
            fresh.append(article)
        new_rows.extend(fresh)
        print(f"  ✓ [STREAM] '{topic}': {len(fresh)} new articles.")

    if not new_rows:
        print("\n✅ [STREAM] No new articles found — model and dashboard unchanged.")
        return

    new_df = pd.DataFrame(new_rows)
    pipeline.report_corpus_quality(new_df, label="New articles")

    # ---- Enrich the new rows (sentiment / NER / KeyBERT) -----------
    # The batch pipeline's step 2 is reused so streamed rows carry the same
    # evidence as batch rows instead of falling back to NEUTRAL sentiment.
    try:
        new_df = pipeline.step_2_nlp_processing(new_df)
    except Exception as nlp_err:
        print(f"  ⚠️ [STREAM] NLP enrichment skipped: {nlp_err}")

    # ---- Online update (the partial_fit core) --------------------
    docs = _clustering_docs(new_df)
    embeddings = pipeline.encode_texts_cached(docs)
    labels = model.partial_update(docs, embeddings)
    names = model.topic_names()
    new_df['Topic_ID'] = labels
    new_df['Topic_Name'] = [names.get(int(t), f"{t}_cluster") for t in labels]

    corpus = pd.concat([corpus, new_df], ignore_index=True)

    # ---- Drift check / optional stable re-fit --------------------
    mean_d, base_d, drifting = model.drift_status()
    if drifting:
        print(f"  ⚠️ [STREAM] Concept drift detected (recent mean dist {mean_d:.4f} "
              f"> {DRIFT_RATIO}x baseline {base_d:.4f}).")
        print("     Running full re-fit with Hungarian ID re-mapping...")
        model = _full_refit(model, corpus, pipeline)
        names = model.topic_names()
        all_embeddings = pipeline.encode_texts_cached(_clustering_docs(corpus))
        raw = model.kmeans.predict(StreamingTopicModel._normalize(all_embeddings))
        corpus['Topic_ID'] = model.public_labels(raw)
        corpus['Topic_Name'] = [names.get(int(t), f"{t}_cluster") for t in corpus['Topic_ID']]

    # ---- Persist + export -----------------------------------------
    corpus.to_csv(CORPUS_PATH, index=False)
    model.save()
    _export_osint_json(corpus, names, pipeline)

    print(f"\n⏱️ [STREAM] Complete in {int(time.time() - start)}s: "
          f"+{len(new_df)} articles, model version {model.version}"
          + (f", drift refit applied (k={model.n_clusters})." if drifting else "."))


if __name__ == "__main__":
    run_stream_update()
