import { type DashboardOverview } from '../lib/api';
import { StatCard } from '../components/StatCard';
import { StatusPill } from '../components/StatusPill';
import { Sparkline } from '../components/Sparkline';

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
const money = (v: number | undefined) => currency.format(v ?? 0);

type Props = {
  overview: DashboardOverview;
  isPending: boolean;
  onChangeMode: (mode: string) => void;
  onRefreshBroker: () => void;
  notice: string | null;
  error: string | null;
};

export function ArenaPage({ overview, isPending, onChangeMode, onRefreshBroker, notice, error }: Props) {
  const { agents, settings, broker_health } = overview;
  const accountSummary = broker_health.account_summary;
  const winner = agents.find((a) => a.is_winner) ?? agents[0] ?? null;
  const benchmarkReturn = settings.competition_benchmark_return_pct;
  const benchmarkSymbol = settings.competition_benchmark_symbol;

  return (
    <div>
      <section className="arena-hero">
        <div className="arena-hero-copy">
          <p className="eyebrow">AI Agent Arena</p>
          <h1>Two agents compete for capital — the winner earns a larger slice of the bankroll.</h1>
          <p className="lede">
            Performance is scored against {benchmarkSymbol}. The leading agent gains capital weight; the trailing agent fights to stay in the game.
          </p>
          <div className="mode-row" style={{ marginTop: 20 }}>
            <button onClick={() => onChangeMode('paused')} className="ghost-button" disabled={isPending}>Pause</button>
            <button onClick={() => onChangeMode('paper')} className="ghost-button" disabled={isPending}>Paper</button>
            <button onClick={() => onChangeMode('live_capped')} className="ghost-button" disabled={isPending}>Live Capped</button>
            <button onClick={onRefreshBroker} className="primary-button" disabled={isPending}>
              {isPending ? 'Working…' : 'Refresh Broker'}
            </button>
          </div>
          {notice ? <p className="banner ok" style={{ marginTop: 12 }}>{notice}</p> : null}
          {error ? <p className="banner error" style={{ marginTop: 12 }}>{error}</p> : null}
        </div>

        <div className="arena-status-column">
          <div className="stat-card" style={{ padding: 20 }}>
            <p className="eyebrow" style={{ margin: 0 }}>Mode</p>
            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <StatusPill tone="neutral">{overview.health.mode}</StatusPill>
              <StatusPill tone={broker_health.environment === 'SIMULATE' ? 'warn' : 'ok'}>
                {broker_health.environment}
              </StatusPill>
              <StatusPill tone={broker_health.is_reachable ? 'ok' : 'error'}>
                {broker_health.is_reachable ? 'broker online' : 'broker offline'}
              </StatusPill>
            </div>
          </div>

          <div className="stat-card" style={{ padding: 20 }}>
            <p className="eyebrow" style={{ margin: 0 }}>{benchmarkSymbol} Benchmark</p>
            <p className="stat-card-value" style={{ marginTop: 8, fontSize: '2rem', fontFamily: 'Cambria, serif' }}>
              {benchmarkReturn != null ? pct(benchmarkReturn) : '—'}
            </p>
            <p className="detail" style={{ marginTop: 4, fontSize: '0.85rem' }}>
              {settings.competition_benchmark_start_price != null
                ? `from $${settings.competition_benchmark_start_price.toFixed(2)}`
                : 'warmup pending'}
            </p>
          </div>
        </div>
      </section>

      <section className="stats-grid" style={{ marginTop: 20 }}>
        <StatCard
          label="Bankroll Cap"
          value={money(settings.risk_bankroll_cap)}
          detail={`Max order ${money(settings.risk_max_order_notional)}`}
        />
        <StatCard
          label="Buying Power"
          value={money(Number(accountSummary.available_funds ?? 0))}
          detail={`Cash ${money(Number(accountSummary.cash ?? 0))}`}
        />
        <StatCard
          label="Market Value"
          value={money(Number(accountSummary.market_value ?? 0))}
          detail={`Total assets ${money(Number(accountSummary.total_assets ?? 0))}`}
          accent="red"
        />
        <StatCard
          label="Leading Agent"
          value={winner?.name ?? 'Pending'}
          detail={winner ? `${pct(winner.total_return_pct)} return` : 'No data yet'}
          accent="teal"
        />
      </section>

      <section className="content-grid" style={{ marginTop: 20 }}>
        {agents.map((agent) => {
          const equityValues = agent.history.map((h) => h.equity);
          const returnColor = agent.total_return_pct >= 0 ? 'var(--teal)' : 'var(--red)';
          const vsBenchmark = benchmarkReturn != null
            ? agent.total_return_pct - benchmarkReturn
            : null;

          return (
            <article className="panel agent-arena-card" key={agent.slug}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">{agent.style}</p>
                  <h2>{agent.name}</h2>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
                  {agent.is_winner && <StatusPill tone="ok">winning agent</StatusPill>}
                  {!agent.is_winner && <StatusPill tone="neutral">challenger</StatusPill>}
                  {agent.is_cash_only && <StatusPill tone="warn">cash only</StatusPill>}
                  {!agent.is_alive && <StatusPill tone="error">eliminated</StatusPill>}
                </div>
              </div>

              <p className="lede" style={{ margin: '0 0 16px' }}>{agent.mandate}</p>

              <div className="agent-return-row">
                <div>
                  <span className="mini-label">Total Return</span>
                  <strong style={{ fontSize: '2rem', fontFamily: 'Cambria, serif', color: returnColor }}>
                    {pct(agent.total_return_pct)}
                  </strong>
                </div>
                {equityValues.length >= 2 && (
                  <Sparkline
                    values={equityValues}
                    width={140}
                    height={52}
                    color={returnColor}
                  />
                )}
              </div>

              <div className="mini-grid" style={{ marginTop: 16 }}>
                <div>
                  <span className="mini-label">vs {benchmarkSymbol}</span>
                  <strong style={{ color: vsBenchmark != null && vsBenchmark >= 0 ? 'var(--teal)' : 'var(--red)' }}>
                    {vsBenchmark != null ? `${vsBenchmark >= 0 ? '+' : ''}${pct(vsBenchmark)}` : '—'}
                  </strong>
                </div>
                <div>
                  <span className="mini-label">Reward Multiplier</span>
                  <strong>{agent.reward_multiplier.toFixed(2)}x</strong>
                </div>
                <div>
                  <span className="mini-label">Capital Weight</span>
                  <strong>{pct(agent.target_weight)}</strong>
                </div>
                <div>
                  <span className="mini-label">Allocated Capital</span>
                  <strong>{money(agent.allocated_capital)}</strong>
                </div>
                <div>
                  <span className="mini-label">Performance Score</span>
                  <strong>{agent.performance_score.toFixed(2)}</strong>
                </div>
                <div>
                  <span className="mini-label">Rolling Net P&amp;L</span>
                  <strong style={{ color: agent.rolling_net_pnl >= 0 ? 'var(--teal)' : 'var(--red)' }}>
                    {money(agent.rolling_net_pnl)}
                  </strong>
                </div>
              </div>

              {agent.is_cash_only && agent.cash_only_reason && (
                <div className="alert-card warning" style={{ marginTop: 16 }}>
                  <strong>Cash-only mode</strong>
                  <p>{agent.cash_only_reason}</p>
                </div>
              )}

              {agent.benchmark_warmup_ends_at && (
                <p style={{ marginTop: 12, fontSize: '0.82rem', color: 'var(--muted)' }}>
                  Benchmark warmup ends {new Date(agent.benchmark_warmup_ends_at).toLocaleDateString()}
                </p>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
