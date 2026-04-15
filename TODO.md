# TODO

Tracked future work for whisperlite. Each entry is self-contained so an agent
(or future-you) can pick it up without reading chat history. Priority tags:
P1 = do next, P2 = soon, P3 = nice-to-have, P4 = someday/maybe.

## [P2] Benchmark Whisper model variants on this machine

**What:** A reproducible benchmark script that measures warmup time, single-utterance latency, and transcription accuracy for each Whisper model supported by mlx-whisper, on the user's actual Mac hardware.

**Why:** Users considering whisperlite want to know which model to pick before committing to a 1.5GB download. The design doc defaults to `mlx-community/whisper-medium-mlx` but provides no quantitative basis for that choice on different hardware.

**Context:** `whisperlite/transcribe.py` wraps `mlx_whisper.transcribe`. Build step 0 measured `whisper-medium-mlx` at ~1595ms first call, ~28ms warm reuse on the user's M-series Mac. We have a fixture audio file at `tests/fixtures/hello_world.wav` (~1.72s, "hello world from whisperlite"). Candidate models to benchmark: `whisper-tiny-mlx`, `whisper-base-mlx`, `whisper-small-mlx`, `whisper-medium-mlx`, `whisper-large-v3-mlx`, and `distil-whisper-medium-mlx` if available. Report: per-model warmup time, warm-call latency (avg + p95 over 10 runs), model size on disk, and transcription text (manual inspection for quality).

**Acceptance criteria:**
- [ ] A script at `benchmarks/benchmark_models.py` that takes no arguments and runs the full suite.
- [ ] Output is a markdown table printed to stdout AND written to `benchmarks/results_{date}.md`.
- [ ] The table includes: model name, size (MB), first-call ms, p50 warm ms, p95 warm ms, transcribed text for the fixture.
- [ ] README section added explaining how to run benchmarks and what the numbers mean.

**Dependencies:** none — uses existing fixture and transcribe.py.

**Approach hints:** Use the existing `tests/fixtures/hello_world.wav` as the input. Use `time.perf_counter()` for timing. Feed each benchmark with 10 repeated calls after warmup, report p50 and p95. Larger models (`large-v3`, ~3GB) may not fit in memory on smaller Macs — wrap each model in try/except and mark it SKIPPED with the error if load fails. Skip models that aren't already cached unless the user passes `--download` to force a pull.

---

## [P2] Add model registry with metadata so users know what to expect

**What:** A module-level dict or TOML file that describes each supported Whisper model: human-readable name, size on disk, quality tier, language support, expected latency range, and a short "when to use this" description. Surface it in a new menubar item `Available Models` that opens a markdown page (or logs it) so users can decide before editing their config.

**Why:** When a user wants to change the model in their `whisperlite.toml`, they currently have to guess or google. A built-in registry removes that friction and lets users make informed trade-offs between speed, quality, size, and multilingual support.

**Context:** Whisper models available via mlx-whisper include tiny (~75MB), base (~150MB), small (~460MB), medium (~1.5GB), large-v3 (~3GB), plus distilled variants. Each has different accuracy on English vs multilingual, different latency characteristics, and different memory footprints. The registry should be source-of-truth for which models are officially supported and what metadata to surface.

**Acceptance criteria:**
- [ ] A file `whisperlite/models.py` (or a TOML at `whisperlite/models.toml`) with the registry data.
- [ ] A function `list_models() -> list[ModelInfo]` returning the registry.
- [ ] Each entry has: repo_id, display_name, size_mb, quality_tier ("basic" / "good" / "best"), languages ("en" / "multilingual"), description (1-2 sentences), approx_latency_ms (rough per-utterance estimate or "see benchmark").
- [ ] Menubar item `Available Models` that opens a temp markdown file summarizing the registry in a human-readable table.

**Dependencies:** Entry 1 (benchmark) — the `approx_latency_ms` field should be populated from actual benchmark data rather than guessed.

**Approach hints:** Start with a static dict hardcoded in `models.py`. Don't try to fetch from Hugging Face dynamically — that's extra complexity with no clear win. The registry only needs to reflect what the user can set in their config.

---

## [P3] Add `--config` CLI flag to `whisperlite` entrypoint

**What:** Accept `--config <path>` on the command line (`python -m whisperlite --config /path/to/custom.toml`) to override the config search order.

**Why:** Useful for testing different configs, comparing model settings side-by-side, or running two whisperlite instances with different hotkeys.

**Context:** Current entrypoint `whisperlite/__main__.py` calls `load_config()` with no arguments. Need to add argparse, pass the path to `load_config(path=Path(args.config))`.

**Acceptance criteria:**
- [ ] `python -m whisperlite --config /tmp/test.toml` loads from that path.
- [ ] `python -m whisperlite --help` prints usage.
- [ ] Missing file at the specified path raises `ConfigError` with a clear message (not a silent fall through to defaults).

**Dependencies:** none.

**Approach hints:** Use `argparse`. Keep it minimal — just `--config`, nothing else for now.

---

## [P4] Hold-to-talk mode

**What:** Support `mode = "hold"` in the config so pressing and holding the modifier records, and releasing it stops + transcribes. Today v1 uses a double-tap toggle pattern; hold mode would be a third interaction mode on top of it, not a replacement.

**Why:** Some users prefer press-and-hold for short utterances (no risk of leaving recording on accidentally). Both modes have their place — double-tap is better for longer dictation (hands-free while you think), hold is better for quick one-shot captures where you don't want to think about toggling off.

**Context:** v1 uses a double-tap-modifier pattern built on `pynput.keyboard.Listener` with an `on_press`/`on_release` state machine (see `whisperlite/hotkey.py`). The state machine already tracks modifier press-time, chord detection, and key-repeat suppression, so adding a hold-mode branch is a localized change: treat a long hold (>300ms, the current tap-disqualification threshold) as a start-record event, and the subsequent release as a stop-record event, instead of discarding both. The wire-up from app.py would need a small enum to select between the two modes.

**Acceptance criteria:**
- [ ] `hotkey.mode = "hold"` in `whisperlite.toml` makes press-and-hold start/stop recording.
- [ ] Default stays `double_tap` (no breaking change for existing users).
- [ ] Both modes covered by tests in `tests/integration/test_hotkey.py`.

**Dependencies:** none.

**Approach hints:** Add a `mode` field to `HotkeyConfig` and branch inside `HotkeyManager._on_press`/`_on_release`. The hold-mode branch can reuse the existing `_modifier_is_down` / `_chord_detected_during_press` bookkeeping but emit `on_record_pressed` twice (start on sustained press, stop on release) instead of counting taps. Test on Sequoia before calling it done.

---

## [P4] Keyword-triggered snippets / text expansion

**What:** Map voice trigger phrases to text expansions. e.g. saying "my email" expands to the user's email address; "sig" expands to their email signature. Optional extension: trigger an LLM transform of the transcript (e.g., "fix grammar" runs the utterance through an LLM before injection).

**Why:** This was the second feature the user wanted during office hours, explicitly deferred to v2 so v1 could nail the core dictation loop first. It's the thing that would make whisperlite competitive with Whispr Flow's snippets feature.

**Context:** See design doc section "What Makes This Cool" and the office-hours session. Three flavors were discussed: (A) pure text expansion (dict lookup post-transcription), (B) LLM transform mode (pass transcript through an LLM with a system prompt), (C) prompt template injection (say "code review" then injects a multi-line prompt). User expressed interest in all three eventually but wanted v1 core loop first.

**Acceptance criteria:**
- [ ] A new `[hooks]` section in `whisperlite.toml` lets users define trigger -> expansion mappings.
- [ ] After transcription, the text is passed through the hook pipeline before injection.
- [ ] At least flavor (A) — pure text expansion — works.
- [ ] Tests for the hook pipeline cover: trigger match, no-match pass-through, multiple hooks in sequence.

**Dependencies:** none (v1 core loop is complete).

**Approach hints:** Start with a simple dict lookup applied to the full transcription. Don't over-engineer. The LLM transform flavor is a separate follow-up (and requires choosing an LLM backend — Anthropic API, local llama.cpp, etc.).

---

## [P4] Distribute as a `.app` bundle with a proper installer

**What:** Package whisperlite as a `.app` bundle so non-technical users can download it, drag it to Applications, and run it without touching Python or a venv.

**Why:** Current distribution path is "clone the repo, set up a venv, grant TCC permissions to the Python binary." That's fine for developers but kills the open-source adoption story. A proper `.app` bundle with code signing and notarization is how real Mac apps ship.

**Context:** Project currently ships as a Python package via `pyproject.toml`. Bundling options: `py2app` (oldest, most mature), `briefcase` (modern, cross-platform), `pyinstaller` (cross-platform but Mac `.app` support is weaker). Code signing requires an Apple Developer Account ($99/year). Notarization is free but requires the same account. Without signing, users get a scary "unidentified developer" prompt on first launch. TCC permission prompts will attach to the bundled binary rather than a shared Python interpreter — a feature, not a bug, since the grants travel with the app.

**Acceptance criteria:**
- [ ] A `make dist` target that produces `whisperlite.app` in `dist/`.
- [ ] The `.app` launches, shows a menubar icon, and successfully runs the core dictation loop.
- [ ] TCC prompts correctly attribute to `whisperlite.app`, not Python.
- [ ] README has a "Download the .app" section with install instructions.

**Dependencies:** dogfood week complete, core loop stable, no known bugs. Signing/notarization is a further step that requires the Apple Developer Account.

**Approach hints:** Try `py2app` first — it's the most documented for this exact use case. Start without signing (users will have to right-click -> Open the first time). Add signing + notarization as a separate follow-up once the basic bundle works.

---

## [P4] Bundle custom whisperlite-branded sound cues

**What:** Ship a pair of custom-designed short audio cues (e.g. `whisperlite_start.aiff`, `whisperlite_stop.aiff`) inside the package at `whisperlite/assets/sounds/` instead of defaulting to macOS system sounds like Tink and Pop.

**Why:** Current defaults (`/System/Library/Sounds/Tink.aiff` and `Pop.aiff`) are fine but generic — many macOS apps and the system itself use them for notifications, which could cause confusion ("was that whisperlite or an iMessage?"). A pair of distinctive, on-brand cues would make whisperlite instantly recognizable by ear.

**Context:** The sound cue feature is already wired in via `whisperlite/sounds.py` and config fields `[sound] start_path` and `[sound] stop_path`. Defaults point to `/System/Library/Sounds/Tink.aiff` and `Pop.aiff`. To ship custom sounds, add a `whisperlite/assets/sounds/` directory with two short (<200ms) audio files, update the defaults in `whisperlite/config.py` to point to the bundled files via `Path(__file__).parent / "assets" / "sounds" / "..."`, and add the new assets to the `[tool.setuptools.package-data]` glob in `pyproject.toml`.

**Acceptance criteria:**
- [ ] Two audio files at `whisperlite/assets/sounds/` (names and format your call)
- [ ] Default config values point to the bundled files
- [ ] Files ship with the package (verified by `pip install` into a fresh venv and checking `whisperlite/assets/sounds/` is present)
- [ ] Sounds are short (<200ms) so they don't delay dictation flow
- [ ] Both sounds are clearly distinguishable from each other at a glance (different pitch or timbre)

**Dependencies:** none.

**Approach hints:** For the actual sound design, options are (a) commission a sound designer, (b) synthesize with a tool like Audacity or Ableton, or (c) use Creative-Commons-licensed short SFX from freesound.org (check the license, prefer CC0). Bundling via `package-data` is the same pattern already used for the speech-bubble PNG icons — see how `whisperlite/assets/*.png` is configured in `pyproject.toml`.

---
