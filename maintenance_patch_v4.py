from pathlib import Path

source = Path("maintenance_patch_v3.py").read_text(encoding="utf-8")
old = '''    ''' + "'''def sum_period(rows: Iterable[Mapping], fields: Sequence[str] = FIELDS) -> dict:\\n    \"\"\"Сначала суммирует тоннаж, не усредняя суточные проценты.\"\"\"\\n    rows = list(rows)\\n    return {key: sum(_number(row.get(key)) for row in rows) for key in fields}\\n'''"
new = '''    ''' + "'''def sum_period(rows: Iterable[Mapping], fields: Sequence[str] = FIELDS) -> dict:\\n    rows = list(rows)\\n    return {key: sum(_number(row.get(key)) for row in rows) for key in fields}\\n'''"
if old not in source:
    raise RuntimeError("v3 sum_period matcher literal not found")
source = source.replace(old, new, 1)
exec(compile(source, "maintenance_patch_v3.py", "exec"))
