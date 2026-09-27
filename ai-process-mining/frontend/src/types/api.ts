export interface Dataset {
  id: string;
  name: string;
  status: "processing" | "ready" | "failed";
  error: string | null;
  file_size_bytes: number;
  created_at: string;
  validation_report: ValidationReport | null;
}

export interface ValidationReport {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  missing_case_ids: number;
  missing_activities: number;
  invalid_timestamps: number;
  impossible_timestamps: number;
  malformed_rows: number;
  single_event_cases: number;
  total_cases: number;
  columns_detected: string[];
  optional_columns_present: string[];
  timezone_assumed_for_naive_timestamps: string;
  counting_rule: string;
  warnings: string[];
  activity_name_merges?: Record<string, string[]>;
}

export interface InvalidRow {
  source_row: number;
  issue: string;
  detail: string;
  raw: Record<string, unknown> | null;
}

export interface Overview {
  total_cases: number;
  total_events: number;
  completed_cases: number;
  incomplete_cases: number;
  completion_activities: string[];
  avg_case_duration_hours: number | null;
  median_case_duration_hours: number | null;
  p90_case_duration_hours: number | null;
  p95_case_duration_hours: number | null;
  unique_activities: number;
  unique_variants: number;
  deviation_rate_pct: number;
  conformance_rate_pct: number;
  dominant_path: string[];
  top10_variant_coverage_pct: number;
  first_event: string | null;
  last_event: string | null;
  processing_time_available: boolean;
  engine_processing_ms: number;
}

export interface GraphNode {
  id: string;
  activity: string;
  count: number;
  cases: number;
  case_pct: number;
  avg_duration_hours: number | null;
  median_duration_hours: number | null;
  avg_position: number | null;
  is_start: boolean;
  is_end: boolean;
  start_count: number;
  end_count: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  frequency: number;
  cases: number;
  case_pct: number;
  avg_transition_hours: number | null;
  median_transition_hours: number | null;
  p90_transition_hours: number | null;
}

export interface ProcessGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_cases: number;
  timing_semantics: string;
}

export interface BottleneckRow {
  activity: string;
  frequency: number;
  affected_cases: number;
  affected_cases_pct: number;
  long_wait_cases: number;
  average_waiting_time_hours: number | null;
  median_waiting_time_hours: number | null;
  p90_waiting_time_hours: number | null;
  p95_waiting_time_hours: number | null;
  median_processing_time_hours: number | null;
  wait_share_pct: number | null;
  score: number | null;
  indicator: "HIGH" | "MEDIUM" | "LOW" | "NOT_SCORED";
  components: Record<string, number | null> | null;
  not_scored_reason: string | null;
}

export interface Bottlenecks {
  activities: BottleneckRow[];
  slow_transitions: {
    source: string; target: string; frequency: number;
    median_transition_hours: number | null; p90_transition_hours: number | null; total_wait_share_pct: number | null;
  }[];
  methodology: {
    formula: string;
    weights_used: Record<string, number>;
    processing_time_available: boolean;
    thresholds: { HIGH: number; MEDIUM: number };
    long_wait_rule: string;
    caveat: string;
  };
}

export interface DeviationType {
  type: string;
  occurrences: number;
  cases: number;
  case_pct: number;
  top_activities: { activity: string; occurrences: number }[];
}

export interface DeviationItem {
  case_id: string;
  type: string;
  activity: string;
  timestamp: string | null;
  description: string;
}

export interface Deviations {
  summary: { total_deviations: number; cases_with_deviations: number; deviation_rate_pct: number;
    by_type: DeviationType[]; delay_rule: string };
  conformance: { method: string; dominant_path_text: string; conformance_rate_pct: number;
    avg_dominant_path_coverage_pct: number; cases_with_missing_activities: number;
    cases_with_unexpected_activities: number; cases_with_rework: number; cases_with_loops: number;
    cases_with_extra_steps: number };
  total: number;
  offset: number;
  limit: number;
  items: DeviationItem[];
}

export interface Variant {
  variant_id: string;
  trace: string[];
  trace_text: string;
  length: number;
  case_count: number;
  percentage_of_cases: number;
  cumulative_pct: number;
  avg_duration_hours: number | null;
  median_duration_hours: number | null;
}

export interface Variants {
  summary: { unique_variants: number; coverage_statement: string; top10_coverage_pct: number;
    variants_for_80pct_coverage: number; definition: string };
  total: number;
  items: Variant[];
}

export interface ResourceRow {
  resource: string;
  department: string | null;
  events: number;
  cases_handled: number;
  distinct_activities: number;
  top_activities: string[];
  avg_waiting_time_hours: number | null;
  median_waiting_time_hours: number | null;
  avg_case_duration_hours: number | null;
  rework_rate_pct: number | null;
}

export interface Resources {
  available: boolean;
  resources: ResourceRow[];
  disclaimer: string;
  definitions?: Record<string, string>;
}

export interface EventRow {
  case_id: string;
  activity: string;
  original_activity: string;
  timestamp: string;
  prev_activity: string | null;
  wait_h: number | null;
  resource: string | null;
  department: string | null;
  amount: number | null;
  source_row: number;
}

export interface CaseDetail {
  case_id: string;
  variant_id: string;
  trace: string[];
  trace_text: string;
  duration_hours: number;
  events: EventRow[];
  deviations: DeviationItem[];
}

export interface Evidence { fact_id?: string; metric: string; value: string; source?: string }

export interface Drilldown {
  kind: "activity" | "transition" | "deviation" | "variant" | "overview" | "resource";
  activity?: string | null; source?: string | null; target?: string | null;
  deviation_type?: string | null; variant_id?: string | null; resource?: string | null;
}

export interface Finding {
  title: string;
  description: string;
  evidence: Evidence[];
  severity: "low" | "medium" | "high";
  possible_explanations: string[];
  recommended_investigations: string[];
  drilldown: Drilldown | null;
}

export interface AnalysisReport {
  summary: string;
  key_findings: Finding[];
  data_quality_notes: string[];
  limitations: string[];
  additional_data_suggestions: string[];
  guardrail_flags: string[];
  generated_by: { mode: string; model: string | null; prompt_version: string };
}

export interface QueryAnswer {
  answer: string;
  evidence: Evidence[];
  tools_used: string[];
  mode: "llm" | "deterministic";
  flags: string[];
  prompt_version: string;
}
