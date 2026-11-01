import json
import re

from app.services.text_utils import clean_for_prompt

AGGREGATE_RE = re.compile(
    r"\b(sum|total|average|avg|mean|median|count|how many|number of|"
    r"maxim\w*|minim\w*|highest|lowest|biggest|"
    r"largest|smallest|top \d+|"
    r"per (month|year|region|city|category)|"
    r"by (month|year|region|city|category)|"
    r"percent\w*|growth|share of|overall)\b"
    r"|(?<!\w)(сумм\w*|итог\w*|всего|общ\w*|в целом|средн\w*|"
    r"медиан\w*|сколько|количеств\w*|числ\w*|"
    r"максимальн\w*|минимальн\w*|"
    r"наибольш\w*|наименьш\w*|самы[йе]\w* (больш|мал|высок|низк)\w*|"
    r"топ[ -]?\d*|по (месяц|год|регион|город|категори)\w*|"
    r"доля|доли|процент\w*|рост\w*|динамик\w*)(?!\w)",
    re.IGNORECASE,
)


def parse_json_object(raw: str) -> dict | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    start, end = text.find("{"), text.rfind("}") + 1
    for candidate in (text, text[start:end]):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def data_block(tag: str, nonce: str, content: str, **attrs: str) -> str:
    """Wrap untrusted text in per-request random tags that the content
    cannot forge."""
    attr_text = "".join(
        f' {k}="{clean_for_prompt(v)}"' for k, v in attrs.items()
    )
    return f"<{tag}-{nonce}{attr_text}>\n{content}\n</{tag}-{nonce}>"


def unique_nonempty(items: list[str], limit: int = 400) -> list[str]:
    out: list[str] = []
    for item in items:
        item = re.sub(r"\s+", " ", item or "").strip()[:limit]
        if item and item.lower() not in {o.lower() for o in out}:
            out.append(item)
    return out
