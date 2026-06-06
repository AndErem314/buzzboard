"""
Shared Ollama client for BuzzBoard LLM agents.

Handles the Ollama chat API with:
  - JSON mode for structured output
  - Retry with exponential backoff
  - Timeout handling
  - Graceful degradation when Ollama is unavailable
"""

from __future__ import annotations

import json
import time
from typing import Optional

import httpx


class OllamaClient:
    """
    Lightweight wrapper around Ollama's /api/chat endpoint.

    Usage:
        client = OllamaClient(model="llama3.1:8b")
        result = client.chat(
            system="You are a helpful assistant.",
            user="What is 2+2?",
        )
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        json_mode: bool = True,
    ) -> str:
        """
        Send a chat request and return the model's text response.

        Args:
            system: System prompt
            user: User message
            temperature: 0.0–1.0 (lower = more deterministic)
            json_mode: If True, request JSON output format

        Returns:
            The model's response text.

        Raises:
            ConnectionError: Ollama is not reachable
            RuntimeError: Model returned an error
        """
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if json_mode:
            payload["format"] = "json"

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                content = data["message"]["content"]

                # Clean up common JSON wrapping issues
                content = self._clean_json_response(content)
                return content

            except httpx.ConnectError as e:
                last_error = ConnectionError(
                    f"Cannot reach Ollama at {self.host}. "
                    f"Is it running? Run: ollama serve"
                )
            except httpx.HTTPStatusError as e:
                last_error = RuntimeError(
                    f"Ollama returned {e.response.status_code}: "
                    f"{e.response.text[:200]}"
                )
            except httpx.TimeoutException:
                last_error = TimeoutError(
                    f"Ollama did not respond within {self.timeout}s. "
                    f"Model '{self.model}' may be too large for available RAM."
                )
            except (KeyError, json.JSONDecodeError) as e:
                last_error = RuntimeError(
                    f"Unexpected Ollama response format: {e}"
                )

            if attempt < self.max_retries:
                wait = 2 ** attempt
                time.sleep(wait)

        raise last_error  # type: ignore[misc]

    @staticmethod
    def _clean_json_response(text: str) -> str:
        """Strip markdown fences and extract JSON from LLM output."""
        text = text.strip()

        # Remove ```json ... ``` fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Drop first line (```json or ```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Drop last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        return text.strip()

    def health_check(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            response = httpx.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
