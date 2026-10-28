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
}

export interface CorrectionCreate {
  readonly analysis_id?: string | null;
  readonly file?: string | null;
  readonly language?: string | null;
  readonly source_code: string;
  readonly issue: CorrectionIssueRef;
  readonly protheus_version?: string | null;
}

export type CorrectionStatus = 'pending' | 'approved' | 'rejected';
export type PostValidationStatus = 'passed' | 'failed' | 'not_run';
export type CorrectionExportFormat = 'corrected' | 'diff' | 'json';

export interface PostValidation {
  readonly status: PostValidationStatus;
  readonly target_resolved: boolean;
  readonly issues: readonly AnalysisIssue[];
  readonly summary: string;
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
