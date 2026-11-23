# PepperRemote

Pannello di controllo (GUI) + telecomando da terminale per un robot **SoftBank/Aldebaran
Pepper (NAOqi 2.x)**, tramite l'API `qimessaging` sulla porta **9559**.

Tutto il protocollo di comunicazione è **reimplementato da zero in Python puro**
(`naoqi_lite.py`, sola libreria standard): **non serve l'SDK ufficiale** di
Aldebaran/SoftBank (ormai dismesso). Funziona perché su questo robot l'API NAOqi è
**aperta**, cioè la sessione qi non richiede password.

> Progetto nato per controllare un Pepper ereditato di cui si erano perse le credenziali
> SSH/web, ma la cui API di rete era rimasta accessibile.

---

## Requisiti

- **Python 3.9+** (consigliato 3.12). Tkinter è incluso nell'installer di python.org.
- PC e robot sulla **stessa rete** (es. un hotspot Wi-Fi).
- IP del robot (default `172.20.10.6`, modificabile nella GUI).

Il **nucleo** (connessione, voce, movimento, LED, telecomando) gira con la **sola libreria
standard**. Le funzioni avanzate hanno dipendenze opzionali:

```
pip install -r requirements.txt
```

(oppure installa solo ciò che ti serve: vedi `requirements.txt`.)

---

## Avvio

GUI:
```
python app.py
```
Scrivi l'IP del robot e premi **Connetti**. Su Windows puoi anche creare un'icona sul
Desktop con `make_icon.py` (lanciata da pythonw, senza finestra del terminale).

L'interfaccia ha un **menu laterale** con le sezioni:

| Sezione | Funzioni |
|---------|----------|
| **Stato** | nome, versione, batteria; sveglia/riposo; pausa/ripresa Autonomous Life |
| **Voce** | far parlare il robot, lingua, volumi |
| **Movimento** | postura, spostamento, LED occhi |
| **Pilota** | guida in tempo reale WASD/QE + testa con le frecce; telecamera con HUD stile drone |
| **Danza** | coreografie a ritmo di musica (BPM automatico) |
| **Secondo schermo** | usa il tablet del robot come schermo di contenuti |
| **Audio** | musica/stream/YouTube sul robot; audio di sistema del PC → casse del robot |
| **Visione** | riconoscimento oggetti dalla telecamera (MediaPipe/EfficientDet-Lite) |

Pulsante **STOP** (o tasto **Esc**) = stop di emergenza.

---

## Telecomando da terminale

Stesso motore, senza GUI:
```
python remote_cli.py say "Ciao a tutti"
python remote_cli.py state
python remote_cli.py life disabled
python remote_cli.py posture Stand
python remote_cli.py led 2F7BFF
python remote_cli.py walk 0.6 0 0 --sec 2
python remote_cli.py tablet https://www.google.com
python remote_cli.py play http://stream.srg-ssr.ch/m/rsc_it/mp3_128
python remote_cli.py call ALTextToSpeech say "ciao" ""   # chiamata generica
```

---

## Secondo schermo (tablet)

La pagina viene inviata **direttamente al tablet** come `data:` URL (nessun server né
tunnel): orologio, messaggio, immagine (URL) o sito (URL). L'opzione "Tieni fisso" mette
in pausa l'Autonomous Life così il robot non si riprende lo schermo.

> È un "secondo schermo di contenuti" (il tablet è un browser), non un monitor esteso del
> sistema operativo. Nota: il tablet è dietro la rete interna del robot, quindi raggiunge
> internet ma non i dispositivi della LAN locale.

---

## Audio: robot come cassa Bluetooth

La "diretta audio" cattura l'uscita di Windows (WASAPI loopback) e la trasmette alle casse
del robot. Di base esce **sia** dal PC **sia** dal robot. Per farla uscire **solo dal
robot**, come una cassa wireless, serve un dispositivo audio virtuale:

1. Installa **VB-CABLE** (gratuito, https://vb-audio.com/Cable/) ed esegui l'installer come
   amministratore, poi riavvia.
2. Imposta **CABLE Input** come uscita di Windows (o solo per una singola app).
3. Nella scheda **Audio** → **Rileva dispositivi** → seleziona **CABLE Output** → **Avvia diretta**.

La scheda Audio permette anche di riprodurre uno **stream**, un **file** o un **link YouTube**
(scaricato con yt-dlp) dalle casse del robot, con opzione di ripetizione.

---

## File del progetto

| File | Ruolo |
|------|-------|
| `naoqi_lite.py` | **Motore**: protocollo qimessaging, autenticazione, chiamata servizi per nome |
| `app.py` | Interfaccia grafica principale (menu laterale) |
| `theme.py` | Tema scuro stile Windows 11 (sv-ttk) e widget personalizzati |
| `remote_cli.py` | Telecomando da riga di comando |
| `pilot.py` | Guida in tempo reale + telecamera con HUD |
| `dance.py` | Coreografie sincronizzate alla musica |
| `bpm.py` | Rilevamento automatico del BPM (spectral flux + autocorrelazione) |
| `vision.py` | Telecamera + riconoscimento oggetti |
| `yt_audio.py` | Download/riproduzione audio da YouTube |
| `audio_bridge.py` | Audio di sistema del PC → casse del robot (WASAPI) |
| `report_gen.py` | Genera un report PDF tecnico sul robot |
| `test_full.py` | Collaudo funzionale (stato, luci, casse, motori) |
| `make_icon.py` | Genera l'icona `pepper.ico` per il collegamento sul Desktop |
| `web/second_screen.html` | Pagina mostrata sul tablet |
| `models/efficientdet_lite0.tflite` | Modello per il riconoscimento oggetti |

---

## Note tecniche (protocollo)

- Header qi: magic `0x42dead42` in **big-endian**, resto little-endian.
- Autenticazione: `Server.authenticate` (service 0, object 1, action 8) con capability map;
  risposta `__qi_auth_state == 3` = sessione aperta senza password.
- I metodi si chiamano per **uid** numerico, ricavato dal `metaObject` di ogni servizio;
  l'overload giusto è scelto in base ai tipi degli argomenti.

## Avvertenze

- "Pausa Autonomous Life" ferma i comportamenti autonomi; si ripristina con **solitary**.
- L'audio di sistema in diretta ha una certa latenza ed è sperimentale.
- Compatibile con **NAOqi 2.5**; altre versioni 2.x non sono state testate.

---

*Progetto personale, non affiliato a SoftBank Robotics / Aldebaran / United Robotics Group.*
