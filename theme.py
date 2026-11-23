# -*- coding: utf-8 -*-
"""
Tema grafico di PepperRemote: stile Windows 11 scuro (Sun Valley / sv_ttk) + icone
Segoe Fluent. Tutti i controlli del tema hanno gli angoli dipinti con il colore di
sfondo #1c1c1c: per questo l'intera app usa quello sfondo e le schede "Card" arrotondate.
"""
import ctypes
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

BG = "#1c1c1c"          # sfondo unico (uguale a quello del tema)
SIDE_HOVER = "#2a2a2a"
SIDE_SEL = "#2d2d2d"
LINE = "#2f2f2f"
FIELD = "#2b2b2b"
FG = "#fafafa"
MUT = "#a3a3a3"
DIM = "#6e6e6e"
ACC = "#57c8ff"
OK = "#6ccb5f"
WARN = "#fce100"
ERR = "#ff99a4"
DANGER = "#c42b1c"

F_DISPLAY = "Segoe UI Variable Display"
F_TEXT = "Segoe UI Variable Text"
F_ICON = "Segoe Fluent Icons"
F_MONO = "Cascadia Mono"

ICONS = {
    "home": "", "game": "", "mic": "", "walk": "", "music": "",
    "tablet": "", "settings": "", "camera": "", "play": "",
    "stop": "", "bolt": "", "power": "", "battery": "",
    "palette": "", "pulse": "",
}


def _pick(*families):
    have = set(tkfont.families())
    for f in families:
        if f in have:
            return f
    return families[-1]


def apply(root):
    """Applica il tema; ritorna True se e' attivo lo stile Windows 11."""
    global F_DISPLAY, F_TEXT, F_ICON, F_MONO
    F_DISPLAY = _pick("Segoe UI Variable Display", "Segoe UI")
    F_TEXT = _pick("Segoe UI Variable Text", "Segoe UI")
    F_ICON = _pick("Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol")
    F_MONO = _pick("Cascadia Mono", "Consolas")
    modern = True
    try:
        import sv_ttk
        sv_ttk.set_theme("dark")
    except Exception:
        modern = False
        ttk.Style().theme_use("clam")
    root.configure(bg=BG)
    st = ttk.Style()
    st.configure(".", font=(F_TEXT, 10), background=BG)
    # il tema non fissa lo sfondo dei contenitori: senza questo restano grigio chiaro
    for name in ("TFrame", "Card.TFrame", "TCheckbutton", "Switch.TCheckbutton", "TRadiobutton",
                 "TScale", "Horizontal.TScale"):
        st.configure(name, background=BG)
    for name in ("TCheckbutton", "Switch.TCheckbutton", "TRadiobutton"):
        st.configure(name, foreground=FG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Title.TLabel", font=(F_DISPLAY, 22, "bold"))
    st.configure("Sub.TLabel", foreground=MUT, font=(F_TEXT, 10))
    st.configure("H.TLabel", font=(F_DISPLAY, 13, "bold"))
    st.configure("Mut.TLabel", foreground=MUT, font=(F_TEXT, 9))
    st.configure("Warn.TLabel", foreground=WARN, font=(F_TEXT, 9))
    st.configure("Big.TLabel", font=(F_DISPLAY, 26, "bold"))
    st.configure("Value.TLabel", foreground=ACC, font=(F_TEXT, 10, "bold"))
    st.configure("Icon.TLabel", foreground=ACC, font=(F_ICON, 16))
    st.configure("TButton", padding=(14, 6))
    st.configure("Accent.TButton", padding=(14, 6))
    st.configure("Big.TButton", padding=(10, 14), font=(F_TEXT, 10, "bold"))
    st.configure("Ghost.TButton", padding=(14, 6))      # compatibilita' con il vecchio codice
    if not modern:
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=BG, relief="solid", borderwidth=1)
    dark_titlebar(root)
    return modern


def dark_titlebar(win):
    """Barra del titolo scura su Windows 10/11."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):    # DWMWA_USE_IMMERSIVE_DARK_MODE (nuovo e vecchio numero)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
    except Exception:
        pass


def card(parent, title=None, subtitle=None, icon=None, padding=(18, 14)):
    """Scheda arrotondata con titolo opzionale; ritorna il frame interno per il contenuto."""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=padding)
    if title:
        head = ttk.Frame(outer)
        head.pack(fill="x", pady=(0, 6 if subtitle else 10))
        if icon:
            ttk.Label(head, text=ICONS.get(icon, icon), style="Icon.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(head, text=title, style="H.TLabel").pack(side="left")
    if subtitle:
        ttk.Label(outer, text=subtitle, style="Mut.TLabel", wraplength=640, justify="left").pack(
            anchor="w", pady=(0, 10))
    return outer


def danger_button(parent, text, command):
    b = tk.Button(parent, text=text, command=command, bg=DANGER, fg="#ffffff", activebackground="#a52618",
                  activeforeground="#ffffff", relief="flat", bd=0, padx=16, pady=6, cursor="hand2",
                  font=(F_TEXT, 10, "bold"))
    return b


class NavItem(tk.Frame):
    """Voce del menu laterale stile Windows 11 (icona + testo + barretta di selezione)."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=BG, cursor="hand2")
        self.command = command
        self.selected = False
        self.bar = tk.Frame(self, bg=BG, width=3, height=18)
        self.bar.pack(side="left", padx=(4, 0))
        self.ico = tk.Label(self, text=ICONS.get(icon, icon), bg=BG, fg=FG, font=(F_ICON, 14), width=2)
        self.ico.pack(side="left", padx=(8, 10), pady=9)
        self.lbl = tk.Label(self, text=text, bg=BG, fg=FG, font=(F_TEXT, 10), anchor="w")
        self.lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self.ico, self.lbl, self.bar):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._paint(hover=True))
            w.bind("<Leave>", lambda e: self._paint(hover=False))

    def set_selected(self, sel):
        self.selected = sel
        self._paint()

    def _paint(self, hover=False):
        bg = SIDE_SEL if self.selected else (SIDE_HOVER if hover else BG)
        for w in (self, self.ico, self.lbl):
            w.config(bg=bg)
        self.bar.config(bg=ACC if self.selected else bg)
        self.ico.config(fg=ACC if self.selected else FG)


class BatteryGauge(tk.Canvas):
    """Anello che mostra la carica della batteria."""

    def __init__(self, parent, size=120):
        super().__init__(parent, width=size, height=size, bg=BG, highlightthickness=0)
        self.size = size
        self.set(None)

    def set(self, value):
        s, w = self.size, 10
        self.delete("all")
        self.create_oval(w, w, s - w, s - w, outline=LINE, width=w)
        if value is not None:
            col = OK if value > 30 else (WARN if value > 15 else ERR)
            self.create_arc(w, w, s - w, s - w, start=90, extent=-3.6 * max(0.5, value),
                            style="arc", outline=col, width=w)
        self.create_text(s / 2, s / 2 - 6, text=("%d%%" % value) if value is not None else "--",
                         fill=FG, font=(F_DISPLAY, 18, "bold"))
        self.create_text(s / 2, s / 2 + 18, text="batteria", fill=MUT, font=(F_TEXT, 9))


class ColorDot(tk.Canvas):
    """Pallino colorato cliccabile (colori dei LED)."""

    def __init__(self, parent, color, command, size=30):
        super().__init__(parent, width=size + 6, height=size + 6, bg=BG, highlightthickness=0, cursor="hand2")
        self.o = self.create_oval(3, 3, size + 3, size + 3, fill=color, outline=LINE, width=2)
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self.itemconfig(self.o, outline=FG))
        self.bind("<Leave>", lambda e: self.itemconfig(self.o, outline=LINE))
