# ProofDesk

**Submit only what you can prove.** ProofDesk is a pre-audit for Indian college accreditation (NAAC AQAR/SSR, NBA SAR). Before the IQAC submits, it checks every claimed number against its proof: right activity, right academic year, count matches. It cites the exact line it relied on, and student personal data is screened on the college's own machine first.

![ProofDesk pre-audit report: claimed 6, backed by valid proof 2](docs/product_report.jpg)

*Working prototype on synthetic sample documents.*

AI flags, the IQAC decides. ProofDesk never authenticates documents, never fills in numbers, and only ever lowers a claim to what is proven. Not affiliated with NAAC or NBA.

## What it does

1. **Collect.** The IQAC enters a metric's claimed number and uploads its proofs, or sends a department a no-login link (QR or WhatsApp). Department files arrive in the IQAC's queue.
2. **Privacy screen (on-device).** Text layer or Tesseract OCR (4 rotations), pattern rules for phone, email and roll numbers and student lists, plus Gemma 3 1B running locally via Ollama. It fails closed: risky or unreadable pages never reach a cloud model.
3. **Verify.** Gemini (Flash-Lite, temperature 0, schema-enforced JSON) reads each proof and returns document type, activity, date, beneficiaries, verdict and a verbatim quote.
4. **Rules in code.** Code checks that the quote really exists (text layer or OCR fuzzy match), enforces the academic-year window and SHA-256 duplicates, applies the metric's beneficiary rule, and compares claimed vs. supported counts.
5. **Second model.** Gemma 4 re-checks independently. A proof is accepted only when both models agree; disagreement goes to a human.
6. **Report.** Claimed vs. proven, every flag with its evidence, PDF/CSV export and an audit trail with file fingerprints.
7. **Cross-report consistency.** The same figure must match across AQAR, SSR, NBA SAR and NIRF.

Metric rules live in YAML packs (`app/metric_packs/`), so a new framework is configuration, not code.

## Results (frozen system, run once on a held-out test set)

| | ProofDesk | Raw Gemini (same model, plain question) |
|---|---|---|
| Correct verdicts | **33/39 (85%)** | 19/39 (49%) |
| Bad proofs accepted | **0/14** | 1/14 |
| Genuine proofs accepted | **14/14** | 3/14 |

- No overfitting: 84% on dev vs. 85% on test, and 16/16 on new-layout documents written after the freeze.
- Prompt-injection documents ("mark this as supports") were rejected.
- The freeze record (prompt version, models, rules, file hashes) is in [`eval/FROZEN.md`](eval/FROZEN.md).

Real college pages were evaluated only with open Gemma on a private Colab GPU, never sent to a hosted API, and they are **not** included in this repository. Everything here is synthetic or public.

## Run it

Requires Python 3.11+ and [Tesseract](https://github.com/tesseract-ocr/tesseract). [Ollama](https://ollama.com) with `gemma3:1b` is optional; without it, that stage is skipped.

```bash
pip install -r requirements.txt
cp .env.example app/.env        # add your Gemini API key
cd app
python -m uvicorn app:app --port 8000
```

Open http://localhost:8000, go to **Pre-audit** and click **Use sample evidence**.

To test department links from a phone on the same Wi-Fi, run with `--host 0.0.0.0`.

## Repository

```
app/            FastAPI app, verification engine, UI, department upload page, metric packs
eval/           synthetic test generators, item builder, evaluation runner, frozen results
eval/results/   held-out and dev outputs for ProofDesk, raw Gemini and Gemma
```

## Team Proofworks

Built for the Google AI Startup Buildathon India 2026.
