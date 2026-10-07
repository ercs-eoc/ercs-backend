import base64
import io
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

import fitz  # pyright: ignore[reportMissingTypeStubs]
from django.conf import settings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from PIL import Image

from apps.reports.ai_features.llms import LLMHandler, get_chat_llm_handler, get_embedding_llm_handler
from apps.reports.ai_features.prompts import (
    DOC_SUMMARY_TOPICS,
    PAGE_SCHEMA,
    doc_summary_max_paragraphs,
    get_doc_summary_prompt,
    get_doc_summary_schema,
)
from apps.reports.models import DocumentExtraction, DocumentExtractionStatus, Report

logger = logging.getLogger(__name__)

# A number (optionally with thousands separators/decimals, or an ordinal suffix) and an
# optional scale word, e.g. "1,200,000", "426 000", "24.3", "26th", "1.2 million", "CHF 110.7M".
# A currency code may be glued to either side ("CHF200,083", "68,629CHF"), as IFRC
# budget tables often print it; otherwise those figures would be invisible to grounding.
FIGURE_PATTERN = re.compile(
    r"(?:(?<=CHF)|(?<=USD)|(?<=EUR)|(?<=GBP)|(?<![\w.]))"
    r"(\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s*"
    r"(thousand|million|billion|mn|bn|[kmb])?(?=(?:CHF|USD|EUR|GBP)\b|(?!\w))",
    re.IGNORECASE,
)
FIGURE_SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}
# A key figure's label must name it with at least one real word: labels that are just
# a number/currency (chart axis ticks such as "CHF 80,000,000") are not headline figures.
KEY_FIGURE_LABEL_WORD = re.compile(r"\b(?!(?:CHF|USD|EUR|GBP)\b)[^\W\d_]{2,}")
# Single digits are mostly list counters/ordinals/word-like ("3 districts") and too
# common to be a meaningful grounding signal.
MIN_CHECKED_FIGURE = 10


def _figure_values(match: re.Match[str]) -> set[float]:
    """All values a figure may denote: as written, and scaled ("1.2M" == 1,200,000)."""
    value = float(re.sub(r"[ ,]", "", match.group(1)))
    scale = FIGURE_SCALES.get((match.group(2) or "").lower())
    return {round(value, 4)} | ({round(value * scale, 4)} if scale else set())


def extract_figures(text: str) -> set[float]:
    return {value for match in FIGURE_PATTERN.finditer(text) for value in _figure_values(match)}


def find_ungrounded_figures(text: str, source_figures: set[float]) -> list[str]:
    """Figures in `text` that don't appear (in any written form) in `source_figures`."""
    ungrounded = []
    for match in FIGURE_PATTERN.finditer(text):
        values = _figure_values(match)
        if max(values) < MIN_CHECKED_FIGURE:
            continue
        if not values & source_figures:
            ungrounded.append(match.group(0).strip())
    return ungrounded


# What a people/household count is labelled as. The combine model has been seen to turn
# a "people affected" figure into the number the operation "aims to assist", and to swap
# people for households/families ("1,800 people (360 families)" -> "1,800 families").
FIGURE_UNITS = {
    "people": "people",
    "persons": "people",
    "individuals": "people",
    "households": "households",
    "household": "households",
    "hhs": "households",
    "hh": "households",
    "families": "households",
    "family": "households",
}
AIM_WORDS = re.compile(r"\b(?:aim|assist|target|reach|support)\w*", re.IGNORECASE)
AFFECTED_WORDS = re.compile(r"\b(?:affected|at risk|in need)\b", re.IGNORECASE)


@dataclass
class FigureContext:
    values: set[float]
    text: str
    unit: str | None
    aimed: bool  # an assist/target/reach verb leads up to the figure
    affected: bool  # labelled as affected/at risk/in need


def figure_contexts(text: str) -> list[FigureContext]:
    """Each checked figure with the label words around it, bounded by neighbouring figures and sentences."""
    matches = [m for m in FIGURE_PATTERN.finditer(text) if max(_figure_values(m)) >= MIN_CHECKED_FIGURE]
    contexts = []
    for i, match in enumerate(matches):
        before = text[matches[i - 1].end() if i else 0 : match.start()]
        before = re.split(r"[.;\n]\s", before)[-1][-60:]
        after = text[match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)][:30]
        after = re.split(r"[.;\n]\s", after)[0]
        unit_word = re.match(r"\s*([a-z]+)", after, re.IGNORECASE)
        contexts.append(
            FigureContext(
                values=_figure_values(match),
                text=match.group(0).strip(),
                unit=FIGURE_UNITS.get(unit_word.group(1).lower()) if unit_word else None,
                aimed=bool(AIM_WORDS.search(before)),
                affected=bool(AFFECTED_WORDS.search(before + after)),
            ),
        )
    return contexts


def find_mislabeled_figures(text: str, source_contexts: list[FigureContext]) -> list[str]:
    """Figures in `text` whose unit or affected-vs-assisted label contradicts every source mention."""
    issues = []
    for context in figure_contexts(text):
        sources = [source for source in source_contexts if context.values & source.values]
        if not sources:
            continue  # ungrounded figures are reported by find_ungrounded_figures
        source_units = {source.unit for source in sources if source.unit}
        if context.unit and source_units and context.unit not in source_units:
            issues.append(f"{context.text} counts {'/'.join(sorted(source_units))}, not {context.unit}")
        if context.aimed and any(s.affected for s in sources) and not any(s.aimed for s in sources):
            issues.append(f"{context.text} is the number affected, not the number assisted/targeted/reached")
    return issues


@dataclass
class BaseExtraction:
    report: Report

    llm_handler: LLMHandler = field(init=False)
    llm_chat_model: BaseChatModel = field(init=False)
    # Text-only model for the doc-level summary combine step (never sees images), which can
    # be a different, non-vision model from LLM_MODEL_NAME via LLM_DOC_SUMMARY_MODEL_NAME.
    doc_summary_chat_model: BaseChatModel = field(init=False)
    llm_embedding_model: Embeddings = field(init=False)

    def __post_init__(self):
        try:
            self.llm_handler = get_chat_llm_handler()
            self.llm_chat_model = self.llm_handler.load_chat_model()
            self.doc_summary_chat_model = self.llm_handler.load_chat_model(
                model_name=settings.LLM_DOC_SUMMARY_MODEL_NAME,
            )
            self.llm_embedding_model = get_embedding_llm_handler().load_embedding_model()
        except Exception as e:
            raise e

    def handle_meta_info(self):
        """Extract meta information of the report."""
        title = self.report.title
        description = self.report.description
        if title and title.strip():
            DocumentExtraction.objects.create(
                report=self.report,
                status=DocumentExtractionStatus.SUCCESS,
                text=title,
                page_number=None,
                chunk_type=DocumentExtraction.ExtractionType.TITLE,
                embedding=self.llm_embedding_model.embed_query(title),
            )
        if description and description.strip():
            DocumentExtraction.objects.create(
                report=self.report,
                status=DocumentExtractionStatus.SUCCESS,
                text=description,
                page_number=None,
                chunk_type=DocumentExtraction.ExtractionType.DESCRIPTION,
                embedding=self.llm_embedding_model.embed_query(description),
            )


@dataclass
class PdfExtraction(BaseExtraction):
    data: bytes

    # Qwen2.5-VL uses a native dynamic-resolution vision encoder, so the number of
    # vision tokens (and Ollama's memory/compute use) scales with input pixel count.
    # Cap the longest side so oversized source pages can't blow up memory regardless
    # of the render zoom.
    MAX_IMAGE_DIMENSION = 1024

    # Retries for a single page's LLM extraction call, covering transient network/
    # timeout errors as well as malformed or truncated JSON in the model's response.
    MAX_PAGE_ATTEMPTS = 3
    PAGE_RETRY_DELAY_SECONDS = 3
    # Text-dense pages can exhaust the handler's default per-page num_ctx (prompt +
    # vision tokens + a long extracted_text), cutting the JSON off mid-string. When a
    # response is malformed/truncated, retry with the next larger window instead of
    # repeating a call that will truncate at the same point.
    PAGE_RETRY_CONTEXT_WINDOWS = (10240, 16384)

    # Doc-summary context window sizing. The prompt concatenates every page's summary,
    # so its input size scales with page count - a fixed window silently truncates
    # earlier page summaries out of the final document summary once the doc has enough
    # pages (or the page summaries are long enough). Estimate tokens from the prompt's
    # character count (~4 chars/token for English) and reserve headroom for the model's
    # own output (up to 10 paragraphs + short summary + per-topic sections).
    DOC_SUMMARY_OUTPUT_TOKEN_BUDGET = 3072
    DOC_SUMMARY_CONTEXT_WINDOW_FLOOR = 8192
    DOC_SUMMARY_CONTEXT_WINDOW_CEILING = 32768
    CHARS_PER_TOKEN_ESTIMATE = 4

    @classmethod
    def estimate_doc_summary_context_window(cls, prompt: str) -> int:
        """Size num_ctx for the doc-summary call from the actual prompt length.

        Rounds up to the nearest 1024 (a clean KV-cache size for Ollama) and clamps
        to a sane floor/ceiling so pathologically small or huge documents don't
        under- or over-allocate.
        """
        input_tokens = math.ceil(len(prompt) / cls.CHARS_PER_TOKEN_ESTIMATE)
        required_tokens = input_tokens + cls.DOC_SUMMARY_OUTPUT_TOKEN_BUDGET
        rounded = math.ceil(required_tokens / 1024) * 1024
        return max(cls.DOC_SUMMARY_CONTEXT_WINDOW_FLOOR, min(rounded, cls.DOC_SUMMARY_CONTEXT_WINDOW_CEILING))

    def img_to_base64(self, data: fitz.Pixmap) -> str:
        img_bytes = data.tobytes("png")

        image = Image.open(io.BytesIO(img_bytes))
        if max(image.size) > self.MAX_IMAGE_DIMENSION:
            scale = self.MAX_IMAGE_DIMENSION / max(image.size)
            new_size = (round(image.width * scale), round(image.height * scale))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            img_bytes = buffer.getvalue()

        return base64.b64encode(img_bytes).decode("utf-8")

    def extract_page(self, page_idx: int, img_b64: str) -> dict[str, Any] | None:
        """Run the LLM extraction call for a single page, retrying on failure."""
        message = self.llm_handler.construct_extraction_message(img_b64=img_b64)
        # None -> the chat model's default num_ctx; grown only after a truncated response.
        context_window: int | None = None
        larger_context_windows = iter(self.PAGE_RETRY_CONTEXT_WINDOWS)

        for attempt in range(1, self.MAX_PAGE_ATTEMPTS + 1):
            try:
                result = self.llm_handler.generate_structured(
                    self.llm_chat_model,
                    [message],
                    PAGE_SCHEMA,
                    context_window=context_window,
                    is_retry=attempt > 1,
                )
                if result.get("has_substantive_content") is False:
                    # Cover/photo/divider pages: drop the summary and key findings even if the
                    # model wrote some anyway, so descriptions of images or guesses about the
                    # document don't reach the doc summary or search index.
                    result["summary"] = ""
                    result["key_findings"] = ""
                    result["key_figures"] = []
                else:
                    result["summary"] = self.append_missing_key_figures(
                        self.drop_mislabeled_sentences(result.get("summary") or "", result.get("extracted_text") or ""),
                        result.get("key_figures") or [],
                        page_text=result.get("extracted_text") or "",
                    )
                return result
            except json.JSONDecodeError:
                logger.warning(
                    "Page %s extraction attempt %s/%s returned malformed or truncated JSON (num_ctx=%s)",
                    page_idx + 1,
                    attempt,
                    self.MAX_PAGE_ATTEMPTS,
                    context_window or "default",
                    exc_info=True,
                )
                context_window = next(larger_context_windows, context_window)
                if attempt < self.MAX_PAGE_ATTEMPTS:
                    time.sleep(self.PAGE_RETRY_DELAY_SECONDS)
            except Exception:
                logger.warning(
                    "Page %s extraction attempt %s/%s failed",
                    page_idx + 1,
                    attempt,
                    self.MAX_PAGE_ATTEMPTS,
                    exc_info=True,
                )
                if attempt < self.MAX_PAGE_ATTEMPTS:
                    time.sleep(self.PAGE_RETRY_DELAY_SECONDS)

        logger.error("Page %s extraction failed after %s attempts", page_idx + 1, self.MAX_PAGE_ATTEMPTS)
        return None

    @staticmethod
    def drop_mislabeled_sentences(summary: str, page_text: str) -> str:
        """Drop page-summary sentences that relabel a figure printed on the page.

        e.g. "aims to assist 14,000 people" for a page printing "People Affected: 14,000".
        Once in the page summary such an error passes every later check, since the doc
        summary is grounded against page summaries; the figure itself comes back with its
        printed label through `append_missing_key_figures`.
        """
        page_contexts = figure_contexts(page_text)
        sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
        kept = []
        for sentence in sentences:
            if find_mislabeled_figures(sentence, page_contexts):
                logger.warning("Dropping page summary sentence with mislabeled figures: %s", sentence)
            else:
                kept.append(sentence)
        return summary if len(kept) == len(sentences) else " ".join(kept)

    @staticmethod
    def append_missing_key_figures(summary: str, key_figures: list[dict[str, str]], page_text: str) -> str:
        """Append headline figures the model listed in `key_figures` but left out of the summary.

        The summary (not the structured fields) is what the doc summary and search read,
        so a stat-box figure missing from it would be lost downstream. Only figures that
        also appear in the page's own extracted text are appended, so a figure the model
        invented (e.g. copied from a prompt example) can't be injected into the summary.
        """
        summary_figures = extract_figures(summary)
        page_figures = extract_figures(page_text)
        missing = [
            f"{figure['label'].strip()}: {figure['value'].strip()}"
            for figure in key_figures
            if KEY_FIGURE_LABEL_WORD.search(figure.get("label", ""))
            and figure.get("value", "").strip()
            # A label repeating the value ("1,656 households: 1,656") names nothing new.
            and not extract_figures(figure["label"]) & extract_figures(figure["value"])
            and find_ungrounded_figures(figure["value"], summary_figures)
            and not find_ungrounded_figures(figure["value"], page_figures)
        ]
        if not missing:
            return summary
        return f"{summary.rstrip()}\nKey figures: {'; '.join(missing)}.".strip()

    @staticmethod
    def find_figure_issues(text: str, source_figures: set[float], source_contexts: list[FigureContext]) -> list[str]:
        return [
            *(f"{figure} is not in the page summaries" for figure in find_ungrounded_figures(text, source_figures)),
            *find_mislabeled_figures(text, source_contexts),
        ]

    def generate_doc_summary(self, page_summaries: list[str]) -> dict[str, Any]:
        """Run the doc-summary LLM call, retrying on failure or on invented/mislabeled figures.

        The call is the single point of failure for the whole document summary, so a
        transient error (e.g. a gateway timeout while the Ollama server is busy) must
        not fail it outright. Every figure in the result must also appear in the page
        summaries: the combine model has been seen to mangle correct page figures
        (e.g. "500 families" -> "50,000 families", "300+" -> "30,000+") or invent
        per-item values from a range. It must also keep the figure's label (people vs
        households, affected vs assisted). Such a result is retried with the issues fed
        back; if every attempt has issues, the best one is kept with those sentences
        removed. Raises the last error if no attempt produced a result.
        """
        source_text = "\n".join(page_summaries)
        source_figures = extract_figures(source_text)
        source_contexts = figure_contexts(source_text)
        max_paragraphs = doc_summary_max_paragraphs(len(page_summaries))
        schema = get_doc_summary_schema(max_paragraphs)
        doc_summary_prompt = get_doc_summary_prompt(page_summaries=page_summaries)
        # Size the context window to the actual prompt rather than a fixed value, since it
        # concatenates every page's summary (see estimate_doc_summary_context_window).
        # (Ollama-only; ignored by handlers whose backend sizes context from the model itself.)
        context_window = self.estimate_doc_summary_context_window(doc_summary_prompt)
        best: dict[str, Any] | None = None
        # Fewest figure issues first, then the most figures overall (the richest
        # summary), since the offending sentences are dropped from whichever is kept.
        best_rank: tuple[int, int] = (0, 0)
        issues: list[str] = []
        for attempt in range(1, self.MAX_PAGE_ATTEMPTS + 1):
            try:
                result = self.llm_handler.generate_structured(
                    self.doc_summary_chat_model,
                    get_doc_summary_prompt(page_summaries=page_summaries, previous_errors=issues),
                    schema,
                    context_window=context_window,
                    is_retry=attempt > 1,
                )
            except Exception:
                if attempt == self.MAX_PAGE_ATTEMPTS and best is None:
                    raise
                logger.warning("Doc summary attempt %s/%s failed", attempt, self.MAX_PAGE_ATTEMPTS, exc_info=True)
            else:
                summary_text = self.doc_summary_text_for_check(result)
                issues = self.find_figure_issues(summary_text, source_figures, source_contexts)
                if not issues:
                    return result
                logger.warning(
                    "Doc summary attempt %s/%s has figure issues: %s",
                    attempt,
                    self.MAX_PAGE_ATTEMPTS,
                    issues,
                )
                rank = (len(issues), -len(extract_figures(summary_text)))
                if best is None or rank < best_rank:
                    best, best_rank = result, rank
            if attempt < self.MAX_PAGE_ATTEMPTS:
                time.sleep(self.PAGE_RETRY_DELAY_SECONDS)
        if best is None:  # unreachable: the last failed attempt re-raises when best is None
            raise RuntimeError("Doc summary produced no result")
        return self.drop_ungrounded_sentences(best, source_figures, source_contexts)

    @staticmethod
    def doc_summary_text_for_check(doc_summary_json: dict[str, Any]) -> str:
        return "\n".join(
            [
                *(doc_summary_json.get("paragraphs") or []),
                doc_summary_json.get("doc_summary_short") or "",
                *((section.get("content") or "") for section in doc_summary_json.get("sections") or []),
            ],
        )

    @classmethod
    def drop_ungrounded_sentences(
        cls,
        doc_summary_json: dict[str, Any],
        source_figures: set[float],
        source_contexts: list[FigureContext] | None = None,
    ) -> dict[str, Any]:
        """Remove every sentence that carries a figure not found in, or mislabeled against, the page summaries."""

        def clean(text: str) -> str:
            kept = []
            for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
                if cls.find_figure_issues(sentence, source_figures, source_contexts or []):
                    logger.warning("Dropping doc summary sentence with figure issues: %s", sentence)
                else:
                    kept.append(sentence)
            return " ".join(kept)

        sections = [
            {**section, "content": clean(section.get("content") or "")} for section in doc_summary_json.get("sections") or []
        ]
        return {
            **doc_summary_json,
            "paragraphs": [p for p in (clean(p) for p in doc_summary_json.get("paragraphs") or []) if p],
            "doc_summary_short": clean(doc_summary_json.get("doc_summary_short") or ""),
            "sections": [section for section in sections if section["content"]],
        }

    def normalize_doc_summary_sections(self, doc_summary_json: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Validate/label the LLM's topical sections, with the short summary as one of them."""
        topic_labels = {slug: label for slug, label, _ in DOC_SUMMARY_TOPICS}
        entries: list[tuple[str, str, str]] = []

        doc_summary_short = doc_summary_json.get("doc_summary_short")
        if doc_summary_short and doc_summary_short.strip():
            entries.append(("doc_summary_short", "Document Summary Short", doc_summary_short))

        for section in doc_summary_json.get("sections") or []:
            slug = section.get("topic")
            content = section.get("content")
            if not slug or not content or not content.strip() or slug not in topic_labels:
                continue
            entries.append((slug, topic_labels[slug], content))

        return entries

    def handle_doc_summary_sections(self, entries: list[tuple[str, str, str]]):
        """Store all topical sections of the doc summary (and its short summary) as one chunk.

        Each section keeps its own embedding in `section_embeddings`, so a query can
        match a single topic (e.g. "impacts recorded") without diluting the signal
        against unrelated content from other topics, while still living in a single
        row per document rather than one row per topic.
        """
        if not entries:
            return
        section_embeddings = [
            {
                "topic": slug,
                "label": label,
                "content": content,
                "embedding": self.llm_embedding_model.embed_query(content),
            }
            for slug, label, content in entries
        ]
        DocumentExtraction.objects.create(
            report=self.report,
            status=DocumentExtractionStatus.SUCCESS,
            text="\n".join(f"{label}: {content}" for _, label, content in entries),
            page_number=None,
            chunk_type=DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SECTION,
            section_embeddings=section_embeddings,
        )

    def pdf_to_images(self, zoom: float = 1.1):
        page_summaries = []
        doc = fitz.open(stream=self.data, filetype="pdf")

        # Get the title and description
        self.handle_meta_info()
        # Doc Summary In Pending State
        doc_summary_obj = DocumentExtraction.objects.create(
            report=self.report,
            status=DocumentExtractionStatus.PENDING,
            text="",
            page_number=None,
            chunk_type=DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY,
            embedding=None,
        )

        for page_idx in range(len(doc)):
            logger.info("Processing Page %s", page_idx + 1)
            page = doc[page_idx]

            pic = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img_b64 = self.img_to_base64(data=pic)

            result = self.extract_page(page_idx=page_idx, img_b64=img_b64)
            if result is None:
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.FAILURE,
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.EXTRACTED_CONTENT,
                )
                continue

            if result.get("summary", "").strip():
                page_summaries.append(result["summary"])
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["summary"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.PAGE_SUMMARY,
                    embedding=self.llm_embedding_model.embed_query(result["summary"]),
                )

            if result.get("has_substantive_content") is False:
                # Cover/ToC/photo/blank/placeholder pages: their raw text (titles, chapter
                # lists, lorem ipsum) is not worth searching and lets content-free documents
                # surface for unrelated queries.
                continue

            if result.get("extracted_text"):
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["extracted_text"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.EXTRACTED_CONTENT,
                    embedding=self.llm_embedding_model.embed_query(result["extracted_text"]),
                )
            if result.get("key_findings"):
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["key_findings"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.KEYWORDS,
                    embedding=self.llm_embedding_model.embed_query(result["key_findings"]),
                )
            if result.get("tables"):
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["tables"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.TABLE,
                    embedding=self.llm_embedding_model.embed_query(json.dumps(result["tables"])),
                )
            if result.get("charts"):
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["charts"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.CHART,
                    embedding=self.llm_embedding_model.embed_query(json.dumps(result["charts"])),
                )

        if not page_summaries:
            # No page produced a summary (all pages failed or returned no content),
            # so there is nothing real to summarize.
            logger.warning("No page summaries extracted for report_id=%s; skipping doc summary.", self.report.pk)
            DocumentExtraction.objects.filter(pk=doc_summary_obj.pk).update(
                status=DocumentExtractionStatus.FAILURE,
            )
            return

        try:
            doc_summary_json = self.generate_doc_summary(page_summaries)
            doc_summary = "\n\n".join(
                paragraph.strip() for paragraph in doc_summary_json.get("paragraphs") or [] if paragraph.strip()
            )
            if not doc_summary:
                # The LLM judged the page summaries to have no substantive content
                # (placeholder/filler/nonsense text), so there is nothing to summarize.
                logger.warning("No meaningful content to summarize for report_id=%s.", self.report.pk)
                DocumentExtraction.objects.filter(pk=doc_summary_obj.pk).update(
                    status=DocumentExtractionStatus.FAILURE,
                )
                return
            DocumentExtraction.objects.filter(pk=doc_summary_obj.pk).update(
                status=DocumentExtractionStatus.SUCCESS,
                text=doc_summary,
                embedding=self.llm_embedding_model.embed_query(doc_summary),
            )
            self.handle_doc_summary_sections(self.normalize_doc_summary_sections(doc_summary_json))
        except Exception:
            logger.warning("Doc summary generation failed or returned malformed output.", exc_info=True)
            DocumentExtraction.objects.filter(pk=doc_summary_obj.pk).update(
                status=DocumentExtractionStatus.FAILURE,
            )


@dataclass
class HeaderExtraction(BaseExtraction):
    """Get the basic meta information extraction."""
