/** API contract mirroring `app/schemas/analysis.py`, `app/api/github.py` and
 * `app/schemas/correction.py`.
 *
 * Optional multi-language fields are omitted by the backend when they do not
 * apply, so every property added after the original Python-only contract is
 * optional here.
 */

/** Languages with a deterministic validator in the backend. */
export type LanguageId = 'python' | 'advpl' | 'html' | 'css' | 'javascript';

/** Detection outcome, which may still be `unknown` for unrecognized input. */
export type DetectedLanguageId = LanguageId | 'unknown';

/** Explicit language selection sent with an analysis. */
export type AnalysisLanguage = LanguageId | 'auto';

/** How the backend picked the language of an analysis. */
export type LanguageSource = 'manual' | 'extension' | 'content' | 'fallback';

/** Where one issue came from. */
export type IssueOrigin = 'validator' | 'ai' | 'mixed';

/** Kind of deterministic or AI analysis that produced an issue. */
export type AnalysisKind = 'heuristic_validation' | 'ia_analysis' | 'official_validation';

/** Confidence of a validation score, distinct from detection confidence. */
export type ScoreStatus = 'evaluated' | 'partial' | 'skipped' | 'unavailable';

/** What a validator checked and which limits apply to its findings. */
export interface AnalysisCoverage {
  readonly score_status?: ScoreStatus | null;
  readonly checks?: readonly string[] | null;
  readonly limitations?: readonly string[] | null;
}

export interface AnalysisIssue {
  readonly severity?: string | null;
  readonly message: string;
  readonly line?: number | null;
  readonly column?: number | null;
  readonly cause?: string | null;
  readonly file?: string | null;
  readonly language?: string | null;
  readonly origin?: IssueOrigin | null;
  readonly analysis_kind?: AnalysisKind | null;
  readonly code?: string | null;
  readonly rule_id?: string | null;
}

export interface AnalysisResult {
  readonly score?: number | null;
  readonly summary?: string | null;
  readonly issues?: readonly AnalysisIssue[] | null;
  readonly status?: string | null;
  readonly report?: unknown;
  readonly insights?: unknown;
  readonly language?: string | null;
  readonly language_source?: LanguageSource | null;
  readonly confidence?: number | null;
  readonly corrections_available?: boolean | null;
  /** No structural validator ran; ``score`` is a neutral 100, not an evaluation. */
  readonly validation_skipped?: boolean | null;
  /** Confidence of the score itself (evaluated/partial/skipped/unavailable). */
  readonly score_status?: ScoreStatus | null;
  /** Coverage keyed by language; absent on legacy or Python-only payloads. */
  readonly coverage?: Readonly<Record<string, AnalysisCoverage>> | null;
}

export interface Analysis {
  readonly id: string;
  readonly task: string;
  readonly project_name: string;
  readonly source_code: string;
  readonly repository_url: string | null;
  readonly result: AnalysisResult | null;
  readonly status: string | null;
  readonly created_at: string;
}

/** One source file supplied as repository context for an analysis. */
export interface RepositoryContextFile {
  readonly path: string;
  readonly source_code: string;
  readonly language?: string | null;
}

/** Optional deterministic repository metadata sent with an analysis. */
export interface RepositoryContext {
  readonly files: readonly RepositoryContextFile[];
  readonly paths?: readonly string[] | null;
  readonly tree_complete?: boolean;
  readonly truncated?: boolean;
  readonly apps_json?: Readonly<Record<string, unknown>> | null;
  readonly apps_json_path?: string | null;
}

export interface CreateAnalysisRequest {
  readonly task: string;
  readonly project_name: string;
  readonly source_code: string;
  readonly repository_url?: string | null;
  readonly branch?: string | null;
  readonly file_path?: string | null;
  readonly language?: AnalysisLanguage;
  readonly protheus_version?: string | null;
  readonly repository_context?: RepositoryContext | null;
}

/** One analyzable file returned by `POST /repositories/load`. */
export interface RepositoryFile {
  readonly path: string;
  readonly size?: number | null;
  readonly source_code?: string | null;
  readonly language?: string | null;
  readonly language_source?: LanguageSource | null;
  readonly confidence?: number | null;
}

export interface RepositoryLoadRequest {
  readonly repository_url: string;
  readonly branch?: string | null;
  readonly language?: AnalysisLanguage | null;
}

export type RelationStatus = 'resolved' | 'missing' | 'external' | 'unknown';
export interface RelationEdge {
  readonly source: string;
  readonly target: string;
  readonly kind: string;
  readonly raw: string;
  readonly status: RelationStatus | string;
  readonly line?: number | null;
  readonly column?: number | null;
}

export interface RelationNode {
  readonly path: string;
  readonly language: string;
  readonly present: boolean;
}

export interface RelationsSummary {
  readonly resolved: number;
  readonly missing: number;
  readonly external: number;
  readonly unknown: number;
}

/** Protheus `apps.json` discovery metadata; never its contents. */
export interface ProtheusAppsJson {
  readonly path?: string | null;
  readonly present?: boolean;
  readonly parsed?: boolean;
  readonly applications?: number;
  readonly keys?: readonly string[];
}

export interface Relations {
  readonly version: number;
  readonly generated_by: string;
  readonly truncated: boolean;
  readonly tree_complete: boolean;
  readonly summary: RelationsSummary;
  readonly edges: readonly RelationEdge[];
  readonly nodes: readonly RelationNode[];
  readonly protheus?: { readonly apps_json?: ProtheusAppsJson | null } | null;
  readonly error?: string | null;
}

export interface RepositoryLoad {
  readonly files: readonly RepositoryFile[];
  readonly truncated: boolean;
  readonly message?: string | null;
  readonly paths?: readonly string[] | null;
  readonly tree_complete?: boolean;
  readonly relations?: Relations | null;
  readonly protheus?: ProtheusAppsJson | null;
}

/** Issue reference sent when requesting one AI correction. */
export interface CorrectionIssueRef {
  readonly message: string;
  readonly severity?: string;
  readonly line?: number | null;
  readonly column?: number | null;
  readonly rule_id?: string | null;
  readonly code?: string | null;
  readonly cause?: string | null;
}

/** Repository path metadata used by the post-validation reference checks. */
export interface CorrectionRepositoryContext {
  readonly paths?: readonly string[] | null;
  readonly tree_complete?: boolean;
  readonly truncated?: boolean;
}

/** One issue (default) or every listed issue of the file in one AI pass. */
export type CorrectionMode = 'single' | 'full';

export interface CorrectionCreate {
  readonly analysis_id?: string | null;
  readonly file?: string | null;
  readonly language?: string | null;
  readonly source_code: string;
  /**
   * Correction mode. Omitted keeps the historical single-issue behaviour, so
   * existing clients do not need to change.
   */
  readonly mode?: CorrectionMode;
  /** Required in single mode; optional in full mode. */
  readonly issue?: CorrectionIssueRef | null;
  /** Targets for full mode; omitted means "derive from the baseline". */
  readonly issues?: readonly CorrectionIssueRef[];
  readonly protheus_version?: string | null;
  readonly repository_context?: CorrectionRepositoryContext | null;
}

export type CorrectionStatus = 'pending' | 'approved' | 'rejected';
export type PostValidationStatus = 'passed' | 'failed' | 'not_run';
export type CorrectionExportFormat = 'corrected' | 'diff' | 'json';

export interface PostValidation {
  readonly status: PostValidationStatus;
  readonly target_resolved: boolean;
  /** Every finding after the correction (historical contract). */
  readonly issues: readonly AnalysisIssue[];
  readonly summary: string;
  /** Original findings the correction resolved (additive, optional on legacy payloads). */
  readonly issues_resolved?: readonly AnalysisIssue[] | null;
  /** Original findings that persist after the correction. */
  readonly issues_remaining?: readonly AnalysisIssue[] | null;
  /** New relevant findings introduced by the correction (critical/high/medium). */
  readonly issues_new?: readonly AnalysisIssue[] | null;
  /** New low/info findings: visible, but they do not fail the status. */
  readonly issues_warnings?: readonly AnalysisIssue[] | null;
}

export interface Correction {
  readonly id: string;
  readonly analysis_id: string | null;
  readonly language: string;
  readonly file: string | null;
  readonly issue_ref: string;
  readonly original_code: string;
  readonly corrected_code: string;
  readonly diff: string;
  readonly explanation: string;
  readonly origin: 'ai';
  readonly post_validation: PostValidation;
  readonly status: CorrectionStatus;
  readonly model: string | null;
  readonly protheus_version: string | null;
  readonly created_at: string;
  readonly decided_at: string | null;
}

export interface CorrectionDecision {
  readonly status: 'approved' | 'rejected';
}

/** One file of a batch correction request. */
export interface CorrectionBatchFile {
  readonly path: string;
  readonly source_code: string;
  /** Targets of the full correction; omitted asks the backend to derive them. */
  readonly issues?: readonly CorrectionIssueRef[];
}

/**
 * Request body for `POST /corrections/batch`.
 *
 * One batch-level language (when set) overrides detection for every file, and
 * the repository context is shared by the reference checks of all files.
 */
export interface CorrectionBatchCreate {
  readonly analysis_id?: string | null;
  readonly files: readonly CorrectionBatchFile[];
  readonly language?: string | null;
  readonly protheus_version?: string | null;
  readonly repository_context?: CorrectionRepositoryContext | null;
}

export type CorrectionBatchItemStatus = 'completed' | 'failed' | 'skipped';

/**
 * Outcome of one file inside a batch.
 *
 * A non-completed item never carries source code: only a bounded reason and a
 * sanitized backend detail. A completed item carries the persisted correction,
 * still pending, so approval stays per file.
 */
export interface CorrectionBatchItem {
  readonly path: string;
  readonly status: CorrectionBatchItemStatus;
  readonly correction?: Correction | null;
  readonly issues_targeted: number;
  readonly error_code?: string | null;
  readonly error_status?: number | null;
  readonly error_detail?: string | null;
  readonly reason?: string | null;
}

/** Aggregated result of a batch correction. */
export interface CorrectionBatchResponse {
  readonly results: readonly CorrectionBatchItem[];
  readonly files_total: number;
  readonly files_completed: number;
  readonly files_failed: number;
  readonly files_skipped: number;
  readonly issues_resolved_total: number;
  readonly issues_remaining_total: number;
  readonly issues_new_total: number;
  readonly partial: boolean;
  readonly budget_exceeded: boolean;
}

/** Raw download returned by `GET /corrections/{id}/export`. */
export interface CorrectionExport {
  readonly blob: Blob;
  readonly filename: string | null;
  readonly contentType: string | null;
}

export interface OrchestratorStatus {
  readonly agent: string;
  readonly responsibility: string;
  readonly status: string;
}
