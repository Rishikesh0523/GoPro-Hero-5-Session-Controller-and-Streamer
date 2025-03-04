
import sys
import socket
try:
    # For Python 3.x
    from urllib.request import urlopen
except ImportError:
    # For Python 2.x
    from urllib2 import urlopen
import subprocess
from time import sleep
import signal
import json
import re
import http

def get_command_msg(id):
    return "_GPHD_:%u:%u:%d:%1lf\n" % (0, 0, 2, 0)

## Parameters:
VERBOSE = False
## Sends Record command to GoPro Camera, must be in Video mode!
RECORD = False
## Converts GoPro camera live stream via FFMPEG to a local source, must be in Video mode!
STREAM = False
##
## Saves the feed to a custom location
SAVE = False
SAVE_FILENAME = "goprofeed3"
SAVE_FORMAT = "ts"
SAVE_LOCATION = "/tmp/"
## for wake_on_lan
GOPRO_IP = '10.5.5.9'
GOPRO_MAC = 'DEADBEEF0000'

def gopro_live():
    # Use a separate variable for the control IP (always 10.5.5.9)
    CONTROL_IP = "10.5.5.9"
    UDP_PORT = 8554
    KEEP_ALIVE_PERIOD = 2500
    KEEP_ALIVE_CMD = 2

    MESSAGE = get_command_msg(KEEP_ALIVE_CMD)
    URL = "http://10.5.5.9:8080/live/amba.m3u8"

    try:
        # Fetch camera control info
        response_raw = urlopen('http://10.5.5.9/gp/gpControl').read().decode('utf-8')
        jsondata = json.loads(response_raw)
        firmware = jsondata["info"]["firmware_version"]
        model = jsondata["info"]["model_name"]
    except http.client.BadStatusLine:
        firmware = urlopen('http://10.5.5.9/camera/cv').read().decode('utf-8')
        model = ""
    
    # Determine streaming IP based on camera model.
    # For many session cameras (including HERO4 Session and HERO5 Session) the stream is on 10.5.5.100;
    # for non-session models (e.g. HERO5 Black) the stream may be on 10.5.5.9.
    if "Session" in model:
        stream_ip = "10.5.5.100"
    else:
        stream_ip = "10.5.5.9"

    # Check if camera is one of the models that use the streaming command
    if ("HD4" in firmware or "HD3.2" in firmware or "HD5" in firmware or 
        "HD6" in firmware or "HD7" in firmware or "H18" in firmware) or ("HERO5" in model):
        
        print("Camera model:", model)
        print("Firmware version:", firmware)
        
        # Start streaming mode
        urlopen("http://10.5.5.9/gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart").read()
        if RECORD:
            urlopen("http://10.5.5.9/gp/gpControl/command/shutter?p=1").read()
        print("Control IP:", CONTROL_IP)
        print("Streaming IP:", stream_ip)
        print("UDP target port:", UDP_PORT)
        print("message:", MESSAGE)
        print("Recording on camera: " + str(RECORD))

        # HERO4 Session (and similar) need a status check before the live feed starts.
        if "HX" in firmware:
            connectedStatus = False
            while not connectedStatus:
                req = urlopen("http://10.5.5.9/gp/gpControl/status")
                data = req.read()
                encoding = req.info().get_content_charset('utf-8')
                json_status = json.loads(data.decode(encoding))
                if json_status["status"]["31"] >= 1:
                    connectedStatus = True

        # Reduced latency settings:
        #   - Use low_delay flag and disable additional delay with -max_delay 0
        #   - Reduce probe size to 32 (from 8192)
        #   - Append UDP URL options to reduce buffering: ?fifo_size=0&overrun_nonfatal=1
        latency_options = "-flags low_delay -max_delay 0 -probesize 32"
        udp_options = "?fifo_size=0"
        loglevel_verbose = ""
        if not VERBOSE:
            loglevel_verbose = "-loglevel panic"
        if not SAVE:
            if STREAM:
                # Using ffmpeg to restream locally (e.g. to udp://localhost:10000)
                subprocess.Popen("ffmpeg " + loglevel_verbose +
                                 " -fflags nobuffer " + latency_options +
                                 " -f:v mpegts -i udp://"+ stream_ip +":8554" + udp_options +
                                 " -f mpegts -vcodec copy udp://localhost:10000", shell=True)
            else:
                # Direct preview via ffplay with low-latency options
                subprocess.Popen("ffplay " + loglevel_verbose +
                                 " -fflags nobuffer " + latency_options +
                                 " -f:v mpegts -i udp://"+ stream_ip +":8554" + udp_options, shell=True)
        else:
            if SAVE_FORMAT == "ts":
                TS_PARAMS = " -acodec copy -vcodec copy "
            else:
                TS_PARAMS = ""
            save_location_full = SAVE_LOCATION + SAVE_FILENAME + "." + SAVE_FORMAT
            print("Recording locally: " + str(SAVE))
            print("Recording stored in: " + save_location_full)
            print("Note: Preview is not available when saving the stream.")
            subprocess.Popen('ffmpeg -i "udp://'+ stream_ip +':8554' + udp_options + '" -fflags nobuffer ' +
                             latency_options + " -f:v mpegts " +
                             TS_PARAMS + save_location_full, shell=True)
        if sys.version_info.major >= 3:
            MESSAGE = bytes(MESSAGE, "utf-8")
        print("Press ctrl+C to quit this application.\n")
        while True:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(MESSAGE, (CONTROL_IP, UDP_PORT))
            sleep(KEEP_ALIVE_PERIOD/1000)
    else:
        print("branch hero3:", firmware)
        if "Hero3" in firmware or "HERO3+" in firmware:
            print("branch hero3")
            PASSWORD = urlopen("http://10.5.5.9/bacpac/sd").read()
            print("HERO3/3+/2 camera")
            Password = str(PASSWORD, 'utf-8')
            text = re.sub(r'\W+', '', Password)
            urlopen("http://10.5.5.9/camera/PV?t=" + text + "&p=%02")
            subprocess.Popen("ffplay " + URL, shell=True)

def quit_gopro(signal, frame):
    if RECORD:
        urlopen("http://10.5.5.9/gp/gpControl/command/shutter?p=0").read()
    sys.exit(0)

def wake_on_lan(macaddress):
    """Switches on the camera using WOL."""
    # Check macaddress format and remove any separators
    if len(macaddress) == 12:
        pass
    elif len(macaddress) == 17:
        sep = macaddress[2]
        macaddress = macaddress.replace(sep, '')
    else:
        raise ValueError('Incorrect MAC Address Format')
    # Pad the sync stream
    data = ''.join(['FFFFFFFFFFFF', macaddress * 20])
    send_data = bytes.fromhex(data)
    # Broadcast to LAN (using the control IP and port 9 for WOL)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(send_data, (GOPRO_IP, 9))

if __name__ == '__main__':
    wake_on_lan(GOPRO_MAC)
    signal.signal(signal.SIGINT, quit_gopro)
    gopro_live()
