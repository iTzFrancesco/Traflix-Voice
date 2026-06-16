---
description: "Check latest CI run and auto-fix any failures"
---

Check the latest GitHub Actions CI workflow run for this repository.

1. Run `gh run list --limit 3 --json conclusion,databaseId,headBranch,displayTitle,status,event` and identify the latest completed run on the current branch that failed.
2. If a failed run is found, get the failure details:
   - `gh run view <ID> --log-failed`
3. Analyze the errors and fix them in the codebase.
4. Verify fixes by running the appropriate commands:
   - Rust: `cd src-tauri && cargo fmt --check && cargo clippy -- -D warnings`
   - Python: `python -m py_compile src-tauri/whisper_engine.py && python -m pytest src-tauri/test_whisper_engine.py -v`
5. Commit and push the fixes with a descriptive message.
