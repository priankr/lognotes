import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse
from pynput import keyboard
from PIL import Image, ImageTk

from .activity import ActivityStore, ActivityTab
from ..paths import resource_path, user_data_dir, user_cache_dir
from ..transcription import (
    DEFAULT_ID as DEFAULT_MODEL_ID,
    all_ids as _all_model_ids,
    all_displays as _all_model_displays,
    display_for as _display_for_model,
    normalize_id as _normalize_model_id,
)

logger = logging.getLogger(__name__)


class _LogHandler(logging.Handler):
    """Logging handler that writes records to a tkinter ScrolledText widget."""

    def __init__(self, text_widget: ScrolledText):
        super().__init__()
        self._widget = text_widget
        fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
                                datefmt="%H:%M:%S")
        self.setFormatter(fmt)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record) + "\n"
            # Must update the widget from the main thread
            self._widget.after(0, self._append, msg, record.levelno)
        except Exception:
            self.handleError(record)

    def _append(self, msg: str, levelno: int):
        self._widget.configure(state="normal")
        tag = self._level_tag(levelno)
        self._widget.insert(tk.END, msg, tag)
        self._widget.see(tk.END)
        self._widget.configure(state="disabled")

    @staticmethod
    def _level_tag(levelno: int) -> str:
        if levelno >= logging.ERROR:
            return "error"
        if levelno >= logging.WARNING:
            return "warning"
        if levelno >= logging.INFO:
            return "info"
        return "debug"


class HotkeyCapture(tk.Toplevel):
    """Dialog for capturing a new hotkey combination."""

    def __init__(self, parent, current_hotkey: str, on_save: Callable[[str], None]):
        super().__init__(parent)
        self.title("Set Hotkey")
        self.geometry("320x220")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._on_save = on_save
        self._current_hotkey = current_hotkey
        self._captured_keys: set = set()
        self._captured_hotkey: Optional[str] = None
        self._listener: Optional[keyboard.Listener] = None

        self._setup_ui()
        self._start_capture()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        """Set up the dialog UI."""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Press your desired hotkey combination:",
            font=("Segoe UI", 10)
        ).pack(pady=(0, 10))

        self._hotkey_label = ttk.Label(
            frame,
            text="Waiting...",
            font=("Segoe UI", 14, "bold"),
            foreground="#0078D4"
        )
        self._hotkey_label.pack(pady=10)

        ttk.Label(
            frame,
            text="(Must include Ctrl, Alt, or Shift)",
            font=("Segoe UI", 8),
            foreground="gray"
        ).pack()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=(20, 0))

        ttk.Button(btn_frame, text="  Save  ", command=self._save, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="  Cancel  ", command=self._cancel, width=10).pack(side=tk.LEFT, padx=10)

    def _start_capture(self):
        """Start capturing keyboard input."""
        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._listener.start()

    def _on_key_press(self, key):
        """Handle key press during capture."""
        key_name = self._key_to_name(key)
        if key_name:
            self._captured_keys.add(key_name)
            self._update_display()

    def _on_key_release(self, key):
        """Handle key release during capture."""
        # Finalize the hotkey when a non-modifier is released
        key_name = self._key_to_name(key)
        if key_name and key_name not in ["ctrl", "shift", "alt", "cmd"]:
            self._finalize_hotkey()

    def _key_to_name(self, key) -> Optional[str]:
        """Convert pynput key to string name."""
        if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
            return "ctrl"
        if key in [keyboard.Key.shift_l, keyboard.Key.shift_r]:
            return "shift"
        if key in [keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr]:
            return "alt"
        if key in [keyboard.Key.cmd, keyboard.Key.cmd_r]:
            return "cmd"
        if hasattr(key, 'char') and key.char:
            char = key.char
            # Convert control characters back to letters (Ctrl+D = \x04, etc.)
            if len(char) == 1 and ord(char) < 32:
                char = chr(ord(char) + 96)
            return char.lower()
        if hasattr(key, 'name'):
            return key.name.lower()
        return None

    def _update_display(self):
        """Update the hotkey display."""
        if self._captured_keys:
            # Sort: modifiers first, then main key
            modifiers = []
            main_keys = []
            for k in self._captured_keys:
                if k in ["ctrl", "shift", "alt", "cmd"]:
                    modifiers.append(k)
                else:
                    main_keys.append(k)

            parts = sorted(modifiers) + main_keys
            display = "+".join(parts)
            self._hotkey_label.config(text=display.upper())

    def _finalize_hotkey(self):
        """Finalize the captured hotkey."""
        modifiers = [k for k in self._captured_keys if k in ["ctrl", "shift", "alt", "cmd"]]
        main_keys = [k for k in self._captured_keys if k not in ["ctrl", "shift", "alt", "cmd"]]

        if modifiers and main_keys:
            parts = sorted(modifiers) + [main_keys[0]]
            self._captured_hotkey = "+".join(parts)

    def _save(self):
        """Save the captured hotkey."""
        if self._captured_hotkey:
            if self._listener:
                self._listener.stop()
            self._on_save(self._captured_hotkey)
            self.destroy()
        else:
            messagebox.showwarning(
                "Invalid Hotkey",
                "Please press a valid hotkey combination\n(modifier + key)",
                parent=self
            )
            self._captured_keys.clear()
            self._hotkey_label.config(text="Waiting...")
            self._start_capture()

    def _cancel(self):
        """Cancel and close dialog."""
        if self._listener:
            self._listener.stop()
        self.destroy()


class LogNotesApp(ttk.Window):
    """Main application window for LogNotes."""

    CONFIG_FILE = str(user_data_dir() / "config.json")
    DEFAULT_CONFIG = {
        "hotkey": "ctrl+shift+d",
        "whisper_model": DEFAULT_MODEL_ID,
        "enable_grammar": True,
        "ollama_model": "llama3.2:1b",
        "ollama_host": "http://localhost:11434",
        "theme": "dark",
        "push_to_talk_mode": "hold",
        "overlay_corner": "bottom-right"
    }

    # Security: Whitelist of allowed values
    ALLOWED_WHISPER_MODELS = set(_all_model_ids())
    ALLOWED_MODIFIERS = {"ctrl", "shift", "alt", "cmd"}
    ALLOWED_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}
    # Regex for valid Ollama model names (alphanumeric, dots, colons, hyphens)
    OLLAMA_MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")

    def __init__(self):
        # Load config first to get theme
        self._config = self._load_config()

        # Initialize with theme
        theme_name = "darkly" if self._config["theme"] == "dark" else "flatly"
        super().__init__(themename=theme_name)

        self.title("LogNotes")
        self.geometry("500x750")
        self.resizable(False, False)

        # Set window icon (Windows taskbar icon).
        # Cache the generated .ico in the user cache dir — the bundle is
        # read-only when frozen (PyInstaller _MEIPASS).
        try:
            logo_path = resource_path("src/ui/assets/logo.png")
            if logo_path.exists():
                ico_path = user_cache_dir() / "logo.ico"
                if not ico_path.exists():
                    logo_img = Image.open(logo_path)
                    logo_img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
                self.iconbitmap(str(ico_path))
        except Exception as e:
            logger.warning(f"Could not set window icon: {e}")

        # State
        self._status = "ready"
        self._status_message = "Ready"

        # Callbacks (set by controller)
        self.on_hotkey_changed: Optional[Callable[[str], None]] = None
        self.on_model_changed: Optional[Callable[[str], None]] = None
        self.on_grammar_toggled: Optional[Callable[[bool], None]] = None
        self.on_theme_changed: Optional[Callable[[str], None]] = None
        self.on_push_to_talk_mode_changed: Optional[Callable[[str], None]] = None
        self.on_toggle_recording: Optional[Callable[[], None]] = None
        self.on_retry_transcription: Optional[Callable[[int, str], None]] = None
        self.is_busy: Optional[Callable[[], bool]] = None

        # Activity tab store (session-scoped, in-memory only)
        self.activity_store = ActivityStore()

        # Overlay (created after main window)
        self._overlay: Optional[tk.Toplevel] = None

        self._setup_styles()
        self._setup_ui()
        self._setup_tray()
        self._setup_overlay()

    def _setup_styles(self):
        """Configure ttk styles with custom terracotta theme."""
        style = ttk.Style()

        # Custom colors
        self.TERRACOTTA = "#C15F3C"
        self.DARK_BG = "#2b2b2b"
        self.SURFACE = "#3a3a3a"
        self.TEXT_LIGHT = "#e8e8e8"
        self.SUCCESS = "#4CAF50"
        self.WARNING = "#FFA726"
        self.INFO = "#42A5F5"

        # Custom styles
        style.configure("Status.TLabel", font=("Segoe UI", 11))
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("StatusMessage.TLabel", font=("Segoe UI", 10))

    def _show_tab(self, name: str):
        """Switch the visible tab panel."""
        for n, frame in self._tab_panels.items():
            frame.pack_forget()
        self._tab_panels[name].pack(fill=tk.BOTH, expand=True)
        for n, btn in self._tab_buttons.items():
            btn.configure(bootstyle="primary" if n == name else "secondary")
        # Reset scroll to top whenever Settings becomes visible
        if name == "Settings" and hasattr(self, "_settings_canvas"):
            self.after(10, lambda: self._settings_canvas.yview_moveto(0))

    def _setup_ui(self):
        """Set up the main UI with a manual Settings/Logs tab bar."""
        # --- Tab bar ---
        tab_bar = ttk.Frame(self, padding=(10, 4, 10, 0))
        tab_bar.pack(fill=tk.X)

        self._tab_buttons: dict = {}
        self._tab_panels: dict = {}

        # Use a smaller font to keep tab bar compact
        tab_style = ttk.Style()
        tab_style.configure("Tab.TButton", font=("Segoe UI", 9), padding=(8, 2))

        for name in ("Settings", "Activity", "Logs"):
            btn = ttk.Button(
                tab_bar,
                text=name,
                width=9,
                bootstyle="secondary",
                style="Tab.TButton",
                command=lambda n=name: self._show_tab(n)
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._tab_buttons[name] = btn

        ttk.Separator(self, orient="horizontal").pack(fill=tk.X, padx=10)

        # --- Settings panel ---
        settings_outer = ttk.Frame(self, padding=0)
        self._tab_panels["Settings"] = settings_outer

        # Scrollable canvas so the Settings content is never cut off
        _frame_bg = ttk.Style().lookup("TFrame", "background") or "#222222"
        self._settings_canvas = tk.Canvas(settings_outer, highlightthickness=0, bd=0, bg=_frame_bg)
        settings_canvas = self._settings_canvas
        settings_scroll = ttk.Scrollbar(settings_outer, orient="vertical", command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_outer.rowconfigure(0, weight=1)
        settings_outer.columnconfigure(0, weight=1)
        settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll.grid(row=0, column=1, sticky="ns")

        main_frame = ttk.Frame(settings_canvas, padding=(20, 20, 20, 20))
        _settings_window = settings_canvas.create_window((0, 0), window=main_frame, anchor="nw")

        def _on_settings_configure(event):
            bbox = settings_canvas.bbox("all")
            if bbox:
                # Ensure scrollregion is at least as tall as the canvas
                canvas_h = settings_canvas.winfo_height()
                sr_h = max(bbox[3], canvas_h)
                settings_canvas.configure(scrollregion=(0, 0, bbox[2], sr_h))

        def _on_canvas_resize(event):
            settings_canvas.itemconfig(_settings_window, width=event.width)
            # Recalculate scrollregion when canvas resizes
            bbox = settings_canvas.bbox("all")
            if bbox:
                sr_h = max(bbox[3], event.height)
                settings_canvas.configure(scrollregion=(0, 0, bbox[2], sr_h))

        main_frame.bind("<Configure>", _on_settings_configure)
        settings_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            settings_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        settings_canvas.bind("<MouseWheel>", _on_mousewheel)
        main_frame.bind("<MouseWheel>", _on_mousewheel)

        # --- Activity panel ---
        activity_outer = ttk.Frame(self)
        self._tab_panels["Activity"] = activity_outer

        # --- Logs panel ---
        logs_outer = ttk.Frame(self)
        self._tab_panels["Logs"] = logs_outer

        # Show Settings by default, then force scroll to top after full render
        self._show_tab("Settings")
        self.after(200, lambda: self._settings_canvas.yview_moveto(0))

        # Header: two-column grid — 30% logo, 70% hotkey controls
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 12))
        header_frame.columnconfigure(0, weight=3)
        header_frame.columnconfigure(1, weight=7)
        header_frame.rowconfigure(0, weight=0)

        # Logo (left column)
        logo_cell = ttk.Frame(header_frame)
        logo_cell.grid(row=0, column=0, sticky="nsew")
        try:
            logo_path = resource_path("src/ui/assets/logo.png")
            logo_img = Image.open(logo_path)
            logo_img = logo_img.resize((100, 100), Image.Resampling.LANCZOS)
            self._logo_photo = ImageTk.PhotoImage(logo_img)
            ttk.Label(logo_cell, image=self._logo_photo).pack(anchor=tk.NW)
        except Exception as e:
            logger.warning(f"Could not load logo: {e}")

        # Hotkey controls (right column)
        hotkey_frame = ttk.Frame(header_frame)
        hotkey_frame.grid(row=0, column=1, sticky="nsew")

        ttk.Label(hotkey_frame, text="Press to Record", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 4))

        hotkey_bg_frame = tk.Frame(
            hotkey_frame,
            bg=self.TERRACOTTA,
            pady=5
        )
        hotkey_bg_frame.pack(anchor=tk.W, pady=0)

        self._hotkey_var = tk.StringVar(value=self._config["hotkey"].upper())
        hotkey_display = tk.Label(
            hotkey_bg_frame,
            textvariable=self._hotkey_var,
            font=("Consolas", 18, "bold"),
            bg=self.TERRACOTTA,
            fg=self.TEXT_LIGHT,
            anchor="w"
        )
        hotkey_display.pack(anchor=tk.W)

        ttk.Button(
            hotkey_frame,
            text="Change Hotkey",
            command=self._change_hotkey,
            bootstyle="secondary"
        ).pack(anchor=tk.W, pady=(6, 0))

        # Status section
        status_frame = ttk.LabelFrame(main_frame, text="Status")
        status_frame.pack(fill=tk.X, pady=(0, 15), padx=0)

        status_inner = ttk.Frame(status_frame, padding=15)
        status_inner.pack(fill=tk.BOTH, expand=True)

        status_row = ttk.Frame(status_inner)
        status_row.pack(fill=tk.X)

        self._status_indicator = tk.Canvas(
            status_row,
            width=16,
            height=16,
            highlightthickness=0,
            bg=self.SURFACE if self._config["theme"] == "dark" else "#ffffff"
        )
        self._status_indicator.pack(side=tk.LEFT, padx=(0, 10))
        self._draw_status_indicator()

        self._status_label = ttk.Label(
            status_row,
            text=self._status_message,
            style="StatusMessage.TLabel"
        )
        self._status_label.pack(side=tk.LEFT)

        # Toggle mode start/stop icon (only visible in toggle mode)
        self._toggle_icon_label = ttk.Label(
            status_row,
            text="",
            font=("Segoe UI", 14),
            cursor="hand2"
        )
        self._toggle_icon_label.pack(side=tk.RIGHT)
        self._toggle_icon_label.bind("<Button-1>", self._on_toggle_icon_click)
        self._update_toggle_icon()

        # Push-to-Talk Mode section
        ptt_frame = ttk.LabelFrame(main_frame, text="Recording Mode")
        ptt_frame.pack(fill=tk.X, pady=(0, 15))

        ptt_inner = ttk.Frame(ptt_frame, padding=15)
        ptt_inner.pack(fill=tk.BOTH, expand=True)

        self._ptt_mode_var = tk.StringVar(value=self._config["push_to_talk_mode"])

        ttk.Radiobutton(
            ptt_inner,
            text="Hold Mode (press and hold to record)",
            variable=self._ptt_mode_var,
            value="hold",
            command=self._on_ptt_mode_change
        ).pack(anchor=tk.W, pady=2)

        ttk.Radiobutton(
            ptt_inner,
            text="Toggle Mode (press hotkey to start, press again to stop)",
            variable=self._ptt_mode_var,
            value="toggle",
            command=self._on_ptt_mode_change
        ).pack(anchor=tk.W, pady=2)

        mode_note = ttk.Label(
            ptt_inner,
            text="Both modes use the same hotkey - no separate buttons needed",
            font=("Segoe UI", 8),
            foreground="gray"
        )
        mode_note.pack(anchor=tk.W, padx=(20, 0), pady=(5, 0))

        # Model section
        model_frame = ttk.LabelFrame(main_frame, text="Transcription Model")
        model_frame.pack(fill=tk.X, pady=(0, 15))

        model_inner = ttk.Frame(model_frame, padding=15)
        model_inner.pack(fill=tk.BOTH, expand=True)

        self._model_var = tk.StringVar(
            value=_display_for_model(self._config["whisper_model"])
        )
        model_combo = ttk.Combobox(
            model_inner,
            textvariable=self._model_var,
            values=_all_model_displays(),
            state="readonly",
            width=22,
        )
        model_combo.pack(side=tk.LEFT)
        model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        ttk.Label(
            model_inner, text="(all sizes preloaded in the background; small is the quality/speed sweet spot on CPU)",
            font=("Segoe UI", 8), foreground="gray",
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Grammar section
        grammar_frame = ttk.LabelFrame(main_frame, text="Grammar Cleanup")
        grammar_frame.pack(fill=tk.X, pady=(0, 15))

        grammar_inner = ttk.Frame(grammar_frame, padding=15)
        grammar_inner.pack(fill=tk.BOTH, expand=True)

        self._grammar_var = tk.BooleanVar(value=self._config["enable_grammar"])
        grammar_check = ttk.Checkbutton(
            grammar_inner,
            text="Enable grammar cleanup",
            variable=self._grammar_var,
            command=self._on_grammar_toggle
        )
        grammar_check.pack(anchor=tk.W)

        model_label = ttk.Label(
            grammar_inner,
            text=f"Model: {self._config['ollama_model']}",
            font=("Segoe UI", 9)
        )
        model_label.pack(anchor=tk.W, padx=(20, 0), pady=(5, 0))

        # Theme toggle
        theme_frame = ttk.LabelFrame(main_frame, text="Appearance")
        theme_frame.pack(fill=tk.X, pady=(0, 15))

        theme_inner = ttk.Frame(theme_frame, padding=15)
        theme_inner.pack(fill=tk.BOTH, expand=True)

        self._theme_var = tk.StringVar(value=self._config["theme"])

        ttk.Radiobutton(
            theme_inner,
            text="🌙 Dark Mode",
            variable=self._theme_var,
            value="dark",
            command=self._on_theme_change
        ).pack(side=tk.LEFT, padx=10)

        ttk.Radiobutton(
            theme_inner,
            text="☀️ Light Mode",
            variable=self._theme_var,
            value="light",
            command=self._on_theme_change
        ).pack(side=tk.LEFT, padx=10)

        self._setup_logs_tab(logs_outer)
        self._setup_activity_tab(activity_outer)

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._quit)

    def _setup_logs_tab(self, parent: ttk.Frame):
        """Build the Logs tab content and wire up the log handler."""
        toolbar = ttk.Frame(parent, padding=(10, 8, 10, 4))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="Session Logs", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        copy_btn = ttk.Button(
            toolbar,
            text="⧉ Copy All",
            command=self._copy_logs,
            bootstyle="secondary",
            width=10
        )
        copy_btn.pack(side=tk.RIGHT)

        clear_btn = ttk.Button(
            toolbar,
            text="Clear",
            command=self._clear_logs,
            bootstyle="secondary",
            width=7
        )
        clear_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ScrolledText for log output
        log_frame = ttk.Frame(parent, padding=(10, 0, 10, 10))
        log_frame.pack(fill=tk.BOTH, expand=True)

        self._log_widget = ScrolledText(
            log_frame,
            state="disabled",
            wrap=tk.WORD,
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0
        )
        self._log_widget.pack(fill=tk.BOTH, expand=True)

        # Colour tags for log levels
        self._log_widget.tag_configure("error",   foreground="#ff6b6b")
        self._log_widget.tag_configure("warning", foreground="#ffa726")
        self._log_widget.tag_configure("info",    foreground="#42a5f5")
        self._log_widget.tag_configure("debug",   foreground="#9e9e9e")

        # Attach handler to root logger so all modules are captured
        self._log_handler = _LogHandler(self._log_widget)
        self._log_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.DEBUG)

        logger.info("Log viewer initialised — session started")

    def _setup_activity_tab(self, parent: ttk.Frame):
        """Build the Activity tab content."""
        def _on_retry(entry_id: int, model: str):
            if self.is_busy and self.is_busy():
                logger.warning(f"Retry ignored (entry {entry_id}, model {model}) — still processing previous request")
                self.set_status(self._status, "Busy — retry again when ready")
                return
            logger.info(f"Retry requested: entry {entry_id} with model '{model}'")
            if self.on_retry_transcription:
                self.on_retry_transcription(entry_id, model)

        def _on_copy(text: str):
            if not text:
                return
            self.clipboard_clear()
            self.clipboard_append(text)
            self.set_status(self._status, "Copied to clipboard")

        def _busy() -> bool:
            return bool(self.is_busy and self.is_busy())

        self._activity_tab = ActivityTab(
            parent,
            self.activity_store,
            on_retry=_on_retry,
            on_copy=_on_copy,
            is_busy=_busy,
        )

    def _copy_logs(self):
        """Copy all log text to the clipboard."""
        content = self._log_widget.get("1.0", tk.END).strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)

    def _clear_logs(self):
        """Clear the log display."""
        self._log_widget.configure(state="normal")
        self._log_widget.delete("1.0", tk.END)
        self._log_widget.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Overlay                                                              #
    # ------------------------------------------------------------------ #

    def _get_work_area(self) -> tuple[int, int, int, int]:
        """Return (left, top, right, bottom) of the screen work area (excludes taskbar)."""
        try:
            import ctypes
            import ctypes.wintypes
            SPI_GETWORKAREA = 0x0030
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            # Fallback: use screen size with a 40px taskbar allowance
            w = self.winfo_screenwidth()
            h = self.winfo_screenheight()
            return 0, 0, w, h - 40

    def _overlay_position(self, ow: int, oh: int) -> tuple[int, int]:
        """Compute (x, y) for the overlay given its size and the configured corner."""
        margin = 12
        left, top, right, bottom = self._get_work_area()
        corner = self._config.get("overlay_corner", "bottom-right")
        if corner == "top-left":
            return left + margin, top + margin
        if corner == "top-right":
            return right - ow - margin, top + margin
        if corner == "bottom-left":
            return left + margin, bottom - oh - margin
        # default: bottom-right
        return right - ow - margin, bottom - oh - margin

    def _setup_overlay(self):
        """Create the always-on-top recording status overlay."""
        self._overlay = tk.Toplevel(self)
        ov = self._overlay

        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.88)
        try:
            ov.wm_attributes("-toolwindow", True)  # Hide from taskbar on Windows
        except tk.TclError:
            pass

        # Build overlay content
        OV_W, OV_H = 130, 36
        self._overlay_canvas = tk.Canvas(
            ov, width=OV_W, height=OV_H,
            highlightthickness=1, highlightbackground="#555555",
            bg="#1e1e1e", cursor="fleur"
        )
        self._overlay_canvas.pack()

        # Status dot
        self._ov_dot = self._overlay_canvas.create_oval(10, 10, 22, 22, fill="#28a745", outline="")
        # Status text
        self._ov_text = self._overlay_canvas.create_text(
            34, 18, anchor=tk.W,
            text="Ready",
            fill="#e8e8e8",
            font=("Segoe UI", 9)
        )

        # Corner switcher: right-click cycles corners
        self._overlay_canvas.bind("<Button-3>", self._overlay_cycle_corner)

        # Drag support
        self._overlay_canvas.bind("<ButtonPress-1>",   self._overlay_drag_start)
        self._overlay_canvas.bind("<B1-Motion>",        self._overlay_drag_move)

        # Position after the event loop settles (avoids focus steal)
        ov.after(50, lambda: self._reposition_overlay(OV_W, OV_H))

    def _reposition_overlay(self, ow: int = 130, oh: int = 36):
        x, y = self._overlay_position(ow, oh)
        self._overlay.geometry(f"{ow}x{oh}+{x}+{y}")

    def _overlay_drag_start(self, event):
        self._drag_x = event.x_root - self._overlay.winfo_x()
        self._drag_y = event.y_root - self._overlay.winfo_y()

    def _overlay_drag_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._overlay.geometry(f"+{x}+{y}")

    def _overlay_cycle_corner(self, event=None):
        """Right-click: cycle the overlay through the four corners."""
        corners = ["top-left", "top-right", "bottom-right", "bottom-left"]
        current = self._config.get("overlay_corner", "bottom-right")
        next_corner = corners[(corners.index(current) + 1) % len(corners)] if current in corners else "bottom-right"
        self._config["overlay_corner"] = next_corner
        self._save_config()
        self._reposition_overlay()

    def _update_overlay(self):
        """Sync overlay dot colour and label with the current status."""
        if not self._overlay:
            return
        colors = {
            "ready":      "#28a745",
            "recording":  "#dc3545",
            "processing": "#ffc107",
        }
        labels = {
            "ready":      "Ready",
            "recording":  "Recording",
            "processing": "Processing",
        }
        color = colors.get(self._status, "#6c757d")
        label = labels.get(self._status, self._status.capitalize())
        self._overlay_canvas.itemconfig(self._ov_dot,  fill=color)
        self._overlay_canvas.itemconfig(self._ov_text, text=label)

    # ------------------------------------------------------------------ #
    # Tray                                                                 #
    # ------------------------------------------------------------------ #

    def _setup_tray(self):
        """Set up system tray icon."""
        self._tray_icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new('RGB', (64, 64), color=(0, 120, 212))
            draw = ImageDraw.Draw(image)
            draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255))

            menu = pystray.Menu(
                pystray.MenuItem("Show", self._show_from_tray),
                pystray.MenuItem("Quit", self._quit)
            )

            self._tray_icon = pystray.Icon("lognotes", image, "LogNotes", menu)
        except ImportError:
            pass

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    def _on_toggle_icon_click(self, event=None):
        if self._config["push_to_talk_mode"] == "toggle" and self.on_toggle_recording:
            self.on_toggle_recording()

    def _update_toggle_icon(self):
        if self._config["push_to_talk_mode"] == "toggle":
            if self._status == "recording":
                self._toggle_icon_label.config(text="⏹", foreground="#dc3545")
            else:
                self._toggle_icon_label.config(text="▶", foreground="#28a745")
        else:
            self._toggle_icon_label.config(text="")

    def _draw_status_indicator(self):
        self._status_indicator.delete("all")
        colors = {
            "ready":      "#28a745",
            "recording":  "#dc3545",
            "processing": "#ffc107"
        }
        color = colors.get(self._status, "#6c757d")
        self._status_indicator.create_oval(2, 2, 14, 14, fill=color, outline="")

    def set_status(self, status: str, message: Optional[str] = None):
        """Update the status display and overlay. Safe to call from any thread.

        Args:
            status: Status key (ready, recording, processing)
            message: Optional status message
        """
        default_messages = {
            "ready":      "Ready",
            "recording":  "Recording...",
            "processing": "Processing..."
        }
        display_message = message or default_messages.get(status, status)

        def _update():
            self._status = status
            self._status_message = display_message
            self._status_label.config(text=display_message)
            self._draw_status_indicator()
            self._update_toggle_icon()
            self._update_overlay()

        self.after(0, _update)

    def _change_hotkey(self):
        def on_save(new_hotkey: str):
            self._config["hotkey"] = new_hotkey
            self._hotkey_var.set(new_hotkey.upper())
            self._save_config()
            if self.on_hotkey_changed:
                self.on_hotkey_changed(new_hotkey)

        HotkeyCapture(self, self._config["hotkey"], on_save)

    def _on_model_change(self, event=None):
        new_model = _normalize_model_id(self._model_var.get())
        self._config["whisper_model"] = new_model
        self._save_config()
        if self.on_model_changed:
            self.on_model_changed(new_model)

    def _on_grammar_toggle(self):
        enabled = self._grammar_var.get()
        self._config["enable_grammar"] = enabled
        self._save_config()
        if self.on_grammar_toggled:
            self.on_grammar_toggled(enabled)

    def _on_theme_change(self):
        new_theme = self._theme_var.get()
        self._config["theme"] = new_theme
        self._save_config()
        if self.on_theme_changed:
            self.on_theme_changed(new_theme)

        messagebox.showinfo(
            "Theme Changed",
            "Theme will be applied when you restart the application.",
            parent=self
        )

    def _on_ptt_mode_change(self):
        new_mode = self._ptt_mode_var.get()
        self._config["push_to_talk_mode"] = new_mode
        self._save_config()
        self._update_toggle_icon()
        if self.on_push_to_talk_mode_changed:
            self.on_push_to_talk_mode_changed(new_mode)

    def _minimize_to_tray(self):
        self.withdraw()
        if self._tray_icon:
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_from_tray(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.deiconify)

    def _quit(self, icon=None, item=None):
        logger.info("Application shutting down")
        try:
            self.activity_store.clear()
        except Exception:
            pass
        # Remove log handler before destroying widget
        if hasattr(self, "_log_handler"):
            logging.getLogger().removeHandler(self._log_handler)
        if self._tray_icon:
            self._tray_icon.stop()
        if self._overlay:
            self._overlay.destroy()
        self.destroy()

    # ------------------------------------------------------------------ #
    # Config                                                               #
    # ------------------------------------------------------------------ #

    def _validate_config(self, config: dict) -> dict:
        validated = self.DEFAULT_CONFIG.copy()

        raw_model = config.get("whisper_model")
        normalized = _normalize_model_id(raw_model)
        if normalized in self.ALLOWED_WHISPER_MODELS:
            if raw_model != normalized:
                logger.info(f"Migrated whisper_model '{raw_model}' -> '{normalized}'")
            validated["whisper_model"] = normalized
        else:
            logger.warning(f"Invalid whisper_model '{raw_model}', using default")

        hotkey = config.get("hotkey", "").lower()
        if hotkey:
            parts = hotkey.split("+")
            modifiers = [p for p in parts if p in self.ALLOWED_MODIFIERS]
            keys = [p for p in parts if p not in self.ALLOWED_MODIFIERS and p.isalnum() and len(p) <= 10]
            if modifiers and len(keys) == 1:
                validated["hotkey"] = "+".join(modifiers + keys)
            else:
                logger.warning(f"Invalid hotkey '{hotkey}', using default")

        if isinstance(config.get("enable_grammar"), bool):
            validated["enable_grammar"] = config["enable_grammar"]

        ollama_host = config.get("ollama_host", "")
        if isinstance(ollama_host, str) and ollama_host and len(ollama_host) <= 256:
            try:
                _parsed = urlparse(ollama_host)
                if _parsed.scheme in ("http", "https") and _parsed.netloc:
                    validated["ollama_host"] = ollama_host
                else:
                    logger.warning(f"Invalid ollama_host '{ollama_host}', using default")
            except Exception:
                logger.warning(f"Invalid ollama_host '{ollama_host}', using default")
        elif ollama_host:
            logger.warning(f"Invalid ollama_host '{ollama_host}', using default")

        ollama_model = config.get("ollama_model", "")
        if ollama_model and self.OLLAMA_MODEL_PATTERN.match(ollama_model) and len(ollama_model) <= 100:
            validated["ollama_model"] = ollama_model
        else:
            logger.warning(f"Invalid ollama_model '{ollama_model}', using default")

        if config.get("theme") in ["dark", "light"]:
            validated["theme"] = config["theme"]

        if config.get("push_to_talk_mode") in ["hold", "toggle"]:
            validated["push_to_talk_mode"] = config["push_to_talk_mode"]

        if config.get("overlay_corner") in self.ALLOWED_CORNERS:
            validated["overlay_corner"] = config["overlay_corner"]

        return validated

    def _load_config(self) -> dict:
        config_path = Path(self.CONFIG_FILE)
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    loaded = json.load(f)
                    return self._validate_config(loaded)
            except json.JSONDecodeError as e:
                logger.error(f"Config file has invalid JSON: {e}")
            except PermissionError as e:
                logger.error(f"Permission denied reading config: {e}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        return self.DEFAULT_CONFIG.copy()

    def _save_config(self):
        try:
            # Create the file with restricted permissions from the start so
            # there is no window between creation and chmod (race condition).
            # O_TRUNC resets an existing file; O_CREAT creates if absent.
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(self.CONFIG_FILE, flags, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    @property
    def config(self) -> dict:
        return self._config.copy()
