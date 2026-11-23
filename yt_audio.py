# -*- coding: utf-8 -*-
"""
Audio da YouTube per il Pepper.

Il robot (ALAudioPlayer.playWebStream) sa riprodurre solo file audio diretti (mp3, radio),
non le pagine di YouTube. Qui il PC:
  1. scarica l'audio del video con yt-dlp e lo converte in mp3 (ffmpeg di imageio-ffmpeg);
  2. lo serve sulla rete locale con un piccolo server HTTP;
  3. restituisce l'indirizzo http://<IP del PC>:8090/<file>.mp3 da passare al robot.
I file scaricati restano in cache: la seconda volta parte subito.

Il server HTTP gira con python.exe (non pythonw.exe) perche' e' il programma
a cui il firewall di Windows permette le connessioni in entrata.
"""
import os
import re
import sys
import socket
import subprocess

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(APP_DIR, "cache_audio")
FILE_PORT = 8090

_server_proc = None

RE_YT = re.compile(r"^(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/", re.I)


def is_youtube(url):
    return bool(RE_YT.match(url.strip()))


def _python_exe():
    exe = sys.executable
    d, name = os.path.split(exe)
    if name.lower() == "pythonw.exe":
        cand = os.path.join(d, "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


def ensure_server():
    """Avvia (una volta) il server HTTP che serve la cartella cache_audio."""
    global _server_proc
    os.makedirs(CACHE_DIR, exist_ok=True)
    if _server_proc is not None and _server_proc.poll() is None:
        return
    s = socket.socket()
    try:
        in_use = s.connect_ex(("127.0.0.1", FILE_PORT)) == 0
    finally:
        s.close()
    if in_use:          # gia' attivo (es. avviato da un'istanza precedente)
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _server_proc = subprocess.Popen(
        [_python_exe(), "-m", "http.server", str(FILE_PORT), "--bind", "0.0.0.0",
         "--directory", CACHE_DIR],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def stop_server():
    global _server_proc
    if _server_proc is not None and _server_proc.poll() is None:
        _server_proc.terminate()
    _server_proc = None


def find_deno():
    """YouTube richiede un motore JavaScript per sbloccare i video: cerca Deno (installato con winget)."""
    import glob
    import shutil
    exe = shutil.which("deno")
    if exe:
        return exe
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet")
    for pattern in (os.path.join(base, "Links", "deno.exe"),
                    os.path.join(base, "Packages", "DenoLand.Deno*", "deno.exe")):
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def download_mp3(url, progress=None):
    """Scarica l'audio del video come mp3 in cache. Ritorna (nome_file, titolo)."""
    import yt_dlp
    import imageio_ffmpeg
    os.makedirs(CACHE_DIR, exist_ok=True)

    def hook(d):
        if progress and d.get("status") == "downloading":
            pct = (d.get("_percent_str") or "").strip()
            progress("scarico da YouTube... %s" % pct)

    # Opzioni costruite come da riga di comando: con il dizionario "a mano" YouTube
    # risponde 403, con le impostazioni predefinite della riga di comando no.
    args = ["-f", "bestaudio/best", "--no-playlist", "-q", "--no-warnings",
            "-o", os.path.join(CACHE_DIR, "%(id)s.%(ext)s"),
            "-x", "--audio-format", "mp3", "--audio-quality", "160K",
            "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
            # 44,1 kHz stereo: formato che il lettore del robot gestisce senza problemi
            "--postprocessor-args", "ExtractAudio:-ar 44100 -ac 2"]
    deno = find_deno()
    if deno:
        args += ["--js-runtimes", "deno:" + deno]
    opts = yt_dlp.parse_options(args).ydl_opts
    opts["progress_hooks"] = [hook]

    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})", url)
    vid = m.group(1) if m else None
    title_file = os.path.join(CACHE_DIR, "%s.txt" % vid) if vid else None
    if vid and os.path.exists(os.path.join(CACHE_DIR, vid + ".mp3")):
        title = vid
        if os.path.exists(title_file):
            title = open(title_file, encoding="utf-8").read().strip() or vid
        if progress:
            progress("gia' in memoria: %s" % title)
        return vid + ".mp3", title

    opts["ignoreerrors"] = False      # la riga di comando ignora gli errori di download: qui no
    info = None
    for attempt in range(1, 4):       # YouTube a volte risponde 403: si riprova
        if progress:
            progress("scarico da YouTube...%s" % ("" if attempt == 1 else " (tentativo %d)" % attempt))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if os.path.exists(os.path.join(CACHE_DIR, info["id"] + ".mp3")):
                break
        except Exception as e:
            if attempt == 3:
                raise RuntimeError("YouTube non ha concesso il download (%s)" % str(e)[:120])
    vid = info["id"]
    title = info.get("title") or vid
    with open(os.path.join(CACHE_DIR, "%s.txt" % vid), "w", encoding="utf-8") as f:
        f.write(title)
    if not os.path.exists(os.path.join(CACHE_DIR, vid + ".mp3")):
        raise RuntimeError("conversione in mp3 non riuscita")
    if progress:
        progress("audio pronto: %s" % title)
    return vid + ".mp3", title


def youtube_to_robot_url(url, pc_ip, progress=None):
    """Da link YouTube a indirizzo http che il robot puo' riprodurre."""
    fname, title = download_mp3(url, progress)
    ensure_server()
    return "http://%s:%d/%s" % (pc_ip, FILE_PORT, fname), title
