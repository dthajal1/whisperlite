# whisperlite

A minimal, fully-local macOS voice dictation tool. Double-tap Option, speak, double-tap again — your transcribed text appears at the cursor. No cloud, no subscription, no account.

Built on [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper) for on-device transcription on Apple Silicon.

## Requirements

- macOS 12+ on Apple Silicon
- Python 3.10+

## Install

```bash
git clone https://github.com/dirajthajali/whisperlite.git
cd whisperlite
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m whisperlite
```

First launch downloads the default Whisper model (~1.5 GB) and triggers macOS prompts for **Microphone**, **Input Monitoring**, and **Accessibility**. Grant all three.

## Usage

Double-tap **Option** to start recording, double-tap again to stop. Press **Escape** at any point to cancel.

To customize the hotkey, model, sounds, or recording cap:

```bash
cp whisperlite.example.toml whisperlite.toml
# then edit whisperlite.toml
```

`whisperlite.toml` is gitignored, so your personal settings stay out of version control.

## Troubleshooting

See [FAQ.md](FAQ.md). When something's off, tail `~/Library/Logs/whisperlite.log`.

## License

MIT — see [LICENSE](LICENSE).
