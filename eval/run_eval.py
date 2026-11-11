"""ProofDesk evaluation harness.

  python run_eval.py gemini  --split dev        # run ProofDesk (Gemini) on non-sensitive items of a split
  python run_eval.py raw     --split dev        # baseline: raw Gemini, plain question, no rubric / no code checks
  python run_eval.py score   --split dev        # score gemini / raw / gemma (from Colab) / ensemble

Rules:
  * Items from real colleges (source starts with 'real_' or 'drive_') are NEVER sent to the Gemini API.
    They are checked only by Gemma (Colab notebook -> gemma_results.json).
  * Ensemble: 'supports' only if Gemini AND Gemma both say supports; disagreement -> needs_review.
  * A prediction is correct if it is in the item's 'acceptable' set (defaults to the label).
  * Headline error = FALSE ACCEPT: predicted 'supports' when the label is 'weak'.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import sys
from datetime import date
from pathlib import Path

E = Path(__file__).parent
sys.path.insert(0, str(E.parent / "app"))
PERIOD = (date(2023, 7, 1), date(2024, 6, 30))
SENSITIVE_PREFIXES = ("real_", "drive_")


def load_items() -> list[dict]:
    items = json.loads((E / "items.json").read_text())
    pub = E / "public_items.json"
    if pub.exists():
        items += json.loads(pub.read_text())
    labels = {}
    for f in sorted(E.glob("labels_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            labels[(r["file"], r["metric"])] = r
    for it in items:
        lab = labels.get((it["file"], it["metric"]))
        if lab:
            it["label"] = lab["label"]
            it["acceptable"] = lab.get("acceptable") or lab["label"]
        elif it.get("label"):
            it.setdefault("acceptable", it["label"])
    return items


def mime_of(path: str) -> str:
    """Detect type from file bytes (some downloaded names were truncated and lost their extension)."""
    head = (E / path).read_bytes()[:12]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head[1:4] == b"PNG":
        return "image/png"
    if head[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def run_gemini(items: list[dict], model: str) -> dict:
    import engine
    packs = engine.load_packs()
    out = {}
    for it in items:
        if it["source"].startswith(SENSITIVE_PREFIXES):
            continue
        key = f"{it['file']}|{it['metric']}"
        data = (E / it["file"]).read_bytes()
        r = engine.check_proof(it["file"], data, mime_of(it["file"]), it["metric"], packs[it["metric"]],
                               *PERIOD, seen={}, model=model)
        out[key] = {"verdict": r.verdict, "flags": r.flags, "quote_check": r.quote_check,
                    "reason": r.reason, "latency_s": r.gemini.get("latency_s"), "cached": r.gemini.get("cached"),
                    "tokens_in": r.gemini.get("tokens_in"), "tokens_out": r.gemini.get("tokens_out")}
        print(f"{it['split']:4} {it['source']:10} {r.verdict:12} {str(r.flags):28} {Path(it['file']).name}", flush=True)
    return out


def run_raw(items: list[dict], model: str) -> dict:
    """Baseline: what an IQAC member gets by dropping the file into Gemini with a plain question."""
    from google.genai import types
    import engine
    out = {}
    for it in items:
        if it["source"].startswith(SENSITIVE_PREFIXES):
            continue
        key = f"{it['file']}|{it['metric']}"
        cache = E / ".raw_cache" / (str(abs(hash((key, model)))) + ".json")
        if cache.exists():
            out[key] = json.loads(cache.read_text())
            continue
        q = (f"Is this document valid proof for NAAC metric {it['metric']} for the academic year 2023-24? "
             "Answer with exactly one word: supports, weak, or needs_review.")
        data = (E / it["file"]).read_bytes()
        resp = engine.client().models.generate_content(
            model=model, contents=[types.Part.from_bytes(data=data, mime_type=mime_of(it["file"])), q])
        word = (resp.text or "").strip().lower()
        v = "supports" if "support" in word else "weak" if "weak" in word else "needs_review"
        out[key] = {"verdict": v, "raw": word[:40]}
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(out[key]))
        print(f"raw {it['split']:4} {v:12} {Path(it['file']).name}", flush=True)
    return out


def wilson_upper(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c + a) / d


def score(items: list[dict], preds: dict, name: str) -> dict:
    rows = [(it, preds.get(f"{it['file']}|{it['metric']}")) for it in items if it.get("label")]
    rows = [(it, p) for it, p in rows if p]
    n = len(rows)
    correct = sum(p["verdict"] in it["acceptable"].split("|") for it, p in rows)
    neg = [(it, p) for it, p in rows if it["label"] == "weak"]
    fa = sum(p["verdict"] == "supports" for it, p in neg)
    pos = [(it, p) for it, p in rows if it["label"] == "supports"]
    hit = sum(p["verdict"] == "supports" for it, p in pos)
    abst = sum(p["verdict"] == "needs_review" for it, p in rows)
    res = {"model": name, "n": n, "correct": correct, "accuracy": round(correct / n, 3) if n else None,
           "false_accepts": fa, "negatives": len(neg),
           "false_accept_upper95": round(wilson_upper(fa, len(neg)), 3) if neg else None,
           "true_supports": hit, "positives": len(pos), "abstained": abst}
    print(f"{name:9} n={n:3}  correct={correct}/{n}  false-accepts={fa}/{len(neg)} "
          f"(95% upper {res['false_accept_upper95']})  supports-recall={hit}/{len(pos)}  abstained={abst}")
    return res


def apply_rules(v: dict, metric_key: str = "") -> dict:
    """Same deterministic rules ProofDesk applies to Gemini output: date window, missing date, low confidence."""
    from engine import date_in_period
    v = dict(v)
    ip = date_in_period(v.get("activity_date", ""), *PERIOD)
    if ip is False:
        v["verdict"] = "weak"
    elif ip is None and v.get("verdict") == "supports":
        v["verdict"] = "needs_review"
    elif ip is None and v.get("verdict") == "weak" and v.get("matches_metric"):
        v["verdict"] = "needs_review"  # fits metric, only the date is missing
    # same beneficiary rule as engine.check_proof (frozen system), driven by the metric pack
    from engine import load_packs
    rule = load_packs().get(metric_key, {}).get("beneficiary_rule")
    ben = v.get("beneficiaries", "unknown")
    if rule == "community" and v.get("verdict") == "supports" and ben != "community":
        v["verdict"] = "weak" if ben == "own_students_or_staff" else "needs_review"
    if v.get("verdict") == "supports" and v.get("confidence") == "low":
        v["verdict"] = "needs_review"
    return v


def ensemble(a: dict, b: dict) -> dict:
    out = {}
    for k in set(a) | set(b):
        va, vb = a.get(k, {}).get("verdict"), b.get(k, {}).get("verdict")
        if va and vb:
            v = va if va == vb else "needs_review"
            if v == "supports" and not (va == vb == "supports"):
                v = "needs_review"
        else:
            v = vb or va  # only one model ran (e.g. sensitive items: Gemma only)
        out[k] = {"verdict": v}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["gemini", "gemma_api", "raw", "score"])
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    a = ap.parse_args()
    items = [i for i in load_items() if a.split == "all" or i["split"] == a.split]
    res_dir = E / "results"
    res_dir.mkdir(exist_ok=True)
    if a.mode == "gemma_api":  # second, independent model family for NON-sensitive items
        preds = run_gemini(items, "gemma-4-26b-a4b-it")
        (res_dir / f"gemma_api_{a.split}.json").write_text(json.dumps(preds, indent=1))
        print(f"saved {len(preds)} predictions")
        return
    if a.mode in ("gemini", "raw"):
        preds = (run_gemini if a.mode == "gemini" else run_raw)(items, a.model)
        (res_dir / f"{a.mode}_{a.split}_{a.model}.json").write_text(json.dumps(preds, indent=1))
        print(f"saved {len(preds)} predictions")
        return
    g = json.loads((res_dir / f"gemini_{a.split}_{a.model}.json").read_text()) if (res_dir / f"gemini_{a.split}_{a.model}.json").exists() else {}
    r = json.loads((res_dir / f"raw_{a.split}_{a.model}.json").read_text()) if (res_dir / f"raw_{a.split}_{a.model}.json").exists() else {}
    gm = {}
    if (res_dir / f"gemma_api_{a.split}.json").exists():
        gm.update(json.loads((res_dir / f"gemma_api_{a.split}.json").read_text()))
    if (res_dir / "gemma_results.json").exists():  # Colab privacy mode (real pages): apply the same code rules
        gm.update({k: apply_rules(v, k.split("|", 1)[1]) for k, v in json.loads((res_dir / "gemma_results.json").read_text()).items()})
    report = [score(items, p, n) for n, p in (("raw", r), ("proofdesk", g), ("gemma", gm), ("ensemble", ensemble(g, gm))) if p]
    (res_dir / f"score_{a.split}.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
