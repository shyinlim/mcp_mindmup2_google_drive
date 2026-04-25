"""Tests for gdrive_cache module: 3-tier key isolation, TTL, and eviction."""
import time
from unittest.mock import patch

import pytest

from src.core import gdrive_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Each test starts and ends with an empty cache."""
    gdrive_cache.clear()
    yield
    gdrive_cache.clear()


class TestCacheHitMiss:

    def test_put_then_get_returns_data(self):
        key = ("shyin-cc", "hash_a", "file_1")
        gdrive_cache.put(key, {"content": "abc"})
        assert gdrive_cache.get(key) == {"content": "abc"}

    def test_get_missing_returns_none(self):
        assert gdrive_cache.get(("x", "y", "z")) is None


class TestCacheIsolation:

    def test_different_client_id_isolated(self):
        """Same credential + file, different client_id -> separate cache entries."""
        gdrive_cache.put(("shyin", "hash_a", "f1"), {"v": "shyin_data"})
        gdrive_cache.put(("colleague", "hash_a", "f1"), {"v": "colleague_data"})

        assert gdrive_cache.get(("shyin", "hash_a", "f1"))["v"] == "shyin_data"
        assert gdrive_cache.get(("colleague", "hash_a", "f1"))["v"] == "colleague_data"

    def test_different_credential_isolated(self):
        """Same client_id + file, different credential_hash -> separate entries.

        Handles the copy-paste case where users share mcp.json but each has
        their own service account.
        """
        gdrive_cache.put(("shyin", "hash_a", "f1"), {"v": "acc_a_data"})
        gdrive_cache.put(("shyin", "hash_b", "f1"), {"v": "acc_b_data"})

        assert gdrive_cache.get(("shyin", "hash_a", "f1"))["v"] == "acc_a_data"
        assert gdrive_cache.get(("shyin", "hash_b", "f1"))["v"] == "acc_b_data"

    def test_different_file_id_isolated(self):
        gdrive_cache.put(("shyin", "hash_a", "f1"), {"v": 1})
        gdrive_cache.put(("shyin", "hash_a", "f2"), {"v": 2})

        assert gdrive_cache.get(("shyin", "hash_a", "f1"))["v"] == 1
        assert gdrive_cache.get(("shyin", "hash_a", "f2"))["v"] == 2


class TestCacheExpiry:

    def test_ttl_expires(self):
        key = ("shyin", "hash_a", "f1")
        gdrive_cache.put(key, {"v": 1})

        future = time.time() + gdrive_cache._CACHE_TTL_SECONDS + 10
        with patch("src.core.gdrive_cache.time.time", return_value=future):
            assert gdrive_cache.get(key) is None

    def test_within_ttl_returns_data(self):
        key = ("shyin", "hash_a", "f1")
        gdrive_cache.put(key, {"v": 1})

        future = time.time() + gdrive_cache._CACHE_TTL_SECONDS - 10
        with patch("src.core.gdrive_cache.time.time", return_value=future):
            assert gdrive_cache.get(key) == {"v": 1}


class TestCacheEviction:

    def test_evicts_when_over_max_size(self):
        """When cache exceeds _MAX_CACHE_SIZE, oldest entries are evicted."""
        with patch("src.core.gdrive_cache._MAX_CACHE_SIZE", 3):
            for i in range(5):
                gdrive_cache.put(("c", "h", f"f{i}"), {"v": i})

            assert gdrive_cache.size() <= 3
