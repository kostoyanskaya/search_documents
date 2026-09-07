from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import get_settings


_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}


@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    preset = _PROVIDER_PRESETS.get(settings.llm_provider.lower(), {})

    model = settings.llm_model or preset.get("model")
    base_url = settings.llm_base_url or preset.get("base_url")

    if not model or not base_url:
        raise RuntimeError(
            f"Unknown llm_provider '{settings.llm_provider}'. Either use a known "
            f"preset ({', '.join(_PROVIDER_PRESETS)}) or set llm_model and "
            "llm_base_url explicitly in .env."
        )

    return ChatOpenAI(
        model=model,
        api_key=settings.llm_api_key,
        base_url=base_url,
        temperature=0.1,
        max_tokens=1200,
    )