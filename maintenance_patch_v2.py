from pathlib import Path

source = Path("maintenance_patch.py").read_text(encoding="utf-8")
old = "'                    if chunk:\\n                        stream_parts.append(chunk)'"
new = "'                        if chunk:\\n                            stream_parts.append(chunk)'"
if old not in source:
    raise RuntimeError("stream matcher literal not found in maintenance patch")
source = source.replace(old, new, 1)
exec(compile(source, "maintenance_patch.py", "exec"))
