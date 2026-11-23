# -*- coding: utf-8 -*-
"""
Riconoscimento di persone e oggetti per la pagina Pilota.

- Oggetti e persone: MediaPipe (Google) con il modello EfficientDet-Lite0, 80 categorie
  comuni (persona, sedia, libro, bottiglia...). Gira sul PC, sull'immagine ricevuta.
  Il modello (~4 MB) si scarica una volta sola nella cartella "models".
- Volti: li rileva il robot stesso (ALFaceDetection) sulla sua telecamera; qui si leggono
  solo posizione e dimensione. Nessun riconoscimento dell'identita', nessun salvataggio.

Le coordinate restituite sono normalizzate (0..1) rispetto all'immagine.
"""
import os
import time
import threading
import urllib.request

import naoqi_lite as nq

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(APP_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "efficientdet_lite0.tflite")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/object_detector/"
             "efficientdet_lite0/float32/1/efficientdet_lite0.tflite")

# campo visivo delle telecamere di Pepper (radianti)
HFOV, VFOV = 0.9826, 0.7627   # 56,3 x 43,7 gradi

ITALIANO = {
    "person": "persona", "bicycle": "bicicletta", "car": "auto", "motorcycle": "moto", "airplane": "aereo",
    "bus": "autobus", "train": "treno", "truck": "camion", "boat": "barca", "traffic light": "semaforo",
    "fire hydrant": "idrante", "stop sign": "stop", "parking meter": "parchimetro", "bench": "panchina",
    "bird": "uccello", "cat": "gatto", "dog": "cane", "horse": "cavallo", "sheep": "pecora", "cow": "mucca",
    "elephant": "elefante", "bear": "orso", "zebra": "zebra", "giraffe": "giraffa", "backpack": "zaino",
    "umbrella": "ombrello", "handbag": "borsa", "tie": "cravatta", "suitcase": "valigia", "frisbee": "frisbee",
    "skis": "sci", "snowboard": "snowboard", "sports ball": "palla", "kite": "aquilone",
    "baseball bat": "mazza", "baseball glove": "guantone", "skateboard": "skateboard", "surfboard": "surf",
    "tennis racket": "racchetta", "bottle": "bottiglia", "wine glass": "bicchiere", "cup": "tazza",
    "fork": "forchetta", "knife": "coltello", "spoon": "cucchiaio", "bowl": "ciotola", "banana": "banana",
    "apple": "mela", "sandwich": "panino", "orange": "arancia", "broccoli": "broccoli", "carrot": "carota",
    "hot dog": "hot dog", "pizza": "pizza", "donut": "ciambella", "cake": "torta", "chair": "sedia",
    "couch": "divano", "potted plant": "pianta", "bed": "letto", "dining table": "tavolo", "toilet": "wc",
    "tv": "televisore", "laptop": "portatile", "mouse": "mouse", "remote": "telecomando",
    "keyboard": "tastiera", "cell phone": "telefono", "microwave": "microonde", "oven": "forno",
    "toaster": "tostapane", "sink": "lavandino", "refrigerator": "frigorifero", "book": "libro",
    "clock": "orologio", "vase": "vaso", "scissors": "forbici", "teddy bear": "peluche",
    "hair drier": "phon", "toothbrush": "spazzolino",
}


def ensure_model(progress=None):
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 100000:
        return MODEL_PATH
    os.makedirs(MODEL_DIR, exist_ok=True)
    if progress:
        progress("scarico il modello di riconoscimento (una volta sola, ~4 MB)...")
    tmp = MODEL_PATH + ".part"
    urllib.request.urlretrieve(MODEL_URL, tmp)
    os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


class ObjectDetector:
    """Analizza l'ultima immagine disponibile in un thread separato."""

    def __init__(self, frame_fn, on_status=None, min_score=0.45):
        self.frame_fn = frame_fn          # ritorna (seq, immagine RGB numpy) oppure None
        self.on_status = on_status or (lambda m: None)
        self.min_score = min_score
        self.results = []                 # [(etichetta, punteggio, x0, y0, x1, y1)] normalizzati
        self.stamp = 0.0
        self.ms = 0.0
        self._gen = 0

    @property
    def running(self):
        return self._gen % 2 == 1

    def start(self):
        if not self.running:
            self._gen += 1
            threading.Thread(target=self._run, args=(self._gen,), daemon=True).start()

    def stop(self):
        if self.running:
            self._gen += 1
        self.results = []

    def _run(self, gen):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision as mpv
            path = ensure_model(self.on_status)
            opts = mpv.ObjectDetectorOptions(base_options=mpt.BaseOptions(model_asset_path=path),
                                             score_threshold=self.min_score, max_results=8)
            det = mpv.ObjectDetector.create_from_options(opts)
        except Exception as e:
            self.on_status("riconoscimento oggetti non disponibile: %s" % e)
            self._gen += 1
            return
        self.on_status("riconoscimento di persone e oggetti attivo")
        last_seq = -1
        try:
            while gen == self._gen:
                f = self.frame_fn()
                if not f or f[0] == last_seq:
                    time.sleep(0.03)
                    continue
                last_seq, rgb = f
                h, w = rgb.shape[:2]
                t0 = time.time()
                res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy()))
                out = []
                for d in res.detections:
                    c = d.categories[0]
                    b = d.bounding_box
                    name = ITALIANO.get(c.category_name, c.category_name)
                    out.append((name, c.score, b.origin_x / w, b.origin_y / h,
                                (b.origin_x + b.width) / w, (b.origin_y + b.height) / h))
                self.ms = (time.time() - t0) * 1000
                self.results, self.stamp = out, time.time()
        finally:
            det.close()


class FaceWatcher:
    """Legge i volti rilevati dal robot (ALFaceDetection) per la telecamera indicata."""

    NAME = "PepperRemoteVolti"

    def __init__(self, on_status=None):
        self.on_status = on_status or (lambda m: None)
        self.faces = []        # [(x0, y0, x1, y1)] normalizzati
        self.camera = 0
        self.stamp = 0.0
        self._gen = 0

    @property
    def running(self):
        return self._gen % 2 == 1

    def start(self, host):
        if not self.running:
            self._gen += 1
            threading.Thread(target=self._run, args=(self._gen, host), daemon=True).start()

    def stop(self):
        if self.running:
            self._gen += 1
        self.faces = []

    @staticmethod
    def parse(val):
        """Estrae i riquadri dei volti dal dato ALMemory 'FaceDetected'."""
        faces, cam = [], 0
        if not val or len(val) < 2:
            return faces, cam
        try:
            cam = int(val[4]) if len(val) > 4 else 0
        except Exception:
            cam = 0
        for item in val[1] or []:
            try:
                shape = item[0]
                if not isinstance(shape, (list, tuple)) or len(shape) < 5:
                    continue
                alpha, beta, sx, sy = (float(v) for v in shape[1:5])
            except Exception:
                continue
            cx, cy = 0.5 - alpha / HFOV, 0.5 + beta / VFOV
            hw, hh = sx / HFOV / 2.0, sy / VFOV / 2.0
            faces.append((cx - hw, cy - hh, cx + hw, cy + hh))
        return faces, cam

    def _run(self, gen, host):
        r = None
        try:
            r = nq.Robot(host, timeout=10)
            r.call('ALFaceDetection', 'subscribe', self.NAME, 400, 0.0)
            while gen == self._gen:
                try:
                    val = r.call('ALMemory', 'getData', 'FaceDetected')
                    faces, cam = self.parse(val)
                    self.faces, self.camera, self.stamp = faces, cam, time.time()
                except Exception:
                    pass
                time.sleep(0.35)
        except Exception as e:
            self.on_status("rilevamento volti non disponibile: %s" % e)
        finally:
            if r:
                try:
                    r.call('ALFaceDetection', 'unsubscribe', self.NAME)
                except Exception:
                    pass
                r.close()
