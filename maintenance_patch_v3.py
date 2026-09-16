from pathlib import Path
import runpy

runpy.run_path("maintenance_patch_v2.py", run_name="__maintenance_v2__")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


# Finish missing-data semantics in pure balance aggregation.
logic_path = Path("balance_logic.py")
logic = logic_path.read_text(encoding="utf-8")
logic = replace_once(
    logic,
    '''def sum_period(rows: Iterable[Mapping], fields: Sequence[str] = FIELDS) -> dict:\n    """Сначала суммирует тоннаж, не усредняя суточные проценты."""\n    rows = list(rows)\n    return {key: sum(_number(row.get(key)) for row in rows) for key in fields}\n''',
    '''def sum_period(rows: Iterable[Mapping], fields: Sequence[str] = FIELDS) -> dict:\n    """Суммирует тоннаж; пропуск хотя бы одного показания делает итог поля недоступным."""\n    rows = list(rows)\n    result = {}\n    for key in fields:\n        values = [_number(row.get(key)) for row in rows]\n        result[key] = None if any(value is None for value in values) else sum(values)\n    return result\n''',
    "sum_period missing propagation",
)
logic_path.write_text(logic, encoding="utf-8")

main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")

# Stock calculations must not manufacture zero for an absent report row.
main = replace_once(
    main,
    '''def calc_produced(d: dict) -> float:\n    """Произведено = (44+44Д)/2 + 46Д + (74+74Д)/2"""\n    avg44 = (finite_number(d.get("kv44")) + finite_number(d.get("kv44d"))) / 2\n    k46d = finite_number(d.get("kv46d"))\n    avg74 = (finite_number(d.get("kv74")) + finite_number(d.get("kv74d"))) / 2\n    return avg44 + k46d + avg74\n\n\ndef calc_shipped(d: dict) -> float:\n    """Отгружено = 65МПС+65ЦПО+66МПС+66ЦПО+84МПС+84ЦПО"""\n    keys = ["kv65mps", "kv65cpo", "kv66mps", "kv66cpo", "kv84mps", "kv84cpo"]\n    return sum(finite_number(d.get(key)) for key in keys)\n''',
    '''STOCK_PRODUCED_FIELDS = ("kv44", "kv44d", "kv46d", "kv74", "kv74d")\nSTOCK_SHIPPED_FIELDS = ("kv65mps", "kv65cpo", "kv66mps", "kv66cpo", "kv84mps", "kv84cpo")\n\n\ndef _stock_numbers(d: dict, keys: tuple[str, ...]) -> list[float] | None:\n    values = []\n    for key in keys:\n        raw = d.get(key)\n        if raw is None:\n            return None\n        value = finite_number(raw, default=math.nan)\n        if not math.isfinite(value):\n            return None\n        values.append(value)\n    return values\n\n\ndef calc_produced(d: dict) -> float | None:\n    """Произведено = (44+44Д)/2 + 46Д + (74+74Д)/2."""\n    values = _stock_numbers(d, STOCK_PRODUCED_FIELDS)\n    if values is None:\n        return None\n    kv44, kv44d, kv46d, kv74, kv74d = values\n    return (kv44 + kv44d) / 2 + kv46d + (kv74 + kv74d) / 2\n\n\ndef calc_shipped(d: dict) -> float | None:\n    """Отгружено = 65МПС+65ЦПО+66МПС+66ЦПО+84МПС+84ЦПО."""\n    values = _stock_numbers(d, STOCK_SHIPPED_FIELDS)\n    return None if values is None else sum(values)\n''',
    "stock strict missing data",
)
main = replace_once(
    main,
    '''            produced = calc_produced(fresh_data)\n            shipped = calc_shipped(fresh_data)\n            ves_izm = produced - shipped\n''',
    '''            produced = calc_produced(fresh_data)\n            shipped = calc_shipped(fresh_data)\n            if produced is None or shipped is None:\n                continue\n            ves_izm = produced - shipped\n''',
    "stock refresh guard",
)
main = replace_once(
    main,
    '''        data = dict(row)\n        produced = calc_produced(data)\n        shipped = calc_shipped(data)\n        ves_izm = produced - shipped\n''',
    '''        data = dict(row)\n        produced = calc_produced(data)\n        shipped = calc_shipped(data)\n        if produced is None or shipped is None:\n            raise ReportDataError(\n                "Недостаточно показаний весов для расчёта склада; пропуски не заменяются нулём."\n            )\n        ves_izm = produced - shipped\n''',
    "stock save guard",
)
main = replace_once(
    main,
    '''    row = rows[-1]\n    day_num = row["day_num"]\n''',
    '''    row = rows[-1]\n    if calc_produced(row) is None or calc_shipped(row) is None:\n        await msg.answer("⚠️ Для последнего дня не хватает показаний весов склада; пропуски не заменяются нулём.")\n        return\n    day_num = row["day_num"]\n''',
    "stock input guard",
)
main = replace_once(
    main,
    '''    produced = calc_produced(ns)\n    shipped = calc_shipped(ns)\n\n    await state.update_data(\n''',
    '''    produced = calc_produced(ns)\n    shipped = calc_shipped(ns)\n    if produced is None or shipped is None:\n        await msg.answer("⚠️ В ночной смене не хватает показаний весов склада; пропуски не заменяются нулём.")\n        return\n\n    await state.update_data(\n''',
    "night stock guard",
)

# Norm and duplicate alerts: absent is absent, explicit zero is still a real zero.
main = replace_once(main, '    base4, base3 = d.get("kv4", 0), d.get("kv3", 0)', '    base4, base3 = d.get("kv4"), d.get("kv3")', "alert bases")
main = replace_once(main, '        val = d.get(key, 0)\n        if not finite_number(base):', '        val = d.get(key)\n        if base is None or not finite_number(base):', "norm alert values")
main = replace_once(main, '    st4, p4, t4 = check_doubles(base4, d.get("kv4d", 0))', '    st4, p4, t4 = check_doubles(base4, d.get("kv4d"))', "dup4 alert")
main = replace_once(main, '    st3, p3, t3 = check_doubles(base3, d.get("kv3d", 0))', '    st3, p3, t3 = check_doubles(base3, d.get("kv3d"))', "dup3 alert")
main = replace_once(
    main,
    '''    if st4 in ("warn", "crit"):\n        alerts.append(\n            (\n                st4,\n                f"{em_dup(st4)} {prefix}Конв.4 vs 4Д: расхождение {p4:.2f}% ({fmt(t4)} т)",\n            )\n        )\n''',
    '''    if st4 == "missing":\n        alerts.append(("warn", f"⚠️ {prefix}Конв.4 vs 4Д: нет одного из показаний"))\n    elif st4 in ("warn", "crit"):\n        alerts.append((st4, f"{em_dup(st4)} {prefix}Конв.4 vs 4Д: расхождение {p4:.2f}% ({fmt(t4)} т)"))\n''',
    "dup4 missing alert",
)
main = replace_once(
    main,
    '''    if st3 in ("warn", "crit"):\n        alerts.append(\n            (\n                st3,\n                f"{em_dup(st3)} {prefix}Конв.3 vs 3Д: расхождение {p3:.2f}% ({fmt(t3)} т)",\n            )\n        )\n''',
    '''    if st3 == "missing":\n        alerts.append(("warn", f"⚠️ {prefix}Конв.3 vs 3Д: нет одного из показаний"))\n    elif st3 in ("warn", "crit"):\n        alerts.append((st3, f"{em_dup(st3)} {prefix}Конв.3 vs 3Д: расхождение {p3:.2f}% ({fmt(t3)} т)"))\n''',
    "dup3 missing alert",
)
main = replace_once(
    main,
    '''    for r in rows:\n        st4, p4, _ = check_doubles(r.get("kv4", 0), r.get("kv4d", 0))\n        st3, p3, _ = check_doubles(r.get("kv3", 0), r.get("kv3d", 0))\n        lines.append(\n            f"`{r['day_num']:>2d}   {em_dup(st4)}{p4:>5.2f}%      {em_dup(st3)}{p3:>5.2f}%`"\n        )\n''',
    '''    for r in rows:\n        st4, p4, _ = check_doubles(r.get("kv4"), r.get("kv4d"))\n        st3, p3, _ = check_doubles(r.get("kv3"), r.get("kv3d"))\n        left = "⬜ нет данных" if st4 == "missing" else f"{em_dup(st4)}{p4:>5.2f}%"\n        right = "⬜ нет данных" if st3 == "missing" else f"{em_dup(st3)}{p3:>5.2f}%"\n        lines.append(f"`{r['day_num']:>2d}   {left:<12s}  {right}`")\n''',
    "duplicate report missing display",
)
main_path.write_text(main, encoding="utf-8")

# Update tests to current architecture and complete test fixtures for formulas.
logic_test_path = Path("tests/test_balance_logic.py")
logic_test = logic_test_path.read_text(encoding="utf-8")
logic_test = replace_once(
    logic_test,
    '''        "kv4": kv4,\n        "kv34": output,\n''',
    '''        "kv4": kv4,\n        "kv34": output,\n        "kv102": 0,\n        "kv24p": 0,\n        "kv24hv": 0,\n        "kv28a1": 0,\n''',
    "logic fixture required fields",
)
logic_test_path.write_text(logic_test, encoding="utf-8")

db_test_path = Path("tests/test_database_windows.py")
db_test = db_test_path.read_text(encoding="utf-8")
db_test = replace_once(
    db_test,
    '''def shifts(kv4, kv34):\n    return {\n        1: {"kv4": kv4 / 2, "kv34": kv34 / 2},\n        2: {"kv4": kv4 / 2, "kv34": kv34 / 2},\n    }\n''',
    '''def shifts(kv4, kv34):\n    def one(input_value, output_value):\n        return {"kv4": input_value, "kv34": output_value, "kv102": 0, "kv24p": 0, "kv24hv": 0, "kv28a1": 0}\n    return {1: one(kv4 / 2, kv34 / 2), 2: one(kv4 / 2, kv34 / 2)}\n''',
    "database balance fixture",
)
stock_zero = ', "kv46d": 0, "kv74": 0, "kv74d": 0, "kv65mps": 0, "kv65cpo": 0, "kv66mps": 0, "kv66cpo": 0, "kv84mps": 0, "kv84cpo": 0'
db_test = db_test.replace('{"kv4": 500, "kv44": 100, "kv44d": 100}', '{"kv4": 500, "kv44": 100, "kv44d": 100' + stock_zero + '}', 2)
db_test = db_test.replace('{"kv4": 500, "kv44": 200, "kv44d": 200}', '{"kv4": 500, "kv44": 200, "kv44d": 200' + stock_zero + '}', 2)
db_test_path.write_text(db_test, encoding="utf-8")

helpers_path = Path("tests/test_helpers_and_alerts.py")
helpers = helpers_path.read_text(encoding="utf-8")
helpers = helpers.replace('self.assertEqual(main.calc_produced(data), 50)', 'self.assertIsNone(main.calc_produced(data))')
helpers = helpers.replace('self.assertIn("ПОСУТОЧНЫЕ АБСОЛЮТНЫЕ ПОКАЗАНИЯ", context)', 'self.assertIn("ФАКТИЧЕСКИЕ СУТОЧНЫЕ ПОКАЗАНИЯ", context)')
helpers = helpers.replace('self.assertIn("Окно 3 сут.; 29–31.07.2026", context)', 'self.assertIn("Окно 3 сут.: 29.07–31.07.2026", context)')
helpers = helpers.replace('self.assertIn("К4=3000.00 т", context)', 'self.assertIn("Дата 31.07.2026: К4=1000.00 т", context)')
helpers_path.write_text(helpers, encoding="utf-8")

handlers_path = Path("tests/test_handlers.py")
handlers = handlers_path.read_text(encoding="utf-8")
handlers = handlers.replace('(main.report_night_shift, "Ночная смена")', '(main.report_night_shift, "ночная смена")', 1)
start = handlers.index("class AIClientTests")
end = handlers.index('\n\nif __name__ == "__main__":', start)
new_ai_tests = '''class AIClientTests(unittest.IsolatedAsyncioTestCase):\n    async def test_ai_is_explicitly_disabled_without_oauth_token(self):\n        with (\n            patch.object(main, "ALLOWED_USER_IDS", {101}),\n            patch.object(main, "CLAUDE_CODE_OAUTH_TOKEN", ""),\n        ):\n            answer = await main.ask_ai("вопрос", "контекст", 101)\n        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", answer)\n\n    async def test_ai_returns_agent_sdk_text(self):\n        with (\n            patch.object(main, "ALLOWED_USER_IDS", {101}),\n            patch.object(main, "CLAUDE_CODE_OAUTH_TOKEN", "test-oauth"),\n            patch.object(main, "CLAUDE_AUTH_CONFLICTS", ()),\n            patch.object(main, "_run_claude_agent", AsyncMock(return_value=("Первая часть\\nВторая часть", None, None))),\n        ):\n            answer = await main.ask_ai("вопрос", "контекст", 101)\n        self.assertEqual(answer, "Первая часть\\nВторая часть")\n\n    async def test_ai_rate_limit_is_user_facing(self):\n        with (\n            patch.object(main, "ALLOWED_USER_IDS", {101}),\n            patch.object(main, "CLAUDE_CODE_OAUTH_TOKEN", "test-oauth"),\n            patch.object(main, "CLAUDE_AUTH_CONFLICTS", ()),\n            patch.object(main, "_run_claude_agent", AsyncMock(return_value=("", "rate_limit", 429))),\n        ):\n            answer = await main.ask_ai("вопрос", "контекст", 101)\n        self.assertIn("Лимит использования Claude Pro", answer)\n'''
handlers = handlers[:start] + new_ai_tests + handlers[end:]
handlers_path.write_text(handlers, encoding="utf-8")

print("maintenance v3 additions applied")
