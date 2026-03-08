# Instructions for contributors especially codex
- When modifying Python file under `/wafer`, create or update the matching test in `/tests/wafer/`.
- When modifying Python file under `/extensions`, create or update the matching test in `/tests/extensions/`.
- Check each test file for compatibility with the source and update or rewrite the test file for optimal testing.
- Keep `/tests/wafer/` directory matching the structure of `/wafer/` for visibility.
- Keep `/tests/extensions/` directory matching the structure of `/extensions/` for visibility.
- The test name uses `test_<source_file>.py`.
- Do NOT add `__init__.py` in any `/tests/` subdirectory (importlib mode, avoids source package collision).
- Do not add comments. add only when required, minimal and in English.
- Adjust tests to reflect code changes.
