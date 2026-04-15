# whisperlite FAQ

Common setup errors and fixes from real debugging sessions. Most are macOS-specific — particularly macOS 15 (Sequoia), which tightened permission enforcement for keyboard capture and text injection.

If your issue isn't here, tail `~/Library/Logs/whisperlite.log` and file an issue with the relevant output.

## Table of contents

- [Permissions & TCC](#permissions--tcc)
  - [Q: Permissions not working ("not trusted" warning)](#q-permissions-not-working-not-trusted-warning)
  - [Q: I upgraded Homebrew Python and permissions stopped working](#q-i-upgraded-homebrew-python-and-permissions-stopped-working)
- [Hotkey](#hotkey)
  - [Q: F5 doesn't work as the record hotkey](#q-f5-doesnt-work-as-the-record-hotkey)
  - [Q: Can I use the fn key?](#q-can-i-use-the-fn-key)
  - [Q: How do I change the hotkey?](#q-how-do-i-change-the-hotkey)
  - [Q: I double-tap Opt but whisperlite doesn't respond](#q-i-double-tap-opt-but-whisperlite-doesnt-respond)
  - [Q: How do I cancel a dictation in progress?](#q-how-do-i-cancel-a-dictation-in-progress)
- [Text injection](#text-injection)
  - [Q: I dictate but nothing appears anywhere](#q-i-dictate-but-nothing-appears-anywhere)
  - [Q: The transcript pastes into my terminal instead of the app I was in](#q-the-transcript-pastes-into-my-terminal-instead-of-the-app-i-was-in)
- [Config](#config)
  - [Q: Where is my config file?](#q-where-is-my-config-file)
  - [Q: "Open Config File" menu item does nothing](#q-open-config-file-menu-item-does-nothing)
- [Sounds](#sounds)
  - [Q: Can I disable the sound cues?](#q-can-i-disable-the-sound-cues)
  - [Q: Can I use different sounds?](#q-can-i-use-different-sounds)
- [Transcription](#transcription)
  - [Q: First run takes forever — is it hung?](#q-first-run-takes-forever--is-it-hung)
  - [Q: How do I change the Whisper model?](#q-how-do-i-change-the-whisper-model)
- [Debugging](#debugging)
  - [Q: How do I see what whisperlite is doing?](#q-how-do-i-see-what-whisperlite-is-doing)
- [Before you file a bug](#before-you-file-a-bug)

---

## Permissions & TCC

### Q: Permissions not working ("not trusted" warning)

**Symptom:** Running `python tests/smoke/smoke_hotkey.py` prints `This process is not trusted! Input event monitoring will not be possible...` and the hotkey is never received.

**Cause:** The Python binary (and, on macOS 15, its parent terminal app) has not been granted Input Monitoring and Accessibility. pynput needs both: Input Monitoring to *read* keystrokes, Accessibility to *synthesize* the Cmd+V paste.

**Fix:**

1. Resolve your venv's real Python path:

   ```bash
   .venv/bin/python3 -c "import os, sys; print(os.path.realpath(sys.executable))"
   ```

   Example: `/opt/homebrew/Cellar/python@3.10/3.10.17/Frameworks/Python.framework/Versions/3.10/bin/python3.10`

2. Open **System Settings → Privacy & Security → Input Monitoring**. Click `+`, press `Cmd+Shift+G`, paste the path, select `python3.10`, toggle ON.
3. Repeat in **Privacy & Security → Accessibility**. Both panes must have `python3.10`, both ON.
4. Re-run the smoke test. No terminal restart needed — each `python` invocation reads current TCC state at launch.

**Still not trusted?** On macOS 15 (Sequoia), TCC also checks the *terminal app* that launched Python. Add your terminal (`/Applications/iTerm.app`, `/Applications/Utilities/Terminal.app`, Ghostty, Warp, etc.) to **Accessibility** as well.

If you don't want to grant your primary terminal: open a different terminal app (e.g. Terminal.app if you normally use iTerm2), grant *it* Accessibility, and run whisperlite from there. The two are distinct app bundles.

> **Input Monitoring vs Accessibility:** Input Monitoring = read keystrokes (hotkey detection). Accessibility = synthesize keystrokes (paste). whisperlite needs both — missing either causes a silent half-failure.

---

### Q: I upgraded Homebrew Python and permissions stopped working

**Symptom:** After `brew upgrade python@3.10`, the `not trusted` warning returns even though `python3.10` was previously granted.

**Cause:** TCC grants attach to the exact resolved binary path. The Cellar path includes the version (`python@3.10/3.10.17/...` → `3.10.18/...` after upgrade), so the grant is now orphaned.

**Fix:** Re-add the new binary path to Input Monitoring and Accessibility (see the previous Q). Optionally remove the stale old-version entry from both lists.

---

## Hotkey

### Q: F5 doesn't work as the record hotkey

**Symptom:** Setting a function key like F5 as the record hotkey does nothing.

**Cause:** whisperlite v1 does not support function keys. Function-key events are often intercepted by system features (Dictation, Mission Control, backlight) or dropped by userspace listeners on macOS 14+.

**Fix:** Use the default double-tap modifier. `whisperlite.toml` ships with:

```toml
[hotkey]
record = "<alt>"
double_tap_window_ms = 400
```

Double-tap Opt to start recording, double-tap again to stop. Valid `record` values: `<alt>`, `<shift>`, `<ctrl>`, `<cmd>`.

---

### Q: Can I use the fn key?

**Symptom:** You want `fn` alone as the hotkey.

**Cause:** pynput cannot capture `fn` on macOS — it's an HID-layer flag, not a regular key event.

**Fix:** Use double-tap `<alt>`/`<shift>`/`<ctrl>`/`<cmd>` instead. `fn` support via a Quartz event tap is a future TODO.

---

### Q: How do I change the hotkey?

**Symptom:** You want a different modifier than the default.

**Cause:** whisperlite v1 only supports double-tap of a single modifier. Chords and non-modifier keys are not supported.

**Fix:** Edit `whisperlite.toml`:

```toml
[hotkey]
record = "<alt>"              # one of <alt>, <shift>, <ctrl>, <cmd>
double_tap_window_ms = 400    # range: [150, 1000]
```

- `<alt>` (default): rarely used alone, lowest false-positive risk.
- `<shift>`: matches JetBrains muscle memory, but can fire while typing capitals if the window is too wide.
- `<cmd>` / `<ctrl>`: usable but easier to brush twice while reaching for chord shortcuts.
- Drop `double_tap_window_ms` to ~250 for accidental triggers, raise to ~600 for missed taps.

---

### Q: I double-tap Opt but whisperlite doesn't respond

**Symptom:** whisperlite is running, menubar icon is idle, double-tapping the modifier does nothing.

**Cause:** One of:

1. Input Monitoring not granted to the Python binary.
2. A remap utility (Karabiner-Elements, BetterTouchTool) is swallowing the modifier.
3. Taps are landing more than `double_tap_window_ms` apart.
4. You're using the modifier in a chord (e.g. Opt+Space) — chords correctly disqualify the press.

**Fix:**

1. Verify permissions (see Permissions & TCC). Run `python tests/smoke/smoke_hotkey.py` and double-tap — it should print `Got double-tap!` within 30 seconds.
2. Check any key-remap utility for rules on your chosen modifier. Try `<shift>` (least likely to be remapped) or temporarily disable the utility.
3. Tail `~/Library/Logs/whisperlite.log` for `hotkey manager started` at launch.

---

### Q: How do I cancel a dictation in progress?

**Symptom:** You started recording but want to abort.

**Fix:** Press **Escape** at any point — while recording, transcribing, or just before paste. Audio is discarded, nothing is pasted, the clipboard is untouched. You'll hear the stop sound as confirmation.

**Note:** Escape fires at the next safe checkpoint. If it catches the ~150ms window where Cmd+V is already in flight, the paste completes — the OS can't unsend a keystroke.

---

## Text injection

### Q: I dictate but nothing appears anywhere

**Symptom:** Double-tap, speak, double-tap again — nothing appears.

**Cause:** Usually a missing Accessibility grant (paste synthesis is silently refused without it). Rarely, the pasteboard write itself failed.

**Fix:**

1. Confirm **Input Monitoring** has `python3.10`, and **Accessibility** has both `python3.10` and your terminal app. See Permissions & TCC.
2. Re-run `python tests/smoke/smoke_inject.py` to confirm.
3. As a sanity check, run `pbpaste` after dictating. If it shows your transcript, the pasteboard write worked and only the synthesized Cmd+V is blocked — you can paste manually.

---

### Q: The transcript pastes into my terminal instead of the app I was in

**Symptom:** You start recording in Notes, switch to your terminal mid-recording, stop, and the text lands in the terminal.

**Cause:** whisperlite pastes to whichever app is frontmost when you stop — not when you started. This is deliberate: recapturing the start-app cost ~800ms of focus-stealing latency on Sequoia.

**Fix:** Don't alt-tab mid-recording. Make sure the target app is frontmost when you double-tap to stop. The transcript is also written to the clipboard, so Cmd+V into the right app if the paste lands wrong.

---

## Config

### Q: Where is my config file?

**Symptom:** You edited a config but changes are ignored, or you don't know which file to edit.

**Cause:** whisperlite searches, in order:

1. `$WHISPERLITE_CONFIG` (env var)
2. `whisperlite.toml` in the current working directory (project root when running `python -m whisperlite` from the repo)
3. `~/.config/whisperlite/config.toml`

On a fresh clone none exist, so whisperlite uses compiled-in defaults until you create one.

**Fix:**

```bash
cp whisperlite.example.toml whisperlite.toml
# edit whisperlite.toml
```

Relaunch whisperlite. It logs the path it loaded:

```
INFO whisperlite.config: loaded config from /Users/.../whisperlite/whisperlite.toml
```

`whisperlite.toml` at the project root is gitignored. `whisperlite.example.toml` is the committed template.

---

### Q: "Open Config File" menu item does nothing

**Symptom:** Clicking "Open Config File" prints `The file /Users/.../config.toml does not exist`.

**Cause:** No config file exists in any search-path location — whisperlite is on compiled-in defaults.

**Fix:**

```bash
cp whisperlite.example.toml whisperlite.toml
```

Restart whisperlite. The menu item opens whichever file was actually loaded.

---

## Sounds

### Q: Can I disable the sound cues?

**Symptom:** The Tink/Pop start/stop sounds are unwanted (e.g. during meetings).

**Cause:** Sound cues are enabled by default (`Tink.aiff` on start, `Pop.aiff` on stop).

**Fix:** Edit `whisperlite.toml`:

```toml
[sound]
enabled = false
```

Restart whisperlite.

---

### Q: Can I use different sounds?

**Symptom:** You want something other than Tink and Pop.

**Cause:** Defaults point at macOS built-ins. whisperlite plays any file `afplay` supports (`.aiff`, `.wav`, `.mp3`).

**Fix:** macOS ships ~15 sounds in `/System/Library/Sounds/` — e.g. `Funk.aiff`, `Glass.aiff`, `Hero.aiff`, `Bottle.aiff`, `Submarine.aiff`. Preview:

```bash
afplay /System/Library/Sounds/Funk.aiff
```

Edit `whisperlite.toml`:

```toml
[sound]
start_path = "/System/Library/Sounds/Funk.aiff"
stop_path = "/System/Library/Sounds/Bottle.aiff"
```

Custom files work too — use an absolute path.

---

## Transcription

### Q: First run takes forever — is it hung?

**Symptom:** First run appears to hang for minutes, or shows slow Hugging Face download progress.

**Cause:** mlx-whisper downloads the model (default `mlx-community/whisper-medium-mlx`, ~1.5 GB) on first use.

**Fix:** Wait it out. Subsequent runs start in ~2 seconds from cache. For faster setup testing, use a smaller model — see the next Q.

---

### Q: How do I change the Whisper model?

**Symptom:** You want a different quality / speed / size trade-off.

**Cause:** The default `medium` is tuned for quality. Smaller models are faster and much smaller to download.

**Fix:** Edit `whisperlite.toml`:

```toml
[model]
name = "mlx-community/whisper-tiny-mlx"   # ~75 MB, much faster
```

`tiny` quality drops significantly — use it for setup testing, then switch back to `medium` or `large-v3`. See `whisperlite.example.toml` for the full list of supported models.

---

## Debugging

### Q: How do I see what whisperlite is doing?

**Symptom:** Something's wrong and the menubar icon isn't enough.

**Cause:** The menubar conveys state at a glance; detail lives in the log.

**Fix:**

```bash
tail -f ~/Library/Logs/whisperlite.log
```

Watch for:

- `state -> ERROR` lines and the error that follows
- `whisperlite.inject` — pasteboard and paste synthesis
- `whisperlite.transcribe` — model load and timing
- `whisperlite.hotkey` — listener start/stop
- `WARNING` lines — usually recoverable but worth attention

Include the relevant tail in any bug report.

---

## Before you file a bug

1. Tail `~/Library/Logs/whisperlite.log` and capture lines around the failure.
2. Confirm both `python3.10` and your terminal app are in **Input Monitoring** and **Accessibility**.
3. Confirm the granted Python binary path still matches your current venv (see the Homebrew upgrade Q).
4. Note your macOS version — Sequoia (15.x) behaves differently from Sonoma and earlier.

Then open an issue with the log tail, macOS version, and the command you ran.
