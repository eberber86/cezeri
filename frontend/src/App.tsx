import { useEffect, useState } from 'react';
import { api, SIDECAR_BASE_URL, type Health } from './lib/api';
import { Chat } from './views/Chat';
import { Plans } from './views/Plans';
import { Approvals } from './views/Approvals';
import { Audit } from './views/Audit';
import { Settings } from './views/Settings';
import './styles.css';

type Tab = 'chat' | 'plans' | 'approvals' | 'audit' | 'settings';

const TABS: { id: Tab; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'plans', label: 'Plans' },
  { id: 'approvals', label: 'Approvals' },
  { id: 'audit', label: 'Audit' },
  { id: 'settings', label: 'Settings' },
];

const HEALTH_POLL_MS = 10000;

export function App() {
  const [tab, setTab] = useState<Tab>('chat');
  const [health, setHealth] = useState<Health | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  const checkSidecar = async () => {
    try {
      const h = await api.health();
      setHealth(h);
      try {
        const { approvals } = await api.approvals();
        setPendingCount(approvals.length);
      } catch {
        // approvals unavailable; health already known good
      }
    } catch {
      setHealth(null);
    }
  };

  useEffect(() => {
    void checkSidecar();
    const t = window.setInterval(() => void checkSidecar(), HEALTH_POLL_MS);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1>Cezeri</h1>
          <div className="tagline">AI research team</div>
        </div>
        <nav className="nav">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'active' : ''}
              onClick={() => setTab(t.id)}
            >
              <span>{t.label}</span>
              {t.id === 'approvals' && pendingCount > 0 && (
                <span className="badge">{pendingCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="meta">sidecar: {SIDECAR_BASE_URL}</div>
          <div className="meta" style={{ marginTop: 4 }}>
            {health ? (
              <span className="health-ok">connected &middot; v{health.version}</span>
            ) : (
              <span className="health-bad">not connected</span>
            )}
          </div>
        </div>
      </aside>

      <main className="main">
        {health === null && (
          <div className="banner">
            <div className="banner-title">Sidecar not running</div>
            <div>
              Cezeri's Python sidecar is not reachable at <code>{SIDECAR_BASE_URL}</code>.
              The UI works in this browser, but nothing will respond until the sidecar is up.
              Start it from the runtime directory with:
              <br />
              <code>python -m cezeri_runtime.server</code>
              <br />
              (port is configurable with the <code>CEZERI_PORT</code> environment variable).
              This message clears automatically once the sidecar answers.
            </div>
          </div>
        )}

        {tab === 'chat' && <Chat />}
        {tab === 'plans' && <Plans />}
        {tab === 'approvals' && <Approvals onDecision={() => void checkSidecar()} />}
        {tab === 'audit' && <Audit />}
        {tab === 'settings' && <Settings health={health} />}
      </main>
    </div>
  );
}
