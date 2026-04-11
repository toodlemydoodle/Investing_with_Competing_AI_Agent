from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from html import unescape
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker.base import QuoteRecord
from app.core.config import Settings
from app.models.entities import AgentPosition
from app.models.entities import Company
from app.models.entities import Decision
from app.models.entities import ResearchNote
from app.models.entities import StrategyAgent
from app.services.quotes import get_quote_record
from app.services.trading import get_competition_benchmark_state
from app.services.trading import get_leader_bonus_award

GOOGLE_NEWS_RSS = 'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
SEC_TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
SEC_CURRENT_FEED_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&count=40&output=atom'
SEC_SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'
ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}
FORM_SCORES = {'8-K': 0.7, '10-Q': 1.0, '10-K': 1.2, '6-K': 0.4, 'S-3': -1.1, '424B5': -0.8, 'S-8': -0.4}
PICK_SHOVEL_THEME_NAMES = {'pick-and-shovel growth', 'pick and shovel growth', 'pick shovel growth'}
GENERAL_MIN_PRICE = 3.0
GENERAL_MAX_SPREAD_PCT = 3.5
DISCOVERY_MIN_PRICE = 8.0
DISCOVERY_MIN_DOLLAR_VOLUME = 2_000_000.0
DISCOVERY_MAX_SPREAD_PCT = 2.0
APPROVAL_PROMOTION_STREAK = 2
APPROVAL_DEMOTION_STREAK = 3
APPROVAL_TRACKING_LOOKBACK_DAYS = 21
COMPETITION_EPSILON = 1e-9



@dataclass(slots=True)
class CandidateIdea:
    symbol: str
    theme_name: str
    target_weight: float
    max_notional: float
    conviction_score: float
    rationale: str
    status: str


@dataclass(slots=True)
class CandidateEvidence:
    idea: CandidateIdea
    notes: list[dict[str, Any]]
    market: MarketContext
    profile: dict[str, Any]
    analysis: dict[str, Any]


@dataclass(slots=True)
class MarketContext:
    last_price: float
    bid_price: float
    ask_price: float
    prev_close_price: float
    quote_change_pct: float
    spread_pct: float | None
    day_volume: float
    dollar_volume: float
    trade_count: float


@dataclass(slots=True)
class CompetitionPressure:
    benchmark_symbol: str
    benchmark_return_gap_pct: float | None
    opponent_name: str | None
    opponent_return_gap_pct: float | None
    missed_bonus: bool
    received_bonus: bool
    bonus_amount: float
    aggression: float
    discipline: float


class ResearchError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _sec_ticker_map_cache() -> dict[str, dict[str, str]]:
    return {}


def _http_request_text(url: str, settings: Settings, headers: dict[str, str] | None = None) -> str:
    request_headers = {
        'User-Agent': settings.research_http_user_agent,
        'Accept': 'application/json, application/xml, text/xml, text/plain;q=0.9, */*;q=0.1',
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=settings.research_http_timeout_seconds) as response:
            return response.read().decode('utf-8', errors='replace')
    except HTTPError as exc:
        raise ResearchError(f'HTTP {exc.code} while fetching {url}') from exc
    except URLError as exc:
        raise ResearchError(f'Network error while fetching {url}: {exc.reason}') from exc


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized.startswith('US.'):
        normalized = f'US.{normalized}'
    return normalized


def _ticker_from_symbol(symbol: str) -> str:
    return _normalize_symbol(symbol).split('.', 1)[1]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _format_dollar_amount(amount: float) -> str:
    rounded = round(float(amount), 2)
    if abs(rounded - round(rounded)) < COMPETITION_EPSILON:
        return f'${rounded:.0f}'
    return f'${rounded:.2f}'


def _neutral_competition_pressure(benchmark_symbol: str) -> CompetitionPressure:
    return CompetitionPressure(
        benchmark_symbol=benchmark_symbol,
        benchmark_return_gap_pct=None,
        opponent_name=None,
        opponent_return_gap_pct=None,
        missed_bonus=False,
        received_bonus=False,
        bonus_amount=0.0,
        aggression=0.0,
        discipline=0.0,
    )


def _competition_pressure_map(db: Session, settings: Settings) -> dict[str, CompetitionPressure]:
    benchmark_state = get_competition_benchmark_state(db, settings, refresh=False)
    benchmark_symbol = str(benchmark_state.get('symbol') or settings.competition_benchmark_symbol)
    benchmark_return_pct = benchmark_state.get('return_pct')
    bonus_recipient, bonus_amount = get_leader_bonus_award(db)
    active_agents = db.scalars(
        select(StrategyAgent)
        .where(StrategyAgent.is_enabled.is_(True), StrategyAgent.is_alive.is_(True))
        .order_by(StrategyAgent.slug)
    ).all()

    pressure_by_agent: dict[str, CompetitionPressure] = {}
    for agent in active_agents:
        opponents = [other for other in active_agents if other.slug != agent.slug]
        opponent = None
        if opponents:
            opponent = max(opponents, key=lambda other: (other.total_return_pct, other.current_value, other.slug))

        benchmark_gap_pct = None
        if benchmark_return_pct is not None:
            benchmark_gap_pct = round(float(agent.total_return_pct) - float(benchmark_return_pct), 2)

        opponent_gap_pct = None
        if opponent is not None:
            opponent_gap_pct = round(float(agent.total_return_pct) - float(opponent.total_return_pct), 2)

        trailing_deficit = max(-(opponent_gap_pct or 0.0), 0.0)
        benchmark_deficit = max(-(benchmark_gap_pct or 0.0), 0.0)
        aggression = _clamp(
            (0.55 if bonus_amount > COMPETITION_EPSILON and bonus_recipient and bonus_recipient != agent.slug else 0.0)
            + min(trailing_deficit / 8.0, 0.45)
            + min(benchmark_deficit / 8.0, 0.35),
            0.0,
            1.0,
        )
        discipline = _clamp(
            (0.30 if bonus_amount > COMPETITION_EPSILON and bonus_recipient == agent.slug else 0.0)
            + min(max(opponent_gap_pct or 0.0, 0.0) / 12.0, 0.35)
            + (0.10 if (benchmark_gap_pct or 0.0) > 0 else 0.0),
            0.0,
            0.75,
        )
        pressure_by_agent[agent.slug] = CompetitionPressure(
            benchmark_symbol=benchmark_symbol,
            benchmark_return_gap_pct=benchmark_gap_pct,
            opponent_name=opponent.name if opponent is not None else None,
            opponent_return_gap_pct=opponent_gap_pct,
            missed_bonus=bool(bonus_amount > COMPETITION_EPSILON and bonus_recipient and bonus_recipient != agent.slug),
            received_bonus=bool(bonus_amount > COMPETITION_EPSILON and bonus_recipient == agent.slug),
            bonus_amount=bonus_amount,
            aggression=round(aggression, 3),
            discipline=round(discipline, 3),
        )

    return pressure_by_agent


def _competition_context_summary(pressure: CompetitionPressure) -> str:
    if pressure.aggression <= COMPETITION_EPSILON and pressure.discipline <= COMPETITION_EPSILON:
        return ''

    if pressure.aggression > pressure.discipline:
        parts: list[str] = []
        if pressure.opponent_name and pressure.opponent_return_gap_pct is not None and pressure.opponent_return_gap_pct < 0:
            parts.append(f"trailing {pressure.opponent_name} by {abs(pressure.opponent_return_gap_pct):.1f} pts")
        if pressure.benchmark_return_gap_pct is not None and pressure.benchmark_return_gap_pct < 0:
            parts.append(f"trailing {pressure.benchmark_symbol} by {abs(pressure.benchmark_return_gap_pct):.1f} pts")
        summary = 'Competition context: '
        summary += ' and '.join(parts) if parts else 'the agent is behind.'
        summary += '.'
        if pressure.missed_bonus and pressure.opponent_name:
            summary += (
                f" The latest {_format_dollar_amount(pressure.bonus_amount)} bonus went to {pressure.opponent_name}, "
                'so the strongest ideas get a modest urgency bump.'
            )
        else:
            summary += ' The strongest ideas get a modest urgency bump.'
        return summary

    parts = []
    if pressure.opponent_name and pressure.opponent_return_gap_pct is not None and pressure.opponent_return_gap_pct > 0:
        parts.append(f"leading {pressure.opponent_name} by {pressure.opponent_return_gap_pct:.1f} pts")
    if pressure.received_bonus:
        parts.append(f"holding the latest {_format_dollar_amount(pressure.bonus_amount)} bonus")
    summary = 'Competition context: '
    summary += ' and '.join(parts) if parts else 'the agent is protecting its lead.'
    summary += '. Marginal risk-taking is trimmed to defend the lead.'
    return summary


def _competition_adjusted_conviction(
    conviction: float,
    pressure: CompetitionPressure,
    *,
    is_held: bool,
) -> float:
    adjusted = conviction
    if pressure.aggression > COMPETITION_EPSILON:
        if conviction >= 7.5:
            adjusted += 0.35 * pressure.aggression
        elif conviction >= 6.8:
            adjusted += 0.20 * pressure.aggression
        elif conviction >= 6.2 and not is_held:
            adjusted += 0.08 * pressure.aggression
    elif pressure.discipline > COMPETITION_EPSILON and not is_held:
        adjusted -= (0.18 if conviction <= 7.0 else 0.10) * pressure.discipline
    return round(_clamp(adjusted, 0.0, 10.0), 2)


def _safe_parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace('Z', '+00:00')
    for pattern in (cleaned, cleaned.replace(' ', 'T')):
        try:
            return datetime.fromisoformat(pattern).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _days_old(published_at: datetime | None, now: datetime) -> float | None:
    if published_at is None:
        return None
    delta = now - published_at
    return max(delta.total_seconds() / 86400.0, 0.0)


def _recency_weight(published_at: datetime | None, now: datetime, *, fresh_days: float, recent_days: float, stale_days: float) -> float:
    age_days = _days_old(published_at, now)
    if age_days is None:
        return 0.35
    if age_days <= fresh_days:
        return 1.0
    if age_days <= recent_days:
        return 0.75
    if age_days <= stale_days:
        return 0.5
    return 0.25


def _source_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower().strip()
    return host or None


def _company_rows(db: Session, *, approved_only: bool = True) -> dict[str, Company]:
    stmt = select(Company)
    if approved_only:
        stmt = stmt.where(Company.is_approved.is_(True))
    rows = db.scalars(stmt).all()
    return {company.symbol: company for company in rows}


def _tracked_specialist_symbols(company_map: dict[str, Company], now: datetime) -> list[str]:
    cutoff = now - timedelta(days=APPROVAL_TRACKING_LOOKBACK_DAYS)
    candidates = [
        company
        for company in company_map.values()
        if (
            company.theme_name.lower() in PICK_SHOVEL_THEME_NAMES
            and not company.is_approved
            and (
                company.approval_source == 'dynamic'
                or ((company.last_researched_at is not None) and company.last_researched_at >= cutoff)
                or company.approval_positive_streak > 0
            )
        )
    ]
    candidates.sort(
        key=lambda company: (
            company.last_conviction_score,
            company.total_score,
            company.last_researched_at or datetime.min,
        ),
        reverse=True,
    )
    return [company.symbol for company in candidates]


def _ensure_specialist_company_row(
    db: Session,
    company_map: dict[str, Company],
    symbol: str,
    profile: dict[str, Any],
    rationale: str,
) -> Company:
    normalized = _normalize_symbol(symbol)
    company = company_map.get(normalized)
    base_score = round(_clamp(_to_float(profile.get('base_score'), 5.8), 0.0, 10.0), 2)
    default_rationale = str(rationale or profile.get('rationale') or '').strip() or f'Specialist tracking candidate for {normalized}.'

    if company is None:
        company = Company(
            symbol=normalized,
            name=str(profile.get('name', _ticker_from_symbol(normalized)))[:200],
            theme_name='Pick-and-Shovel Growth',
            sector=str(profile.get('sector', 'Unknown'))[:120],
            theme_linkage=base_score,
            multi_winner_exposure=base_score,
            bottleneck_or_differentiation=base_score,
            growth_proof=base_score,
            management_proof=base_score,
            valuation_sanity=5.5,
            total_score=base_score,
            rationale=default_rationale,
            is_approved=False,
            approval_source='dynamic',
        )
        db.add(company)
        db.flush()
        company_map[normalized] = company
        return company

    if profile.get('name'):
        company.name = str(profile.get('name'))[:200]
    if profile.get('sector'):
        company.sector = str(profile.get('sector'))[:120]
    if default_rationale:
        company.rationale = default_rationale
    return company


def _sync_specialist_company_state(
    company: Company,
    idea: CandidateIdea,
    analysis: dict[str, Any],
    now: datetime,
    *,
    passes_gate: bool,
    is_held: bool,
    settings: Settings,
) -> None:
    trend = analysis.get('trend') or {}
    porter = analysis.get('porter') or {}
    company.theme_name = 'Pick-and-Shovel Growth'
    company.total_score = round(float(idea.conviction_score), 2)
    company.last_conviction_score = round(float(idea.conviction_score), 2)
    company.last_researched_at = now
    company.rationale = str(idea.rationale or company.rationale or '').strip() or company.rationale
    company.theme_linkage = round(_clamp(_to_float(trend.get('theme_heat'), idea.conviction_score), 0.0, 10.0), 2)
    company.multi_winner_exposure = round(_clamp(_to_float(trend.get('capex_alignment'), idea.conviction_score), 0.0, 10.0), 2)
    company.bottleneck_or_differentiation = round(_clamp(_to_float(trend.get('mission_criticality'), idea.conviction_score), 0.0, 10.0), 2)
    company.growth_proof = round(_clamp(_to_float(trend.get('execution_readiness'), idea.conviction_score), 0.0, 10.0), 2)
    company.management_proof = round(_clamp(_to_float(porter.get('overall'), idea.conviction_score), 0.0, 10.0), 2)

    strong_signal = passes_gate and idea.conviction_score >= settings.research_min_buy_score
    weak_signal = (not passes_gate) or idea.conviction_score < settings.research_min_hold_score

    if strong_signal:
        company.approval_positive_streak += 1
        company.approval_negative_streak = 0
    elif weak_signal and not is_held:
        company.approval_negative_streak += 1
        company.approval_positive_streak = 0
    else:
        company.approval_positive_streak = 0
        company.approval_negative_streak = 0

    if company.approval_positive_streak >= APPROVAL_PROMOTION_STREAK:
        company.is_approved = True
        if company.approval_source != 'baseline':
            company.approval_source = 'dynamic'

    if company.is_approved and company.approval_negative_streak >= APPROVAL_DEMOTION_STREAK and not is_held:
        company.is_approved = False


def _agent_position_symbols(db: Session, agent: StrategyAgent) -> list[str]:
    return [
        position.symbol
        for position in db.scalars(select(AgentPosition).where(AgentPosition.agent_slug == agent.slug, AgentPosition.quantity > 0)).all()
    ]


def _load_sec_ticker_map(settings: Settings) -> dict[str, dict[str, str]]:
    cache = _sec_ticker_map_cache()
    if cache:
        return cache
    payload = _http_request_text(SEC_TICKERS_URL, settings)
    raw = json.loads(payload)
    for item in raw.values():
        ticker = str(item.get('ticker', '')).upper().strip()
        if not ticker or not re.fullmatch(r'[A-Z]{1,5}', ticker):
            continue
        cache[ticker] = {
            'ticker': ticker,
            'name': str(item.get('title', ticker)).strip(),
            'cik': str(item.get('cik_str', '')).strip(),
        }
    return cache


def _current_feed_discoveries(settings: Settings, limit: int) -> list[dict[str, str]]:
    if settings.quote_provider.lower() == 'mock':
        return []
    try:
        ticker_map = _load_sec_ticker_map(settings)
        cik_index = {meta['cik'].lstrip('0'): meta for meta in ticker_map.values() if meta.get('cik')}
        xml_text = _http_request_text(SEC_CURRENT_FEED_URL, settings, {'Accept': 'application/atom+xml, application/xml;q=0.9'})
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in root.findall('atom:entry', ATOM_NS):
        title = (entry.findtext('atom:title', default='', namespaces=ATOM_NS) or '').strip()
        summary = unescape((entry.findtext('atom:summary', default='', namespaces=ATOM_NS) or '').strip())
        updated = (entry.findtext('atom:updated', default='', namespaces=ATOM_NS) or '').strip()
        link_el = entry.find('atom:link', ATOM_NS)
        link = link_el.attrib.get('href', '') if link_el is not None else ''
        match = re.search(r'\((\d{1,10})\)', title) or re.search(r'CIK(?:=|\s)(\d{1,10})', summary)
        if not match:
            continue
        cik = match.group(1).lstrip('0')
        meta = cik_index.get(cik)
        if not meta:
            continue
        ticker = meta['ticker']
        symbol = _normalize_symbol(ticker)
        if symbol in seen:
            continue
        seen.add(symbol)
        results.append({
            'symbol': symbol,
            'name': meta['name'],
            'source_title': title or f'Recent SEC filing for {ticker}',
            'source_url': link,
            'published_at': updated,
        })
        if len(results) >= limit:
            break
    return results


def _news_notes_for_symbol(settings: Settings, symbol: str, company_name: str, now: datetime) -> list[dict[str, Any]]:
    if settings.quote_provider.lower() == 'mock':
        return []
    ticker = _ticker_from_symbol(symbol)
    query = quote_plus(f'"{ticker}" "{company_name}" stock')
    url = GOOGLE_NEWS_RSS.format(query=query)
    try:
        xml_text = _http_request_text(url, settings, {'Accept': 'application/rss+xml, application/xml;q=0.9'})
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    items = root.findall('./channel/item')
    notes: list[dict[str, Any]] = []
    for item in items[: settings.research_news_items_per_symbol]:
        title = unescape((item.findtext('title') or '').strip())
        link = (item.findtext('link') or '').strip()
        pub_date = (item.findtext('pubDate') or '').strip()
        published_at = _safe_parse_datetime(pub_date)
        attention_score = 0.12 + (0.22 * _recency_weight(published_at, now, fresh_days=1.0, recent_days=3.0, stale_days=10.0))
        notes.append(
            {
                'source_type': 'news',
                'source_title': title or f'News item for {symbol}',
                'source_url': link or None,
                'note_text': title or f'News item for {symbol}',
                'note_score': round(attention_score, 2),
                'published_at': published_at,
                'raw_payload': {'headline': title, 'link': link, 'published_at': pub_date},
            }
        )
    return notes


def _filing_notes_for_symbol(settings: Settings, symbol: str, now: datetime) -> list[dict[str, Any]]:
    if settings.quote_provider.lower() == 'mock':
        return []
    ticker = _ticker_from_symbol(symbol)
    try:
        meta = _load_sec_ticker_map(settings).get(ticker)
        if not meta or not meta.get('cik'):
            return []
        payload = _http_request_text(SEC_SUBMISSIONS_URL.format(cik=str(meta['cik']).zfill(10)), settings)
        data = json.loads(payload)
    except Exception:
        return []

    recent = data.get('filings', {}).get('recent', {})
    forms = recent.get('form', []) or []
    filing_dates = recent.get('filingDate', []) or []
    accessions = recent.get('accessionNumber', []) or []
    primary_docs = recent.get('primaryDocument', []) or []
    notes: list[dict[str, Any]] = []
    for index, form in enumerate(forms[: max(settings.research_filings_per_symbol * 3, 6)]):
        form_name = str(form).strip()
        if form_name not in FORM_SCORES:
            continue
        filing_date = str(filing_dates[index]) if index < len(filing_dates) else ''
        accession = str(accessions[index]).replace('-', '') if index < len(accessions) else ''
        primary_doc = str(primary_docs[index]).strip() if index < len(primary_docs) else ''
        published_at = _safe_parse_datetime(filing_date)
        url = None
        if accession and primary_doc:
            url = f'https://www.sec.gov/Archives/edgar/data/{int(meta["cik"]):d}/{accession}/{primary_doc}'
        score = FORM_SCORES.get(form_name, 0.0) * _recency_weight(
            published_at,
            now,
            fresh_days=7.0,
            recent_days=30.0,
            stale_days=90.0,
        )
        notes.append(
            {
                'source_type': 'filing',
                'source_title': f'{form_name} filed for {ticker}',
                'source_url': url,
                'note_text': f'Recent SEC filing {form_name} for {ticker} on {filing_date}.',
                'note_score': round(score, 2),
                'published_at': published_at,
                'raw_payload': {'form': form_name, 'filing_date': filing_date, 'primary_doc': primary_doc},
            }
        )
        if len(notes) >= settings.research_filings_per_symbol:
            break
    return notes


def _pick_shovel_signal_profile(
    profile: dict[str, Any],
    company_row: Company | None,
) -> dict[str, Any]:
    theme_name = str(company_row.theme_name if company_row is not None else profile.get('theme_name', '')).strip()
    themed_pick_shovel = theme_name.lower() in PICK_SHOVEL_THEME_NAMES
    base_score = _to_float(profile.get('base_score'), 6.8)
    theme_linkage = _company_metric(company_row, 'theme_linkage', base_score)
    multi = _company_metric(company_row, 'multi_winner_exposure', base_score)
    bottleneck = _company_metric(company_row, 'bottleneck_or_differentiation', base_score)
    growth = _company_metric(company_row, 'growth_proof', base_score)
    structural_strength = round((theme_linkage * 0.35) + (multi * 0.25) + (bottleneck * 0.40), 2)
    mission_criticality = round((bottleneck * 0.55) + (multi * 0.25) + (growth * 0.20), 2)
    is_candidate = company_row is not None and (themed_pick_shovel or (structural_strength >= 7.6 and mission_criticality >= 7.4))
    qualification_basis = 'curated pick-and-shovel thesis' if themed_pick_shovel else 'company bottleneck metrics'
    return {
        'theme_alignment': theme_linkage,
        'structural_strength': structural_strength,
        'mission_criticality': mission_criticality,
        'is_candidate': is_candidate,
        'has_curated_theme': themed_pick_shovel,
        'qualification_basis': qualification_basis,
    }


def _symbol_profile(symbol: str, company_map: dict[str, Company], discovered_meta: dict[str, dict[str, str]]) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    company = company_map.get(normalized)
    if company is not None:
        return {
            'name': company.name,
            'sector': company.sector,
            'base_score': company.total_score,
            'theme_name': company.theme_name,
            'rationale': company.rationale,
            'source': 'approved-company',
        }
    if normalized in discovered_meta:
        return {
            'name': discovered_meta[normalized].get('name', _ticker_from_symbol(normalized)),
            'sector': 'Recent Filing Discovery',
            'base_score': 5.8,
            'theme_name': 'Discovered US Stocks',
            'rationale': discovered_meta[normalized].get('source_title', ''),
            'source': 'discovery',
        }
    return {
        'name': _ticker_from_symbol(normalized),
        'sector': 'Unknown',
        'base_score': 5.5,
        'theme_name': 'Unclassified',
        'rationale': '',
        'source': 'unknown',
    }

def _market_context_from_quote(quote: QuoteRecord) -> MarketContext:
    payload = quote.raw_payload if isinstance(quote.raw_payload, dict) else {}
    daily_bar = payload.get('dailyBar') if isinstance(payload.get('dailyBar'), dict) else {}
    prev_daily_bar = payload.get('prevDailyBar') if isinstance(payload.get('prevDailyBar'), dict) else {}
    day_volume = _to_float(daily_bar.get('v')) or _to_float(prev_daily_bar.get('v')) or _to_float(payload.get('volume'))
    trade_count = _to_float(daily_bar.get('n')) or _to_float(payload.get('number_of_trades'))
    quote_change_pct = 0.0
    if quote.prev_close_price > 0:
        quote_change_pct = ((quote.last_price - quote.prev_close_price) / quote.prev_close_price) * 100.0
    spread_pct = None
    if quote.bid_price > 0 and quote.ask_price > 0 and quote.ask_price >= quote.bid_price:
        midpoint = (quote.bid_price + quote.ask_price) / 2.0
        if midpoint > 0:
            spread_pct = ((quote.ask_price - quote.bid_price) / midpoint) * 100.0
    return MarketContext(
        last_price=quote.last_price,
        bid_price=quote.bid_price,
        ask_price=quote.ask_price,
        prev_close_price=quote.prev_close_price,
        quote_change_pct=quote_change_pct,
        spread_pct=spread_pct,
        day_volume=day_volume,
        dollar_volume=day_volume * max(quote.last_price, 0.0),
        trade_count=trade_count,
    )


def _passes_market_gate(
    agent: StrategyAgent,
    symbol: str,
    profile: dict[str, Any],
    market: MarketContext,
    notes: list[dict[str, Any]],
    company_row: Company | None,
) -> bool:
    if market.last_price <= 0:
        return False
    if market.last_price < GENERAL_MIN_PRICE:
        return False
    if market.spread_pct is not None and market.spread_pct > GENERAL_MAX_SPREAD_PCT:
        return False

    if agent.slug == 'pick-shovel-growth':
        signal = _pick_shovel_signal_profile(profile, company_row)
        if not signal['is_candidate']:
            return False
        if market.last_price < 5.0:
            return False
        if market.dollar_volume > 0 and market.dollar_volume < 5_000_000:
            return False
        return True

    if profile.get('sector') == 'Recent Filing Discovery':
        filing_count = sum(1 for note in notes if note['source_type'] == 'filing')
        news_count = sum(1 for note in notes if note['source_type'] == 'news')
        if market.last_price < DISCOVERY_MIN_PRICE:
            return False
        if market.dollar_volume <= 0 or market.dollar_volume < DISCOVERY_MIN_DOLLAR_VOLUME:
            return False
        if market.spread_pct is not None and market.spread_pct > DISCOVERY_MAX_SPREAD_PCT:
            return False
        if filing_count < 1 or news_count < 2:
            return False
    return True

def _company_metric(company_row: Company | None, attribute: str, fallback: float) -> float:
    if company_row is None:
        return _clamp(fallback, 0.0, 10.0)
    return _clamp(_to_float(getattr(company_row, attribute, fallback), fallback), 0.0, 10.0)


def _filing_analysis(notes: list[dict[str, Any]], now: datetime) -> dict[str, float]:
    filing_notes = [note for note in notes if note['source_type'] == 'filing']
    if not filing_notes:
        return {'count': 0.0, 'net_signal': 0.0, 'freshness': 0.0, 'quality': 4.2}

    freshness = sum(
        _recency_weight(note.get('published_at'), now, fresh_days=7.0, recent_days=30.0, stale_days=90.0)
        for note in filing_notes
    ) / len(filing_notes)
    net_signal = sum(_to_float(note.get('note_score')) for note in filing_notes)
    quality = _clamp(4.5 + (net_signal * 1.4) + (freshness * 1.25) + (min(len(filing_notes), 3) * 0.25), 0.0, 10.0)
    return {
        'count': float(len(filing_notes)),
        'net_signal': round(net_signal, 2),
        'freshness': round(freshness, 2),
        'quality': round(quality, 2),
    }


def _news_coverage_analysis(notes: list[dict[str, Any]], now: datetime) -> dict[str, float]:
    news_notes = [note for note in notes if note['source_type'] == 'news']
    if not news_notes:
        return {'count': 0.0, 'domains': 0.0, 'freshness': 0.0, 'quality': 4.0}

    domains = {_source_domain(note.get('source_url')) for note in news_notes}
    domains.discard(None)
    freshness = sum(
        _recency_weight(note.get('published_at'), now, fresh_days=1.0, recent_days=3.0, stale_days=10.0)
        for note in news_notes
    ) / len(news_notes)
    quality = _clamp(
        4.4 + (min(len(news_notes), 4) * 0.45) + (min(len(domains), 3) * 0.55) + (freshness * 1.4),
        0.0,
        10.0,
    )
    return {
        'count': float(len(news_notes)),
        'domains': float(len(domains)),
        'freshness': round(freshness, 2),
        'quality': round(quality, 2),
    }


def _market_quality_component(market: MarketContext) -> float:
    score = 4.8
    if market.last_price >= 100:
        score += 1.0
    elif market.last_price >= 40:
        score += 0.8
    elif market.last_price >= 10:
        score += 0.5
    elif market.last_price >= 5:
        score += 0.2
    else:
        score -= 1.4

    if market.dollar_volume >= 1_000_000_000:
        score += 2.0
    elif market.dollar_volume >= 250_000_000:
        score += 1.4
    elif market.dollar_volume >= 50_000_000:
        score += 1.0
    elif market.dollar_volume >= 10_000_000:
        score += 0.6
    elif market.dollar_volume >= 2_000_000:
        score += 0.25
    else:
        score -= 1.5

    if market.spread_pct is not None:
        if market.spread_pct <= 0.15:
            score += 0.6
        elif market.spread_pct <= 0.4:
            score += 0.25
        elif market.spread_pct > 2.0:
            score -= 1.2
        elif market.spread_pct > 1.0:
            score -= 0.6

    return round(_clamp(score, 0.0, 10.0), 2)


def _price_trend_component(market: MarketContext) -> float:
    score = 5.0
    if market.prev_close_price > 0:
        score += _clamp(market.quote_change_pct / 2.75, -1.75, 1.75)
    if market.trade_count >= 50_000:
        score += 0.4
    elif market.trade_count >= 5_000:
        score += 0.2
    return round(_clamp(score, 0.0, 10.0), 2)


def _business_quality_component(profile: dict[str, Any], company_row: Company | None) -> float:
    base_score = _clamp(_to_float(profile.get('base_score'), 5.8), 0.0, 10.0)
    total_score = _company_metric(company_row, 'total_score', base_score)
    growth = _company_metric(company_row, 'growth_proof', base_score)
    management = _company_metric(company_row, 'management_proof', base_score)
    moat = _company_metric(company_row, 'bottleneck_or_differentiation', base_score)
    return round((total_score * 0.35) + (growth * 0.25) + (management * 0.20) + (moat * 0.20), 2)


def _liberated_dossier(
    profile: dict[str, Any],
    market: MarketContext,
    notes: list[dict[str, Any]],
    company_row: Company | None,
    now: datetime,
) -> dict[str, Any]:
    filing = _filing_analysis(notes, now)
    coverage = _news_coverage_analysis(notes, now)
    market_quality = _market_quality_component(market)
    business_quality = _business_quality_component(profile, company_row)
    price_trend = _price_trend_component(market)
    evidence_quality = round((filing['quality'] * 0.55) + (coverage['quality'] * 0.45), 2)
    trend_fit = round(
        _clamp(
            (price_trend * 0.60) + ((filing['freshness'] * 10.0) * 0.20) + ((coverage['freshness'] * 10.0) * 0.20),
            0.0,
            10.0,
        ),
        2,
    )
    discovery_penalty = 0.8 if profile.get('sector') == 'Recent Filing Discovery' else 0.0
    optionality = round(_clamp(business_quality - discovery_penalty + (0.35 if market.last_price >= 25 else 0.0), 0.0, 10.0), 2)
    return {
        'business_quality': business_quality,
        'evidence_quality': evidence_quality,
        'market_quality': market_quality,
        'trend_fit': trend_fit,
        'optionality': optionality,
        'filing': filing,
        'coverage': coverage,
    }


def _liberated_pairwise_score(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
    dimensions = ('business_quality', 'evidence_quality', 'market_quality', 'trend_fit', 'optionality')
    left_points = 0.0
    right_points = 0.0
    for dimension in dimensions:
        delta = _to_float(left.get(dimension)) - _to_float(right.get(dimension))
        if abs(delta) < 0.2:
            continue
        award = 1.25 if abs(delta) >= 1.0 else 1.0
        if delta > 0:
            left_points += award
        else:
            right_points += award
    return left_points, right_points


def _build_liberated_rationale(
    agent: StrategyAgent,
    row: CandidateEvidence,
    conviction: float,
    rank_index: int,
    total_candidates: int,
    pressure: CompetitionPressure,
) -> str:
    metrics = {
        'business quality': row.analysis['business_quality'],
        'evidence depth': row.analysis['evidence_quality'],
        'market quality': row.analysis['market_quality'],
        'trend fit': row.analysis['trend_fit'],
        'optionality': row.analysis['optionality'],
    }
    ordered = sorted(metrics.items(), key=lambda item: item[1], reverse=True)
    strongest = ', '.join(f'{label} {value:.1f}/10' for label, value in ordered[:2])
    weakest_label, weakest_value = ordered[-1]
    parts = [
        f"{row.profile.get('name', row.idea.symbol)} ranked {rank_index + 1} of {total_candidates} for {agent.name} after comparing live dossiers rather than using a fixed additive formula.",
        f'Strongest edges were {strongest}.',
        f'Weakest area was {weakest_label} at {weakest_value:.1f}/10.',
        f'Final conviction landed at {conviction:.1f}/10.',
    ]
    if row.market.dollar_volume > 0:
        parts.append(f"Approximate daily dollar volume is ${row.market.dollar_volume / 1_000_000:.1f}M.")
    if row.market.spread_pct is not None:
        parts.append(f'Observed spread is {row.market.spread_pct:.2f}%.')
    competition_summary = _competition_context_summary(pressure)
    if competition_summary:
        parts.append(competition_summary)
    return ' '.join(parts)


def _finalize_liberated_candidates(
    rows: list[CandidateEvidence],
    held_symbols: set[str],
    settings: Settings,
    agent: StrategyAgent,
    pressure: CompetitionPressure,
) -> list[CandidateEvidence]:
    if not rows:
        return rows

    for row in rows:
        pairwise_score = 0.0
        win_count = 0
        for other in rows:
            if row is other:
                continue
            wins, losses = _liberated_pairwise_score(row.analysis, other.analysis)
            if wins > losses:
                win_count += 1
                pairwise_score += 1.0 + ((wins - losses) * 0.15)
            elif wins == losses:
                pairwise_score += 0.25
        row.analysis['pairwise_score'] = round(pairwise_score, 2)
        row.analysis['win_count'] = win_count

    ranked = sorted(
        rows,
        key=lambda row: (
            row.analysis['pairwise_score'],
            row.analysis['business_quality'],
            row.analysis['trend_fit'],
            row.analysis['market_quality'],
        ),
        reverse=True,
    )

    total = len(ranked)
    buy_slots = min(total, max(2, min(3, settings.research_max_generated_decisions_per_agent - 1)))
    hold_slots = min(total, buy_slots + max(1, len(held_symbols)))

    for index, row in enumerate(ranked):
        percentile = 1.0 if total == 1 else 1.0 - (index / max(total - 1, 1))
        dossier_average = (
            row.analysis['business_quality']
            + row.analysis['evidence_quality']
            + row.analysis['market_quality']
            + row.analysis['trend_fit']
            + row.analysis['optionality']
        ) / 5.0
        base_conviction = round(_clamp((dossier_average * 0.62) + (percentile * 3.6), 0.0, 10.0), 2)
        conviction = _competition_adjusted_conviction(
            base_conviction,
            pressure,
            is_held=row.idea.symbol in held_symbols,
        )
        if not row.analysis.get('passes_gate'):
            status = 'research-avoid'
        elif index < buy_slots and conviction >= settings.research_min_buy_score:
            status = 'research-buy'
        elif row.idea.symbol in held_symbols and index < hold_slots and conviction >= settings.research_min_hold_score:
            status = 'research-hold'
        else:
            status = 'research-avoid'

        target_weight = _candidate_target_weight(agent, conviction, pressure)
        row.idea = CandidateIdea(
            symbol=row.idea.symbol,
            theme_name=row.idea.theme_name,
            target_weight=target_weight,
            max_notional=_candidate_max_notional(settings, agent, target_weight, row.market),
            conviction_score=conviction,
            rationale=_build_liberated_rationale(agent, row, conviction, index, total, pressure),
            status=status,
        )

    return ranked


def _pick_shovel_porter_forces(
    profile: dict[str, Any],
    market: MarketContext,
    notes: list[dict[str, Any]],
    company_row: Company | None,
    now: datetime,
) -> dict[str, float]:
    signal = _pick_shovel_signal_profile(profile, company_row)
    base_score = _to_float(profile.get('base_score'), 6.8)
    theme = _company_metric(company_row, 'theme_linkage', base_score)
    multi = _company_metric(company_row, 'multi_winner_exposure', base_score)
    moat = _company_metric(company_row, 'bottleneck_or_differentiation', base_score)
    growth = _company_metric(company_row, 'growth_proof', base_score)
    management = _company_metric(company_row, 'management_proof', base_score)
    valuation = _company_metric(company_row, 'valuation_sanity', 6.0)
    filing = _filing_analysis(notes, now)
    market_quality = _market_quality_component(market)

    infrastructure_bonus = max((signal['structural_strength'] - 7.0) * 0.25, 0.0)
    vertical_control_bonus = 0.35 if signal['theme_alignment'] >= 8.0 else 0.0
    outsourced_penalty = 0.25 if signal['mission_criticality'] < 7.5 else 0.0
    buyer_bonus = 0.35 if signal['mission_criticality'] >= 8.0 else (0.15 if signal['mission_criticality'] >= 7.5 else 0.0)
    substitute_bonus = 0.35 if signal['structural_strength'] >= 8.0 else (0.15 if signal['structural_strength'] >= 7.5 else 0.0)

    entrants = round(_clamp(((moat + theme + management) / 3.0) + infrastructure_bonus, 0.0, 10.0), 2)
    suppliers = round(_clamp(((growth + management + market_quality) / 3.0) + vertical_control_bonus - outsourced_penalty, 0.0, 10.0), 2)
    buyers = round(_clamp(((moat + multi + growth) / 3.0) + buyer_bonus, 0.0, 10.0), 2)
    substitutes = round(_clamp(((theme + moat + filing['quality']) / 3.0) + substitute_bonus, 0.0, 10.0), 2)
    rivalry = round(_clamp(((moat + growth + management) / 3.0) + (0.35 if valuation >= 6.0 else -0.2), 0.0, 10.0), 2)
    overall = round((entrants + suppliers + buyers + substitutes + rivalry) / 5.0, 2)
    return {
        'new_entrants': entrants,
        'supplier_power': suppliers,
        'buyer_power': buyers,
        'substitutes': substitutes,
        'rivalry': rivalry,
        'overall': overall,
    }

def _pick_shovel_trend_fit(
    profile: dict[str, Any],
    market: MarketContext,
    notes: list[dict[str, Any]],
    company_row: Company | None,
    now: datetime,
) -> dict[str, float]:
    signal = _pick_shovel_signal_profile(profile, company_row)
    base_score = _to_float(profile.get('base_score'), 6.8)
    theme = _company_metric(company_row, 'theme_linkage', base_score)
    multi = _company_metric(company_row, 'multi_winner_exposure', base_score)
    moat = _company_metric(company_row, 'bottleneck_or_differentiation', base_score)
    growth = _company_metric(company_row, 'growth_proof', base_score)
    management = _company_metric(company_row, 'management_proof', base_score)
    filing = _filing_analysis(notes, now)
    coverage = _news_coverage_analysis(notes, now)
    market_quality = _market_quality_component(market)

    bottleneck_heat = round(_clamp((signal['mission_criticality'] * 0.65) + (signal['structural_strength'] * 0.35) + (0.35 if signal['has_curated_theme'] else 0.0), 0.0, 10.0), 2)
    theme_heat = round(
        _clamp(
            (theme * 0.35)
            + (coverage['quality'] * 0.25)
            + (filing['quality'] * 0.20)
            + ((coverage['freshness'] * 10.0) * 0.10)
            + ((filing['freshness'] * 10.0) * 0.10),
            0.0,
            10.0,
        ),
        2,
    )
    mission_criticality = round(_clamp((moat * 0.45) + (bottleneck_heat * 0.35) + (multi * 0.20), 0.0, 10.0), 2)
    capex_alignment = round(_clamp((theme * 0.35) + (multi * 0.40) + (moat * 0.25), 0.0, 10.0), 2)
    execution_readiness = round(_clamp((growth * 0.45) + (management * 0.35) + (market_quality * 0.20), 0.0, 10.0), 2)
    overall = round((theme_heat * 0.25) + (mission_criticality * 0.30) + (capex_alignment * 0.25) + (execution_readiness * 0.20), 2)
    return {
        'theme_heat': theme_heat,
        'mission_criticality': mission_criticality,
        'capex_alignment': capex_alignment,
        'execution_readiness': execution_readiness,
        'overall': overall,
    }

def _pick_shovel_force_label(name: str) -> str:
    return {
        'new_entrants': 'threat from new entrants',
        'supplier_power': 'supplier power resilience',
        'buyer_power': 'buyer power resilience',
        'substitutes': 'substitute resistance',
        'rivalry': 'competitive rivalry resilience',
    }.get(name, name.replace('_', ' '))


def _score_pick_shovel_candidate(
    agent: StrategyAgent,
    symbol: str,
    profile: dict[str, Any],
    market: MarketContext,
    notes: list[dict[str, Any]],
    company_row: Company | None,
    now: datetime,
    pressure: CompetitionPressure,
    *,
    is_held: bool,
) -> tuple[float, str, dict[str, Any]]:
    signal = _pick_shovel_signal_profile(profile, company_row)
    porter = _pick_shovel_porter_forces(profile, market, notes, company_row, now)
    trend = _pick_shovel_trend_fit(profile, market, notes, company_row, now)
    base_conviction = round(_clamp((porter['overall'] * 0.60) + (trend['overall'] * 0.40), 0.0, 10.0), 2)
    conviction = _competition_adjusted_conviction(base_conviction, pressure, is_held=is_held)

    porter_components = {key: value for key, value in porter.items() if key != 'overall'}
    trend_components = {key: value for key, value in trend.items() if key != 'overall'}
    strongest_force_name, strongest_force_value = max(porter_components.items(), key=lambda item: item[1])
    weakest_force_name, weakest_force_value = min(porter_components.items(), key=lambda item: item[1])
    strongest_trend_name, strongest_trend_value = max(trend_components.items(), key=lambda item: item[1])
    qualification_basis = signal['qualification_basis']

    rationale_parts = [
        f"{profile.get('name', symbol)} scored {conviction:.1f}/10 for {agent.name} from a Porter five forces review plus trend-fit analysis.",
        f"Strongest force was {_pick_shovel_force_label(strongest_force_name)} at {strongest_force_value:.1f}/10, while the weakest was {_pick_shovel_force_label(weakest_force_name)} at {weakest_force_value:.1f}/10.",
        f"Trend fit scored {trend['overall']:.1f}/10 and was led by {strongest_trend_name.replace('_', ' ')} at {strongest_trend_value:.1f}/10.",
        f"Specialist qualification came from {qualification_basis} with structural strength {signal['structural_strength']:.1f}/10 and mission criticality {signal['mission_criticality']:.1f}/10.",
        'That trend score is structural, not chart-based: it measures whether the theme is hot and whether the company supplies a mission-critical bottleneck inside it.',
    ]
    if abs(conviction - base_conviction) >= 0.05:
        rationale_parts.append(f'Competition pressure adjusted the live conviction from {base_conviction:.1f}/10 to {conviction:.1f}/10.')
    if market.dollar_volume > 0:
        rationale_parts.append(f"Approximate daily dollar volume is ${market.dollar_volume / 1_000_000:.1f}M.")
    if market.spread_pct is not None:
        rationale_parts.append(f'Observed spread is {market.spread_pct:.2f}%.')
    competition_summary = _competition_context_summary(pressure)
    if competition_summary:
        rationale_parts.append(competition_summary)

    analysis = {'porter': porter, 'trend': trend}
    return conviction, ' '.join(rationale_parts).strip(), analysis


def _candidate_max_notional(settings: Settings, agent: StrategyAgent, target_weight: float, market: MarketContext) -> float:
    floor_price = market.ask_price or market.last_price or 1.0
    return round(
        min(
            settings.risk_max_order_notional,
            max((agent.allocated_capital or settings.risk_bankroll_cap) * target_weight, floor_price),
        ),
        2,
    )


def _research_status_priority(status: str) -> int:
    return {'research-buy': 3, 'research-hold': 2, 'research-watch': 1, 'research-avoid': 0}.get(status, 0)


def _candidate_target_weight(
    agent: StrategyAgent,
    conviction: float,
    pressure: CompetitionPressure | None = None,
) -> float:
    if agent.slug == 'pick-shovel-growth':
        base_weight = 0.10 + ((conviction - 6.0) * 0.03)
        lower_bound = 0.10
        upper_bound = 0.30
    else:
        base_weight = 0.07 + ((conviction - 5.5) * 0.025)
        lower_bound = 0.06
        upper_bound = 0.24

    modifier = 1.0
    if pressure is not None:
        modifier += 0.15 * pressure.aggression
        modifier -= 0.08 * pressure.discipline
    return round(_clamp(base_weight * modifier, lower_bound, upper_bound), 4)


def _research_universe(
    db: Session,
    settings: Settings,
    agent: StrategyAgent,
    company_map: dict[str, Company],
    now: datetime,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    holdings = _agent_position_symbols(db, agent)
    discoveries = _current_feed_discoveries(settings, limit=max(6, settings.research_max_symbols_per_agent * 3))
    discovered_meta = {item['symbol']: item for item in discoveries}
    if agent.slug == 'pick-shovel-growth':
        approved_symbols = [
            symbol
            for symbol, company in company_map.items()
            if company.is_approved and company.theme_name.lower() in PICK_SHOVEL_THEME_NAMES
        ]
        tracked_symbols = _tracked_specialist_symbols(company_map, now)
    else:
        approved_symbols = [symbol for symbol, company in company_map.items() if company.is_approved]
        tracked_symbols = []

    ordered: list[str] = []
    for symbol in holdings:
        if symbol not in ordered:
            ordered.append(symbol)
    for item in discoveries:
        if item['symbol'] not in ordered:
            ordered.append(item['symbol'])
    for symbol in approved_symbols:
        if symbol not in ordered:
            ordered.append(symbol)
    for symbol in tracked_symbols:
        if symbol not in ordered:
            ordered.append(symbol)

    if agent.slug == 'pick-shovel-growth':
        limit = max(len(holdings) + 6, settings.research_max_symbols_per_agent * 4)
    else:
        limit = max(len(holdings) + 2, settings.research_max_symbols_per_agent * 2)
    return ordered[:limit], discovered_meta

def refresh_live_research(db: Session, settings: Settings, agents: list[StrategyAgent] | None = None, *, commit: bool = True) -> dict[str, list[Decision]]:
    if agents is None:
        agents = db.scalars(
            select(StrategyAgent).where(StrategyAgent.is_enabled.is_(True), StrategyAgent.is_alive.is_(True)).order_by(StrategyAgent.slug)
        ).all()

    company_map = _company_rows(db, approved_only=False)
    generated: dict[str, list[Decision]] = {}
    now = datetime.utcnow()
    competition_pressure = _competition_pressure_map(db, settings)
    benchmark_symbol = settings.competition_benchmark_symbol

    for agent in agents:
        pressure = competition_pressure.get(agent.slug, _neutral_competition_pressure(benchmark_symbol))
        symbols, discovered_meta = _research_universe(db, settings, agent, company_map, now)
        held_symbols = set(_agent_position_symbols(db, agent))
        evidence_rows: list[CandidateEvidence] = []

        for symbol in symbols:
            profile = _symbol_profile(symbol, company_map, discovered_meta)
            try:
                quote = get_quote_record(settings, symbol)
            except Exception:
                continue

            market = _market_context_from_quote(quote)
            should_fetch_external = settings.research_enabled and (
                symbol in held_symbols or symbol in discovered_meta or len(evidence_rows) < 3
            )
            news_notes = _news_notes_for_symbol(settings, symbol, str(profile.get('name', _ticker_from_symbol(symbol))), now) if should_fetch_external else []
            filing_notes = _filing_notes_for_symbol(settings, symbol, now) if should_fetch_external else []
            discovered_note = None
            if symbol in discovered_meta:
                discovered = discovered_meta[symbol]
                discovered_note = {
                    'source_type': 'discovery',
                    'source_title': discovered.get('source_title', f'Recent SEC discovery for {symbol}'),
                    'source_url': discovered.get('source_url'),
                    'note_text': f'{symbol} surfaced through recent SEC filing flow and was added to the liberated discovery queue.',
                    'note_score': 0.2,
                    'published_at': _safe_parse_datetime(discovered.get('published_at')),
                    'raw_payload': discovered,
                }
            notes: list[dict[str, Any]] = []
            if discovered_note is not None:
                notes.append(discovered_note)
            notes.extend(filing_notes)
            notes.extend(news_notes)

            company_row = company_map.get(symbol)
            passes_gate = _passes_market_gate(agent, symbol, profile, market, notes, company_row)
            theme_name = str(profile.get('theme_name', agent.name))

            if agent.slug == 'pick-shovel-growth':
                conviction, rationale, analysis = _score_pick_shovel_candidate(
                    agent,
                    symbol,
                    profile,
                    market,
                    notes,
                    company_row,
                    now,
                    pressure,
                    is_held=symbol in held_symbols,
                )
                if passes_gate and symbol in held_symbols and conviction >= settings.research_min_hold_score:
                    status = 'research-hold'
                elif passes_gate and conviction >= settings.research_min_buy_score:
                    status = 'research-buy'
                else:
                    status = 'research-avoid'
                target_weight = _candidate_target_weight(agent, conviction, pressure)
                idea = CandidateIdea(
                    symbol=symbol,
                    theme_name=theme_name,
                    target_weight=target_weight,
                    max_notional=_candidate_max_notional(settings, agent, target_weight, market),
                    conviction_score=conviction,
                    rationale=rationale,
                    status=status,
                )
                analysis['passes_gate'] = passes_gate
            else:
                analysis = _liberated_dossier(profile, market, notes, company_row, now)
                analysis['passes_gate'] = passes_gate
                idea = CandidateIdea(
                    symbol=symbol,
                    theme_name=theme_name,
                    target_weight=0.0,
                    max_notional=0.0,
                    conviction_score=0.0,
                    rationale='',
                    status='research-avoid',
                )

            evidence_rows.append(
                CandidateEvidence(
                    idea=idea,
                    notes=notes,
                    market=market,
                    profile=profile,
                    analysis=analysis,
                )
            )

        if agent.slug == 'liberated-us-stocks':
            evidence_rows = _finalize_liberated_candidates(evidence_rows, held_symbols, settings, agent, pressure)
        else:
            for row in evidence_rows:
                company = _ensure_specialist_company_row(db, company_map, row.idea.symbol, row.profile, row.idea.rationale)
                _sync_specialist_company_state(
                    company,
                    row.idea,
                    row.analysis,
                    now,
                    passes_gate=bool(row.analysis.get('passes_gate')),
                    is_held=row.idea.symbol in held_symbols,
                    settings=settings,
                )
            evidence_rows.sort(
                key=lambda row: (_research_status_priority(row.idea.status), row.idea.conviction_score),
                reverse=True,
            )

        selected: list[CandidateEvidence] = []
        for row in evidence_rows:
            if row.idea.status == 'research-buy':
                selected.append(row)
        for row in evidence_rows:
            if row.idea.symbol in held_symbols and row.idea.status == 'research-hold' and row not in selected:
                selected.append(row)
        decision_limit = max(settings.research_max_generated_decisions_per_agent, len(held_symbols) + 2)
        fallback_target = min(decision_limit, max(2, len(held_symbols) + 1))
        if len(selected) < fallback_target:
            for row in evidence_rows:
                if row in selected:
                    continue
                if row.idea.status == 'research-avoid':
                    row.idea = CandidateIdea(
                        symbol=row.idea.symbol,
                        theme_name=row.idea.theme_name,
                        target_weight=row.idea.target_weight,
                        max_notional=row.idea.max_notional,
                        conviction_score=row.idea.conviction_score,
                        rationale=row.idea.rationale,
                        status='research-watch',
                    )
                selected.append(row)
                if len(selected) >= fallback_target:
                    break
        selected = selected[:decision_limit]

        db.execute(delete(Decision).where(Decision.strategy_slug == agent.slug))
        db.execute(delete(ResearchNote).where(ResearchNote.agent_slug == agent.slug))
        db.flush()

        created: list[Decision] = []
        for row in selected:
            decision = Decision(
                symbol=row.idea.symbol,
                side='BUY',
                theme_name=row.idea.theme_name,
                strategy_slug=agent.slug,
                strategy_name=agent.name,
                target_weight=row.idea.target_weight,
                max_notional=row.idea.max_notional,
                conviction_score=row.idea.conviction_score,
                rationale=row.idea.rationale,
                status=row.idea.status,
            )
            db.add(decision)
            created.append(decision)
            for note in row.notes[: settings.research_news_items_per_symbol + settings.research_filings_per_symbol + 1]:
                db.add(
                    ResearchNote(
                        agent_slug=agent.slug,
                        symbol=row.idea.symbol,
                        source_type=str(note['source_type']),
                        source_title=str(note['source_title'])[:240],
                        source_url=note.get('source_url'),
                        note_text=str(note['note_text']),
                        note_score=_to_float(note.get('note_score')),
                        published_at=note.get('published_at'),
                        raw_payload=json.dumps(note.get('raw_payload') or {}, default=str),
                    )
                )
        generated[agent.slug] = created

    if commit:
        db.commit()
    return generated


def get_research_notes(db: Session, limit: int = 60) -> list[ResearchNote]:
    return db.scalars(select(ResearchNote).order_by(ResearchNote.created_at.desc()).limit(limit)).all()
