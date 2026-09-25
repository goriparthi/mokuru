# mokuru

Lights and LCD for the **MOKURU AK8753** keyboard, with **Claude Code** integration.
Runs on Windows, macOS and Linux.

- Your keys show what Claude is doing: Claude-orange while it works (with the
  context window filling up across F1–F12), red when it needs your permission,
  a green flash when it's done, then your own lighting comes back.
- The 135×240 LCD shows a usage card: model, session, context %, cost, lines changed.
- Set lighting effects, put pictures and animations on the LCD, set the clock.
- **Ctrl + dial = app switcher** (Windows): hold Ctrl and turn to walk through
  windows like Alt+Tab, release Ctrl to pick one; Ctrl + press opens Task View.
  The dial alone is still volume.
- A tray icon (optional) shows Claude's state and has quick controls.

## Install

```sh
pipx install "git+https://github.com/goriparthi/mokuru.git#egg=mokuru[tray]"
# or, from a clone:  pip install -e ".[tray]"

mokuru info                 # finds the keyboard (plug it in by USB cable)
mokuru install hooks        # Claude Code hooks in ~/.claude/settings.json
mokuru install statusline   # feeds the LCD usage card (see below)
mokuru install autostart    # start the tray/daemon at login
```

Linux also needs a udev rule so you can open the keyboard without root:
`mokuru install udev` prints the two commands (a copy is in `contrib/`).

## Everyday use

```sh
mokuru light wave                         # rainbow wave (no --color = rainbow)
mokuru light static --color 00ffcc        # any colour
mokuru light breathing --color d97757 --speed 1
mokuru light off
mokuru image photo.jpg --slot 0           # still picture, cropped to fit (~20 s)
mokuru gif cat.gif                        # animation, up to 5 frames (~20 s per frame)
mokuru gif claude                         # built-in Claude spark animation
mokuru lcd usage | off                    # usage card on the LCD
mokuru clock                              # set the LCD clock (the daemon also does this daily)
mokuru pause | resume                     # stop/start reacting to Claude Code
mokuru status                             # daemon state as JSON
mokuru start | stop | tray | daemon
```

`mokuru light …` sets *your* lighting: it's what the keyboard returns to when
Claude is idle.

## How it works

A small daemon owns the keyboard. It listens on `127.0.0.1` only (port 38917,
or the next free one; the port is written to `~/.mokuru/daemon.port`) and
accepts JSON only, so web pages can't drive it. The CLI and the Claude Code
hooks talk to it, and start it if it isn't running.

| Claude Code | Keys |
|---|---|
| prompt submitted | working: per-key Claude-orange, Esc bright, F1–F12 = context used |
| permission prompt | fast red breathing |
| tool finished after a permission | back to working |
| stopped | green for 4 s, then your lighting |

With several Claude sessions open, the most urgent one wins
(needs-you > working > done).

### Ctrl + dial

The dial sends ordinary Volume Up/Down/Mute keys, and the keyboard's firmware
ignores its Fn layer for the dial, so this can't be done on the keyboard itself.
Instead the daemon installs a Windows low-level keyboard hook: with Ctrl held,
dial clicks are swallowed and turned into a held-Alt Tab / Shift+Tab sequence.
It only works while the daemon runs (`mokuru install autostart`). Turn it off
with `"dial_switcher": false`. macOS and Linux aren't supported yet.

### Status line

Claude Code gives its status-line command a JSON payload with the model,
context window and cost. mokuru reads it from `~/.mokuru/status.json`.
`mokuru install statusline` wraps your existing status line with
`mokuru tap -- <your command>`. If your status line is a bash script, it's
cheaper to add one line after it reads stdin into `$payload`:

```sh
mkdir -p "$HOME/.mokuru" && printf '%s' "$payload" > "$HOME/.mokuru/status.json"
```

## Settings

`~/.mokuru/config.json` (created on first save; defaults shown):

```json
{
  "port": 38917,
  "claude_lighting": true,
  "per_key": true,
  "done_hold": 4.0,
  "dial_switcher": true,
  "colors": {"working": [217, 119, 87], "attention": [255, 0, 0], "done": [0, 220, 60]},
  "lcd": {"enabled": true, "slot": 0, "min_interval": 300}
}
```

## Hardware notes and limits

- **Keyboard:** MOKURU AK8753, USB `3151:5002`, vendor device 3177 (ROYUAN gen2
  command set, yc3123 chip). Other ROYUAN boards speak similar dialects but
  differ in the details; this package checks the device ID before writing.
- **Wired only for the LCD.** Screen frames need the USB cable.
- **Flash wear.** Per-key patterns and LCD frames are written to the keyboard's
  flash. mokuru spaces flash writes at least 10 s apart, re-uploads the per-key
  pattern only when the context bar gains or loses a key, and refreshes the usage
  card at most every 5 minutes and only when something visible changed.
  Whole-board lighting changes are cheap and instant.
- **LCD updates are slow**, about 20 s for a full frame. A smaller box doesn't
  help: it replaces the picture rather than patching it.
- **Animations are experimental.** Frames go into slots 1..N and the keyboard
  loops them, but the playback layout isn't fully worked out yet.
- **Never sent:** `0xAC` (erases every stored picture), `0x7F`/`0x30` (firmware
  boot entry). `mokuru.device.packet()` refuses them.

## Credits

The protocol comes from the reverse-engineering notes in
[sharkfin](https://github.com/dniminenn/sharkfin) (`docs/PROTOCOL.md`), plus
the keyboard's own responses. This is an independent implementation.

## Development

```sh
pip install -e ".[tray,dev]"
pytest              # no keyboard needed
```
