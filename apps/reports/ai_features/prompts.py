import typing

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        # Listed first so the model commits to this judgement before writing a summary;
        # small vision models otherwise describe photos/covers instead of returning "".
        "has_substantive_content": {"type": "boolean"},
        # Also before the summary: enumerating every stat box/tile first stops the model
        # from dropping headline figures (e.g. "People affected 2.7M") from the summary.
        "key_figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                "required": ["label", "value"],
            },
        },
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
    "required": ["has_substantive_content", "key_figures", "extracted_text", "key_findings", "tables", "charts", "summary"],
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

# Long documents get more paragraphs so later pages' figures aren't squeezed out.
DOC_SUMMARY_MAX_PARAGRAPHS = 7
LONG_DOC_SUMMARY_MAX_PARAGRAPHS = 10
LONG_DOC_PAGE_SUMMARY_COUNT = 20


def doc_summary_max_paragraphs(page_summary_count: int) -> int:
    if page_summary_count > LONG_DOC_PAGE_SUMMARY_COUNT:
        return LONG_DOC_SUMMARY_MAX_PARAGRAPHS
    return DOC_SUMMARY_MAX_PARAGRAPHS


def get_doc_summary_schema(max_paragraphs: int = DOC_SUMMARY_MAX_PARAGRAPHS) -> dict[str, typing.Any]:
    return {
        "type": "object",
        "properties": {
            # A list (joined into the stored doc summary) rather than one string, so the
            # model can't run on into a page-by-page dump and paragraph count stays bounded.
            "paragraphs": {"type": "array", "items": {"type": "string"}, "maxItems": max_paragraphs},
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


DOC_SUMMARY_SCHEMA = get_doc_summary_schema()

PAGE_PROMPT = """
You are analyzing an image (scan) of a document page.
Extract all content and return ONLY a valid JSON object per this schema -
no explanation, no markdown, no backticks.

STEP 1 - decide "has_substantive_content" FIRST:
- true only if the page states concrete facts in its text or data visuals
  (figures, dates, locations, named activities, findings, descriptive
  paragraphs).
- false for: cover/title pages (title, subtitle, logos, partner names),
  section-divider pages (a heading over a photo), photo-only or
  illustration-only pages, logos, headers/footers/page numbers alone, blank
  pages, placeholder/filler/test text, or gibberish.
- false for navigation pages: a table of contents, or a list of chapters,
  sections, figures, tables, or abbreviations - even when long. Chapter
  titles and their page numbers are NOT facts, and page numbers are not
  figures.
- If false: "summary": "" and "key_findings": "" - no exceptions. Do NOT
  describe the photo, the layout, or what the document is "likely" about.

{
  "has_substantive_content": true or false,
  "key_figures": [{"label": "<figure's label as printed>", "value": "<figure as printed>"}],
  "extracted_text": "extracted text of the page",
  "key_findings": "important phrases separated by a period",
  "tables": [{"title": "...", "headers": ["col1", "col2"], "rows": [["val1", "val2"]]}],
  "charts": [{"type": "bar/line/pie etc", "title": "...", "description": "key info + what it shows"}],
  "summary": "dense, factual summary of the page, under 500 words"
}

"key_figures" (fill BEFORE the summary): list EVERY headline figure on the
page - each big number in a stat box, tile, or next to an icon, and chart
totals - with its exact label and value as printed on THIS page. Take the
label from the text that names the figure (often just below it), not from
its unit ("people", "households"). Never copy the schema placeholders above.
[] if the page has no such headline figures (e.g. plain text pages), and []
when "has_substantive_content" is false. The summary must then mention every
key figure with its label.

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
  The same goes for spending: funding received, expenditure, and requirement
  are three different figures - report each one shown, with its own label.
- People counts (critical): "affected", "targeted", "to be reached",
  "reached", and "assisted" are DIFFERENT figures. Use exactly the label the
  page gives each number - e.g. if 1,200,000 are "affected" and 60,000 are
  "targeted", never write that the operation "aims to assist 1,200,000".
- Statistic type (critical): keep the kind of number the page states. A
  median, average, or per-organization value is NOT a total; a percentage is
  NOT a count. If a chart shows medians per National Society, write "median
  of 426,000 per National Society", never "the network reached 426,000".
  When a chart shows both totals and medians, report both, labelled.
- Chart/table labels: attribute each value to the exact row/column/bar label
  it sits next to. A total row (e.g. "Country" or "Total") is not the same
  as a sub-row beneath it (e.g. "IFRC Secretariat").
- Acronyms (critical): use acronyms exactly as written on the page (e.g.
  "ERCS", "NRCS", "DREF", "PGI") and do NOT add their full form - not in
  brackets, not before or after, not even for well-known organizations.
  Use a full form only when this page itself prints it. Never guess what an
  acronym stands for: write "ERCS deployed 45 volunteers", not "ERCS
  (<guessed full form>) deployed 45 volunteers".
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
- If the page has no substantive informational content, return
  "summary": "" and "key_findings": "". This includes: blank pages; cover or
  title pages (a title, subtitle, logos, partner names/logos, without
  figures or factual statements); section-divider pages (a heading over a
  photo); pages that are only photos, illustrations, decorative graphics or
  logos; table of contents; headers/footers/page numbers alone; placeholder
  or filler text (e.g. "lorem ipsum", "no data here", "sample text"); test
  strings; or gibberish. Substantive content means concrete facts stated in
  the page's text or data visuals - figures, dates, locations, named
  activities, findings. A heading, document title or logo alone is NOT
  substantive.
  In that case, NEVER describe what is visible (no "the page features an
  image of a person..."), never describe the emptiness (no "this page
  contains no data"), never guess what the document or section is "likely"
  about, and NEVER invent content to fill the summary. Do not infer facts
  from photos (e.g. a flooded street in a photo is not a fact that the
  report covers floods).
- Never speculate: no "likely", "suggesting", "implies", "possibly",
  "appears to" - if something is not explicitly stated, leave it out.

Rules:
- Return ONLY the JSON object.
- In every field, keep acronyms as printed; never add a full form the page
  doesn't print.
- "extracted_text": write each table row on its own line with cells
  separated by " | " (e.g. "El Oro | 150 | 150 | 430"). NEVER output tab
  characters or long runs of spaces/newlines to align columns.
- "tables": [] / "charts": [] if none present.
- "key_findings": "" if none, else phrases separated by a period.
- No trailing commas.
"""


def get_doc_summary_prompt(page_summaries: list[str], previous_errors: list[str] | None = None):
    # One paragraph per content page (capped at the schema's maxItems), so a multi-page
    # source can't collapse into a single paragraph that drops later pages' figures.
    max_paragraphs = doc_summary_max_paragraphs(len(page_summaries))
    min_paragraphs = min(max_paragraphs, max(1, len(page_summaries)))
    # Fed back on a retry so the model fixes what the figure check rejected instead of
    # regenerating blind.
    previous_errors_note = (
        "A previous answer had these errors - do not repeat them:\n"
        + "\n".join(f"        - {error}" for error in previous_errors)
        if previous_errors
        else ""
    )
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
           Never invent a figure: a range ("from CHF 0.5 million to CHF 2.6
           million") stays a range - never assign its endpoints or any other
           value to individual items; keep qualifiers like "300+" exactly.
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
        8. Coverage (critical): the "paragraphs" must carry the key figures
           from EVERY page summary that has figures - headline totals,
           breakdowns (by channel, thematic area, region, year), people
           counts, and indicator values. Never let a slogan, mission
           statement, or general description crowd out a page's figures;
           figures always take priority over general statements. Figures
           placed in "sections" must ALSO appear in "paragraphs".
        9. Keep each number's label: "affected" vs "targeted" vs "reached",
           median/average vs total, requirement vs received vs expenditure.
           Use acronyms exactly as they appear in the page summaries - do not
           add a full form that the page summaries don't state, not even for
           well-known organizations.

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
          general description. Write at least {min_paragraphs} paragraph(s)
          and at most {max_paragraphs} - enough to carry every page's key figures. Never pad
          with filler.
        - "doc_summary_short": 15-20 words on what the source is about. Do
          not include any year or date unless that exact year/date appears in
          the page summaries.
        - "sections": [{{"topic": <slug from the list>, "content": <a few
          factual sentences>}}] only for topics with material.

        {previous_errors_note}

        Page summaries:
        {chr(10).join(f"Page {i + 1}: {summary}" for i, summary in enumerate(page_summaries))}
    """
