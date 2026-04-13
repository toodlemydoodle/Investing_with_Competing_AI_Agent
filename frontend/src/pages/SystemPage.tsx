import { useState, useTransition } from 'react';
import { type DashboardOverview, toggleAutopilot, runAutopilotCycle } from '../lib/api';
import { StatusPill } from '../components/StatusPill';
import { StatCard } from '../components/StatCard';

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const money = (v: number) => currency.format(v);
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

type Props = {
  overview: DashboardOverview;
  onRefreshed: () => void;
};

export function SystemPage({ overview, onRefreshed }: Props) {
  const { broker_health, accounts, alerts, settings } = overview;
  const accountSummary = broker_health.account_summary;
  const [isPending, startTransition] = useTransition();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const doToggleAutopilot = (enabled: boolean) => {
    startTransition(() => {
      void (async () => {
        try {
          await toggleAutopilot(enabled);
          setNotice(`Autopilot ${enabled ? 'enabled' : 'disabled'}.`);
          setError(null);
          onRefreshed();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Autopilot toggle failed.');
        }
      })();
    });
  };

  const doCycle = () => {
    startTransition(() => {
      void (async () => {
        try {
          const result = await runAutopilotCycle();
          setNotice(`Cycle complete. ${result.executed_orders} orders executed.`);
          setError(null);
          onRefreshed();
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Cycle failed.');
        }
      })();
    });
  };

  return (
    <div>
      <div className="page-header-row" style={{ marginBottom: 20 }}>
        <div>
          <p className="eyebrow">System</p>
          <h2 style={{ fontFamily: 'Cambria, serif', fontSize: '1.8rem', margin: 0 }}>Broker, Autopilot &amp; Risk</h2>
        </div>
      </div>

      {notice && <p className="banner ok" style={{ marginBottom: 16 }}>{notice}</p>}
      {error && <p className="banner error" style={{ marginBottom: 16 }}>{error}</p>}

      <section className="stats-grid" style={{ marginBottom: 20 }}>
        <StatCard
          label="Bankroll Cap"
          value={money(settings.risk_bankroll_cap)}
          detail={`Max order ${money(settings.risk_max_order_notional)}`}
        />
        <StatCard
          label="Max Open Positions"
          value={String(settings.risk_max_open_positions)}
          detail={`${settings.risk_max_positions_per_theme} per theme`}
        />
        <StatCard
          label="Daily Loss Stop"
          value={money(settings.risk_daily_loss_limit)}
          detail="Hard stop on daily drawdown"
          accent="red"
        />
        <StatCard
          label="Stop Loss / Take Profit"
          value={`${pct(settings.agent_stop_loss_pct)} / ${pct(settings.agent_take_profit_pct)}`}
          detail="Per-position exit thresholds"
        />
      </section>

      <section className="content-grid" style={{ marginBottom: 20 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Broker</p>
              <h2>Connection &amp; Account</h2>
            </div>
            <StatusPill tone={broker_health.is_reachable ? 'ok' : 'error'}>
              {broker_health.is_reachable ? 'reachable' : 'offline'}
            </StatusPill>
          </div>

          <p className="panel-copy">{broker_health.message}</p>

          <div className="mini-grid" style={{ marginTop: 16 }}>
            <div>
              <span className="mini-label">Backend</span>
              <strong>{broker_health.backend}</strong>
            </div>
            <div>
              <span className="mini-label">Environment</span>
              <StatusPill tone={broker_health.environment === 'SIMULATE' ? 'warn' : 'ok'}>
                {broker_health.environment}
              </StatusPill>
            </div>
            <div>
              <span className="mini-label">Selected Account</span>
              <strong>{broker_health.selected_acc_id ?? 'Not set'}</strong>
            </div>
            <div>
              <span className="mini-label">Quote Provider</span>
              <strong>{settings.quote_provider}</strong>
            </div>
            {accountSummary.available_funds != null && (
              <div>
                <span className="mini-label">Available Funds</span>
                <strong>{money(Number(accountSummary.available_funds))}</strong>
              </div>
            )}
            {accountSummary.total_assets != null && (
              <div>
                <span className="mini-label">Total Assets</span>
                <strong>{money(Number(accountSummary.total_assets))}</strong>
              </div>
            )}
          </div>

          {broker_health.warnings.length > 0 && (
            <ul className="warning-list" style={{ marginTop: 16 }}>
              {broker_health.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}

          {accounts.length > 0 && (
            <div className="stack" style={{ marginTop: 16 }}>
              {accounts.map((acc) => (
                <div className="list-card" key={acc.acc_id}>
                  <div className="list-row">
                    <strong>Account {acc.acc_id}</strong>
                    {acc.is_selected && <StatusPill tone="ok">selected</StatusPill>}
                  </div>
                  <div className="meta-row">
                    <span>{acc.acc_type}</span>
                    <span>{acc.security_firm}</span>
                    <span>{acc.trd_env}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Autopilot</p>
              <h2>Agent Loop</h2>
            </div>
            <StatusPill tone={settings.agent_autopilot_enabled ? 'ok' : 'neutral'}>
              {settings.agent_autopilot_enabled ? 'enabled' : 'disabled'}
            </StatusPill>
          </div>

          <div className="mini-grid" style={{ marginBottom: 16 }}>
            <div>
              <span className="mini-label">Cycle Interval</span>
              <strong>{settings.agent_autopilot_interval_seconds}s</strong>
            </div>
            <div>
              <span className="mini-label">Max Orders / Cycle</span>
              <strong>{settings.agent_max_orders_per_cycle}</strong>
            </div>
            <div>
              <span className="mini-label">Last Cycle</span>
              <strong>
                {settings.agent_autopilot_last_cycle_at
                  ? new Date(settings.agent_autopilot_last_cycle_at).toLocaleString()
                  : 'Never'}
              </strong>
            </div>
            <div>
              <span className="mini-label">Admin Access</span>
              <StatusPill tone={settings.is_admin ? 'ok' : 'warn'}>
                {settings.is_admin ? 'unlocked' : 'locked'}
              </StatusPill>
            </div>
          </div>

          {settings.agent_autopilot_last_summary && (
            <div className="list-card" style={{ marginBottom: 16 }}>
              <span className="mini-label">Last Summary</span>
              <p style={{ margin: '4px 0 0', fontSize: '0.88rem' }}>{settings.agent_autopilot_last_summary}</p>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              className="primary-button"
              onClick={() => doToggleAutopilot(!settings.agent_autopilot_enabled)}
              disabled={isPending || !settings.is_admin}
            >
              {settings.agent_autopilot_enabled ? 'Disable Autopilot' : 'Enable Autopilot'}
            </button>
            <button
              className="ghost-button"
              onClick={doCycle}
              disabled={isPending || !settings.is_admin}
            >
              {isPending ? 'Running…' : 'Run Cycle Now'}
            </button>
          </div>

          {!settings.is_admin && (
            <p style={{ marginTop: 12, fontSize: '0.85rem', color: 'var(--muted)' }}>
              Admin controls are locked. Provide the admin token to unlock.
            </p>
          )}
        </article>
      </section>

      {alerts.length > 0 && (
        <section>
          <article className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Alerts</p>
                <h2>Active Warnings</h2>
              </div>
              <StatusPill tone="warn">{alerts.length} active</StatusPill>
            </div>
            <div className="stack">
              {alerts.map((alert) => (
                <div className={`alert-card ${alert.severity}`} key={`${alert.title}-${alert.created_at}`}>
                  <strong>{alert.title}</strong>
                  <p>{alert.message}</p>
                  <p style={{ fontSize: '0.78rem', color: 'var(--muted)', margin: '4px 0 0' }}>
                    {new Date(alert.created_at).toLocaleString()}
                  </p>
                </div>
              ))}
            </div>
          </article>
        </section>
      )}

      <section style={{ marginTop: 20 }}>
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Research Config</p>
              <h2>AI Research Settings</h2>
            </div>
            <StatusPill tone={settings.research_enabled ? 'ok' : 'neutral'}>
              {settings.research_enabled ? 'enabled' : 'disabled'}
            </StatusPill>
          </div>
          <div className="mini-grid">
            <div>
              <span className="mini-label">Max Symbols / Agent</span>
              <strong>{settings.research_max_symbols_per_agent}</strong>
            </div>
            <div>
              <span className="mini-label">Max Decisions / Agent</span>
              <strong>{settings.research_max_generated_decisions_per_agent}</strong>
            </div>
            <div>
              <span className="mini-label">Min Buy Score</span>
              <strong>{settings.research_min_buy_score.toFixed(2)}</strong>
            </div>
            <div>
              <span className="mini-label">Min Hold Score</span>
              <strong>{settings.research_min_hold_score.toFixed(2)}</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
