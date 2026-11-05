import httpx

from routers._upstream import upstream_detail


def test_json_detail_is_unwrapped():
    r = httpx.Response(404, json={"detail": "TCS1 is not in the NSE bhavcopy"})
    assert upstream_detail(r) == "TCS1 is not in the NSE bhavcopy"


def test_validation_errors_and_plain_text_pass_through():
    v = httpx.Response(422, json={"detail": [{"msg": "String should match pattern"}]})
    assert upstream_detail(v) == [{"msg": "String should match pattern"}]
    t = httpx.Response(502, text="Bad gateway " * 50)
    assert upstream_detail(t, 20) == ("Bad gateway " * 50)[:20]
