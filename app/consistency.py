"""Cross-report consistency check (deterministic).

The same institutional figure (total students, full-time teachers, mentors, outreach programmes...) is reported in
several places: AQAR metrics, SSR, NBA SAR, NIRF, AISHE. NAAC's DVV and NBA visitors compare them; a mismatch
triggers clarifications. A chatbot reading one PDF at a time cannot see this. ProofDesk lines the figures up.

Input rows: {"figure": "total_students", "year": "2023-24", "source": "AQAR 2.2.1", "value": 4639}
Optional derived rules check ratios that must agree with their parts (e.g. mentor ratio = students / mentors).
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict

# relative tolerance per figure (counts must match exactly unless a tolerance is given)
TOLERANCE = {"total_students": 0.0, "full_time_teachers": 0.0, "mentors": 0.0, "outreach_programmes": 0.0}

# figures that are derived from others: name -> (numerator, denominator)
DERIVED = {"student_teacher_ratio": ("total_students", "full_time_teachers"),
           "student_mentor_ratio": ("total_students", "mentors")}


def parse_csv(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({"figure": r["figure"].strip(), "year": r["year"].strip(), "source": r["source"].strip(),
                         "value": float(r["value"])})
        except (KeyError, ValueError):
            continue
    return rows


def check(rows: list[dict]) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["figure"], r["year"])].append(r)
    findings = []
    for (fig, year), rs in sorted(groups.items()):
        if len(rs) < 2:
            continue  # a figure reported once cannot be inconsistent
        vals = sorted({r["value"] for r in rs})
        tol = TOLERANCE.get(fig, 0.01)
        spread = (max(vals) - min(vals)) / max(abs(max(vals)), 1e-9)
        status = "consistent" if spread <= tol else "mismatch"
        findings.append({"figure": fig, "year": year, "status": status,
                         "values": [{"source": r["source"], "value": r["value"]} for r in rs],
                         "message": (f"{fig} for {year} is reported consistently ({vals[0]:g}) across {len(rs)} reports."
                                     if status == "consistent" else
                                     f"{fig} for {year} differs across reports: " +
                                     ", ".join(f"{r['source']} = {r['value']:g}" for r in rs) +
                                     ". Reconcile before submission or attach an explanation.")})
    # derived ratios must match their parts
    base = {(r["figure"], r["year"], r["source"]): r["value"] for r in rows}
    for name, (num, den) in DERIVED.items():
        for (fig, year, src), val in base.items():
            if fig != name:
                continue
            nums = [v for (f, y, _), v in base.items() if f == num and y == year]
            dens = [v for (f, y, _), v in base.items() if f == den and y == year]
            if nums and dens and min(dens) > 0:
                expected = nums[0] / dens[0]
                ok = abs(val - expected) / expected <= 0.05
                findings.append({"figure": name, "year": year, "status": "consistent" if ok else "mismatch",
                                 "values": [{"source": src, "value": val}],
                                 "message": (f"{name} in {src} ({val:g}) matches {num}/{den} = {expected:.1f}."
                                             if ok else
                                             f"{name} in {src} is {val:g}, but {num}/{den} = "
                                             f"{nums[0]:g}/{dens[0]:g} = {expected:.1f}. Recheck the ratio.")})
    mism = sum(f["status"] == "mismatch" for f in findings)
    return {"checked": len(findings), "mismatches": mism, "findings": findings}


DEMO_CSV = """figure,year,source,value
total_students,2023-24,AQAR 2.2.1,4120
total_students,2023-24,NIRF data capture,4120
total_students,2023-24,NBA SAR 5.1 (sum of programmes),3985
full_time_teachers,2023-24,AQAR 2.4.1,262
full_time_teachers,2023-24,NBA SAR faculty list,262
mentors,2023-24,AQAR 2.3.3,205
student_mentor_ratio,2023-24,AQAR 2.3.3,18
student_teacher_ratio,2023-24,AQAR 2.2.1,15.7
outreach_programmes,2023-24,AQAR 3.3.3,31
outreach_programmes,2023-24,Annual report,27
"""

if __name__ == "__main__":
    import json
    print(json.dumps(check(parse_csv(DEMO_CSV)), indent=1))
