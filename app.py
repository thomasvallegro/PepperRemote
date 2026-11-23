"""
PepperRemote - pannello di controllo con interfaccia grafica per un robot
Pepper/NAO (NAOqi 2.x) via API aperta sulla porta 9559.

Avvio:  python app.py
Richiede Python 3 (Tkinter incluso); grafica stile Windows 11 con il pacchetto sv-ttk.
Le funzioni audio di sistema richiedono pacchetti extra (vedi pagina Audio).
"""
import os
import sys
import json
import time
import socket
import threading
import functools
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import naoqi_lite as nq
import theme
from theme import BG, FG, MUT, ACC, OK, WARN, ERR, FIELD, LINE

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
DEFAULT_HOST = "172.20.10.6"
SCREEN_PORT = 8080
FLAP_KEY = "Device/SubDeviceList/Platform/ILS/Sensor/Value"


# ==========================================================================
# Web server per il "secondo schermo"
# ==========================================================================
SCREEN_STATE = {"mode": "clock", "text": "", "sub": "", "url": "", "rev": 1}
_state_lock = threading.Lock()


def set_screen(**kw):
    with _state_lock:
        SCREEN_STATE.update(kw)
        SCREEN_STATE["rev"] = SCREEN_STATE.get("rev", 0) + 1


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") in ("/state.json", "/state"):
            with _state_lock:
                body = json.dumps(SCREEN_STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


class ScreenServer:
    def __init__(self, port=SCREEN_PORT):
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self):
        if self.httpd:
            return
        handler = functools.partial(_Handler, directory=WEB_DIR)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd = None


def local_ip(target=DEFAULT_HOST):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 9559))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ==========================================================================
# Applicazione GUI
# ==========================================================================
PAGES = [  # chiave, icona, voce del menu, titolo, sottotitolo
    ("state", "home", "Stato", "Stato del robot", "Connessione, batteria, energia e comportamento autonomo"),
    ("pilot", "game", "Pilota", "Pilota", "Guida da tastiera e telecamera in diretta"),
    ("voice", "mic", "Voce", "Voce", "Fai parlare Pepper e regola i volumi"),
    ("move", "walk", "Movimento", "Movimento", "Posture, spostamenti e luci degli occhi"),
    ("audio", "music", "Musica e ballo", "Musica e ballo", "Brani da YouTube, ballo a tempo e audio del PC"),
    ("screen", "tablet", "Tablet", "Tablet", "Usa il tablet di Pepper come secondo schermo"),
]


class PepperApp:
    def __init__(self, root):
        self.root = root
        self.robot = None
        self.audio = None           # LiveAudioBridge
        self.audio_robot = None     # connessione dedicata all'audio
        self.server = ScreenServer()
        self.host = tk.StringVar(value=DEFAULT_HOST)
        self.battery_value = None
        self._poll_running = False

        root.title("PepperRemote")
        root.geometry("1300x860")
        root.minsize(1240, 820)
        theme.apply(root)

        self._build_sidebar()
        tk.Frame(root, bg=LINE, width=1).pack(side="left", fill="y")
        self.main = tk.Frame(root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self._build_header()
        self._build_statusbar()
        self.content = tk.Frame(self.main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=28, pady=(4, 8))

        self.pages = {}
        for key, *_ in PAGES:
            self.pages[key] = ttk.Frame(self.content)
        self._build_state_page(self.pages["state"])
        import pilot
        self.pilot = pilot.PilotPanel(self.pages["pilot"], self)
        self._build_voice_page(self.pages["voice"])
        self._build_move_page(self.pages["move"])
        self._build_audio_page(self.pages["audio"])
        self._build_screen_page(self.pages["screen"])
        self.current = None
        self.show_page("state")

        # Esc = stop di emergenza da qualunque pagina
        root.bind_all("<Escape>", lambda e: self.emergency_stop())

    # -------------------- struttura --------------------
    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=BG, width=250)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        logo = tk.Frame(sb, bg=BG)
        logo.pack(fill="x", padx=18, pady=(18, 14))
        cv = tk.Canvas(logo, width=40, height=40, bg=BG, highlightthickness=0)
        cv.pack(side="left")
        cv.create_oval(2, 2, 38, 38, fill="#f2f2f2", outline="")
        cv.create_oval(11, 14, 18, 22, fill="#1c1c1c", outline="")
        cv.create_oval(22, 14, 29, 22, fill="#1c1c1c", outline="")
        cv.create_arc(12, 18, 28, 31, start=200, extent=140, style="arc", outline="#1c1c1c", width=2)
        t = tk.Frame(logo, bg=BG)
        t.pack(side="left", padx=10)
        tk.Label(t, text="Pepper", bg=BG, fg=FG, font=(theme.F_DISPLAY, 15, "bold")).pack(anchor="w")
        tk.Label(t, text="REMOTE", bg=BG, fg=ACC, font=(theme.F_TEXT, 8, "bold")).pack(anchor="w")

        conn = ttk.Frame(sb, style="Card.TFrame", padding=(14, 12))
        conn.pack(fill="x", padx=14, pady=(0, 16))
        row = ttk.Frame(conn)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot.pack(side="left")
        self._dot = self.dot.create_oval(1, 1, 11, 11, fill=ERR, outline="")
        self.lbl_state = ttk.Label(row, text="non connesso", style="Mut.TLabel")
        self.lbl_state.pack(side="left", padx=8)
        self.lbl_batt = ttk.Label(row, text="", style="Mut.TLabel")
        self.lbl_batt.pack(side="right")
        ttk.Label(conn, text="Indirizzo IP del robot", style="Mut.TLabel").pack(anchor="w", pady=(10, 2))
        ttk.Entry(conn, textvariable=self.host).pack(fill="x")
        self.btn_conn = ttk.Button(conn, text="Connetti", style="Accent.TButton", command=self.toggle_connect)
        self.btn_conn.pack(fill="x", pady=(10, 0))

        self.nav = {}
        for key, icon, label, *_ in PAGES:
            it = theme.NavItem(sb, icon, label, lambda k=key: self.show_page(k))
            it.pack(fill="x", padx=8, pady=1)
            self.nav[key] = it

        foot = tk.Frame(sb, bg=BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=14)
        tk.Label(foot, text="Esc = stop di emergenza", bg=BG, fg=theme.DIM, font=(theme.F_TEXT, 8)).pack(anchor="w")

    def _build_header(self):
        h = tk.Frame(self.main, bg=BG)
        h.pack(fill="x", padx=28, pady=(20, 12))
        left = tk.Frame(h, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        self.lbl_title = ttk.Label(left, text="", style="Title.TLabel")
        self.lbl_title.pack(anchor="w")
        self.lbl_sub = ttk.Label(left, text="", style="Sub.TLabel")
        self.lbl_sub.pack(anchor="w", pady=(2, 0))
        theme.danger_button(h, "■  STOP", self.emergency_stop).pack(side="right", pady=6)

    def _build_statusbar(self):
        bar = tk.Frame(self.main, bg=BG)
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=LINE, height=1).pack(fill="x")
        self.status = tk.Label(bar, text="pronto", bg=BG, fg=MUT, anchor="w",
                               font=(theme.F_MONO, 9), padx=28, pady=6)
        self.status.pack(fill="x")

    def show_page(self, key):
        if key == self.current:
            return
        if self.current == "pilot":
            self.pilot.deactivate()     # lasciando il Pilota si fermano guida e telecamera
        if self.current:
            self.pages[self.current].pack_forget()
            self.nav[self.current].set_selected(False)
        self.current = key
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].set_selected(True)
        for k, _i, _l, title, sub in PAGES:
            if k == key:
                self.lbl_title.config(text=title)
                self.lbl_sub.config(text=sub)

    def set_dot(self, color, text):
        self.dot.itemconfig(self._dot, fill=color)
        self.lbl_state.config(text=text)

    # -------------------- pagina Stato --------------------
    def _build_state_page(self, p):
        top = ttk.Frame(p)
        top.pack(fill="x")
        info = theme.card(top, "Robot", icon="pulse")
        info.pack(side="left", fill="both", expand=True, padx=(0, 12))
        body = ttk.Frame(info)
        body.pack(fill="x")
        self.gauge = theme.BatteryGauge(body, 120)
        self.gauge.pack(side="left", padx=(0, 22))
        facts = ttk.Frame(body)
        facts.pack(side="left", fill="x", expand=True)
        self.lbl_name = ttk.Label(facts, text="Robot: -", style="H.TLabel")
        self.lbl_name.pack(anchor="w")
        self.lbl_ver = ttk.Label(facts, text="NAOqi: -", style="Mut.TLabel")
        self.lbl_ver.pack(anchor="w", pady=(2, 10))
        grid = ttk.Frame(facts)
        grid.pack(anchor="w")
        self.facts = {}
        for i, (key, label) in enumerate((("life", "Comportamento autonomo"), ("posture", "Postura"),
                                          ("wake", "Motori"), ("flap", "Ruote"))):
            ttk.Label(grid, text=label, style="Mut.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            self.facts[key] = ttk.Label(grid, text="-", style="Value.TLabel")
            self.facts[key].grid(row=i, column=1, sticky="w", padx=(18, 0), pady=2)
        self.lbl_life = self.facts["life"]

        power = theme.card(top, "Energia", icon="power")
        power.pack(side="left", fill="y")
        ttk.Label(power, text="Sveglia accende i motori e mette Pepper in piedi;\nRiposo lo rilassa e spegne i motori.",
                  style="Mut.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Button(power, text="Sveglia", style="Accent.TButton",
                   command=lambda: self.act(lambda r: r.wake_up(), "sveglia", refresh=True)).pack(fill="x", pady=3)
        ttk.Button(power, text="Riposo",
                   command=lambda: self.act(lambda r: r.rest(), "riposo", refresh=True)).pack(fill="x", pady=3)
        ttk.Button(power, text="Aggiorna stato", command=self.refresh_state).pack(fill="x", pady=3)

        life = theme.card(p, "Comportamento autonomo (Autonomous Life)", icon="settings",
                          subtitle="Quando è attivo Pepper si guarda intorno e si muove da solo. Mettilo in pausa per "
                                   "comandarlo tu, usare il tablet come secondo schermo o farlo ballare.")
        life.pack(fill="x", pady=(14, 0))
        r2 = ttk.Frame(life)
        r2.pack(anchor="w")
        ttk.Button(r2, text="Pausa", command=lambda: self.act(lambda r: r.set_life("disabled"), "pausa",
                                                              refresh=True)).pack(side="left", padx=(0, 8))
        ttk.Button(r2, text="Riprendi", command=lambda: self.act(lambda r: r.set_life("solitary"), "riprendi",
                                                                 refresh=True)).pack(side="left")

    # -------------------- pagina Voce --------------------
    def _build_voice_page(self, p):
        c = theme.card(p, "Fai parlare Pepper", icon="mic")
        c.pack(fill="x")
        top = ttk.Frame(c)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Lingua", style="Mut.TLabel").pack(side="left")
        self.cmb_lang = ttk.Combobox(top, width=18, state="readonly")
        self.cmb_lang.pack(side="left", padx=8)
        ttk.Button(top, text="Imposta",
                   command=lambda: self.act(lambda r: r.set_language(self.cmb_lang.get()), "lingua")).pack(side="left")
        self.txt = tk.Text(c, height=5, bg=FIELD, fg=FG, insertbackground=FG, relief="flat", bd=0,
                           highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC,
                           font=(theme.F_TEXT, 12), wrap="word", padx=12, pady=10)
        self.txt.pack(fill="x")
        self.txt.insert("1.0", "Ciao! Sono Pepper, comandato dal computer.")
        b = ttk.Frame(c)
        b.pack(fill="x", pady=(10, 0))
        ttk.Button(b, text="Parla", style="Accent.TButton", command=self.say).pack(side="left")
        for phrase in ("Ciao a tutti!", "Benvenuti!", "Come state?", "Grazie, arrivederci!"):
            ttk.Button(b, text=phrase, command=lambda t=phrase: self.act(lambda r: r.say(t), "parla")).pack(
                side="left", padx=(8, 0))

        v = theme.card(p, "Volumi", icon="music")
        v.pack(fill="x", pady=(14, 0))
        self.sld_ttsvol = self._slider(v, "Volume della voce", 0, 100, 80,
                                       lambda val: self.act(lambda r: r.set_tts_volume(val / 100.0), "volume voce"))
        self.sld_outvol = self._slider(v, "Volume generale (casse)", 0, 100, 60,
                                       lambda val: self.act(lambda r: r.set_output_volume(int(val)), "volume casse"))

    def _slider(self, parent, label, lo, hi, init, on_release, unit="%"):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=24).pack(side="left")
        val = ttk.Label(row, text="%d%s" % (init, unit), style="Value.TLabel", width=8)
        s = ttk.Scale(row, from_=lo, to=hi, length=360,
                      command=lambda v: val.config(text="%d%s" % (float(v), unit)))
        s.set(init)
        s.pack(side="left", padx=10)
        val.pack(side="left")
        s.bind("<ButtonRelease-1>", lambda e: on_release(s.get()))
        return s

    # -------------------- pagina Movimento --------------------
    def _build_move_page(self, p):
        top = ttk.Frame(p)
        top.pack(fill="x")
        c = theme.card(top, "Postura", icon="walk")
        c.pack(side="left", fill="both", expand=True, padx=(0, 12))
        pr = ttk.Frame(c)
        pr.pack(anchor="w")
        for name, label in (("Stand", "In piedi"), ("StandInit", "Pronto"), ("Crouch", "Accucciato")):
            ttk.Button(pr, text=label, command=lambda n=name: self.act(lambda r: r.posture(n), "postura " + n)).pack(
                side="left", padx=(0, 8))
        ttk.Label(c, text="Per guidarlo con la tastiera usa la pagina Pilota.", style="Mut.TLabel").pack(
            anchor="w", pady=(12, 0))

        c3 = theme.card(top, "Occhi", icon="palette")
        c3.pack(side="left", fill="both")
        lr = ttk.Frame(c3)
        lr.pack(anchor="w")
        for hexv in (0xFFFFFF, 0x57C8FF, 0x2F7BFF, 0x6CCB5F, 0xFF4040, 0xB050FF, 0xFFD040, 0xFF8AD8):
            theme.ColorDot(lr, "#%06x" % hexv, lambda h=hexv: self.act(lambda r: r.leds_rgb(h), "occhi")).pack(
                side="left", padx=2)
        ttk.Button(c3, text="Altro colore...", command=self.pick_led).pack(anchor="w", pady=(10, 0))

        c2 = theme.card(p, "Spostamento", icon="game", subtitle="Tieni premuto un pulsante: Pepper si muove finché "
                                                                "non lo rilasci.")
        c2.pack(fill="x", pady=(14, 0))
        pad = ttk.Frame(c2)
        pad.pack(anchor="w")
        #               etichetta        x     y    theta  riga col
        self._mk_hold(pad, "↶  Ruota", 0.0, 0.0, 0.6, 0, 0)
        self._mk_hold(pad, "↑  Avanti", 0.6, 0.0, 0.0, 0, 1)
        self._mk_hold(pad, "Ruota  ↷", 0.0, 0.0, -0.6, 0, 2)
        self._mk_hold(pad, "←  Sinistra", 0.0, 0.5, 0.0, 1, 0)
        self._mk_stop(pad, 1, 1)
        self._mk_hold(pad, "Destra  →", 0.0, -0.5, 0.0, 1, 2)
        self._mk_hold(pad, "↓  Indietro", -0.5, 0.0, 0.0, 2, 1)

    def _mk_hold(self, parent, label, x, y, th, row, col):
        b = ttk.Button(parent, text=label, width=14, style="Big.TButton")
        b.grid(row=row, column=col, padx=4, pady=4)
        b.bind("<ButtonPress-1>", lambda e: self.act(lambda r: r.walk(x, y, th), "cammina", quiet=True))
        b.bind("<ButtonRelease-1>", lambda e: self.act(lambda r: r.stop_move(), "stop", quiet=True))

    def _mk_stop(self, parent, row, col):
        b = theme.danger_button(parent, "STOP", lambda: self.act(lambda r: r.stop_move(), "stop"))
        b.config(width=12, pady=12)
        b.grid(row=row, column=col, padx=4, pady=4)

    # -------------------- pagina Tablet --------------------
    def _build_screen_page(self, p):
        c2 = theme.card(p, "Contenuto da mostrare", icon="tablet",
                        subtitle="La pagina viene inviata direttamente al tablet. Per tenerla fissa serve mettere "
                                 "in pausa il comportamento autonomo (lo fa l'interruttore qui sotto).")
        c2.pack(fill="x")
        self.screen_mode = tk.StringVar(value="clock")
        mr = ttk.Frame(c2)
        mr.pack(anchor="w", pady=(0, 8))
        for val, lab in (("clock", "Orologio"), ("message", "Messaggio"), ("image", "Immagine (indirizzo)"),
                         ("site", "Sito web (indirizzo)")):
            ttk.Radiobutton(mr, text=lab, value=val, variable=self.screen_mode).pack(side="left", padx=(0, 16))
        ttk.Label(c2, text="Testo del messaggio, oppure indirizzo dell'immagine o del sito", style="Mut.TLabel").pack(
            anchor="w")
        self.ent_msg = ttk.Entry(c2)
        self.ent_msg.pack(fill="x", pady=(2, 8))
        self.ent_msg.insert(0, "Benvenuti!")
        ttk.Label(c2, text="Sottotitolo (solo per il messaggio)", style="Mut.TLabel").pack(anchor="w")
        self.ent_sub = ttk.Entry(c2)
        self.ent_sub.pack(fill="x", pady=(2, 8))
        self.screen_lock = tk.BooleanVar(value=True)
        ttk.Checkbutton(c2, text="Tieni fisso il tablet", variable=self.screen_lock,
                        style="Switch.TCheckbutton").pack(anchor="w", pady=(4, 10))
        br = ttk.Frame(c2)
        br.pack(anchor="w")
        ttk.Button(br, text="Mostra sul tablet", style="Accent.TButton", command=self.push_tablet).pack(side="left")
        ttk.Button(br, text="Nascondi", command=lambda: self.act(lambda r: r.tablet_hide(), "nascondi tablet")).pack(
            side="left", padx=8)

        c3 = theme.card(p, "Luminosità", icon="bolt")
        c3.pack(fill="x", pady=(14, 0))
        self._slider(c3, "Luminosità del tablet", 10, 100, 80,
                     lambda v: self.act(lambda r: r.tablet_brightness(v / 100.0), "luminosita'"))

    # -------------------- pagina Musica e ballo --------------------
    def _build_audio_page(self, p):
        c = theme.card(p, "Musica sul robot", icon="music",
                       subtitle="Incolla un link di YouTube (il PC scarica l'audio e lo manda al robot) "
                                "oppure l'indirizzo diretto di un mp3 o di una radio.")
        c.pack(fill="x")
        self.ent_stream = ttk.Entry(c)
        self.ent_stream.pack(fill="x")
        self.ent_stream.insert(0, "http://stream.srg-ssr.ch/m/rsc_it/mp3_128")
        r = ttk.Frame(c)
        r.pack(fill="x", pady=(10, 0))
        ttk.Button(r, text="▶  Riproduci sul robot", style="Accent.TButton", command=self.play_media).pack(
            side="left")
        ttk.Button(r, text="Stop", command=self.stop_audio).pack(side="left", padx=8)
        self.var_loop = tk.BooleanVar(value=True)
        self.var_dance = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="Balla con la musica", variable=self.var_dance,
                        style="Switch.TCheckbutton").pack(side="right")
        ttk.Checkbutton(r, text="Ripeti all'infinito", variable=self.var_loop,
                        style="Switch.TCheckbutton").pack(side="right", padx=18)

        cd = theme.card(p, "Ballo", icon="walk",
                        subtitle="Pepper balla a tempo con braccia, testa e fianchi (resta fermo sulle ruote). "
                                 "Tieni libero lo spazio intorno alle braccia.")
        cd.pack(fill="x", pady=(14, 0))
        rd = ttk.Frame(cd)
        rd.pack(fill="x")
        ttk.Button(rd, text="Balla", style="Accent.TButton", command=self.start_dance).pack(side="left")
        ttk.Button(rd, text="Ferma ballo", command=self.stop_dance).pack(side="left", padx=8)
        self.var_autobpm = tk.BooleanVar(value=True)
        ttk.Checkbutton(rd, text="Tempo automatico dal brano", variable=self.var_autobpm,
                        style="Switch.TCheckbutton").pack(side="right")
        rt = ttk.Frame(cd)
        rt.pack(fill="x", pady=(10, 0))
        ttk.Label(rt, text="Tempo", width=10).pack(side="left")
        self.lbl_bpm = ttk.Label(rt, text="110 BPM", style="Value.TLabel", width=9)
        self.sld_bpm = ttk.Scale(rt, from_=70, to=160, length=360, command=self._on_bpm)
        self.sld_bpm.set(110)
        self.sld_bpm.pack(side="left", padx=10)
        self.lbl_bpm.pack(side="left")

        c2 = theme.card(p, "Audio del PC sulle casse del robot", icon="play",
                        subtitle="Invia alle casse di Pepper tutto ciò che suona sul computer (sperimentale). "
                                 "Per non sentirlo anche dal PC: installa VB-CABLE, imposta 'CABLE Input' come uscita "
                                 "di Windows e scegli qui 'CABLE Output'.")
        c2.pack(fill="x", pady=(14, 0))
        src = ttk.Frame(c2)
        src.pack(fill="x")
        ttk.Label(src, text="Sorgente", style="Mut.TLabel").pack(side="left")
        self.cmb_audio_src = ttk.Combobox(src, width=46, state="readonly")
        self.cmb_audio_src.pack(side="left", padx=8)
        self.cmb_audio_src.set("(uscita predefinita di Windows)")
        ttk.Button(src, text="Rileva dispositivi", command=self.detect_audio_devices).pack(side="left")
        self._audio_devs = []   # lista (index, nome)
        r2 = ttk.Frame(c2)
        r2.pack(fill="x", pady=(10, 0))
        self.btn_audio_start = ttk.Button(r2, text="Avvia diretta", style="Accent.TButton",
                                          command=self.start_live_audio)
        self.btn_audio_start.pack(side="left")
        ttk.Button(r2, text="Ferma diretta", command=self.stop_live_audio).pack(side="left", padx=8)
        ttk.Button(r2, text="Installa componenti", command=self.install_audio_deps).pack(side="left")
        self.lbl_audio = ttk.Label(r2, text="diretta ferma", style="Mut.TLabel")
        self.lbl_audio.pack(side="right")

    # ======================================================================
    # Logica
    # ======================================================================
    def emergency_stop(self):
        """Ferma tutto: ruote, ballo, musica, guida."""
        self.pilot.deactivate()
        self.stop_dance()
        self._media_gen = getattr(self, "_media_gen", 0) + 1

        def fn(r):
            for f in (r.stop_move, r.audio_stop):
                try:
                    f()
                except Exception:
                    pass
            try:
                r.call('ALMemory', 'raiseEvent', 'PepperAI/Command', json.dumps({"cmd": "stop_music"}))
            except Exception:
                pass
        self.act(fn, "STOP di emergenza")

    def play_media(self):
        """Riproduce sul robot un link YouTube (convertito dal PC) o un indirizzo audio diretto."""
        url = self.ent_stream.get().strip()
        if not url:
            return
        if not self.robot:
            self.set_status("non connesso: premi Connetti", WARN)
            return
        import yt_audio
        host = self.host.get().strip()
        loop = bool(self.var_loop.get())
        self._media_gen = getattr(self, "_media_gen", 0) + 1
        gen = self._media_gen

        def run():
            player = None
            try:
                title = url
                robot_url = url
                if yt_audio.is_youtube(url):
                    robot_url, title = yt_audio.youtube_to_robot_url(
                        url, local_ip(host), progress=lambda m: self.set_status(m, ACC))
                    if self.var_autobpm.get():
                        self._auto_bpm(os.path.join(yt_audio.CACHE_DIR, robot_url.rsplit("/", 1)[-1]))
                if gen != self._media_gen:
                    return
                if self.var_dance.get():
                    self.start_dance()
                # Se sul robot gira Pepper AI, il brano viene scaricato tutto sul robot e
                # riprodotto da li': niente salti dovuti ai ritardi della rete Wi-Fi.
                if yt_audio.is_youtube(url) and self._pepper_ai_ready():   # le radio sono infinite: solo brani
                    self._play_via_pepper_ai(robot_url, title, loop)
                    return
                # altrimenti streaming diretto. playWebStream ritorna solo a fine brano:
                # usa una connessione dedicata, cosi' il resto dell'app (e Stop) funziona
                player = nq.Robot(host)
                player.sess.sock.settimeout(None)
                n = 0
                while gen == self._media_gen:
                    n += 1
                    self.set_status("in riproduzione sul robot: %s%s" % (title, " (giro %d)" % n if n > 1 else ""), OK)
                    t0 = time.time()
                    player.play_stream(robot_url)
                    # senza "ripeti", o se e' una radio che si e' interrotta subito, ci si ferma
                    if not loop or not yt_audio.is_youtube(url) or time.time() - t0 < 3:
                        break
                if gen == self._media_gen:
                    self.set_status("finito: %s" % title, MUT)
            except Exception as e:
                self.set_status("errore riproduzione: %s" % e, ERR)
            finally:
                if player:
                    player.close()
                if gen == self._media_gen and self.var_dance.get():
                    self.stop_dance()
        threading.Thread(target=run, daemon=True).start()

    def _auto_bpm(self, mp3_path):
        """Misura il tempo del brano e lo imposta per il ballo (chiamata da un thread)."""
        try:
            import bpm
            self.set_status("misuro il tempo del brano...", ACC)
            value = bpm.detect_bpm(mp3_path)
            self.root.after(0, lambda: self.sld_bpm.set(value))   # aggiorna cursore e ballo
            self.set_status("tempo rilevato: %d BPM" % value, OK)
        except Exception as e:
            self.set_status("tempo non rilevato (%s): uso quello del cursore" % e, WARN)

    def _on_bpm(self, v):
        bpm = int(float(v))
        self.lbl_bpm.config(text="%d BPM" % bpm)
        if getattr(self, "dancer", None):
            self.dancer.bpm = bpm

    def start_dance(self):
        if not self.robot:
            self.set_status("non connesso: premi Connetti", WARN)
            return
        import dance
        if not getattr(self, "dancer", None) or self.dancer.host != self.host.get().strip():
            self.dancer = dance.Dancer(self.host.get().strip(), on_status=lambda m: self.set_status(m, ACC))
        self.dancer.start(int(self.sld_bpm.get()))

    def stop_dance(self):
        if getattr(self, "dancer", None):
            self.dancer.stop()

    def _pepper_ai_ready(self):
        try:
            if not self.robot.call('ALBehaviorManager', 'getRunningBehaviors'):
                return False
            st = self.robot.call('ALMemory', 'getData', 'PepperAI/MusicStatus')
            return bool(st) and st != "non attivo"
        except Exception:
            return False

    def _play_via_pepper_ai(self, robot_url, title, loop=True):
        self.robot.call('ALMemory', 'raiseEvent', 'PepperAI/Command',
                        json.dumps({"cmd": "play_url", "url": robot_url, "loop": bool(loop)}))
        msgs = {"scarico": ("il robot scarica il brano: %s", ACC),
                "in riproduzione": ("in riproduzione sul robot: %s", OK),
                "finito": ("finito: %s", MUT), "fermato": ("fermato: %s", MUT)}
        last = None
        t0 = time.time()
        while True:
            time.sleep(1.0)
            try:
                st = self.robot.call('ALMemory', 'getData', 'PepperAI/MusicStatus')
            except Exception:
                continue
            if st != last:
                last = st
                if st in msgs:
                    fmt, col = msgs[st]
                    self.set_status(fmt % title, col)
                elif st.startswith("errore"):
                    self.set_status("robot: %s" % st, ERR)
                    return
            if st in ("finito", "fermato", "non attivo") and time.time() - t0 > 2:
                return

    def stop_audio(self):
        self._media_gen = getattr(self, "_media_gen", 0) + 1   # interrompe la ripetizione
        self.stop_dance()

        def fn(rb):
            try:
                rb.call('ALMemory', 'raiseEvent', 'PepperAI/Command', json.dumps({"cmd": "stop_music"}))
            except Exception:
                pass
            return rb.audio_stop()
        self.act(fn, "audio stop")

    # -------------------- helpers --------------------
    def set_status(self, text, color=MUT):
        self.root.after(0, lambda: self.status.config(text=text, fg=color))

    def act(self, fn, desc="", refresh=False, quiet=False):
        """Esegue fn(robot) in un thread; riporta errori nella barra di stato."""
        if not self.robot:
            self.set_status("non connesso: premi Connetti", WARN)
            return

        def run():
            try:
                res = fn(self.robot)
                if not quiet:
                    self.set_status("OK: %s%s" % (desc, "" if res is None else " -> %s" % (res,)), OK)
                if refresh:
                    self.refresh_state()
            except Exception as e:
                self.set_status("errore [%s]: %s" % (desc, e), ERR)
        threading.Thread(target=run, daemon=True).start()

    # -------------------- connessione --------------------
    def toggle_connect(self):
        if self.robot:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        host = self.host.get().strip()
        self.set_dot(WARN, "connessione...")
        self.btn_conn.config(text="Connessione...")

        def run():
            try:
                rb = nq.Robot(host)
                self.robot = rb
                name = rb.robot_name(); ver = rb.naoqi_version()
                self.root.after(0, lambda: self._on_connected(name, ver))
            except Exception as e:
                self.robot = None
                self.root.after(0, lambda: self._on_conn_fail(e))
        threading.Thread(target=run, daemon=True).start()

    def _on_connected(self, name, ver):
        self.set_dot(OK, "connesso")
        self.btn_conn.config(text="Disconnetti")
        self.lbl_name.config(text=name)
        self.lbl_ver.config(text="NAOqi %s  ·  %s" % (ver, self.host.get().strip()))
        self.set_status("connesso a %s" % self.host.get(), OK)
        try:
            langs = self.robot.languages()
            self.cmb_lang["values"] = langs
            cur = self.robot.call("ALTextToSpeech", "getLanguage")
            if cur in langs:
                self.cmb_lang.set(cur)
        except Exception:
            pass
        self._poll_running = True
        self._poll_battery()          # legge batteria e stato (una volta sola: la rete e' lenta)

    def _on_conn_fail(self, e):
        self.set_dot(ERR, "non connesso")
        self.btn_conn.config(text="Connetti")
        self.set_status("connessione fallita: %s" % e, ERR)
        messagebox.showerror("Connessione", "Impossibile connettersi al robot:\n%s" % e)

    def disconnect(self):
        self._poll_running = False
        self.pilot.deactivate()
        self.stop_live_audio()
        try:
            self.robot.close()
        except Exception:
            pass
        self.robot = None
        self.battery_value = None
        self.gauge.set(None)
        self.set_dot(ERR, "non connesso")
        self.btn_conn.config(text="Connetti")
        self.lbl_batt.config(text="")
        self.set_status("disconnesso", MUT)

    def refresh_state(self):
        def run():
            vals = {}
            for key, fn in (("life", lambda r: r.life_state()),
                            ("posture", lambda r: r.call('ALRobotPosture', 'getPosture')),
                            ("wake", lambda r: "accesi" if r.call('ALMotion', 'robotIsWakeUp') else "spenti (riposo)"),
                            ("flap", lambda r: "BLOCCATE: sportello di ricarica aperto"
                             if r.call('ALMemory', 'getData', FLAP_KEY) else "libere")):
                try:
                    vals[key] = str(fn(self.robot))
                except Exception:
                    vals[key] = "-"
            names = {"disabled": "in pausa", "solitary": "attivo (da solo)", "interactive": "attivo (in interazione)",
                     "safeguard": "protezione", "Stand": "in piedi", "StandInit": "pronto", "Crouch": "accucciato"}

            def apply():
                for k, v in vals.items():
                    col = ERR if v.startswith("BLOCCATE") else ACC
                    self.facts[k].config(text=names.get(v, v), foreground=col)
            self.root.after(0, apply)
        if self.robot:
            threading.Thread(target=run, daemon=True).start()

    def _poll_battery(self):
        if not (self.robot and self._poll_running):
            return

        def run():
            try:
                b = int(self.robot.battery())
                self.battery_value = b
                self.root.after(0, lambda: (self.lbl_batt.config(text="%d%%" % b), self.gauge.set(b)))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()
        self.refresh_state()
        self.root.after(20000, self._poll_battery)

    # -------------------- azioni voce --------------------
    def say(self):
        text = self.txt.get("1.0", "end").strip()
        if text:
            self.act(lambda r: r.say(text), "parla")

    def pick_led(self):
        rgb, _ = colorchooser.askcolor(title="Colore degli occhi")
        if rgb:
            hexv = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
            self.act(lambda r: r.leds_rgb(hexv), "occhi")

    # -------------------- secondo schermo --------------------
    def _build_tablet_html(self, mode, text, sub):
        import html as _h
        base = ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<style>html,body{margin:0;height:100%;overflow:hidden;"
                "font-family:'Segoe UI',system-ui,sans-serif;"
                "background:radial-gradient(circle at 50% 30%,#152238,#070b14 70%);"
                "color:#eaf2ff}#w{height:100vh;display:flex;align-items:center;"
                "justify-content:center;text-align:center;flex-direction:column;padding:4vh 5vw;box-sizing:border-box}</style></head><body><div id='w'>")
        if mode == "clock":
            body = ("<div id='t' style='font-size:20vw;font-weight:700;"
                    "text-shadow:0 0 40px rgba(80,150,255,.5)'>--:--</div>"
                    "<div id='d' style='font-size:5vw;opacity:.8'></div>"
                    "<script>function u(){var x=new Date();"
                    "document.getElementById('t').textContent=('0'+x.getHours()).slice(-2)+':'+('0'+x.getMinutes()).slice(-2);"
                    "document.getElementById('d').textContent=x.toLocaleDateString('it-IT',{weekday:'long',day:'numeric',month:'long'});}"
                    "setInterval(u,1000);u();</script>")
        elif mode == "image":
            url = _h.escape((sub.strip() or text.strip()))
            body = "<img src='%s' style='max-width:100%%;max-height:100vh;object-fit:contain'>" % url
        else:  # message
            body = ("<div style='font-size:9vw;font-weight:700;line-height:1.1;"
                    "text-shadow:0 0 30px rgba(80,150,255,.45)'>%s</div>" % _h.escape(text))
            if sub.strip():
                body += "<div style='font-size:4vw;opacity:.75;margin-top:3vh'>%s</div>" % _h.escape(sub)
        return base + body + "</div></body></html>"

    def push_tablet(self):
        if not self.robot:
            self.set_status("connettiti prima", WARN); return
        mode = self.screen_mode.get()
        text = self.ent_msg.get(); sub = self.ent_sub.get()
        lock = self.screen_lock.get()
        if mode == "site":
            url = (sub.strip() or text.strip())
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
            target = url
        else:
            html = self._build_tablet_html(mode, text, sub)
            import base64
            target = "data:text/html;charset=utf-8;base64," + base64.b64encode(html.encode("utf-8")).decode()

        def push(r):
            if lock:
                try:
                    r.set_life("disabled")
                except Exception:
                    pass
            return r.tablet_url(target)
        self.act(push, "tablet: " + mode)

    # -------------------- audio di sistema --------------------
    def install_audio_deps(self):
        self.lbl_audio.config(text="installazione componenti in corso...", foreground=WARN)

        def run():
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "PyAudioWPatch", "numpy"])
                self.root.after(0, lambda: self.lbl_audio.config(text="componenti installati: premi Avvia diretta",
                                                                 foreground=OK))
            except Exception as e:
                self.root.after(0, lambda: self.lbl_audio.config(text="installazione fallita: %s" % e, foreground=ERR))
        threading.Thread(target=run, daemon=True).start()

    def detect_audio_devices(self):
        self.lbl_audio.config(text="rilevamento dispositivi...", foreground=WARN)

        def run():
            try:
                import audio_bridge
                devs = audio_bridge.list_loopback_devices()
            except Exception as e:
                self.root.after(0, lambda: self.lbl_audio.config(
                    text="rilevamento fallito (installa i componenti): %s" % e, foreground=ERR))
                return

            def apply():
                self._audio_devs = devs
                vals = ["(uscita predefinita di Windows)"] + [n for _, n in devs]
                self.cmb_audio_src["values"] = vals
                # preseleziona un cavo virtuale se presente
                pick = next((n for _, n in devs if "cable" in n.lower() or "voicemeeter" in n.lower()), None)
                self.cmb_audio_src.set(pick or "(uscita predefinita di Windows)")
                self.lbl_audio.config(text="%d dispositivi trovati" % len(devs), foreground=OK)
            self.root.after(0, apply)
        threading.Thread(target=run, daemon=True).start()

    def _selected_audio_index(self):
        sel = self.cmb_audio_src.get()
        for idx, name in self._audio_devs:
            if name == sel:
                return idx
        return None   # predefinito

    def start_live_audio(self):
        if not self.robot:
            self.set_status("connettiti prima", WARN); return
        if self.audio and self.audio.running:
            return
        try:
            import audio_bridge
            # connessione dedicata per non contendere il socket della GUI
            self.audio_robot = nq.Robot(self.host.get().strip())
            self.audio = audio_bridge.LiveAudioBridge(
                self.audio_robot, device_index=self._selected_audio_index(),
                on_status=lambda s: self.root.after(0, lambda: self.lbl_audio.config(text=s, foreground=OK)))
            self.audio.start()
            self.lbl_audio.config(text="diretta avviata...", foreground=OK)
        except Exception as e:
            self.lbl_audio.config(text="errore: %s" % e, foreground=ERR)
            self.set_status("audio diretta: %s" % e, ERR)

    def stop_live_audio(self):
        try:
            if self.audio:
                self.audio.stop()
            if self.audio_robot:
                self.audio_robot.close()
        except Exception:
            pass
        self.audio = None; self.audio_robot = None
        try:
            self.lbl_audio.config(text="diretta ferma", foreground=MUT)
        except Exception:
            pass


# ==========================================================================
# Schermata di avvio
# ==========================================================================
def splash(root, after):
    sp = tk.Toplevel(root)
    sp.overrideredirect(True)
    w, h = 460, 260
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    sp.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
    sp.configure(bg=BG)
    cv = tk.Canvas(sp, width=w, height=h, bg=BG, highlightthickness=1, highlightbackground=LINE)
    cv.pack(fill="both", expand=True)
    cx = w // 2
    cv.create_oval(cx - 42, 40, cx + 42, 124, fill="#f2f2f2", outline="")
    cv.create_oval(cx - 22, 70, cx - 8, 88, fill=BG, outline="")
    cv.create_oval(cx + 8, 70, cx + 22, 88, fill=BG, outline="")
    cv.create_arc(cx - 20, 82, cx + 20, 112, start=200, extent=140, style="arc", outline=BG, width=3)
    cv.create_text(cx, 160, text="Pepper Remote", fill=FG, font=(theme.F_DISPLAY, 22, "bold"))
    cv.create_text(cx, 190, text="pannello di controllo del robot", fill=MUT, font=(theme.F_TEXT, 10))
    cv.create_rectangle(60, 222, w - 60, 225, fill=LINE, outline="")
    bar = cv.create_rectangle(60, 222, 60, 225, fill=ACC, outline="")

    def grow(x=60):
        cv.coords(bar, 60, 222, x, 225)
        if x < w - 60:
            root.after(14, lambda: grow(x + 12))
        else:
            sp.destroy(); after()
    root.after(150, grow)


def enable_sharp_text():
    """Testi nitidi con la scala di Windows (125%, 150%...): l'app dichiara di gestire i DPI."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    enable_sharp_text()
    root = tk.Tk()
    root.withdraw()
    app = PepperApp(root)

    def show_main():
        root.deiconify()
        theme.dark_titlebar(root)
    splash(root, show_main)

    def on_close():
        try:
            app.pilot.deactivate()
            app.stop_dance()
            app.stop_live_audio()
            app.server.stop()
            import yt_audio
            yt_audio.stop_server()
            if app.robot:
                app.robot.close()
        except Exception:
            pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
