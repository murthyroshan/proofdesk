# FROZEN for held-out test — 2026-11-10T20:35
Prompt/schema version: v4 (beneficiaries field)
Verifier model: gemini-3.5-flash-lite (temperature 0, structured JSON)
Second checker: gemma-4-26b-a4b-it via API (non-sensitive items); gemma3:4b on Colab (real college pages)
Baseline: raw gemini-3.5-flash-lite, plain one-line question, no rubric, no code checks
Code rules: date-in-period, missing-date->review, fits-but-no-date->review, SHA-256 duplicate, quote check (text+OCR),
            beneficiary rule (3.3.3 community only), low-confidence supports->review
Ensemble: supports only if both models say supports; disagreement -> needs_review
Tuning history (dev only): v3 -> v4 beneficiaries field + rule (fixed internal tech-fest false accept); fits-but-no-date rule.
File hashes (sha256, first 16): app/engine.py=dac28646bd1f825b; app/metric_packs/naac_aqar.yaml=6b6f67b5ec28664a; app/metric_packs/nba_sar.yaml=6eaa259c78058e06; eval/run_eval.py=02862e5777480b13
Test set: synthetic (test half), public CC photos (test half), synthetic_v2 (16 new-layout docs, written after freeze, test only),
          real college pages (test half, Gemma-only, labels by teammates).
Note: apply_rules now mirrors engine's frozen beneficiary rule (consistency fix, no tuning)

Post-freeze change (scoring only, no prompt/model/rule change): eval/run_eval.py after the apply_rules consistency fix = 733dd1e459d1e40c.
The engine and metric packs are unchanged since the freeze (hashes above still match).
