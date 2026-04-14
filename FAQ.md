# whisperlite FAQ

Common setup errors and how to fix them, drawn from real debugging sessions
during development. Most of these are macOS-specific — particularly macOS 15
(Sequoia), which introduced stricter permission enforcement that affects
every keyboard-capture and text-injection tool on the platform.

If your issue isn't listed here, tail the log file (`~/Library/Logs/whisperlite.log`)
for clues and file an issue with the relevant log output.

## Table of contents

- [Permissions & TCC](#permissions--tcc)
  - [Q: "This process is not trusted!" warning from pynput](#q-this-process-is-not-trusted-warning-from-pynput)
  - [Q: I granted python3.10 Accessibility but it still says not trusted](#q-i-granted-python310-accessibility-but-it-still-says-not-trusted)
  - [Q: What's the difference between Input Monitoring and Accessibility?](#q-whats-the-difference-between-input-monitoring-and-accessibility)
  - [Q: Do I have to quit my terminal after granting permissions?](#q-do-i-have-to-quit-my-terminal-after-granting-permissions)
  - [Q: I upgraded Homebrew Python and permissions stopped working](#q-i-upgraded-homebrew-python-and-permissions-stopped-working)
- [Hotkey](#hotkey)
  - [Q: F5 doesn't work as the record hotkey](#q-f5-doesnt-work-as-the-record-hotkey)
  - [Q: Can I use the fn key?](#q-can-i-use-the-fn-key)
- [Text injection](#text-injection)
  - [Q: I dictate but nothing appears anywhere](#q-i-dictate-but-nothing-appears-anywhere)
  - [Q: The transcript pastes into my terminal instead of the app I was in](#q-the-transcript-pastes-into-my-terminal-instead-of-the-app-i-was-in)
  - [Q: Why is dictation ~1 second slower on Sequoia?](#q-why-is-dictation-1-second-slower-on-sequoia)
  - [Q: smoke_inject.py runs but nothing appears in TextEdit / Notes](#q-smoke_injectpy-runs-but-nothing-appears-in-textedit--notes)
- [Config](#config)
  - [Q: Where is my config file?](#q-where-is-my-config-file)
  - [Q: "Open Config File" menu item does nothing](#q-open-config-file-menu-item-does-nothing)
- [Transcription](#transcription)
  - [Q: First run takes forever — is it hung?](#q-first-run-takes-forever--is-it-hung)
  - [Q: How do I change the Whisper model?](#q-how-do-i-change-the-whisper-model)
- [Debugging](#debugging)
  - [Q: How do I see what whisperlite is doing?](#q-how-do-i-see-what-whisperlite-is-doing)
- [Before you file a bug](#before-you-file-a-bug)

---

## Permissions & TCC

### Q: "This process is not trusted!" warning from pynput

**Symptom:** Running `python tests/smoke/smoke_hotkey.py` prints a warning
like `This process is not trusted! Input event monitoring will not be
possible...` from pynput, and the hotkey is never received within the
30-second timeout.

**Cause:** The Python binary running whisperlite has not been granted
Input Monitoring and/or Accessibility permissions in macOS System Settings.
pynput needs both to capture and synthesize keyboard events globally.

**Fix:**

1. Find the actual Python binary path that your venv resolves to:

   ```bash
   .venv/bin/python3 -c "import os, sys; print(os.path.realpath(sys.executable))"
   ```

   Typical output:

   ```
   /opt/homebrew/Cellar/python@3.10/3.10.17/Frameworks/Python.framework/Versions/3.10/bin/python3.10
   ```

2. Open **System Settings → Privacy & Security → Input Monitoring**.
3. Click the `+` button, press `Cmd+Shift+G` to bring up "Go to folder,"
   paste the full path from step 1, and select `python3.10`.
4. Toggle it ON.
5. Repeat steps 2–4 in **Privacy & Security → Accessibility**. Both panes
   must have `python3.10`, both must be toggled ON.

Then re-run the smoke test. See also the next question if it still fails.

---

### Q: I granted python3.10 Accessibility but it still says not trusted

**Symptom:** Same `not trusted` error as above, but `python3.10` is clearly
listed in both Accessibility and Input Monitoring with the toggles ON.
Re-running the smoke test still fails.

**Cause:** macOS 15 (Sequoia) introduced stricter "responsible process"
enforcement. When a child process (your Python) tries to use a TCC-gated
API, macOS checks permissions at **two levels**:

1. Is the binary itself trusted? (`python3.10` — yes.)
2. Is the binary's *responsible process* — the app that launched it, i.e.
   your terminal — also trusted?

If your terminal app (iTerm2, Terminal.app, Ghostty, Warp, etc.) isn't in
the Accessibility list, the check fails at step 2 even though Python
itself has the grant.

**Fix:**

1. Open **System Settings → Privacy & Security → Accessibility**.
2. Click `+`, navigate to your terminal app in `/Applications/` (e.g.
   `/Applications/iTerm.app` or `/Applications/Utilities/Terminal.app`),
   select it, and toggle ON.
3. Re-run the smoke test in the same terminal session. It should now work.

You do **not** need to restart the terminal — each `python …` invocation
is a fresh process that reads current TCC state at launch.

**If you don't want to modify your primary terminal's grants** (e.g.
because you have long-running sessions and want to keep them pristine),
use a separate terminal app. macOS Terminal.app is a different app bundle
from iTerm2, so granting Terminal.app Accessibility has zero effect on
iTerm2. Open Terminal.app from Spotlight, grant it permissions, run the
smoke tests from there. Your iTerm2 workflow stays untouched.

---

### Q: What's the difference between Input Monitoring and Accessibility?

**Symptom:** You granted one of the two and something still doesn't work.

**Cause:** The two TCC categories cover different operations:

- **Input Monitoring** lets a process *read* global keystrokes. This is
  how whisperlite captures your hotkey (e.g. Ctrl+Cmd+R) while you're
  typing in some other app.
- **Accessibility** lets a process *synthesize* keystrokes and control
  other apps. This is how whisperlite posts Cmd+V to paste the
  transcript, and how it brings the target app to the front.

**Fix:** whisperlite needs both. Granting only Input Monitoring will
capture hotkeys fine but the paste will silently fail. Granting only
Accessibility will paste fine but the hotkey listener will never fire.
Add `python3.10` (and your terminal app — see previous question) to
both panes.

---

### Q: Do I have to quit my terminal after granting permissions?

**Symptom:** You're wondering whether to restart iTerm2 / Terminal after
adding it to Accessibility.

**Cause:** TCC grants take effect at process launch. Existing processes
keep whatever permissions they had when they started, but new child
processes read current TCC state.

**Fix:** You don't need to quit the terminal. Just run your `python …`
command again — the new Python process will pick up the new grants
immediately. If you're paranoid, open a fresh tab and re-run from there.

---

### Q: I upgraded Homebrew Python and permissions stopped working

**Symptom:** After `brew upgrade python@3.10` (or installing a new minor
version), the `not trusted` warning returns even though you previously
granted `python3.10`.

**Cause:** TCC grants attach to the *exact resolved binary path*.
Homebrew's Cellar path includes the version number:

```
/opt/homebrew/Cellar/python@3.10/3.10.17/...
```

After an upgrade, the path becomes `3.10.18/...`, which is a different
binary from TCC's perspective. The old grant is now orphaned.

**Fix:** Re-add the new binary path to Input Monitoring and Accessibility,
following the first question in this section. Optionally remove the
orphaned old-version entry from both lists to keep them clean.

---

## Hotkey

### Q: F5 doesn't work as the record hotkey

**Symptom:** Pressing F5 when whisperlite is running doesn't start
recording. The menubar stays 🎤 idle.

**Cause:** On macOS 14+ (Sonoma and later), Apple changed how function-key
events are routed, and pynput's `GlobalHotKeys` listener frequently fails
to receive them — even when Input Monitoring is granted correctly. Some
Macs also have F5 bound to system Dictation, Mission Control "Show all
windows", or backlight control, which intercepts the event before
userspace hotkey listeners see it.

**Fix:** Change your hotkey to a modifier combo, which is much more
reliable. Edit `whisperlite.toml` in the project root (see the Config
section for file paths) and set:

```toml
[hotkey]
record = "<ctrl>+<cmd>+r"
```

Good modifier-combo choices:

- `<ctrl>+<cmd>+r`
- `<ctrl>+<alt>+<space>`
- `<cmd>+<shift>+<space>`

Avoid combinations that conflict with system shortcuts: Cmd+Space is
Spotlight, Cmd+Tab is the app switcher, etc.

---

### Q: Can I use the fn key?

**Symptom:** You want to use `fn` alone as the dictation hotkey because
it's ergonomic and otherwise unused.

**Cause:** pynput cannot capture `fn` on macOS. `fn` is a special HID-layer
flag, not a regular keyboard event, and pynput's `GlobalHotKeys` doesn't
expose it. Whispr Flow works around this by using low-level Quartz event
taps to handle `fn` directly.

**Fix:** Use a modifier combo instead (see previous question). Adding
`fn` support to whisperlite via a Quartz event tap is tracked as a future
TODO but is not available in v1.

---

## Text injection

### Q: I dictate but nothing appears anywhere

**Symptom:** You press Ctrl+Cmd+R in Notes, speak, press again, and
nothing happens. No text appears anywhere.

**Cause:** Missing Accessibility grant for keystroke synthesis. Input
Monitoring covers *capturing* keystrokes; *synthesizing* them (for the
Cmd+V paste) requires Accessibility. If Accessibility is missing for
either `python3.10` or your terminal app (the responsible process under
Sequoia), the paste is silently refused by macOS.

**Fix:** Verify both panes have both entries:

- **Input Monitoring**: `python3.10`
- **Accessibility**: `python3.10` *and* your terminal app

See the Permissions & TCC section above for exact steps. Once both panes
look right, re-run `python tests/smoke/smoke_inject.py` to confirm the
paste works.

As a sanity check, after running whisperlite and dictating something,
run `pbpaste` in your terminal. If it shows your transcript, the
pasteboard write worked — the problem is purely the synthesized Cmd+V
being blocked, and you can always paste manually with Cmd+V as a
fallback.

---

### Q: The transcript pastes into my terminal instead of the app I was in

**Symptom:** You press Ctrl+Cmd+R in Notes, speak, switch to your
terminal mid-recording, press again, and the text pastes into the
terminal instead of Notes.

**Cause:** Sequoia focus-stealing protection. Even with correct
permissions, macOS 15 refuses to let apps forcibly transfer keyboard
focus away from the user's currently-active app. When whisperlite calls
`NSRunningApplication.activate(options:)` to bring Notes to the front
before pasting, Sequoia silently blocks it: Notes' window comes forward
visually, but keyboard focus stays on the terminal (or whatever was
last user-active), so the subsequent Cmd+V lands in the wrong app.

**Fix:** whisperlite already handles this — `inject.py` has a fallback
that detects the blocked activation and retries via
`osascript -e 'tell application "X" to activate'`, which sends an
AppleEvent that Sequoia honors. You should see this in
`~/Library/Logs/whisperlite.log`:

```
INFO whisperlite.inject: native activation blocked, trying AppleScript fallback for 'Notes'
```

Troubleshooting steps:

1. Check the log for the line above. If it's absent, the fallback didn't
   run — likely a code regression; file a bug.
2. If the line is present but the paste still goes to the wrong app,
   there's a deeper Sequoia lockdown (rare — happens with certain
   enterprise MDM profiles that disable AppleEvents). In that case, the
   transcribed text is copied to your clipboard and you can press Cmd+V
   manually to paste.
3. As a workflow tip, don't switch apps mid-recording. whisperlite
   captures the target app at record-start time; switching apps while
   speaking just confuses things.

---

### Q: Why is dictation ~1 second slower on Sequoia?

**Symptom:** End-to-end inject latency on macOS 15 feels sluggish
compared to older macOS — roughly 1.1s instead of ~280ms.

**Cause:** The AppleScript activation fallback described in the previous
question. whisperlite has to poll (up to 500ms) for native activation
to succeed before giving up and invoking `osascript`, which itself adds
another few hundred milliseconds of overhead.

**Fix:** This is a known cost of Sequoia's focus-stealing protection and
is tracked as a future optimization — specifically, reducing the poll
timeout and/or skipping the native attempt entirely on Sequoia. For now,
it's the price of reliable cross-app paste on macOS 15.

---

### Q: smoke_inject.py runs but nothing appears in TextEdit / Notes

**Symptom:** `python tests/smoke/smoke_inject.py` exits with
`Done. Verify the text appeared in Notes` but the note is empty.

**Cause:** Either:

- **(a)** the target app (Notes) didn't have keyboard focus when the
  Cmd+V was synthesized, or
- **(b)** Accessibility is missing for keystroke synthesis.

Most commonly (a): if the script captures the focused app *at inject
time* rather than at record-start time, and you switched back to the
terminal to press Enter in the middle of the test, the capture returns
the terminal's PID and the paste goes to the terminal (where Cmd+V does
nothing visible in zsh).

**Fix:** The current `smoke_inject.py` handles this by re-activating the
target app after you press Enter and sleeping 1.5s before capturing
focus. If the bug persists:

1. Check the printed `captured focused app pid=XXXX` line. Compare to
   `pgrep -ix Notes` — if they match, focus capture is correct. If not,
   the timing window needs widening.
2. Before running the script, open Notes and click inside a note body so
   the cursor is placed there. Notes remembers the cursor position when
   re-activated.
3. Check the actual clipboard contents after the script exits:

   ```bash
   pbpaste
   ```

   If it shows the transcript, the pasteboard write worked and the
   paste is failing (Accessibility issue — see the first question in
   this section). If it shows something else, the pasteboard write
   failed entirely.

---

## Config

### Q: Where is my config file?

**Symptom:** You want to change a setting but don't know which file to
edit, or you edited `~/.config/whisperlite/config.toml` but your changes
are ignored.

**Cause:** whisperlite searches for its config in this order:

1. `$WHISPERLITE_CONFIG` environment variable, if set
2. `whisperlite.toml` in the current working directory (the project root,
   when you run `python -m whisperlite` from the repo)
3. `~/.config/whisperlite/config.toml` (XDG-style, for future PyPI
   distribution)

On first clone, none of these exist, so whisperlite falls back to
compiled-in defaults. If you want to edit settings, you must **create**
a config file first.

**Fix:**

```bash
cp config.example.toml whisperlite.toml
# edit whisperlite.toml
```

Then relaunch whisperlite. It will log the path it loaded from:

```
INFO whisperlite.config: loaded config from /Users/.../whisperlite/whisperlite.toml
```

Note: `whisperlite.toml` at the project root is gitignored — it's your
personal config and should not be committed. The committed
`config.example.toml` is the template for new users.

---

### Q: "Open Config File" menu item does nothing

**Symptom:** Clicking "Open Config File" in the whisperlite menubar
prints `The file /Users/.../config.toml does not exist` and nothing
opens.

**Cause:** No config file exists yet in any of the search-path locations
(see the previous question), so there's nothing to open. whisperlite is
running on compiled-in defaults.

**Fix:** Create a config file from the example:

```bash
cp config.example.toml whisperlite.toml
```

Then restart whisperlite. The "Open Config File" menu item is aware of
the search order and will open whichever file was actually loaded.

---

## Transcription

### Q: First run takes forever — is it hung?

**Symptom:** First run of whisperlite (or `smoke_transcribe.py`) appears
to hang for minutes with no output, or shows slow Hugging Face download
progress.

**Cause:** mlx-whisper downloads models from Hugging Face on first use.
The default model (`mlx-community/whisper-medium-mlx`) is ~1.5 GB. On a
slow connection or a cold Hugging Face cache, the download can take
2–10 minutes.

**Fix:** Be patient on first run. Subsequent runs reuse the cached model
and start in ~2 seconds. If you want faster setup testing, use a smaller
model — see the next question.

---

### Q: How do I change the Whisper model?

**Symptom:** You want a different quality / speed / download-size
trade-off.

**Cause:** The default is tuned for quality (`medium`, ~1.5 GB). For
setup testing or weaker hardware, a smaller model is faster.

**Fix:** Edit `whisperlite.toml`:

```toml
[model]
name = "mlx-community/whisper-tiny-mlx"   # ~75 MB, much faster to download
```

Quality drops significantly with `tiny` — use it for setup testing only,
then switch back to `medium` or `large-v3` for real dictation.

---

## Debugging

### Q: How do I see what whisperlite is doing?

**Symptom:** Something is wrong with whisperlite and you want more
information than the menubar icon shows.

**Cause:** The menubar icon only conveys state at a glance; the real
detail is in the log file.

**Fix:** Tail the log:

```bash
tail -f ~/Library/Logs/whisperlite.log
```

The log captures every state transition, every captured target PID,
every permission probe, and every error with full traceback. When
something unexpected happens, the log line immediately before and after
usually tells you most of the story. Specifically watch for:

- `state -> ERROR` lines — followed by the error message
- `captured target_pid=…` lines — confirms focus capture at record-start
- Lines from `whisperlite.inject` — activation fallback, pasteboard
  guards, etc.
- Lines from `whisperlite.hotkey` — listener start/stop
- `WARNING`-level lines — usually recoverable issues that are still
  worth attention

Include the relevant tail in any bug report.

---

## Before you file a bug

1. Tail `~/Library/Logs/whisperlite.log` and capture the lines around
   the failure.
2. Confirm both `python3.10` and your terminal app are in **Input
   Monitoring** and **Accessibility** under System Settings → Privacy
   & Security.
3. Confirm the Python binary path matches the one currently granted
   (see the Homebrew upgrade question above).
4. Note your macOS version — Sequoia (15.x) behaves differently from
   Sonoma and earlier, and the answer often depends on it.

Then open an issue with the log tail, your macOS version, and the
command you ran.
