import { FormEvent, useEffect, useState, useTransition } from 'react';

import { StatCard } from './components/StatCard';
import { StatusPill } from './components/StatusPill';
import { type DashboardOverview, getOverview, submitPaperOrder, testBroker, updateMode } from './lib/api';

const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
});

function formatMoney(value: number | undefined) {
  return currency.format(value ?? 0);
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

export default function App() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [orderForm, setOrderForm] = useState({
    symbol: 'US.NVDA',
    agentSlug: 'high-growth-picks-shovels',
    quantity: 1,
    limitPrice: 100,
    side: 'BUY',
    remark: 'paper test',
  });

  const runTransitionTask = (task: () => Promise<void>) => {
    startTransition(() => {
      void task();
    });
  };

  useEffect(() => {
    let isMounted = true;
    const load = async () => {
      try {
        const data = await getOverview();
        if (isMounted) {
          setOverview(data);
          if (data.agents.length && !data.agents.some((agent) => agent.slug === orderForm.agentSlug)) {
            setOrderForm((current) => ({ ...current, agentSlug: data.agents[0].slug }));
          }
          setError(null);
        }
      } catch (nextError) {
        if (isMounted) {
          setError(nextError instanceof Error ? nextError.message : 'Failed to load dashboard.');
        }
      }
    };
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 15000);
    return () => {
      isMounted = false;
      window.clearInterval(timer);
    };
  }, [orderForm.agentSlug]);

  const runBrokerTest = () => {
    runTransitionTask(async () => {
      try {
        const data = await testBroker();
        setOverview(data);
        setNotice('Broker sync completed.');
        setError(null);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : 'Broker sync failed.');
      }
    });
  };

  const changeMode = (mode: string) => {
    runTransitionTask(async () => {
      try {
        await updateMode(mode);
        const data = await getOverview();
        setOverview(data);
        setNotice(`App mode changed to ${mode}.`);
        setError(null);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : 'Mode update failed.');
      }
    });
  };

  const placeOrder = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runTransitionTask(async () => {
      try {
        await submitPaperOrder({
          symbol: orderForm.symbol,
          agent_slug: orderForm.agentSlug || null,
          quantity: orderForm.quantity,
          limit_price: orderForm.limitPrice,
          side: orderForm.side,
          remark: orderForm.remark,
        });
        const data = await getOverview();
        setOverview(data);
        const agentName = data.agents.find((agent) => agent.slug === orderForm.agentSlug)?.name ?? 'No agent';
        setNotice(`Submitted ${orderForm.side} ${orderForm.symbol} to ${agentName}.`);
        setError(null);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : 'Paper order failed.');
      }
    });
  };

  const accountSummary = overview?.broker_health.account_summary ?? {};
  const winner = overview?.agents.find((agent) => agent.is_winner) ?? overview?.agents[0] ?? null;

return (
    <main className="app-shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Moomoo Picks Trader</p>
          <h1>Run two competing styles, then let the winner earn a larger slice of the bankroll.</h1>
          <p className="lede">
            One AI agent can stay flexible and nearly unlimited. The other can stay concentrated in high-growth AI
            picks-and-shovels like NVIDIA, Arista, and Vertiv.
          </p>
        </div>
        <div className="hero-panel">
          <div className="mode-row">
            <button onClick={() => changeMode('paused')} className="ghost-button" disabled={isPending}>
              Pause
            </button>
            <button onClick={() => changeMode('paper')} className="ghost-button" disabled={isPending}>
              Paper
            </button>
            <button onClick={() => changeMode('live_capped')} className="ghost-button" disabled={isPending}>
              Live Capped
            </button>
          </div>
          <div className="notice-stack">
            {winner ? <StatusPill tone="ok">winner {winner.name}</StatusPill> : null}
            {overview ? <StatusPill tone="neutral">mode {overview.health.mode}</StatusPill> : null}
            {overview ? (
              <StatusPill tone={overview.broker_health.environment === 'SIMULATE' ? 'warn' : 'error'}>
                env {overview.broker_health.environment}
              </StatusPill>
            ) : null}
          </div>
          <button onClick={runBrokerTest} className="primary-button" disabled={isPending}>
            {isPending ? 'Working...' : 'Refresh Broker State'}
          </button>
          {notice ? <p className="banner ok">{notice}</p> : null}
          {error ? <p className="banner error">{error}</p> : null}
        </div>
      </section>

      <section className="stats-grid">
        <StatCard
          label="Bankroll Cap"
          value={formatMoney(overview?.settings.risk_bankroll_cap)}
          detail={`Max order ${formatMoney(overview?.settings.risk_max_order_notional)}`}
        />
        <StatCard
          label="Winning Agent"
          value={winner?.name ?? 'Pending'}
          detail={winner ? `${formatPct(winner.total_return_pct)} return | ${formatPct(winner.target_weight)} capital` : 'No agent data'}
          accent="teal"
        />
        <StatCard
          label="Buying Power"
          value={formatMoney(Number(accountSummary.available_funds ?? 0))}
          detail={`Cash ${formatMoney(Number(accountSummary.cash ?? 0))}`}
        />
        <StatCard
          label="Market Value"
          value={formatMoney(Number(accountSummary.market_value ?? 0))}
          detail={`Total assets ${formatMoney(Number(accountSummary.total_assets ?? 0))}`}
          accent="red"
        />
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Agents</p>
              <h2>Competing Trading Styles</h2>
            </div>
            {winner ? <StatusPill tone="ok">rewarding winner</StatusPill> : null}
          </div>
          <div className="stack">
            {overview?.agents.map((agent) => (
              <div className="list-card" key={agent.slug}>
                <div className="list-row">
                  <strong>{agent.name}</strong>
                  <StatusPill tone={agent.is_winner ? 'ok' : 'neutral'}>
                    {agent.is_winner ? 'winning agent' : 'challenger'}
                  </StatusPill>
                </div>
                <p>{agent.mandate}</p>
                <div className="meta-row">
                  <span>{formatPct(agent.total_return_pct)} return</span>
                  <span>{formatPct(agent.target_weight)} target</span>
                  <span>{formatMoney(agent.allocated_capital)}</span>
                </div>
                <div className="meta-row">
                  <span>{agent.style}</span>
                  <span>{agent.benchmark}</span>
                  <span>{agent.reward_multiplier.toFixed(2)}x reward</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Paper Trade</p>
              <h2>Submit a Agent-Tagged Order</h2>
            </div>
            <StatusPill tone="warn">limit + RTH only</StatusPill>
          </div>
          <form className="order-form" onSubmit={placeOrder}>
            <label>
              <span>Symbol</span>
              <input
                value={orderForm.symbol}
                onChange={(event) => setOrderForm((current) => ({ ...current, symbol: event.target.value }))}
                placeholder="US.NVDA"
              />
            </label>
            <label>
              <span>Agent</span>
              <select
                value={orderForm.agentSlug}
                onChange={(event) => setOrderForm((current) => ({ ...current, agentSlug: event.target.value }))}
              >
                {overview?.agents.map((agent) => (
                  <option key={agent.slug} value={agent.slug}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Quantity</span>
              <input
                type="number"
                min="1"
                step="1"
                value={orderForm.quantity}
                onChange={(event) =>
                  setOrderForm((current) => ({ ...current, quantity: Number(event.target.value) }))
                }
              />
            </label>
            <label>
              <span>Limit Price</span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={orderForm.limitPrice}
                onChange={(event) =>
                  setOrderForm((current) => ({ ...current, limitPrice: Number(event.target.value) }))
                }
              />
            </label>
            <label>
              <span>Side</span>
              <select
                value={orderForm.side}
                onChange={(event) => setOrderForm((current) => ({ ...current, side: event.target.value }))}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
            </label>
            <label className="full">
              <span>Remark</span>
              <input
                value={orderForm.remark}
                onChange={(event) => setOrderForm((current) => ({ ...current, remark: event.target.value }))}
              />
            </label>
            <div className="order-summary">
              <span>Estimated notional</span>
              <strong>{formatMoney(orderForm.quantity * orderForm.limitPrice)}</strong>
            </div>
            <button className="primary-button full" type="submit" disabled={isPending}>
              Submit Paper Order
            </button>
          </form>
        </article>
      </section>

      <section className="content-grid three-up">
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Decisions</p>
              <h2>Agent Trade Queue</h2>
            </div>
          </div>
          <div className="stack">
            {overview?.decisions.map((decision) => (
              <div className="list-card" key={`${decision.strategy_slug}-${decision.symbol}`}>
                <div className="list-row">
                  <strong>{decision.symbol}</strong>
                  <StatusPill tone="neutral">{decision.strategy_name}</StatusPill>
                </div>
                <p>{decision.rationale}</p>
                <div className="meta-row">
                  <span>{decision.theme_name}</span>
                  <span>{formatMoney(decision.max_notional)}</span>
                  <span>{formatPct(decision.target_weight)}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Positions</p>
              <h2>Broker Holdings</h2>
            </div>
          </div>
          <div className="stack">
            {overview?.positions.length ? (
              overview.positions.map((position) => (
                <div className="list-card" key={position.symbol}>
                  <div className="list-row">
                    <strong>{position.symbol}</strong>
                    <span>{formatMoney(position.market_value)}</span>
                  </div>
                  <p>
                    {position.quantity} shares at {formatMoney(position.market_price)} | P/L{' '}
                    {formatMoney(position.unrealized_pl)}
                  </p>
                </div>
              ))
            ) : (
              <p className="empty-state">No synced positions yet.</p>
            )}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Orders</p>
              <h2>Recent Orders</h2>
            </div>
          </div>
          <div className="stack">
            {overview?.orders.length ? (
              overview.orders.map((order) => (
                <div className="list-card" key={order.order_id}>
                  <div className="list-row">
                    <strong>{order.symbol}</strong>
                    <StatusPill tone="neutral">{order.status}</StatusPill>
                  </div>
                  <p>
                    {order.side} {order.quantity} @ {formatMoney(order.price)}
                  </p>
                  <div className="meta-row">
                    <span>{order.agent_slug ?? 'unassigned'}</span>
                    <span>{order.trading_env}</span>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No orders synced yet.</p>
            )}
          </div>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Universe</p>
              <h2>Approved Names</h2>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Name</th>
                  <th>Theme</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {overview?.companies.map((company) => (
                  <tr key={company.symbol}>
                    <td>{company.symbol}</td>
                    <td>{company.name}</td>
                    <td>{company.theme_name}</td>
                    <td>{company.total_score.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Broker</p>
              <h2>Connection and Account State</h2>
            </div>
            {overview ? (
              <StatusPill tone={overview.broker_health.is_reachable ? 'ok' : 'error'}>
                {overview.broker_health.is_reachable ? 'reachable' : 'offline'}
              </StatusPill>
            ) : null}
          </div>
          <p className="panel-copy">{overview?.broker_health.message}</p>
          <div className="mini-grid">
            <div>
              <span className="mini-label">Selected account</span>
              <strong>{overview?.broker_health.selected_acc_id ?? 'Not set'}</strong>
            </div>
            <div>
              <span className="mini-label">Security firm</span>
              <strong>{overview?.accounts.find((account) => account.is_selected)?.security_firm ?? 'Unknown'}</strong>
            </div>
            <div>
              <span className="mini-label">Open positions cap</span>
              <strong>{overview?.settings.risk_max_open_positions ?? 0}</strong>
            </div>
            <div>
              <span className="mini-label">Daily loss stop</span>
              <strong>{formatMoney(overview?.settings.risk_daily_loss_limit)}</strong>
            </div>
          </div>
          {overview?.broker_health.warnings.length ? (
            <ul className="warning-list">
              {overview.broker_health.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <div className="stack">
            {overview?.alerts.map((alert) => (
              <div className={`alert-card ${alert.severity}`} key={`${alert.title}-${alert.created_at}`}>
                <strong>{alert.title}</strong>
                <p>{alert.message}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}


