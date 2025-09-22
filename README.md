# Retype Helper

Retype Helper is a small Windows Python tool that simulates typing or pasting text into the active window.  
It’s useful in environments like RDP sessions where normal copy-paste is blocked or unreliable.

## Quick Start

1) Install prerequisites (once):

    pip install keyboard pyperclip

2) Run the app (preferably as Administrator):

    python retyper_gui.py

3) Global hotkeys:
   - Ctrl+Enter → Start
   - Pause/Break → Stop

## Features

- Text sources: built-in editor, clipboard, or file.
- Two modes:
  - **Type keys (Unicode)** – retypes text character by character (RDP-safe).
  - **Ctrl+V paste** – pastes all text in one go (fastest if clipboard passthrough works).
- Configurable delays:
  - **Start delay** – time to switch focus to the target window before typing begins.
  - **Per-character delay** – pause after each character.
  - **Per-line delay** – extra pause after each newline (Enter).
- Optional **Bracketed paste** wrapper for shells (bash/zsh/readline).
- Live **ETA** shown based on text length and configured delays.
- Global hotkeys work from anywhere: **Ctrl+Enter** to start, **Pause/Break** to stop.

## Requirements

- Windows
- Python 3.8+
- Administrator privileges recommended (required for global hotkeys and reliable input injection).

Install:

    pip install keyboard pyperclip

## Usage

1) Start the app:

    python retyper_gui.py

2) Choose the text source:
   - Editor: type or paste text into the window.
   - Clipboard: use whatever text is currently in your clipboard.
   - Load from file…: import text from a file.

3) Choose the mode:
   - **Type keys (Unicode)** – recommended when regular paste does not work over RDP.
   - **Ctrl+V paste** – fastest if remote clipboard is available.

4) Set delays:
   - **Start delay**: seconds to wait before typing starts (for Alt-Tab and focusing the target).
   - **Per-char delay**: try 0.005–0.015 s for reliability over RDP.
   - **Per-line delay**: try 0.05–0.10 s so shells/editors keep up between lines.

5) (Optional) Enable **Bracketed paste** when typing into bash/zsh/readline shells to prevent the shell from reacting to partial input.

6) Press **Start** (or Ctrl+Enter), switch to the target window before the countdown finishes, and let it type.  
   Press **Stop** (or Pause/Break) at any time to cancel.

## Notes and Behavior

- Printable characters are injected via Windows `SendInput` in **Unicode** mode, which avoids layout/AltGr issues across RDP.
- Newlines are sent as a real **Enter** keystroke.
- The app does **not** send other special keys or key combinations (Tab, Esc, Ctrl+C, etc.) in typing mode.
- If characters are skipped, slightly increase the per-character delay.
- If lines merge or get reordered, increase the per-line delay.
- Keep the target window focused while typing.

## Troubleshooting

- Run the app **as Administrator**. Non-elevated processes can’t inject reliably into elevated targets.
- Security software with “keyboard protection” may block injection; whitelist the script if needed.
- You cannot inject into secure desktop surfaces (UAC prompts, lock screen).
- If Ctrl+V mode fails, clipboard passthrough may be disabled in the client.
