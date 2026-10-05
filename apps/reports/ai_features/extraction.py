import base64
import io
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import fitz  # pyright: ignore[reportMissingTypeStubs]
from django.conf import settings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from PIL import Image

from apps.reports.ai_features.llms import LLMHandler, get_chat_llm_handler, get_embedding_llm_handler
from apps.reports.ai_features.prompts import DOC_SUMMARY_SCHEMA, DOC_SUMMARY_TOPICS, PAGE_SCHEMA, get_doc_summary_prompt
from apps.reports.models import DocumentExtraction, DocumentExtractionStatus, Report

logger = logging.getLogger(__name__)


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

    # Doc-summary context window sizing. The prompt concatenates every page's summary,
    # so its input size scales with page count - a fixed window silently truncates
    # earlier page summaries out of the final document summary once the doc has enough
    # pages (or the page summaries are long enough). Estimate tokens from the prompt's
    # character count (~4 chars/token for English) and reserve headroom for the model's
    # own output (5-7 paragraphs + short summary + per-topic sections).
    DOC_SUMMARY_OUTPUT_TOKEN_BUDGET = 2048
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

        for attempt in range(1, self.MAX_PAGE_ATTEMPTS + 1):
            try:
                return self.llm_handler.generate_structured(self.llm_chat_model, [message], PAGE_SCHEMA)
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

            if result.get("summary"):
                page_summaries.append(result["summary"])
                DocumentExtraction.objects.create(
                    report=self.report,
                    status=DocumentExtractionStatus.SUCCESS,
                    text=result["summary"],
                    page_number=page_idx + 1,
                    chunk_type=DocumentExtraction.ExtractionType.PAGE_SUMMARY,
                    embedding=self.llm_embedding_model.embed_query(result["summary"]),
                )

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

        doc_summary_prompt = get_doc_summary_prompt(page_summaries=page_summaries)
        try:
            # Size the context window to the actual prompt rather than a fixed value,
            # since it concatenates every page's summary (see estimate_doc_summary_context_window).
            # (Ollama-only; ignored by handlers whose backend sizes context from the model itself.)
            doc_summary_json = self.llm_handler.generate_structured(
                self.doc_summary_chat_model,
                doc_summary_prompt,
                DOC_SUMMARY_SCHEMA,
                context_window=self.estimate_doc_summary_context_window(doc_summary_prompt),
            )
            DocumentExtraction.objects.filter(pk=doc_summary_obj.pk).update(
                status=DocumentExtractionStatus.SUCCESS,
                text=doc_summary_json["doc_summary"],
                embedding=self.llm_embedding_model.embed_query(doc_summary_json["doc_summary"]),
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
