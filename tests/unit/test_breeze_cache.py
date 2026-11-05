"""shared/breeze_cache.py: Breeze sessions read ICICI's security master from a local cache, never a hanging download."""
import importlib.util
import io
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared import breeze_cache as bcache  # noqa: E402

def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("NSEScripMaster.txt", '"Token","ShortName","Series","CompanyName","x"\n"11536","TCS","EQ","TATA CONSULTANCY","x"\n')
    return buf.getvalue()


# breeze_connect downloads ICICI's security master *at import*; import it the guarded way, from an in-memory archive
if importlib.util.find_spec("breeze_connect") is None:      # (find_spec: importing it would download)
    pytest.skip("breeze_connect not installed", allow_module_level=True)
_real_master_bytes = bcache.master_bytes
bcache.master_bytes = lambda *a, **k: _zip()
bc = bcache._import_breeze()
bcache.master_bytes = _real_master_bytes


def test_cached_archive_is_used_and_nothing_is_downloaded(tmp_path, monkeypatch):
    cache = tmp_path / "SecurityMaster.zip"
    cache.write_bytes(_zip())
    monkeypatch.setattr(bcache, "CACHE", cache)
    monkeypatch.setattr(bcache, "master_bytes", lambda: cache.read_bytes())
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(bc, "urlopen", boom)              # the real download would hang
    bcache._state["installed"] = False
    monkeypatch.setattr(bc.BreezeConnect, "get_stock_script_list", bc.BreezeConnect.get_stock_script_list)
    bcache.install()
    b = bc.BreezeConnect(api_key="x")
    b.get_stock_script_list()
    assert b.stock_script_dict_list[1].get("TCS") == "11536"
    assert bc.urlopen is boom                              # the module is restored afterwards


def test_master_bytes_prefers_fresh_cache_then_stale_and_backs_off(tmp_path, monkeypatch):
    cache = tmp_path / "m.zip"
    calls = []
    monkeypatch.setattr(bcache, "_download", lambda dest, timeout_s=0: calls.append(1) or False)
    monkeypatch.setattr(bcache, "master_bytes", _real_master_bytes)
    bcache._state["failed_at"] = 0.0
    assert _real_master_bytes(cache) == b"" and len(calls) == 1          # nothing cached, download failed
    assert _real_master_bytes(cache) == b"" and len(calls) == 1          # backs off: no retry for 30 minutes
    cache.write_bytes(b"old")
    assert _real_master_bytes(cache, now=time.time()) == b"old"          # fresh copy: no download at all
    assert len(calls) == 1
