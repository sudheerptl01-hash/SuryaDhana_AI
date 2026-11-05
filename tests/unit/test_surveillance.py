"""NSE surveillance flags (services/data-service/surveillance.py) on rows shaped like the real 13 Oct 2026 files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import surveillance as sv  # noqa: E402

REG1 = (b"ScripCode,Symbol,Nse Exclusive,Status,Series,GSM,Long_Term_Additional_Surveillance_Measure (Long Term ASM),"
        b"Short_Term_Additional_Surveillance_Measure (Short Term ASM),ESM,Pledge,Under BZ/SZ Series\n"
        b"1,CUPID,N,A,EQ,100,1,100,100,100,100\n"
        b"2,PCJEWELLER,N,A,EQ,100,100,1,100,100,100\n"
        b"3,TCS,N,A,EQ,100,100,100,100,100,100\n"
        b"4,JUNKCO,N,A,BZ,2,100,100,1,1,0\n")
BANDS = (b"Symbol,Series,Security Name,Band,Remarks\n"
         b"CUPID,EQ,CUPID LIMITED,20,-\nJUNKCO,BZ,JUNK CO,2,GSM STAGE - 2\nTCS,EQ,TCS,No Band,-\nSMALL,EQ,SMALL LTD,5,-\n")
BAN = b"Securities in Ban For Trade Date 14-OCT-2026:\n1,AMBUJACEM\n2,KAYNES\n"


def test_parsers_read_the_real_layouts():
    s = sv.parse_reg1(REG1)
    assert s["CUPID"]["measures"] == {"ASM LT": 1} and s["PCJEWELLER"]["measures"] == {"ASM ST": 1}
    assert "TCS" not in s                                          # nothing flagged: not listed
    assert s["JUNKCO"]["measures"] == {"GSM": 2, "ESM": 1} and set(s["JUNKCO"]["flags"]) == {"pledge", "trade-to-trade"}
    b = sv.parse_bands(BANDS)
    assert b["CUPID"]["band"] == 20 and b["TCS"]["band"] is None and b["JUNKCO"]["remarks"] == "GSM STAGE - 2"
    assert sv.parse_ban(BAN) == ["AMBUJACEM", "KAYNES"]


def test_flags_for_orders_and_grades_the_chips():
    data = {"surveillance": sv.parse_reg1(REG1), "bands": sv.parse_bands(BANDS), "ban": sv.parse_ban(BAN)}
    assert [c["code"] for c in sv.flags_for("CUPID", data)["chips"]] == ["ASM LT 1"]
    assert sv.flags_for("TCS", data)["chips"] == []                 # 20% band or no band: nothing to say
    small = sv.flags_for("SMALL", data)["chips"]
    assert small == [{"code": "BAND 5%", "level": "medium", "why": small[0]["why"]}]
    junk = [c["code"] for c in sv.flags_for("JUNKCO", data)["chips"]]
    assert junk[:3] == ["GSM 2", "ESM 1", "BAND 2%"] and "T2T" in junk and "PLEDGE" in junk
    assert sv.flags_for("KAYNES", data)["chips"][0]["code"] == "F&O BAN"
