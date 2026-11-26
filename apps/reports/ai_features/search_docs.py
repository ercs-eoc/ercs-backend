import math
import re
import typing
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib.postgres.search import SearchQuery
from django.db import connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import F, Func, IntegerField, Sum, TextField, Value
from django.db.models.functions import Greatest
from django.db.models.sql.compiler import SQLCompiler
from langchain_core.embeddings import Embeddings
from pgvector.django import CosineDistance

from apps.reports.ai_features.llms import get_embedding_llm_handler
from apps.reports.models import DocumentExtraction, DocumentExtractionStatus, Report

# Per-part trust levels: how reliable a chunk type is as a relevance signal, not how
# much text it tends to contain. Parts written or curated by a person (title,
# description, summaries) are trusted more than raw machine-extracted text, which
# carries boilerplate, headers/footers, and passing mentions indistinguishable from
# genuine "aboutness". These are reasoned starting points, not measurements against
# this specific corpus - revisit once a real query/relevance eval set exists.
WEIGHTS: dict[int, float] = {
    DocumentExtraction.ExtractionType.TITLE: 1.00,
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY: 0.8,
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SHORT: 0.98,
    # Topical slices of the doc summary (overview, impacts, etc.) - as trustworthy
    # as the summary they were split from, since they carry the same curated content.
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SECTION: 0.8,
    DocumentExtraction.ExtractionType.PAGE_SUMMARY: 0.80,
    DocumentExtraction.ExtractionType.DESCRIPTION: 0.80,
    DocumentExtraction.ExtractionType.KEYWORDS: 0.70,
    DocumentExtraction.ExtractionType.TABLE: 0.45,
    DocumentExtraction.ExtractionType.EXTRACTED_CONTENT: 0.45,
    DocumentExtraction.ExtractionType.CHART: 0.45,
}
DEFAULT_CHUNK_WEIGHT = 0.5

# Queries of at most this many words are ranked keyword-first (report-level BM25):
# a few-word query's cosine similarity against sentence/paragraph chunks is nearly
# flat across reports (verified on IFRC docs: an unrelated "operating systems" guide
# scored 0.23 vs 0.26-0.36 for true matches, and outscored them for "displacement"),
# while term frequency/rarity cleanly separates reports that are about the term.
KEYWORD_FIRST_TOKEN_LIMIT = 4

# BM25 parameters (standard defaults): term-frequency saturation and length normalization.
BM25_K1 = 1.2
BM25_B = 0.75
# Field boosts for BM25 term frequency: a hit in a title/summary says more about what
# the report is about than a passing mention in raw page text.
KEYWORD_FIELD_BOOSTS: dict[int, float] = {
    DocumentExtraction.ExtractionType.TITLE: 3.0,
    DocumentExtraction.ExtractionType.DESCRIPTION: 2.0,
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SHORT: 2.0,
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY: 1.5,
    DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SECTION: 1.5,
    DocumentExtraction.ExtractionType.KEYWORDS: 1.5,
}
KEYWORD_RELATIVE_CUTOFF = 0.85
# Semantic similarity only breaks ties among keyword matches for short queries.
KEYWORD_FIRST_SEMANTIC_WEIGHT = 0.2

# Longer queries: a report's "query coverage" is the share of the query's IDF mass (its
# distinctive words) that the report contains. Absolute cosine similarity can't tell an
# off-topic query from a real one (verified: "volcanic eruption and ash fall in Iceland"
# scored 0.635 against an IFRC report, above the 0.601 of a true match), but coverage
# can: on-topic queries reached 1.00, off-topic ones 0.17-0.53, because their
# distinctive words ("sourdough", "Iceland", "technology") appear in no report or only
# in passing. Paraphrased queries whose key word isn't used by any report (e.g. "prices
# soar") cover ~0.5-0.6 for every report alike - keywords can't tell those apart, so
# they return nothing rather than an arbitrary list.
MIN_QUERY_COVERAGE = 0.6
# A report must cover at least this fraction of the best report's coverage, so a report
# missing the query's most distinctive word (e.g. the place name) is left out.
COVERAGE_RELATIVE_CUTOFF = 0.8
# Reciprocal rank fusion constant (standard value): orders long-query results by their
# keyword and semantic ranks rather than by adding incomparable scores.
RRF_K = 60

# Prefix fallback: drop this many trailing characters of a term (keeping at least
# PREFIX_MIN_LENGTH), so word forms the stemmer doesn't unify still match each other,
# e.g. "volcano" (stem "volcano") vs "volcanic" (stem "volcan").
PREFIX_TRIM = 2
PREFIX_MIN_LENGTH = 4
PREFIX_MAX_EXPANSIONS = 20
# How many prefix-matching chunks to read corpus terms from.
PREFIX_MAX_CHUNKS = 200

# One `'lexeme':positions` entry of a tsvector's text form, e.g. `'flood':3A,17A`.
TSVECTOR_ENTRY = re.compile(r"'((?:[^']|'')*)'(?::(\S+))?")


class QueryTermPositions(Func):
    """A chunk's `search_vector` reduced to the given lexemes (with their positions), as text.

    Postgres has no "keep these lexemes" function, but stored vectors carry no weights:
    marking the query's lexemes with weight A and keeping only weight-A entries leaves
    exactly them, e.g. `'flood':3A,17A 'sudan':5A`.
    """

    def __init__(self, vector: F, lexemes: list[str]):
        super().__init__(vector, Value(lexemes), output_field=TextField())

    @typing.override
    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: typing.Any,
    ) -> tuple[str, tuple[typing.Any, ...]]:
        vector, lexemes = self.source_expressions
        vector_sql, vector_params = compiler.compile(vector)
        lexemes_sql, lexemes_params = compiler.compile(lexemes)
        sql = f"ts_filter(setweight({vector_sql}, 'A', {lexemes_sql}::text[]), '{{a}}')::text"
        return sql, (*vector_params, *lexemes_params)


def _parse_tsvector(text: str) -> dict[str, int]:
    """Lexeme -> occurrence count from a tsvector's text form."""
    return {
        lexeme.replace("''", "'"): len(positions.split(",")) if positions else 1
        for lexeme, positions in TSVECTOR_ENTRY.findall(text)
    }


def _any_term_query(lexemes: typing.Iterable[str], prefix: bool = False) -> SearchQuery:
    """Build a tsquery matching any of the (already stemmed) lexemes, optionally as prefixes."""
    suffix = ":*" if prefix else ""
    terms = " | ".join("'" + lexeme.replace("\\", "\\\\").replace("'", "''") + "'" + suffix for lexeme in lexemes)
    return SearchQuery(terms, search_type="raw", config="simple")


class Bm25Hit(typing.NamedTuple):
    score: float
    matched: frozenset[str]


class KeywordStats(typing.NamedTuple):
    hits: dict[int, Bm25Hit]
    # Lexeme -> IDF across reports; terms no report contains get the highest IDF.
    idfs: dict[str, float]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Cosine similarity clamped to [0, 1], mirroring the DB-side score from CosineDistance."""
    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))
    if not norm_a or not norm_b:
        return 0.0
    return max(dot_product / (norm_a * norm_b), 0.0)


@dataclass
class SearchReports:
    """Search and rank reports for a user query (keyword BM25 + semantic similarity)."""

    query: str
    llm_embedding_model: Embeddings = field(init=False)

    def __post_init__(self):
        self.llm_embedding_model = get_embedding_llm_handler().load_embedding_model()

    def is_keyword_first_query(self) -> bool:
        """Whether the query is short enough that semantic similarity is an unreliable signal."""
        return len(_normalize_text(self.query).split()) <= KEYWORD_FIRST_TOKEN_LIMIT

    def get_query_lexemes(self) -> list[str]:
        """Distinct stemmed, stopword-free terms of the query, as stored in `search_vector`."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT tsvector_to_array(to_tsvector('english', %s))", [self.query])
            return list(cursor.fetchone()[0])

    def get_keyword_stats(self, lexemes: list[str]) -> KeywordStats:
        """BM25 score per report over all of its chunks, plus each query term's IDF.

        Scores whole reports rather than chunks, so a report that keeps returning to a
        term outranks one that mentions it once; rare terms (e.g. a country) weigh more
        than ones in every IFRC report (e.g. "volunteers", "DREF").
        """
        if not lexemes:
            return KeywordStats({}, {})
        successful = DocumentExtraction.objects.filter(status=DocumentExtractionStatus.SUCCESS)

        # Term frequency per (report, term), boosted by the chunk it occurs in.
        term_frequency: defaultdict[int, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
        matches = (
            successful.filter(search_vector=_any_term_query(lexemes))
            .annotate(terms=QueryTermPositions(F("search_vector"), lexemes))
            .values_list("report_id", "chunk_type", "terms")
        )
        for report_id, chunk_type, terms in matches:
            boost = KEYWORD_FIELD_BOOSTS.get(chunk_type, 1.0)
            for term, count in _parse_tsvector(terms).items():
                term_frequency[report_id][term] += count * boost

        # Report length = number of distinct terms per chunk, summed over its chunks.
        lengths = dict(
            successful.values("report_id")
            .annotate(length=Sum(Func(F("search_vector"), function="length", output_field=IntegerField())))
            .values_list("report_id", "length"),
        )
        total_reports = len(lengths)
        average_length = sum(lengths.values()) / total_reports if total_reports else 1.0

        document_frequency = {term: sum(term in terms for terms in term_frequency.values()) for term in lexemes}
        idfs = {term: math.log(1 + (total_reports - df + 0.5) / (df + 0.5)) for term, df in document_frequency.items()}
        hits = {}
        for report_id, terms in term_frequency.items():
            length_norm = 1 - BM25_B + BM25_B * lengths.get(report_id, 0) / (average_length or 1.0)
            score = sum(idfs[term] * tf * (BM25_K1 + 1) / (tf + BM25_K1 * length_norm) for term, tf in terms.items())
            hits[report_id] = Bm25Hit(score, frozenset(terms))
        return KeywordStats(hits, idfs)

    def get_report_bm25_scores(self, lexemes: list[str]) -> dict[int, Bm25Hit]:
        """Report id -> BM25 score and which query terms it contains."""
        return self.get_keyword_stats(lexemes).hits

    def expand_lexemes_by_prefix(self, lexemes: list[str]) -> dict[str, frozenset[str]]:
        """Query term -> corpus terms starting with its (trimmed) prefix."""
        expanded = {}
        for lexeme in lexemes:
            prefix = lexeme[: max(PREFIX_MIN_LENGTH, len(lexeme) - PREFIX_TRIM)]
            vectors = DocumentExtraction.objects.filter(
                status=DocumentExtractionStatus.SUCCESS,
                search_vector=_any_term_query([prefix], prefix=True),
            ).values_list("search_vector", flat=True)[:PREFIX_MAX_CHUNKS]
            forms = {term for vector in vectors for term in _parse_tsvector(vector) if term.startswith(prefix)}
            expanded[lexeme] = frozenset(sorted(forms)[:PREFIX_MAX_EXPANSIONS])
        return expanded

    def get_prefix_bm25_scores(self, lexemes: list[str]) -> dict[int, Bm25Hit]:
        """BM25 over prefix-expanded terms, with matches reported as the original query terms."""
        expanded = self.expand_lexemes_by_prefix(lexemes)
        corpus_terms = sorted(set().union(*expanded.values()))
        return {
            report_id: Bm25Hit(hit.score, frozenset(term for term, forms in expanded.items() if forms & hit.matched))
            for report_id, hit in self.get_report_bm25_scores(corpus_terms).items()
        }

    def get_phrase_matched_report_ids(self) -> set[int]:
        """Reports with a chunk containing the query words in order, as a phrase."""
        return set(
            DocumentExtraction.objects.filter(
                status=DocumentExtractionStatus.SUCCESS,
                search_vector=SearchQuery(self.query, search_type="phrase", config="english"),
            )
            .values_list("report_id", flat=True)
            .distinct(),
        )

    def get_report_semantic_scores(self, report_ids: set[int]) -> dict[int, float]:
        """Report id -> best trust-weighted cosine similarity among its chunks."""
        query_vector = self.generate_query_embedding()
        chunk_scores = self.get_semantic_scores(query_vector)
        chunk_scores.update(self.get_section_semantic_scores(query_vector))
        best: dict[int, float] = {}
        chunks = DocumentExtraction.objects.filter(pk__in=chunk_scores, report_id__in=report_ids).values_list(
            "pk",
            "report_id",
            "chunk_type",
        )
        for pk, report_id, chunk_type in chunks:
            score = chunk_scores[pk] * WEIGHTS.get(chunk_type, DEFAULT_CHUNK_WEIGHT)
            best[report_id] = max(best.get(report_id, 0.0), score)
        return best

    def rank_keyword_first(self) -> list[tuple[int, float]] | None:
        """Rank reports for a short query by BM25, with semantic similarity as a tiebreaker.

        When no report contains any query term exactly, terms are retried as prefixes (so
        "volcano" finds "volcanic"). Candidates are matched strict-to-loose, taking the
        first tier with any match: the query as an exact phrase, then all of its terms
        anywhere in the report, then any term. So "South Sudan" doesn't match every
        report mentioning "south", and "operating system" doesn't match every IFRC report about an "operation" (stemmed
        alike) that also mentions a "system". Returns None when the query has no
        searchable terms (e.g. only stopwords).
        """
        lexemes = self.get_query_lexemes()
        if not lexemes:
            return None
        hits = self.get_report_bm25_scores(lexemes) or self.get_prefix_bm25_scores(lexemes)
        candidates = {rid: hit.score for rid, hit in hits.items() if len(hit.matched) == len(lexemes)}
        if not candidates:
            candidates = {rid: hit.score for rid, hit in hits.items()}
        if not candidates:
            return []

        if len(lexemes) > 1 and (phrase_matched := self.get_phrase_matched_report_ids() & set(candidates)):
            candidates = {rid: score for rid, score in candidates.items() if rid in phrase_matched}

        top_keyword = max(candidates.values())
        candidates = {rid: s for rid, s in candidates.items() if s >= KEYWORD_RELATIVE_CUTOFF * top_keyword}

        semantic = self.get_report_semantic_scores(set(candidates))
        top_semantic = max(semantic.values(), default=0.0) or 1.0
        ranked = [
            (
                report_id,
                (1 - KEYWORD_FIRST_SEMANTIC_WEIGHT) * score / top_keyword
                + KEYWORD_FIRST_SEMANTIC_WEIGHT * semantic.get(report_id, 0.0) / top_semantic,
            )
            for report_id, score in candidates.items()
        ]
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def generate_query_embedding(self) -> list[float]:
        """Return the vector of the query."""
        return self.llm_embedding_model.embed_query(self.query)

    def get_semantic_scores(self, query_vector: list[float], k_top: int = 100) -> dict[int, float]:
        """Return chunk id -> cosine similarity score for the top matching chunks."""
        results = (
            DocumentExtraction.objects.filter(status=DocumentExtractionStatus.SUCCESS)
            .filter(embedding__isnull=False)
            .annotate(
                # 1 - CosineDistance can go slightly negative (opposite-direction vectors);
                # clamp so it stays a valid [0, 1] similarity score.
                score=Greatest(
                    1 - CosineDistance("embedding", query_vector),
                    0.0,
                ),
            )
            .order_by("-score")[:k_top]
        )
        return {result.pk: result.score for result in results}  # type: ignore[attr-defined]

    def get_section_semantic_scores(self, query_vector: list[float], k_top: int = 100) -> dict[int, float]:
        """Return chunk id -> best cosine similarity across a doc-summary-section row's topics.

        DOCUMENT_SUMMARY_SECTION rows keep one embedding per topic (overview, impacts,
        short summary, etc.) in `section_embeddings` rather than the single indexed
        `embedding` column, so this comparison runs in Python instead of via pgvector's
        operator. A report matches through this row via whichever topic is most relevant,
        without diluting the signal against its other, unrelated topics.
        """
        rows = DocumentExtraction.objects.filter(
            status=DocumentExtractionStatus.SUCCESS,
            chunk_type=DocumentExtraction.ExtractionType.DOCUMENT_SUMMARY_SECTION,
        ).exclude(section_embeddings=[])

        scores: dict[int, float] = {}
        for row in rows:
            best_score = max(
                (_cosine_similarity(query_vector, section["embedding"]) for section in row.section_embeddings),
                default=0.0,
            )
            if best_score > 0:
                scores[row.pk] = best_score

        top_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:k_top]
        return dict(top_scores)

    def get_exact_title_report_ids(self) -> list[int]:
        """Known-item lookup: reports whose title is exactly the query (case/whitespace-insensitive)."""
        normalized_query = _normalize_text(self.query)
        candidates = Report.objects.filter(
            title__iexact=self.query.strip(),
            document_extractions__status=DocumentExtractionStatus.SUCCESS,
        ).distinct()
        return [report.pk for report in candidates if _normalize_text(report.title) == normalized_query]

    def rank_fused(self) -> list[tuple[int, float]]:
        """Rank reports for a longer query by fusing keyword (BM25) and semantic ranks.

        Off-topic guard: returns nothing when no report covers enough of the query's
        distinctive words (see MIN_QUERY_COVERAGE). Otherwise keeps reports with a strong
        keyword score that cover nearly as much of the query as the best report, ordered
        by reciprocal rank fusion of their BM25 and semantic ranks.
        """
        lexemes = self.get_query_lexemes()
        hits, idfs = self.get_keyword_stats(lexemes)
        if not hits:
            return []
        total_idf = sum(idfs.values()) or 1.0
        coverage = {rid: sum(idfs.get(term, 0.0) for term in hit.matched) / total_idf for rid, hit in hits.items()}
        top_coverage = max(coverage.values())
        if top_coverage < MIN_QUERY_COVERAGE:
            return []

        top_keyword = max(hit.score for hit in hits.values())
        candidates = {
            rid: hit.score
            for rid, hit in hits.items()
            if hit.score >= KEYWORD_RELATIVE_CUTOFF * top_keyword
            and coverage[rid] >= max(MIN_QUERY_COVERAGE, COVERAGE_RELATIVE_CUTOFF * top_coverage)
        }
        if not candidates:
            return []

        semantic = self.get_report_semantic_scores(set(candidates))
        keyword_rank = {rid: i for i, rid in enumerate(sorted(candidates, key=lambda r: -candidates[r]), start=1)}
        semantic_rank = {rid: i for i, rid in enumerate(sorted(candidates, key=lambda r: -semantic.get(r, 0.0)), start=1)}
        fused = [(rid, 1 / (RRF_K + keyword_rank[rid]) + 1 / (RRF_K + semantic_rank[rid])) for rid in candidates]
        # Ties (a report first on one signal, second on the other) go to the keyword leader.
        return sorted(fused, key=lambda item: (item[1], -keyword_rank[item[0]]), reverse=True)

    def rank_reports(self, top_k: int = 10) -> list[Report]:
        """Rank the reports.

        Exact title matches (known-item lookups) always come first; the rest are ranked
        keyword-first for short queries, by fused keyword/semantic rank otherwise.
        """
        exact_matches = self.get_exact_title_report_ids()
        ranked = (self.rank_keyword_first() if self.is_keyword_first_query() else self.rank_fused()) or []

        report_ids = list(dict.fromkeys([*exact_matches, *(report_id for report_id, _ in ranked)]))[:top_k]
        reports_by_id = Report.objects.in_bulk(report_ids)
        return [reports_by_id[report_id] for report_id in report_ids]
