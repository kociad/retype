# retyper_gui.py
# Windows RDP-safe fake "copy-paste" typer with live ETA
# pip install keyboard pyperclip
# Run as Administrator

import sys
import time
import threading
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import filedialog, messagebox

import keyboard
import pyperclip

IS_WINDOWS = sys.platform.startswith("win")
ESC = "\x1b"

# ---------------------- Windows Unicode typing backend -----------------------

INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_KEYUP    = 0x0002
KEYEVENTF_UNICODE  = 0x0004
VK_RETURN          = 0x0D

if hasattr(wintypes, "ULONG_PTR"):
    ULONG_PTR = wintypes.ULONG_PTR
else:
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

if IS_WINDOWS:
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx",          wintypes.LONG),
            ("dy",          wintypes.LONG),
            ("mouseData",   wintypes.DWORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg",    wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [
            ("type", wintypes.DWORD),
            ("u",    _INPUTUNION),
        ]

    SendInput = ctypes.windll.user32.SendInput
    SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    SendInput.restype  = wintypes.UINT

    GetLastError = ctypes.windll.kernel32.GetLastError
    FormatMessageW = ctypes.windll.kernel32.FormatMessageW
    FORMAT_MESSAGE_FROM_SYSTEM = 0x00001000

    def _last_error_msg():
        err = GetLastError()
        if not err:
            return "0"
        buf = ctypes.create_unicode_buffer(1024)
        n = FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM, None, err, 0, buf, len(buf), None)
        msg = buf.value.strip() if n else f"WinError {err}"
        return f"{err} ({msg})"

    def _send_input(ki: KEYBDINPUT):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = ki
        n = SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        return n == 1

    def send_vk(vk: int):
        down = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=ULONG_PTR(0))
        up   = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=ULONG_PTR(0))
        if not _send_input(down):
            raise OSError(f"SendInput VK down failed: {_last_error_msg()}")
        if not _send_input(up):
            raise OSError(f"SendInput VK up failed: {_last_error_msg()}")

    def send_unicode_unit(unit: int):
        kd = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=ULONG_PTR(0))
        ku = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=ULONG_PTR(0))
        if not _send_input(kd):
            raise OSError(f"SendInput UNICODE down failed: {_last_error_msg()}")
        if not _send_input(ku):
            raise OSError(f"SendInput UNICODE up failed: {_last_error_msg()}")

def type_text_unicode(text, char_delay, line_delay, stop_event, status_cb, bracketed=False):
    if not IS_WINDOWS:
        raise RuntimeError("Unicode SendInput backend is Windows-only.")

    t = text.replace("\r\n", "\n").replace("\r", "\n")
    utf16 = t.encode("utf-16-le")

    def responsive_sleep(seconds):
        end = time.time() + seconds
        while time.time() < end:
            if stop_event.is_set():
                return True
            time.sleep(0.005)
        return False

    def units():
        for i in range(0, len(utf16), 2):
            yield int.from_bytes(utf16[i:i+2], "little")

    if bracketed:
        for ch in ESC + "[200~":
            send_unicode_unit(ord(ch))

    text_i = 0
    for u in units():
        if stop_event.is_set():
            status_cb("Stopped.")
            return
        ch = t[text_i]
        text_i += 1
        if ch == "\n":
            send_vk(VK_RETURN)
            if line_delay and responsive_sleep(line_delay):
                status_cb("Stopped."); return
            continue
        send_unicode_unit(u)
        if char_delay and responsive_sleep(char_delay):
            status_cb("Stopped."); return

    if bracketed:
        for ch in ESC + "[201~":
            send_unicode_unit(ord(ch))

# ------------------------------- Worker thread --------------------------------

class RetypeWorker(threading.Thread):
    def __init__(self, text, start_delay, char_delay, line_delay, mode, bracketed, stop_event, status_cb, eta_text):
        super().__init__(daemon=True)
        self.text = text
        self.start_delay = max(0.0, start_delay)
        self.char_delay = max(0.0, char_delay)
        self.line_delay = max(0.0, line_delay)
        self.mode = mode
        self.bracketed = bracketed
        self.stop_event = stop_event
        self.status_cb = status_cb
        self.eta_text = eta_text  # string like "ETA: 12.3s (350 chars, 10 lines)"

    def _countdown(self):
        remaining = self.start_delay
        while remaining > 0:
            if self.stop_event.is_set():
                self.status_cb("Stopped before start.")
                return False
            self.status_cb(f"Starting in {remaining:.1f}s… | {self.eta_text}  (Pause/Break to stop)")
            time.sleep(min(0.1, remaining))
            remaining -= 0.1
        return True

    def run(self):
        if not self._countdown():
            return

        if self.mode == "paste":
            try:
                pyperclip.copy(self.text)
                self.status_cb("Sending Ctrl+V…")
                keyboard.send("ctrl+v")
                self.status_cb("Done (pasted).")
            except Exception as e:
                self.status_cb(f"Clipboard paste failed: {e}")
            return

        self.status_cb("Typing… (Pause/Break to stop)")
        try:
            type_text_unicode(
                text=self.text,
                char_delay=self.char_delay,
                line_delay=self.line_delay,
                stop_event=self.stop_event,
                status_cb=self.status_cb,
                bracketed=self.bracketed
            )
            if not self.stop_event.is_set():
                self.status_cb("Done (typed).")
        except Exception as e:
            self.status_cb(f"Typing failed: {e}")

# ----------------------------------- UI ---------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("Retype Helper (RDP-safe)")

        self.worker = None
        self.stop_event = threading.Event()

        wrap = tk.Frame(root, padx=10, pady=10)
        wrap.pack(fill="both", expand=True)

        # Source
        srcRow = tk.Frame(wrap); srcRow.pack(fill="x", pady=(0, 6))
        tk.Label(srcRow, text="Source:").pack(side="left")
        self.srcVar = tk.StringVar(value="editor")
        tk.Radiobutton(srcRow, text="Editor", variable=self.srcVar, value="editor", command=self.update_eta).pack(side="left")
        tk.Radiobutton(srcRow, text="Clipboard", variable=self.srcVar, value="clipboard", command=self.update_eta).pack(side="left", padx=(6,0))
        tk.Button(srcRow, text="Load from file…", command=self.load_file).pack(side="right")

        # Editor
        self.txt = tk.Text(wrap, height=16, width=96, wrap="none", undo=True, font=("Consolas", 10))
        self.txt.pack(fill="both", expand=True)
        self.txt.bind("<<Modified>>", self._on_text_change)

        # Mode & options
        modeRow = tk.Frame(wrap); modeRow.pack(fill="x", pady=(8, 6))
        tk.Label(modeRow, text="Mode:").pack(side="left")
        self.modeVar = tk.StringVar(value="type")
        tk.Radiobutton(modeRow, text="Type keys (Unicode, safest)", variable=self.modeVar, value="type", command=self.update_eta).pack(side="left")
        tk.Radiobutton(modeRow, text="Ctrl+V paste (fastest)", variable=self.modeVar, value="paste", command=self.update_eta).pack(side="left", padx=(8,0))
        self.bracketVar = tk.BooleanVar(value=False)
        tk.Checkbutton(modeRow, text="Bracketed paste (bash/zsh)", variable=self.bracketVar).pack(side="left", padx=(12,0))

        # Params 1
        params = tk.Frame(wrap); params.pack(fill="x", pady=(0, 6))
        tk.Label(params, text="Start delay (s):").pack(side="left")
        self.delay_entry = tk.Entry(params, width=6); self.delay_entry.insert(0, "2.5")
        self.delay_entry.pack(side="left", padx=(4, 12)); self.delay_entry.bind("<KeyRelease>", self._on_param_change)

        tk.Label(params, text="Per-char delay (s):").pack(side="left")
        self.char_delay_entry = tk.Entry(params, width=6); self.char_delay_entry.insert(0, "0.1")
        self.char_delay_entry.pack(side="left", padx=(4, 12)); self.char_delay_entry.bind("<KeyRelease>", self._on_param_change)

        # Params 2
        params2 = tk.Frame(wrap); params2.pack(fill="x", pady=(0, 6))
        tk.Label(params2, text="Per-line delay (s):").pack(side="left")
        self.line_delay_entry = tk.Entry(params2, width=6); self.line_delay_entry.insert(0, "0.060")
        self.line_delay_entry.pack(side="left", padx=(4, 12)); self.line_delay_entry.bind("<KeyRelease>", self._on_param_change)

        # Buttons
        btns = tk.Frame(wrap); btns.pack(fill="x")
        self.start_btn = tk.Button(btns, text="Start (Ctrl+Enter)", command=self.start); self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(btns, text="Stop (Pause/Break)", command=self.stop, state="disabled"); self.stop_btn.pack(side="left", padx=(8, 0))

        # ETA row (persistent)
        etaRow = tk.Frame(wrap); etaRow.pack(fill="x", pady=(4, 2))
        self.eta_var = tk.StringVar(value="ETA: —")
        tk.Label(etaRow, textvariable=self.eta_var, anchor="w").pack(side="left")

        # Status bar
        self.status_var = tk.StringVar(value="Ready. Paste or load text, pick mode, then Ctrl+Enter.")
        tk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(4, 8))

        # Hotkeys
        keyboard.add_hotkey("ctrl+enter", self.start)
        keyboard.add_hotkey("pause", self.stop)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # initial ETA
        self.update_eta()

    # ---------- ETA helpers ----------
    def _get_text_for_eta(self):
        if self.srcVar.get() == "clipboard":
            try:
                t = pyperclip.paste()
                return t if isinstance(t, str) else ""
            except Exception:
                return ""
        return self.txt.get("1.0", "end-1c")

    def estimate_time(self, text, start_delay, char_delay, line_delay):
        n_chars = len(text)
        n_lines = text.count("\n")
        total = start_delay + (n_chars * char_delay) + (n_lines * line_delay)
        return total, n_chars, n_lines

    def update_eta(self, *_):
        try:
            start_delay = float(self.delay_entry.get())
            char_delay  = float(self.char_delay_entry.get())
            line_delay  = float(self.line_delay_entry.get())
        except ValueError:
            self.eta_var.set("ETA: —")
            return
        text = self._get_text_for_eta()
        est, n_chars, n_lines = self.estimate_time(text, start_delay, char_delay, line_delay)
        self.eta_var.set(f"ETA: {est:.1f}s  ({n_chars} chars, {n_lines} lines)")

    def _on_text_change(self, event):
        # reset modified flag and recalc ETA
        self.txt.edit_modified(False)
        self.update_eta()

    def _on_param_change(self, event):
        self.update_eta()

    # ---------- Actions ----------
    def load_file(self):
        path = filedialog.askopenfilename(
            title="Open text file",
            filetypes=[("Text files","*.txt;*.log;*.md;*.json;*.csv;*.py;*.cfg;*.ini;*.*"),("All files","*.*")]
        )
        if not path: return
        try:
            for enc in ("utf-8","utf-8-sig","utf-16","cp1250","latin-1"):
                try:
                    with open(path,"r",encoding=enc,newline="") as f: content=f.read()
                    break
                except UnicodeDecodeError: continue
            self.txt.delete("1.0","end"); self.txt.insert("1.0",content)
            self.srcVar.set("editor")
            self.status("Loaded file.")
            self.update_eta()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{e}")

    def start(self):
        if self.worker and self.worker.is_alive(): return

        src = self.srcVar.get()
        if src=="clipboard":
            try:
                text = pyperclip.paste()
                if not isinstance(text,str): text=""
            except Exception as e:
                messagebox.showerror("Clipboard Error", f"Could not read clipboard:\n{e}"); return
        else:
            text = self.txt.get("1.0","end-1c")
        if not text: self.status("Nothing to type."); return

        try:
            start_delay=float(self.delay_entry.get()); char_delay=float(self.char_delay_entry.get()); line_delay=float(self.line_delay_entry.get())
        except ValueError:
            messagebox.showerror("Invalid input","Please enter numeric delays."); return

        # Compute ETA once more (for countdown display)
        est,n_chars,n_lines = self.estimate_time(text,start_delay,char_delay,line_delay)
        eta_text = f"ETA: {est:.1f}s ({n_chars} chars, {n_lines} lines)"
        self.eta_var.set(eta_text)  # keep it visible

        mode=self.modeVar.get(); bracketed=bool(self.bracketVar.get())
        self.stop_event.clear(); self.start_btn.configure(state="disabled"); self.stop_btn.configure(state="normal")
        def status_cb(msg): self.root.after(0, lambda: self.status(msg))
        self.worker=RetypeWorker(text,start_delay,char_delay,line_delay,mode,bracketed if mode=="type" else False,self.stop_event,status_cb,eta_text)
        self.worker.start()

    def stop(self):
        self.stop_event.set(); self.start_btn.configure(state="normal"); self.stop_btn.configure(state="disabled"); self.status("Stopping…")

    def status(self,msg): self.status_var.set(msg)

    def on_close(self):
        try: keyboard.remove_hotkey("ctrl+enter")
        except: pass
        try: keyboard.remove_hotkey("pause")
        except: pass
        self.stop_event.set(); self.root.destroy()

# --------------------------------- Main ---------------------------------------

def main():
    root=tk.Tk(); app=App(root)
    root.update_idletasks()
    w,h=860,560; x=(root.winfo_screenwidth()-w)//2; y=(root.winfo_screenheight()-h)//3
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()

if __name__=="__main__": main()
