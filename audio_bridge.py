"""
audio_bridge - sperimentale.
Cattura l'audio di SISTEMA di Windows (WASAPI loopback) e lo invia alle casse
del robot tramite ALAudioDevice.sendRemoteBufferToOutput.

Richiede pacchetti extra (solo per questa funzione):
    pip install PyAudioWPatch numpy

Il robot riproduce buffer PCM int16 stereo a 48000 Hz. Catturiamo l'uscita
alla frequenza nativa del dispositivo e, se serve, ricampioniamo a 48 kHz.
"""
import threading

ROBOT_RATE = 48000      # Hz attesi dalle casse del robot
ROBOT_CH = 2            # stereo


class MissingDeps(Exception):
    pass


def _load_deps():
    try:
        import pyaudiowpatch as pyaudio
    except Exception as e:
        raise MissingDeps("PyAudioWPatch non installato: pip install PyAudioWPatch") from e
    try:
        import numpy as np
    except Exception as e:
        raise MissingDeps("numpy non installato: pip install numpy") from e
    return pyaudio, np


def list_loopback_devices():
    """Elenco (indice, nome) dei dispositivi di uscita catturabili in loopback.
    Scegli il cavo virtuale (es. 'CABLE Input') per NON far uscire l'audio
    dalle casse del PC (comportamento da cassa Bluetooth)."""
    pyaudio, _ = _load_deps()
    p = pyaudio.PyAudio()
    out = []
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_idx = wasapi["defaultOutputDevice"]
        default_name = p.get_device_info_by_index(default_idx)["name"]
        for info in p.get_loopback_device_info_generator():
            label = info["name"]
            if default_name in label:
                label += "  [predefinito]"
            out.append((info["index"], label))
    finally:
        p.terminate()
    return out


class LiveAudioBridge:
    def __init__(self, robot, chunk_frames=2048, on_status=None, device_index=None):
        self.robot = robot
        self.chunk = chunk_frames
        self.on_status = on_status or (lambda s: None)
        self.device_index = device_index   # None = uscita predefinita
        self._stop = threading.Event()
        self._thread = None
        self.running = False

    def start(self):
        pyaudio, np = _load_deps()   # alza MissingDeps se mancano
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(pyaudio, np), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.running = False

    def _run(self, pyaudio, np):
        p = pyaudio.PyAudio()
        stream = None
        try:
            if self.device_index is not None:
                # dispositivo scelto esplicitamente (es. cavo virtuale)
                loop = p.get_device_info_by_index(self.device_index)
            else:
                # dispositivo loopback di default (uscita predefinita di Windows)
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                loop = None
                for info in p.get_loopback_device_info_generator():
                    if default_out["name"] in info["name"]:
                        loop = info
                        break
                if loop is None:
                    loop = next(p.get_loopback_device_info_generator())
            src_rate = int(loop["defaultSampleRate"])
            src_ch = int(loop["maxInputChannels"]) or 2

            stream = p.open(format=pyaudio.paInt16, channels=src_ch, rate=src_rate,
                            frames_per_buffer=self.chunk, input=True,
                            input_device_index=loop["index"])
            self.running = True
            self.on_status("in diretta: %s  (%d Hz, %d ch) -> robot 48kHz" %
                           (loop["name"][:40], src_rate, src_ch))

            ratio = ROBOT_RATE / float(src_rate)
            while not self._stop.is_set():
                raw = stream.read(self.chunk, exception_on_overflow=False)
                a = np.frombuffer(raw, dtype=np.int16)
                if src_ch > 1:
                    a = a.reshape(-1, src_ch)
                    # mixa a stereo: usa i primi due canali
                    if src_ch >= 2:
                        st = a[:, :2].astype(np.float32)
                    else:
                        st = np.repeat(a.astype(np.float32), 2, axis=1)
                else:
                    st = np.repeat(a.reshape(-1, 1).astype(np.float32), 2, axis=1)

                if abs(ratio - 1.0) > 1e-3:
                    n_out = int(st.shape[0] * ratio)
                    idx = (np.arange(n_out) / ratio).astype(np.int64)
                    idx = np.clip(idx, 0, st.shape[0] - 1)
                    st = st[idx]

                pcm = np.clip(st, -32768, 32767).astype('<i2').tobytes()
                nb = st.shape[0]  # frame stereo
                try:
                    self.robot.send_audio_buffer(nb, pcm)
                except Exception as e:
                    self.on_status("errore invio audio: %s" % e)
                    break
        except Exception as e:
            self.on_status("audio stream fermato: %s" % e)
        finally:
            try:
                if stream:
                    stream.stop_stream(); stream.close()
            except Exception:
                pass
            p.terminate()
            self.running = False
