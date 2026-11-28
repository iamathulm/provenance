"""Which model judges answers, and the judge interface. No RAGAS import here.

Gemini (`gemini-3.5-flash-lite`, free tier) is preferred when `GEMINI_API_KEY` is set: it keeps
judging out of the Groq budget the answers need, and a different model family from the one that
wrote the answers avoids self-preference. Without it the judge is `openai/gpt-oss-20b` on Groq.
Gemini is used only by the evaluation CLI; its free tier may use inputs to improve Google's
products, so it only ever sees the synthetic and CC-BY evaluation corpora.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from provenance.core.config import Settings


@dataclass(frozen=True)
class JudgeConfig:
    provider: Literal["gemini", "groq"]
    model: str
    base_url: str
    api_key: str


def judge_settings(settings: Settings) -> JudgeConfig | None:
    if settings.gemini_api_key is not None:
        return JudgeConfig(
            "gemini",
            settings.gemini_judge_model,
            settings.gemini_base_url,
            settings.gemini_api_key.get_secret_value(),
        )
    if settings.groq_api_key is not None:
        return JudgeConfig(
            "groq",
            settings.groq_judge_model,
            settings.groq_base_url,
            settings.groq_api_key.get_secret_value(),
        )
    return None


@dataclass(frozen=True)
class JudgeScores:
    faithfulness: float | None
    answer_relevancy: float | None


class AnswerJudge(Protocol):
    model: str

    async def score(self, question: str, answer: str, contexts: list[str]) -> JudgeScores: ...
