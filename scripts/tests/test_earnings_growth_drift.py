from earnings_growth_drift_study import fundamental_bucket


def test_buckets_match_the_plan():
    assert fundamental_bucket(45.0, 12.0, None) == "strong growth"
    assert fundamental_bucket(45.0, 5.0, None) == "growth"          # profit up but revenue < +10%
    assert fundamental_bucket(0.0, -3.0, None) == "growth"
    assert fundamental_bucket(-10.0, 8.0, None) == "decline"
    assert fundamental_bucket(-30.0, 8.0, None) == "collapse"
    assert fundamental_bucket(None, 8.0, "to loss") == "collapse"
    assert fundamental_bucket(None, 8.0, "to profit") is None
    assert fundamental_bucket(None, None, None) is None


def test_within_sample_removes_what_the_week_shares():
    import pandas as pd
    from earnings_growth_drift_study import within_sample
    # two weeks; everyone gains +10 / +4 that week (shared bias), strong growth beats its week by +2 each time
    d = pd.DataFrame({
        "entry_date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-12", "2026-01-13", "2026-01-14"]),
        "fbucket": ["strong growth", "collapse", "growth", "strong growth", "collapse", "growth"],
        "ex60": [12.0, 9.0, 9.0, 6.0, 3.0, 3.0]})
    w = within_sample(d, 60)
    assert w["weeks"] == 2 and w["within"] == 2.0
