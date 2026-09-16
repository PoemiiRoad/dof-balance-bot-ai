from pathlib import Path

# One-shot tested migration for non-text Claude stream events.
main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
old = '''                    if delta.get("type") == "text_delta":\n                        chunk = delta.get("text", "")\n                    if chunk:\n                        if first_text_s is None:\n                            first_text_s = loop.time() - started\n                            logger.warning("Claude first text_delta after %.1f s", first_text_s)\n                        stream_parts.append(chunk)\n'''
new = '''                    if delta.get("type") == "text_delta":\n                        chunk = delta.get("text", "")\n                        if chunk:\n                            if first_text_s is None:\n                                first_text_s = loop.time() - started\n                                logger.warning("Claude first text_delta after %.1f s", first_text_s)\n                            stream_parts.append(chunk)\n'''
if main.count(old) != 1:
    raise RuntimeError(f"stream delta block: expected 1 occurrence, found {main.count(old)}")
main = main.replace(old, new, 1)
main = main.replace("обновите CLAUDE_CODE_OAUTH_TOKEN в Northflank.", "обновите CLAUDE_CODE_OAUTH_TOKEN в переменных окружения сервиса.")
main = main.replace("Удалите их из Northflank — иначе подписочный токен", "Удалите их из переменных окружения сервиса — иначе подписочный токен")
main_path.write_text(main, encoding="utf-8")

handlers_path = Path("tests/test_handlers.py")
handlers = handlers_path.read_text(encoding="utf-8")
anchor = '''    async def test_ai_rate_limit_is_user_facing(self):\n        with (\n            patch.object(main, "ALLOWED_USER_IDS", {101}),\n            patch.object(main, "CLAUDE_CODE_OAUTH_TOKEN", "test-oauth"),\n            patch.object(main, "CLAUDE_AUTH_CONFLICTS", ()),\n            patch.object(main, "_run_claude_agent", AsyncMock(return_value=("", "rate_limit", 429))),\n        ):\n            answer = await main.ask_ai("вопрос", "контекст", 101)\n        self.assertIn("Лимит использования Claude Pro", answer)\n'''
if anchor not in handlers:
    raise RuntimeError("AI client test anchor missing")
extra = '''\n    async def test_service_stream_delta_without_text_does_not_crash(self):\n        class FakeStreamEvent:\n            def __init__(self, event):\n                self.event = event\n\n        async def fake_query(*, prompt, options):\n            yield FakeStreamEvent({\n                "type": "content_block_delta",\n                "delta": {"type": "thinking_delta", "thinking": "internal"},\n            })\n\n        with (\n            patch.object(main, "StreamEvent", FakeStreamEvent),\n            patch.object(main, "query", fake_query),\n        ):\n            answer, error_type, status = await main._run_claude_agent("тест")\n\n        self.assertEqual(answer, "")\n        self.assertIsNone(error_type)\n        self.assertIsNone(status)\n'''
handlers = handlers.replace(anchor, anchor + extra, 1)
handlers_path.write_text(handlers, encoding="utf-8")
