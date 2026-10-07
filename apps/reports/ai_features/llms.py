import json
import typing
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
from sentence_transformers import SentenceTransformer

from apps.reports.ai_features.prompts import PAGE_PROMPT

EMBEDDING_TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "mxbai-embed-large": ("Represent this sentence for searching relevant passages: ", ""),
}


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """OllamaEmbeddings that prepends the query/document task prefix a model requires, if any."""

    query_prefix: str = ""
    document_prefix: str = ""

    @typing.override
    def embed_query(self, text: str) -> list[float]:
        return super().embed_query(self.query_prefix + text)

    @typing.override
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return super().embed_documents([self.document_prefix + text for text in texts])


@dataclass
class LLMHandler:
    temperature: float = 0.0

    def construct_extraction_message(self, img_b64: str) -> HumanMessage:
        return HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": PAGE_PROMPT,
                },
                {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{img_b64}",
                },
            ],
        )

    def load_chat_model(self, model_name: str | None = None) -> BaseChatModel:
        """Load the chat model. `model_name` overrides the handler's configured default
        (used to run a different model for the text-only doc-summary combine step).
        """
        raise NotImplementedError

    def load_embedding_model(self) -> Embeddings:
        raise NotImplementedError

    def generate_structured(
        self,
        chat_model: BaseChatModel,
        messages: LanguageModelInput,
        schema: dict[str, Any],
        context_window: int | None = None,
    ) -> dict[str, Any]:
        """Invoke the chat model and return its response parsed against `schema`."""
        raise NotImplementedError


@dataclass
class OpenAIHandler(LLMHandler):
    """LLM inference using OpenAI."""

    def __init__(self):
        try:
            self.llm_model = ChatOpenAI(model=settings.LLM_MODEL_NAME, temperature=self.temperature)
        except Exception as e:
            raise Exception(f"OpenAI LLM model is not successfully loaded. {str(e)}") from e


@dataclass
class OllamaHandler(LLMHandler):
    """LLM Handler using Ollama."""

    @typing.override
    def load_chat_model(self, model_name: str | None = None) -> BaseChatModel:
        try:
            return ChatOllama(
                model=model_name or settings.LLM_MODEL_NAME,
                base_url=settings.LLM_OLLAMA_BASE_URL,
                temperature=self.temperature,
                # Explicitly disable "thinking" mode. Reasoning-capable models (e.g. the
                # qwen3 family) can otherwise burn the entire context window on a hidden
                # chain-of-thought before ever emitting the requested JSON, returning an
                # empty response. No effect on non-reasoning models (e.g. qwen2.5vl).
                reasoning=False,
                # Sized for a single page (prompt + one page's vision tokens + JSON output),
                # with headroom for pages that combine long extracted_text with large tables
                # and the up-to-500-word summary. The multi-page document summary call needs
                # a larger, size-dependent window and overrides this via
                # `options={"num_ctx": ...}` at call time.
                num_ctx=6144,
                client_kwargs={
                    "timeout": httpx.Timeout(
                        connect=30.0,
                        read=600.0,  # Allow up to 10 minutes for generation
                        write=300.0,
                        pool=30.0,
                    ),
                },
            )
        except Exception as e:
            raise Exception(f"Ollama LLM model is not successfully loaded. {str(e)}") from e

    @typing.override
    def load_embedding_model(self) -> Embeddings:
        model_name = settings.LLM_EMBEDDING_MODEL
        if not model_name:
            raise ValueError("LLM_EMBEDDING_MODEL is not set (required unless LLM_USE_SENTENCE_TRANSFORMERS=true).")
        try:
            # Model names may carry a tag, e.g. "nomic-embed-text:v1.5".
            base_model_name = model_name.split(":")[0]
            query_prefix, document_prefix = EMBEDDING_TASK_PREFIXES.get(base_model_name, ("", ""))
            return PrefixedOllamaEmbeddings(
                model=model_name,
                base_url=settings.LLM_OLLAMA_BASE_URL,
                query_prefix=query_prefix,
                document_prefix=document_prefix,
            )
        except Exception as e:
            raise Exception(f"Ollama LLM model is not successfully loaded. {str(e)}") from e

    @typing.override
    def generate_structured(
        self,
        chat_model: BaseChatModel,
        messages: LanguageModelInput,
        schema: dict[str, Any],
        context_window: int | None = None,
    ) -> dict[str, Any]:
        invoke_kwargs: dict[str, Any] = {"options": {"num_ctx": context_window}} if context_window else {}
        response = chat_model.invoke(messages, format=schema, **invoke_kwargs)
        if not isinstance(response.content, str):
            raise TypeError("Response content is not a string")
        return json.loads(response.content)


@dataclass
class OpenRouterHandler(LLMHandler):
    """LLM Handler using OpenRouter (chat completions only, no embeddings support)."""

    model_name: str = "test"
    max_tokens: int = 16384
    # Reasoning is opt-in: many OpenRouter models (e.g. gemma-3-12b-it) don't
    # support it, and the API may reject or ignore the field if sent regardless.
    reasoning: dict[str, Any] | None = None

    @typing.override
    def load_chat_model(self, model_name: str | None = None) -> BaseChatModel:
        try:
            reasoning_kwargs: dict[str, Any] = {"reasoning": self.reasoning} if self.reasoning else {}
            return ChatOpenRouter(
                model=model_name or settings.LLM_MODEL_NAME or self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=settings.OPENROUTER_API_KEY,
                **reasoning_kwargs,
            )
        except Exception as e:
            raise Exception(f"OpenRouter LLM model is not successfully loaded. {str(e)}") from e

    @typing.override
    def generate_structured(
        self,
        chat_model: BaseChatModel,
        messages: LanguageModelInput,
        schema: dict[str, Any],
        context_window: int | None = None,
    ) -> dict[str, Any]:
        # context_window has no OpenRouter equivalent to Ollama's num_ctx override;
        # the model's own context window applies.
        response = chat_model.with_structured_output(schema, method="json_schema").invoke(messages)
        if not isinstance(response, dict):
            raise TypeError("Response is not a dict")
        return response


class SentenceTransformerEmbeddings(Embeddings):
    """Embeddings backed directly by a local sentence-transformers model."""

    def __init__(self, model_name: str):
        self._model = SentenceTransformer(model_name)

    @typing.override
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts).tolist()

    @typing.override
    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()


@dataclass
class SentenceTransformerHandler(LLMHandler):
    """Embeddings-only handler using a local sentence-transformers model."""

    @typing.override
    def load_embedding_model(self) -> Embeddings:
        try:
            return SentenceTransformerEmbeddings(model_name=settings.SENTENCE_TRANSFORMER_MODEL_NAME)
        except Exception as e:
            raise Exception(f"Sentence-transformers embedding model is not successfully loaded. {str(e)}") from e


def get_chat_llm_handler() -> LLMHandler:
    """Return the handler to use for chat completions, per LLM_USE_OPENROUTER."""
    if settings.LLM_USE_OPENROUTER:
        return OpenRouterHandler()
    return OllamaHandler()


def get_embedding_llm_handler() -> LLMHandler:
    """Return the handler to use for embeddings, per LLM_USE_SENTENCE_TRANSFORMERS."""
    if settings.LLM_USE_SENTENCE_TRANSFORMERS:
        return SentenceTransformerHandler()
    return OllamaHandler()
