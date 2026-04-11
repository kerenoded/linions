"""Bedrock Knowledge Base access for the orchestrator Lambda."""

from __future__ import annotations

from typing import Any


class BedrockKnowledgeBaseService:
    """Build Director RAG context from Bedrock Knowledge Base retrieval."""

    def __init__(self, client: Any, knowledge_base_id: str) -> None:
        """Initialise the KB service with a retrieval client and KB id."""
        self._client = client
        self._knowledge_base_id = knowledge_base_id

    def build_rag_context(self, prompt: str) -> str:
        """Retrieve and merge behavior and tone context for the Director agent."""
        behavior = self._retrieve_text(query=prompt, max_results=5)
        tone = self._retrieve_text(query=self._extract_tone_hint(prompt), max_results=3)
        return f"Behavior context:\n{behavior}\n\nTone/style context:\n{tone}"

    def _retrieve_text(self, *, query: str, max_results: int) -> str:
        """Run one Bedrock KB retrieve call and flatten text snippets."""
        response = self._client.retrieve(
            knowledgeBaseId=self._knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": max_results}},
        )
        texts: list[str] = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {})
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        return "\n".join(texts)

    def _extract_tone_hint(self, prompt: str) -> str:
        """Derive a lightweight tone query from the user prompt."""
        lowered = prompt.lower()
        if any(token in lowered for token in ("scary", "afraid", "fear", "dark")):
            return "worried"
        if any(token in lowered for token in ("happy", "joy", "celebrate", "fun")):
            return "delight"
        if any(token in lowered for token in ("mystery", "strange", "curious")):
            return "curious"
        return "tone all ages comedy warm ending"
