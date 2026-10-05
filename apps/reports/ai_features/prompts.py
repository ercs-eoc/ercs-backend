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
        "doc_summary": {"type": "string"},
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
    "required": ["doc_summary", "doc_summary_short", "sections"],
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
- If the page has no meaningful content (blank, cover, table of contents),
  say so briefly instead of padding.

Rules:
- Return ONLY the JSON object.
- "tables": [] / "charts": [] if none present.
- "key_findings": "" if none, else phrases separated by a period.
- No trailing commas.
"""


def get_doc_summary_prompt(page_summaries: list[str]):
    return f"""
        You are an expert document analyst. You are given per-page summaries
        of a document. Combine them into one coherent, factual summary:
        merge info across pages, drop duplicates/repetition, preserve facts,
        stats, dates and conclusions, surface the main themes, and highlight
        key findings/recommendations.

        Factual accuracy (critical):
        - No hallucination. State only facts, figures, names, and dates
          explicitly present in the page summaries.
        - Preserve numbers exactly as given - never round, estimate, infer,
          extrapolate, or compute a number that isn't explicitly stated.
          Never downgrade an exact figure into a vague quantifier ("over a
          million", "nearly all") when a page summary gives a precise one -
          e.g. write "1,400,000 people (of 3,200,000 doses)", not "over one
          million people".
        - If summaries conflict or a fact is ambiguous, omit it rather than
          guessing or reconciling it with unstated assumptions.
        - Leave out a topic or "doc_summary_short" entirely rather than
          fabricate content for it.
        - Entity precision: when two similar/related entities appear (e.g.
          the subject country vs. a neighboring one, similarly named orgs),
          keep every fact tied to the exact entity its source summary
          attributed it to. Never merge them or let a fact drift from one to
          the other just because they co-occur.
        - Funding precision (critical, the most commonly gotten-wrong fact):
          a funding REQUIREMENT/target (the amount asked for, often broken
          down by channel, e.g. "CHF 5 million through X, CHF 9 million
          through Y") is NOT the same fact as the amount actually
          RECEIVED/raised or a "% funded" figure - keep them as two separate
          facts even when a page summary mentions both close together.
          Never phrase a requirement breakdown as if it were funding already
          received (e.g. do NOT write "the appeal had raised CHF 5 million
          and CHF 9 million, with a total target of CHF 14 million" if the
          actual received figure is a separate "13% funded" - state instead
          that the requirement is CHF 5M+9M (=CHF 14M target) AND, as a
          distinct fact, that only 13% of it has been funded so far).
        - Preserve conditionals (critical): if a page summary describes
          something as conditional, planned, contingent, or hypothetical
          ("if X occurs, Y would happen", "services would be scaled up if
          needed", "planned to", "would deploy"), it must stay conditional in
          "doc_summary" - never flatten it into a statement that Y actually
          happened or was provided. Do NOT write "ZRCS provided emergency
          shelter services" when the source says shelter/PSS support would
          only be scaled up IF the results announcement was delayed or
          violence escalated - keep the "if/would" framing intact. When
          unsure whether something is conditional or already actual, treat
          it as conditional and phrase it that way.
        - Thoroughness: this is a detailed operational document, not a
          headline-only one. Preserve granular facts where available - every
          named location (not just one or two), per-location/per-indicator
          actual-vs-target figures, funding breakdowns (not just one total),
          and organizational capacity numbers (staff, volunteers, branches).
          Don't flatten available specifics into vague generalities.

        Writing style:
        - Describe the subject matter directly, not the document itself.
          Never open "doc_summary", or any paragraph within it, with "This",
          "The document", "The report", "The presentation", or similar; never
          use "document"/"report"/"presentation" generically as a sentence
          subject anywhere (e.g. "The report states..." is forbidden - a
          proper-noun title like "The 2023 Annual Report of X..." is fine).
          Start straight in on the topic (e.g. "The disaster response..."
          not "This document provides an overview of disaster response.").
          This applies to EVERY sentence, not just the opening one - a
          violation mid-paragraph (e.g. "...community trust. The document
          emphasizes the need for...") is just as forbidden as one at the
          very start. Before finalizing, scan every sentence of "doc_summary"
          for "document"/"report"/"presentation" used generically and rewrite
          any hit, wherever in the text it falls.
        - Informative, objective, concise tone. Don't mention page numbers,
          sections, or that content was extracted from multiple pages.

        Cover the following topics in "doc_summary" wherever the page
        summaries have relevant material (no headings/labels in the prose,
        just flow naturally). Check EVERY topic against the page summaries
        before skipping it - skip only if truly nothing is said about it
        anywhere; a brief, factual mention beats a silent drop. In an
        operational/response report, resources_and_funding, timeline,
        involved_organization, and coordination_and_partnerships almost
        always have at least some material somewhere in the page summaries,
        so scan for it specifically rather than defaulting to the topics
        that happen to dominate any single page:
        {chr(10).join(f"- {label}: {guidance}" for _, label, guidance in DOC_SUMMARY_TOPICS)}

        Page Summaries:

        {chr(10).join(f"Page {i + 1}: {summary}" for i, summary in enumerate(page_summaries))}

        Return a JSON object with:
        1. "doc_summary": 5-7 paragraphs of flowing prose per the style/topics
        above, each paragraph covering a distinct cluster of topics (don't
        write it all as one block). Separate paragraphs with a blank line
        (two newlines) - the string must contain 4-6 such blank-line breaks.
        Use as few as 5 if there isn't enough material to substantively cover
        more - don't pad with vague or repetitive content just to reach 7.
        2. "doc_summary_short": 15-20 words on what this document is all
        about, including the publication year if available.
        3. "sections": an array of {{"topic": ..., "content": ...}} objects,
        one per topic with relevant info in the page summaries (omit a topic
        entirely if there's nothing to say). Use the exact topic slug as
        "topic", and a few factual sentences (not a restatement of the label)
        as "content":
        {chr(10).join(f'- "{slug}" ({label})' for slug, label, _ in DOC_SUMMARY_TOPICS)}

        Before finalizing, re-scan the page summaries once more for
        resources_and_funding, timeline, involved_organization, and
        coordination_and_partnerships specifically, and add any material
        found for them to "doc_summary"/"sections" if missing from your draft.
    """
