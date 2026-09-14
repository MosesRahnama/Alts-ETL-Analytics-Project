# RAG evaluation

Source-verified retrieval cases, measured results, the activation decision, and the static dashboard export.

| File | Role |
|---|---|
| `cases.csv` | 35 cases across eight documents: 32 lookups, one constructed claim, one partial-number case, and one access refusal; eight lookups use paraphrased language |
| `results.csv` | Per-case keyword, context, and hybrid results; historical model rows remain labeled and outside current metrics |
| `summary.json` | Aggregate results and the held-out rule that keeps keyword retrieval as the default |
| `public-demo.json` | Permitted questions, bounded excerpts, and current offline measurements embedded in `dashboard.html` |

All three retrieval configurations passed 35 of 35 cases. Hybrid retrieval produced no held-out improvement. Restricted file SRC132 stays out of the public export.
