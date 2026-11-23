# -*- coding: utf-8 -*-
"""
Balli per Pepper: coreografie a tempo (BPM) fatte di pose di braccia, testa e fianchi.
Il robot resta fermo sulle ruote (si muove solo il corpo): piu' sicuro in mezzo alla gente.
Usa una connessione dedicata, cosi' non blocca il resto di PepperRemote.
"""
import time
import threading

import naoqi_lite as nq

# limiti dei giunti di Pepper (radianti), per sicurezza
LIMITS = {
    "HeadYaw": (-2.08, 2.08), "HeadPitch": (-0.70, 0.63),
    "LShoulderPitch": (-2.08, 2.08), "RShoulderPitch": (-2.08, 2.08),
    "LShoulderRoll": (0.01, 1.56), "RShoulderRoll": (-1.56, -0.01),
    "LElbowYaw": (-2.08, 2.08), "RElbowYaw": (-2.08, 2.08),
    "LElbowRoll": (-1.56, -0.01), "RElbowRoll": (0.01, 1.56),
    "LWristYaw": (-1.82, 1.82), "RWristYaw": (-1.82, 1.82),
    "HipRoll": (-0.51, 0.51), "HipPitch": (-1.03, 1.03),
}


def arm(side, pitch, roll, eyaw, eroll, wrist=0.0):
    """Posa di un braccio descritta come per il SINISTRO; per il destro gli angoli si specchiano."""
    s = 1.0 if side == "L" else -1.0
    return {side + "ShoulderPitch": pitch, side + "ShoulderRoll": s * roll,
            side + "ElbowYaw": s * eyaw, side + "ElbowRoll": s * eroll, side + "WristYaw": s * wrist}


def pose(l, r, head=(0.0, -0.15), hip=(0.0, -0.03)):
    p = {}
    p.update(arm("L", *l))
    p.update(arm("R", *r))
    p["HeadYaw"], p["HeadPitch"] = head
    p["HipRoll"], p["HipPitch"] = hip
    return p


# pose base del braccio (pitch, roll, elbowYaw, elbowRoll)
GIU = (1.45, 0.15, -1.2, -0.45)          # braccio rilassato
SU = (-1.0, 0.25, -1.2, -0.2)            # braccio alzato
DIAG_SU = (-1.0, 0.85, -1.0, -0.1)       # in alto e in fuori (disco)
FIANCO = (1.25, 0.55, -0.4, -1.45)       # mano sul fianco
FUORI_DRITTO = (0.1, 1.25, -1.2, -0.1)   # braccio aperto di lato
FUORI_PIEGATO = (0.1, 1.25, -1.2, -1.3)
AVANTI = (0.15, 0.05, -1.6, -1.25)       # mani davanti al petto
ALTO_TESTA = (-1.3, 0.12, -1.2, -0.65)   # mani sopra la testa

NEUTRA = pose(GIU, GIU)

MOSSE = [
    ("Braccia su e giu'", [
        pose(SU, GIU, head=(0.25, -0.2), hip=(0.12, -0.03)),
        pose(GIU, SU, head=(-0.25, -0.2), hip=(-0.12, -0.03)),
    ]),
    ("Disco", [
        pose(FIANCO, DIAG_SU, head=(-0.35, -0.3), hip=(-0.1, -0.03)),
        pose(FIANCO, (0.9, 0.05, -1.2, -0.3), head=(0.2, 0.15), hip=(0.1, -0.03)),
    ]),
    ("Onda", [
        pose(FUORI_DRITTO, FUORI_PIEGATO, head=(0.2, -0.1), hip=(0.15, -0.03)),
        pose(FUORI_PIEGATO, FUORI_DRITTO, head=(-0.2, -0.1), hip=(-0.15, -0.03)),
    ]),
    ("Mani in alto", [
        pose(ALTO_TESTA, ALTO_TESTA, head=(0.0, -0.35), hip=(0.0, -0.05)),
        pose(AVANTI, AVANTI, head=(0.0, 0.05), hip=(0.0, -0.03)),
    ]),
    ("Testa a ritmo", [
        pose(FIANCO, FIANCO, head=(0.3, -0.25), hip=(0.2, -0.03)),
        pose(FIANCO, FIANCO, head=(0.0, 0.2), hip=(0.0, -0.03)),
        pose(FIANCO, FIANCO, head=(-0.3, -0.25), hip=(-0.2, -0.03)),
        pose(FIANCO, FIANCO, head=(0.0, 0.2), hip=(0.0, -0.03)),
    ]),
]
BATTITI_PER_MOSSA = 8


def _clamp(name, v):
    lo, hi = LIMITS.get(name, (-3.0, 3.0))
    return max(lo, min(hi, v))


class Dancer:
    def __init__(self, host, on_status=None):
        self.host = host
        self.on_status = on_status or (lambda m: None)
        self.bpm = 110
        self._gen = 0
        self._thread = None

    @property
    def dancing(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, bpm=None):
        if bpm:
            self.bpm = int(bpm)
        if self.dancing:
            return
        self._gen += 1
        self._thread = threading.Thread(target=self._run, args=(self._gen,), daemon=True)
        self._thread.start()

    def stop(self):
        self._gen += 1

    def _send(self, r, p, speed):
        names = sorted(p)
        r.set_angles(names, [_clamp(n, p[n]) for n in names], speed)

    def _run(self, gen):
        r = None
        try:
            r = nq.Robot(self.host)
            try:
                if not r.call('ALMotion', 'robotIsWakeUp'):
                    self.on_status("sveglio il robot per ballare...")
                    r.wake_up()
            except Exception:
                pass
            try:
                r.awareness(False)        # niente sguardo automatico durante il ballo
            except Exception:
                pass
            self.on_status("Pepper balla!")
            i = 0
            while gen == self._gen:
                nome, frames = MOSSE[(i // BATTITI_PER_MOSSA) % len(MOSSE)]
                if i % BATTITI_PER_MOSSA == 0:
                    self.on_status("Pepper balla: %s (%d BPM)" % (nome, self.bpm))
                beat = 60.0 / max(60, min(180, self.bpm))
                speed = 0.55 if self.bpm >= 110 else 0.4
                t0 = time.time()
                self._send(r, frames[i % len(frames)], speed)
                i += 1
                while gen == self._gen and time.time() - t0 < beat:
                    time.sleep(0.02)
        except Exception as e:
            self.on_status("errore ballo: %s" % e)
        finally:
            if r:
                try:
                    self._send(r, NEUTRA, 0.25)
                    time.sleep(1.2)
                    r.awareness(True)
                except Exception:
                    pass
                r.close()
            self.on_status("ballo fermato")
