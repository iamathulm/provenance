import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.conversations.models import Feedback
from tests.conversations.test_conversations_api import QUESTION, ask, use_llm
from tests.ingest.harness import Harness

ANSWER = "Land within 90 seconds and swap the pack [S1]."


async def test_feedback_rules(
    app: FastAPI, client: AsyncClient, harness: Harness, conversation: str, db: AsyncSession
) -> None:
    use_llm(app, harness, ANSWER)
    await ask(client, conversation, QUESTION)
    question, answer = (await client.get(f"{conversation}/messages")).json()
    url = f"{conversation}/messages/{answer['id']}/feedback"

    first = await client.put(url, json={"rating": "up"})
    second = await client.put(
        url, json={"rating": "down", "comment": "mail me at jane@example.com"}
    )
    on_question = await client.put(
        f"{conversation}/messages/{question['id']}/feedback", json={"rating": "up"}
    )
    unknown = await client.put(
        f"{conversation}/messages/{uuid.uuid4()}/feedback", json={"rating": "up"}
    )
    rows = (await db.scalars(select(Feedback))).all()
    listed = (await client.get(f"{conversation}/messages")).json()

    assert first.status_code == 200
    assert second.json()["rating"] == "down"
    assert [(r.rating, r.comment) for r in rows] == [("down", "mail me at [REDACTED:email]")]
    assert on_question.status_code == 422
    assert on_question.json()["error"]["code"] == "feedback_not_allowed"
    assert unknown.status_code == 404
    assert listed[1]["feedback"] == "down"


async def test_answers_store_latency_and_ttft(
    app: FastAPI, client: AsyncClient, harness: Harness, conversation: str
) -> None:
    use_llm(app, harness, ANSWER)

    final = (await ask(client, conversation, QUESTION))[-1][1]

    assert 0 < final["ttft_ms"] <= final["latency_ms"]
