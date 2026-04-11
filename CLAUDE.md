# Linions — AI assistant instructions

Read these documents before writing any code, in this order:
1. REQUIREMENTS.md — what and why
2. STANDARDS.md — quality rules (non-negotiable)
3. DESIGN.md — how (contracts, schemas, data flow)
4. PHASES.md — what phase we are in and what the gate is

Current phase: 8 — Public-launch hardening, showcase README, and documentation (in progress)

Never implement anything outside the current phase scope.
After writing code, run the test command from PHASES.md before declaring done.

## Permissions

You are authorized to run any of the following without asking:
- Any `ruff` command
- Any `pytest` command  
- Any `pip` command
- Any `npm install` command
- Any related test run command

Always run lint and tests automatically after making changes.
Do not ask permission for these — just run them and report results.

Never commit anything or push to github and never deploy something yourself to aws account.
