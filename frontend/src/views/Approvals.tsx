import { useEffect, useState } from 'react';
import { api, type Approval } from '../lib/api';

export function Approvals({ onDecision }: { onDecision: () => void }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const { approvals } = await api.approvals();
      setApprovals(approvals);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load approvals');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const decide = async (id: string, approved: boolean) => {
    setWorking(id);
    setError('');
    try {
      await api.decideApproval(id, approved, notes[id] ?? '');
      setApprovals((prev) => prev.filter((a) => a.id !== id));
      onDecision();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision');
    } finally {
      setWorking(null);
    }
  };

  return (
    <div>
      <h2 className="view-title">Approvals</h2>
      <p className="view-sub">
        Agents propose file writes and code executions. Nothing is executed until you approve it here.
      </p>

      {error && <div className="error">{error}</div>}

      <div className="row" style={{ marginBottom: 12 }}>
        <span className="view-sub" style={{ margin: 0 }}>{approvals.length} pending</span>
        <div className="spacer" />
        <button className="btn-ghost btn" onClick={() => void load()}>Refresh</button>
      </div>

      {loading && <div className="meta">Loading approvals…</div>}

      {!loading && approvals.length === 0 && (
        <div className="empty">No pending approvals. Proposed actions will appear here.</div>
      )}

      {approvals.map((a) => (
        <div className="card approval-card" key={a.id}>
          <div className="approval-summary">{a.summary}</div>
          <div className="approval-kind">
            {a.kind === 'file_write' ? 'File write' : 'Code execution'} &middot;{' '}
            proposed in plan <span className="mono">{a.plan_id}</span>, step{' '}
            <span className="mono">{a.step_id}</span> &middot;{' '}
            <span className="mono">{a.created_at}</span>
          </div>
          <div className="meta" style={{ marginBottom: 6 }}>Payload preview</div>
          <pre className="preview">{a.payload_preview}</pre>
          <div className="approval-actions">
            <input
              type="text"
              placeholder="Optional note for the agent…"
              value={notes[a.id] ?? ''}
              onChange={(e) => setNotes((prev) => ({ ...prev, [a.id]: e.target.value }))}
            />
            <button
              className="btn"
              disabled={working === a.id}
              onClick={() => void decide(a.id, true)}
            >
              {working === a.id ? 'Working…' : 'Approve'}
            </button>
            <button
              className="btn btn-danger"
              disabled={working === a.id}
              onClick={() => void decide(a.id, false)}
            >
              Deny
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
