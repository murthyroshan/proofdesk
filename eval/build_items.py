"""Build the evaluation item list and a fixed dev/test split (seed 42, stratified by source).

Item = (file, metric to test against, expected label). Sources:
  real_513   : PII-screened public pages from one college (not included in this repo), tested against NAAC 5.1.3 (their true metric) -> label by hand
  real_513_x : the same pages tested against NAAC 3.3.3 outreach (cross-metric hard negative) -> label by hand
  drive_x    : PII-screened public college evidence for OTHER metrics (4.x, 6.x...), tested against 3.3.3 -> 'weak' (wrong metric)
  synthetic  : our own stamped synthetic documents with known labels (genuine / wrong period / internal event / injection...)
Labels for real_513 / real_513_x come from labels_dev.csv (founder/assistant) and labels_test_*.csv (teammates).
"""
import csv
import json
import random
from pathlib import Path

E = Path(__file__).parent
random.seed(42)
items = []
for p in sorted((E / "real/clean_513").glob("*.png")):
    items.append({"file": f"real/clean_513/{p.name}", "metric": "NAAC AQAR 5.1.3", "source": "real_513", "label": None})
    items.append({"file": f"real/clean_513/{p.name}", "metric": "NAAC AQAR 3.3.3", "source": "real_513_x", "label": None})
for p in sorted((E / "real/drive_items").glob("*.png")):
    items.append({"file": f"real/drive_items/{p.name}", "metric": "NAAC AQAR 3.3.3", "source": "drive_x", "label": "weak"})
for row in csv.DictReader(open(E / "synthetic/labels.csv", encoding="utf-8")):
    items.append({"file": f"synthetic/{row['file']}", "metric": row["metric"], "source": "synthetic",
                  "label": row["label"], "case": row["case"]})

# split by PAGE (both metric variants of one real page go to the same split, so no leakage)
by_source: dict[str, list] = {}
for it in items:
    key = "real_513" if it["source"].startswith("real_513") else it["source"]
    by_source.setdefault(key, []).append(it)
# pages already looked at during development must never be in the test split
SEEN = {"real/clean_513/513_p272.png", "real/clean_513/513_p344.png", "real/clean_513/513_p363.png",
        "real/clean_513/513_p525.png", "real/clean_513/513_p218.png", "real/clean_513/513_p381.png"}
for key, group in by_source.items():
    pages = sorted({it["file"] for it in group})
    seen = [p for p in pages if p in SEEN]
    rest = [p for p in pages if p not in SEEN]
    random.shuffle(rest)
    dev = set(seen + rest[: max(0, len(pages) // 2 - len(seen))])
    for it in group:
        it["split"] = "dev" if it["file"] in dev else "test"

(E / "items.json").write_text(json.dumps(items, indent=1))
for split in ("dev", "test"):
    s = [i for i in items if i["split"] == split]
    print(split, len(s), {k: sum(i["source"] == k for i in s) for k in ("real_513", "real_513_x", "drive_x", "synthetic")})
# labeling sheets for the real pages that need human labels
for split in ("dev", "test"):
    rows = [i for i in items if i["split"] == split and i["label"] is None]
    with open(E / f"to_label_{split}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "metric", "doc_type", "activity_title", "activity_date", "in_period",
                    "seal_or_signature", "fits_metric", "label", "note"])
        for i in rows:
            w.writerow([i["file"], i["metric"]] + [""] * 8)
    print(f"to_label_{split}.csv:", len(rows), "rows")
