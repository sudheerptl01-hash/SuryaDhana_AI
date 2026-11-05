"""SuryaDhana desktop QA harness (reports/desktop_app/PLAN.md, workstream T).

Modules
-------
- ``pages``          parse the 42-page source of truth (``ui/app/page.tsx``) and the Rust Go-menu copy
- ``netpolicy``      request/console failure classification, the narrow stream-abort allowlist, URL keys
- ``probe``          one-tab browser probe (timing, events, structural fingerprint), shared by
                     ``scripts/ui_audit.py`` and ``parity.py``
- ``parity.py``      CLI: per-tab A-vs-B parity report (same engine, Chromium and/or WebKit)
- ``streams.py``     CLI: SSE / WebSocket / pipeline-stream / POST-stream routability checks through a base
- ``run_selftest.py`` CLI: drive the built SuryaDhana.app (``--self-test``, codesign, size, plist, single
                     instance, RSS/CPU of the app and its WebKit XPC children)
- ``scratch_server.py`` CLI: serve a static export and forward /api (HTTP, SSE, WS) to a backend
- ``scratch_export.py`` CLI: build a scratch static export (``scripts/build_ui.sh --out`` when present,
                     else the feasibility recipe in a scratch copy of ``ui/``)

How to run each check, and what PASS means: ``reports/desktop_app/qa_harness.md``.
Everything here is read-only against the live stack (GET page loads, GET streams, a WS ping).
"""
