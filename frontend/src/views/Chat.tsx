import { useEffect, useRef, useState } from 'react';
import {
  api,
  agentDisplayName,
  isTerminalStatus,
  type Plan,
  type Target,
} from '../lib/api';
import { StatusPill } from '../components/StatusPill';

const TARGETS: { value: Target; label: string }[] = [
  { value: 'team', label: 'Team' },
  { value: 'viral_immunologist', label: 'Viral Immunologist' },
  { value: 'molecular_virologist', label: 'Molecular Virologist' },
  { value: 'scientific_writer', label: 'Scientific Writer' },
];

type ChatEntry =
  | { kind: 'user'; target: Target; text: string }
  | { kind: 'plan'; plan: Plan };

const POLL_MS = 1500;

export function Chat() {
  const [target, setTarget] = useState<Target>('team');
  const [message, setMessage] = useState('');
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef<number | null>(null);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const pollPlan = (planId: string) => {
    stopPolling();
    const tick = async () => {
      try {
        const plan = await api.plan(planId);
        setEntries((prev) =>
          prev.map((e) => (e.kind === 'plan' && e.plan.id === planId ? { kind: 'plan' as const, plan } : e))
        );
        if (isTerminalStatus(plan.status)) stopPolling();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to poll plan');
        stopPolling();
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => void tick(), POLL_MS);
  };

  const send = async () => {
    const text = message.trim();
    if (!text || sending) return;
    setSending(true);
    setError('');
    stopPolling();
    try {
      const { plan_id } = await api.chat(target, text);
      const plan = await api.plan(plan_id);
      setEntries((prev) => [
        ...prev,
        { kind: 'user', target, text },
        { kind: 'plan' as const, plan },
      ]);
      setMessage('');
      pollPlan(plan_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div>
      <h2 className="view-title">Team Chat</h2>
      <p className="view-sub">
        Address the whole team or one specialist directly. The team replies through a plan; steps appear live as they run.
      </p>

      {error && <div className="error">{error}</div>}

      <div className="chat-log">
        {entries.length === 0 && (
          <div className="empty">
            No messages yet. Pick a target below and ask the team a research question.
          </div>
        )}
        {entries.map((entry, i) =>
          entry.kind === 'user' ? (
            <div className="chat-entry user" key={i}>
              <div className="bubble">
                <div className="who">You &rarr; {agentDisplayName(entry.target)}</div>
                <div className="body">{entry.text}</div>
              </div>
            </div>
          ) : (
            <div className="chat-entry" key={entry.plan.id}>
              <div className="bubble">
                <div className="who">
                  {agentDisplayName(entry.plan.target)} &middot; {entry.plan.title} &middot;{' '}
                  <span className="mono">{entry.plan.id}</span>
                </div>
                <div className="step-head">
                  <StatusPill status={entry.plan.status} />
                </div>
                {entry.plan.steps.map((step) => (
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
            </div>
          )
        )}
      </div>

      <div className="chat-compose">
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value as Target)}
          aria-label="Target"
        >
          {TARGETS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask the team a research question… (Enter to send, Shift+Enter for a new line)"
          rows={2}
          disabled={sending}
        />
        <button className="btn" onClick={() => void send()} disabled={sending || !message.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
