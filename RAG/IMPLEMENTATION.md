# RAG implementation status

| Area | State | Current evidence | Boundary |
|---|---|---|---|
| Text index | Complete | 441 indexed reports, one restricted report, 40,788 pages, 494,838 blocks, and zero stale or failed documents | Runtime index stays outside Git |
| Local vectors | Complete | 4,399 active 384-value vectors across all 36 reviewed documents; model revision and block versions are checked before use | Keyword remains available without vector packages |
| Retrieval | Complete | 35 of 35 cases passed under keyword, context, and hybrid configurations across eight documents | Hybrid tied keyword on held-out cases and is not the default |
| Field checks | Complete offline | Each claimed field receives its own assessment and evidence IDs; unrelated notes and partial-number matches do not support a claim | Reasoning-model accuracy is not claimed |
| Context review | Complete offline | Potential definitions, conditions, fee bases, and methods are written only to the private runtime review file | Suggestions require human review |
| Analytics | Complete offline | Five named, parameter-bound reads enforce the session document set and extracted or integrated data group | Arbitrary SQL is refused |
| Access and failure handling | Complete | Sessions, permission-first ranking, stale-vector exclusion, bounded requests, path confinement, cache isolation, and atomic index replacement are covered by tests | Source permissions remain operator decisions |
| Dashboard and tools | Complete | The dedicated RAG page explains the system and provides the loopback evidence console; the PDF opener, MCP adapter, and command line use the same service | Public controls stay disabled; local operations require a reviewer session |
| Extraction instructions | Complete | All 14 A/B route prompts name `search_sources` and `get_evidence`; contract verification requires the tools and the full TXT, grid, and PNG reading rule | Retrieval finds evidence but does not replace page review or write candidate rows |
| Provider reasoning | Disabled | GPT-5.6 Luna through OpenRouter with Max reasoning remains unverified and has no approved job | First provider test requires a recorded approval and verified price settings |

Validation includes 81 passing RAG tests, 86 passing dashboard and repository tests, eight local field-guide skips, Ruff, the release table, and the project structure. A repository-wide run passed 632 tests and found two RAG documentation and prompt-check defects, both corrected and re-tested, plus two checks that require 693 local page images absent from this worktree. No provider request was made. The feature branch is prepared for pull-request review.
