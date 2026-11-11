"""ProofDesk prototype web app.

Run (from this folder):  python -m uvicorn app:app --port 8000
Needs GEMINI_API_KEY in .env. Optional GEMINI_MODEL (default gemini-3.5-flash-lite).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import consistency
import engine

HERE = Path(__file__).parent
app = FastAPI(title="ProofDesk prototype")
PACKS = engine.load_packs()


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.get("/metrics")
def metrics():
    return {k: f"{m['framework']} {m['id']} — {m['name']}" for k, m in PACKS.items() if m.get("unit") == "count"}


@app.post("/check")
async def check(metric: str = Form(...), claimed: int = Form(...), period_start: str = Form(...),
                period_end: str = Form(...), files: list[UploadFile] = File(...)):
    m = PACKS.get(metric)
    if not m:
        return JSONResponse({"error": "unknown metric"}, status_code=400)
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    seen: dict[str, str] = {}
    results = []
    for f in files:
        data = await f.read()
        results.append(engine.check_proof(f.filename, data, f.content_type or "application/octet-stream",
                                          metric, m, start, end, seen))
    dev = engine.deviation_preview(claimed, results, m)
    return {"model": engine.DEFAULT_MODEL, "metric": f"{m['framework']} {m['id']} — {m['name']}",
            "deviation": dev, "results": [asdict(r) for r in results]}


# ---------------- step-by-step API used by the console UI ----------------
import hashlib
import re
import uuid

import fitz
from fastapi.responses import Response

SESSIONS: dict[str, dict] = {}  # session -> {"seen": {}, "files": {sha: (bytes, mime)}, "log": [...]}
SECOND_MODEL = "gemma-4-26b-a4b-it"
PII = {"phone numbers": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"),
       "email addresses": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
       "roll numbers": re.compile(r"\b\d{2}[A-Z0-9]{2}\d[A-Z]\d[A-Z0-9]\d{1,2}\b", re.I),
       "lists of students": re.compile(r"roll\s*(?:no|number)|attend[ae]nce|student\s*name", re.I)}


def _sess(sid: str) -> dict:
    return SESSIONS.setdefault(sid, {"seen": {}, "files": {}, "log": []})


@app.post("/session")
def new_session():
    sid = uuid.uuid4().hex[:12]
    _sess(sid)
    return {"session": sid}


@app.post("/screen")
async def screen(session: str = Form(...), file: UploadFile = File(...)):
    """On-device privacy screen (text layer / OCR + pattern rules). Pages with student data never reach the cloud."""
    import time as _t
    t0 = _t.perf_counter()
    data = await file.read()
    mime = file.content_type or "application/octet-stream"
    pages = engine.pdf_text_pages(data) if mime == "application/pdf" else None
    has_text = bool(pages and "".join(pages).strip())
    text = "\n".join(pages) if has_text else engine.ocr_text(data, mime)
    hits = {k: len(rx.findall(text)) for k, rx in PII.items()}
    found = [k for k, v in hits.items() if v]
    gemma = _gemma_local_pii(text) if not found and len(text.strip()) > 20 else None
    if gemma is True:
        found.append("personal data (Gemma)")
    _sess(session)["log"].append({"t": _now(), "event": "screened on-device", "file": file.filename,
                                  "result": "clean" if not found else "blocked: " + ", ".join(found)})
    return {"file": file.filename, "clean": not found, "found": found, "pages": len(pages) if pages else 1,
            "readable": len(text.strip()) > 20,
            "stages": {"read": "text layer" if has_text else "OCR",
                       "patterns": "clean" if not any(hits.values()) else "hit",
                       "gemma": {True: "flagged", False: "clean", None: "skipped"}[gemma]},
            "ms": round((_t.perf_counter() - t0) * 1000)}


def _now():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def _gemma_local_pii(text: str):
    """Ask Gemma 3 1B running locally (Ollama) whether the text has personal data. None if it isn't running."""
    import json as _j
    import urllib.request as _u
    prompt = ("Answer only YES or NO. Does this text contain personal data of individual students or staff "
              "(phone numbers, emails, roll numbers, ID numbers, or a list of named students)?\n\n"
              + text[:2500] + "\n\nAnswer:")
    try:
        body = _j.dumps({"model": "gemma3:1b", "prompt": prompt, "stream": False,
                         "options": {"temperature": 0, "num_predict": 3}}).encode()
        r = _u.urlopen(_u.Request("http://localhost:11434/api/generate", body,
                                  {"Content-Type": "application/json"}), timeout=25)
        return _j.loads(r.read())["response"].strip().upper().startswith("Y")
    except Exception:  # noqa: BLE001
        return None


@app.post("/verify")
async def verify(session: str = Form(...), metric: str = Form(...), period_start: str = Form(...),
                 period_end: str = Form(...), file: UploadFile = File(...)):
    m = PACKS.get(metric)
    if not m:
        return JSONResponse({"error": "unknown metric"}, status_code=400)
    s = _sess(session)
    data = await file.read()
    mime = file.content_type or "application/octet-stream"
    sha = hashlib.sha256(data).hexdigest()
    s["files"][sha] = (data, mime)
    r = engine.check_proof(file.filename, data, mime, metric, m, date.fromisoformat(period_start),
                           date.fromisoformat(period_end), s["seen"])
    out = asdict(r)
    out["model"] = engine.DEFAULT_MODEL
    out["gemini_verdict"] = r.verdict
    out["second"] = None
    if not r.duplicate_of and "ai_error" not in r.flags:
        g2 = engine.check_proof(file.filename, data, mime, metric, m, date.fromisoformat(period_start),
                                date.fromisoformat(period_end), {}, model=SECOND_MODEL)
        if "ai_error" not in g2.flags:
            out["second"] = {"model": SECOND_MODEL, "verdict": g2.verdict, "reason": g2.reason}
            if r.verdict != g2.verdict:
                out["verdict"] = "needs_review"
                out["flags"] = out["flags"] + ["models_disagree"]
                out["reason"] = (f"The two models disagree ({r.verdict.replace('_', ' ')} vs "
                                 f"{g2.verdict.replace('_', ' ')}), so the IQAC decides. " + r.reason)
    s["log"].append({"t": _now(), "event": "verified", "file": file.filename, "sha": sha[:12],
                     "result": out["verdict"]})
    return out


@app.get("/page")
def page(session: str, sha: str, quote: str = "", p: int = 1):
    """Render a proof page as PNG, with the cited quote highlighted (for the evidence side panel)."""
    s = _sess(session)
    if sha not in s["files"]:
        return JSONResponse({"error": "unknown file"}, status_code=404)
    data, mime = s["files"][sha]
    if mime != "application/pdf":
        return Response(content=data, media_type=mime)
    doc = fitz.open(stream=data, filetype="pdf")
    pg = doc[max(0, min(p - 1, len(doc) - 1))]
    if quote.strip():
        for rect in pg.search_for(quote.strip())[:4]:
            annot = pg.add_highlight_annot(rect)
            annot.set_colors(stroke=(1.0, 0.86, 0.35))
            annot.update()
    pix = pg.get_pixmap(dpi=144, annots=True)
    return Response(content=pix.tobytes("png"), media_type="image/png")


@app.post("/report.pdf")
async def report_pdf(payload: dict):
    """Printable one-page pre-audit summary for the IQAC."""
    from html import escape as e
    label = {"supports": "VERIFIED", "weak": "FLAGGED"}
    rows = "".join(
        f"<tr><td>{i + 1}</td><td><b>{e(str(r.get('title') or r.get('file', '')))}</b><br>"
        f"<span class='m'>{e(str(r.get('reason', '')))}</span></td>"
        f"<td class='v {r.get('verdict')}'>{label.get(r.get('verdict'), 'REVIEW')}</td></tr>"
        for i, r in enumerate(payload.get("results", [])))
    html = (f"<h1>ProofDesk pre-audit</h1><p class='m'>{e(str(payload.get('institution', '')))} &middot; "
            f"{e(str(payload.get('metric', '')))} &middot; {e(str(payload.get('period', '')))} &middot; "
            f"generated {e(str(payload.get('when', '')))}</p>"
            f"<p class='big'>Claimed <b>{payload.get('claimed')}</b> &middot; Backed by valid proof "
            f"<b>{payload.get('proven')}</b> &middot; Recommended claim <b>{payload.get('proven')}</b></p>"
            f"<table>{rows}</table>"
            "<p class='m'>AI flags, the IQAC decides. ProofDesk never authenticates documents or fills in numbers. "
            "Recommendations only lower a claim to what is proven. Not affiliated with NAAC.</p>")
    css = ("*{font-family:sans-serif;color:#17191e} h1{font-size:20pt;margin:0} .m{color:#666;font-size:9pt}"
           " .big{font-size:12pt;margin:12pt 0} table{width:100%;border-collapse:collapse;font-size:9.5pt}"
           " td{border-top:1px solid #ddd;padding:6pt 4pt;vertical-align:top} .v{font-weight:bold;font-size:8.5pt}"
           " .supports{color:#1f7a4d} .weak{color:#c2410c} .needs_review{color:#9a6a04}")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_htmlbox(fitz.Rect(48, 48, 547, 800), html, css=css)
    return Response(content=doc.tobytes(), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=proofdesk_preaudit.pdf"})


@app.get("/log")
def audit_log(session: str):
    return _sess(session)["log"]


@app.get("/favicon.svg")
def favicon():
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
           "<rect width='64' height='64' rx='15' fill='#0f2a2c'/>"
           "<circle cx='32' cy='32' r='26' fill='none' stroke='#f5c84c' stroke-width='1.6' stroke-dasharray='2.6 3' opacity='.8'/>"
           "<path d='M21 14h14l8 8v24a3 3 0 0 1-3 3H21a3 3 0 0 1-3-3V17a3 3 0 0 1 3-3z' fill='#fffdf6'/>"
           "<path d='M35 14v8h8' fill='#e9e1cf'/>"
           "<rect x='22' y='27' width='17' height='5' rx='1.4' fill='#f5c84c'/>"
           "<path d='M29 40l4 4 9-10' fill='none' stroke='#1f9d5c' stroke-width='3.6' stroke-linecap='round' stroke-linejoin='round'/>"
           "</svg>")
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


DEMO_DIR = HERE.parent / "eval" / "demo"  # synthetic, stamped documents only


@app.get("/demo/files")
def demo_files():
    return sorted(p.name for p in DEMO_DIR.glob("*.pdf"))


@app.get("/demo/file/{name}")
def demo_file(name: str):
    p = DEMO_DIR / Path(name).name
    if not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/pdf")


@app.post("/consistency")
async def consistency_check(csv_text: str = Form(None), file: UploadFile = File(None)):
    text = csv_text or (await file.read()).decode("utf-8-sig") if (csv_text or file) else consistency.DEMO_CSV
    return consistency.check(consistency.parse_csv(text))


@app.get("/consistency/demo")
def consistency_demo():
    return {"csv": consistency.DEMO_CSV, **consistency.check(consistency.parse_csv(consistency.DEMO_CSV))}


# ---------------- department upload links (no login, opens from WhatsApp) ----------------
import secrets
import socket
import time as _time
from fastapi import Request

SHARES: dict[str, dict] = {}  # token -> {"dept", "metric", "period", "created", "files": [...]}
MAX_FILE = 15 * 1024 * 1024
MAX_FILES = 40


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; only picks the outgoing interface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


@app.post("/share")
async def create_share(request: Request, dept: str = Form(...), metric: str = Form(""), period: str = Form("")):
    token = secrets.token_urlsafe(9)
    SHARES[token] = {"dept": dept.strip()[:60] or "Department", "metric": metric[:120], "period": period[:40],
                     "created": _now(), "files": []}
    port = request.url.port or 80
    return {"token": token, "url": f"http://{_lan_ip()}:{port}/d/{token}",
            "local_url": f"{request.base_url}d/{token}"}


@app.get("/d/{token}")
def dept_page(token: str):
    if token not in SHARES:
        return JSONResponse({"error": "This link has expired. Ask your IQAC for a new one."}, status_code=404)
    return FileResponse(HERE / "dept.html")


@app.get("/d/{token}/info")
def dept_info(token: str):
    sh = SHARES.get(token)
    if not sh:
        return JSONResponse({"error": "expired"}, status_code=404)
    return {"dept": sh["dept"], "metric": sh["metric"], "period": sh["period"], "received": len(sh["files"])}


@app.post("/d/{token}/upload")
async def dept_upload(token: str, file: UploadFile = File(...), note: str = Form("")):
    sh = SHARES.get(token)
    if not sh:
        return JSONResponse({"error": "expired"}, status_code=404)
    if len(sh["files"]) >= MAX_FILES:
        return JSONResponse({"error": "This link has reached its file limit."}, status_code=413)
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        return JSONResponse({"error": "File is larger than 15 MB."}, status_code=413)
    mime = file.content_type or "application/octet-stream"
    if not (mime == "application/pdf" or mime.startswith("image/")):
        return JSONResponse({"error": "Send a PDF or a photo."}, status_code=415)
    name = Path(file.filename or "proof").name[:120]
    sh["files"].append({"name": name, "data": data, "mime": mime, "note": note[:200], "t": _now(),
                        "sha": hashlib.sha256(data).hexdigest()})
    return {"ok": True, "received": len(sh["files"])}


@app.get("/share/{token}/files")
def share_files(token: str):
    sh = SHARES.get(token)
    if not sh:
        return JSONResponse({"error": "expired"}, status_code=404)
    return [{"i": i, "name": f["name"], "size": len(f["data"]), "mime": f["mime"], "t": f["t"], "note": f["note"],
             "dept": sh["dept"]} for i, f in enumerate(sh["files"])]


@app.get("/share/{token}/file/{i}")
def share_file(token: str, i: int):
    sh = SHARES.get(token)
    if not sh or not 0 <= i < len(sh["files"]):
        return JSONResponse({"error": "not found"}, status_code=404)
    f = sh["files"][i]
    return Response(content=f["data"], media_type=f["mime"])
