### Command safety and reproducibility

- Do not use large shell heredocs for Python or other scripting languages.
- Do not generate complex structured data inline in shell commands (for example JSON, SVG, XML, HTML, or large nested dicts).
- Any non-trivial script that creates, modifies, or deletes repo files must be written as a real file in the repository.
- Prefer versioned repo scripts over ephemeral terminal-only scripts.
- Generated scripts must be readable, deterministic, and rerunnable.
- Commands must be easy to review, copy-paste safe, and practical to debug.
- Do not use `python - <<'PY'` except for very small read-only inspection commands or trivial one-liners.
- For anything beyond a trivial one-liner, create a real script file in the repo and run that file instead.
- Before executing a generated script, validate its syntax when practical.
- Avoid quoting-heavy inline commands that are fragile or hard to audit.

### Read and follow CLAUDE.md before making changes.