"""
Genera un report tecnico in PDF sul robot Pepper e sul progetto PepperRemote.
Uso:  python report_gen.py [IP]   ->  crea Report_Pepper.pdf
"""
import sys
import datetime
import naoqi_lite as nq

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.enums import TA_LEFT

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.10.6"
OUT = r"C:\Users\Pepper\PepperRemote\Report_Pepper.pdf"

NAVY = colors.HexColor("#0c2340")
ACC = colors.HexColor("#2f7bff")
GREY = colors.HexColor("#5a6a85")
LIGHT = colors.HexColor("#eef3fb")
OKC = colors.HexColor("#1f9d57")
WARNC = colors.HexColor("#c77700")
ERRC = colors.HexColor("#c0392b")


def gather():
    d = dict(name="Pepper", ver="n/d", batt="n/d", life="n/d",
             nsvc="n/d", online=False)
    try:
        r = nq.Robot(HOST, timeout=8)
        d["name"] = r.robot_name()
        d["ver"] = r.naoqi_version()
        d["batt"] = "%d%%" % r.battery()
        d["life"] = r.life_state()
        try:
            sd = nq._get_methods(r.sess, 1)
            uid, ret, _ = sd["services"][0]
            body = r.sess.call_raw(1, 1, uid)
            svcs, _ = nq.decode(nq.parse_sig(ret)[0], body, 0)
            d["nsvc"] = str(len(svcs))
        except Exception:
            pass
        d["online"] = True
        r.close()
    except Exception as e:
        d["err"] = str(e)
    return d


def build():
    data = gather()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=10.5, leading=15, textColor=colors.HexColor("#1b2430"))
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=15, textColor=NAVY, spaceBefore=14, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=9, textColor=GREY)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=2)

    doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            title="Report tecnico - Robot Pepper", author="PepperRemote")
    el = []

    # ---- intestazione ----
    el.append(Paragraph("Report Tecnico", ParagraphStyle(
        "title", parent=h1, fontSize=26, leading=30, textColor=NAVY, spaceAfter=6)))
    el.append(Paragraph("Robot SoftBank Pepper &mdash; accesso, diagnostica e software di controllo",
                        ParagraphStyle("sub", parent=body, fontSize=12, textColor=ACC)))
    el.append(Spacer(1, 4))
    el.append(HRFlowable(width="100%", thickness=2, color=ACC))
    el.append(Spacer(1, 4))
    stato = "ONLINE" if data["online"] else "non raggiunto"
    el.append(Paragraph("Generato il %s &nbsp;&bull;&nbsp; robot: %s (%s) &nbsp;&bull;&nbsp; host %s"
                        % (datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), data["name"], stato, HOST), small))
    el.append(Spacer(1, 10))

    # ---- 1. riepilogo ----
    el.append(Paragraph("1. Riepilogo esecutivo", h1))
    el.append(Paragraph(
        "Il robot Pepper &egrave; stato ereditato senza credenziali n&eacute; documentazione. "
        "Le password di sistema (SSH e pagina web) risultano perse e il reset di fabbrica "
        "richiederebbe un account del produttore anch'esso non disponibile. "
        "La diagnostica ha per&ograve; rilevato che l'<b>interfaccia di programmazione NAOqi "
        "(porta 9559) &egrave; aperta e non richiede password</b>: ci&ograve; consente di "
        "controllare integralmente il robot via rete. Su questa base &egrave; stato sviluppato "
        "<b>PepperRemote</b>, un'applicazione Python con interfaccia grafica che reimplementa "
        "il protocollo di comunicazione del robot senza l'SDK ufficiale (ormai dismesso).", body))

    # ---- 2. identificazione ----
    el.append(Paragraph("2. Identificazione del robot", h1))
    rows = [
        ["Modello", "SoftBank / Aldebaran Pepper"],
        ["Versione software (NAOqi)", data["ver"]],
        ["Indirizzo IP", HOST],
        ["Indirizzo MAC", "48:A9:D2:63:62:6C"],
        ["Livello batteria", data["batt"]],
        ["Autonomous Life", data["life"]],
        ["Servizi NAOqi attivi", data["nsvc"]],
        ["Porte di rete aperte", "9559 (API NAOqi), 22 (SSH), 80 (web)"],
    ]
    t = Table(rows, colWidths=[55 * mm, 105 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6ea")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    el.append(t)

    # ---- 3. rete ----
    el.append(Paragraph("3. Rete e connettivit&agrave;", h1))
    el.append(Paragraph(
        "Il robot e il computer sono collegati all'hotspot &laquo;iPhone di Thomas&raquo; "
        "(sottorete 172.20.10.0/28). Il computer controlla il robot direttamente sulla porta 9559. "
        "Il <b>tablet</b> del Pepper &egrave; invece dietro la rete interna del robot (198.18.0.1): "
        "dispone di accesso a internet tramite il robot, ma non raggiunge gli altri dispositivi "
        "della rete locale (il computer). Il collegamento Wi-Fi dell'hotspot entra in standby, "
        "per cui i primi tentativi di connessione possono fallire e riuscire subito dopo.", body))

    # ---- 4. accesso e sicurezza ----
    el.append(Paragraph("4. Accesso e sicurezza", h1))
    for txt in [
        "<b>Password di sistema perse:</b> l'utente &egrave; amministratore ma non dispone delle "
        "credenziali; la password di fabbrica &laquo;nao&raquo; &egrave; rifiutata.",
        "<b>Reset di fabbrica:</b> sul NAOqi 2.5 richiede l'account Aldebaran collegato al robot "
        "(non disponibile) oppure il reflash con immagine ufficiale, ottenibile solo dal supporto "
        "United Robotics Group / Aldebaran. Rischio: cancellazione dell'app di deployment "
        "&laquo;jp.softbank.customb_...&raquo; e della configurazione di avvio.",
        "<b>API NAOqi aperta:</b> la sessione qimessaging non richiede autenticazione "
        "(stato handshake &laquo;DONE&raquo;). Questo permette controllo e lettura completi del "
        "robot senza password &mdash; la base del software realizzato.",
    ]:
        el.append(Paragraph("&bull;&nbsp; " + txt, bullet))

    # ---- 5. software ----
    el.append(Paragraph("5. Software realizzato &mdash; PepperRemote", h1))
    el.append(Paragraph(
        "Applicazione Python (sola libreria standard per il nucleo) in "
        "<font face='Courier'>C:\\Users\\Pepper\\PepperRemote</font>. Componenti:", body))
    comp = [
        ["naoqi_lite.py", "Motore: protocollo qimessaging reimplementato, autenticazione, chiamata dei servizi per nome."],
        ["app.py", "Interfaccia grafica (schermata di presentazione + schede) e web server del secondo schermo."],
        ["audio_bridge.py", "Invio dell'audio di sistema del PC alle casse del robot (sperimentale)."],
        ["remote_cli.py", "Telecomando da riga di comando."],
        ["web/second_screen.html", "Pagina mostrata sul tablet (orologio, messaggi, immagini, siti)."],
    ]
    t2 = Table(comp, colWidths=[48 * mm, 112 * mm])
    t2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Courier-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (0, -1), 8),
        ("FONTSIZE", (1, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), ACC),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6ea")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
    ]))
    el.append(t2)

    # ---- 6. stato funzionalita' ----
    el.append(Paragraph("6. Stato delle funzionalit&agrave;", h1))
    feat = [
        ["Funzione", "Stato"],
        ["Connessione e lettura stato (batteria, versione)", "Funzionante"],
        ["Voce (sintesi vocale, lingue, volume)", "Funzionante"],
        ["Movimento, postura, spostamento", "Funzionante"],
        ["LED degli occhi (colore)", "Funzionante"],
        ["Pausa/ripresa Autonomous Life", "Funzionante"],
        ["Riproduzione audio/stream dalle casse del robot", "Funzionante"],
        ["Tablet come secondo schermo", "Da completare (vedi par. 7)"],
        ["Audio di sistema del PC sulle casse del robot", "Sperimentale"],
    ]
    t3 = Table(feat, colWidths=[110 * mm, 50 * mm])
    style3 = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6ea")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    for i, row in enumerate(feat[1:], start=1):
        c = OKC if row[1] == "Funzionante" else (WARNC if "Sperimentale" in row[1] else ERRC)
        style3.append(("TEXTCOLOR", (1, i), (1, i), c))
        style3.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
    t3.setStyle(TableStyle(style3))
    el.append(t3)

    # ---- 7. problemi e soluzioni ----
    el.append(Paragraph("7. Problemi noti e soluzioni", h1))
    for txt in [
        "<b>Secondo schermo:</b> il tablet non raggiunge il web server locale del PC (rete interna "
        "del robot). Soluzione prevista: esporre la pagina su internet con un tunnel "
        "(es. cloudflared, senza account) e puntare l&igrave; la webview.",
        "<b>Audio solo sul robot (tipo cassa Bluetooth):</b> installare un dispositivo audio "
        "virtuale (VB-CABLE), impostarlo come uscita di Windows e selezionarlo come sorgente "
        "nell'app, cos&igrave; l'audio non esce dalle casse del PC.",
        "<b>Recupero credenziali:</b> per un reset sicuro, prima salvare via API i contenuti "
        "importanti; poi contattare United Robotics Group / Aldebaran con Head ID e Body ID.",
    ]:
        el.append(Paragraph("&bull;&nbsp; " + txt, bullet))

    # ---- 8. raccomandazioni ----
    el.append(Paragraph("8. Raccomandazioni", h1))
    el.append(Paragraph(
        "Mantenere il robot sulla rete attuale e usare PepperRemote per l'uso quotidiano senza "
        "necessit&agrave; delle password perse. Prima di valutare qualsiasi reset, effettuare un "
        "backup dei contenuti del robot. Completare la funzione secondo schermo tramite tunnel "
        "internet e, se desiderato, configurare l'audio virtuale per l'uso del robot come cassa.", body))

    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=0.6, color=GREY))
    el.append(Paragraph("Documento generato automaticamente da PepperRemote &bull; report_gen.py", small))

    doc.build(el)
    print("PDF creato:", OUT, "(robot %s)" % ("online" if data["online"] else "offline"))


if __name__ == "__main__":
    build()
