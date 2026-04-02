const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const REQUEST_TIMEOUT_MS = 8000;

function fmtMoney(value) { return money.format(Number(value || 0)); }
function fmtMaybeMoney(value) { return value === null || value === undefined ? 'n/a' : fmtMoney(value); }
function fmtWeight(value) { return `${(Number(value || 0) * 100).toFixed(1)}%`; }
function fmtPercent(value) { return `${Number(value || 0).toFixed(1)}%`; }
function fmtMaybePercent(value) { return value === null || value === undefined ? 'n/a' : fmtPercent(value); }
function fmtShares(value) { return Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function parseApiDate(value) {
  if (!value) { return null; }
  const raw = String(value).trim();
  if (!raw) { return null; }
  const hasZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(raw);
  return new Date(hasZone ? raw : `${raw}Z`);
}
function fmtDate(value) {
  const date = parseApiDate(value);
  return date
    ? new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }).format(date)
    : 'n/a';
}
function fmtDateTime(value) {
  const date = parseApiDate(value);
  return date
    ? new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short',
    }).format(date)
    : 'n/a';
}
function pill(tone, text) { return `<span class="pill ${tone}">${text}</span>`; }
function setPill(id, tone, text) {
  const el = document.getElementById(id);
  if (!el) { return; }
  el.className = `pill ${tone}`;
  el.textContent = text;
}
function card(title, body, meta = []) {
  return `
    <div class="card">
      <div class="card-head"><strong>${title}</strong>${meta[0] || ''}</div>
      <p>${body}</p>
      ${meta.length > 1 ? `<div class="meta">${meta.slice(1).join('')}</div>` : ''}
    </div>
  `;
}

function cardHtml(title, bodyHtml, meta = []) {
  return `
    <div class="card">
      <div class="card-head"><strong>${title}</strong>${meta[0] || ''}</div>
      ${bodyHtml}
      ${meta.length > 1 ? `<div class="meta">${meta.slice(1).join('')}</div>` : ''}
    </div>
  `;
}

function agentName(value) {
  const name = String(value || '').trim();
  if (!name) { return 'Unknown Agent'; }
  return /agent$/i.test(name) ? name : `${name} Agent`;
}

function agentNameBySlug(data) {
  return Object.fromEntries(data.agents.map((agent) => [agent.slug, agentName(agent.name)]));
}

function agentPositionsByOwner(data) {
  return data.agent_positions.reduce((positions, position) => {
    positions[position.agent_slug] = positions[position.agent_slug] || [];
    positions[position.agent_slug].push(position);
    return positions;
  }, {});
}

async function request(path, init) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...init,
    });
    if (!response.ok) {
      throw new Error(await response.text() || `Request failed: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds.`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function showMessage(kind, text) {
  const notice = document.getElementById('notice');
  const error = document.getElementById('error');
  if (kind === 'error') {
    error.textContent = text;
    error.classList.remove('hidden');
    notice.classList.add('hidden');
  } else {
    notice.textContent = text;
    notice.classList.remove('hidden');
    error.classList.add('hidden');
  }
}

function bindClick(id, handler) {
  const el = document.getElementById(id);
  if (!el) { return null; }
  el.addEventListener('click', handler);
  return el;
}

function benchmarkHistoryPoints(settings) {
  return (settings.competition_benchmark_history || [])
    .map((point) => {
      const price = Number(point.price || 0);
      const recordedAt = point.recorded_at;
      const date = parseApiDate(recordedAt);
      return price > 0 && date ? { price, recordedAt, date } : null;
    })
    .filter(Boolean)
    .sort((left, right) => left.date - right.date);
}

function easternDayKey(value) {
  const date = parseApiDate(value);
  return date
    ? new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(date)
    : '';
}

function fmtBenchmarkAxis(value, referenceValue) {
  const date = parseApiDate(value);
  if (!date) { return 'n/a'; }
  const sameDay = easternDayKey(value) === easternDayKey(referenceValue || value);
  return new Intl.DateTimeFormat('en-US', sameDay
    ? {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
    }
    : {
      timeZone: 'America/New_York',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
    }).format(date);
}

function fmtBenchmarkLabel(value) {
  return Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function buildBenchmarkChart(history) {
  if (!history.length) {
    return {
      high: null,
      low: null,
      markup: '<div class="benchmark-chart-empty">Refresh Broker State or let autopilot run to start tracking benchmark history.</div>',
    };
  }

  const prices = history.map((point) => point.price);
  const high = Math.max(...prices);
  const low = Math.min(...prices);
  if (history.length < 2) {
    return {
      high,
      low,
      markup: '<div class="benchmark-chart-empty">One more benchmark snapshot will turn this into a live chart.</div>',
    };
  }

  const width = 920;
  const height = 300;
  const padding = { top: 18, right: 20, bottom: 30, left: 18 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const spread = Math.max(high - low, high * 0.01, 0.35);
  const floor = low - (spread * 0.2);
  const ceiling = high + (spread * 0.2);
  const valueRange = Math.max(ceiling - floor, 0.01);
  const x = (index) => padding.left + ((index / (history.length - 1)) * innerWidth);
  const y = (price) => padding.top + (((ceiling - price) / valueRange) * innerHeight);
  const linePath = history.map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(2)} ${y(point.price).toFixed(2)}`).join(' ');
  const fillPath = `${linePath} L ${x(history.length - 1).toFixed(2)} ${(padding.top + innerHeight).toFixed(2)} L ${x(0).toFixed(2)} ${(padding.top + innerHeight).toFixed(2)} Z`;
  const gridValues = Array.from({ length: 4 }, (_, index) => ceiling - ((ceiling - floor) * index / 3));
  const gridLines = gridValues.map((value) => {
    const gy = y(value);
    return `
      <line x1="${padding.left}" y1="${gy.toFixed(2)}" x2="${(width - padding.right).toFixed(2)}" y2="${gy.toFixed(2)}" stroke="rgba(26, 33, 29, 0.10)" stroke-width="1" />
      <text x="${(width - 4).toFixed(2)}" y="${Math.max(14, gy - 6).toFixed(2)}" text-anchor="end" fill="rgba(90, 97, 90, 0.9)" font-size="11">${fmtBenchmarkLabel(value)}</text>
    `;
  }).join('');
  const last = history[history.length - 1];
  const lastX = x(history.length - 1);
  const lastY = y(last.price);
  const labelCenterX = Math.min(width - padding.right - 60, Math.max(padding.left + 60, lastX));
  const labelTopY = Math.max(padding.top + 8, lastY - 32);

  return {
    high,
    low,
    markup: `
      <svg class="benchmark-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Benchmark price history chart">
        <defs>
          <linearGradient id="benchmark-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="#2e6b5e" stop-opacity="0.34" />
            <stop offset="100%" stop-color="#2e6b5e" stop-opacity="0.04" />
          </linearGradient>
        </defs>
        ${gridLines}
        <path d="${fillPath}" fill="url(#benchmark-fill)" />
        <path d="${linePath}" fill="none" stroke="#2e6b5e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
        <line x1="${lastX.toFixed(2)}" y1="${padding.top}" x2="${lastX.toFixed(2)}" y2="${(padding.top + innerHeight).toFixed(2)}" stroke="rgba(23, 73, 63, 0.18)" stroke-width="1.2" stroke-dasharray="4 5" />
        <circle cx="${lastX.toFixed(2)}" cy="${lastY.toFixed(2)}" r="5" fill="#2e6b5e" stroke="rgba(255, 252, 247, 0.95)" stroke-width="2.5" />
        <rect x="${(labelCenterX - 60).toFixed(2)}" y="${labelTopY.toFixed(2)}" width="120" height="24" rx="12" fill="rgba(20, 53, 47, 0.9)" />
        <text x="${labelCenterX.toFixed(2)}" y="${(labelTopY + 16).toFixed(2)}" text-anchor="middle" fill="rgba(255, 250, 243, 0.96)" font-size="11">${fmtBenchmarkLabel(last.price)}</text>
      </svg>
    `,
  };
}

function renderBenchmarkPanel(settings) {
  const symbol = settings.competition_benchmark_symbol || 'US.SPY';
  const cleanSymbol = String(symbol).replace('US.', '');
  const history = benchmarkHistoryPoints(settings);
  const chart = buildBenchmarkChart(history);
  const currentPrice = settings.competition_benchmark_current_price ?? (history.length ? history[history.length - 1].price : null);
  const startPrice = settings.competition_benchmark_start_price ?? (history.length ? history[0].price : null);
  const benchmarkReturn = settings.competition_benchmark_return_pct;
  const returnText = benchmarkReturn === null || benchmarkReturn === undefined
    ? 'Waiting for benchmark refresh.'
    : `${benchmarkReturn >= 0 ? '+' : ''}${Number(benchmarkReturn || 0).toFixed(1)}% since arena start`;
  const returnTone = benchmarkReturn === null || benchmarkReturn === undefined ? 'neutral' : (benchmarkReturn >= 0 ? 'up' : 'down');
  const updatedText = settings.competition_benchmark_last_updated_at
    ? `Updated ${fmtDateTime(settings.competition_benchmark_last_updated_at)}`
    : 'Refresh Broker State or let autopilot run to build benchmark history.';

  return `
    <article class="stat benchmark-stat">
      <div class="benchmark-top">
        <div class="benchmark-copy">
          <p class="eyebrow">Benchmark</p>
          <h3>${cleanSymbol}</h3>
          <div class="benchmark-value">${fmtMaybeMoney(currentPrice)}</div>
          <p class="benchmark-change ${returnTone}">${returnText}</p>
          <p class="benchmark-note">${updatedText}</p>
        </div>
        <div class="benchmark-summary">
          <span>Start ${fmtMaybeMoney(startPrice)}</span>
          <span>Now ${fmtMaybeMoney(currentPrice)}</span>
          <span>Range ${fmtMaybeMoney(chart.low)} to ${fmtMaybeMoney(chart.high)}</span>
          <span>${history.length} samples</span>
        </div>
      </div>
      <div class="benchmark-chart-shell">${chart.markup}</div>
      <div class="benchmark-chart-axis">
        <span>${history.length ? fmtBenchmarkAxis(history[0].recordedAt, history[0].recordedAt) : 'Start'}</span>
        <span>${history.length ? fmtBenchmarkAxis(history[history.length - 1].recordedAt, history[0].recordedAt) : 'Now'}</span>
      </div>
    </article>
  `;
}

function renderStats(data) {
  const winner = data.agents.find((agent) => agent.is_winner) || null;
  const aliveCount = data.agents.filter((agent) => agent.is_alive).length;
  const windowDays = data.agents[0] ? data.agents[0].competition_window_days : 90;
  const benchmarkSymbol = data.settings.competition_benchmark_symbol || 'US.SPY';
  const benchmarkReturn = data.settings.competition_benchmark_return_pct;
  const nextCheck = data.agents
    .filter((agent) => agent.is_alive && !agent.is_eligible_for_elimination && agent.elimination_ready_at)
    .map((agent) => agent.elimination_ready_at)
    .sort()[0];
  const statCards = [
    ['Bankroll Cap', fmtMoney(data.settings.risk_bankroll_cap), `Max order ${fmtMoney(data.settings.risk_max_order_notional)}`],
    ['Surviving Agents', String(aliveCount), `${data.agents.length - aliveCount} eliminated`],
    ['Leading Agent', winner ? agentName(winner.name) : 'No survivor', winner ? `${fmtPercent(winner.total_return_pct)} total return | ${fmtWeight(winner.target_weight)} capital` : 'No live agent to reward'],
    ['Arena Rule', `${windowDays}-day benchmark test`, nextCheck ? `First elimination window opens ${fmtDate(nextCheck)} | ${benchmarkSymbol} ${fmtMaybePercent(benchmarkReturn)}` : `After warm-up, trailing ${benchmarkSymbol} means elimination`],
  ].map(([label, value, detail]) => `<article class="stat"><p class="eyebrow">${label}</p><h3>${value}</h3><p>${detail}</p></article>`).join('');
  document.getElementById('stats').innerHTML = `${statCards}${renderBenchmarkPanel(data.settings)}`;
}

function agentBadge(agent, benchmarkReturn, benchmarkSymbol) {
  if (!agent.is_alive) { return pill('error', 'lost'); }
  if (agent.is_winner) { return pill('ok', 'leader'); }
  if (!agent.is_eligible_for_elimination) { return pill('neutral', 'warming up'); }
  if (benchmarkReturn !== null && benchmarkReturn !== undefined && Number(agent.total_return_pct || 0) < Number(benchmarkReturn)) {
    return pill('warn', `below ${String(benchmarkSymbol || 'SPY').replace('US.', '')}`);
  }
  return pill('ok', 'alive');
}

function renderAgents(data) {
  const winner = data.agents.find((agent) => agent.is_winner && agent.is_alive);
  const benchmarkSymbol = data.settings.competition_benchmark_symbol || 'US.SPY';
  const benchmarkReturn = data.settings.competition_benchmark_return_pct;
  setPill('winner-badge', winner ? 'ok' : 'error', winner ? `leader ${agentName(winner.name)}` : 'no live winner');
  document.getElementById('agents').innerHTML = data.agents.map((agent) => {
    const benchmarkGap = benchmarkReturn === null || benchmarkReturn === undefined
      ? null
      : Number(agent.total_return_pct || 0) - Number(benchmarkReturn || 0);
    const windowLine = agent.is_eligible_for_elimination
      ? `${benchmarkSymbol} is ${fmtMaybePercent(benchmarkReturn)}. This agent is ${fmtPercent(agent.total_return_pct)} since the arena began.`
      : `Warm-up ends ${fmtDate(agent.elimination_ready_at)}. Benchmark elimination starts after that.`;
    const body = agent.is_alive
      ? `${agent.mandate} ${windowLine}`
      : `${agent.death_reason || 'This agent lost the arena.'} Allowed universe was ${agent.allowed_universe}.`;
    return card(
      agentName(agent.name),
      body,
      [
        agentBadge(agent, benchmarkReturn, benchmarkSymbol),
        `<span>${fmtPercent(agent.total_return_pct)} total return</span>`,
        `<span>${benchmarkGap === null ? 'Benchmark gap n/a' : `${fmtPercent(benchmarkGap)} vs ${benchmarkSymbol}`}</span>`,
        `<span>${fmtMoney(agent.rolling_net_pnl)} rolling net</span>`,
        `<span>${fmtWeight(agent.target_weight)} capital</span>`,
        `<span>${fmtMoney(agent.current_value)} value</span>`,
        `<span>${agent.reward_multiplier.toFixed(2)}x reward</span>`,
      ],
    );
  }).join('');
}

function renderAgentPositions(data) {
  const el = document.getElementById('agent-positions');
  const names = agentNameBySlug(data);
  el.innerHTML = data.agent_positions.length ? data.agent_positions.map((position) => card(
    position.symbol,
    `${names[position.agent_slug] || position.agent_slug} holds ${fmtShares(position.quantity)} shares at ${fmtMoney(position.market_price)} | Unrealized ${fmtMoney(position.unrealized_pl)}`,
    [pill('neutral', names[position.agent_slug] || position.agent_slug), `<span>Cost ${fmtMoney(position.average_cost)}</span>`, `<span>Value ${fmtMoney(position.market_value)}</span>`, `<span>Realized ${fmtMoney(position.realized_pl)}</span>`]
  )).join('') : '<p class="empty">No agent holdings yet.</p>';
}

function renderAgentTrades(data) {
  const el = document.getElementById('agent-trades');
  const names = agentNameBySlug(data);
  el.innerHTML = data.agent_trades.length ? data.agent_trades.map((trade) => card(
    trade.symbol,
    `${trade.side} ${trade.quantity} @ ${fmtMoney(trade.price)} | Notional ${fmtMoney(trade.notional)}`,
    [
      pill(trade.side === 'BUY' ? 'ok' : 'warn', trade.side),
      `<span>${names[trade.agent_slug] || trade.agent_slug}</span>`,
      `<span>Realized ${fmtMoney(trade.realized_pl)}</span>`,
      `<span>${trade.order_id || 'manual ledger event'}</span>`,
      `<span>${fmtDateTime(trade.created_at)}</span>`
    ]
  )).join('') : '<p class="empty">No agent trade events yet.</p>';
}

function renderDecisions(data) {
  const el = document.getElementById('decisions');
  el.innerHTML = data.decisions.length ? data.decisions.map((decision) => card(
    decision.symbol,
    decision.rationale,
    [
      pill(decision.status === 'research-buy' ? 'ok' : 'warn', decision.status.replace('research-', '')),
      `<span>${agentName(decision.strategy_name)}</span>`,
      `<span>${decision.theme_name}</span>`,
      `<span>${fmtMoney(decision.max_notional)}</span>`,
      `<span>${fmtWeight(decision.target_weight)}</span>`,
      `<span>${decision.conviction_score.toFixed(1)}/10</span>`
    ]
  )).join('') : '<p class="empty">No live research ideas yet. Run research first.</p>';
}

function renderPositions(data) {
  const el = document.getElementById('positions');
  const names = agentNameBySlug(data);
  const positionsByOwner = agentPositionsByOwner(data);
  const trackedAgents = data.agents;
  el.innerHTML = trackedAgents.length ? trackedAgents.map((agent) => {
    const holdings = positionsByOwner[agent.slug] || [];
    const holdingsValue = holdings.reduce((sum, holding) => sum + Number(holding.market_value || 0), 0);
    const netValue = Number(agent.current_value || 0);
    const body = holdings.length
      ? `
        <ul class="holding-list">
          ${holdings.map((holding) => `<li><strong>${holding.symbol}</strong><span>${fmtShares(holding.quantity)} shares at ${fmtMoney(holding.market_price)}</span></li>`).join('')}
        </ul>
      `
      : '<p>No assigned holdings.</p>';

    return cardHtml(
      names[agent.slug] || agent.slug,
      body,
      [
        pill(agent.style === 'specialist' ? 'ok' : 'warn', agent.style),
        `<span>Holdings ${holdings.length}</span>`,
        `<span>Value ${fmtMoney(holdingsValue)}</span>`,
        `<span>Cash ${fmtMoney(agent.cash_buffer)}</span>`,
        `<span>Net value ${fmtMoney(netValue)}</span>`,
      ]
    );
  }).join('') : '<p class="empty">No tracked agent holdings yet.</p>';
}

function renderOrders(data) {
  const el = document.getElementById('orders');
  const names = agentNameBySlug(data);
  el.innerHTML = data.orders.length ? data.orders.map((order) => card(
    order.symbol,
    `${order.side} ${order.quantity} @ ${fmtMoney(order.price)}`,
    [
      pill('neutral', order.status),
      `<span>${names[order.agent_slug] || 'no agent'}</span>`,
      `<span>${order.trading_env}</span>`,
      `<span>Filled ${order.filled_quantity}</span>`,
      `<span>${fmtDateTime(order.updated_at)}</span>`,
    ]
  )).join('') : '<p class="empty">No orders synced yet.</p>';
}

function renderCompanies(data) {
  document.getElementById('companies').innerHTML = data.companies.map((company) => `
    <tr>
      <td>${company.symbol}</td>
      <td>${company.name}</td>
      <td>${company.theme_name}</td>
      <td>${company.total_score.toFixed(1)}</td>
    </tr>
  `).join('');
}

function renderAutopilot(data) {
  const el = document.getElementById('autopilot-status');
  const toggle = document.getElementById('autopilot-toggle-button');
  const isEnabled = data.settings.agent_autopilot_enabled;

  if (toggle) {
    toggle.textContent = isEnabled ? 'Autopilot: On' : 'Autopilot: Off';
    toggle.className = isEnabled ? 'primary' : '';
    toggle.dataset.enabled = isEnabled;
  }

  const status = isEnabled ? 'Autopilot enabled' : 'Autopilot disabled';
  const lastRun = data.settings.agent_autopilot_last_cycle_at ? `Last cycle ${fmtDate(data.settings.agent_autopilot_last_cycle_at)}` : 'No cycle has run yet';
  const summary = data.settings.agent_autopilot_last_summary || 'Run one cycle manually to see what the agents want to do.';
  el.textContent = `${status}. Every ${data.settings.agent_autopilot_interval_seconds}s. ${lastRun}. ${summary}`;
}

function renderBroker(data) {
  const broker = data.broker_health;
  const selectedAccount = data.accounts.find((account) => account.is_selected);
  setPill('broker-pill', broker.is_reachable ? 'ok' : 'error', broker.is_reachable ? 'reachable' : 'offline');
  document.getElementById('broker-summary').innerHTML = [
    ['Backend', data.settings.broker_backend],
    ['Quote source', data.settings.quote_provider],
    ['Selected account', broker.selected_acc_id || 'Not set'],
    ['Security firm', selectedAccount ? selectedAccount.security_firm : 'Unknown'],
    ['Environment', broker.environment],
    ['Mode', data.health.mode],
  ].map(([label, value]) => `<div><p class="eyebrow">${label}</p><strong>${value}</strong></div>`).join('');
  document.getElementById('warnings').innerHTML = (broker.warnings || []).map((warning) => `<li>${warning}</li>`).join('');
  document.getElementById('alerts').innerHTML = data.alerts.map((alert) => `
    <div class="alert-card ${alert.severity}">
      <strong>${alert.title}</strong>
      <p>${alert.message}</p>
    </div>
  `).join('');
}

function populateAgentSelect(data) {
  const select = document.getElementById('agent-select');
  const submitButton = document.getElementById('submit-order');
  const aliveAgents = data.agents.filter((agent) => agent.is_alive);
  const current = select.value;
  select.innerHTML = aliveAgents.map((agent) => `<option value="${agent.slug}">${agentName(agent.name)}</option>`).join('');
  const hasAliveAgents = aliveAgents.length > 0;
  select.disabled = !hasAliveAgents;
  submitButton.disabled = !hasAliveAgents;
  if (!hasAliveAgents) {
    return;
  }
  if (current && aliveAgents.some((agent) => agent.slug === current)) {
    select.value = current;
  }
}

async function fetchQuote() {
  const symbolInput = document.querySelector('input[name="symbol"]');
  const sideSelect = document.querySelector('select[name="side"]');
  const limitInput = document.querySelector('input[name="limit_price"]');
  const summary = document.getElementById('quote-summary');
  const symbol = String(symbolInput.value || '').trim().toUpperCase();
  if (!symbol) {
    summary.innerHTML = '<span>Enter a symbol first.</span>';
    return;
  }
  const quote = await request(`/quotes/${encodeURIComponent(symbol)}`);
  const side = String(sideSelect.value || 'BUY').toUpperCase();
  const suggested = side === 'SELL' ? (quote.bid_price || quote.last_price) : (quote.ask_price || quote.last_price);
  if (suggested > 0) {
    limitInput.value = suggested.toFixed(2);
  }
  summary.innerHTML = [
    `<span>${quote.name}</span>`,
    `<span>Last ${fmtMoney(quote.last_price)}</span>`,
    `<span>Bid ${fmtMoney(quote.bid_price)}</span>`,
    `<span>Ask ${fmtMoney(quote.ask_price)}</span>`,
    `<span>Updated ${quote.update_time || 'n/a'}</span>`,
  ].join('');
}

async function refreshOverview() {
  const data = await request('/dashboard/overview');
  renderStats(data);
  renderAgents(data);
  renderAgentPositions(data);
  renderAgentTrades(data);
  renderDecisions(data);
  renderPositions(data);
  renderOrders(data);
  renderCompanies(data);
  renderBroker(data);
  renderAutopilot(data);
  populateAgentSelect(data);
  return data;
}

async function init() {
  bindClick('refresh-button', async () => {
    try {
      await request('/broker/test', { method: 'POST' });
      await refreshOverview();
      showMessage('ok', 'Broker sync completed.');
    } catch (error) {
      showMessage('error', error.message || 'Broker sync failed.');
    }
  });

  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await request('/mode', { method: 'POST', body: JSON.stringify({ mode: button.dataset.mode }) });
        await refreshOverview();
        showMessage('ok', `Runtime mode changed to ${button.dataset.mode}.`);
      } catch (error) {
        showMessage('error', error.message || 'Mode update failed.');
      }
    });
  });

  bindClick('run-research-button', async () => {
    try {
      const result = await request('/research/run', { method: 'POST' });
      await refreshOverview();
      showMessage('ok', `Research refreshed for ${result.generated_agents} agents.`);
    } catch (error) {
      showMessage('error', error.message || 'Research refresh failed.');
    }
  });

  bindClick('run-cycle-button', async () => {
    try {
      const result = await request('/agents/cycle', { method: 'POST' });
      await refreshOverview();
      showMessage('ok', result.events[0] || 'Agent cycle completed.');
    } catch (error) {
      showMessage('error', error.message || 'Agent cycle failed.');
    }
  });

  bindClick('autopilot-toggle-button', async (event) => {
    const button = event.currentTarget;
    const enabled = button instanceof HTMLElement && button.dataset.enabled === 'true';
    try {
      await request('/agents/autopilot', { method: 'POST', body: JSON.stringify({ enabled: !enabled }) });
      const data = await refreshOverview();
      showMessage('ok', data.settings.agent_autopilot_enabled ? 'Agent autopilot enabled.' : 'Agent autopilot disabled.');
    } catch (error) {
      showMessage('error', error.message || 'Failed to update autopilot.');
    }
  });

  bindClick('quote-button', async () => {
    try {
      await fetchQuote();
      showMessage('ok', 'Quote refreshed.');
    } catch (error) {
      const message = String(error.message || 'Quote lookup failed.');
      if (message.includes('denied US quote access')) {
        showMessage('error', 'moomoo quote rights are missing. Set QUOTE_PROVIDER=twelvedata with a Twelve Data API key, or enter the limit price manually.');
      } else if (message.includes('ALPACA_DATA_API_KEY / ALPACA_DATA_SECRET are missing')) {
        showMessage('error', 'QUOTE_PROVIDER is alpaca, but Alpaca data keys are missing in backend/.env.');
      } else if (message.includes('TWELVEDATA_API_KEY is missing')) {
        showMessage('error', 'QUOTE_PROVIDER is twelvedata, but TWELVEDATA_API_KEY is missing in backend/.env.');
      } else if (message.includes('Alpaca market-data credentials were rejected')) {
        showMessage('error', 'Alpaca rejected the market-data credentials. Check ALPACA_DATA_API_KEY and ALPACA_DATA_SECRET.');
      } else if (message.includes('Twelve Data credentials were rejected')) {
        showMessage('error', 'Twelve Data rejected the API key or the plan lacks access.');
      } else {
        showMessage('error', message);
      }
    }
  });

  const orderForm = document.getElementById('order-form');
  if (orderForm) {
    orderForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      try {
        await request('/orders/paper', {
          method: 'POST',
          body: JSON.stringify({
            symbol: form.get('symbol'),
            agent_slug: form.get('agent_slug'),
            quantity: Number(form.get('quantity')),
            limit_price: Number(form.get('limit_price')),
            side: form.get('side'),
            remark: form.get('remark'),
          }),
        });
        await refreshOverview();
        showMessage('ok', `Submitted ${form.get('side')} ${form.get('symbol')}.`);
      } catch (error) {
        showMessage('error', error.message || 'Paper order failed.');
      }
    });
  }

  try {
    await refreshOverview();
  } catch (error) {
    showMessage('error', error.message || 'Dashboard load failed.');
  }
}

void init();



