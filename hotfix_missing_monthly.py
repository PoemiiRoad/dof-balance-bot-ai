from pathlib import Path

# One-shot tested migration for the monthly missing-data edge case.
main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
replacements = {
    "{pct(s['kv14'], s['kv4']):.0f}%": "{pct_text(s['kv14'], s['kv4'])}",
    "{pct(s['kv32'], s['kv4']):.0f}%": "{pct_text(s['kv32'], s['kv4'])}",
    "{pct(s['kv34'], s['kv4']):.0f}%": "{pct_text(s['kv34'], s['kv4'])}",
    "{pct(s['kv102'], s['kv4']):.0f}%": "{pct_text(s['kv102'], s['kv4'])}",
    "{pct(s['kv15'], s['kv3']):.0f}%": "{pct_text(s['kv15'], s['kv3'])}",
    "{pct(s['kv33'], s['kv3']):.0f}%": "{pct_text(s['kv33'], s['kv3'])}",
    "{pct(s['kv101'], s['kv3']):.0f}%": "{pct_text(s['kv101'], s['kv3'])}",
}
for old, new in replacements.items():
    count = main.count(old)
    if count != 1:
        raise RuntimeError(f"expected one monthly percentage expression {old!r}, found {count}")
    main = main.replace(old, new, 1)
main_path.write_text(main, encoding="utf-8")

helpers_path = Path("tests/test_helpers_and_alerts.py")
helpers = helpers_path.read_text(encoding="utf-8")
anchor = '        self.assertEqual(main.sign(math.inf), "—")\n'
if anchor not in helpers:
    raise RuntimeError("helper test anchor missing")
helpers = helpers.replace(anchor, anchor + '        self.assertEqual(main.pct_text(None, 100), "—")\n', 1)
helpers_path.write_text(helpers, encoding="utf-8")
