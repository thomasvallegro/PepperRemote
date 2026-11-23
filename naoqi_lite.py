"""
naoqi_lite  -  Client NAOqi (qimessaging) minimale e autonomo, solo stdlib.
Parla con un robot Pepper/NAO NAOqi 2.x via porta 9559, senza l'SDK ufficiale.

Scoperto/validato su un Pepper NAOqi 2.5:
  - header qi: magic 0x42dead42 in BIG-ENDIAN, resto little-endian
  - autenticazione aperta (nessuna password) -> __qi_auth_state == 3 (DONE)

Autore: generato per il progetto PepperRemote.
"""
import socket
import struct
import threading

DEFAULT_HOST = "172.20.10.6"
DEFAULT_PORT = 9559
MAGIC = 0x42dead42


# --------------------------------------------------------------------------
# Serializzazione tipi qi
# --------------------------------------------------------------------------
def u32(n):
    return struct.pack('<I', n)


def qstr(s):
    b = s.encode('utf-8') if isinstance(s, str) else s
    return u32(len(b)) + b


class _AnyEmpty:
    """Segnaposto per un AnyValue 'vuoto' (lista vuota) usato come config di default."""
    pass


EMPTY = _AnyEmpty()


def _anyval_bool(v):
    return qstr('b') + (b'\x01' if v else b'\x00')


def capability_map():
    entries = [
        ("MetaObjectCache", _anyval_bool(True)),
        ("MessageFlags", _anyval_bool(True)),
        ("RemoteCancelableCalls", _anyval_bool(True)),
        ("ClientServerSocket", _anyval_bool(True)),
        ("ObjectPtrUID", _anyval_bool(True)),
    ]
    out = u32(len(entries))
    for k, av in entries:
        out += qstr(k) + av
    return out


# --------------------------------------------------------------------------
# Parser di signature qi  ->  albero di tipi (ignora le annotazioni <...>)
# --------------------------------------------------------------------------
def parse_sig(sig):
    pos = 0

    def skip_annot():
        nonlocal pos
        if pos < len(sig) and sig[pos] == '<':
            depth = 0
            while pos < len(sig):
                if sig[pos] == '<':
                    depth += 1
                elif sig[pos] == '>':
                    depth -= 1
                    if depth == 0:
                        pos += 1
                        break
                pos += 1

    def parse_one():
        nonlocal pos
        c = sig[pos]
        pos += 1
        if c in 'vbcCwWiIlLfdsmroX':
            return (c,)
        if c == '[':
            elem = parse_one()
            if pos < len(sig) and sig[pos] == ']':
                pos += 1
            skip_annot()
            return ('[', elem)
        if c == '{':
            k = parse_one()
            v = parse_one()
            if pos < len(sig) and sig[pos] == '}':
                pos += 1
            skip_annot()
            return ('{', k, v)
        if c == '(':
            elems = []
            while pos < len(sig) and sig[pos] != ')':
                elems.append(parse_one())
            pos += 1
            skip_annot()
            return ('(', elems)
        raise ValueError("signature non valida %r in %r" % (c, sig))

    nodes = []
    while pos < len(sig):
        if sig[pos] == '<':
            skip_annot()
            continue
        nodes.append(parse_one())
    return nodes


_SIMPLE = {'b': 1, 'c': 1, 'C': 1, 'w': 2, 'W': 2,
           'i': 4, 'I': 4, 'l': 8, 'L': 8, 'f': 4, 'd': 8}


def decode(node, buf, pos):
    k = node[0]
    if k in _SIMPLE:
        n = _SIMPLE[k]
        raw = buf[pos:pos + n]
        pos += n
        if k == 'b':
            return (raw[0] != 0), pos
        if k == 'f':
            return struct.unpack('<f', raw)[0], pos
        if k == 'd':
            return struct.unpack('<d', raw)[0], pos
        return int.from_bytes(raw, 'little', signed=k.islower()), pos
    if k in ('s', 'r'):
        n = int.from_bytes(buf[pos:pos + 4], 'little')
        pos += 4
        b = buf[pos:pos + n]
        pos += n
        return (b.decode('utf-8', 'replace') if k == 's' else b), pos
    if k == 'm':
        n = int.from_bytes(buf[pos:pos + 4], 'little')
        pos += 4
        sg = buf[pos:pos + n].decode('utf-8', 'replace')
        pos += n
        if not sg:
            return None, pos
        return decode(parse_sig(sg)[0], buf, pos)
    if k == 'o':
        raise ValueError("decode di 'object' non supportato")
    if k == '[':
        n = int.from_bytes(buf[pos:pos + 4], 'little')
        pos += 4
        out = []
        for _ in range(n):
            v, pos = decode(node[1], buf, pos)
            out.append(v)
        return out, pos
    if k == '{':
        n = int.from_bytes(buf[pos:pos + 4], 'little')
        pos += 4
        out = {}
        for _ in range(n):
            kk, pos = decode(node[1], buf, pos)
            vv, pos = decode(node[2], buf, pos)
            out[kk] = vv
        return out, pos
    if k == '(':
        out = []
        for el in node[1]:
            v, pos = decode(el, buf, pos)
            out.append(v)
        return tuple(out), pos
    raise ValueError("decode: tipo non gestito %r" % (k,))


def _ser_one(node, val):
    k = node[0]
    if k == 's':
        return qstr(val)
    if k == 'b':
        return b'\x01' if val else b'\x00'
    if k in ('i', 'I'):
        return struct.pack('<i' if k == 'i' else '<I', int(val))
    if k in ('l', 'L'):
        return struct.pack('<q' if k == 'l' else '<Q', int(val))
    if k == 'f':
        return struct.pack('<f', float(val))
    if k == 'd':
        return struct.pack('<d', float(val))
    if k == 'r':
        return qstr(val if isinstance(val, (bytes, bytearray)) else bytes(val))
    if k == 'm':
        # AnyValue: se EMPTY -> lista vuota; altrimenti prova a dedurre
        if isinstance(val, _AnyEmpty):
            return qstr('[m]') + u32(0)
        if isinstance(val, bool):
            return qstr('b') + (b'\x01' if val else b'\x00')
        if isinstance(val, int):
            return qstr('i') + struct.pack('<i', val)
        if isinstance(val, float):
            return qstr('f') + struct.pack('<f', val)
        if isinstance(val, str):
            return qstr('s') + qstr(val)
        if isinstance(val, (bytes, bytearray)):
            return qstr('r') + qstr(bytes(val))
        if isinstance(val, (list, tuple)) and val and all(isinstance(x, str) for x in val):
            # lista di stringhe (es. nomi dei giunti)
            out = qstr('[s]') + u32(len(val))
            for x in val:
                out += qstr(x)
            return out
        if isinstance(val, (list, tuple)):
            # lista di float per default
            out = qstr('[f]') + u32(len(val))
            for x in val:
                out += struct.pack('<f', float(x))
            return out
        raise ValueError("AnyValue non serializzabile: %r" % (val,))
    if k == '[':
        out = u32(len(val))
        for v in val:
            out += _ser_one(node[1], v)
        return out
    if k == '(':
        out = b''
        for el, v in zip(node[1], val):
            out += _ser_one(el, v)
        return out
    raise ValueError("serializzazione non gestita per %r" % (node,))


def ser_args(parsig, args):
    nodes = parse_sig(parsig)[0] if parsig else ('(', [])
    elems = nodes[1] if nodes and nodes[0] == '(' else [nodes]
    out = b''
    for node, val in zip(elems, args):
        out += _ser_one(node, val)
    return out


def num_params(parsig):
    nodes = parse_sig(parsig)[0] if parsig else ('(', [])
    return len(nodes[1]) if nodes and nodes[0] == '(' else 1


# --------------------------------------------------------------------------
# Messaggistica
# --------------------------------------------------------------------------
def _header(mid, size, mtype, service, obj, action, version=0, flags=0):
    return (struct.pack('>I', MAGIC) +
            struct.pack('<IIHBBIII', mid, size, version, mtype, flags, service, obj, action))


def _recv_all(sock, n):
    d = b''
    while len(d) < n:
        c = sock.recv(n - len(d))
        if not c:
            break
        d += c
    return d


def _read_msg(sock):
    h = _recv_all(sock, 28)
    if len(h) < 28:
        return None
    _, mid, size, version, mtype, flags, service, obj, action = struct.unpack('<IIIHBBIII', h)
    body = _recv_all(sock, size) if size else b''
    return dict(id=mid, size=size, type=mtype, service=service, obj=obj, action=action, body=body)


META_SIG = '({I(Issss[(ss)]s)}{I(Iss)}{I(Iss)}s)'


class RobotError(Exception):
    pass


class Session:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=10):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._mid = 0
        self._lock = threading.Lock()

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def call_raw(self, service, obj, action, payload=b''):
        with self._lock:
            self._mid += 1
            mid = self._mid
            self.sock.sendall(_header(mid, len(payload), 1, service, obj, action) + payload)
            while True:
                m = _read_msg(self.sock)
                if m is None:
                    raise RobotError("connessione chiusa dal robot")
                if m['id'] == mid and m['type'] in (2, 3):
                    if m['type'] == 3:
                        # corpo = AnyValue stringa d'errore
                        try:
                            msg, _ = decode(('m',), m['body'], 0)
                        except Exception:
                            msg = repr(m['body'][:120])
                        raise RobotError("errore NAOqi: %s" % msg)
                    return m['body']

    def authenticate(self):
        body = self.call_raw(0, 1, 8, capability_map())
        i = body.find(b'__qi_auth_state')
        if i < 0:
            return None
        p = i + len(b'__qi_auth_state')
        sl = int.from_bytes(body[p:p + 4], 'little')
        p += 4 + sl
        return int.from_bytes(body[p:p + 4], 'little')


def _get_methods(sess, service, obj=1):
    """Ritorna  nome -> lista di overload (uid, returnSig, paramSig)."""
    body = sess.call_raw(service, obj, 2, u32(obj))  # metaObject(objectId)
    val, _ = decode(parse_sig(META_SIG)[0], body, 0)
    methods = val[0]
    byname = {}
    for uid, mm in methods.items():
        name, ret, par = mm[2], mm[1], mm[3]
        byname.setdefault(name, []).append((uid, ret, par))
    return byname


def _type_ok(sigchar, val):
    if sigchar in 'sr':
        return isinstance(val, (str, bytes, bytearray))
    if sigchar in 'iIlLwWcC':
        return isinstance(val, int) and not isinstance(val, bool)
    if sigchar in 'fd':
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if sigchar == 'b':
        return isinstance(val, bool)
    return True  # 'm' e contenitori accettano tutto


def _resolve_overload(name, overloads, args):
    best = None
    for uid, ret, par in overloads:
        nodes = parse_sig(par)[0] if par else ('(', [])
        elems = nodes[1] if nodes and nodes[0] == '(' else [nodes]
        if len(elems) != len(args):
            continue
        score = sum(1 for e, a in zip(elems, args) if _type_ok(e[0], a))
        if best is None or score > best[0]:
            best = (score, uid, ret, par)
    if best is None:
        raise RobotError("%s: nessun overload con %d argomenti" % (name, len(args)))
    return best[1], best[2], best[3]


class Robot:
    """Connessione ad alto livello: risolve i servizi per nome e chiama i metodi per nome."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=10):
        self.sess = Session(host, port, timeout)
        st = self.sess.authenticate()
        if st != 3:
            self.sess.close()
            raise RobotError("autenticazione non aperta (stato=%s): il robot richiede password" % st)
        self._svc = {}
        self._sd = _get_methods(self.sess, 1)

    def close(self):
        self.sess.close()

    def _resolve(self, name):
        suid, sret, _ = self._sd['service'][0]
        body = self.sess.call_raw(1, 1, suid, qstr(name))
        info, _ = decode(parse_sig(sret)[0], body, 0)
        return info[1]  # serviceId

    def service(self, name):
        if name not in self._svc:
            sid = self._resolve(name)
            self._svc[name] = (sid, _get_methods(self.sess, sid))
        return self._svc[name]

    def call(self, service, method, *args):
        sid, methods = self.service(service)
        if method not in methods:
            raise RobotError("%s non ha il metodo %s" % (service, method))
        uid, ret, par = _resolve_overload(method, methods[method], args)
        payload = ser_args(par, args)
        body = self.sess.call_raw(sid, 1, uid, payload)
        if ret in ('v', ''):
            return None
        val, _ = decode(parse_sig(ret)[0], body, 0)
        return val

    def methods(self, service):
        return self.service(service)[1]

    # ---------------- comandi di comodo ----------------
    def robot_name(self):
        try:
            return self.call('ALSystem', 'robotName')
        except Exception:
            return "Pepper"

    def naoqi_version(self):
        return self.call('ALSystem', 'systemVersion')

    def battery(self):
        return self.call('ALBattery', 'getBatteryCharge')

    def life_state(self):
        return self.call('ALAutonomousLife', 'getState')

    def set_life(self, state):
        return self.call('ALAutonomousLife', 'setState', state)

    def wake_up(self):
        return self.call('ALMotion', 'wakeUp')

    def rest(self):
        return self.call('ALMotion', 'rest')

    def say(self, text, language=None):
        _, methods = self.service('ALTextToSpeech')
        arities = [num_params(o[2]) for o in methods['say']]
        if 1 in arities and language is None:
            return self.call('ALTextToSpeech', 'say', text)
        lang = language or self.call('ALTextToSpeech', 'getLanguage')
        return self.call('ALTextToSpeech', 'say', text, lang)

    def set_tts_volume(self, v01):
        return self.call('ALTextToSpeech', 'setVolume', float(v01))

    def set_output_volume(self, v0_100):
        return self.call('ALAudioDevice', 'setOutputVolume', int(v0_100))

    def get_output_volume(self):
        return self.call('ALAudioDevice', 'getOutputVolume')

    def languages(self):
        try:
            return self.call('ALTextToSpeech', 'getAvailableLanguages')
        except Exception:
            return []

    def set_language(self, lang):
        return self.call('ALTextToSpeech', 'setLanguage', lang)

    def posture(self, name="Stand", speed=0.6):
        return self.call('ALRobotPosture', 'goToPosture', name, float(speed))

    def walk(self, x, y, theta):
        return self.call('ALMotion', 'moveToward', float(x), float(y), float(theta), EMPTY)

    def stop_move(self):
        return self.call('ALMotion', 'stopMove')

    def move_toward(self, x, y, theta):
        """Velocita' normalizzate in [-1, 1] (frazione della velocita' massima)."""
        return self.call('ALMotion', 'moveToward', float(x), float(y), float(theta), EMPTY)

    def set_angles(self, names, angles, speed=0.2):
        """Muove i giunti (non bloccante). speed = frazione della velocita' massima (0..1)."""
        return self.call('ALMotion', 'setAngles', list(names), [float(a) for a in angles], float(speed))

    def get_angles(self, names, use_sensors=True):
        return self.call('ALMotion', 'getAngles', list(names), bool(use_sensors))

    def awareness(self, enabled):
        """Attiva/disattiva lo sguardo automatico (altrimenti combatte con i comandi della testa)."""
        try:
            return self.call('ALBasicAwareness', 'setEnabled', bool(enabled))
        except Exception:
            return self.call('ALBasicAwareness', 'startAwareness' if enabled else 'stopAwareness')

    # --- telecamera ---
    def camera_subscribe(self, name="PepperRemoteCam", camera=0, resolution=1, colorspace=11, fps=15):
        """camera 0=fronte (testa) 1=bassa; resolution 0=160x120 1=320x240 2=640x480; 11=RGB."""
        return self.call('ALVideoDevice', 'subscribeCamera', name, int(camera), int(resolution),
                         int(colorspace), int(fps))

    def camera_frame(self, handle):
        """(larghezza, altezza, byte RGB) oppure None."""
        img = self.call('ALVideoDevice', 'getImageRemote', handle)
        if not img or len(img) < 7:
            return None
        return int(img[0]), int(img[1]), bytes(img[6])

    def camera_set(self, handle, camera):
        return self.call('ALVideoDevice', 'setActiveCamera', handle, int(camera))

    def camera_unsubscribe(self, handle):
        return self.call('ALVideoDevice', 'unsubscribe', handle)

    def leds_rgb(self, hexrgb, group="FaceLeds", duration=0.4):
        return self.call('ALLeds', 'fadeRGB', group, int(hexrgb) & 0xFFFFFF, float(duration))

    # --- tablet ---
    def tablet_url(self, url):
        return self.call('ALTabletService', 'showWebview', url)

    def tablet_load(self, url):
        return self.call('ALTabletService', 'loadUrl', url)

    def tablet_image(self, url):
        return self.call('ALTabletService', 'showImage', url)

    def tablet_video(self, url):
        return self.call('ALTabletService', 'playVideo', url)

    def tablet_hide(self):
        return self.call('ALTabletService', 'hideWebview')

    def tablet_brightness(self, v01):
        return self.call('ALTabletService', 'setBrightness', float(v01))

    # --- audio ---
    def play_stream(self, url, volume=1.0, pan=0.0):
        return self.call('ALAudioPlayer', 'playWebStream', url, float(volume), float(pan))

    def play_file(self, path, volume=1.0, pan=0.0):
        return self.call('ALAudioPlayer', 'playFile', path, float(volume), float(pan))

    def audio_stop(self):
        return self.call('ALAudioPlayer', 'stopAll')

    def send_audio_buffer(self, nb_frames, pcm_bytes):
        # ALAudioDevice.sendRemoteBufferToOutput(int nbFrames, AnyValue buffer)
        return self.call('ALAudioDevice', 'sendRemoteBufferToOutput', int(nb_frames), bytes(pcm_bytes))


if __name__ == '__main__':
    import sys
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    r = Robot(host)
    print("Connesso a", r.robot_name(), "- NAOqi", r.naoqi_version())
    print("Batteria:", r.battery(), "%   AutonomousLife:", r.life_state())
