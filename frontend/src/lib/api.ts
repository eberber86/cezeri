/**
 * Single module wrapping all sidecar HTTP calls.
 * Base URL comes from one constant: SIDECAR_BASE_URL.
 * The sidecar API is defined in ~/workspace/cezeri/docs/CONTRACT.md.
 */

export const SIDECAR_BASE_URL = 'http://127.0.0.1:8765';

export type Target = 'team' | 'viral_immunologist' | 'molecular_virologist' | 'scientific_writer';

export type StepStatus =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'done'
  | 'failed'
  | 'skipped';

export type PlanStatus = 'queued' | 'running' | 'awaiting_approval' | 'done' | 'failed';

export type ApprovalKind = 'file_write' | 'code_exec';
export type ApprovalStatus = 'pending' | 'approved' | 'denied';

export interface PlanStep {
  id: string;
  agent: string;
  label: string;
  status: StepStatus;
  detail?: string | null;
  result?: string | null;
}

export interface Plan {
  id: string;
  title: string;
  target: string;
  status: PlanStatus;
  steps: PlanStep[];
  created_at: string;
  error?: string | null;
}

export interface PlanSummary {
  id: string;
  title: string;
  status: PlanStatus;
  created_at: string;
}

export interface Approval {
  id: string;
  plan_id: string;
  step_id: string;
  kind: ApprovalKind;
  summary: string;
  payload_preview: string;
  status: ApprovalStatus;
  created_at: string;
}

export interface AuditEntry {
  ts: string;
  actor: string;
  action: string;
  detail: string;
  plan_id?: string | null;
}

export interface AppConfig {
  provider: string;
  model: string;
  approved_dirs: string[];
  has_key: boolean;
}

export interface Health {
  status: string;
  version: string;
  provider: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(SIDECAR_BASE_URL + path, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Sidecar ${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json() as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<Health>('/health'),

  chat: (target: Target, message: string) =>
    request<{ plan_id: string; status: string }>(
      '/chat',
      jsonInit('POST', { target, message })
    ),

  plans: () => request<{ plans: PlanSummary[] }>('/plans'),

  plan: (id: string) => request<Plan>(`/plans/${encodeURIComponent(id)}`),

  approvals: () => request<{ approvals: Approval[] }>('/approvals?status=pending'),

  decideApproval: (id: string, approved: boolean, note: string) =>
    request<{ ok: boolean }>(
      `/approvals/${encodeURIComponent(id)}/decision`,
      jsonInit('POST', { approved, note })
    ),

  audit: (limit = 200) =>
    request<{ entries: AuditEntry[] }>(`/audit?limit=${limit}`),

  config: () => request<AppConfig>('/config'),

  updateConfig: (cfg: { provider: string; model: string; approved_dirs: string[] }) =>
    request<{ ok: boolean }>('/config', jsonInit('PUT', cfg)),

  setKey: (api_key: string) =>
    request<{ ok: boolean }>('/key', jsonInit('POST', { api_key })),
};

export function agentDisplayName(agent: string): string {
  switch (agent) {
    case 'team':
    case 'orchestrator':
      return 'Team (Orchestrator)';
    case 'viral_immunologist':
      return 'Viral Immunologist';
    case 'molecular_virologist':
      return 'Molecular Virologist';
    case 'scientific_writer':
      return 'Scientific Writer';
    default:
      return agent;
  }
}

export function isTerminalStatus(status: PlanStatus): boolean {
  return status === 'done' || status === 'failed';
}
