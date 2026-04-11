from __future__ import annotations

from datetime import datetime
from threading import Lock

_STATE_LOCK = Lock()
_STATE: dict[str, object] = {
    'revision': 0,
    'updated_at': datetime.utcnow().isoformat(),
    'reason': 'startup',
}


def mark_dashboard_state_updated(reason: str = 'update') -> dict[str, object]:
    normalized_reason = (reason or 'update').strip() or 'update'
    with _STATE_LOCK:
        _STATE['revision'] = int(_STATE['revision']) + 1
        _STATE['updated_at'] = datetime.utcnow().isoformat()
        _STATE['reason'] = normalized_reason
        return dict(_STATE)


def get_dashboard_stream_state() -> dict[str, object]:
    with _STATE_LOCK:
        return dict(_STATE)
