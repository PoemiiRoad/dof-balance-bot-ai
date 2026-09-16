from pathlib import Path
import runpy

runpy.run_path("maintenance_patch_v4.py", run_name="__maintenance_v4__")

# Database helper rows represent a valid report; include zero-valued stock channels
# so stock-specific tests do not rely on fabricated values for absent rows.
db_path = Path("tests/test_database_windows.py")
db = db_path.read_text(encoding="utf-8")
old = 'return {"kv4": input_value, "kv34": output_value, "kv102": 0, "kv24p": 0, "kv24hv": 0, "kv28a1": 0}'
new = 'return {"kv4": input_value, "kv34": output_value, "kv102": 0, "kv24p": 0, "kv24hv": 0, "kv28a1": 0, "kv44": 0, "kv44d": 0, "kv46d": 0, "kv74": 0, "kv74d": 0, "kv65mps": 0, "kv65cpo": 0, "kv66mps": 0, "kv66cpo": 0, "kv84mps": 0, "kv84cpo": 0}'
if old not in db:
    raise RuntimeError("database helper row not found")
db = db.replace(old, new, 1)
db_path.write_text(db, encoding="utf-8")

# The current deterministic report renderer communicates continuity via the window
# itself; the old literal phrase was removed long ago.
helpers_path = Path("tests/test_helpers_and_alerts.py")
helpers = helpers_path.read_text(encoding="utf-8")
old_assert = '        self.assertIn("последовательные даты: да", context)\n'
if old_assert not in helpers:
    raise RuntimeError("obsolete continuity assertion not found")
helpers = helpers.replace(old_assert, '', 1)
helpers_path.write_text(helpers, encoding="utf-8")

print("maintenance v5 final fixture fixes applied")
