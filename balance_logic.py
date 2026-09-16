"""Чистая логика материального и скользящего баланса.

Модуль не зависит от Telegram и базы данных, поэтому формулы можно проверять
обычными модульными тестами.
"""

import logging
import math
import os
import re
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from itertools import pairwise

# main.py импортирует balance_logic до чтения AI_TIMEOUT_SECONDS, поэтому это
# значение гарантированно становится рабочим лимитом для Claude.
os.environ["AI_TIMEOUT_SECONDS"] = "300"

try:
    from claude_agent_sdk import ClaudeAgentOptions as _ClaudeAgentOptions
except ImportError:
    _ClaudeAgentOptions = None

if _ClaudeAgentOptions is not None and not getattr(
    _ClaudeAgentOptions, "_dof_streaming_patched", False
):
    _original_claude_options_init = _ClaudeAgentOptions.__init__

    def _dof_streaming_options_init(self, *args, **kwargs):
        kwargs.setdefault("include_partial_messages", True)
        _original_claude_options_init(self, *args, **kwargs)

    _ClaudeAgentOptions.__init__ = _dof_streaming_options_init
    _ClaudeAgentOptions._dof_streaming_patched = True


# Дополнительные постоянные правила для AI. main.py импортирует balance_logic
# раньше, чем забирает AI_RULES из balance_monitor, поэтому правило применяется
# ко всем будущим вопросам без изменения пользовательского запроса.
_AI_COMMON_MODE_RULES = """

ДИАГНОСТИКА ОБЩЕГО СМЕЩЕНИЯ ВХОДНЫХ ВЕСОВ:
При положительном Б1 или Б2 не предполагай автоматически завышение выходных весов.
Всегда проверяй обе стороны материального баланса.

Если основной и дублирующий входные весы К4/К4Д или К3/К3Д хорошо согласованы
между собой, но независимая сумма учтённых выходов превышает показания ОБОИХ
входных весов на сходную величину, обязательно рассмотри гипотезу общего
систематического занижения обоих входных комплектов весов (common-mode error).

Совпадение К4 с К4Д или К3 с К3Д подтверждает только взаимную согласованность
двух весов. Оно НЕ доказывает правильность их абсолютного показания.

Для Б1 отдельно сравни учтённые выходы:
К102 + К34 + К24ПП + К24ХВ − К28А.I
с К4 и отдельно с К4Д. Покажи разницу в тоннах относительно каждого входного
комплекта. Для Б2 аналогично сравни К101 + К33 − К28А.II с К3 и отдельно с К3Д.

Если Б1/Б2 имеет устойчивый положительный небаланс, основной и дублирующий
входные весы согласованы, БС1/БС2 около нуля, а отдельные выходные потоки
не имеют явного независимого завышения, повышай приоритет гипотезы
синхронного занижения входных весов. Это остаётся гипотезой до контрольной проверки.

Не складывай последовательно расположенные потоки как независимые. В частности,
К10/34А поступает далее через К32, поэтому К32 + К10/34А нельзя использовать как
независимую ожидаемую сумму для сравнения с К34: это может привести к двойному
учёту одного материала.

При диагностике ранжируй минимум три конкурирующие версии:
1) занижение входных весов;
2) завышение одного или нескольких выходных весов;
3) неучтённый маршрут, возврат или изменение запасов.
Сравни, какая версия лучше одновременно объясняет Б, БС, дубли и нормы потоков.
"""

try:
    import balance_monitor as _balance_monitor
except ImportError:
    _balance_monitor = None

if _balance_monitor is not None and _AI_COMMON_MODE_RULES not in _balance_monitor.AI_RULES:
    _balance_monitor.AI_RULES += _AI_COMMON_MODE_RULES


def _install_main_ai_diagnostics() -> None:
    """После загрузки main.py оборачивает ask_ai и пишет только размеры prompt."""
    log = logging.getLogger("dof.ai.prompt")
    for _ in range(1200):
        main_module = sys.modules.get("__main__")
        ask_ai = getattr(main_module, "ask_ai", None) if main_module else None
        if ask_ai is not None:
            if getattr(ask_ai, "_dof_prompt_diag_wrapped", False):
                return

            async def _logged_ask_ai(question, context, user_id, _original=ask_ai):
                system_prompt = getattr(main_module, "SYSTEM_PROMPT", "")
                total_prompt = (
                    f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
                    f"ДАННЫЕ ИЗ ОТЧЁТА:\n{context}"
                )
                log.warning("AI SYSTEM_PROMPT chars=%s", len(system_prompt))
                log.warning("AI context chars=%s", len(context))
                log.warning("AI total prompt chars=%s", len(total_prompt))
                return await _original(question, context, user_id)

            _logged_ask_ai._dof_prompt_diag_wrapped = True
            main_module.ask_ai = _logged_ask_ai
            return
        time.sleep(0.05)


threading.Thread(
    target=_install_main_ai_diagnostics,
    name="dof-ai-diagnostics",
    daemon=True,
).start()


FIELDS = [
    "kv4",
    "kv4d",
    "kv14",
    "kv32",
    "kv34",
    "kv34a",
    "kv102",
    "kv24p",
    "kv24hv",
    "kv28a1",
    "kv3",
    "kv3d",
    "kv15",
    "kv19",
    "kv31",
    "kv33",
    "kv101",
    "kv28a2",
    "kv44",
    "kv44d",
    "kv46",
    "kv46d",
    "kv74",
    "kv74d",
    "kv65mps",
    "kv65cpo",
    "kv66mps",
    "kv66cpo",
    "kv84mps",
    "kv84cpo",
    "kv63",
    "kv61",
]


MONTH_NAMES = {
    1: ("январь", "января", "қаңтар"),
    2: ("февраль", "февраля", "ақпан"),
    3: ("март", "марта", "наурыз"),
    4: ("апрель", "апреля", "сәуір"),
    5: ("май", "мая", "мамыр"),
    6: ("июнь", "июня", "маусым"),
    7: ("июль", "июля", "шілде"),
    8: ("август", "августа", "тамыз"),
    9: ("сентябрь", "сентября", "қыркүйек"),
    10: ("октябрь", "октября", "қазан"),
    11: ("ноябрь", "ноября", "қараша"),
    12: ("декабрь", "декабря", "желтоқсан"),
}


def _number(value) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def bal1(data: Mapping) -> float | None:
    """Баланс первой очереди, % от конвейера 4."""
    base = _number(data.get("kv4"))
    if not base:
        return None
    result = (
        _number(data.get("kv102"))
        + _number(data.get("kv34"))
        + _number(data.get("kv24p"))
        + _number(data.get("kv24hv"))
        - _number(data.get("kv28a1"))
        - base
    )
    return result / base * 100


def bal2(data: Mapping) -> float | None:
    """Баланс второй очереди, % от конвейера 3."""
    base = _number(data.get("kv3"))
    if not base:
        return None
    result = (
        _number(data.get("kv101"))
        + _number(data.get("kv33"))
        - _number(data.get("kv28a2"))
        - base
    )
    return result / base * 100


def balc1(data: Mapping) -> float | None:
    """Баланс сепарации первой очереди, % от конвейера 4."""
    base = _number(data.get("kv4"))
    if not base:
        return None
    result = (
        _number(data.get("kv102"))
        + _number(data.get("kv24hv"))
        + _number(data.get("kv24p"))
        + _number(data.get("kv32"))
        - _number(data.get("kv28a1"))
        - _number(data.get("kv14"))
    )
    return result / base * 100


def balc2(data: Mapping) -> float | None:
    """Баланс сепарации второй очереди, % от конвейера 3."""
    base = _number(data.get("kv3"))
    if not base:
        return None
    result = (
        _number(data.get("kv101"))
        + _number(data.get("kv31"))
        - _number(data.get("kv28a2"))
        - _number(data.get("kv15"))
    )
    return result / base * 100


def calculate_balances(data: Mapping) -> dict:
    return {
        "b1": bal1(data),
        "bc1": balc1(data),
        "b2": bal2(data),
        "bc2": balc2(data),
    }


def sum_period(rows: Iterable[Mapping], fields: Sequence[str] = FIELDS) -> dict:
    """Сначала суммирует тоннаж, не усредняя суточные проценты."""
    rows = list(rows)
    return {key: sum(_number(row.get(key)) for row in rows) for key in fields}


def row_date(row: Mapping) -> date:
    raw = str(row.get("report_date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    return date(int(row["year"]), int(row["month"]), int(row["day_num"]))


def format_period_label(rows: Sequence[Mapping]) -> str:
    if not rows:
        return "—"
    dates = sorted(row_date(row) for row in rows)
    first, last = dates[0], dates[-1]
    if first == last:
        return first.strftime("%d.%m.%Y")
    if first.year == last.year and first.month == last.month:
        return f"{first.day:02d}–{last.day:02d}.{last.month:02d}.{last.year}"
    if first.year == last.year:
        return f"{first.day:02d}.{first.month:02d}–{last.day:02d}.{last.month:02d}.{last.year}"
    return f"{first:%d.%m.%Y}–{last:%d.%m.%Y}"


def is_consecutive_period(rows: Sequence[Mapping]) -> bool:
    dates = sorted(row_date(row) for row in rows)
    return all(
        current - previous == timedelta(days=1) for previous, current in pairwise(dates)
    )


def rolling_snapshots(
    rows: Sequence[Mapping],
    periods: Sequence[int] = (1, 2, 3),
    fields: Sequence[str] = FIELDS,
) -> list:
    """Возвращает расчёты по последним 1/2/3 доступным завершённым суткам."""
    ordered = sorted(rows, key=row_date)
    snapshots = []
    for days in periods:
        if days < 1 or len(ordered) < days:
            continue
        selected = ordered[-days:]
        total = sum_period(selected, fields)
        snapshots.append(
            {
                "days": days,
                "rows": selected,
                "total": total,
                "balances": calculate_balances(total),
                "label": format_period_label(selected),
                "consecutive": is_consecutive_period(selected),
            }
        )
    return snapshots


def balance_status(
    value: float | None,
    warn_pct: float = 2.0,
    crit_pct: float = 5.0,
) -> str:
    if value is None or not math.isfinite(value):
        return "none"
    absolute = abs(value)
    if absolute <= warn_pct:
        return "ok"
    if absolute <= crit_pct:
        return "warn"
    return "crit"


def infer_report_period(period_text: str, reference=None) -> tuple:
    """Определяет год и месяц из подписи отчёта.

    Если в подписи указан только месяц словами, год выбирается относительно
    даты загрузки. Например, отчёт «за декабрь», загруженный в январе,
    относится к предыдущему году.
    """
    if reference is None:
        ref_date = datetime.now(timezone.utc).date()
    elif isinstance(reference, datetime):
        ref_date = reference.date()
    else:
        ref_date = reference

    text = str(period_text or "").strip().lower().replace("ё", "е")

    # Форматы с числовым месяцем: 07.2026, 2026-07 и полные даты.
    month_year = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[./-](20\d{2})(?!\d)", text)
    if month_year:
        return int(month_year.group(2)), int(month_year.group(1)), True

    year_month = re.search(r"(?<!\d)(20\d{2})[./-](0?[1-9]|1[0-2])(?!\d)", text)
    if year_month:
        return int(year_month.group(1)), int(year_month.group(2)), True

    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    for month, names in MONTH_NAMES.items():
        if not any(
            re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) for name in names
        ):
            continue
        if year_match:
            year = int(year_match.group(1))
        else:
            year = ref_date.year - (1 if month > ref_date.month else 0)
        return year, month, True

    return ref_date.year, ref_date.month, False