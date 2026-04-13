import { FormEvent, useState, useTransition } from 'react';
import { type DashboardOverview, submitPaperOrder } from '../lib/api';
import { StatusPill } from '../components/StatusPill';

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const money = (v: number) => currency.format(v);

type Props = {
  overview: DashboardOverview;
  onOrderPlaced: () => void;
};

export function TradesPage({ overview, onOrderPlaced }: Props) {
  const { agents, agent_trades, orders } = overview;
  const [isPending, startTransition] = useTransition();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<string>('all');

  const [orderForm, setOrderForm] = useState({
    symbol: 'US.NVDA',
    agentSlug: agents[0]?.slug ?? '',
    quantity: 1,
    limitPrice: 100,
    side: 'BUY',
    remark: 'paper test',
  });

  const placeOrder = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    startTransition(() => {
      void (async () => {
        try {
          await submitPaperOrder({
            symbol: orderForm.symbol,
            agent_slug: orderForm.agentSlug || null,
            quantity: orderForm.quantity,
            limit_price: orderForm.limitPrice,
            side: orderForm.side,
            remark: orderForm.remark,
          });
          const agentName = agents.find((a) => a.slug === orderForm.agentSlug)?.name ?? 'No agent';
          setNotice(`Submitted ${orderForm.side} ${orderForm.symbol} to ${agentName}.`);
          setError(null);
          onOrderPlaced();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Paper order failed.');
        }
      })();
    });
  };

  const filteredTrades = agentFilter === 'all'
    ? agent_trades
    : agent_trades.filter((t) => t.agent_slug === agentFilter);

  const filteredOrders = agentFilter === 'all'
    ? orders
    : orders.filter((o) => o.agent_slug === agentFilter);

  return (
    <div>
      <div className="page-header-row">
        <div>
          <p className="eyebrow">Trades</p>
          <h2 style={{ fontFamily: 'Cambria, serif', fontSize: '1.8rem', margin: 0 }}>Order History &amp; Paper Trading</h2>
        </div>
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
      </div>

      <section className="content-grid" style={{ marginTop: 16 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Paper Trade</p>
              <h2>Submit an Agent-Tagged Order</h2>
            </div>
            <StatusPill tone="warn">limit + RTH only</StatusPill>
          </div>

          {notice && <p className="banner ok" style={{ marginBottom: 12 }}>{notice}</p>}
          {error && <p className="banner error" style={{ marginBottom: 12 }}>{error}</p>}

          <form className="order-form" onSubmit={placeOrder}>
            <label>
              <span>Symbol</span>
              <input
                value={orderForm.symbol}
                onChange={(e) => setOrderForm((s) => ({ ...s, symbol: e.target.value }))}
                placeholder="US.NVDA"
              />
            </label>
            <label>
              <span>Agent</span>
              <select
                value={orderForm.agentSlug}
                onChange={(e) => setOrderForm((s) => ({ ...s, agentSlug: e.target.value }))}
              >
                {agents.map((a) => (
                  <option key={a.slug} value={a.slug}>{a.name}</option>
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
                onChange={(e) => setOrderForm((s) => ({ ...s, quantity: Number(e.target.value) }))}
              />
            </label>
            <label>
              <span>Limit Price</span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={orderForm.limitPrice}
                onChange={(e) => setOrderForm((s) => ({ ...s, limitPrice: Number(e.target.value) }))}
              />
            </label>
            <label>
              <span>Side</span>
              <select
                value={orderForm.side}
                onChange={(e) => setOrderForm((s) => ({ ...s, side: e.target.value }))}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
            </label>
            <label className="full">
              <span>Remark</span>
              <input
                value={orderForm.remark}
                onChange={(e) => setOrderForm((s) => ({ ...s, remark: e.target.value }))}
              />
            </label>
            <div className="order-summary">
              <span>Estimated notional</span>
              <strong>{money(orderForm.quantity * orderForm.limitPrice)}</strong>
            </div>
            <button className="primary-button full" type="submit" disabled={isPending}>
              {isPending ? 'Submitting…' : 'Submit Paper Order'}
            </button>
          </form>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Agent Trades</p>
              <h2>Tracked Executions</h2>
            </div>
            <StatusPill tone="neutral">{filteredTrades.length}</StatusPill>
          </div>
          <div className="stack">
            {filteredTrades.length > 0 ? (
              filteredTrades.map((trade) => {
                const agent = agents.find((a) => a.slug === trade.agent_slug);
                return (
                  <div className="list-card" key={trade.id}>
                    <div className="list-row">
                      <strong>{trade.symbol}</strong>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <StatusPill tone={trade.side === 'BUY' ? 'ok' : 'error'}>{trade.side}</StatusPill>
                        <StatusPill tone="neutral">{agent?.name ?? trade.agent_slug}</StatusPill>
                      </div>
                    </div>
                    <div className="meta-row">
                      <span>{trade.quantity} shares @ {money(trade.price)}</span>
                      <span>{money(trade.notional)}</span>
                      <span style={{ color: trade.realized_pl >= 0 ? 'var(--teal)' : 'var(--red)' }}>
                        P&L {money(trade.realized_pl)}
                      </span>
                    </div>
                    {trade.notes && (
                      <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--muted)' }}>{trade.notes}</p>
                    )}
                    <p style={{ margin: '2px 0 0', fontSize: '0.78rem', color: 'var(--muted)' }}>
                      {new Date(trade.created_at).toLocaleString()}
                    </p>
                  </div>
                );
              })
            ) : (
              <p className="empty-state">No agent trades recorded yet.</p>
            )}
          </div>
        </article>
      </section>

      <section style={{ marginTop: 20 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Broker</p>
              <h2>Recent Orders</h2>
            </div>
            <StatusPill tone="neutral">{filteredOrders.length}</StatusPill>
          </div>
          {filteredOrders.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Filled</th>
                    <th>Status</th>
                    <th>Agent</th>
                    <th>Env</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders.map((order) => (
                    <tr key={order.order_id}>
                      <td><strong>{order.symbol}</strong></td>
                      <td>
                        <StatusPill tone={order.side === 'BUY' ? 'ok' : 'error'}>{order.side}</StatusPill>
                      </td>
                      <td>{order.quantity}</td>
                      <td>{money(order.price)}</td>
                      <td>{order.filled_quantity > 0 ? `${order.filled_quantity} @ ${money(order.average_fill_price)}` : '—'}</td>
                      <td><StatusPill tone="neutral">{order.status}</StatusPill></td>
                      <td>{order.agent_slug ?? '—'}</td>
                      <td>{order.trading_env}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>
                        {new Date(order.updated_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty-state">No orders synced yet. Refresh broker state to populate.</p>
          )}
        </article>
      </section>
    </div>
  );
}
