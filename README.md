# whisperlite

A minimal, fully-local macOS voice dictation tool. Double-tap Option, speak, double-tap again -- your transcribed text appears at the cursor. No cloud, no subscription, no account. Built on [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper) for on-device transcription on Apple Silicon.

## Quick start

```bash
git clone https://github.com/dirajthajali/whisperlite.git
cd whisperlite
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m whisperlite
```

First launch downloads the default Whisper model (~480 MB). Before it can record, you'll need to grant three macOS permissions — see [macOS permissions](#macos-permissions) below.

### Requirements

- macOS 12+ on Apple Silicon
- Python 3.10+

## macOS permissions

whisperlite is built to run locally on your own device — you clone, install, and run it as a Python package from your venv. That means it isn't distributed as a bundled `.app`, so macOS attaches permission grants to the *exact path* of your venv's Python binary rather than a signed app identity. You'll need to grant three permissions manually. (If you want to bundle whisperlite into a signed `.app` for broader distribution, you're welcome to fork and take it further.)

| Permission | What it's for | How to grant |
|---|---|---|
| **Microphone** | Record audio | Click **Allow** on the first-launch prompt. If no prompt fires (common on fresh installs), see [FAQ](FAQ.md#permissions--tcc). |
| **Input Monitoring** | Detect the double-tap hotkey | System Settings → Privacy & Security → Input Monitoring. Click `+`, add your venv's Python binary, toggle ON. |
| **Accessibility** | Paste the transcript (synthesize Cmd+V) | Same pane under Accessibility. Add **both** your Python binary **and** your terminal app (Terminal / iTerm / Ghostty / Warp). On macOS 15 (Sequoia), both are required — granting only Python results in a silent half-failure. |

**Find your Python binary path:**

```bash
.venv/bin/python3 -c "import os, sys; print(os.path.realpath(sys.executable))"
```

Paste that into the `+` file picker (use `Cmd+Shift+G` to paste a path).

**Why the terminal too?** For Accessibility specifically, Sequoia checks both the binary making the call *and* the terminal that launched it. Input Monitoring only needs the Python binary.

See [FAQ](FAQ.md#permissions--tcc) if: the Microphone pane shows no apps, you upgraded Homebrew Python, or the hotkey doesn't respond. For live debugging, `tail -f ~/Library/Logs/whisperlite.log`.

## Usage

| Action | How |
|---|---|
| Start recording | Double-tap **Option** |
| Stop & transcribe | Double-tap **Option** again |
| Cancel anytime | Press **Escape** |

Transcribed text is pasted at whatever cursor is active when you stop.

## Customization

whisperlite ships with sensible defaults but is designed to be forked and tweaked. All configuration lives in a single TOML file:

```bash
cp whisperlite.example.toml whisperlite.toml
# edit whisperlite.toml
```

`whisperlite.toml` is gitignored, so your personal settings stay out of version control. See [`whisperlite.example.toml`](whisperlite.example.toml) for every option (hotkey, sounds, recording cap, icons, logging, etc.).

### Changing the Whisper model

The default model is `mlx-community/whisper-small-mlx` (~480 MB). Try a few and see what fits your hardware:

| Model | Size | Notes |
|---|---|---|
| `mlx-community/whisper-tiny-mlx` | ~75 MB | Fast, lower accuracy. Good for testing setup. |
| `mlx-community/whisper-base-mlx` | ~145 MB | Lightweight, decent for short phrases. |
| `mlx-community/whisper-small-mlx` | ~480 MB | **Default.** Reasonable quality, low resource use. |
| `mlx-community/whisper-medium-mlx` | ~1.5 GB | Higher accuracy, slower. |
| `mlx-community/whisper-large-v3-mlx` | ~3 GB | Highest accuracy. Needs more RAM and is slower. |

Swap it in `whisperlite.toml` -- any `mlx-community/whisper-*-mlx` [repo on Hugging Face](https://huggingface.co/mlx-community) should work:

```toml
[model]
name = "mlx-community/whisper-large-v3-mlx"
```

### Going deeper

The codebase is small. If you want to change behavior beyond what the config supports:

```
whisperlite/
  app.py          # State machine and menubar app (core coordinator)
  transcribe.py   # Model download, warmup, and transcription
  audio.py        # Mic capture via sounddevice
  hotkey.py       # Double-tap modifier detection
  inject.py       # Clipboard + Cmd+V text injection
  config.py       # TOML loading and validation
  sounds.py       # Audio cue playback
  errors.py       # Custom exceptions
```

Fork the repo, make your changes, and `pip install -e .` to run your version.

## License

MIT -- see [LICENSE](LICENSE).
