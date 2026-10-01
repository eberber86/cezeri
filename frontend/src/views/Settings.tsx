import { useEffect, useState } from 'react';
import { api, type AppConfig, type Health } from '../lib/api';

const PROVIDERS = ['anthropic', 'openai', 'gemini'];

export function Settings({ health }: { health: Health | null }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [provider, setProvider] = useState('anthropic');
  const [model, setModel] = useState('');
  const [dirs, setDirs] = useState<string[]>([]);
  const [newDir, setNewDir] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await api.config();
        setConfig(cfg);
        setProvider(cfg.provider);
        setModel(cfg.model);
        setDirs(cfg.approved_dirs ?? []);
        setError('');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load config');
      }
    })();
  }, []);

  const saveConfig = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.updateConfig({ provider, model: model.trim(), approved_dirs: dirs });
      setNotice('Configuration saved.');
      const cfg = await api.config();
      setConfig(cfg);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save config');
    } finally {
      setSaving(false);
    }
  };

  const saveKey = async () => {
    if (!apiKey) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.setKey(apiKey);
      setApiKey('');
      setNotice('API key saved to the sidecar key file. It is never displayed back.');
      const cfg = await api.config();
      setConfig(cfg);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save API key');
    } finally {
      setSaving(false);
    }
  };

  const addDir = () => {
    const d = newDir.trim();
    if (d && !dirs.includes(d)) setDirs((prev) => [...prev, d]);
    setNewDir('');
  };

  const removeDir = (d: string) => setDirs((prev) => prev.filter((x) => x !== d));

  return (
    <div>
      <h2 className="view-title">Settings</h2>
      <p className="view-sub">
        Model provider, API key, and the folders agents are allowed to touch.
      </p>

      {error && <div className="error">{error}</div>}
      {notice && <div className="card" style={{ borderColor: '#4caf7d' }}>{notice}</div>}

      <div className="card">
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Sidecar health</div>
        {health ? (
          <div className="health-box">
            <span className="health-ok">REACHABLE</span>
            <span>version <span className="mono">{health.version}</span></span>
            <span>provider <span className="mono">{health.provider}</span></span>
          </div>
        ) : (
          <div className="health-box">
            <span className="health-bad">UNREACHABLE</span>
            <span className="meta">Start the sidecar to manage settings.</span>
          </div>
        )}
      </div>

      <div className="card settings-form">
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Model provider</div>

        <div className="field">
          <label className="field-label" htmlFor="provider">Provider</label>
          <select id="provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="model">Model</label>
          <input
            id="model"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. claude-sonnet-4-5"
            style={{ width: '100%' }}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="api-key">
            API key {config && (config.has_key ? <span className="health-ok">— stored on sidecar</span> : <span className="health-bad">— not set</span>)}
          </label>
          <div className="row">
            <input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste a new key to replace the stored one"
              autoComplete="off"
              style={{ flex: 1 }}
            />
            <button className="btn" onClick={() => void saveKey()} disabled={saving || !apiKey}>
              Save key
            </button>
          </div>
          <div className="meta" style={{ marginTop: 4 }}>
            The key is written to the sidecar key file (0600) and is never returned or displayed.
          </div>
        </div>

        <div className="field">
          <label className="field-label">Approved folders</label>
          <div className="meta" style={{ marginBottom: 6 }}>
            Agents may only read and write inside these directories.
          </div>
          <div className="dir-list">
            {dirs.map((d) => (
              <div className="dir-row" key={d}>
                <span className="path">{d}</span>
                <button className="btn-ghost btn" onClick={() => removeDir(d)}>Remove</button>
              </div>
            ))}
            {dirs.length === 0 && <div className="meta">No approved folders yet.</div>}
          </div>
          <div className="row">
            <input
              type="text"
              value={newDir}
              onChange={(e) => setNewDir(e.target.value)}
              placeholder="/path/to/approved/folder"
              style={{ flex: 1 }}
              onKeyDown={(e) => { if (e.key === 'Enter') addDir(); }}
            />
            <button className="btn-ghost btn" onClick={addDir}>Add</button>
          </div>
        </div>

        <button className="btn" onClick={() => void saveConfig()} disabled={saving}>
          {saving ? 'Saving…' : 'Save configuration'}
        </button>
      </div>
    </div>
  );
}
