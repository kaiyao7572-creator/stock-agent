"""
Cerebras API client (robust version).

- Uses only approved models
- Has automatic fallback
- Prevents invalid model usage
- Centralizes model control
"""

import logging
from typing import Optional, List

from cerebras.cloud.sdk import AsyncCerebras
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: Optional[AsyncCerebras] = None


# ✅ ONLY models your account ACTUALLY supports
# (based on your test output)
ALLOWED_MODELS: List[str] = [
    "gpt-oss-120b",
    "zai-glm-4.7"
]


def _get_client() -> AsyncCerebras:
    global _client
    if _client is None:
        if not settings.cerebras_api_key:
            raise RuntimeError("CEREBRAS_API_KEY is not set.")
        _client = AsyncCerebras(api_key=settings.cerebras_api_key)
    return _client


async def complete(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-oss-120b",
    max_tokens: int = 2048
) -> str:
    """
    Send a chat completion request to Cerebras with automatic fallback.
    """

    client = _get_client()

    # 🔥 enforce safe model selection
    if model not in ALLOWED_MODELS:
        logger.warning("Invalid model requested: %s. Switching to default.", model)
        model = "gpt-oss-120b"

    models_to_try = [model] + [m for m in ALLOWED_MODELS if m != model]

    last_error = None

    for m in models_to_try:
        try:
            logger.info("Using Cerebras model: %s", m)

            response = await client.chat.completions.create(
                model=m,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            return response.choices[0].message.content or ""

        except Exception as exc:
            logger.error("Model failed (%s): %s", m, exc)
            last_error = exc

    raise RuntimeError(f"All Cerebras models failed. Last error: {last_error}")