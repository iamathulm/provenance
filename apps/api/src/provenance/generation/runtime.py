"""Assembles the LLM client from settings: Groq, optionally behind cassette record/replay."""

import httpx

from provenance.core.config import Settings
from provenance.generation.cassette import CassetteProvider
from provenance.generation.client import LLMClient, ProviderCallRecorder
from provenance.generation.limiter import ModelLimits, TokenLimiter
from provenance.generation.providers import GroqProvider, LLMProvider


def build_llm_client(
    settings: Settings, http: httpx.AsyncClient, recorder: ProviderCallRecorder
) -> LLMClient:
    key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    groq = GroqProvider(http, key, settings.llm_timeout_s)
    provider: LLMProvider = groq
    if settings.llm_cassettes == "replay":
        provider = CassetteProvider(settings.llm_cassette_dir, "replay")
    elif settings.llm_cassettes == "record":
        provider = CassetteProvider(settings.llm_cassette_dir, "record", groq)
    limits = ModelLimits(settings.model_requests_per_minute, settings.model_tokens_per_minute)
    return LLMClient(provider, TokenLimiter(limits, settings.llm_max_wait_s), recorder)
