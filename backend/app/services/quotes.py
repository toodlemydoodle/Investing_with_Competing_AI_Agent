from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from app.broker.base import QuoteRecord
from app.broker.mock import MockBrokerAdapter
from app.core.config import Settings

ALPACA_DATA_BASE_URL = 'https://data.alpaca.markets'
TWELVEDATA_BASE_URL = 'https://api.twelvedata.com'


def _normalize_input_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise RuntimeError('Quote symbol cannot be blank.')
    return normalized


def _alpaca_symbol(symbol: str) -> str:
    normalized = _normalize_input_symbol(symbol)
    if normalized.startswith('US.'):
        return normalized.split('.', 1)[1]
    return normalized


def _build_quote_broker_adapter(settings: Settings):
    if settings.broker_backend.lower() == 'moomoo':
        from app.services.trading import build_broker_adapter

        return build_broker_adapter(settings)
    return MockBrokerAdapter(settings)


def _http_json(url: str, headers: dict[str, str], timeout: float, provider_name: str) -> dict[str, object]:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode('utf-8')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'{provider_name} quote request failed: HTTP {exc.code} {body}'.strip()) from exc
    except URLError as exc:
        raise RuntimeError(f'{provider_name} quote request failed: {exc.reason}') from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{provider_name} quote request returned invalid JSON.') from exc


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_quote_record(settings: Settings, symbol: str) -> QuoteRecord:
    provider = settings.quote_provider.lower()
    if provider == 'broker':
        return _build_quote_broker_adapter(settings).get_quote(symbol)
    if provider == 'mock':
        return MockBrokerAdapter(settings).get_quote(symbol)
    if provider == 'alpaca':
        return get_alpaca_quote(settings, symbol)
    if provider == 'twelvedata':
        return get_twelvedata_quote(settings, symbol)
    raise RuntimeError(f'Unsupported QUOTE_PROVIDER `{settings.quote_provider}`.')


def get_alpaca_quote(settings: Settings, symbol: str) -> QuoteRecord:
    if not settings.alpaca_data_api_key or not settings.alpaca_data_secret:
        raise RuntimeError(
            'QUOTE_PROVIDER is set to alpaca, but ALPACA_DATA_API_KEY / ALPACA_DATA_SECRET are missing.'
        )

    normalized = _normalize_input_symbol(symbol)
    ticker = _alpaca_symbol(symbol)
    query = urlencode({'feed': settings.alpaca_data_feed})
    url = f'{ALPACA_DATA_BASE_URL}/v2/stocks/{ticker}/snapshot?{query}'
    headers = {
        'APCA-API-KEY-ID': settings.alpaca_data_api_key,
        'APCA-API-SECRET-KEY': settings.alpaca_data_secret,
        'Accept': 'application/json',
    }
    payload = _http_json(url, headers, settings.broker_query_timeout_seconds, 'Alpaca')

    latest_trade = payload.get('latestTrade') or {}
    latest_quote = payload.get('latestQuote') or {}
    prev_daily_bar = payload.get('prevDailyBar') or {}
    daily_bar = payload.get('dailyBar') or {}

    last_price = _to_float(latest_trade.get('p')) or _to_float(daily_bar.get('c')) or _to_float(prev_daily_bar.get('c'))
    bid_price = _to_float(latest_quote.get('bp'), last_price)
    ask_price = _to_float(latest_quote.get('ap'), last_price)
    prev_close_price = _to_float(prev_daily_bar.get('c'))
    update_time = latest_trade.get('t') or latest_quote.get('t') or daily_bar.get('t')

    if last_price <= 0:
        raise RuntimeError(f'Alpaca returned no usable price for {normalized}.')

    return QuoteRecord(
        symbol=normalized,
        name=ticker,
        last_price=last_price,
        bid_price=bid_price or last_price,
        ask_price=ask_price or last_price,
        prev_close_price=prev_close_price,
        update_time=str(update_time) if update_time else None,
        raw_payload=payload,
    )


def get_twelvedata_quote(settings: Settings, symbol: str) -> QuoteRecord:
    if not settings.twelvedata_api_key:
        raise RuntimeError('QUOTE_PROVIDER is set to twelvedata, but TWELVEDATA_API_KEY is missing.')

    normalized = _normalize_input_symbol(symbol)
    ticker = _alpaca_symbol(symbol)
    params = urlencode({'symbol': ticker, 'apikey': settings.twelvedata_api_key})
    url = f'{TWELVEDATA_BASE_URL}/quote?{params}'
    payload = _http_json(url, {'Accept': 'application/json'}, settings.broker_query_timeout_seconds, 'Twelve Data')

    if payload.get('status') == 'error':
        code = payload.get('code')
        message = payload.get('message', 'Unknown Twelve Data error')
        raise RuntimeError(f'Twelve Data quote request failed: HTTP {code} {message}')

    last_price = _to_float(payload.get('close')) or _to_float(payload.get('price'))
    prev_close = _to_float(payload.get('previous_close'))
    open_price = _to_float(payload.get('open'))
    if last_price <= 0:
        raise RuntimeError(f'Twelve Data returned no usable price for {normalized}.')

    inferred_bid = last_price
    inferred_ask = last_price
    if open_price > 0 and open_price != last_price:
        midpoint = (open_price + last_price) / 2.0
        inferred_bid = min(midpoint, last_price)
        inferred_ask = max(midpoint, last_price)

    return QuoteRecord(
        symbol=normalized,
        name=str(payload.get('name') or ticker),
        last_price=last_price,
        bid_price=inferred_bid,
        ask_price=inferred_ask,
        prev_close_price=prev_close,
        update_time=str(payload.get('timestamp')) if payload.get('timestamp') else None,
        raw_payload=payload,
    )
