# whisperlite

A minimal, fully-local macOS voice dictation tool. Double-tap Option, speak, double-tap again -- your transcribed text appears at the cursor. No cloud, no subscription, no account.

Built on [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper) for on-device transcription on Apple Silicon.

## Quick start

```bash
git clone https://github.com/dirajthajali/whisperlite.git
cd whisperlite
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m whisperlite
```

First launch downloads the default Whisper model (~1.5 GB) and triggers macOS prompts for **Microphone**, **Input Monitoring**, and **Accessibility**. Grant all three.

### Requirements

- macOS 12+ on Apple Silicon
- Python 3.10+

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

The default model is `mlx-community/whisper-medium-mlx` (~1.5 GB). I use this on an M2 Pro and it works well for me -- your mileage may vary. Try a few and see what fits:

| Model | Size | Notes |
|---|---|---|
| `mlx-community/whisper-tiny-mlx` | ~75 MB | Fast, lower accuracy. Good for testing setup. |
| `mlx-community/whisper-base-mlx` | ~140 MB | Lightweight, decent for short phrases. |
| `mlx-community/whisper-small-mlx` | ~460 MB | Reasonable quality, low resource use. |
| `mlx-community/whisper-medium-mlx` | ~1.5 GB | **Default.** |
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

## Troubleshooting

See [FAQ.md](FAQ.md) for common issues (permissions, hotkey problems, etc.). When something's off:

```bash
tail -f ~/Library/Logs/whisperlite.log
```

## License

MIT -- see [LICENSE](LICENSE).
