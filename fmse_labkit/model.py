"""Model access for the labs: an offline simulator by default, real providers optional.

Every lab runs completely offline against `SimulatedModel`, a deterministic
teaching simulator whose behaviour is documented in each lab. It is NOT a
language model and its outputs are not evidence about any real model — it exists
so the engineering exercises (validation, retries, evaluation, security
controls) can be run and graded reproducibly on a free runtime with no key.

To run the optional real-provider experiments, set in Colab Secrets (or env):
    FMSE_PROVIDER = gemini | openai | anthropic
    FMSE_MODEL    = the model id you want to test (check the provider's current docs)
    and the matching key: GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY

Model names and prices change faster than this course; none are hard-coded.
Keys travel only in request headers and are never printed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .secrets import get_secret, redact


def approx_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token). Real tokenizers differ; Module 4 measures this."""
    return max(1, (len(text or "") + 3) // 4)


@dataclass
class ModelResponse:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str
    provider: str
    meta: Dict[str, Any] = field(default_factory=dict)


class ModelError(RuntimeError):
    """A provider call failed. The message never contains credentials."""


class SimulatedModel:
    """Deterministic teaching simulator.

    `behavior(prompt, **kwargs) -> str` decides the output; labs supply their own
    documented behaviours. Latency is simulated from token counts so profiling
    exercises have something to measure; `speed` scales it.
    """

    provider = "simulator"

    def __init__(self, behavior: Optional[Callable[..., str]] = None, name: str = "fmse-sim", speed: float = 1.0,
                 ms_per_input_token: float = 0.05, ms_per_output_token: float = 2.0, base_ms: float = 40.0):
        self.behavior = behavior or (lambda prompt, **_: f"[simulated response to {approx_tokens(prompt)} input tokens]")
        self.name = name
        self.speed = speed
        self.ms_per_input_token = ms_per_input_token
        self.ms_per_output_token = ms_per_output_token
        self.base_ms = base_ms
        self.calls = 0

    def complete(self, prompt: str, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        text = self.behavior(prompt, **kwargs)
        tin, tout = approx_tokens(prompt), approx_tokens(text)
        latency = (self.base_ms + tin * self.ms_per_input_token + tout * self.ms_per_output_token) / self.speed
        return ModelResponse(text, tin, tout, round(latency, 1), self.name, self.provider, {"ttft_ms": round((self.base_ms + tin * self.ms_per_input_token) / self.speed, 1)})


class ProviderModel:
    """Minimal HTTP adapters for three providers' public REST APIs.

    Provider APIs are volatile (course maintenance class "provider API behavior");
    if a call starts failing, re-check the request shape against the provider's
    current documentation before assuming the lab is wrong."""

    def __init__(self, provider: str, model: str, api_key: str, timeout_s: float = 60.0):
        self.provider = provider
        self.name = model
        self._key = api_key
        self.timeout_s = timeout_s
        self.calls = 0

    def __repr__(self) -> str:  # never expose the key
        return f"ProviderModel(provider={self.provider!r}, model={self.name!r})"

    def _post(self, url: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            detail = redact(err.read().decode(errors="replace")[:300], [self._key])
            raise ModelError(f"{self.provider} returned HTTP {err.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise ModelError(f"{self.provider} unreachable: {type(err).__name__}") from None

    def complete(self, prompt: str, system: Optional[str] = None, max_output_tokens: int = 800, **_: Any) -> ModelResponse:
        self.calls += 1
        start = time.perf_counter()
        if self.provider == "gemini":
            body: Dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_output_tokens}}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            data = self._post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.name}:generateContent", {"x-goog-api-key": self._key}, body)
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            usage = data.get("usageMetadata", {})
            tin, tout = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
        elif self.provider == "openai":
            messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            data = self._post("https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {self._key}"}, {"model": self.name, "messages": messages, "max_completion_tokens": max_output_tokens})
            text = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage", {})
            tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
        elif self.provider == "anthropic":
            body = {"model": self.name, "max_tokens": max_output_tokens, "messages": [{"role": "user", "content": prompt}]}
            if system:
                body["system"] = system
            data = self._post("https://api.anthropic.com/v1/messages", {"x-api-key": self._key, "anthropic-version": "2023-06-01"}, body)
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            tin, tout = usage.get("input_tokens"), usage.get("output_tokens")
        else:
            raise ModelError(f"Unknown provider {self.provider!r}")
        latency = (time.perf_counter() - start) * 1000
        return ModelResponse(text, tin or approx_tokens(prompt), tout or approx_tokens(text), round(latency, 1), self.name, self.provider)


_KEY_NAMES = {"gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "openai": ("OPENAI_API_KEY",), "anthropic": ("ANTHROPIC_API_KEY",)}


def get_model(behavior: Optional[Callable[..., str]] = None, prefer_real: bool = True, **sim_kwargs: Any):
    """Return a real provider model if fully configured, else the simulator (with the lab's behaviour)."""
    provider = (get_secret("FMSE_PROVIDER") or "").strip().lower()
    model = (get_secret("FMSE_MODEL") or "").strip()
    if prefer_real and provider:
        if provider not in _KEY_NAMES:
            print(f"FMSE_PROVIDER={provider!r} is not supported (use gemini, openai or anthropic). Using the simulator.")
        elif not model:
            print("FMSE_PROVIDER is set but FMSE_MODEL is not. Set the model id you want to test. Using the simulator.")
        else:
            key = next((k for k in (get_secret(n) for n in _KEY_NAMES[provider]) if k), None)
            if key:
                print(f"Using real provider: {provider} / {model} (key found; value not shown).")
                return ProviderModel(provider, model, key)
            print(f"No key found for {provider}. Using the simulator.")
    return SimulatedModel(behavior, **sim_kwargs)


__all__ = ["ModelError", "ModelResponse", "ProviderModel", "SimulatedModel", "approx_tokens", "get_model"]
