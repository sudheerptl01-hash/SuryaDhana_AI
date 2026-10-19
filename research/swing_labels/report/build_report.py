#!/usr/bin/env python3
"""Inject the collected report data into the HTML template and write the publishable page."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(os.path.dirname(HERE), "lab")
tpl = open(os.path.join(HERE, "swing_label_study.template.html"), encoding="utf-8").read()
data = json.load(open(os.path.join(LAB, "results", "_lead", "report_data.json")))
blob = json.dumps(data, separators=(",", ":"), default=float).replace("</", "<\\/")
out = tpl.replace("__REPORT_DATA__", blob)
dst = os.path.join(HERE, "swing_label_study.html")
open(dst, "w", encoding="utf-8").write(out)
print("wrote", dst, len(out), "bytes")
