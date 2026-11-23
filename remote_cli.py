"""
remote_cli - telecomando da terminale per il robot (stesso motore della GUI).

Esempi:
  python remote_cli.py say "Ciao a tutti"
  python remote_cli.py battery
  python remote_cli.py state
  python remote_cli.py life disabled
  python remote_cli.py posture Stand
  python remote_cli.py led 2F7BFF
  python remote_cli.py vol 50
  python remote_cli.py walk 0.6 0 0 --sec 2
  python remote_cli.py tablet https://www.google.com
  python remote_cli.py play http://stream.srg-ssr.ch/m/rsc_it/mp3_128

Host diverso:  python remote_cli.py --host 172.20.10.6 battery
"""
import argparse
import time
import sys
import naoqi_lite as nq


def main():
    ap = argparse.ArgumentParser(description="Telecomando Pepper")
    ap.add_argument("--host", default=nq.DEFAULT_HOST)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("battery")
    sub.add_parser("state")
    sub.add_parser("wake")
    sub.add_parser("rest")
    p = sub.add_parser("say"); p.add_argument("text")
    p = sub.add_parser("life"); p.add_argument("value", choices=["disabled", "solitary", "interactive", "safeguard"])
    p = sub.add_parser("posture"); p.add_argument("name"); p.add_argument("--speed", type=float, default=0.6)
    p = sub.add_parser("led"); p.add_argument("hex", help="RRGGBB, es. 2F7BFF")
    p = sub.add_parser("vol"); p.add_argument("level", type=int, help="0-100")
    p = sub.add_parser("walk"); p.add_argument("x", type=float); p.add_argument("y", type=float)
    p.add_argument("theta", type=float); p.add_argument("--sec", type=float, default=2.0)
    p = sub.add_parser("tablet"); p.add_argument("url")
    p = sub.add_parser("image"); p.add_argument("url")
    p = sub.add_parser("play"); p.add_argument("url")
    sub.add_parser("stopaudio")
    p = sub.add_parser("call", help="chiamata generica: SERVIZIO METODO [arg...]")
    p.add_argument("service"); p.add_argument("method"); p.add_argument("args", nargs="*")

    a = ap.parse_args()
    r = nq.Robot(a.host)

    if a.cmd == "battery":
        print("Batteria:", r.battery(), "%")
    elif a.cmd == "state":
        print("Robot:", r.robot_name(), "| NAOqi:", r.naoqi_version(),
              "| Life:", r.life_state(), "| Batteria:", r.battery(), "%")
    elif a.cmd == "wake":
        r.wake_up(); print("sveglio")
    elif a.cmd == "rest":
        r.rest(); print("a riposo")
    elif a.cmd == "say":
        r.say(a.text); print("detto.")
    elif a.cmd == "life":
        r.set_life(a.value); print("Autonomous Life ->", a.value)
    elif a.cmd == "posture":
        ok = r.posture(a.name, a.speed); print("postura", a.name, "->", ok)
    elif a.cmd == "led":
        r.leds_rgb(int(a.hex, 16)); print("led impostati")
    elif a.cmd == "vol":
        r.set_output_volume(a.level); print("volume casse ->", a.level)
    elif a.cmd == "walk":
        r.wake_up(); r.walk(a.x, a.y, a.theta)
        print("cammino per %.1fs..." % a.sec); time.sleep(a.sec); r.stop_move(); print("stop")
    elif a.cmd == "tablet":
        print("showWebview ->", r.tablet_url(a.url))
    elif a.cmd == "image":
        print("showImage ->", r.tablet_image(a.url))
    elif a.cmd == "play":
        r.play_stream(a.url); print("in riproduzione")
    elif a.cmd == "stopaudio":
        r.audio_stop(); print("audio fermato")
    elif a.cmd == "call":
        conv = []
        for x in a.args:
            try:
                conv.append(int(x))
            except ValueError:
                try:
                    conv.append(float(x))
                except ValueError:
                    conv.append(x)
        print(r.call(a.service, a.method, *conv))

    r.close()


if __name__ == "__main__":
    try:
        main()
    except nq.RobotError as e:
        print("Errore robot:", e, file=sys.stderr); sys.exit(1)
