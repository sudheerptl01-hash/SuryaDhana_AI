"""The gate registry: PLAN 1.7's G1–G12, each mapped to the tests that implement it — the builders' tests (cited, not
copied) and this package's additions. The registry fails when a cited test is renamed or deleted, when a gate has no test
in some suite that CI runs, or when a UI check named here disappears from its ``*.check.ts``. G13 is the owner's (live,
first week) and has no code. Static: every test is found by parsing its file (nothing is imported or run here; each suite
runs its own tests)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = "tests/terminal_v2_gates"
UIAPI = "services/ui-api/tests"

#: gate → [(file, test function | check-name fragment), ...]
GATES: dict[str, list[tuple[str, str]]] = {
    "G1": [("tests/unit/test_iv_eod.py", "test_parity_forward_is_recovered_and_recorded_on_every_row"),
           ("tests/unit/test_iv_eod.py", "test_untraded_strikes_carry_no_iv_but_traded_ones_do"),
           ("tests/unit/test_iv_eod.py", "test_expiry_day_and_short_dte_rows_stay_in_the_surface_but_out_of_near"),
           ("tests/unit/test_iv_eod.py", "test_iv30_cm_needs_a_bracket"),
           ("tests/unit/test_iv_eod.py", "test_rank_21_and_percentile_60_on_a_synthetic_series"),
           ("tests/unit/test_iv_eod.py", "test_legacy_parser_fo01apr2022_monthly_atm_17_13_with_96_iv_strikes"),
           ("tests/unit/test_iv_eod.py", "test_legacy_parser_rejects_a_udiff_body"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_parity_forward_23931_23_on_the_real_4_nov_chain"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_model_version_and_r_on_every_row_of_the_real_chain"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_untraded_strikes_have_no_iv_on_the_real_chain"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_near_skips_the_short_dated_and_iv30_is_bracketed"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_negative_control_an_expiry_day_chain_has_no_near"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g1_legacy_parser_on_the_committed_fo01apr2022_trim")],
    "G2": [("tests/test_iv_replay_g2.py", "test_replay_matches_the_prototype_within_0_05_vol_pt"),
           ("tests/test_iv_replay_g2.py", "test_replay_correlates_with_the_product_history"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g2_the_4_nov_session_matches_r_iv_within_0_05_vol_pt"),
           (f"{G}/test_g01_g02_iv_fixtures.py", "test_g2_negative_controls_a_0_06_vol_pt_drift_or_a_missing_value_fails")],
    "G3": [("tests/test_index_drivers.py", "test_pit_identity_split_special_session_and_fit"),
           ("tests/test_index_drivers.py", "test_calibration_equals_the_official_top10_to_a_hundredth"),
           ("tests/test_index_drivers.py", "test_hysteresis_turns_many_raw_changes_into_few"),
           (f"{G}/test_g03_drivers_fit_gate.py", "test_threshold_is_25_points_and_inclusive"),
           (f"{G}/test_g03_drivers_fit_gate.py", "test_only_the_last_60_sessions_count_and_nothing_after_as_of")],
    "G4": [("tests/test_data_health.py", "test_catalog_covers_every_new_table_ingest_and_job"),
           ("tests/test_data_health.py", "test_expected_by_is_trading_day_aware"),
           ("tests/test_data_health.py", "test_state_rule_fresh_amber_red_gap_with_negative_controls"),
           ("tests/test_data_health.py", "test_ingest_log_sha256_dedupe_and_if_modified_since_revision"),
           ("tests/test_data_health.py", "test_gap_rows_are_written_once_and_render_as_gap"),
           (f"{G}/test_g04_catalog_coverage.py", "test_every_scheduled_job_has_a_row_or_a_stated_reason"),
           (f"{G}/test_g04_catalog_coverage.py", "test_every_page_has_a_data_source_row"),
           (f"{G}/test_g04_catalog_coverage.py", "test_negative_controls_a_new_job_or_page_without_a_row_fails")],
    "G5": [("tests/test_hosts_allowlist_terminal.py", "test_every_url_host_literal_is_allowlisted_and_never_yahoo"),
           ("tests/test_hosts_allowlist_terminal.py", "test_forbidden_publishers_and_yahoo_callers_are_absent"),
           ("tests/test_hosts_allowlist_terminal.py", "test_no_bare_http_client_in_the_new_packages"),
           ("tests/arch/test_hosts_allowlist_shared.py", "test_no_yahoo_caller_under_shared"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_routers_name_no_publisher_host"),
           ("tests/integration/test_gold_gates.py", "test_every_fetched_host_is_allowlisted"),     # T8 incl. the v2 routers
           (f"{G}/test_g05_market_monitor_no_yahoo.py", "test_no_yahoo_on_the_market_monitor_request_path"),
           (f"{G}/test_g05_market_monitor_no_yahoo.py", "test_negative_control_the_scanner_sees_a_yahoo_helper_two_calls_deep")],
    "G6": [(f"{UIAPI}/test_terminal_v2_api.py", "test_iv_history_payload"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_iv_surface_with_ghost"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_iv_cone"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_vol_screen_sorts_and_filters"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_index_drivers_route"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_index_drivers_timeline_and_monthly"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_data_health_route"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_margin_breeze_first_through_the_ledger"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_margin_budget_exhausted_falls_to_the_span_file"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_margin_heuristic_last_with_the_measured_error"),
           (f"{UIAPI}/test_terminal_v2_api.py", "test_request_path_never_leaves_the_loopback"),
           (f"{UIAPI}/test_breeze_budget.py", "test_hard_stop_at_the_day_cap_refuses_before_the_body_runs")],
    "G7": [("tests/arch/test_duckdb_rw.py", "test_ten_concurrent_history_reads_take_at_most_twice_one"),
           ("tests/arch/test_duckdb_rw.py", "test_health_style_probe_is_fast_during_the_burst"),
           (f"{G}/test_g07_health_during_burst.py", "test_real_health_stays_under_10ms_during_a_read_burst"),
           (f"{G}/test_g07_health_during_burst.py", "test_negative_control_a_health_behind_the_exclusive_lock_is_slow")],
    "G8": [("tests/arch/test_metrics_middleware.py", "test_metrics_endpoint_has_the_named_series"),
           ("tests/arch/test_metrics_middleware.py", "test_request_id_is_echoed_and_bound_as_correlation_id"),
           ("tests/arch/test_metrics_middleware.py", "test_access_log_excludes_health_root_live_but_logs_failures"),
           (f"{G}/test_g08_service_metrics.py", "test_g8_metrics_request_id_and_access_log_on_the_real_app"),
           (f"{G}/test_g08_service_metrics.py", "test_g8_negative_control_a_bare_app_breaks_every_rule")],
    "G9": [("ui/components/vol/__tests__/terminal_v2.check.ts", "R2 OMON history prints BOTH chips"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "B1 context is the neutral tone"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "D1 the regime strip"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "S4 G9: every Panel header on every page carries a SourceChip"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "P3 the live today panel"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "P3 the horizon table on MEMB only"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "P1 DERV VIX level once per page"),
           ("ui/components/vol/__tests__/terminal_v2.check.ts", "T1 an unknown tab is named"),
           ("ui/components/__tests__/terminal_v2.check.ts", "G9.1 IV percentile and IV rank are both defined"),
           ("ui/components/__tests__/terminal_v2.check.ts", "G9.2 context panels"),
           ("ui/components/__tests__/terminal_v2.check.ts", "G9.4 every <Panel"),
           ("ui/components/__tests__/terminal_v2.check.ts", "G9.5 the VIX level once per page"),
           ("ui/components/__tests__/terminal_v2.check.ts", "G9.6 unknown ?tab=")],
    "G10": [("scripts/tests/test_tv2_g10_ui_harness.py", "test_ui_perf_budgets_are_the_plan_numbers"),
            ("scripts/tests/test_tv2_g10_ui_harness.py", "test_budget_breaches_flag_omon_and_first_load_with_negative_controls"),
            ("scripts/tests/test_tv2_g10_ui_harness.py", "test_ui_audit_v2_set_and_repetition_rules")],
    "G11": [("scripts/tests/test_terminal_v2_controller.py", "test_missed_jobs_lists_the_terminal_jobs_whose_slot_passed"),
            ("scripts/tests/test_terminal_v2_controller.py", "test_the_2245_pass_fetches_the_late_files_with_revalidation"),
            ("scripts/tests/test_terminal_v2_controller.py",
             "test_the_0835_sweep_runs_the_plan_sends_one_digest_and_is_quiet_when_nothing_is_missing"),
            ("scripts/tests/test_terminal_v2_controller.py",
             "test_iv_intraday_skips_without_a_request_outside_the_window_on_a_holiday_and_without_a_session"),
            ("scripts/tests/test_terminal_v2_controller.py",
             "test_no_terminal_job_fires_inside_a_freeze_window_except_the_light_stored_data_ones"),
            ("scripts/tests/test_tv2_g11_jobs_gate.py", "test_every_terminal_job_is_replayed_or_says_why_not"),
            ("scripts/tests/test_tv2_g11_jobs_gate.py", "test_no_heavy_job_fires_inside_a_freeze_window")],
    "G12": [("scripts/tests/test_tv2_g12_quality_gates.py", "test_ci_runs_ruff_mypy_pin_drift_and_pip_audit"),
            ("scripts/tests/test_tv2_g12_quality_gates.py", "test_ruff_passes_on_the_tree_with_the_repo_config"),
            ("scripts/tests/test_tv2_g12_quality_gates.py", "test_negative_control_ruff_fails_a_new_dtz_violation"),
            ("scripts/tests/test_tv2_g12_quality_gates.py", "test_mypy_passes_per_package"),
            ("scripts/tests/test_pin_drift.py", "test_every_requirement_is_pinned_exactly"),
            ("scripts/tests/test_pin_drift.py", "test_installed_versions_match_the_ci_pins"),
            ("tests/test_gold_study_reproduce.py", "test_g_study_smoke_200_weeks")],
}


def _defined_tests(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test_")}


def missing_entries(gates: dict[str, list[tuple[str, str]]]) -> list[str]:
    out: list[str] = []
    cache: dict[str, set[str] | str] = {}
    for gate, entries in gates.items():
        if not entries:
            out.append(f"{gate}: no test")
        for rel, name in entries:
            p = ROOT / rel
            if not p.exists():
                out.append(f"{gate}: {rel} does not exist")
                continue
            if rel.endswith(".check.ts"):
                text = cache.setdefault(rel, p.read_text(encoding="utf-8"))
                if not (isinstance(text, str) and name in text):
                    out.append(f"{gate}: {rel} has no check named '{name}'")
            else:
                defined = cache.setdefault(rel, _defined_tests(p))
                if not (isinstance(defined, set) and name in defined):
                    out.append(f"{gate}: {rel}::{name} not found")
    return out


def test_every_gate_g1_to_g12_is_mapped_to_existing_tests():
    assert sorted(GATES, key=lambda g: int(g[1:])) == [f"G{i}" for i in range(1, 13)]
    problems = missing_entries(GATES)
    assert not problems, problems


def test_every_gate_has_a_test_in_a_suite_ci_runs():
    suites = ("tests/", "scripts/tests/", f"{UIAPI}/", "ui/")
    for gate, entries in GATES.items():
        assert all(rel.startswith(suites) for rel, _ in entries), gate


def test_negative_control_a_renamed_test_or_check_is_reported():
    bad = {"G1": [("tests/unit/test_iv_eod.py", "test_this_name_does_not_exist")],
           "G9": [("ui/components/vol/__tests__/terminal_v2.check.ts", "no such check name xyz")],
           "G2": [("tests/no_such_file.py", "test_x")], "G3": []}
    found = missing_entries(bad)
    assert len(found) == 4 and any("not found" in f for f in found) and any("no check named" in f for f in found)
    assert any("does not exist" in f for f in found) and any("no test" in f for f in found)
