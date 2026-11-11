"""On-device privacy screen (nothing leaves the laptop).

Per page/image:
  1. Tesseract OCR -> text
  2. Regex rules  -> Indian mobile numbers, emails, roll numbers, Aadhaar-like numbers
  3. Gemma 3 1B (local, via Ollama) -> second opinion: does the text contain personal data of students/staff?
A page is CLEAN only if regex finds nothing AND Gemma says no. Otherwise it is excluded from any cloud call.

Usage: python privacy_screen.py <folder_with_png_or_pdf> [out.json]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OLLAMA_URL = "http://localhost:11434/api/generate"
GEMMA = "gemma3:1b"

RULES = {
    "mobile": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "roll_no": re.compile(r"\b\d{2}[A-Z0-9]{2}\d[A-Z]\d[A-Z0-9]\d{1,2}\b", re.I),
    "aadhaar": re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)"),
    # headings that mean "this page is a list of named people" (attendance, feedback, registers), even if
    # the names/numbers themselves are handwritten and unreadable
    "person_list": re.compile(r"roll\s*(?:no|number|num)|attend[ae]nce|signature\s*of\s*(?:the\s*)?student|register\s*(?:no|number)|"
                              r"admission\s*(?:no|number)|hall\s*ticket|student\s*name|your\s*name|"
                              r"name\s+of\s+the\s+student|aadhaar|aadhar|mobile\s*(?:no|number)|phone\s*(?:no|number)",
                              re.I),
}


def _ocr_file(path: Path) -> str:
    r = subprocess.run([TESSERACT, str(path), "stdout", "--psm", "3"], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    return r.stdout


def _quality(text: str) -> int:
    """Number of real-looking words (3+ letters) + long digit runs: higher = better read."""
    return len(re.findall(r"[A-Za-z]{3,}", text)) + len(re.findall(r"\d{6,}", text))


def ocr(path: Path) -> list[tuple[int, str]]:
    """OCR at all 4 rotations (scans are often sideways). Returns [(rotation, text), ...]."""
    from PIL import Image
    import os
    import tempfile
    img = Image.open(path)
    if img.width < 1600:  # small renders OCR badly (sideways fine print); upscale 2x
        img = img.resize((img.width * 2, img.height * 2))
    out = []
    for rot in (0, 90, 180, 270):
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.rotate(rot, expand=True).save(tmp)
        out.append((rot, _ocr_file(Path(tmp))))
        os.remove(tmp)
    return out


def gemma_has_pii(text: str) -> tuple[bool | None, float]:
    prompt = ("You are a privacy filter. Answer only YES or NO.\n"
              "Does the following OCR text contain personal data of individual students or staff, such as "
              "phone numbers, email addresses, roll numbers, ID numbers, or a list of named students?\n\n"
              f"TEXT:\n{text[:3000]}\n\nAnswer:")
    body = json.dumps({"model": GEMMA, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "num_predict": 3}}).encode()
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(urllib.request.Request(OLLAMA_URL, body, {"Content-Type": "application/json"}),
                                      timeout=180)
        ans = json.loads(resp.read())["response"].strip().upper()
        return ans.startswith("Y"), round(time.perf_counter() - t0, 2)
    except Exception:  # noqa: BLE001
        return None, round(time.perf_counter() - t0, 2)


def screen(path: Path) -> dict:
    """Fail-safe: a page is excluded if ANY rotation shows PII, or if it is unreadable, or if Gemma says yes/errs."""
    t0 = time.perf_counter()
    reads = ocr(path)
    ocr_s = round(time.perf_counter() - t0, 2)
    hits = {k: sum(len(rx.findall(t)) for _, t in reads) for k, rx in RULES.items()}
    regex_pii = any(hits.values())
    rot, text = max(reads, key=lambda r: _quality(r[1]))  # best-looking read for Gemma
    quality = _quality(text)
    readable = quality >= 15
    gemma_pii, gemma_s = gemma_has_pii(text) if (readable and not regex_pii) else (None, 0.0)
    clean = readable and (not regex_pii) and (gemma_pii is False)
    reason = ("regex" if regex_pii else "unreadable" if not readable else
              "gemma" if gemma_pii else "gemma_error" if gemma_pii is None else "clean")
    return {"file": path.name, "clean": clean, "reason": reason, "regex_hits": hits, "gemma_pii": gemma_pii,
            "ocr_quality": quality, "rotation": rot, "ocr_s": ocr_s, "gemma_s": gemma_s}


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else folder / "privacy_screen.json"
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    results = []
    for p in files:
        r = screen(p)
        results.append(r)
        print(f"{r['file']:22} clean={r['clean']!s:5} why={r['reason']:11} q={r['ocr_quality']} rot={r['rotation']} regex={r['regex_hits']} gemma={r['gemma_pii']} "
              f"ocr={r['ocr_s']}s gemma={r['gemma_s']}s", flush=True)
    out.write_text(json.dumps(results, indent=1))
    n = len(results)
    c = sum(r["clean"] for r in results)
    print(f"\n{c}/{n} pages clean; {n - c} excluded (contain personal data or uncertain). Saved {out}")
