import { type DashboardOverview } from '../lib/api';
import { StatCard } from '../components/StatCard';
import { StatusPill } from '../components/StatusPill';
import { Sparkline } from '../components/Sparkline';

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const money = (v: number) => currency.format(v);
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

type Props = {
  overview: DashboardOverview;
};

export function PortfolioPage({ overview }: Props) {
  const { agents, agent_positions, positions, broker_health } = overview;
  const accountSummary = broker_health.account_summary;

  const totalUnrealizedPL = positions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const totalMarketValue = positions.reduce((sum, p) => sum + p.market_value, 0);

  return (
    <div>
      <section className="stats-grid" style={{ marginBottom: 20 }}>
        <StatCard
          label="Market Value"
          value={money(Number(accountSummary.market_value ?? totalMarketValue))}
          detail={`Total assets ${money(Number(accountSummary.total_assets ?? 0))}`}
          accent="teal"
        />
        <StatCard
          label="Buying Power"
          value={money(Number(accountSummary.available_funds ?? 0))}
          detail={`Cash ${money(Number(accountSummary.cash ?? 0))}`}
        />
        <StatCard
          label="Unrealized P&L"
          value={money(totalUnrealizedPL)}
          detail={`Across ${positions.length} broker position${positions.length !== 1 ? 's' : ''}`}
          accent={totalUnrealizedPL >= 0 ? 'teal' : 'red'}
        />
        <StatCard
          label="Open Positions"
          value={String(positions.length)}
          detail={`${agent_positions.length} agent-tracked`}
        />
      </section>

      <section className="content-grid" style={{ marginBottom: 20 }}>
        {agents.map((agent) => {
          const myPositions = agent_positions.filter((p) => p.agent_slug === agent.slug);
          const holdingsValues = agent.holdings_history.map((h) => h.holdings);
          const cashValues = agent.cash_history.map((h) => h.cash);
          const agentPL = myPositions.reduce((sum, p) => sum + p.unrealized_pl, 0);

          return (
            <article className="panel" key={agent.slug}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">{agent.style}</p>
                  <h2>{agent.name}</h2>
                </div>
                <StatusPill tone={agent.is_winner ? 'ok' : 'neutral'}>
                  {agent.is_winner ? 'winner' : 'challenger'}
                </StatusPill>
              </div>

              <div className="mini-grid" style={{ marginBottom: 16 }}>
                <div>
                  <span className="mini-label">Allocated Capital</span>
                  <strong>{money(agent.allocated_capital)}</strong>
                </div>
                <div>
                  <span className="mini-label">Current Value</span>
                  <strong>{money(agent.current_value)}</strong>
                </div>
                <div>
                  <span className="mini-label">Unrealized P&amp;L</span>
                  <strong style={{ color: agentPL >= 0 ? 'var(--teal)' : 'var(--red)' }}>
                    {money(agentPL)}
                  </strong>
                </div>
                <div>
                  <span className="mini-label">Capital Weight</span>
                  <strong>{pct(agent.target_weight)}</strong>
                </div>
              </div>

              {(holdingsValues.length >= 2 || cashValues.length >= 2) && (
                <div style={{ display: 'flex', gap: 24, marginBottom: 16, flexWrap: 'wrap' }}>
                  {holdingsValues.length >= 2 && (
                    <div>
                      <span className="mini-label">Holdings history</span>
                      <Sparkline values={holdingsValues} width={140} height={44} color="var(--teal)" />
                    </div>
                  )}
                  {cashValues.length >= 2 && (
                    <div>
                      <span className="mini-label">Cash history</span>
                      <Sparkline values={cashValues} width={140} height={44} color="var(--gold)" />
                    </div>
                  )}
                </div>
              )}

              {myPositions.length > 0 ? (
                <div className="stack">
                  {myPositions.map((pos) => (
                    <div className="list-card" key={pos.symbol}>
                      <div className="list-row">
                        <strong>{pos.symbol}</strong>
                        <span style={{ color: pos.unrealized_pl >= 0 ? 'var(--teal)' : 'var(--red)', fontWeight: 700 }}>
                          {money(pos.unrealized_pl)}
                        </span>
                      </div>
                      <div className="meta-row">
                        <span>{pos.quantity} shares</span>
                        <span>avg {money(pos.average_cost)}</span>
                        <span>now {money(pos.market_price)}</span>
                        <span>{money(pos.market_value)} value</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty-state">No agent-tracked positions.</p>
              )}
            </article>
          );
        })}
      </section>

      <section style={{ marginBottom: 20 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Broker</p>
              <h2>All Holdings</h2>
            </div>
            <StatusPill tone="neutral">{positions.length} positions</StatusPill>
          </div>
          {positions.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Qty</th>
                    <th>Cost</th>
                    <th>Price</th>
                    <th>Market Value</th>
                    <th>Unrealized P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={pos.symbol}>
                      <td><strong>{pos.symbol}</strong></td>
                      <td>{pos.name}</td>
                      <td>{pos.quantity}</td>
                      <td>{money(pos.cost_price)}</td>
                      <td>{money(pos.market_price)}</td>
                      <td>{money(pos.market_value)}</td>
                      <td style={{ color: pos.unrealized_pl >= 0 ? 'var(--teal)' : 'var(--red)', fontWeight: 600 }}>
                        {money(pos.unrealized_pl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty-state">No synced positions. Refresh broker state to populate.</p>
          )}
        </article>
      </section>
    </div>
  );
}
