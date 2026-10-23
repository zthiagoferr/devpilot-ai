/** API contract mirroring `app/schemas/analysis.py`. */

export interface AnalysisIssue {
  readonly severity?: string | null;
  readonly message: string;
  readonly line?: number | null;
}

export interface AnalysisResult {
  readonly score?: number | null;
  readonly summary?: string | null;
  readonly issues?: readonly AnalysisIssue[] | null;
  readonly status?: string | null;
  readonly report?: unknown;
  readonly insights?: unknown;
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

export interface CreateAnalysisRequest {
  readonly task: string;
  readonly project_name: string;
  readonly source_code: string;
  readonly repository_url?: string | null;
}

export interface OrchestratorStatus {
  readonly agent: string;
  readonly responsibility: string;
  readonly status: string;
}
