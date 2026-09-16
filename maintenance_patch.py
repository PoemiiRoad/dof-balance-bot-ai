from pathlib import Path
import re


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


def sub_once(text, pattern, replacement, label, flags=0):
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 regex match, found {count}")
    return new_text


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = replace_once(main, 'BUILD_VERSION = "2026.09.15-claude-stream-180-v1"', 'BUILD_VERSION = "2026.09.16-robust-ai-v3"', "build version")
main = replace_once(main, 'AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "180"))', 'AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "300"))', "AI timeout")

# Historical day: a present but all-zero second shift is a legitimate completed shift.
main = sub_once(
    main,
    r'''\n    if incomplete_day is None and measured_days:\n        last_measured_day, _last_measured_date = max\(\n            measured_days, key=lambda item: item\[1\]\n        \)\n        last_shifts = all_valid_by_day\[last_measured_day\]\n\n        if \(\n            _shift_has_measurements\(last_shifts\.get\(1, \{\}\)\)\n            and not _shift_has_measurements\(last_shifts\.get\(2, \{\}\)\)\n        \):\n            incomplete_day = last_measured_day\n''',
    "\n",
    "historical zero second shift",
)

# Preserve missing measurements as NULL instead of silently manufacturing zero.
old_helpers = '''def _day_has_measurements(shifts: dict) -> bool:\n    return _shift_has_measurements(shifts.get(1, {})) or _shift_has_measurements(\n        shifts.get(2, {})\n    )\n'''
new_helpers = old_helpers + '''\n\ndef _completed_shift_value(shift_1: dict, shift_2: dict, field: str) -> float | None:\n    if field not in shift_1 or field not in shift_2:\n        return None\n    first = finite_number(shift_1[field], default=math.nan)\n    second = finite_number(shift_2[field], default=math.nan)\n    if not math.isfinite(first) or not math.isfinite(second):\n        return None\n    return first + second\n\n\ndef _single_shift_value(shift: dict, field: str) -> float | None:\n    if field not in shift:\n        return None\n    value = finite_number(shift[field], default=math.nan)\n    return value if math.isfinite(value) else None\n'''
main = replace_once(main, old_helpers, new_helpers, "missing helpers")
main = replace_once(
    main,
    '''            values = {\n                field: finite_number(shift_1.get(field))\n                + finite_number(shift_2.get(field))\n                for field in FIELDS\n            }''',
    '''            values = {\n                field: _completed_shift_value(shift_1, shift_2, field)\n                for field in FIELDS\n            }''',
    "daily NULL preservation",
)
main = replace_once(
    main,
    '**{field: finite_number(shift_1.get(field)) for field in FIELDS},',
    '**{field: _single_shift_value(shift_1, field) for field in FIELDS},',
    "night NULL preservation",
)
main = replace_once(
    main,
    '            "Для них будет использовано значение 0."',
    '            "Расчёты, которым нужны эти показания, будут недоступны; ноль вместо пропуска не подставляется."',
    "missing field warning",
)

# Missing data must remain unavailable in percentages, norms and duplicate checks.
old_pct = '''def pct(v: float, base: float) -> float:\n    value = finite_number(v)\n    denominator = finite_number(base)\n    return value / denominator * 100 if denominator else 0.0\n'''
new_pct = '''def pct(v: float | None, base: float | None) -> float | None:\n    if v is None or base is None:\n        return None\n    value = finite_number(v, default=math.nan)\n    denominator = finite_number(base, default=math.nan)\n    if not math.isfinite(value) or not math.isfinite(denominator) or denominator == 0:\n        return None\n    return value / denominator * 100\n\n\ndef pct_text(v: float | None, base: float | None, digits: int = 0) -> str:\n    value = pct(v, base)\n    return "—" if value is None else f"{value:.{digits}f}%"\n'''
main = replace_once(main, old_pct, new_pct, "pct semantics")
main = replace_once(
    main,
    '''def check_norm(val: float, base: float, key: str) -> tuple:\n    base = finite_number(base)\n    val = finite_number(val)\n    if not base or key not in NORMS:\n        return "none", 0.0\n    p = pct(val, base)\n    if val <= 0:\n        return "crit", p\n''',
    '''def check_norm(val: float | None, base: float | None, key: str) -> tuple:\n    if key not in NORMS:\n        return "none", None\n    p = pct(val, base)\n    if p is None:\n        return "none", None\n    value = finite_number(val, default=math.nan)\n    if not math.isfinite(value):\n        return "none", None\n    if value <= 0:\n        return "crit", p\n''',
    "norm semantics",
)
main = replace_once(
    main,
    '''def check_doubles(val_main: float, val_dup: float) -> tuple:\n    val_main = finite_number(val_main)\n    val_dup = finite_number(val_dup)\n    if not val_main and not val_dup:\n        return "none", 0.0, 0.0\n''',
    '''def check_doubles(val_main: float | None, val_dup: float | None) -> tuple:\n    if val_main is None or val_dup is None:\n        return "missing", None, None\n    val_main = finite_number(val_main)\n    val_dup = finite_number(val_dup)\n    if not val_main and not val_dup:\n        return "none", 0.0, 0.0\n''',
    "duplicate semantics",
)

# AI prompt is single-source; context carries data only.
main = replace_once(main, '    from balance_monitor import AI_RULES, analyze, record_date, render, calculate, SPECS', '    from balance_monitor import analyze, record_date, render, calculate, SPECS', "AI context import")
main = replace_once(main, '        lines = [AI_RULES, "ФАКТИЧЕСКИЕ СУТОЧНЫЕ ПОКАЗАНИЯ:"]', '        lines = ["ФАКТИЧЕСКИЕ СУТОЧНЫЕ ПОКАЗАНИЯ:"]', "AI context dedup")
main = replace_once(main, '        return AI_RULES + f"\\nРасчёт заблокирован: {exc}. Не делай выводов о балансе."', '        return f"Расчёт заблокирован: {exc}. Не делай выводов о балансе."', "AI context error dedup")

# Direct Agent SDK settings and lifecycle diagnostics; no monkey patch required.
main = replace_once(main, '        include_partial_messages=True,\n        env={', '        include_partial_messages=True,\n        effort="medium",\n        env={', "AI effort")
main = replace_once(
    main,
    '    prompt = f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\\n{question}\\n\\nДАННЫЕ ИЗ ОТЧЁТА:\\n{context}"\n',
    '    prompt = f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\\n{question}\\n\\nДАННЫЕ ИЗ ОТЧЁТА:\\n{context}"\n    logger.warning("AI SYSTEM_PROMPT chars=%s", len(SYSTEM_PROMPT))\n    logger.warning("AI context chars=%s", len(context))\n    logger.warning("AI total prompt chars=%s", len(prompt))\n',
    "prompt diagnostics",
)

# First real text timing directly in the stream loop.
main = replace_once(
    main,
    '    assistant_error: str | None = None\n\n    options = ClaudeAgentOptions(',
    '    assistant_error: str | None = None\n    loop = asyncio.get_running_loop()\n    started = loop.time()\n    first_text_s: float | None = None\n\n    options = ClaudeAgentOptions(',
    "stream timer init",
)
main = replace_once(
    main,
    '                    if chunk:\n                        stream_parts.append(chunk)',
    '                    if chunk:\n                        if first_text_s is None:\n                            first_text_s = loop.time() - started\n                            logger.warning("Claude first text_delta after %.1f s", first_text_s)\n                        stream_parts.append(chunk)',
    "first text log",
)
main = replace_once(
    main,
    '    logger.info("Claude Agent stream completed: %s text chunks", len(stream_parts))',
    '    logger.info("Claude Agent stream completed after %.1fs: %s text chunks", loop.time() - started, len(stream_parts))',
    "stream completion log",
)

# Display missing values to AI explicitly.
main = replace_once(
    main,
    '''def _ai_tonnage_line(data: dict) -> str:\n    return "; ".join(\n        f"{label}={finite_number(data.get(key)):.2f} т"\n        for label, key in AI_CONTEXT_FIELDS\n    )\n''',
    '''def _ai_tonnage_line(data: dict) -> str:\n    parts = []\n    for label, key in AI_CONTEXT_FIELDS:\n        raw = data.get(key)\n        if raw is None:\n            parts.append(f"{label}=нет показания")\n            continue\n        value = finite_number(raw, default=math.nan)\n        parts.append(f"{label}={value:.2f} т" if math.isfinite(value) else f"{label}=нет показания")\n    return "; ".join(parts)\n''',
    "AI missing display",
)

main_path.write_text(main, encoding="utf-8")

# Remove AI runtime hooks from the pure balance module and make missing input propagate.
logic_path = Path("balance_logic.py")
logic = logic_path.read_text(encoding="utf-8")
marker = logic.index("FIELDS = [")
logic = '''"""Чистая логика материального и скользящего баланса.\n\nМодуль не зависит от Telegram, базы данных или AI runtime.\n"""\n\nimport math\nimport re\nfrom collections.abc import Iterable, Mapping, Sequence\nfrom datetime import date, datetime, timedelta, timezone\nfrom itertools import pairwise\n\n\n''' + logic[marker:]
logic = logic.replace('        number = float(value or 0.0)', '        if value is None:\n            return None\n        number = float(value)')
logic = logic.replace('        return 0.0\n    return number if math.isfinite(number) else 0.0', '        return None\n    return number if math.isfinite(number) else None', 1)
for func in ("bal1", "bal2", "balc1", "balc2"):
    start = logic.index(f"def {func}(")
    end = logic.index("\n\ndef ", start + 5)
    block = logic[start:end]
    block = block.replace('    if not base:\n        return None', '    if base is None or not base:\n        return None')
    # A missing participating field invalidates the formula instead of being treated as zero.
    keys = {
        "bal1": ("kv102", "kv34", "kv24p", "kv24hv", "kv28a1"),
        "bal2": ("kv101", "kv33", "kv28a2"),
        "balc1": ("kv102", "kv24hv", "kv24p", "kv32", "kv28a1", "kv14"),
        "balc2": ("kv101", "kv31", "kv28a2", "kv15"),
    }[func]
    guard = '    if any(_number(data.get(key)) is None for key in ' + repr(keys) + '):\n        return None\n'
    insert_at = block.index('    result =')
    block = block[:insert_at] + guard + block[insert_at:]
    logic = logic[:start] + block + logic[end:]
logic_path.write_text(logic, encoding="utf-8")

# Fix dimensional wording in AI rules.
monitor_path = Path("balance_monitor.py")
monitor = monitor_path.read_text(encoding="utf-8")
monitor = monitor.replace('VERSION = "2026.09.16-ai-diagnostics-v4"', 'VERSION = "2026.09.16-ai-diagnostics-v5"')
monitor = replace_once(
    monitor,
    '''ДИАГНОСТИКА РАСХОЖДЕНИЯ Б1 И БС1:\nЕсли Б1 отклонён, а БС1 близок к нулю, сначала используй разность формул:\nБ1 − БС1 = (К34 − К32) − (К4 − К14).\n''',
    '''ДИАГНОСТИКА РАСХОЖДЕНИЯ Б И БС:\nНе смешивай тонны и проценты. Для первой очереди:\nΔБ1 − ΔБС1 = (К34 − К32) − (К4 − К14), единица — тонны.\nБ1% − БС1% = [(К34 − К32) − (К4 − К14)] / К4 × 100%.\nДля второй очереди:\nΔБ2 − ΔБС2 = (К33 − К31) − (К3 − К15), единица — тонны.\nБ2% − БС2% = [(К33 − К31) − (К3 − К15)] / К3 × 100%.\n''',
    "dimensional AI rule",
)
monitor_path.write_text(monitor, encoding="utf-8")

# Align stale tests and add regression checks.
db_test_path = Path("tests/test_database_windows.py")
db_test = db_test_path.read_text(encoding="utf-8").replace('self.assertIn(["📉 Просмотр проскальзывания"], labels)', 'self.assertIn(["📉 Скользящий баланс"], labels)')
db_test_path.write_text(db_test, encoding="utf-8")
helpers_path = Path("tests/test_helpers_and_alerts.py")
helpers = helpers_path.read_text(encoding="utf-8").replace('self.assertEqual(main.calc_produced(data), 50)', 'self.assertEqual(main.calc_produced(data), 50)')
helpers = helpers.replace('        context = main.make_ai_context(rows, rolling_rows)\n', '        context = main.make_ai_context(rows, rolling_rows)\n        from balance_monitor import AI_RULES\n        self.assertFalse(context.startswith(AI_RULES))\n', 1)
helpers_path.write_text(helpers, encoding="utf-8")

# Documentation and safety files.
readme_path = Path("README.md")
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace('рассчитывает скользящий баланс за последние 1, 2 и 3 завершённых суток;', 'рассчитывает скользящий баланс за последние 1, 3, 5 и 7 завершённых суток;')
readme = re.sub(r'## AI-ассистент\n.*?\n## Установка', '''## AI-ассистент\n\nСборка использует `claude-agent-sdk` и `CLAUDE_CODE_OAUTH_TOKEN`, полученный через\n`claude setup-token`. Отдельный `ANTHROPIC_API_KEY` для этого режима не нужен.\nAI работает только при ровно одном ID в `ALLOWED_USER_IDS`. Модель задаётся\n`AI_MODEL` (по умолчанию `sonnet`), лимит запроса — до 300 секунд.\n\nAI может ошибаться. Формулы, сохранение отчёта и алерты выполняются обычным кодом.\n\n## Установка''', readme, count=1, flags=re.S)
readme_path.write_text(readme, encoding="utf-8")

setup_path = Path("CLAUDE_PRO_SETUP.md")
setup = setup_path.read_text(encoding="utf-8").replace("Northflank", "Railway или другой хостинг").replace("AI_TIMEOUT_SECONDS=180", "AI_TIMEOUT_SECONDS=300").replace('`2026.09.15-claude-stream-180-v1`', '`2026.09.16-robust-ai-v3`')
setup_path.write_text(setup, encoding="utf-8")

Path(".gitignore").write_text(".env\n*.db\n*.db-wal\n*.db-shm\n__pycache__/\n*.py[cod]\n.venv/\nvenv/\n", encoding="utf-8")
Path(".env.example").write_text("BOT_TOKEN=\nCLAUDE_CODE_OAUTH_TOKEN=\nAI_MODEL=sonnet\nAI_TIMEOUT_SECONDS=300\nBOT_TIMEZONE=Asia/Qostanay\nDB_PATH=dof_balance.db\nMAX_REPORT_SIZE_MB=15\nMAX_XLSX_UNCOMPRESSED_MB=100\nALLOWED_USER_IDS=\n", encoding="utf-8")

print("maintenance patch applied")
