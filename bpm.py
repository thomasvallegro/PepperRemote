# -*- coding: utf-8 -*-
"""
Rilevamento automatico del tempo (BPM) di un brano.

Metodo (classico, senza librerie extra oltre a numpy):
  1. ffmpeg decodifica l'audio in mono a 11 kHz;
  2. si calcola lo spettro a piccoli passi e si misura quanto "cresce" l'energia da un istante
     al successivo (spectral flux): i picchi sono gli attacchi delle note e dei colpi di batteria;
  3. l'autocorrelazione di questa curva mostra ogni quanto si ripetono gli attacchi:
     il ritardo piu' forte, tra 60 e 200 BPM, e' il battito del brano.
Il risultato si salva accanto all'mp3 (file .bpm) per non ricalcolarlo.
"""
import os
import subprocess

import numpy as np

SR = 11025
HOP = 256
NFFT = 1024
FPS = SR / float(HOP)      # ~43 valori al secondo
BPM_RANGE = (70, 160)      # stesso intervallo del cursore del ballo


def _decode(path, seconds=150):
    import imageio_ffmpeg
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "quiet", "-i", path,
                          "-ac", "1", "-ar", str(SR), "-t", str(seconds), "-f", "s16le", "-"],
                         capture_output=True, creationflags=flags).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def onset_envelope(x):
    n = 1 + (len(x) - NFFT) // HOP
    if n < 50:
        raise ValueError("brano troppo corto per misurare il tempo")
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(NFFT)[None, :]
    mag = np.log1p(100.0 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    # toglie l'andamento lento (strofe piu' forti/piano): restano solo gli attacchi
    k = int(FPS)  # ~1 secondo
    local = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0.0, flux - local)
    return env / (env.std() + 1e-9)


def tempo_from_envelope(env):
    e = env - env.mean()
    nfft = 1 << int(np.ceil(np.log2(2 * len(e))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(e, nfft)) ** 2)[: len(e)]
    ac = ac / (ac[0] + 1e-9)

    def ac_at(lag):            # autocorrelazione a un ritardo non intero (interpolata)
        i = int(lag)
        if i + 1 >= len(ac):
            return 0.0
        f = lag - i
        return ac[i] * (1 - f) + ac[i + 1] * f

    best, best_score = 120.0, -1e9
    for cand in np.arange(BPM_RANGE[0], BPM_RANGE[1] + 0.25, 0.25):
        lag = 60.0 * FPS / cand
        # il battito vero ha attacchi anche al 2°, 3° e 4° battito successivo: si sommano.
        # Cosi' 2/3 o 3/2 del tempo (che non tornano sui multipli) perdono punti.
        s = sum(ac_at(lag * k) / k ** 0.5 for k in (1, 2, 3, 4))
        # preferenza per i tempi "da ballo" (intorno a 120): tra meta' e doppio sceglie quello
        s *= np.exp(-0.5 * (np.log2(cand / 120.0) / 0.5) ** 2)
        if s > best_score:
            best, best_score = cand, s
    return best


def detect_bpm(path):
    """BPM del file audio (intero), con cache nel file <nome>.bpm."""
    cache = os.path.splitext(path)[0] + ".bpm"
    if os.path.exists(cache):
        try:
            return int(open(cache).read().strip())
        except Exception:
            pass
    bpm = int(round(tempo_from_envelope(onset_envelope(_decode(path)))))
    try:
        with open(cache, "w") as f:
            f.write(str(bpm))
    except Exception:
        pass
    return bpm
