import { useState, useTransition } from 'react';
import { type DashboardOverview, runResearch } from '../lib/api';
import { StatusPill } from '../components/StatusPill';

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

type Props = {
  overview: DashboardOverview;
  onRefreshed: () => void;
};

export function ResearchPage({ overview, onRefreshed }: Props) {
  const { decisions, research_notes, companies, agents, settings } = overview;
  const [isPending, startTransition] = useTransition();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<string>('all');

  const triggerResearch = () => {
    startTransition(() => {
      void (async () => {
        try {
          const result = await runResearch();
          setNotice(`Research complete. ${result.generated_decisions} decisions, ${result.generated_notes} notes generated.`);
          setError(null);
          onRefreshed();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Research run failed.');
        }
      })();
    });
  };

  const filteredNotes = agentFilter === 'all'
    ? research_notes
    : research_notes.filter((n) => n.agent_slug === agentFilter);

  const filteredDecisions = agentFilter === 'all'
    ? decisions
    : decisions.filter((d) => d.strategy_slug === agentFilter);

  return (
    <div>
      <div className="page-header-row">
        <div>
          <p className="eyebrow">Research</p>
          <h2 style={{ fontFamily: 'Cambria, serif', fontSize: '1.8rem', margin: 0 }}>AI Analysis &amp; Trade Queue</h2>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 12 }}
          >
            <option value="all">All agents</option>
            {agents.map((a) => (
              <option key={a.slug} value={a.slug}>{a.name}</option>
            ))}
          </select>
          {settings.research_enabled ? (
            <button className="primary-button" onClick={triggerResearch} disabled={isPending}>
              {isPending ? 'Running…' : 'Run Research'}
            </button>
          ) : (
            <StatusPill tone="warn">research disabled</StatusPill>
          )}
        </div>
      </div>

      {notice && <p className="banner ok" style={{ marginBottom: 16 }}>{notice}</p>}
      {error && <p className="banner error" style={{ marginBottom: 16 }}>{error}</p>}

      <section className="content-grid" style={{ marginTop: 16 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Decisions</p>
              <h2>Trade Queue</h2>
            </div>
            <StatusPill tone="neutral">{filteredDecisions.length} queued</StatusPill>
          </div>
          <div className="stack">
            {filteredDecisions.length > 0 ? (
              filteredDecisions.map((d) => (
                <div className="list-card" key={`${d.strategy_slug}-${d.symbol}`}>
                  <div className="list-row">
                    <strong>{d.symbol}</strong>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <StatusPill tone={d.side === 'BUY' ? 'ok' : 'error'}>{d.side}</StatusPill>
                      <StatusPill tone="neutral">{d.strategy_name}</StatusPill>
                    </div>
                  </div>
                  <p style={{ margin: '6px 0' }}>{d.rationale}</p>
                  <div className="meta-row">
                    <span>{d.theme_name}</span>
                    <span>{money.format(d.max_notional)} max</span>
                    <span>{pct(d.target_weight)} target</span>
                    <span>score {d.conviction_score.toFixed(1)}</span>
                    <StatusPill tone="neutral">{d.status}</StatusPill>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No decisions queued. Run research to generate trade ideas.</p>
            )}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Research Notes</p>
              <h2>AI Analysis</h2>
            </div>
            <StatusPill tone="neutral">{filteredNotes.length} notes</StatusPill>
          </div>
          <div className="stack" style={{ maxHeight: 600, overflowY: 'auto' }}>
            {filteredNotes.length > 0 ? (
              filteredNotes.map((note) => {
                const agent = agents.find((a) => a.slug === note.agent_slug);
                return (
                  <div className="list-card" key={note.id}>
                    <div className="list-row">
                      <strong>{note.symbol}</strong>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <StatusPill tone="neutral">{agent?.name ?? note.agent_slug}</StatusPill>
                        <StatusPill tone={note.note_score >= 0.7 ? 'ok' : note.note_score >= 0.4 ? 'warn' : 'neutral'}>
                          {note.note_score.toFixed(2)}
                        </StatusPill>
                      </div>
                    </div>
                    <p style={{ margin: '6px 0', fontSize: '0.9rem' }}>{note.note_text}</p>
                    <div className="meta-row">
                      <span>{note.source_title}</span>
                      <span>{note.source_type}</span>
                      {note.source_url && (
                        <a href={note.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--teal)' }}>
                          source
                        </a>
                      )}
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="empty-state">No research notes yet.</p>
            )}
          </div>
        </article>
      </section>

      <section style={{ marginTop: 20 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Universe</p>
              <h2>Approved Names</h2>
            </div>
            <StatusPill tone="neutral">{companies.length} companies</StatusPill>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Name</th>
                  <th>Theme</th>
                  <th>Sector</th>
                  <th>Score</th>
                  <th>Rationale</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((c) => (
                  <tr key={c.symbol}>
                    <td><strong>{c.symbol}</strong></td>
                    <td>{c.name}</td>
                    <td>{c.theme_name}</td>
                    <td>{c.sector}</td>
                    <td>{c.total_score.toFixed(1)}</td>
                    <td style={{ color: 'var(--muted)', fontSize: '0.85rem', maxWidth: 320 }}>{c.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </div>
  );
}
