"""Upcoming-release notes for dashboard section 16."""

from __future__ import annotations


def _box(
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    body: str = "",
    fill: str = "#ffffff",
) -> str:
    lines = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" '
        f'stroke="#087e83" stroke-width="1.4"/>',
        f'<text x="{x + w / 2}" y="{y + 22}" text-anchor="middle" fill="#173344" '
        f'font-size="13" font-weight="700">{title}</text>',
    ]
    if body:
        lines.append(
            f'<text x="{x + w / 2}" y="{y + 42}" text-anchor="middle" fill="#214b60" '
            f'font-size="11">{body}</text>'
        )
    return "".join(lines)


def _arrow(x1: int, y1: int, x2: int, y2: int, marker: str = "next-arrow") -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#087e83" '
        f'stroke-width="1.6" marker-end="url(#{marker})"/>'
    )


def temporal_svg() -> str:
    inner = "#ffffff"
    shell = "#edf7f7"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 360" role="img" aria-label="Temporal agent workflow">
  <defs>
    <marker id="next-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#087e83"/>
    </marker>
  </defs>
  {_box(16, 145, 150, 70, "Source PDFs", "calls and reports", fill=shell)}
  {_box(196, 16, 668, 328, "Temporal Cloud workflow", "", fill=shell)}
  {_box(230, 58, 175, 64, "Extractor A", "retryable activity", fill=inner)}
  {_box(445, 58, 175, 64, "Extractor B", "isolated activity", fill=inner)}
  {_box(660, 58, 175, 64, "Adjudicator", "automated agent", fill=inner)}
  {_box(230, 250, 175, 64, "Publish rows", "warehouse write", fill=inner)}
  {_box(445, 250, 175, 64, "Refresh RAG", "index the new text", fill=inner)}
  {_box(660, 250, 175, 64, "Receipt", "hashes and status", fill=inner)}
  {_box(896, 145, 168, 70, "Dashboard", "the finished run", fill=shell)}
  {_arrow(166, 180, 196, 180)}
  {_arrow(405, 90, 445, 90)}
  {_arrow(620, 90, 660, 90)}
  {_arrow(317, 122, 317, 250)}
  {_arrow(747, 122, 747, 250)}
  {_arrow(405, 282, 445, 282)}
  {_arrow(620, 282, 660, 282)}
  {_arrow(864, 180, 896, 180)}
  <text x="530" y="200" text-anchor="middle" fill="#214b60" font-size="12">Retries stay in the workflow. No operator click to continue.</text>
</svg>"""


def pricing_svg() -> str:
    inner = "#ffffff"
    shell = "#edf7f7"
    marker = "price-arrow"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 340" role="img" aria-label="Saturday pricing and secondaries path">
  <defs>
    <marker id="price-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#087e83"/>
    </marker>
  </defs>
  {_box(16, 24, 188, 70, "Holdings extract", "companies and weights", fill=shell)}
  {_box(16, 135, 188, 70, "Transaction extract", "calls, sales, true-ups", fill=shell)}
  {_box(16, 246, 188, 70, "Fund databases", "warehouse tables", fill=shell)}
  {_box(248, 135, 188, 70, "Quoted interest", "NAV, dates, fraction", fill=inner)}
  {_box(480, 24, 188, 70, "Seller ask", "percent of NAV", fill=inner)}
  {_box(480, 246, 188, 70, "Buyer ceiling", "required return", fill=inner)}
  {_box(712, 135, 168, 70, "NAV gap", "ask vs reported NAV", fill=inner)}
  {_box(916, 135, 148, 70, "Decision", "pursue or decline", fill=shell)}
  {_arrow(204, 59, 248, 155, marker)}
  {_arrow(204, 170, 248, 170, marker)}
  {_arrow(204, 281, 248, 185, marker)}
  {_arrow(436, 155, 480, 59, marker)}
  {_arrow(436, 185, 480, 281, marker)}
  {_arrow(668, 59, 712, 155, marker)}
  {_arrow(668, 281, 712, 185, marker)}
  {_arrow(880, 170, 916, 170, marker)}
</svg>"""


def next_update_section() -> dict:
    from src.dashboard.build_dashboard import heading, keyvalue, note, steps
    from src.dashboard.teaching import primers_for

    return {
        "id": "next-update",
        "title": "Next update",
        "blurb": (
            "Two additions planned for the next public release. Temporal Cloud will run the "
            "agent jobs that today sit on one machine. Saturday pricing will turn holdings, "
            "cash events, and secondary quotes into a same-session diligence read."
        ),
        "blocks": [
            *primers_for("next-update"),
            heading("Cloud-based agentic automation using Temporal"),
            note(
                "Extractor A, Extractor B, the adjudicator agent, warehouse publication, and the "
                "RAG index rebuild become one Temporal workflow on Temporal Cloud. Each step is an "
                "activity with retries. The run does not stop for an operator to approve. A failed "
                "step resumes from the last completed activity instead of restarting the PDF."
            ),
            {
                "kind": "figure",
                "title": "Temporal run",
                "about": "Documents enter a durable workflow. Isolated extractors and an automated adjudicator, then publish and index.",
                "svg": temporal_svg(),
            },
            steps([
                ("One document run", "A PDF starts a Temporal workflow that records every activity result."),
                ("Parallel extractors", "A and B type the same pages as separate activities and never share scratch files."),
                ("Automated adjudicator", "The third-reader agent compares A and B and writes the kept rows. No operator click."),
                ("Warehouse and RAG", "Publication and index refresh are later activities on the same run ID."),
            ]),
            heading("Saturday pricing and secondaries due diligence"),
            note(
                "The next release folds the One-Day Pricing work into the main product: an LP "
                "interest priced against reported NAV, a seller ask, and a buyer ceiling. It also "
                "deepens transaction and holdings extraction so cash events, company weights, and "
                "secondary filings sit in the same databases the dashboard already opens. A gap "
                "between a secondary price and reported NAV is a market signal, not a score."
            ),
            {
                "kind": "figure",
                "title": "Quote path",
                "about": "Holdings and transactions feed a quoted interest. Ask and ceiling stay separate. The NAV gap informs the decision.",
                "svg": pricing_svg(),
            },
            keyvalue([
                ("Quoted interest", "Transferred fraction of a fund interest, with reference NAV, quote date, and assumed close."),
                ("Seller ask", "An independent percent of NAV. It is not the buyer's affordable price."),
                ("Buyer ceiling", "Discounted post-close cash flows at a stated required return, after settlement true-up."),
                ("Holdings enrichment", "More company, sector, and look-through rows in the extracted and warehouse holdings tables."),
                ("Transaction enrichment", "Calls, distributions, and secondary sales as dated events, not a single remaining-value number."),
                ("NAV gap", "Secondary price versus reported NAV, kept as a comparable for industry appetite, not a GP rank."),
            ]),
        ],
    }
