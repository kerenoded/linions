# Plan: Multi-language Support (including RTL)

> Status: planned for v2
> Scope: pipeline models, Director agent, episode JSON schema, frontend rendering

---

## Problem

The Director agent currently always responds in English regardless of the prompt language.
The gallery and player have no concept of text direction — Hebrew and Arabic would render
left-to-right and look broken. There is no `language` field in the episode JSON schema.

---

## Goal

- Episodes are generated in the language of the prompt (Italian prompt → Italian episode).
- The gallery and player render text with the correct direction (RTL for Hebrew/Arabic).
- The episode JSON carries a `language` field so any client can render it correctly.
- No regression for existing English episodes.

---

## RTL languages in scope

| Code | Language |
|------|----------|
| `he` | Hebrew |
| `ar` | Arabic |
| `fa` | Persian / Farsi |
| `ur` | Urdu |

All other languages are LTR. Unknown language codes default to LTR.

---

## Implementation steps

### Step 1 — Language detection before the Director call

The orchestrator detects the prompt language before invoking the Director.
This keeps the Director prompt simple and avoids asking the LLM to self-report reliably.

Add `langdetect` (Python package) to `requirements.lock`.

In the orchestrator, before building `DirectorInput`:

```python
from langdetect import detect, LangDetectException

def detect_prompt_language(prompt: str) -> str:
    """Detect ISO 639-1 language code from prompt text. Defaults to 'en' on failure."""
    try:
        return detect(prompt)
    except LangDetectException:
        return "en"
```

`langdetect` is fast, offline, and requires no API calls. It handles short strings
reasonably well. Confidence is not perfect — good enough for this use case since the
Director will produce output in the prompt's natural language anyway.

---

### Step 2 — Add `language` and `text_direction` to `DirectorInput`

```python
RTL_LANGUAGES: frozenset[str] = frozenset({"he", "ar", "fa", "ur"})

class DirectorInput(BaseModel):
    prompt: str
    username: str
    job_id: str
    session_id: str
    rag_context: str
    available_obstacles: list[str]
    language: str              # ISO 639-1 code detected from the prompt
    text_direction: Literal["ltr", "rtl"]   # derived from language
```

The orchestrator derives `text_direction` from `language`:

```python
text_direction = "rtl" if language in RTL_LANGUAGES else "ltr"
```

`RTL_LANGUAGES` lives in `pipeline/config.py` with an inline comment.

---

### Step 3 — Update the Director agent prompt

The Director prompt gets a language instruction block:

```
Language: {language} ({text_direction})
You MUST write all story content — title, description, approach_description,
outcome_description, and choice labels — in {language}.
Do not translate into English. Respond in {language} only.
```

For RTL languages, add:

```
Note: {language} is a right-to-left language. Keep text natural and idiomatic.
```

---

### Step 4 — Add `language` and `text_direction` to `DirectorOutput`

The Director echoes back the language it used. The validator checks it matches the input.

```python
class DirectorOutput(BaseModel):
    title: str
    description: str
    acts: list[Act]
    language: str
    text_direction: Literal["ltr", "rtl"]
```

**ScriptValidator** new rule:

```python
# Rule: language and text_direction must be consistent with the input.
# Prevents the model from switching language silently.
if output.language != input_language:
    errors.append(f"language mismatch: expected {input_language}, got {output.language}")
if output.text_direction not in ("ltr", "rtl"):
    errors.append(f"invalid text_direction: {output.text_direction}")
```

---

### Step 5 — Add `language` and `textDirection` to episode JSON schema

**`pipeline/models/episode.py`** — add to the `Episode` root model:

```python
class Episode(BaseModel):
    schema_version: str = Field(alias="schemaVersion")
    uuid: str
    username: str
    title: str
    description: str
    generated_at: str = Field(alias="generatedAt")
    content_hash: str | None = Field(alias="contentHash")
    act_count: int = Field(alias="actCount")
    language: str                              # NEW — ISO 639-1 code e.g. "he", "en", "it"
    text_direction: Literal["ltr", "rtl"] = Field(alias="textDirection")  # NEW
    acts: list[EpisodeAct]
```

**Schema version bump:** `"1.0"` → `"1.1"`. Update `DESIGN.md` §5.1 and all fixtures.

Existing English episodes without these fields are rejected as schema version `"1.0"` —
they stay valid under the old schema. Any episode claiming `"1.1"` must have both fields.

---

### Step 6 — Update `episodes/index.json` entry shape

Add `language` and `textDirection` to each gallery index entry so the gallery can render
direction without fetching the full episode JSON:

```json
{
  "path": "episodes/odedkeren/uuid.json",
  "thumbPath": "episodes/odedkeren/uuid-thumb.svg",
  "username": "odedkeren",
  "title": "...",
  "description": "...",
  "createdAt": "...",
  "language": "he",
  "textDirection": "rtl"
}
```

Update `scripts/build-index.js` and `scripts/prepare-contribution.sh` to read and
include these fields.

---

### Step 7 — Frontend: gallery cards

In `frontend/src/gallery.ts`, when rendering each episode card, apply `dir` attribute:

```typescript
titleEl.setAttribute("dir", entry.textDirection ?? "ltr");
descriptionEl.setAttribute("dir", entry.textDirection ?? "ltr");
```

For RTL cards, also add a CSS class `rtl-card` so layout can be adjusted if needed
(e.g., text-align, padding adjustments).

---

### Step 8 — Frontend: episode player

In `frontend/src/player.ts`, when loading an episode, apply direction to:

- Episode title display element
- Episode description display element
- Each choice button label

```typescript
function applyTextDirection(episode: Episode): void {
  const dir = episode.textDirection ?? "ltr";
  titleEl.setAttribute("dir", dir);
  descriptionEl.setAttribute("dir", dir);
  // Applied per button when choices are rendered
}
```

Choice buttons are created dynamically — set `dir` on each button element at creation time:

```typescript
btn.setAttribute("dir", episode.textDirection ?? "ltr");
```

---

### Step 9 — Frontend types

`frontend/src/types.ts` — update `Episode` and `GalleryEntry` interfaces:

```typescript
export interface Episode {
  schemaVersion: string;
  uuid: string;
  username: string;
  title: string;
  description: string;
  generatedAt: string;
  contentHash: string | null;
  actCount: number;
  language: string;             // NEW
  textDirection: "ltr" | "rtl"; // NEW
  acts: EpisodeAct[];
}

export interface GalleryEntry {
  path: string;
  thumbPath: string;
  username: string;
  title: string;
  description: string;
  createdAt: string;
  language: string;             // NEW
  textDirection: "ltr" | "rtl"; // NEW
}
```

---

### Step 10 — Update fixtures and tests

- `tests/fixtures/valid_episode.json` — add `"language": "en"` and `"textDirection": "ltr"`, bump `"schemaVersion"` to `"1.1"`.
- Add `tests/fixtures/valid_episode_hebrew.json` — a valid episode with `"language": "he"` and `"textDirection": "rtl"`.
- Add `tests/fixtures/valid_episode_italian.json` — a valid LTR non-English episode.
- `ScriptValidator` tests: add test for language mismatch failure.
- Frontend state machine tests: add RTL episode path.

---

## What does NOT change

- The `contentHash` computation — language fields are part of the JSON body and therefore
  included in the hash automatically. No change needed.
- PR validation CI — schema validation already covers new required fields. No extra logic.
- Choice button max 40 chars rule — remains. Hebrew words tend to be shorter; not a problem.
- The SVG clips themselves — these are visual animations of Linai, no text inside SVGs.

---

## Existing English episodes

Episodes stored in `episodes/` before this change carry `schemaVersion: "1.0"` and have no
`language` or `textDirection` fields. Two options:

**Option A (recommended):** The frontend treats missing fields as `language: "en"`,
`textDirection: "ltr"`. No migration needed. Old episodes still display correctly.

**Option B:** Run a one-time migration script that adds the fields and updates hashes.
Not recommended — the contentHash would change, breaking existing PR validation history.

Go with Option A.

---

## Files changed summary

| File | Change |
|------|--------|
| `pipeline/config.py` | Add `RTL_LANGUAGES` frozenset |
| `requirements.lock` | Add `langdetect` |
| `pipeline/models/director.py` | Add `language`, `text_direction` to `DirectorInput` and `DirectorOutput` |
| `pipeline/models/episode.py` | Add `language`, `text_direction` to `Episode`; schema version `1.1` |
| `pipeline/validators/script_validator.py` | Add language consistency check |
| `pipeline/agents/director/prompt.txt` | Add language instruction block |
| `pipeline/lambdas/orchestrator/` | Add `detect_prompt_language()`, populate `DirectorInput` |
| `frontend/src/types.ts` | Add `language`, `textDirection` to `Episode` and `GalleryEntry` |
| `frontend/src/gallery.ts` | Apply `dir` attribute to title and description elements |
| `frontend/src/player.ts` | Apply `dir` attribute to title, description, choice buttons |
| `scripts/build-index.js` | Include `language` and `textDirection` in index entries |
| `scripts/prepare-contribution.sh` | Include `language` and `textDirection` |
| `DESIGN.md` §5.1, §6.2, §6.5 | Schema version bump, updated contracts |
| `tests/fixtures/valid_episode.json` | Add language fields, bump schema version |
| `tests/fixtures/valid_episode_hebrew.json` | New RTL fixture |
| `tests/fixtures/valid_episode_italian.json` | New LTR non-English fixture |
| All tests referencing episode schema | Update for new fields |
