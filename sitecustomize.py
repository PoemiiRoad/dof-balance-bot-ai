"""Runtime overrides and lightweight Claude request diagnostics for the DOF bot.

Python imports sitecustomize automatically on normal startup. The project starts
with `python main.py`, so these hooks are applied before main.py imports the bot
modules.

Only prompt LENGTHS are logged. User questions, report contents and tokens are
never written to the log by this diagnostic hook.
"""

import logging
import os

_original_getenv = os.getenv


def _dof_getenv(key, default=None):
    if key == "AI_TIMEOUT_SECONDS":
        return "300"
    return _original_getenv(key, default)


os.getenv = _dof_getenv


# Log the actual sizes passed to Claude without logging any sensitive text.
# sitecustomize runs before main.py executes `from claude_agent_sdk import query`,
# so replacing the SDK module function here also replaces what main.py imports.
try:
    import claude_agent_sdk as _claude_sdk

    _original_claude_query = _claude_sdk.query
    _ai_diag_logger = logging.getLogger("dof.ai.prompt")

    async def _dof_logged_query(*args, **kwargs):
        prompt = kwargs.get("prompt")
        if prompt is None and args:
            prompt = args[0]
        prompt = "" if prompt is None else str(prompt)

        options = kwargs.get("options")
        system_prompt = getattr(options, "system_prompt", "") if options is not None else ""
        system_chars = len(system_prompt) if isinstance(system_prompt, str) else len(str(system_prompt or ""))

        marker = "ДАННЫЕ ИЗ ОТЧЁТА:\n"
        if marker in prompt:
            context = prompt.split(marker, 1)[1]
            context_chars = len(context)
        else:
            context_chars = 0

        _ai_diag_logger.warning("AI SYSTEM_PROMPT chars=%s", system_chars)
        _ai_diag_logger.warning("AI context chars=%s", context_chars)
        _ai_diag_logger.warning("AI total prompt chars=%s", len(prompt))

        async for message in _original_claude_query(*args, **kwargs):
            yield message

    _claude_sdk.query = _dof_logged_query
except Exception:
    # Diagnostics must never prevent the bot from starting.
    pass
