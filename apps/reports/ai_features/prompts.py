PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_text": {"type": "string"},
        "key_findings": {"type": "string"},
        "tables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "headers": {"type": "array", "items": {"type": "string"}},
                    "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                },
                "required": ["title", "headers", "rows"],
            },
        },
        "charts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["type", "title", "description"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["extracted_text", "key_findings", "tables", "charts", "summary"],
}

# Canonical topics used to break a document summary into independently
# embeddable/searchable sections. (slug, label, guidance)
DOC_SUMMARY_TOPICS = [
    ("overview", "Overview", "what the subject/event/report is about."),
    ("problem_statement", "Problem statement", "the issue, challenge, or need being addressed."),
    ("efforts_to_resolve", "Efforts to resolve", "actions, interventions, or measures taken."),
    ("impacts_recorded", "Impacts recorded", "outcomes, effects, or consequences observed."),
    ("conclusion", "Conclusion", "overall takeaway or result."),
    ("involved_organization", "Involved organization", "organizations, agencies, or bodies involved."),
    (
        "affected_population",
        "Affected population",
        "who was affected, beneficiary numbers, or demographics "
        "(e.g. displaced people, children, women, vulnerable groups).",
    ),
    ("geographic_location", "Geographic location", "country, region, district, or specific location(s) involved."),
    ("timeline", "Timeline", "dates, duration, or phases of the event/response."),
    (
        "needs_assessment",
        "Needs assessment",
        "identified gaps or needs (e.g. shelter, WASH, food security, health, protection).",
    ),
    (
        "resources_and_funding",
        "Resources and funding",
        "funding sources, amounts, or resources mobilized/allocated.",
    ),
    (
        "coordination_and_partnerships",
        "Coordination and partnerships",
        "collaboration between organizations, government bodies, or coordination mechanisms (e.g. clusters).",
    ),
    (
        "recommendations_and_lessons_learned",
        "Recommendations and lessons learned",
        "forward-looking suggestions or lessons for future response.",
    ),
]

DOC_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        # A list (joined into the stored doc summary) rather than one string, so the
        # model can't run on into a page-by-page dump and paragraph count stays bounded.
        "paragraphs": {"type": "array", "items": {"type": "string"}, "maxItems": 7},
        "doc_summary_short": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    "required": ["paragraphs", "doc_summary_short", "sections"],
}

PAGE_PROMPT = """
You are analyzing an image (scan) of a document page.
Extract all content and return ONLY a valid JSON object per this schema -
no explanation, no markdown, no backticks:

{
  "extracted_text": "extracted text of the page",
  "key_findings": "important phrases separated by a period",
  "tables": [{"title": "...", "headers": ["col1", "col2"], "rows": [["val1", "val2"]]}],
  "charts": [{"type": "bar/line/pie etc", "title": "...", "description": "key info + what it shows"}],
  "summary": "dense, factual summary of the page, under 500 words"
}

Summary rules:
- Be dense and factual - not a vague "this page discusses/presents..." overview.
  Write about the content itself; never use "The document"/"The page"/"This
  page" as a sentence subject.
- Capture every number (stats, %, counts, amounts, units), date/timeframe, and
  named location on the page, exactly as stated - never round, estimate, or
  invent. Never swap an exact figure for a vague quantifier ("over a
  million", "about half") when the page states a precise one - write "1,400,000"
  not "over one million". List EVERY distinct location, not just the most
  prominent one, and keep location-specific figures paired with their
  location (don't merge a per-county/per-branch breakdown into one number).
- Name every organization, agency, program, or person mentioned.
- Entity precision (critical): attribute each fact to the EXACT entity it is
  stated about. Never swap in a similar/related entity just because it's
  mentioned nearby (e.g. don't attribute one country's stats to a
  neighboring country also mentioned on the page).
- Funding precision (critical): a funding REQUIREMENT/target (the amount
  asked for, often broken down by channel or thematic area, e.g. "CHF 5
  million through X, CHF 9 million through Y") is a DIFFERENT fact from the
  amount actually RECEIVED/raised or a "% funded" figure, even when they sit
  next to each other on the page. Report both, but keep them separate and
  never phrase the requirement breakdown as if it were the amount received
  (e.g. don't write "has raised CHF 5 million and CHF 9 million" when those
  are the target breakdown and a separate figure says only 13% is funded).
- Pull real values from every visual, not just body text - tables, charts,
  and infographics (icon-stats, annotated maps, info-boxes, pull-quotes).
  State their actual figures/labels, don't just note a visual is present.
  This applies even when the same data is also captured in the "tables"/
  "charts" fields - the "summary" text must independently restate it, since
  it (not the structured fields) is what downstream summarization reads.
  Concretely:
  - Every stat-box/infographic number on the page (e.g. a headline figure
    next to an icon, a ranking, a population count) must appear in the
    summary text by name and value - don't drop one just because it isn't
    part of the main paragraph text.
  - For a table, don't just describe its structure or say entities are
    "marked" or "involved" - name each row's entity individually together
    with its specific column values (e.g. "British Red Cross: Crises,
    Health, Trusted" not "various National Societies were marked with
    checkmarks indicating involvement"). If the table is large, still cover
    every row - a table row is exactly the kind of per-entity figure the
    entity-precision and location-pairing rules above already require.
- State only facts explicitly on the page - no inference or hallucination.
- Preserve conditionals: if the page describes something as conditional,
  planned, or contingent ("would be scaled up if X happens", "planned to"),
  keep that framing in the summary - never state it as something that
  already happened or was actually provided.
- If the page has no substantive informational content - blank, cover/title
  only, table of contents, placeholder or filler text (e.g. "lorem ipsum",
  "no data here", "sample text"), test strings, or gibberish - return
  "summary": "" and "key_findings": "". Do NOT describe the emptiness
  (no "this page contains no data"), and NEVER invent content to fill the
  summary.

Rules:
- Return ONLY the JSON object.
- "tables": [] / "charts": [] if none present.
- "key_findings": "" if none, else phrases separated by a period.
- No trailing commas.
"""


def get_doc_summary_prompt(page_summaries: list[str]):
    return f"""
        Combine the per-page summaries below into one factual document summary.

        Rules (critical):
        1. Use ONLY facts stated in the page summaries. No background
           knowledge, no generic commentary, no plausible filler (e.g.
           "highlighted the need for early warning systems", "vulnerable groups
           were disproportionately affected", unnamed "partners", or services
           not mentioned). Every sentence must be traceable to a page summary.
        2. If the page summaries have no substantive content (blank, "no data",
           placeholder/filler/test text, nonsense), return
           {{"paragraphs": [], "doc_summary_short": "", "sections": []}}.
        3. Copy numbers, dates, names and locations digit-for-digit - never round,
           estimate, compute, or turn an exact figure into "over"/"about".
           Keep every fact tied to the exact entity/location it belongs to.
        4. Funding: a requirement/target (and its breakdown) is a different
           fact from the amount received or "% funded". State both separately;
           never present a requirement as money raised.
        5. Keep conditional/planned things conditional ("would", "if",
           "planned to") - never state them as done. If unsure, keep conditional.
        6. Keep specifics: every named location, per-location/per-indicator
           figures (actual vs target), funding breakdowns, staff/volunteer/branch
           counts. Drop duplicates across pages.
        7. If summaries conflict or a fact is ambiguous, omit it.

        Style: objective and concise. Write about the subject itself, never
        about the document (no sentences starting "The document"/"The
        report"/"This"). Synthesize across pages; don't retell page by page
        or mention pages.

        Topics (cover only those the page summaries actually address; the
        descriptions explain the topic and are NOT content):
        {chr(10).join(f'- "{slug}": {guidance}' for slug, _, guidance in DOC_SUMMARY_TOPICS)}

        Return JSON:
        - "paragraphs": the summary as a list of prose paragraphs, each
          covering a distinct group of topics in under 150 words, packed with
          specific figures (counts, amounts, dates, locations) rather than
          general description. Use 1 paragraph for a short source and up to
          7 for a long one. Never pad.
        - "doc_summary_short": 15-20 words on what the source is about. Add
          a publication year only if one is explicitly stated - never guess.
        - "sections": [{{"topic": <slug from the list>, "content": <a few
          factual sentences>}}] only for topics with material.

        Page summaries:
        {chr(10).join(f"Page {i + 1}: {summary}" for i, summary in enumerate(page_summaries))}
    """
