"""Runtime override for the DOF bot AI timeout.

Python imports sitecustomize automatically on normal startup. The project starts
with `python main.py`, so this override is applied before main.py imports the bot
modules. It keeps the effective Claude timeout at 300 seconds even while older
compatibility code still writes 180 into the environment.
"""

import os

_original_getenv = os.getenv


def _dof_getenv(key, default=None):
    if key == "AI_TIMEOUT_SECONDS":
        return "300"
    return _original_getenv(key, default)


os.getenv = _dof_getenv
