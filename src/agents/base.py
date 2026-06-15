"""
Base agent class — all 5 PR Pilot agents inherit from this.
Provides Gemini API access, structured logging, and retry logic.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    AGENT_TIMEOUT_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_AGENT_RETRIES,
    MAX_PROMPT_SIZE_WARN_BYTES,
)

logger = structlog.get_logger(__name__)


@dataclass
class AgentResult:
    """Standardized output from any agent in the chain."""

    agent_name: str
    status: str  # "pass" | "fail" | "escalate" | "error"
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    patches: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""
    duration_seconds: float = 0.0


class BaseAgent(ABC):
    """Abstract base for all PR Pilot agents."""

    name: str = "base"

    
    async def _validate_and_retry(self, response_text: str, schema: dict, prompt_fn, context: dict) -> dict:
        """Validate LLM response against JSON schema. Retry once on failure."""
        import json as _json
        try:
            data = _json.loads(response_text)
        except _json.JSONDecodeError as e:
            self.logger.warning("agent_json_parse_failed", error=str(e), agent=self.name)
            # Retry once with explicit formatting instruction
            retry_prompt = prompt_fn(context) + "\n\nYour previous response was not valid JSON. Please respond with ONLY the JSON object, no markdown fences, no extra text."
            retry_response = await self._call_llm(retry_prompt)
            try:
                data = _json.loads(retry_response)
            except _json.JSONDecodeError:
                self.logger.error("agent_json_retry_failed", agent=self.name)
                return {"status": "error", "summary": f"Agent {self.name} failed to produce valid JSON after retry", "findings": []}
        
        # Validate against schema
        try:
            import jsonschema
            jsonschema.validate(data, schema)
        except ImportError:
            self.logger.warning("jsonschema_not_installed", agent=self.name)
        except jsonschema.ValidationError as e:
            self.logger.warning("agent_schema_validation_failed", error=str(e), agent=self.name)
            # Don't block on schema mismatch — log and proceed
        
        return data

    def __init__(self) -> None:
        self._model = None
        self.model_name = GEMINI_MODEL
        self.log = structlog.get_logger(self.name)
        self.system_prompt = self._build_system_prompt()

    @property
    def model(self):
        """Lazy-init Gemini model — only when actually making API calls."""
        if self._model is None:
            if not GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY not set — required by XPRIZE rules")

            # Works with both google-generativeai 0.8.x and google-genai
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)

            generation_config = {
                "temperature": 0.2,
                "max_output_tokens": 8192,
            }

            self._model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_prompt,
                generation_config=generation_config,
            )
        return self._model

    @abstractmethod
    def _build_system_prompt(self) -> str:
        """Each agent defines its own system prompt."""
        ...

    @retry(
        stop=stop_after_attempt(MAX_AGENT_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def _call_gemini(self, prompt: str, schema: dict | None = None) -> str:
        """Call Gemini API with structured output support."""
        start = time.monotonic()

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")

        # Warn if the prompt is approaching token limits (best-effort byte count).
        prompt_bytes = len(prompt.encode("utf-8"))
        if prompt_bytes > MAX_PROMPT_SIZE_WARN_BYTES:
            self.log.warning(
                "large_prompt",
                agent=self.name,
                prompt_bytes=prompt_bytes,
                limit=MAX_PROMPT_SIZE_WARN_BYTES,
            )

        import google.generativeai as genai

        # Reuse the cached model when no schema is needed; create a fresh one
        # when the schema changes the generation_config (the 0.8.x SDK does not
        # support per-request config overrides on a cached model).
        #
        # The API key is configured once in the model property (lazy-init). The
        # per-call import is a no-op when the module is already loaded.
        #
        # NOTE: All five current agents pass a schema, so the cached-model
        # fast-path below is not exercised in production. It exists for future
        # agents that may make schema-less calls (e.g. a quick pre-filter).
        if schema:
            generation_config = {
                "temperature": 0.2,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json",
                "response_schema": schema,
            }
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_prompt,
                generation_config=generation_config,
            )
        else:
            model = self.model  # cached from the lazy property

        loop = asyncio.get_running_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, model.generate_content, prompt),
            timeout=AGENT_TIMEOUT_SECONDS,
        )

        elapsed = time.monotonic() - start
        self.log.info("gemini_call", model=self.model_name, elapsed=round(elapsed, 2))

        if not response.text:
            raise RuntimeError("Empty Gemini response")

        return response.text

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Execute the agent's task. Called by the orchestration engine."""
        ...

    async def run(self, context: dict[str, Any]) -> AgentResult:
        """Public interface — wraps execute() with timing and error handling."""
        started = time.monotonic()
        self.log.info("agent_started", agent=self.name)
        try:
            result = await self.execute(context)
        except Exception as exc:
            self.log.error("agent_failed", agent=self.name, error=str(exc))
            result = AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Agent failed: {str(exc)}",
                metadata={"error": str(exc)},
            )
        result.duration_seconds = round(time.monotonic() - started, 2)
        result.completed_at = datetime.now(timezone.utc).isoformat()
        self.log.info(
            "agent_completed",
            agent=self.name,
            status=result.status,
            duration=result.duration_seconds,
        )
        return result
