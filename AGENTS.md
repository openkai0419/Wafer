# Instructions for contributors especially codex
- When modifying Python file under `/source`, create or update the matching test in `/tests/source/`.
- When modifying Python file under `/plugins`, create or update the matching test in `/tests/plugins/`.
- Check each test file for compatibility with the source and update or rewrite the test file for optimal testing.
- Keep `/tests/source/` directory matching the structure of `/source/` for visibility.
- Keep `/tests/plugins/` directory matching the structure of `/plugins/` for visibility.
- The test name uses `test_<source_file>.py`.
- Do NOT add `__init__.py` in any `/tests/` subdirectory (importlib mode, avoids source package collision).
- Do not add comments. add only when required, minimal and in English.
- Adjust tests to reflect code changes.
