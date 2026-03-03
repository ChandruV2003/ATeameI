from __future__ import annotations

import httpx


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self._base_url = base_url

    async def chat(self, model: str, prompt: str) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            resp = await client.post(
                "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": 0.2},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message") or {}
            return (message.get("content") or "").strip()

    async def embeddings(self, model: str, prompt: str) -> list[float]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            resp = await client.post(
                "/api/embeddings",
                json={"model": model, "prompt": prompt},
            )
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding")
            if not isinstance(emb, list):
                raise ValueError("ollama embeddings response missing 'embedding' list")
            return [float(x) for x in emb]
