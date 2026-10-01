import { useEffect, useState } from 'react';
import { api, type AuditEntry } from '../lib/api';

export function Audit() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [limit, setLimit] = useState(200);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (lim: number) => {
    setLoading(true);
    try {
      const { entries } = await api.audit(lim);
      setEntries(entries);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(limit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyLimit = () => void load(Math.max(1, Math.min(1000, limit)));

  return (
    <div>
      <h2 className="view-title">Audit Log</h2>
      <p className="view-sub">
        Append-only record of every tool call, approval, file access, and LLM call the team makes.
      </p>

      {error && <div className="error">{error}</div>}

      <div className="row" style={{ marginBottom: 12 }}>
        <label className="meta" htmlFor="audit-limit">Entries</label>
        <input
          id="audit-limit"
          type="text"
          value={limit}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!Number.isNaN(n)) setLimit(n);
          }}
          style={{ width: 80 }}
        />
        <button className="btn-ghost btn" onClick={applyLimit}>Apply</button>
        <div className="spacer" />
        <button className="btn-ghost btn" onClick={applyLimit}>Refresh</button>
      </div>

      {loading && <div className="meta">Loading audit entries…</div>}

      {!loading && entries.length === 0 && (
        <div className="empty">No audit entries yet.</div>
      )}

      {!loading && entries.length > 0 && (
        <div className="card" style={{ padding: '4px 8px' }}>
          <table className="audit">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Detail</th>
                <th>Plan</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={i}>
                  <td className="mono" style={{ whiteSpace: 'nowrap' }}>{e.ts}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{e.actor}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{e.action}</td>
                  <td style={{ maxWidth: 420 }}>{e.detail}</td>
                  <td className="mono">{e.plan_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
