# -*- coding: utf-8 -*-
"""
Scheda "Pilota": guida di Pepper da tastiera (stile videogioco) e telecamera con i dati
dei motori, della testa, della batteria e il riconoscimento di persone e oggetti.

Tasti (con il riquadro video selezionato):
  W / S   avanti / indietro          A / D   di lato a sinistra / destra
  Q / E   ruota a sinistra / destra  Shift   turbo
  frecce  muovono la testa           R       testa al centro
  Spazio  STOP immediato             C       cambia telecamera
  F       foto

Video e guida usano connessioni separate al robot: la guida non aspetta il video.
"""
import os
import time
import math
import threading
import collections
import tkinter as tk
from tkinter import ttk

import numpy as np

import naoqi_lite as nq

CAM_W, CAM_H = 640, 480
QUALITA = {   # etichetta -> (risoluzione NAOqi, spazio colore NAOqi)
    "Fluida (bianco e nero)": (0, 0),     # 160x120, solo luminanza: ~1 byte/pixel
    "Colori": (0, 9),                     # 160x120 YUV422: ~2 byte/pixel
    "Dettaglio 320x240 (lenta)": (1, 9),
}
TELECAMERE = {"Testa (davanti)": 0, "Bassa (bocca)": 1}

# colori della grafica sopra il video (stessi dell'app, nessuno stile "militare")
PANEL = "#15181d"
PANEL_LINE = "#3a3f47"
TXT = "#fafafa"
MUTED = "#a3a3a3"
ACCENT = "#57c8ff"
OKC = "#6ccb5f"
WARNC = "#fce100"
ERRC = "#ff99a4"
COL_PERSON = "#57c8ff"     # persone: azzurro
COL_FACE = "#6ccb5f"       # volti: verde
COL_OBJECT = "#c9a4ff"     # oggetti: lilla

MAX_MS = 0.35          # velocita' massima di Pepper, m/s (per l'indicatore)
ACCEL = 2.2            # rampa di accelerazione (frazione di velocita' max al secondo)
DECEL = 4.5            # rampa di frenata, piu' rapida
HEAD_RATE = 1.3        # rad/s quando tieni premuta una freccia
YAW_LIM = (-2.0, 2.0)
PITCH_LIM = (-0.65, 0.5)
HEAD_HOME = (0.0, -0.2)

KEYMAP = {"w": "w", "a": "a", "s": "s", "d": "d", "q": "q", "e": "e",
          "up": "up", "down": "down", "left": "left", "right": "right",
          "shift_l": "shift", "shift_r": "shift"}


# --------------------------------------------------------------------------
# Conversione immagini
# --------------------------------------------------------------------------
def yuv422_to_rgb(buf, w, h):
    a = np.frombuffer(buf, np.uint8)[: w * h * 2].reshape(h, w // 2, 4).astype(np.float32)
    y = np.stack([a[..., 0], a[..., 2]], axis=-1).reshape(h, w)
    u = np.repeat(a[..., 1] - 128.0, 2, axis=1)
    v = np.repeat(a[..., 3] - 128.0, 2, axis=1)
    rgb = np.stack([y + 1.402 * v, y - 0.344136 * u - 0.714136 * v, y + 1.772 * u], axis=-1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def gray_to_rgb(buf, w, h):
    g = np.frombuffer(buf, np.uint8)[: w * h].reshape(h, w)
    return np.repeat(g[..., None], 3, axis=2)


def resize_bilinear(img, W, H):
    h, w = img.shape[:2]
    ys = np.linspace(0, h - 1, H)
    xs = np.linspace(0, w - 1, W)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    wy = (ys - y0)[:, None, None]
    wx = (xs - x0)[None, :, None]
    a = img.astype(np.float32)
    top = a[y0][:, x0] * (1 - wx) + a[y0][:, x1] * wx
    bot = a[y1][:, x0] * (1 - wx) + a[y1][:, x1] * wx
    return (top * (1 - wy) + bot * wy).astype(np.uint8)


def to_ppm(rgb):
    return b"P6\n%d %d\n255\n" % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()


# --------------------------------------------------------------------------
# Video
# --------------------------------------------------------------------------
class CameraWorker:
    CONNS = 2    # richieste in parallelo: nasconde il ritardo della rete

    def __init__(self, host_fn, on_status):
        self.host_fn = host_fn
        self.on_status = on_status
        self.latest = None          # byte PPM gia' alla dimensione del riquadro
        self.latest_rgb = None
        self.seq = 0
        self.src_size = (0, 0)
        self.kbps = 0.0
        self._times = collections.deque(maxlen=20)
        self._gen = 0
        self._lock = threading.Lock()

    @property
    def fps(self):
        t = [x for x in self._times if time.time() - x < 3.0]
        if len(t) < 2:
            return 0.0
        return (len(t) - 1) / max(0.001, t[-1] - t[0])

    @property
    def running(self):
        return self._gen % 2 == 1

    def start(self, camera, quality):
        if self.running:
            self._gen += 1          # ferma il precedente
        self._gen += 1              # dispari = attivo
        host = self.host_fn()       # letto qui, nel thread dell'interfaccia
        threading.Thread(target=self._run, args=(self._gen, host, camera) + QUALITA[quality],
                         daemon=True).start()

    def stop(self):
        if self.running:
            self._gen += 1
        self.latest = None
        self.latest_rgb = None

    def _run(self, gen, host, camera, res, cs):
        conns, handle = [], None
        try:
            conns =[nq.Robot(host, timeout=15) for _ in range(self.CONNS)]
            handle = conns[0].camera_subscribe("PepperRemoteCam", camera, res, cs, 30)
            self.on_status("telecamera collegata")
            ts = [threading.Thread(target=self._loop, args=(gen, r, handle, cs), daemon=True)
                  for r in conns]
            [t.start() for t in ts]
            [t.join() for t in ts]
        except Exception as e:
            if gen == self._gen:
                self.on_status("errore telecamera: %s" % e)
        finally:
            if handle and conns:
                try:
                    conns[0].camera_unsubscribe(handle)
                except Exception:
                    pass
            for r in conns:
                r.close()

    def _loop(self, gen, r, handle, cs):
        nbytes, t_k = 0, time.time()
        while gen == self._gen:
            try:
                f = r.camera_frame(handle)
            except Exception as e:
                self.on_status("telecamera: %s" % e)
                time.sleep(0.5)
                continue
            if not f:
                time.sleep(0.05)
                continue
            w, h, data = f
            rgb = gray_to_rgb(data, w, h) if cs == 0 else yuv422_to_rgb(data, w, h)
            big = resize_bilinear(rgb, CAM_W, CAM_H)
            ppm = to_ppm(big)
            with self._lock:
                if gen != self._gen:
                    break
                self.latest = ppm
                self.latest_rgb = big          # per il riconoscimento di persone e oggetti
                self.seq += 1
                self.src_size = (w, h)
                self._times.append(time.time())
            nbytes += len(data)
            if time.time() - t_k > 2:
                self.kbps = nbytes / 1024.0 / (time.time() - t_k) * self.CONNS
                nbytes, t_k = 0, time.time()


# --------------------------------------------------------------------------
# Guida
# --------------------------------------------------------------------------
class DriveWorker:
    HZ = 15

    def __init__(self, host_fn, on_status):
        self.host_fn = host_fn
        self.on_status = on_status
        self.keys = set()
        self.lock = threading.Lock()
        self.max_speed = 0.6
        self.v = [0.0, 0.0, 0.0]
        self.head = list(HEAD_HOME)
        self.head_known = False
        self.emergency = False
        self.center_head = False
        self.flap_open = False      # sportello di ricarica aperto = ruote bloccate dal robot
        self._gen = 0

    @property
    def running(self):
        return self._gen % 2 == 1

    def start(self):
        if self.running:
            return
        self._gen += 1
        threading.Thread(target=self._run, args=(self._gen, self.host_fn()), daemon=True).start()

    def stop(self):
        if self.running:
            self._gen += 1
        self.clear()

    def press(self, k):
        with self.lock:
            self.keys.add(k)

    def release(self, k):
        with self.lock:
            self.keys.discard(k)

    def clear(self):
        with self.lock:
            self.keys.clear()

    def stop_now(self):
        self.clear()
        self.emergency = True

    def _run(self, gen, host):
        r = None
        moving = False
        try:
            r = nq.Robot(host, timeout=10)
            try:
                if not r.call('ALMotion', 'robotIsWakeUp'):
                    self.on_status("sveglio il robot...")
                    r.wake_up()
            except Exception:
                pass
            try:
                r.awareness(False)      # lo sguardo automatico combatterebbe con le frecce
            except Exception:
                pass
            try:
                self.head = list(r.get_angles(["HeadYaw", "HeadPitch"]))
            except Exception:
                self.head = list(HEAD_HOME)
            self.head_known = True
            self.on_status("guida attiva: W A S D per muoverti, frecce per la testa")
            last_sent, last_t, last_head = None, 0.0, list(self.head)
            dt = 1.0 / self.HZ
            flap_t = 0.0
            while gen == self._gen:
                t = time.time()
                if t - flap_t > 2.0:
                    flap_t = t
                    try:
                        was = self.flap_open
                        self.flap_open = bool(r.call('ALMemory', 'getData',
                                                     'Device/SubDeviceList/Platform/ILS/Sensor/Value'))
                        if self.flap_open and not was:
                            self.on_status("SPORTELLO DI RICARICA APERTO: chiudilo, altrimenti le ruote restano bloccate")
                    except Exception:
                        pass
                with self.lock:
                    k = set(self.keys)
                if self.emergency:
                    self.emergency = False
                    self.v = [0.0, 0.0, 0.0]
                    r.stop_move()
                    moving, last_sent = False, None
                m = 1.0 if "shift" in k else self.max_speed
                target = [((("w" in k) - ("s" in k)) * m),
                          ((("a" in k) - ("d" in k)) * m),
                          ((("q" in k) - ("e" in k)) * m)]
                for i, tv in enumerate(target):
                    cur = self.v[i]
                    speeding_up = abs(tv) > abs(cur) and tv * cur >= 0
                    step = (ACCEL if speeding_up else DECEL) * dt
                    cur += max(-step, min(step, tv - cur))
                    if tv == 0 and abs(cur) < 0.03:
                        cur = 0.0
                    self.v[i] = cur
                if any(self.v):
                    if (last_sent is None or t - last_t > 0.5 or
                            max(abs(a - b) for a, b in zip(self.v, last_sent)) > 0.03):
                        r.move_toward(*self.v)
                        last_sent, last_t, moving = list(self.v), t, True
                elif moving:
                    r.stop_move()
                    moving, last_sent = False, None

                # testa
                if self.center_head:
                    self.center_head = False
                    self.head = list(HEAD_HOME)
                self.head[0] += (("left" in k) - ("right" in k)) * HEAD_RATE * dt
                self.head[1] += (("down" in k) - ("up" in k)) * HEAD_RATE * dt
                self.head[0] = max(YAW_LIM[0], min(YAW_LIM[1], self.head[0]))
                self.head[1] = max(PITCH_LIM[0], min(PITCH_LIM[1], self.head[1]))
                if max(abs(a - b) for a, b in zip(self.head, last_head)) > 0.004:
                    r.set_angles(["HeadYaw", "HeadPitch"], self.head, 0.3)
                    last_head = list(self.head)

                time.sleep(max(0.0, dt - (time.time() - t)))
        except Exception as e:
            if gen == self._gen:
                self.on_status("errore guida: %s" % e)
                self._gen += 1
        finally:
            self.v = [0.0, 0.0, 0.0]
            if r:
                try:
                    r.stop_move()
                    r.awareness(True)
                except Exception:
                    pass
                r.close()
            self.head_known = False


# --------------------------------------------------------------------------
# Interfaccia
# --------------------------------------------------------------------------
class PilotPanel:
    def __init__(self, parent, app):
        self.app = app
        self.cam = CameraWorker(lambda: app.host.get().strip(), self._status)
        self.drive = DriveWorker(lambda: app.host.get().strip(), self._status)
        self._shown_seq = -1
        self._photo = None
        self._flash_until = 0
        self._msg = ""
        self._msg_t = 0
        import vision
        self.det = vision.ObjectDetector(self._frame_for_detection, self._status)
        self.faces = vision.FaceWatcher(self._status)
        self.var_detect = tk.BooleanVar(value=True)

        import theme
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 10))
        self.btn_cam = ttk.Button(bar, text="Accendi telecamera", style="Accent.TButton",
                                  command=self.toggle_camera)
        self.btn_cam.pack(side="left")
        self.cmb_cam = ttk.Combobox(bar, width=13, state="readonly", values=list(TELECAMERE))
        self.cmb_cam.set("Testa (davanti)")
        self.cmb_cam.pack(side="left", padx=(8, 4))
        self.cmb_q = ttk.Combobox(bar, width=19, state="readonly", values=list(QUALITA))
        self.cmb_q.set("Colori")
        self.cmb_q.pack(side="left", padx=4)
        self.cmb_cam.bind("<<ComboboxSelected>>", lambda e: self._restart_camera())
        self.cmb_q.bind("<<ComboboxSelected>>", lambda e: self._restart_camera())
        ttk.Button(bar, text="Foto", command=self.snapshot).pack(side="left", padx=4)
        ttk.Checkbutton(bar, text="Persone e oggetti", variable=self.var_detect, style="Switch.TCheckbutton",
                        command=self._update_detection).pack(side="left", padx=(10, 0))
        self.btn_drive = ttk.Button(bar, text="Attiva guida", style="Accent.TButton", command=self.toggle_drive)
        self.btn_drive.pack(side="right")
        self.sld_speed = ttk.Scale(bar, from_=20, to=100, length=90,
                                   command=lambda v: setattr(self.drive, "max_speed", float(v) / 100.0))
        self.sld_speed.set(60)
        self.sld_speed.pack(side="right", padx=(4, 14))
        ttk.Label(bar, text="Velocità", style="Mut.TLabel").pack(side="right")

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.cv = tk.Canvas(body, width=CAM_W, height=CAM_H, bg="#05080f",
                            highlightthickness=2, highlightbackground=theme.LINE,
                            highlightcolor=theme.ACC, takefocus=1)
        self.cv.pack(side="left", anchor="n")
        self._img_item = self.cv.create_image(0, 0, anchor="nw")

        help_ = theme.card(body, "Comandi", icon="game", padding=(16, 12))
        help_.pack(side="left", fill="y", padx=(14, 0), anchor="n")
        rows = [("W / S", "avanti / indietro"), ("A / D", "di lato sx / dx"), ("Q / E", "ruota sx / dx"),
                ("Shift", "turbo"), ("Frecce", "muovi la testa"), ("R", "testa al centro"),
                ("Spazio", "STOP"), ("C", "cambia telecamera"), ("F", "foto")]
        for k, d in rows:
            r = ttk.Frame(help_)
            r.pack(anchor="w", pady=2)
            tk.Label(r, text=k, width=7, anchor="w", bg=theme.BG, fg=theme.ACC,
                     font=(theme.F_MONO, 10, "bold")).pack(side="left")
            ttk.Label(r, text=d).pack(side="left")
        ttk.Label(help_, text="Clicca sul video prima di usare i tasti. Se la finestra perde il fuoco o "
                              "cambi pagina, il robot si ferma da solo.\n\nCon il Wi-Fi dell'hotspot il video "
                              "è lento (3-7 immagini al secondo): con un cavo di rete diventa fluido.",
                  style="Mut.TLabel", wraplength=200, justify="left").pack(anchor="w", pady=(12, 0))

        for seq in ("<KeyPress>", "<KeyRelease>"):
            self.cv.bind(seq, self._on_key)
        self.cv.bind("<Button-1>", lambda e: self.cv.focus_set())
        self.cv.bind("<FocusOut>", lambda e: self.drive.clear())
        self._tick()

    # ---------------- comandi ----------------
    def _status(self, msg):
        self._msg, self._msg_t = msg, time.time()
        self.app.set_status(msg)

    def _connected(self):
        if not self.app.robot:
            self.app.set_status("non connesso: premi Connetti", "#ffb454")
            return False
        return True

    def _frame_for_detection(self):
        rgb = self.cam.latest_rgb
        return (self.cam.seq, rgb) if rgb is not None else None

    def _update_detection(self):
        """Riconoscimento attivo solo con la telecamera accesa e l'interruttore attivo."""
        on = self.cam.running and self.var_detect.get()
        if on:
            self.det.start()
            self.faces.start(self.app.host.get().strip())
        else:
            self.det.stop()
            self.faces.stop()

    def toggle_camera(self):
        if self.cam.running:
            self.cam.stop()
            self.btn_cam.config(text="Accendi telecamera", style="Accent.TButton")
        elif self._connected():
            self.cam.start(TELECAMERE[self.cmb_cam.get()], self.cmb_q.get())
            self.btn_cam.config(text="Spegni telecamera", style="TButton")
            self.cv.focus_set()
        self._update_detection()

    def _restart_camera(self):
        if self.cam.running:
            self.cam.start(TELECAMERE[self.cmb_cam.get()], self.cmb_q.get())
        self.cv.focus_set()

    def toggle_drive(self):
        if self.drive.running:
            self.drive.stop()
            self.btn_drive.config(text="Attiva guida", style="Accent.TButton")
            self._status("guida disattivata")
        elif self._connected():
            self.drive.start()
            self.btn_drive.config(text="Disattiva guida", style="TButton")
            self.cv.focus_set()

    def deactivate(self):
        """Chiamata quando si lascia la scheda o si chiude l'app: ferma tutto."""
        if self.drive.running:
            self.drive.stop()
            self.btn_drive.config(text="Attiva guida", style="Accent.TButton")
        if self.cam.running:
            self.cam.stop()
            self.btn_cam.config(text="Accendi telecamera", style="Accent.TButton")
        self._update_detection()

    def snapshot(self):
        """Salva il riquadro cosi' come si vede: immagine + grafica (motori, batteria, riquadri)."""
        if not self.cam.latest:
            self._status("nessuna immagine da salvare: accendi la telecamera")
            return
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "PepperRemote")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("pepper_%Y%m%d_%H%M%S.png"))
        self._draw_hud(for_photo=True)           # grafica senza i messaggi temporanei
        self.cv.update_idletasks()
        try:
            from PIL import ImageGrab
            bd = int(self.cv.cget("highlightthickness"))
            x, y = self.cv.winfo_rootx() + bd, self.cv.winfo_rooty() + bd
            ImageGrab.grab(bbox=(x, y, x + CAM_W, y + CAM_H), all_screens=True).save(path)
        except Exception:
            # ripiego: solo l'immagine della telecamera
            tk.PhotoImage(data=self.cam.latest, format="PPM").write(path, format="png")
        self._flash_until = time.time() + 0.15
        self._status("foto salvata: %s" % path)

    def _on_key(self, ev):
        ks = ev.keysym.lower()
        down = ev.type in (tk.EventType.KeyPress, "2")
        if down and ks == "space":
            self.drive.stop_now()
            return "break"
        if down and ks == "r":
            self.drive.center_head = True
            return "break"
        if down and ks == "c":
            names = list(TELECAMERE)
            self.cmb_cam.set(names[(names.index(self.cmb_cam.get()) + 1) % len(names)])
            self._restart_camera()
            return "break"
        if down and ks == "f":
            self.snapshot()
            return "break"
        k = KEYMAP.get(ks)
        if k and self.drive.running:
            (self.drive.press if down else self.drive.release)(k)
            return "break"

    # ---------------- disegno ----------------
    def _tick(self):
        try:
            if self.cam.latest is not None and self.cam.seq != self._shown_seq:
                self._shown_seq = self.cam.seq
                self._photo = tk.PhotoImage(data=self.cam.latest, format="PPM")
                self.cv.itemconfig(self._img_item, image=self._photo)
            elif self.cam.latest is None and self._photo is not None:
                self._photo = None
                self.cv.itemconfig(self._img_item, image="")
            self._draw_hud()
        except Exception as e:
            self.app.set_status("HUD: %s" % e)
        self.cv.after(60, self._tick)

    def _battery(self):
        if getattr(self.app, "battery_value", None) is not None:
            return self.app.battery_value
        try:
            txt = self.app.lbl_batt.cget("text")
            n = int("".join(c for c in txt if c.isdigit()) or -1)
            return n if 0 <= n <= 100 else None
        except Exception:
            return None

    # ---------------- grafica sopra il video ----------------
    @staticmethod
    def _rrect(cv, x0, y0, x1, y1, r=8, **kw):
        """Rettangolo con angoli arrotondati."""
        r = max(1, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _chip(self, x, y, text, fg=None, dot=None, anchor="nw"):
        """Etichetta su fondo scuro arrotondato; ritorna la larghezza."""
        import theme
        cv = self.cv
        f = (theme.F_TEXT, 9, "bold")
        t = cv.create_text(0, 0, text=text, font=f, anchor="nw", tags="hud")
        bx0, by0, bx1, by1 = cv.bbox(t)
        w = bx1 - bx0 + (24 if dot else 16)
        h = by1 - by0 + 8
        if anchor == "ne":
            x -= w
        elif anchor == "n":
            x -= w / 2
        self._rrect(cv, x, y, x + w, y + h, r=h / 2, fill=PANEL, outline=PANEL_LINE, tags="hud")
        if dot:
            cv.create_oval(x + 9, y + h / 2 - 4, x + 17, y + h / 2 + 4, fill=dot, outline="", tags="hud")
        cv.coords(t, x + (20 if dot else 8), y + 4)
        cv.itemconfig(t, fill=fg or TXT)
        cv.tag_raise(t)
        return w

    def _box(self, x0, y0, x1, y1, color, label):
        """Riquadro di un oggetto riconosciuto, con etichetta."""
        import theme
        cv = self.cv
        W, H = CAM_W, CAM_H
        x0, x1 = max(2, x0 * W), min(W - 2, x1 * W)
        y0, y1 = max(2, y0 * H), min(H - 2, y1 * H)
        if x1 - x0 < 6 or y1 - y0 < 6:
            return
        self._rrect(cv, x0, y0, x1, y1, r=10, fill="", outline=color, width=2, tags="hud")
        f = (theme.F_TEXT, 9, "bold")
        t = cv.create_text(0, 0, text=label, font=f, anchor="nw", fill="#111111", tags="hud")
        bx0, by0, bx1, by1 = cv.bbox(t)
        lw, lh = bx1 - bx0 + 12, by1 - by0 + 4
        ly = y0 - lh - 2 if y0 - lh - 2 > 0 else y0 + 2
        self._rrect(cv, x0, ly, x0 + lw, ly + lh, r=6, fill=color, outline="", tags="hud")
        cv.coords(t, x0 + 6, ly + 2)
        cv.tag_raise(t)

    def _bar(self, x, y, w, value, label):
        """Barra centrata da -1 a +1 (es. velocita' avanti/indietro)."""
        import theme
        cv = self.cv
        cv.create_text(x, y, text=label, anchor="w", fill=MUTED, font=(theme.F_TEXT, 8), tags="hud")
        bx, bw = x + 78, w - 78
        cy = y
        self._rrect(cv, bx, cy - 4, bx + bw, cy + 4, r=4, fill="#2a2f36", outline="", tags="hud")
        mid = bx + bw / 2
        cv.create_line(mid, cy - 6, mid, cy + 6, fill=MUTED, tags="hud")
        v = max(-1.0, min(1.0, value))
        if abs(v) > 0.01:
            a, b = sorted((mid, mid + v * bw / 2))
            self._rrect(cv, a, cy - 4, b, cy + 4, r=4, fill=ACCENT, outline="", tags="hud")

    def _draw_hud(self, for_photo=False):
        import theme
        cv = self.cv
        cv.delete("hud")
        W, H = CAM_W, CAM_H
        now = time.time()
        live = self.cam.running and self.cam.latest is not None
        cam_idx = TELECAMERE.get(self.cmb_cam.get(), 0)

        if not live:
            msg = "Telecamera spenta" if not self.cam.running else "Collegamento alla telecamera..."
            cv.create_text(W / 2, H / 2 - 8, text=msg, fill=TXT, font=(theme.F_DISPLAY, 16, "bold"), tags="hud")
            if not self.cam.running:
                cv.create_text(W / 2, H / 2 + 20, text="premi \"Accendi telecamera\"", fill=MUTED,
                               font=(theme.F_TEXT, 10), tags="hud")

        # --- riquadri di persone, volti e oggetti ---
        counts = {}
        if live and self.var_detect.get():
            if now - self.det.stamp < 1.5:
                for name, score, x0, y0, x1, y1 in self.det.results:
                    col = COL_PERSON if name == "persona" else COL_OBJECT
                    self._box(x0, y0, x1, y1, col, "%s %d%%" % (name, score * 100))
                    counts[name] = counts.get(name, 0) + 1
            if now - self.faces.stamp < 1.5 and self.faces.camera == cam_idx:
                for x0, y0, x1, y1 in self.faces.faces:
                    self._box(x0, y0, x1, y1, COL_FACE, "volto")
                if self.faces.faces:
                    counts["volto"] = len(self.faces.faces)

        # --- in alto a sinistra: stato della telecamera ---
        cam_name = "testa" if cam_idx == 0 else "bassa"
        if live:
            self._chip(12, 12, "In diretta  ·  telecamera %s  ·  %.1f img/s" % (cam_name, self.cam.fps), dot=OKC)
        if counts:
            plur = {"persona": "persone", "volto": "volti"}
            parts = ["%d %s" % (n, plur.get(k, k) if n > 1 else k) for k, n in sorted(counts.items())]
            self._chip(12, 42, "Vedo: " + ", ".join(parts))

        # --- in alto a destra: batteria ---
        b = self._battery()
        bcol = OKC if (b is None or b > 30) else (WARNC if b > 15 else ERRC)
        x1 = W - 12
        x0 = x1 - 104
        self._rrect(cv, x0, 12, x1, 40, r=14, fill=PANEL, outline=PANEL_LINE, tags="hud")
        bx, by = x0 + 12, 19
        self._rrect(cv, bx, by, bx + 30, by + 14, r=3, fill="", outline=TXT, width=1.5, tags="hud")
        cv.create_rectangle(bx + 30, by + 4, bx + 33, by + 10, fill=TXT, outline="", tags="hud")
        if b is not None:
            cv.create_rectangle(bx + 3, by + 3, bx + 3 + 24 * b / 100.0, by + 11, fill=bcol, outline="", tags="hud")
        cv.create_text(x1 - 12, 26, anchor="e", text=("%d%%" % b) if b is not None else "--",
                       fill=TXT, font=(theme.F_TEXT, 10, "bold"), tags="hud")

        # --- in basso a sinistra: motori ---
        vx, vy, vt = self.drive.v
        px0, py1 = 12, H - 12
        px1, py0 = px0 + 232, py1 - 112
        self._rrect(cv, px0, py0, px1, py1, r=12, fill=PANEL, outline=PANEL_LINE, tags="hud")
        cv.create_text(px0 + 12, py0 + 14, anchor="w", text="Motori", fill=TXT,
                       font=(theme.F_TEXT, 10, "bold"), tags="hud")
        state = ("turbo" if "shift" in self.drive.keys else "guida attiva") if self.drive.running else "guida spenta"
        cv.create_text(px1 - 12, py0 + 14, anchor="e", text=state, fill=ACCENT if self.drive.running else MUTED,
                       font=(theme.F_TEXT, 8, "bold"), tags="hud")
        self._bar(px0 + 12, py0 + 38, 208, vx, "avanti")
        self._bar(px0 + 12, py0 + 56, 208, vy, "lato")
        self._bar(px0 + 12, py0 + 74, 208, vt, "rotazione")
        cv.create_text(px0 + 12, py0 + 96, anchor="w",
                       text="velocità %.2f m/s   ·   max %d%%" % (math.hypot(vx, vy) * MAX_MS,
                                                                  self.drive.max_speed * 100),
                       fill=MUTED, font=(theme.F_TEXT, 8), tags="hud")

        # --- in basso a destra: testa ---
        hx1, hy1 = W - 12, H - 12
        hx0, hy0 = hx1 - 196, hy1 - 112
        self._rrect(cv, hx0, hy0, hx1, hy1, r=12, fill=PANEL, outline=PANEL_LINE, tags="hud")
        cv.create_text(hx0 + 12, hy0 + 14, anchor="w", text="Testa", fill=TXT,
                       font=(theme.F_TEXT, 10, "bold"), tags="hud")
        known = self.drive.head_known
        yaw, pitch = self.drive.head
        # vista dall'alto: cerchio = robot, freccia = dove guarda la testa
        ccx, ccy, rr = hx0 + 46, hy0 + 66, 26
        cv.create_oval(ccx - rr, ccy - rr, ccx + rr, ccy + rr, outline=PANEL_LINE, width=2, tags="hud")
        if known:
            ex, ey = ccx - math.sin(yaw) * rr, ccy - math.cos(yaw) * rr
            cv.create_line(ccx, ccy, ex, ey, fill=ACCENT, width=3, arrow="last", tags="hud")
        cv.create_oval(ccx - 4, ccy - 4, ccx + 4, ccy + 4, fill=TXT, outline="", tags="hud")
        tx = hx0 + 88
        cv.create_text(tx, hy0 + 48, anchor="w", text="direzione", fill=MUTED, font=(theme.F_TEXT, 8), tags="hud")
        cv.create_text(tx, hy0 + 64, anchor="w", text=("%+.0f°" % -math.degrees(yaw)) if known else "--",
                       fill=TXT, font=(theme.F_TEXT, 11, "bold"), tags="hud")
        cv.create_text(tx, hy0 + 84, anchor="w", text="inclinazione", fill=MUTED, font=(theme.F_TEXT, 8), tags="hud")
        cv.create_text(tx, hy0 + 100, anchor="w", text=("%+.0f°" % -math.degrees(pitch)) if known else "--",
                       fill=TXT, font=(theme.F_TEXT, 11, "bold"), tags="hud")

        # --- avvisi ---
        if self.drive.running and self.drive.flap_open:
            self._rrect(cv, W / 2 - 200, 60, W / 2 + 200, 106, r=12, fill="#3a1418", outline=ERRC, tags="hud")
            cv.create_text(W / 2, 76, text="Sportello di ricarica aperto", fill=ERRC,
                           font=(theme.F_TEXT, 10, "bold"), tags="hud")
            cv.create_text(W / 2, 94, text="le ruote restano bloccate finché non lo chiudi", fill=TXT,
                           font=(theme.F_TEXT, 9), tags="hud")
        if not for_photo:
            if self.drive.running and self.app.root.focus_get() is not self.cv:
                self._chip(W / 2, H - 160, "Clicca sul video per guidare", fg=WARNC, anchor="n")
            if self._msg and now - self._msg_t < 4:
                self._chip(W / 2, H - 132, self._msg[:70], anchor="n")
            if now < self._flash_until:
                cv.create_rectangle(0, 0, W, H, fill="#ffffff", outline="", stipple="gray50", tags="hud")
