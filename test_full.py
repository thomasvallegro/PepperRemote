"""Collaudo funzionale del Pepper via API. Uso: python test_full.py [sezioni...]
Sezioni: status lights speakers motors  (default: tutte)"""
import sys, time
import naoqi_lite as nq

HOST = "172.20.10.6"
SECTIONS = [a for a in sys.argv[1:] if not a[0].isdigit()] or ["status", "lights", "speakers", "motors"]

def ok(msg): print("  [OK]   " + msg)
def ko(msg, e): print("  [FAIL] %s -> %s" % (msg, e))

r = nq.Robot(HOST)
print("=" * 56)
print("COLLAUDO PEPPER  @", HOST)
print("=" * 56)

if "status" in SECTIONS:
    print("\n# STATO")
    try: ok("Nome robot: %s" % r.robot_name())
    except Exception as e: ko("robot_name", e)
    try: ok("Versione NAOqi: %s" % r.naoqi_version())
    except Exception as e: ko("naoqi_version", e)
    try: ok("Batteria: %d%%" % r.battery())
    except Exception as e: ko("battery", e)
    try: ok("Autonomous Life: %s" % r.life_state())
    except Exception as e: ko("life_state", e)
    try:
        sd = nq._get_methods(r.sess, 1); uid, ret, _ = sd["services"][0]
        body = r.sess.call_raw(1, 1, uid); svcs, _ = nq.decode(nq.parse_sig(ret)[0], body, 0)
        ok("Servizi NAOqi attivi: %d" % len(svcs))
    except Exception as e: ko("services", e)

if "lights" in SECTIONS:
    print("\n# LUCI (LED occhi)")
    for name, hexv in (("rosso", 0xFF0000), ("verde", 0x00FF00), ("blu", 0x0000FF), ("bianco", 0xFFFFFF)):
        try:
            r.leds_rgb(hexv, "FaceLeds", 0.3); ok("LED occhi -> %s" % name); time.sleep(0.8)
        except Exception as e: ko("LED %s" % name, e)
    for grp in ("ChestLeds",):
        try:
            r.call("ALLeds", "fadeRGB", grp, 0x2F7BFF, 0.3); ok("LED %s -> blu" % grp); time.sleep(0.6)
        except Exception as e: ko("LED %s" % grp, e)
    try:
        r.leds_rgb(0xFFFFFF, "FaceLeds", 0.3); ok("LED ripristinati a bianco")
    except Exception as e: ko("ripristino LED", e)

if "speakers" in SECTIONS:
    print("\n# CASSE (audio)")
    try: ok("Volume uscita attuale: %d" % r.get_output_volume())
    except Exception as e: ko("get volume", e)
    try:
        r.say("Test delle casse. Motori, luci e audio del robot."); ok("Sintesi vocale (say) riprodotta")
    except Exception as e: ko("say", e)
    try:
        r.call("ALAudioDevice", "playSine", 880, 40, 1, 0.0); ok("Tono di prova (880 Hz) inviato"); time.sleep(1.0)
    except Exception as e: ko("playSine", e)

if "motors" in SECTIONS:
    print("\n# MOTORI")
    try: ok("wakeUp (motori attivati) -> %s" % r.wake_up()); time.sleep(2)
    except Exception as e: ko("wakeUp", e)
    try: ok("Postura Stand -> %s" % r.posture("Stand", 0.5)); time.sleep(1)
    except Exception as e: ko("posture Stand", e)
    try:
        r.call("ALMotion", "setAngles", "HeadYaw", 0.5, 0.1); ok("Testa a sinistra"); time.sleep(1.2)
        r.call("ALMotion", "setAngles", "HeadYaw", -0.5, 0.1); ok("Testa a destra"); time.sleep(1.2)
        r.call("ALMotion", "setAngles", "HeadYaw", 0.0, 0.1); ok("Testa al centro"); time.sleep(0.8)
    except Exception as e: ko("movimento testa", e)
    try: ok("rest (motori di nuovo a riposo) -> %s" % r.rest())
    except Exception as e: ko("rest", e)

print("\n" + "=" * 56); print("COLLAUDO TERMINATO"); print("=" * 56)
r.close()
