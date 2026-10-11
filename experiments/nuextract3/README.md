# Local NuExtract3 experiment

This experiment evaluates **extraction from saved LightOnOCR text**, not OCR accuracy.
It uses the official NuMind Q4_K_M model with the existing llama.cpp CPU runtime.
It does not call OpenAI, change the app's default extractor, write to the invoice
database, or overwrite original proposals or human reviews.

## Run

From the repository root:

```powershell
node scripts/python.mjs experiments/nuextract3/setup.py
node scripts/python.mjs experiments/nuextract3/run_trial.py
```

The default trial uses the stored Al-Ruwad invoice and handwritten XYZ invoice.
To test another document with complete OCR:

```powershell
node scripts/python.mjs experiments/nuextract3/run_trial.py --invoice DOCUMENT_ID
```

Weights and private inputs/results are ignored by Git under `.local/nuextract3/`.
Results include the full rendered prompt, request, raw model response, parsed
fields/items, token counts, latency, header/item comparisons and validation warnings.
No correct answers or invoice-specific examples are provided in the model prompt.
Manual references are used only **after** inference for scoring this small trial.
The supplied JSON template defines output fields, not document layouts.

## Configuration and integrity

- Official weights: `numind/NuExtract3-GGUF`, revision
  `28a1aae6288c5d50bdf999ca2e572240966d669b`.
- File: `NuExtract3-Q4_K_M.gguf`, 2,783,445,984 bytes; SHA256
  `7ee3c0ee9e5699a4391624ae758487f583f73b3242aa4e73dc2bb33e508d703e`.
- Official chat template: `numind/NuExtract3`, revision
  `c99dc8f5641b866aa0192b6ea78f84bf9f3535f1`.
- Runtime: existing `llama.cpp b11387`, CPU, 4 threads, context 4096,
  one slot, batch 128 / microbatch 64, no vision projector.
- No thinking; temperature 0.2, seed 42, output budget 768 tokens.
- Local server binds `127.0.0.1:18988` and is stopped in `finally`.
- The script verifies the NuExtract structured prompt before inference and
  cancels its own server if Windows available commit falls below 150MB.
- JSON parsing and the app's Pydantic models validate output. No Regex fallback
  replaces failed model responses. Arithmetic warnings never correct amounts.

NuExtract3 is a **generative extraction model**, not a non-generative regex/NER
engine. Performance on two invoices cannot establish production accuracy, and
CPU latency on this memory-constrained laptop cannot establish GPU throughput.

Official sources:
[model and usage](https://huggingface.co/numind/NuExtract3),
[official GGUF weights](https://huggingface.co/numind/NuExtract3-GGUF).

## Actual results — 2026-10-05

Both **real local** requests completed with valid JSON and the app's Pydantic
schema. The same generic prompt and template were used for both documents.

| Saved OCR document | Header comparison | Purchased items | Extraction time |
| --- | --- | --- | --- |
| `invoice_09.png` / Al-Ruwad | 7/7 exact matches | 2/2 items, all 8 item fields match | 114.042 s |
| `handwritten-invoice.png` / XYZ | 6/6 scored fields match; supplier separately verified against the OCR heading | 3/3 items, all 12 item fields match | 116.616 s |

The second supplier output is `XYZ للمقاولات والصيانة`, matching the stored OCR
heading. The physical image contains an additional company prefix; this trial
scores extraction from OCR, and does not repair or score upstream OCR omissions.

Al-Ruwad output:

```json
{
  "invoice_number": "SAL-2024-0876",
  "supplier_name": "شركة الرواد للحلول الحاسوبية",
  "invoice_date": "2024-06-02",
  "subtotal": 7900,
  "vat": 1185,
  "total": 9085,
  "currency": "SAR"
}
```

The model handled a reversed invoice-number label, an OCR typo in the final-total
label, Arabic/English product names, merged HTML footer cells, and Arabic numerals
in the second invoice. It kept XYZ's written subtotal **14,250**, VAT **2,080**
and total **16,330**. Its three item totals are **13,500**, **2,250**, **1,500**;
they sum to **17,250**. The app's independent validator emitted `items_mismatch`.
This warning comes from the validator, not a claim that the model detected the error.

Measured on Intel Core i7-1355U, 7.69GiB total RAM, CPU inference:

- One model load: **14.226 s**, separate from the per-invoice extraction times.
- Al-Ruwad: **1,410** input / **164** output tokens; prompt **71.538 s**,
  generation **42.397 s**, **3.84 output tokens/s**.
- XYZ: **1,119** input / **197** output tokens; prompt **54.644 s**,
  generation **61.162 s**, **3.20 output tokens/s**.
- Both finish reasons were `stop`; neither used prompt-cache hits.
- Server peak working set: **2,896MiB**, approximately **2.83GiB**. This is a
  measured process peak, not a recommended system RAM minimum.
- Available physical RAM fell as low as **17MiB** while other applications
  remained running. These measurements reflect substantial memory pressure.
- Total trial after checksum verification: **245.776 s**. Downloads, OCR time,
  model checksum verification, and classification are outside that duration.
- The trial server was stopped after inference; the existing frontend and API
  still returned HTTP 200, and the app's default extractor remained `regex`.

Private evidence is at:
`.local/nuextract3/results/20261005-163147/summary.json`, with per-document
`.request.json`, `.prompt.txt`, `.response.json`, `.raw.txt`, `.result.json`, and
`server.log` alongside it. Memory fields named `_mb` in the JSON use MiB (2^20 bytes).

**Interpretation:** this is a successful extraction feasibility trial with no
invoice-specific examples or training. Both samples also passed the existing
Regex v2 extraction, so these results do not demonstrate better accuracy than
Regex. NuExtract still performs generative inference and is much slower here.
The current laptop timing is unsuitable for a large daily invoice workload;
server throughput and extraction accuracy need a representative labeled dataset
and measurement on the intended hardware before choosing it for production.

Not evaluated: category classification, missing-field abstention on a dedicated
test set, unknown suppliers/layouts at scale, PDF page aggregation, image input,
OCR accuracy, GPU batching, or repeated-run consistency.
