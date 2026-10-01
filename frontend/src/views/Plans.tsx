import { useEffect, useState } from 'react';
import { api, agentDisplayName, isTerminalStatus, type Plan, type PlanSummary } from '../lib/api';
import { StatusPill } from '../components/StatusPill';

const POLL_MS = 3000;

export function Plans() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadList = async () => {
    try {
      const { plans } = await api.plans();
      setPlans(plans);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plans');
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (id: string) => {
    try {
      const plan = await api.plan(id);
      setDetail(plan);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plan detail');
    }
  };

  useEffect(() => {
    void loadList();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedId);
    const t = window.setInterval(async () => {
      const plan = await api.plan(selectedId).catch(() => null);
      if (plan) {
        setDetail(plan);
        if (isTerminalStatus(plan.status)) window.clearInterval(t);
      }
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [selectedId]);

  return (
    <div>
      <h2 className="view-title">Plans</h2>
      <p className="view-sub">
        Multi-step runs created by the team. Select a plan to see per-agent step progress.
      </p>

      {error && <div className="error">{error}</div>}

      <div className="row" style={{ marginBottom: 12 }}>
        <span className="view-sub" style={{ margin: 0 }}>{plans.length} plans</span>
        <div className="spacer" />
        <button className="btn-ghost btn" onClick={() => void loadList()}>Refresh</button>
      </div>

      {loading && <div className="meta">Loading plans…</div>}

      {!loading && plans.length === 0 && (
        <div className="empty">No plans yet. Start one from the Chat view.</div>
      )}

      {plans.map((p) => (
        <div
          key={p.id}
          className={`plan-row${selectedId === p.id ? ' selected' : ''}`}
          onClick={() => setSelectedId(p.id)}
        >
          <div style={{ flex: 1 }}>
            <div className="title">{p.title}</div>
            <div className="ts mono">{p.id} &middot; {p.created_at}</div>
          </div>
          <StatusPill status={p.status} />
        </div>
      ))}

      {detail && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{detail.title}</div>
              <div className="meta mono">
                {detail.id} &middot; {agentDisplayName(detail.target)} &middot; {detail.created_at}
              </div>
            </div>
            <div className="spacer" />
            <StatusPill status={detail.status} />
          </div>
          {detail.steps.length === 0 && <div className="meta">No steps yet.</div>}
          {detail.steps.map((step) => (
            <div className="step" key={step.id}>
              <div className="step-head">
                <span className="step-agent">{agentDisplayName(step.agent)}</span>
                <StatusPill status={step.status} />
              </div>
              <div className="step-label">{step.label}</div>
              {step.detail && <div className="step-detail">{step.detail}</div>}
              {step.result && <div className="step-result">{step.result}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
