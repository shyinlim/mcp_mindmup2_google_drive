"""Module-level cache for Google Drive file content.

Cache key is a 3-tuple: (client_id, credential_hash, file_id).
This isolates cache entries per AI client and per service account,
so different users don't share each other's cached content.
"""
import threading
import time
from typing import Any, Dict, Optional, Tuple

from src.utility.logger import get_logger

logger = get_logger(__name__)

CacheKey = Tuple[str, str, str]  # (client_id, credential_hash, file_id)
CacheValue = Tuple[Dict[str, Any], float]  # (file_data, stored_at_epoch)

_CACHE: Dict[CacheKey, CacheValue] = {}
_CACHE_TTL_SECONDS = 300
_MAX_CACHE_SIZE = 100
_LOCK = threading.Lock()


def get(key: CacheKey) -> Optional[Dict[str, Any]]:
    """Return cached value if present and not expired, else None."""
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None

        data, stored_at = entry
        if time.time() - stored_at >= _CACHE_TTL_SECONDS:
            del _CACHE[key]
            return None

        logger.info(f'Cache HIT: client={key[0]} file={key[2]}')
        return data


def put(key: CacheKey, value: Dict[str, Any]) -> None:
    """Store value. Evict expired + oldest entries if cache exceeds max size."""
    with _LOCK:
        _CACHE[key] = (value, time.time())
        logger.info(f'Cache PUT: client={key[0]} file={key[2]}')
        _evict_if_needed()


def clear() -> None:
    """Clear all cache entries. Used by tests."""
    with _LOCK:
        _CACHE.clear()


def size() -> int:
    with _LOCK:
        return len(_CACHE)


def _evict_if_needed() -> None:
    """Remove expired entries; if still over max, remove oldest by timestamp."""
    now = time.time()
    expired_keys = [
        k for k, (_, stored_at) in _CACHE.items()
        if now - stored_at >= _CACHE_TTL_SECONDS
    ]
    for k in expired_keys:
        del _CACHE[k]

    if len(_CACHE) > _MAX_CACHE_SIZE:
        sorted_items = sorted(_CACHE.items(), key=lambda x: x[1][1])
        to_remove = len(_CACHE) - _MAX_CACHE_SIZE
        for i in range(to_remove):
            del _CACHE[sorted_items[i][0]]

    if expired_keys:
        logger.info(
            f'Cache cleanup: removed {len(expired_keys)} expired, '
            f'{len(_CACHE)} remaining'
        )
