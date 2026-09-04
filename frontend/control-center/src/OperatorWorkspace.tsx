import { useEffect, useMemo, useState } from "react";
import ApplicationSourceUpload from "./ApplicationSourceUpload";
import JobReviewLabelControls, {
  type JobReviewLabelState,
} from "./JobReviewLabelControls";
import { clearProductTruthCache, readProductTruth } from "./productPayloadRuntimeAdapter";
import "./operator-workspace-v2.css";
import "./operator-demo-hardening.css";

type Job = {
  silver_job_id: number;
  product_rank?: number;
  title?: string | null;
  company_name?: string | null;
  display_company_name?: string | null;
  legal_entity_name?: string | null;
  city?: string | null;
  country?: string | null;
  publication_date?: string | null;
  source_url?: string | null;
  product_readiness_status?: string;
  lifecycle_status?: string;
  overall_quality_score?: number | null;
  product_overall_quality_score?: number | null;
  display_fit_score?: number | null;
  display_fit_scope?: string | null;
  profile_direction_score?: number | null;
  data_focus_score?: number | null;
  reliability_focus_score?: number | null;
  evidence_quality_score?: number | null;
  work_model?: string;
  commute_minutes?: number | null;
  explanations?: string[];
  uncertainties?: string[];
  review_label?: JobReviewLabelState | null;
  career_intelligence?: CareerIntelligenceRecord | null;
};

type CareerOperatorState = "NEW" | "REVIEWED" | "INTERESTED" | "DISMISSED";
type CareerRecommendation = "APPLY_NOW" | "NETWORK_FIRST" | "EXPLORE" | "WATCH" | "SKIP";

type CareerIntelligenceRecord = {
  source_file: string;
  silver_job_id?: number | null;
  job_join_status?: string;
  company?: string | null;
  title?: string | null;
  opportunity_score?: number | null;
  recommendation?: CareerRecommendation | string | null;
  career_lane?: string | null;
  career_lane_label?: string | null;
  constraint_action?: string | null;
  risks?: unknown[];
  key_matched_capabilities?: unknown[];
  network_access?: number | null;
  relationship_level?: string | null;
  network_status?: string | null;
  publication_date?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  job_age_days?: number | null;
  freshness_bucket?: string | null;
  job_age_date_source?: string | null;
  freshness_ranking_penalty?: number | null;
  operator_state: CareerOperatorState;
  workspace_available?: boolean;
  provenance?: {
    source_file?: string;
    silver_job_id?: number | null;
    raw_job_id?: number | null;
    source_name?: string | null;
    external_job_id?: string | null;
    source_url?: string | null;
    stable_identity_type?: string | null;
    stable_identity_sha256?: string | null;
    description_source?: string | null;
    description_quality?: string | null;
    ingestion_status?: string | null;
    publication_date?: string | null;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
    freshness_bucket?: string | null;
    job_age_days?: number | null;
    job_age_date_source?: string | null;
    freshness_ranking_penalty?: number | null;
  };
};

type CareerIntelligencePayload = {
  available: boolean;
  status: string;
  reason?: string | null;
  records: CareerIntelligenceRecord[];
  state_action_path?: string;
  summary?: {
    opportunity_count?: number;
    joined_job_count?: number;
    unmatched_opportunity_count?: number;
    recommendation_counts?: Record<string, number>;
    operator_state_counts?: Record<string, number>;
  };
};

type SourceConnector = {
  candidate_id: number | null;
  source_name: string;
  source_label: string;
  source_type: string;
  candidate_status: string;
  current_blocker?: string | null;
  next_action: string;
  connector: {
    implementation_status: string;
    registration_status: string;
  };
  activation: { status: string; active: boolean | null };
  search_profiles: { active_profile_count: number; profile_count: number };
  gates: {
    connector_validation_gate: { status: string; decision?: string | null };
    final_approval_gate: { status: string; decision?: string | null };
  };
  last_ingestion: { status: string; total_loaded: number; inserted_count: number };
  layers: { bronze_count: number; silver_count: number };
  career_source_strategy?: {
    configured: boolean;
    company_name?: string;
    tier?: string;
    tier_label?: string;
    strategic_priority?: number;
    relevant_career_lanes?: string[];
    preferred_evidence_type?: string;
    source_role?: string;
    is_employer_origin?: boolean;
    is_discovery?: boolean;
    location_relevance?: string[];
    status?: string;
    source_status?: string;
    strategy_group?: string;
    career_relevance?: string;
  };
  career_source_advisory?: {
    status?: string;
    observed_opportunity_count?: number;
    best_score?: number | null;
    reasons?: string[];
    automatic_downgrade?: boolean;
  };
};

type AdaptiveSourceCandidate = {
  company_name: string;
  normalized_company_key: string;
  observed_opportunity_count: number;
  assessed_opportunity_count: number;
  highest_opportunity_score: number;
  average_opportunity_score: number;
  recommendations_distribution?: Record<string, number>;
  career_lanes: string[];
  berlin_relevance: boolean;
  remote_germany_relevance: boolean;
  location_constraint_conflicts: boolean;
  evidence_quality: string;
  employer_origin_evidence_available: boolean;
  discovery_source_evidence_available: boolean;
  source_strategy_status: string;
  suggested_action: string;
  operator_decision: string;
  promotion_reasons: string[];
};

type ProductPayload = {
  summary: {
    observed_job_count: number;
    current_active_job_count: number;
    review_scope_current_active_job_count?: number;
    stale_job_count: number;
    inactive_confirmed_job_count: number;
    unverifiable_job_count: number;
    rankable_job_count: number;
    top_job_count: number;
    application_ready_count: number;
  };
  job_readiness: Job[];
  discovery_job_readiness?: Job[];
  top_jobs: Job[];
  application_sources_ready: {
    base_cv: boolean;
    base_application_letter: boolean;
  };
  source_connector_overview: {
    summary: {
      source_count: number;
      implemented_count: number;
      validated_count: number;
      final_approved_count: number;
      registered_count: number;
      active_count: number;
      ingested_count: number;
      attention_count: number;
    };
    sources: SourceConnector[];
    adaptive_source_discovery?: {
      available: boolean;
      status: string;
      reason?: string | null;
      state_action_path?: string;
      candidates?: AdaptiveSourceCandidate[];
      summary?: {
        candidate_count?: number;
        promotion_candidate_count?: number;
        watch_candidate_count?: number;
        ignored_candidate_count?: number;
      };
    };
  };
  operator_blockers: Array<{ code: string; title: string; detail: string }>;
  review_label_capture?: {
    available: boolean;
  };
  career_intelligence?: CareerIntelligencePayload;
};

type View = "overview" | "jobs" | "career" | "top5" | "application" | "applications" | "sources" | "approvals" | "operations";
type JobFilter = "current" | "unreviewed" | "interesting" | "not_relevant" | "rankable" | "all";
type CareerStateFilter = CareerOperatorState | "ALL";
type CareerRecommendationFilter = CareerRecommendation | "ALL";
type JobSort =
  | "newest"
  | "oldest"
  | "fit_desc"
  | "fit_asc"
  | "review_asc"
  | "review_desc"
  | "job_asc"
  | "job_desc"
  | "location_asc"
  | "location_desc"
  | "gate_asc"
  | "gate_desc";
type SortColumn = "fit" | "review" | "job" | "location" | "published" | "gate";
type SourceGroup = "Strategic employers" | "Adjacent employers" | "Discovery sources" | "Adaptive candidates" | "Existing generic/demo sources";

const normalize = (value: string | undefined | null) => (value || "").trim().toLocaleLowerCase();
const label = (value: string | undefined | null) => (value || "unknown").replaceAll("_", " ");
const scoreText = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value)}%`;
const compactItemText = (value: unknown) => {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.name || record.capability || record.constraint || record.reason || JSON.stringify(record));
  }
  return String(value);
};
const isCurrent = (job: Job) => ["active confirmed", "active_confirmed"].includes(normalize(job.lifecycle_status));
const isRankable = (job: Job) => normalize(job.product_readiness_status) === "rankable";
const employerName = (job: Job) => job.display_company_name || job.company_name || "Employer not resolved";
const locationText = (job: Job) => job.city || job.country || (normalize(job.work_model) === "remote" ? "Remote" : "Location not confirmed");
const reviewText = (job: Job) => job.review_label?.label || "unreviewed";
const gateText = (job: Job) => job.product_readiness_status || "unknown";

function externalJobUrl(job: Job): string | null {
  const raw = (job.source_url || "").trim();
  if (!raw) return null;
  if (raw.startsWith("https://") || raw.startsWith("http://")) return raw;
  if (raw.startsWith("ba://")) {
    const reference = raw.slice("ba://".length).trim();
    return reference
      ? `https://www.arbeitsagentur.de/jobsuche/jobdetail/${encodeURIComponent(reference)}`
      : null;
  }
  return null;
}

const publicationTime = (job: Job) => {
  if (!job.publication_date) return null;
  const value = Date.parse(job.publication_date);
  return Number.isNaN(value) ? null : value;
};

const displayDate = (value: string | null | undefined) => {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(parsed));
};

const compareText = (left: string, right: string) => left.localeCompare(right, "de", { sensitivity: "base" });

function jobAgeText(record: CareerIntelligenceRecord) {
  const bucket = record.freshness_bucket || record.provenance?.freshness_bucket || "UNKNOWN";
  const age = record.job_age_days ?? record.provenance?.job_age_days;
  const source = record.job_age_date_source || record.provenance?.job_age_date_source;
  if (typeof age !== "number") return `${bucket} · date unknown`;
  return `${bucket} · ${age}d · ${label(source)}`;
}

function compareJobs(a: Job, b: Job, sort: JobSort) {
  if (sort === "fit_desc" || sort === "fit_asc") {
    const aFit = a.overall_quality_score ?? -1;
    const bFit = b.overall_quality_score ?? -1;
    const fitDelta = sort === "fit_desc" ? bFit - aFit : aFit - bFit;
    if (fitDelta !== 0) return fitDelta;
  }

  if (sort === "review_asc" || sort === "review_desc") {
    const delta = compareText(reviewText(a), reviewText(b));
    if (delta !== 0) return sort === "review_asc" ? delta : -delta;
  }

  if (sort === "job_asc" || sort === "job_desc") {
    const delta = compareText(`${a.title || ""} ${employerName(a)}`, `${b.title || ""} ${employerName(b)}`);
    if (delta !== 0) return sort === "job_asc" ? delta : -delta;
  }

  if (sort === "location_asc" || sort === "location_desc") {
    const delta = compareText(locationText(a), locationText(b));
    if (delta !== 0) return sort === "location_asc" ? delta : -delta;
  }

  if (sort === "gate_asc" || sort === "gate_desc") {
    const delta = compareText(gateText(a), gateText(b));
    if (delta !== 0) return sort === "gate_asc" ? delta : -delta;
  }

  const aDate = publicationTime(a);
  const bDate = publicationTime(b);

  if (aDate == null && bDate != null) return 1;
  if (aDate != null && bDate == null) return -1;

  if (aDate != null && bDate != null) {
    const dateDelta = sort === "oldest" ? aDate - bDate : bDate - aDate;
    if (dateDelta !== 0) return dateDelta;
  }

  return b.silver_job_id - a.silver_job_id;
}

function tone(value: string | undefined | null) {
  const normalized = normalize(value);
  if (["rankable", "active", "active confirmed", "active_confirmed", "approved", "interesting", "passed"].includes(normalized)) return "good";
  if (normalized.includes("failed") || normalized.includes("blocked") || normalized === "not_relevant") return "bad";
  if (normalized.includes("required") || normalized.includes("unknown") || normalized.includes("stale") || normalized === "unsure") return "warn";
  return "neutral";
}

function Status({ value }: { value?: string | null }) {
  return <span className={`ow-status ${tone(value)}`}>{label(value)}</span>;
}

function Metric({ labelText, value, helper }: { labelText: string; value: number | string; helper: string }) {
  return <article className="ow-metric"><span>{labelText}</span><strong>{value}</strong><small>{helper}</small></article>;
}

function OpenApplicationButton({ disabled = false, silverJobId }: { disabled?: boolean; silverJobId?: number | null }) {
  return <button
    type="button"
    className="ow-primary"
    disabled={disabled}
    onClick={() => window.dispatchEvent(new CustomEvent("product-v1:open-application-workspace", { detail: { silverJobId } }))}
  >Prepare application</button>;
}

function Overview({ payload, onNavigate }: { payload: ProductPayload; onNavigate: (view: View) => void }) {
  const currentJobs = payload.job_readiness.filter(isCurrent);
  const reviewed = payload.job_readiness.filter((job) => Boolean(job.review_label));
  const interesting = reviewed.filter((job) => job.review_label?.label === "interesting").length;
  const rejected = reviewed.filter((job) => job.review_label?.label === "not_relevant").length;
  const top = payload.top_jobs[0] || null;
  const docsReady = payload.application_sources_ready.base_cv && payload.application_sources_ready.base_application_letter;
  const topUrl = top ? externalJobUrl(top) : null;

  return <div className="ow-stack">
    <header className="ow-page-header">
      <div><span>Overall</span><h1>What matters now</h1><p>Current Product V1 truth, reduced to the next useful decisions.</p></div>
    </header>

    <section className="ow-metrics">
      <Metric labelText="Current jobs" value={currentJobs.length} helper="confirmed active in review scope" />
      <Metric labelText="Rankable" value={payload.summary.rankable_job_count} helper="hard gates passed" />
      <Metric labelText="Top 5" value={`${payload.summary.top_job_count}/5`} helper="authoritative shortlist" />
      <Metric labelText="Application ready" value={payload.summary.application_ready_count} helper="review draft context" />
    </section>

    <section className="ow-overview-grid">
      <article className="ow-card ow-now-card">
        <div className="ow-card-title"><div><span>Best current option</span><h2>{top ? top.title : "No rankable job yet"}</h2></div>{top && <strong>#{top.product_rank || 1}</strong>}</div>
        {top ? <>
          <p className="ow-job-meta">{employerName(top)} · {locationText(top)}</p>
          <div className="ow-fit-line"><b>{scoreText(top.overall_quality_score)}</b><span>authoritative profile fit</span></div>
          <div className="ow-actions"><button type="button" onClick={() => onNavigate("top5")}>Open Top 5</button>{topUrl && <a href={topUrl} target="_blank" rel="noreferrer">Original job ↗</a>}</div>
        </> : <p className="ow-muted">The UI will not manufacture a recommendation.</p>}
      </article>

      <article className="ow-card">
        <div className="ow-card-title"><div><span>Your feedback</span><h2>Relevance labels</h2></div><strong>{reviewed.length}</strong></div>
        <div className="ow-feedback-summary"><div><span>Interesting</span><b>{interesting}</b></div><div><span>Not relevant</span><b>{rejected}</b></div><div><span>Unreviewed</span><b>{payload.job_readiness.length - reviewed.length}</b></div></div>
        <p className="ow-muted">These labels build personal relevance evidence; they do not directly rewrite ranking.</p>
        <button type="button" className="ow-text-action" onClick={() => onNavigate("jobs")}>Review jobs →</button>
      </article>

      <article className="ow-card">
        <div className="ow-card-title"><div><span>Application</span><h2>{docsReady ? "Source documents ready" : "Source documents still required"}</h2></div></div>
        <div className="ow-readiness"><div className={payload.application_sources_ready.base_cv ? "ready" : "blocked"}><i /><span>Base CV</span><b>{payload.application_sources_ready.base_cv ? "Approved" : "Required"}</b></div><div className={payload.application_sources_ready.base_application_letter ? "ready" : "blocked"}><i /><span>Base letter</span><b>{payload.application_sources_ready.base_application_letter ? "Approved" : "Required"}</b></div></div>
        <button type="button" className="ow-text-action" onClick={() => onNavigate("application")}>Open application step →</button>
      </article>

      <article className="ow-card">
        <div className="ow-card-title"><div><span>Discovery health</span><h2>Remote is producing value</h2></div></div>
        <p>{currentJobs.length} current vacancies are in the visible review scope. Product V1 keeps broader source/lifecycle truth separate from this review surface.</p>
        <div className="ow-actions"><button type="button" onClick={() => onNavigate("sources")}>Sources</button><button type="button" onClick={() => onNavigate("applications")}>Applications</button></div>
      </article>
    </section>
  </div>;
}

function JobDetail({ job, payload, refresh }: { job: Job; payload: ProductPayload; refresh: () => Promise<void> }) {
  const sourceUrl = externalJobUrl(job);
  const rankable = isRankable(job);
  const scoreRows = rankable
    ? ([
        ["Overall", job.overall_quality_score],
        ["Profile direction", job.profile_direction_score],
        ["Data focus", job.data_focus_score],
        ["Reliability", job.reliability_focus_score],
        ["Evidence quality", job.evidence_quality_score],
      ] as Array<[string, number | null | undefined]>)
    : ([ ["Role affinity", job.overall_quality_score] ] as Array<[string, number | null | undefined]>);

  return <aside className="ow-job-detail">
    <div className="ow-detail-head"><span>Silver #{job.silver_job_id}</span><h2>{job.title || "Untitled job"}</h2><p>{employerName(job)} · {locationText(job)}</p>{job.legal_entity_name && normalize(job.legal_entity_name) !== normalize(employerName(job)) && <small>Legal entity: {job.legal_entity_name}</small>}</div>
    <div className="ow-actions">{sourceUrl && <a className="ow-primary-link" href={sourceUrl} target="_blank" rel="noreferrer">Open original ↗</a>}{rankable && <OpenApplicationButton silverJobId={job.silver_job_id} />}</div>
    <JobReviewLabelControls silverJobId={job.silver_job_id} currentLabel={job.review_label} captureAvailable={payload.review_label_capture?.available === true} refreshProductTruth={refresh} />
    <section className="ow-score-card"><h3>{rankable ? "Profile fit" : "Role affinity · preliminary"}</h3>{scoreRows.map(([name, value]) => <div key={name}><span>{name}</span><i><b style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }} /></i><strong>{scoreText(value)}</strong></div>)}{!rankable && <p className="ow-score-note">Detail check required. This preliminary signal uses review-scope evidence and is not capability-fit or Product V1 ranking authority.</p>}</section>
    <section className="ow-facts"><div><span>Lifecycle</span><Status value={job.lifecycle_status} /></div><div><span>Product gate</span><Status value={job.product_readiness_status} /></div><div><span>Work model</span><b>{label(job.work_model)}</b></div><div><span>Commute</span><b>{job.commute_minutes == null ? "—" : `${job.commute_minutes} min`}</b></div></section>
    <section className="ow-evidence"><div><span>Verified</span>{job.explanations?.length ? <ul>{job.explanations.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No projected explanation evidence.</p>}</div><div><span>Unknown / review</span>{job.uncertainties?.length ? <ul>{job.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No projected uncertainty.</p>}</div></section>
  </aside>;
}

function Jobs({ payload, refresh }: { payload: ProductPayload; refresh: () => Promise<void> }) {
  const [filter, setFilter] = useState<JobFilter>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<JobSort>("newest");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const q = normalize(search);

    return payload.job_readiness
      .filter((job) => {
        if (filter === "current" && !isCurrent(job)) return false;
        if (filter === "unreviewed" && job.review_label) return false;
        if (filter === "interesting" && job.review_label?.label !== "interesting") return false;
        if (filter === "not_relevant" && job.review_label?.label !== "not_relevant") return false;
        if (filter === "rankable" && job.product_readiness_status !== "rankable") return false;
        if (
          q &&
          !normalize(
            `${job.title} ${employerName(job)} ${job.city} ${job.country}`
          ).includes(q)
        ) return false;
        return true;
      })
      .sort((a, b) => compareJobs(a, b, sort));
  }, [filter, payload.job_readiness, search, sort]);

  const selected =
    filtered.find((job) => job.silver_job_id === selectedId) ||
    filtered[0] ||
    null;

  const counts: Record<JobFilter, number> = {
    current: payload.job_readiness.filter(isCurrent).length,
    unreviewed: payload.job_readiness.filter((job) => !job.review_label).length,
    interesting: payload.job_readiness.filter(
      (job) => job.review_label?.label === "interesting"
    ).length,
    not_relevant: payload.job_readiness.filter(
      (job) => job.review_label?.label === "not_relevant"
    ).length,
    rankable: payload.job_readiness.filter(
      (job) => job.product_readiness_status === "rankable"
    ).length,
    all: payload.job_readiness.length,
  };

  const sortFor = (column: SortColumn): [JobSort, JobSort] => {
    if (column === "fit") return ["fit_desc", "fit_asc"];
    if (column === "review") return ["review_asc", "review_desc"];
    if (column === "job") return ["job_asc", "job_desc"];
    if (column === "location") return ["location_asc", "location_desc"];
    if (column === "gate") return ["gate_asc", "gate_desc"];
    return ["newest", "oldest"];
  };

  const sortHeader = (column: SortColumn, text: string) => {
    const [first, second] = sortFor(column);
    const active = sort === first || sort === second;
    return <button
      type="button"
      className={active ? "active" : ""}
      onClick={() => setSort(sort === first ? second : first)}
      title={`Sort by ${text}`}
    >{text}</button>;
  };

  return <div className="ow-stack">
    <header className="ow-page-header">
      <div>
        <span>Review surface</span>
        <h1>All jobs</h1>
        <p>
          Every displayed job has a deterministic preliminary role-affinity signal.
          A real Profile Fit exists only after detail evidence, capability fit and hard gates.
          Sorting and filters never change Product V1 ranking authority.
        </p>
      </div>
    </header>

    <section className="ow-job-toolbar">
      <div className="ow-filter-row">
        {([
          ["all", "All observed"],
          ["current", "Current"],
          ["unreviewed", "Unreviewed"],
          ["interesting", "Interesting"],
          ["not_relevant", "Not relevant"],
          ["rankable", "Rankable"],
        ] as Array<[JobFilter, string]>).map(([id, text]) =>
          <button
            type="button"
            key={id}
            className={filter === id ? "active" : ""}
            onClick={() => setFilter(id)}
          >
            {text}<b>{counts[id]}</b>
          </button>
        )}
      </div>

      <div className="ow-toolbar-controls">
        <label className="ow-search">
          <span>⌕</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Title, employer, location…"
          />
        </label>

        <label className="ow-sort">
          <span>Sort</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as JobSort)}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="fit_desc">Affinity high → low</option>
            <option value="fit_asc">Affinity low → high</option>
            <option value="review_asc">Review A → Z</option>
            <option value="job_asc">Job A → Z</option>
            <option value="location_asc">Location A → Z</option>
            <option value="gate_asc">Gate A → Z</option>
          </select>
        </label>
      </div>
    </section>

    <section className="ow-job-workspace">
      <div className="ow-job-list">
        <div className="ow-job-list-head">
          {sortHeader("fit", "Affinity")}
          {sortHeader("review", "Review")}
          {sortHeader("job", "Job")}
          {sortHeader("location", "Location")}
          {sortHeader("published", "Published")}
          {sortHeader("gate", "Gate")}
        </div>

        {filtered.map((job) =>
          <button
            type="button"
            key={job.silver_job_id}
            className={
              selected?.silver_job_id === job.silver_job_id ? "selected" : ""
            }
            onClick={() => setSelectedId(job.silver_job_id)}
          >
            <strong title={isRankable(job) ? "Authoritative Profile Fit" : "Preliminary role affinity · detail check required"}>{scoreText(job.overall_quality_score)}</strong>
            <Status value={job.review_label?.label || "unreviewed"} />

            <span className="ow-job-name">
              <b>{job.title || "Untitled job"}</b>
              <small>{employerName(job)}</small>
            </span>

            <span className="ow-location">
              <b>{locationText(job)}</b>
              <small>{label(job.work_model)}</small>
            </span>

            <span className="ow-published">
              {displayDate(job.publication_date)}
            </span>

            <Status value={job.product_readiness_status} />
          </button>
        )}

        {filtered.length === 0 &&
          <p className="ow-empty">No jobs match this filter.</p>}
      </div>

      {selected
        ? <JobDetail job={selected} payload={payload} refresh={refresh} />
        : <aside className="ow-job-detail">
            <p className="ow-empty">Select a job.</p>
          </aside>}
    </section>
  </div>;
}

function careerScore(record: CareerIntelligenceRecord) {
  return typeof record.opportunity_score === "number" ? record.opportunity_score : -1;
}

function careerTitle(record: CareerIntelligenceRecord) {
  return record.title || "Untitled opportunity";
}

function careerCompany(record: CareerIntelligenceRecord) {
  return record.company || "Unknown employer";
}

function careerSort(a: CareerIntelligenceRecord, b: CareerIntelligenceRecord) {
  const scoreDelta = careerScore(b) - careerScore(a);
  if (scoreDelta !== 0) return scoreDelta;
  const recommendationDelta = compareText(String(a.recommendation || ""), String(b.recommendation || ""));
  if (recommendationDelta !== 0) return recommendationDelta;
  const companyDelta = compareText(careerCompany(a), careerCompany(b));
  if (companyDelta !== 0) return companyDelta;
  const titleDelta = compareText(careerTitle(a), careerTitle(b));
  if (titleDelta !== 0) return titleDelta;
  return compareText(a.source_file, b.source_file);
}

function setApplicationWorkspaceJob(silverJobId: number | null | undefined) {
  if (silverJobId == null) return;
  window.dispatchEvent(new CustomEvent("product-v1:open-application-workspace", { detail: { silverJobId } }));
}

function CareerIntelligence({
  payload,
  refresh,
}: {
  payload: ProductPayload;
  refresh: () => Promise<void>;
}) {
  const career = payload.career_intelligence;
  const [recommendation, setRecommendation] = useState<CareerRecommendationFilter>("ALL");
  const [operatorState, setOperatorState] = useState<CareerStateFilter>("ALL");
  const [lane, setLane] = useState("ALL");
  const [minimumScore, setMinimumScore] = useState(0);
  const [includeDismissed, setIncludeDismissed] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const records = career?.records || [];
  const laneOptions = useMemo(() => {
    const values = new Set(records.map((record) => record.career_lane).filter((value): value is string => Boolean(value)));
    return Array.from(values).sort(compareText);
  }, [records]);

  const filtered = useMemo(() => records
    .filter((record) => includeDismissed || record.operator_state !== "DISMISSED")
    .filter((record) => recommendation === "ALL" || record.recommendation === recommendation)
    .filter((record) => operatorState === "ALL" || record.operator_state === operatorState)
    .filter((record) => lane === "ALL" || record.career_lane === lane)
    .filter((record) => careerScore(record) >= minimumScore)
    .sort(careerSort), [includeDismissed, lane, minimumScore, operatorState, recommendation, records]);

  const selected = filtered.find((record) => record.source_file === selectedSource) || filtered[0] || null;
  const summary = career?.summary;
  const stateCounts = summary?.operator_state_counts || {};
  const recommendationCounts = summary?.recommendation_counts || {};

  const updateState = async (record: CareerIntelligenceRecord, nextState: CareerOperatorState) => {
    if (!career?.state_action_path) return;
    setSaving(record.source_file);
    setActionError(null);
    try {
      const response = await fetch(career.state_action_path, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ source_file: record.source_file, state: nextState }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(String(result.reason || `API returned ${response.status}`));
      }
      clearProductTruthCache();
      await refresh();
    } catch (reason) {
      setActionError(String(reason));
    } finally {
      setSaving(null);
    }
  };

  if (!career || career.available !== true) {
    return <div className="ow-stack">
      <header className="ow-page-header"><div><span>Career Intelligence</span><h1>Daily radar unavailable</h1><p>Run the daily Career Intelligence workflow to populate this lens.</p></div></header>
      <section className="ow-card"><h2>{career?.status === "error" ? "Runtime data failed safely" : "No Career Intelligence run yet"}</h2><p>{career?.reason || "No local Career Intelligence opportunities were found. Product V1 remains available."}</p></section>
    </div>;
  }

  return <div className="ow-stack">
    <header className="ow-page-header">
      <div><span>Career Intelligence</span><h1>Opportunity radar</h1><p>Additional decision lens from local Career Intelligence outputs. Product V1 ranking is unchanged.</p></div>
      <strong className="ow-big-count">{filtered.length}/{records.length}</strong>
    </header>

    <section className="ow-metrics">
      <Metric labelText="Career records" value={summary?.opportunity_count ?? records.length} helper="local V1.1 results" />
      <Metric labelText="Joined jobs" value={summary?.joined_job_count ?? 0} helper="matched by Silver provenance" />
      <Metric labelText="NEW" value={stateCounts.NEW ?? 0} helper="unreviewed radar items" />
      <Metric labelText="INTERESTED" value={stateCounts.INTERESTED ?? 0} helper="kept prominent" />
    </section>

    <section className="ow-job-toolbar">
      <div className="ow-filter-row">
        {(["ALL", "APPLY_NOW", "NETWORK_FIRST", "EXPLORE", "WATCH", "SKIP"] as CareerRecommendationFilter[]).map((item) =>
          <button type="button" key={item} className={recommendation === item ? "active" : ""} onClick={() => setRecommendation(item)}>
            {item === "ALL" ? "All recommendations" : item}<b>{item === "ALL" ? records.length : recommendationCounts[item] ?? 0}</b>
          </button>
        )}
      </div>
      <div className="ow-toolbar-controls">
        <label className="ow-sort"><span>State</span><select value={operatorState} onChange={(event) => setOperatorState(event.target.value as CareerStateFilter)}>{(["ALL", "NEW", "INTERESTED", "REVIEWED", "DISMISSED"] as CareerStateFilter[]).map((state) => <option key={state} value={state}>{state === "ALL" ? "All states" : state}</option>)}</select></label>
        <label className="ow-sort"><span>Lane</span><select value={lane} onChange={(event) => setLane(event.target.value)}><option value="ALL">All lanes</option>{laneOptions.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label className="ow-score-filter"><span>Min score</span><input type="number" min="0" max="100" value={minimumScore} onChange={(event) => setMinimumScore(Number(event.target.value) || 0)} /></label>
        <label className="ow-checkbox"><input type="checkbox" checked={includeDismissed} onChange={(event) => setIncludeDismissed(event.target.checked)} />Dismissed</label>
      </div>
    </section>

    {actionError && <section className="ow-callout warn"><b>State update failed</b><span>{actionError}</span></section>}

    <section className="ow-job-workspace ow-career-workspace">
      <div className="ow-career-list">
        <div className="ow-career-list-head"><span>Score</span><span>State</span><span>Recommendation</span><span>Opportunity</span><span>Freshness</span><span>Lane</span></div>
        {filtered.map((record) =>
          <button type="button" key={record.source_file} className={selected?.source_file === record.source_file ? "selected" : ""} onClick={() => setSelectedSource(record.source_file)}>
            <strong>{scoreText(record.opportunity_score)}</strong>
            <Status value={record.operator_state} />
            <Status value={record.recommendation || "unknown"} />
            <span className="ow-job-name"><b>{careerTitle(record)}</b><small>{careerCompany(record)} · {record.job_join_status === "joined" ? `Silver #${record.silver_job_id}` : "not joined to Product V1 job"}</small></span>
            <Status value={jobAgeText(record)} />
            <span>{record.career_lane_label || label(record.career_lane)}</span>
          </button>
        )}
        {filtered.length === 0 && <p className="ow-empty">No Career Intelligence opportunities match this filter.</p>}
      </div>

      {selected ? <aside className="ow-job-detail">
        <div className="ow-detail-head"><span>{selected.source_file}</span><h2>{careerTitle(selected)}</h2><p>{careerCompany(selected)} · {selected.job_join_status === "joined" ? `Silver #${selected.silver_job_id}` : "No Product V1 join"}</p></div>
        <div className="ow-actions">
          {(["NEW", "REVIEWED", "INTERESTED", "DISMISSED"] as CareerOperatorState[]).map((state) => <button type="button" key={state} className={selected.operator_state === state ? "ow-primary" : "ow-secondary"} disabled={saving === selected.source_file || selected.operator_state === state} onClick={() => void updateState(selected, state)}>{state}</button>)}
        </div>
        <section className="ow-score-card"><h3>Career Intelligence</h3><div><span>Opportunity</span><i><b style={{ width: `${Math.max(0, Math.min(100, selected.opportunity_score || 0))}%` }} /></i><strong>{scoreText(selected.opportunity_score)}</strong></div><div><span>Network</span><i><b style={{ width: `${Math.max(0, Math.min(100, selected.network_access || 0))}%` }} /></i><strong>{scoreText(selected.network_access)}</strong></div>{selected.network_status && <p className="ow-score-note">Network detail: {label(selected.network_status)}</p>}</section>
        <section className="ow-facts"><div><span>Recommendation</span><Status value={selected.recommendation || "unknown"} /></div><div><span>Constraint</span><Status value={selected.constraint_action || "unknown"} /></div><div><span>Career lane</span><b>{selected.career_lane_label || label(selected.career_lane)}</b></div><div><span>Relationship</span><b>{label(selected.relationship_level)}</b></div></section>
        <section className="ow-facts"><div><span>Freshness</span><Status value={jobAgeText(selected)} /></div><div><span>Published</span><b>{displayDate(selected.publication_date || selected.provenance?.publication_date)}</b></div><div><span>First seen</span><b>{displayDate(selected.first_seen_at || selected.provenance?.first_seen_at)}</b></div><div><span>Last seen</span><b>{displayDate(selected.last_seen_at || selected.provenance?.last_seen_at)}</b></div></section>
        <section className="ow-evidence"><div><span>Matched capabilities</span>{selected.key_matched_capabilities?.length ? <ul>{selected.key_matched_capabilities.slice(0, 6).map((item, index) => <li key={`${compactItemText(item)}-${index}`}>{compactItemText(item)}</li>)}</ul> : <p>No matched capabilities projected.</p>}</div><div><span>Key risks</span>{selected.risks?.length ? <ul>{selected.risks.slice(0, 6).map((item, index) => <li key={`${compactItemText(item)}-${index}`}>{compactItemText(item)}</li>)}</ul> : <p>No key risks projected.</p>}</div></section>
        <section className="ow-facts"><div><span>Source</span><b>{selected.provenance?.source_name || "unknown"}</b></div><div><span>External id</span><b>{selected.provenance?.external_job_id || "unknown"}</b></div><div><span>Description</span><b>{label(selected.provenance?.description_quality)} · {label(selected.provenance?.description_source)}</b></div><div><span>Join</span><b>{label(selected.job_join_status)}</b></div></section>
        {selected.workspace_available ? <div className="ow-actions"><button type="button" className="ow-primary" onClick={() => setApplicationWorkspaceJob(selected.silver_job_id)}>Open Application Workspace</button>{selected.provenance?.source_url && <a className="ow-primary-link" href={selected.provenance.source_url} target="_blank" rel="noreferrer">Original job ↗</a>}</div> : <p className="ow-muted">Application Workspace opens only for joined INTERESTED, APPLY_NOW, or NETWORK_FIRST opportunities and still enforces its own gates.</p>}
      </aside> : <aside className="ow-job-detail"><p className="ow-empty">Select a Career Intelligence opportunity.</p></aside>}
    </section>
  </div>;
}

function TopFive({ payload, refresh }: { payload: ProductPayload; refresh: () => Promise<void> }) {
  const [selectedId, setSelectedId] = useState<number | null>(payload.top_jobs[0]?.silver_job_id ?? null);
  const jobs = payload.top_jobs.slice(0, 5);
  const selected = jobs.find((job) => job.silver_job_id === selectedId) || jobs[0] || null;
  return <div className="ow-stack"><header className="ow-page-header"><div><span>Application shortlist</span><h1>Top 5</h1><p>Only authoritative rankable jobs. Empty slots stay empty.</p></div><strong className="ow-big-count">{jobs.length}/5</strong></header>
    {jobs.length ? <section className="ow-top5-workspace"><div className="ow-top5-list">{jobs.map((job, index) => <button type="button" key={job.silver_job_id} className={selected?.silver_job_id === job.silver_job_id ? "selected" : ""} onClick={() => setSelectedId(job.silver_job_id)}><span className="ow-rank">#{job.product_rank || index + 1}</span><span><b>{job.title}</b><small>{employerName(job)} · {locationText(job)}</small></span><strong>{scoreText(job.overall_quality_score)}</strong></button>)}</div>{selected && <JobDetail job={selected} payload={payload} refresh={refresh} />}</section> : <section className="ow-card"><h2>No Top-5 job currently qualifies.</h2><p>The product does not fill the shortlist with weaker or stale jobs.</p></section>}
  </div>;
}

function Application({ payload, refresh }: { payload: ProductPayload; refresh: () => Promise<void> }) {
  const top = payload.top_jobs[0] || null;
  const docsReady = payload.application_sources_ready.base_cv && payload.application_sources_ready.base_application_letter;
  return <div className="ow-stack">
    <header className="ow-page-header"><div><span>Final preparation step</span><h1>Application</h1><p>Verified vacancy + Candidate Facts + approved local base documents → complete review package. Never auto-submit.</p></div></header>
    <section className="ow-application-grid">
      <article className="ow-card"><span className="ow-kicker">Selected target</span><h2>{top?.title || "No authoritative Top-5 job"}</h2>{top && <p>{employerName(top)} · {locationText(top)} · {scoreText(top.overall_quality_score)} authoritative fit</p>}<div className="ow-readiness"><div className={top ? "ready" : "blocked"}><i /><span>Top-5 target</span><b>{top ? "Ready" : "Required"}</b></div><div className={payload.application_sources_ready.base_cv ? "ready" : "blocked"}><i /><span>Base CV</span><b>{payload.application_sources_ready.base_cv ? "Approved" : "Required"}</b></div><div className={payload.application_sources_ready.base_application_letter ? "ready" : "blocked"}><i /><span>Base letter</span><b>{payload.application_sources_ready.base_application_letter ? "Approved" : "Required"}</b></div></div><OpenApplicationButton disabled={!top || !docsReady} silverJobId={top?.silver_job_id} /></article>
      <article className="ow-card ow-boundary-card"><span className="ow-kicker">Private source model</span><h2>{docsReady ? "Base documents are ready" : "Choose your two local base PDFs"}</h2><p>File bytes stay local. On your explicit Generate action, extracted text from the two approved base documents may be sent to the configured drafting provider as style/structure context. Candidate Facts remain authority for new candidate claims.</p><ul><li>Approved file bytes stay on this machine</li><li>Extracted base text is shared only on explicit Generate</li><li>Local PDF text extraction validates the approved source</li><li>No hidden auto-apply, submit or send</li></ul></article>
    </section>
    <article className="ow-card">
      <span className="ow-kicker">Your base documents</span>
      <h2>Local application sources</h2>
      <p>For the demo, select the current CV and application letter you already use. Replacing either file creates a new hash-bound approved source while preserving the same application contract.</p>
      <div className="ow-document-grid">
        <ApplicationSourceUpload documentType="base_cv" title="Base CV" ready={payload.application_sources_ready.base_cv} onUploaded={refresh} />
        <ApplicationSourceUpload documentType="base_application_letter" title="Base Letter" ready={payload.application_sources_ready.base_application_letter} onUploaded={refresh} />
      </div>
    </article>
  </div>;
}

function Applications({ payload, onPrepare }: { payload: ProductPayload; onPrepare: () => void }) {
  const top = payload.top_jobs[0] || null;
  const docsReady = payload.application_sources_ready.base_cv && payload.application_sources_ready.base_application_letter;
  const prepareReady = Boolean(top && docsReady);
  const topUrl = top ? externalJobUrl(top) : null;
  return <div className="ow-stack">
    <header className="ow-page-header"><div><span>After preparation</span><h1>Applications</h1><p>Your application portfolio after a job leaves discovery and ranking. No submitted state is invented.</p></div></header>
    <section className="ow-application-pipeline" aria-label="Application lifecycle">
      <article className={`ow-application-stage ${prepareReady ? "active" : "active"}`}><span>1 · Prepare</span><b>{prepareReady ? "Ready for review package" : "Sources incomplete"}</b><small>{prepareReady ? "The Top-5 target and both approved base documents are available." : "Complete the Application step before a grounded review package can be prepared."}</small></article>
      <article className="ow-application-stage"><span>2 · Review</span><b>Human review</b><small>CV and letter remain draft_for_review until you explicitly accept them.</small></article>
      <article className="ow-application-stage"><span>3 · Submitted</span><b>Not submitted</b><small>Submission is manual. The product must never infer this state from draft generation.</small></article>
      <article className="ow-application-stage"><span>4 · Interview</span><b>No interview recorded</b><small>Future tracking can hold interview dates, contacts, preparation notes and follow-ups.</small></article>
      <article className="ow-application-stage"><span>5 · Decision</span><b>No decision recorded</b><small>Offer, rejected and withdrawn become explicit terminal outcomes.</small></article>
    </section>
    <section className="ow-after-application-grid">
      <article className="ow-card">
        <span className="ow-kicker">Current portfolio</span>
        <h2>No submitted applications yet</h2>
        {top ? <><p>The current next candidate is <b>{top.title}</b> at {employerName(top)}. It is still before submission, so it does not appear as a fake active application.</p><div className="ow-actions"><button type="button" onClick={onPrepare}>Open Application</button>{topUrl && <a href={topUrl} target="_blank" rel="noreferrer">Original job ↗</a>}</div></> : <p className="ow-muted">No authoritative Top-5 target is currently available.</p>}
      </article>
      <article className="ow-card">
        <span className="ow-kicker">Product continuation</span>
        <h2>What this becomes after the demo</h2>
        <p>This is the natural home for submission date, application channel, recruiter/contact, next follow-up, interview rounds and final outcome. Those states should be append-only operator facts, not guesses from scraping or drafting.</p>
      </article>
    </section>
  </div>;
}

function sourceGroup(source: SourceConnector): SourceGroup {
  const strategy = source.career_source_strategy;
  if (strategy?.tier === "A") return "Strategic employers";
  if (strategy?.tier === "B") return "Adjacent employers";
  if (strategy?.source_role === "discovery" || strategy?.tier === "C") return "Discovery sources";
  return "Existing generic/demo sources";
}

function adaptiveDecisionForSuggestion(suggestedAction: string): string {
  if (suggestedAction === "PROMOTE_TO_TIER_A") return "PROMOTED_A";
  if (suggestedAction === "PROMOTE_TO_TIER_B") return "PROMOTED_B";
  if (suggestedAction === "IGNORE") return "IGNORED";
  return "WATCH";
}

function Sources({ payload, refresh }: { payload: ProductPayload; refresh: () => Promise<void> }) {
  const sources = payload.source_connector_overview.sources;
  const [selectedName, setSelectedName] = useState(sources.find((source) => source.career_source_strategy?.tier === "A")?.source_name || sources.find((source) => source.current_blocker)?.source_name || sources.find((source) => source.activation.active === true)?.source_name || sources[0]?.source_name || "");
  const [showAll, setShowAll] = useState(false);
  const [adaptiveBusyKey, setAdaptiveBusyKey] = useState<string | null>(null);
  const lifecycleGroups = ["Needs attention", "Active", "Pending", "Not implemented"];
  const adaptive = payload.source_connector_overview.adaptive_source_discovery;
  const adaptiveCandidates = adaptive?.candidates || [];
  const groups: SourceGroup[] = ["Strategic employers", "Adjacent employers", "Discovery sources", "Adaptive candidates", "Existing generic/demo sources"];
  const groupCounts = Object.fromEntries(groups.map((group) => [group, sources.filter((source) => sourceGroup(source) === group).length])) as Record<SourceGroup, number>;
  groupCounts["Adaptive candidates"] = adaptiveCandidates.length;
  const visibleGroups = groups
    .map((group) => ({
      group,
      sources: sources
        .filter((source) => sourceGroup(source) === group)
        .filter((source) => showAll || group !== "Existing generic/demo sources")
        .sort((left, right) => {
          const priorityDelta = (right.career_source_strategy?.strategic_priority || 0) - (left.career_source_strategy?.strategic_priority || 0);
          if (priorityDelta !== 0) return priorityDelta;
          return compareText(left.source_label, right.source_label);
        }),
    }))
    .filter((entry) => entry.sources.length > 0);
  const visible = visibleGroups.flatMap((entry) => entry.sources);
  const selected = sources.find((source) => source.source_name === selectedName) || visible[0] || null;
  const strategy = selected?.career_source_strategy;
  const setAdaptiveDecision = async (candidate: AdaptiveSourceCandidate, decision: string) => {
    const path = adaptive?.state_action_path || "/api/v1/career-intelligence/adaptive-sources";
    setAdaptiveBusyKey(candidate.normalized_company_key);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          normalized_company_key: candidate.normalized_company_key,
          company_name: candidate.company_name,
          decision,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.reason || `Adaptive source update failed (${response.status})`);
      }
      clearProductTruthCache();
      await refresh();
    } finally {
      setAdaptiveBusyKey(null);
    }
  };

  return <div className="ow-stack">
    <header className="ow-page-header"><div><span>Source control</span><h1>Sources</h1><p>Lingjia strategy sources are grouped above existing generic/demo sources. Lifecycle gates still own activation truth.</p></div><button type="button" className="ow-secondary" title={`Lifecycle vocabulary: ${lifecycleGroups.join(", ")}`} onClick={() => setShowAll((value) => !value)}>{showAll ? "Hide generic/demo" : `Show all ${sources.length}`}</button></header>
    <section className="ow-source-summary-strip">
      {groups.map((group) => <div key={group}><span>{group}</span><b>{groupCounts[group]}</b></div>)}
    </section>
    {adaptive?.available === false && <div className="ow-callout warn"><b>Adaptive discovery unavailable</b><span>{adaptive.reason || "Runtime source evidence is not ready."}</span></div>}
    {adaptiveCandidates.length > 0 && <section className="ow-adaptive-candidates"><div className="ow-source-group-title"><span>Adaptive candidates</span><b>{adaptiveCandidates.length}</b></div>{adaptiveCandidates.map((candidate) => {
      const recommendedDecision = adaptiveDecisionForSuggestion(candidate.suggested_action);
      const busy = adaptiveBusyKey === candidate.normalized_company_key;
      return <article className="ow-card ow-adaptive-card" key={candidate.normalized_company_key}><div><span className="ow-kicker">{label(candidate.suggested_action)} · {label(candidate.operator_decision)}</span><h2>{candidate.company_name}</h2><code>{candidate.normalized_company_key}</code></div><div className="ow-strategy-band"><div><span>Opportunities</span><b>{candidate.observed_opportunity_count}</b></div><div><span>Best score</span><b>{candidate.highest_opportunity_score}</b></div><div><span>Average</span><b>{candidate.average_opportunity_score}</b></div><div><span>Evidence</span><b>{label(candidate.evidence_quality)}</b></div></div><div className="ow-source-facts"><div><span>Employer origin</span><b>{candidate.employer_origin_evidence_available ? "available" : "not observed"}</b></div><div><span>Discovery</span><b>{candidate.discovery_source_evidence_available ? "available" : "not observed"}</b></div><div><span>Berlin</span><b>{candidate.berlin_relevance ? "yes" : "not observed"}</b></div><div><span>Remote Germany</span><b>{candidate.remote_germany_relevance ? "yes" : "not observed"}</b></div><div><span>Location conflict</span><b>{candidate.location_constraint_conflicts ? "yes" : "no"}</b></div><div><span>Lanes</span><b>{candidate.career_lanes.map(label).join(", ") || "unknown"}</b></div></div><section className="ow-evidence"><div><span>Promotion reasons</span><ul>{candidate.promotion_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div></section><div className="ow-actions"><button type="button" onClick={() => void setAdaptiveDecision(candidate, "PROMOTED_A")} disabled={busy}>Promote to Tier A</button><button type="button" onClick={() => void setAdaptiveDecision(candidate, "PROMOTED_B")} disabled={busy}>Promote to Tier B</button><button type="button" onClick={() => void setAdaptiveDecision(candidate, "WATCH")} disabled={busy || recommendedDecision === "WATCH"}>Watch</button><button type="button" onClick={() => void setAdaptiveDecision(candidate, "IGNORED")} disabled={busy}>Ignore</button></div></article>;
    })}</section>}
    <section className="ow-source-workspace">
      <div className="ow-source-list">{visibleGroups.map(({ group, sources: groupedSources }) => <div key={group}><div className="ow-source-group-title"><span>{group}</span><b>{groupedSources.length}</b></div>{groupedSources.map((source) => <button type="button" key={source.source_name} className={selected?.source_name === source.source_name ? "selected" : ""} onClick={() => setSelectedName(source.source_name)}><span><b>{source.source_label}</b><small>{source.source_name}</small></span><span className="ow-source-mini"><Status value={source.career_source_strategy?.source_status || source.current_blocker || source.activation.status} /><small>{source.career_source_strategy?.source_role || "generic"}</small></span></button>)}</div>)}</div>
      {selected && <article className="ow-card ow-source-detail"><span className="ow-kicker">{sourceGroup(selected)} · {selected.source_type}</span><h2>{selected.source_label}</h2><code>{selected.source_name}</code>{strategy?.configured ? <div className="ow-strategy-band"><div><span>Tier</span><b>{strategy.tier} · {strategy.tier_label}</b></div><div><span>Priority</span><b>{strategy.strategic_priority}</b></div><div><span>Role</span><b>{label(strategy.source_role)}</b></div><div><span>Status</span><b>{label(strategy.source_status)}</b></div></div> : <div className="ow-callout warn"><b>Existing generic/demo source</b><span>This source remains available but is not part of Lingjia's target-source strategy.</span></div>}{selected.career_source_advisory && <div className="ow-callout neutral"><b>Source advisory: {label(selected.career_source_advisory.status)}</b><span>{selected.career_source_advisory.reasons?.join(" · ") || "No advisory detail."}</span></div>}<div className="ow-source-facts"><div><span>Implementation</span><b>{label(selected.connector.implementation_status)}</b></div><div><span>Validation</span><b>{label(selected.gates.connector_validation_gate.status)}</b></div><div><span>Approval</span><b>{label(selected.gates.final_approval_gate.status)}</b></div><div><span>Activation</span><b>{label(selected.activation.status)}</b></div><div><span>Profiles</span><b>{selected.search_profiles.active_profile_count}/{selected.search_profiles.profile_count} active</b></div><div><span>Layers</span><b>Bronze {selected.layers.bronze_count} · Silver {selected.layers.silver_count}</b></div></div>{strategy?.configured && <section className="ow-evidence"><div><span>Career lanes</span>{strategy.relevant_career_lanes?.length ? <ul>{strategy.relevant_career_lanes.map((lane) => <li key={lane}>{label(lane)}</li>)}</ul> : <p>No configured lanes.</p>}</div><div><span>Location relevance</span>{strategy.location_relevance?.length ? <ul>{strategy.location_relevance.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No location relevance configured.</p>}</div></section>}{selected.current_blocker ? <div className="ow-callout warn"><b>{label(selected.current_blocker)}</b><span>{selected.next_action}</span></div> : <div className="ow-callout good"><b>No current blocker</b><span>{selected.next_action}</span></div>}</article>}
    </section>
  </div>;
}

function Approvals({ payload }: { payload: ProductPayload }) {
  const waiting = payload.source_connector_overview.sources.filter((source) => source.current_blocker === "final_approval_incomplete");
  return <div className="ow-stack"><header className="ow-page-header"><div><span>Human authority</span><h1>Approvals</h1><p>Only real authority decisions belong here. Technical work stays in Sources.</p></div><strong className="ow-big-count">{waiting.length}</strong></header><section className="ow-approval-grid"><article className="ow-card"><h2>{waiting.length ? "Final source approvals" : "Nothing waiting"}</h2>{waiting.length ? waiting.map((source) => <div className="ow-approval-row" key={source.source_name}><span><b>{source.source_label}</b><small>{source.next_action}</small></span><Status value="approval_required" /></div>) : <p className="ow-muted">No source approval decision is currently waiting.</p>}</article><article className="ow-card"><h2>Product-level gates</h2>{payload.operator_blockers.length ? payload.operator_blockers.map((blocker) => <div className="ow-approval-row" key={blocker.code}><span><b>{blocker.title}</b><small>{blocker.detail}</small></span></div>) : <p className="ow-muted">No product-level approval blocker.</p>}</article></section></div>;
}

function Operations({ payload }: { payload: ProductPayload }) {
  const overview = payload.source_connector_overview.summary;
  const stages: Array<[string, number]> = [["Known", overview.source_count], ["Implemented", overview.implemented_count], ["Validated", overview.validated_count], ["Approved", overview.final_approved_count], ["Registered", overview.registered_count], ["Active", overview.active_count], ["Ingested", overview.ingested_count]];
  return <div className="ow-stack"><header className="ow-page-header"><div><span>Runtime truth</span><h1>Operations</h1><p>Observability and lifecycle health, separated from daily job review.</p></div></header><section className="ow-card"><h2>Source lifecycle</h2><div className="ow-pipeline">{stages.map(([name, value]) => <div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div></section><section className="ow-metrics"><Metric labelText="Current active" value={payload.summary.current_active_job_count} helper="all persisted vacancies" /><Metric labelText="Review scope current" value={payload.summary.review_scope_current_active_job_count ?? payload.job_readiness.filter(isCurrent).length} helper="visible vacancies" /><Metric labelText="Stale" value={payload.summary.stale_job_count} helper="refresh required" /><Metric labelText="Attention sources" value={overview.attention_count} helper="need action" /></section></div>;
}

const navItems: Array<{ id: View; label: string; glyph: string }> = [
  { id: "overview", label: "Overall", glyph: "◉" },
  { id: "jobs", label: "All jobs", glyph: "≡" },
  { id: "career", label: "Career Intel", glyph: "◇" },
  { id: "top5", label: "Top 5", glyph: "★" },
  { id: "application", label: "Application", glyph: "↗" },
  { id: "applications", label: "Applications", glyph: "◎" },
  { id: "sources", label: "Sources", glyph: "⌁" },
  { id: "approvals", label: "Approvals", glyph: "✓" },
  { id: "operations", label: "Operations", glyph: "⌘" },
];

export default function OperatorWorkspace() {
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("overview");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let active = true;

    readProductTruth<ProductPayload>()
      .then((truth) => {
        if (active) setPayload(truth);
      })
      .catch((reason: unknown) => {
        if (active) setError(String(reason));
      });

    return () => {
      active = false;
    };
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      setPayload(await readProductTruth<ProductPayload>({ fresh: true }));
      setError(null);
    } finally {
      setRefreshing(false);
    }
  };

  if (error) return <main className="ow-fatal"><div><span>Fail closed</span><h1>Control Center unavailable</h1><pre>{error}</pre></div></main>;
  if (!payload) return <main className="ow-loading"><div /><p>Reading Product V1 truth…</p></main>;

  const navBadges: Partial<Record<View, number>> = {
    jobs: payload.summary.review_scope_current_active_job_count ?? payload.job_readiness.filter(isCurrent).length,
    career: payload.career_intelligence?.summary?.opportunity_count,
    top5: payload.summary.top_job_count,
    approvals: payload.source_connector_overview.sources.filter((source) => source.current_blocker === "final_approval_incomplete").length,
    sources: payload.source_connector_overview.summary.attention_count,
  };

  return <div className="ow-shell">
    <aside className="ow-sidebar">
      <div className="ow-brand"><div>DO</div><span><b>Deep Ocean</b><small>Intelligence</small></span></div>
      <nav aria-label="Primary navigation">{navItems.map((item, index) => <div key={item.id} className={index === 5 ? "ow-nav-break" : undefined}><button type="button" className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><i>{item.glyph}</i><span>{item.label}</span>{navBadges[item.id] != null && <b>{navBadges[item.id]}</b>}</button></div>)}</nav>
      <footer><span><i /> DB truth</span><small>Product V1 · review-first</small></footer>
    </aside>
    <div className="ow-content-shell">
      <header className="ow-topline"><div><b>{navItems.find((item) => item.id === view)?.label}</b><span>DEMO-001 · Personio pilot</span></div><button type="button" disabled={refreshing} onClick={() => void refresh()}>{refreshing ? "Refreshing…" : "↻ Refresh"}</button></header>
      <main className="ow-main">{view === "overview" && <Overview payload={payload} onNavigate={setView} />}{view === "jobs" && <Jobs payload={payload} refresh={refresh} />}{view === "career" && <CareerIntelligence payload={payload} refresh={refresh} />}{view === "top5" && <TopFive payload={payload} refresh={refresh} />}{view === "application" && <Application payload={payload} refresh={refresh} />}{view === "applications" && <Applications payload={payload} onPrepare={() => setView("application")} />}{view === "sources" && <Sources payload={payload} refresh={refresh} />}{view === "approvals" && <Approvals payload={payload} />}{view === "operations" && <Operations payload={payload} />}</main>
    </div>
  </div>;
}
