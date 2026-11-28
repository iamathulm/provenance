"""RAGAS faithfulness and answer relevancy as an `AnswerJudge`. The only module importing RAGAS.

RAGAS sends usage analytics unless told not to, so tracking is switched off before RAGAS is
imported. Judge calls go to an OpenAI-compatible endpoint (Gemini or Groq, see `judging.py`) and
are cached on disk, so re-running an evaluation costs no quota. Embeddings for answer relevancy
come from the same local FastEmbed model retrieval uses.
"""

import os

os.environ["RAGAS_DO_NOT_TRACK"] = "true"  # before any ragas import

from typing import Any

from openai import AsyncOpenAI
from ragas.cache import DiskCacheBackend
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import llm_factory
from ragas.metrics.collections import AnswerRelevancy, Faithfulness

from provenance.core.config import REPO_ROOT
from provenance.evaluation.judging import JudgeConfig, JudgeScores
from provenance.retrieval.embeddings import Embedder

CACHE_DIR = REPO_ROOT / ".cache" / "ragas"


# Without the eval group installed (CI type check) the base class is Any.
class FastEmbedRagasEmbedding(BaseRagasEmbedding):  # type: ignore[misc,unused-ignore]
    def __init__(self, embedder: Embedder) -> None:
        super().__init__()
        self._embedder = embedder

    def embed_text(self, text: str, **_: Any) -> list[float]:
        return self._embedder.embed_query_dense(text)

    async def aembed_text(self, text: str, **_: Any) -> list[float]:
        return self.embed_text(text)


class RagasJudge:
    def __init__(self, config: JudgeConfig, embedder: Embedder) -> None:
        client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=6)
        llm = llm_factory(config.model, client=client, cache=DiskCacheBackend(str(CACHE_DIR)))
        self.model = config.model
        self._faithfulness = Faithfulness(llm=llm)
        self._relevancy = AnswerRelevancy(
            llm=llm, embeddings=FastEmbedRagasEmbedding(embedder), strictness=1
        )

    async def score(self, question: str, answer: str, contexts: list[str]) -> JudgeScores:
        faithfulness = await self._safe(
            self._faithfulness.ascore(
                user_input=question, response=answer, retrieved_contexts=contexts
            )
        )
        relevancy = await self._safe(self._relevancy.ascore(user_input=question, response=answer))
        return JudgeScores(faithfulness, relevancy)

    @staticmethod
    async def _safe(pending: Any) -> float | None:
        """A judge failure leaves that score empty instead of failing the run."""
        try:
            result = await pending
        except Exception:  # judge errors (quota, malformed JSON) are reported as missing
            return None
        value = getattr(result, "value", result)
        return float(value) if value is not None else None
