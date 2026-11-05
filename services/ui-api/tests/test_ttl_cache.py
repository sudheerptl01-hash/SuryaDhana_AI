"""cache.TTLCache (F2.1/S1): expiry, LRU bound, stats, thread safety."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cache import REGISTRY, TTLCache, cache_stats  # noqa: E402


def test_expiry_on_read_and_write_semantics():
    t = [0.0]
    c = TTLCache("t_exp", max_items=10, default_ttl=5, clock=lambda: t[0])
    c.set("a", 1)
    assert c.get("a") == 1
    t[0] = 4.9
    assert c.get("a") == 1
    t[0] = 5.1
    assert c.get("a") is None                      # expired on read, evicted
    c.set("b", 2, ttl=100)                         # per-call ttl override
    t[0] = 50
    assert c.get("b") == 2
    s = c.stats()
    assert s["expired"] == 1 and s["size"] == 1


def test_lru_eviction_at_bound_keeps_most_recent():
    c = TTLCache("t_lru", max_items=3, default_ttl=100, clock=lambda: 0)
    for k in "abc":
        c.set(k, k)
    c.get("a")                                      # a becomes MRU
    c.set("d", "d")                                 # evicts LRU = b
    assert c.get("b") is None
    assert c.get("a") == "a" and c.get("d") == "d"
    assert len(c) == 3 and c.stats()["evictions"] == 1


def test_thread_hammer_never_exceeds_bound():
    c = TTLCache("t_thr", max_items=64, default_ttl=100)

    def work(seed: int):
        for i in range(10_000):
            k = f"k{(seed * 31 + i) % 500}"
            if i % 3:
                c.set(k, i)
            else:
                c.get(k)

    threads = [threading.Thread(target=work, args=(s,)) for s in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(c) <= 64


def test_registry_and_stats_snapshot():
    TTLCache("t_reg", max_items=2, default_ttl=1)
    names = [s["name"] for s in cache_stats()]
    assert "t_reg" in names and REGISTRY["t_reg"].max_items == 2
