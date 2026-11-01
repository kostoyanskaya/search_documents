from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
from dataclasses import dataclass, field

import duckdb
import numpy as np

from app.core.config import get_settings

from .file_processing import RawTable
from .text_utils import clean_for_prompt, tokenize

logger = logging.getLogger(__name__)

_NULLISH = {
    "",
    "-",
    "—",
    "–",
    "n/a",
    "na",
    "nan",
    "null",
    "none",
    "нет",
    "н/д",
    "нд",
}
_CURRENCY = re.compile(
    r"[₽$€£¥%]|\b(руб|р|rub|usd|eur|тыс|млн|млрд)\.?(?=\s|$)",
    re.IGNORECASE,
)
_CYR = re.compile(r"[А-Яа-яЁё]")
_DATE_RES = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$"), (0, 1, 2)),
    (re.compile(r"^(\d{4})/(\d{2})/(\d{2})$"), (0, 1, 2)),
    (re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(?:\s.*)?$"), (2, 1, 0)),
]
_BLOCKED = re.compile(
    r"\b(read_\w+|glob|sniff_csv|query_table|query|copy|attach|detach|"
    r"pragma|install|load|getenv|export|import)\b",
    re.IGNORECASE,
)
_STRINGS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


class SQLValidationError(Exception):
    pass


class SQLExecutionError(Exception):
    pass


@dataclass
class ColMeta:
    name: str
    sql_type: str
    note: str = ""
    distinct: list[str] = field(default_factory=list)


@dataclass
class TableMeta:
    sql_name: str
    doc_id: str
    filename: str
    sheet: str
    columns: list[ColMeta]
    n_rows: int
    samples: list[list[str]]


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    tables: list[TableMeta]


def _parse_number(raw: str, decimal: str) -> float | None:
    s = raw.strip().replace("\u2212", "-")
    neg = s.startswith("(") and s.endswith(")")
    s = _CURRENCY.sub("", s.strip("()")).strip()
    s = re.sub(r"[\s\u00a0\u202f']", "", s)
    if not s or not re.fullmatch(r"[+-]?[\d.,]+", s):
        return None
    thousands = "," if decimal == "." else "."
    s = s.replace(thousands, "")
    if decimal == ",":
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if neg else value


def _detect_decimal(values: list[str], prefer_comma: bool) -> str:
    seen_dot_dec = seen_comma_dec = seen_comma_thou = seen_dot_thou = False
    for raw in values:
        s = re.sub(r"[\s\u00a0\u202f']", "", _CURRENCY.sub("", raw)).strip(
            "()+-\u2212"
        )
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                seen_comma_dec = True
            else:
                seen_dot_dec = True
        elif s.count(",") > 1:
            seen_comma_thou = True
        elif s.count(".") > 1:
            seen_dot_thou = True
        elif "," in s and len(s.split(",")[1]) != 3:
            seen_comma_dec = True
        elif "." in s and len(s.split(".")[1]) != 3:
            seen_dot_dec = True
    if seen_comma_dec and not seen_dot_dec:
        return ","
    if seen_dot_dec and not seen_comma_dec:
        return "."
    if seen_comma_thou:
        return "."
    if seen_dot_thou:
        return ","
    return "," if prefer_comma else "."


def _parse_date(raw: str) -> dt.date | None:
    s = raw.strip()
    for rx, (yi, mi, di) in _DATE_RES:
        m = rx.match(s)
        if m:
            try:
                return dt.date(
                    int(m.group(yi + 1)),
                    int(m.group(mi + 1)),
                    int(m.group(di + 1)),
                )
            except ValueError:
                return None
    return None


def _infer_column(name: str, values: list[str], prefer_comma: bool):
    """-> (sql_type, numpy array for staging, note)."""
    non_null = [v for v in values if v.strip().lower() not in _NULLISH]
    n = len(values)
    if non_null:
        if any(
            re.fullmatch(r"0\d+", v.strip()) or len(re.sub(r"\D", "", v)) > 15
            for v in non_null
        ):
            return "VARCHAR", np.array(values, dtype=object), ""
        dates = [_parse_date(v) for v in non_null]
        if sum(d is not None for d in dates) >= 0.95 * len(non_null):
            arr = np.full(n, np.datetime64("NaT"), dtype="datetime64[us]")
            for i, v in enumerate(values):
                d = (
                    _parse_date(v)
                    if v.strip().lower() not in _NULLISH
                    else None
                )
                if d is not None:
                    arr[i] = np.datetime64(d, "us")
            return "DATE", arr, ""
        decimal = _detect_decimal(non_null, prefer_comma)
        nums = [_parse_number(v, decimal) for v in non_null]
        if sum(x is not None for x in nums) >= 0.95 * len(non_null):
            arr = np.full(n, np.nan, dtype=float)
            for i, v in enumerate(values):
                if v.strip().lower() not in _NULLISH:
                    x = _parse_number(v, decimal)
                    if x is not None:
                        arr[i] = x
            note = (
                "values were written with % (12.5 means 12.5%)"
                if any("%" in v for v in non_null)
                else ""
            )
            return "DOUBLE", arr, note
    return "VARCHAR", np.array(values, dtype=object), ""


class _DB:
    def __init__(self) -> None:
        s = get_settings()
        self.conn = duckdb.connect(
            ":memory:",
            config={
                "memory_limit": f"{s.sql_memory_mb}MB",
                "threads": 1,
                "enable_external_access": False,
                "lock_configuration": True,
            },
        )
        self.lock = threading.RLock()
        self.tables: dict[str, TableMeta] = {}
        self.counter = 0
        self.cells = 0


_dbs: dict[str, _DB] = {}
_global_lock = threading.Lock()
_total_cells = 0


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def add_tables(
    session_id: str, doc_id: str, filename: str, raw_tables: list[RawTable]
) -> int:
    """Load tables of one document. Returns the number of tables registered."""
    global _total_cells
    s = get_settings()
    added = 0
    for raw in raw_tables:
        cells = len(raw.rows) * len(raw.header)
        with _global_lock:
            if _total_cells + cells > s.max_total_table_cells:
                logger.warning("table cell budget exhausted; table skipped")
                continue
            _total_cells += cells
            db = _dbs.setdefault(session_id, _DB())
        try:
            _load_one(db, doc_id, filename, raw, cells)
            added += 1
        except Exception:
            logger.exception("table load failed")
            with _global_lock:
                _total_cells -= cells
    return added


def _load_one(
    db: _DB, doc_id: str, filename: str, raw: RawTable, cells: int
) -> None:
    columns = (
        list(zip(*raw.rows, strict=False))
        if raw.rows
        else [() for _ in raw.header]
    )
    sample_text = (
        " ".join(raw.header)
        + " "
        + " ".join(c for col in columns[:6] for c in col[:50])
    )
    prefer_comma = bool(_CYR.search(sample_text))
    cols: list[ColMeta] = []
    staged: dict[str, np.ndarray] = {}
    select_parts = []
    for i, (name, col) in enumerate(zip(raw.header, columns, strict=False)):
        values = list(col)
        sql_type, arr, note = _infer_column(name, values, prefer_comma)
        key = f"c{i}"
        staged[key] = arr
        if sql_type == "DOUBLE":
            select_parts.append(
                f"CASE WHEN isnan({key}) THEN NULL ELSE {key} END "
                f"AS {_qi(name)}"
            )
        elif sql_type == "DATE":
            select_parts.append(f"CAST({key} AS DATE) AS {_qi(name)}")
        else:
            select_parts.append(f"NULLIF(TRIM({key}), '') AS {_qi(name)}")
        distinct: list[str] = []
        if sql_type == "VARCHAR":
            uniq = {v.strip() for v in values if v.strip()}
            if 0 < len(uniq) <= 12:
                distinct = sorted(uniq)
        cols.append(ColMeta(name, sql_type, note, distinct))
    with db.lock:
        db.counter += 1
        sql_name = f"t{db.counter}"
        db.conn.register("stage", staged)
        try:
            create = (
                f"CREATE TABLE {sql_name} AS "
                f"SELECT {', '.join(select_parts)} FROM stage"
            )
            db.conn.execute(create)
        finally:
            db.conn.unregister("stage")
        db.cells += cells
        db.tables[sql_name] = TableMeta(
            sql_name,
            doc_id,
            filename,
            raw.name,
            cols,
            len(raw.rows),
            [list(r) for r in raw.rows[:3]],
        )


def remove_document(session_id: str, doc_id: str) -> None:
    global _total_cells
    db = _dbs.get(session_id)
    if db is None:
        return
    with db.lock:
        for name in [n for n, t in db.tables.items() if t.doc_id == doc_id]:
            meta = db.tables.pop(name)
            cells = meta.n_rows * len(meta.columns)
            try:
                db.conn.execute(f"DROP TABLE {name}")
            except Exception:
                logger.exception("drop table failed")
            with _global_lock:
                _total_cells = max(0, _total_cells - cells)


def remove_session(session_id: str) -> None:
    global _total_cells
    with _global_lock:
        db = _dbs.pop(session_id, None)
        if db is not None:
            _total_cells = max(0, _total_cells - db.cells)
    if db is not None:
        with db.lock:
            db.conn.close()


def tables_for(
    session_id: str, allowed_doc_ids: set[str] | None = None
) -> list[TableMeta]:
    db = _dbs.get(session_id)
    if db is None:
        return []
    with db.lock:
        return [
            t
            for t in db.tables.values()
            if allowed_doc_ids is None or t.doc_id in allowed_doc_ids
        ]


def has_tables(
    session_id: str, allowed_doc_ids: set[str] | None = None
) -> bool:
    return bool(tables_for(session_id, allowed_doc_ids))


def schema_prompt(tables: list[TableMeta]) -> str:
    lines = []
    for t in tables:
        file_name = clean_for_prompt(t.filename, 80)
        sheet = clean_for_prompt(t.sheet, 40)
        lines.append(
            f'Table {t.sql_name}: file "{file_name}", '
            f'sheet "{sheet}", {t.n_rows} rows'
        )
        for c in t.columns:
            extra = f"  -- {c.note}" if c.note else ""
            vals = ""
            if c.distinct:
                shown = ", ".join(clean_for_prompt(v, 30) for v in c.distinct)
                vals = f"  -- values: {shown}"
            name = _qi(clean_for_prompt(c.name, 60))
            lines.append(f"  {name} {c.sql_type}{extra}{vals}")
        for row in t.samples[:2]:
            lines.append(
                "  sample: " + " | ".join(clean_for_prompt(v, 40) for v in row)
            )
    return "\n".join(lines)


def schema_overlap(question: str, tables: list[TableMeta]) -> list[str]:
    vocab: set[str] = set()
    for t in tables:
        vocab.update(tokenize(f"{t.filename} {t.sheet}"))
        for c in t.columns:
            vocab.update(tokenize(c.name))
            for v in c.distinct:
                vocab.update(tokenize(v))
    q = {
        tok
        for tok in tokenize(question)
        if len(tok) >= 3 and not tok[0].isdigit()
    }
    return sorted(q & vocab)


def _validate(db: _DB, sql: str) -> str:
    if not sql or len(sql) > 4000:
        raise SQLValidationError("empty or too long")
    if _BLOCKED.search(_STRINGS.sub("''", sql)):
        raise SQLValidationError("forbidden function or keyword")
    try:
        parsed = json.loads(
            db.conn.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[
                0
            ]
        )
    except Exception as exc:
        raise SQLValidationError("could not parse the statement") from exc
    if parsed.get("error"):
        raise SQLValidationError(
            str(
                parsed.get("error_message", "only a single SELECT is allowed")
            )[:200]
        )
    statements = parsed.get("statements", [])
    if len(statements) != 1:
        raise SQLValidationError("exactly one statement is allowed")
    try:
        normalised = db.conn.execute(
            "SELECT json_deserialize_sql(?)", [json.dumps(parsed)]
        ).fetchone()[0]
    except Exception:
        return sql
    return str(normalised).strip().rstrip(";").strip() or sql


def _json_safe(v):
    if v is None or isinstance(v, (int, str, bool)):
        return v
    if isinstance(v, float):
        return None if v != v else v
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def execute(
    session_id: str, sql: str, allowed_doc_ids: set[str] | None = None
) -> QueryResult:
    s = get_settings()
    db = _dbs.get(session_id)
    if db is None:
        raise SQLExecutionError("no tables")
    sql = sql.strip().rstrip(";").strip()
    with db.lock:
        sql = _validate(db, sql)
        cur = db.conn.cursor()
        timer = threading.Timer(s.sql_timeout_s, cur.interrupt)
        timer.start()
        try:
            wrapped = (
                f"SELECT * FROM (\n{sql}\n) "
                f"AS _q LIMIT {s.sql_result_rows + 1}"
            )
            cur.execute(wrapped)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except duckdb.InterruptException as exc:
            raise SQLExecutionError("query timed out") from exc
        except duckdb.Error as exc:
            raise SQLExecutionError(str(exc).split("\n")[0][:300]) from exc
        finally:
            timer.cancel()
            cur.close()
        tables = [
            t
            for t in db.tables.values()
            if allowed_doc_ids is None or t.doc_id in allowed_doc_ids
        ]
    truncated = len(rows) > s.sql_result_rows
    rows = rows[: s.sql_result_rows]
    used = [t for t in tables if re.search(rf"\b{t.sql_name}\b", sql)]
    return QueryResult(
        columns,
        [[_json_safe(v) for v in r] for r in rows],
        len(rows),
        truncated,
        used,
    )
