import re
import threading
import unicodedata
from functools import lru_cache

import snowballstemmer

_INVISIBLE = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f"), None
)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_])[-\u2010]\n(?=[a-zа-яё])")
_SPACES = re.compile(r"[ \t\u00a0\u2009\u202f]+")
_BLANKS = re.compile(r"\n{3,}")
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-z]")
_THOUSANDS = re.compile(r"(?<!\d)(\d{1,3})((?:[\u00a0\u202f ]\d{3})+)(?!\d)")
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """NFKC, strip invisible/control chars, repair PDF line-break
    hyphenation, tidy whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    text = _CTRL.sub(" ", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub("", text)
    text = "\n".join(
        _SPACES.sub(" ", line).strip() for line in text.split("\n")
    )
    return _BLANKS.sub("\n\n", text).strip()


def detect_language(text: str) -> str:
    """'ru' if Cyrillic letters dominate, otherwise 'en'."""
    return "ru" if len(_CYR.findall(text)) > len(_LAT.findall(text)) else "en"


_local = threading.local()


def _stemmers():
    if not hasattr(_local, "ru"):
        _local.ru = snowballstemmer.stemmer("russian")
        _local.en = snowballstemmer.stemmer("english")
    return _local.ru, _local.en


@lru_cache(maxsize=200_000)
def _stem(token: str) -> str:
    ru, en = _stemmers()
    if _CYR.search(token):
        return ru.stemWord(token)
    if token.isascii() and token.isalpha():
        return en.stemWord(token)
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, ё->е, merge '1 234,5' style numbers, stem ru/en words."""
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    text = _THOUSANDS.sub(
        lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), text
    )
    out: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok[0].isdigit():
            out.append(tok.replace(",", "."))
        elif len(tok) > 1:
            out.append(_stem(tok))
    return out


def clean_for_prompt(value: str, limit: int = 120) -> str:
    """Make an untrusted short string (e.g. a filename) safe to embed in
    a prompt."""
    value = _CTRL.sub(" ", value.translate(_INVISIBLE)).replace("\n", " ")
    value = re.sub(r"[<>`{}\[\]]", "", value)
    return value.strip()[:limit]


_INJECTION = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) "
    r"(instructions|rules)|disregard .{0,30}(instructions|rules)"
    r"|(reveal|show|print) .{0,30}(system|hidden) prompt"
    r"|you are now|new instructions?:"
    r"|игнорируй .{0,30}(инструкци|правил)"
    r"|забудь .{0,30}(инструкци|правил)"
    r"|системн\w+ промпт|ты теперь|новые инструкции",
    re.IGNORECASE,
)


def looks_like_injection(text: str) -> bool:
    """Heuristic flag (used for logging only; never the sole defence)."""
    return bool(_INJECTION.search(text))


def collapse_for_match(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", text).lower().replace("ё", "е"),
    ).strip()
