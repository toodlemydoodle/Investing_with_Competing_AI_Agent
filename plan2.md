# moomoo Canada Picks-and-Shovels Investor MVP Plan

## Summary
- Build a greenfield, single-user AI-agent trading runtime for personal use: `moomoo Canada` first, with programmatic trading limited to `US-listed stocks and ETFs`.
- Strategy: invest in differentiated suppliers to fast-growing spend waves, not the eventual downstream winner and not on technical-analysis signals.
- V1 theme focus: AI infrastructure picks-and-shovels such as compute, networking, power/cooling, foundry/packaging, and related infrastructure bottlenecks.
- Runtime: your machine only. Interface is a local AI-agent control room with desktop notifications.
- Rollout: `paper` first, then `live_capped`; live mode auto-executes only small trades inside hard limits.
- Holding period: days to weeks, tied to filings, earnings, capex, demand, backlog, and guidance trends rather than intraday price movement.
- As of `March 5, 2026`, moomoo's OpenAPI update history says OpenAPI is available for users in `Canada`, which makes a moomoo-first build viable for this repo.

## Why This Plan Changes vs IBKR
- moomoo automation is built around a local gateway process, `OpenD`, plus the `moomoo-api` SDK. This is the main architectural difference from the IBKR plan.
- The agent runtime should treat `OpenD` as a required local dependency and monitor it like infrastructure, not as a hidden implementation detail.
- Trading account selection should be based on `acc_id` returned by `get_acc_list()`, because moomoo recommends using `acc_id` rather than a positional account index.
- Live trading requires an explicit `unlock_trade()` step with the transaction password before placing, modifying, or canceling orders.
- If moomoo token is enabled on the account, OpenAPI unlock fails. The setup flow must call this out explicitly.
- Paper trading is the correct first environment, but moomoo's docs say paper trading for US stocks does not support irregular trading hours, so v1 should stay `regular-hours only`.

## Product Scope
- V1 is `long-only`, `whole-share only`, `stocks/ETFs only`, `regular-hours only`, `no options`, `no shorting`, `no margin`, and `no extended-hours orders`.
- The investable universe is a manually approved seed list of `10-20` US-listed names.
- The agent runtime does not scan the whole market in v1.
- The strategy excludes `RSI`, `MACD`, moving-average crossovers, candlestick patterns, and other technical-analysis signals.
- The system is personal-use only, not a multi-user SaaS product.

## Broker Integration Plan
- Build a `MoomooAdapter` as the only live broker implementation for v1.
- Run `OpenD` locally on the same machine as the agent runtime.
- Keep market data and trading behind one broker abstraction so another adapter can be added later without rewriting the strategy stack.
- Required broker capabilities:
  - account discovery via `get_acc_list()`
  - account funds and buying power
  - positions
  - open orders and order history
  - order placement
  - order modification/cancel
  - order/deal push callbacks
  - trading-environment awareness: `SIMULATE` vs `REAL`
- Treat broker setup as a first-class feature:
  - verify `OpenD` is reachable
  - verify login succeeded
  - verify the expected `acc_id` exists
  - verify paper vs live environment
  - verify trade unlock state for live mode
  - surface clear remediation steps when any of the above fails

## Strategy Engine
- Define a `ThemeDefinition` for each investable wave with fields such as `theme_name`, `spend_driver`, `enablement_layer`, `winner_agnostic_case`, and `disqualifiers`.
- Score each company on six axes:
  - `theme_linkage`
  - `multi_winner_exposure`
  - `bottleneck_or_differentiation`
  - `growth_proof`
  - `management_proof`
  - `valuation_sanity`
- Add hard rejects before any order can be generated:
  - `reject_commodity`
  - `reject_ubiquity`
  - `reject_non_us_listing`
  - `reject_thesis_break`
  - `reject_liquidity`
- Re-rank companies after earnings, guidance changes, major capex announcements, or material backlog/order updates.
- Keep the portfolio small and thesis-driven rather than signal-driven.

## Research and Evidence Pipeline
- Ingest official investor-relations releases, earnings slides, annual reports, 10-K/10-Q/20-F filings, and major market news for each approved company.
- Normalize evidence into structured records with:
  - `source_type`
  - `publish_date`
  - `metric`
  - `quoted_growth`
  - `theme_relevance`
  - `confidence`
  - `evidence_text`
- Store extracted metrics and thesis notes separately so the model layer can be audited and re-run.
- Re-score only the affected companies when new evidence arrives.
- Require human approval to add or remove symbols from the seed universe in v1.

## Portfolio and Execution Rules
- Rebalance cadence is `event-driven` plus one daily review pass.
- Risk engine is the final gate and can only approve orders if bankroll, concentration, liquidity, spread, cooldown, and daily-loss checks pass.
- Default v1 limits:
  - bankroll cap `$250`
  - max order size `min($25, 10% of bankroll)`
  - max `5` open names
  - max `2` names per theme
  - max daily loss `$25`
- Additional moomoo-specific execution constraints:
  - use `paper` mode first, `live_capped` only after acceptance gates pass
  - use `limit` orders by default in v1
  - disable irregular-hours execution in all v1 modes
  - rate-limit order submission well below moomoo's published limits
  - treat order callbacks as authoritative for fills and status transitions
- The execution service supports `paused`, `paper`, and `live_capped`.

## Architecture
- Backend: `Python` service, because moomoo's official SDK and examples are strongest there.
- API layer: `FastAPI` for local HTTP and WebSocket endpoints.
- Frontend: local agent control room, likely `React` + `Vite`, unless a simpler server-rendered UI proves sufficient.
- Storage: `SQLite` for app state and auditability.
- Background jobs:
  - evidence ingestion
  - scoring
  - decision generation
  - broker sync
  - alerting
- Local services:
  - agent runtime backend
  - moomoo `OpenD`
  - optional scheduler/worker process if background work is split out

## Persistence Model
- `themes`
- `companies`
- `theme_company_membership`
- `evidence_records`
- `score_snapshots`
- `decision_runs`
- `order_intents`
- `broker_orders`
- `broker_fills`
- `positions`
- `alerts`
- `audit_logs`
- `settings`
- `broker_accounts`

## Public Interfaces / Types
- Core interfaces:
  - `BrokerAdapter`: `health_check()`, `list_accounts()`, `get_account()`, `list_positions()`, `list_open_orders()`, `submit_order()`, `cancel_order()`, `unlock_live_trading()`, `stream_order_updates()`
  - `ResearchSource`: `fetch_items(company)`, `normalize_item()`, `extract_evidence()`
  - `ThemeEngine`: `score_company(symbol, theme_id) -> ThemeCompanyScore`
  - `DecisionEngine`: `build_position_actions(theme_id) -> list[Decision]`
  - `RiskEngine`: `evaluate(intent, portfolio_state) -> Allow | Block(reason[])`
- Strategy types:
  - `ThemeDefinition`
  - `EvidenceRecord`
  - `ThemeCompanyScore`
  - `Decision`
  - `RiskResult`
  - `BrokerHealth`
  - `BrokerAccountRef`
- Backend API:
  - `GET /health`
  - `GET /broker/health`
  - `GET /broker/accounts`
  - `POST /broker/test`
  - `POST /mode`
  - `GET /themes`
  - `POST /themes`
  - `GET /companies`
  - `POST /watchlist`
  - `GET /positions`
  - `GET /decisions`
  - `GET /alerts`
  - `POST /risk-limits`
  - `WS /events`

## Agent Control Surfaces
- `Overview`: current mode, broker health, last sync, alerts, and current agent winner
- `Themes`: active theses and score leaders
- `Universe`: approved names and disqualifiers
- `Evidence`: filings, releases, extracted metrics, notes
- `Scores`: component score breakdowns and rejection reasons
- `Decisions`: proposed trades from each agent, blocked trades, rationale
- `Portfolio`: broker positions plus virtual per-agent capital, exposure, and realized/unrealized P&L
- `Orders`: intents, broker orders, fills, retries, failures
- `Broker`: `OpenD` health, account selection, environment, unlock status
- `Settings`: limits, notifications, credentials references, and agent runtime controls

## Delivery Phases
- Phase 0: foundation
  - create repo structure for backend, frontend, and shared types
  - define config model and local env conventions
  - add SQLite schema and migrations
  - add logging, error envelopes, and audit trail primitives
- Phase 1: moomoo connectivity
  - add `OpenD` health checks
  - implement account discovery with `get_acc_list()`
  - persist selected `acc_id`
  - implement positions, orders, and fills sync
  - implement paper-order placement and cancellation
  - surface broker status in the dashboard
- Phase 2: research pipeline
  - ingest seed-company IR sources
  - normalize evidence
  - store and review extracted facts
  - trigger re-scoring on new evidence
- Phase 3: strategy and decisions
  - implement theme definitions
  - implement scorecard and hard rejects
  - generate target actions
  - apply risk engine and create order intents
- Phase 4: controlled execution
  - wire decisions to paper trading
  - reconcile order/deal callbacks
  - add cooldowns, kill switch, and pause controls
  - add desktop notifications
- Phase 5: live-capped rollout
  - add explicit live unlock flow
  - add live-mode confirmation UX
  - enforce smaller caps than paper
  - run a supervised first-live checklist

## Test Plan
- Unit tests to verify technical indicators and beta inputs are never read by the decision engine.
- Unit tests for each score axis and each hard-reject rule.
- Unit tests for moomoo account selection so the app always targets the configured `acc_id`.
- Unit tests for mode safety so `paper` and `live_capped` cannot be confused.
- Integration tests for `OpenD` health detection, login failures, missing accounts, and locked live trading.
- Replay tests using captured filings, earnings releases, news items, and moomoo order events to verify evidence extraction and broker-state reconciliation.
- Paper-mode integration test:
  - new evidence
  - score update
  - decision
  - risk pass/block
  - simulated moomoo fill
  - dashboard update
- Acceptance gates before live:
  - at least `2 weeks` of paper trading on the approved universe
  - zero reconciliation mismatches after restart
  - zero malformed model outputs escaping schema validation
  - successful broker reconnect testing with `OpenD` restarts
  - manual review of first live config with notifications enabled

## Setup and Secrets
- Store moomoo login credentials, transaction password references, and model credentials in the OS keychain or a local secret manager.
- Do not store plaintext broker passwords in SQLite.
- Store only masked broker account references and the chosen `acc_id` in the runtime database.
- Add a startup checklist for:
  - `OpenD` installed
  - `OpenD` configured for local-only access unless remote access is explicitly needed
  - moomoo login working
  - paper account visible
  - live account visible only if the user intends to enable live mode

## Assumptions / Defaults
- Personal-use agent runtime, not multi-user SaaS.
- Seed theme for v1 is `AI picks-and-shovels`, not a broad market allocator.
- The investable universe is restricted to `US-listed stocks and ETFs`.
- Starter company examples that fit the thesis and are US-listed include `NVDA`, `ANET`, `VRT`, `AVGO`, and `TSM`.
- A company can still fail the strategy if the valuation check, concentration rules, or evidence quality are weak.
- The runtime defaults to `paper` on startup until the user explicitly changes mode.
- Because moomoo OpenAPI support for Canada is newly noted in the official update history on `March 5, 2026`, broker setup should be verified early with a real account before deeper execution work proceeds.

## Official References
- moomoo OpenAPI update history: <https://www.moomoo.com/download/OpenAPI>
- moomoo OpenAPI overview / download hub: <https://www.moomoo.com/openapi>
- moomoo API docs, trading overview: <https://openapi.moomoo.com/moomoo-api-doc/en/trade/overview.html>
- moomoo API docs, get account list: <https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-acc-list.html>
- moomoo API docs, unlock trade: <https://openapi.moomoo.com/moomoo-api-doc/en/trade/unlock.html>
- moomoo API docs, place order: <https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html>
- moomoo API docs, command-line OpenD: <https://openapi.moomoo.com/moomoo-api-doc/en/opend/opend-cmd.html>
- moomoo Canada site: <https://www.moomoo.com/ca>


