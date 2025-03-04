import streamlit as st
import requests
from typing import Optional
import subprocess
import threading
import time
import os
import socket

class GoProController:
    def __init__(self, ip: str = "10.5.5.9"):
        self.ip = ip
        self.base_url = f"http://{ip}"
        self.stream_process = None
        self.stream_active = False
        self.preview_port = 8554

    def send_command(self, command: str) -> Optional[requests.Response]:
        try:
            response = requests.get(f"{self.base_url}/{command}")
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException:
            return None

    def status(self) -> Optional[dict]:
        response = self.send_command("gp/gpControl/status")
        if response:
            return response.json()
        return None

    def set_mode(self, mode: str) -> bool:
        mode_map = {"video": 0, "photo": 1, "burst": 2, "timelapse": 2}
        if mode.lower() not in mode_map:
            return False
        response = self.send_command(f"gp/gpControl/command/mode?p={mode_map[mode.lower()]}")
        return response is not None

    def start_recording(self) -> bool:
        response = self.send_command("gp/gpControl/command/shutter?p=1")
        return response is not None

    def stop_recording(self) -> bool:
        response = self.send_command("gp/gpControl/command/shutter?p=0")
        return response is not None

    def take_photo(self) -> bool:
        response = self.send_command("gp/gpControl/command/shutter?p=1")
        return response is not None

    def set_video_settings(self, resolution: str, fps: str, fov: str) -> bool:
        res_map = {"4K": 1, "1080p": 9, "720p": 12}
        fps_map = {"30fps": 5, "60fps": 6}
        fov_map = {
            "Wide": 0,
            "Medium": 1,
            "Narrow": 2,
            "Linear": 4
        }

        try:
            commands = [
                f"gp/gpControl/setting/2/{res_map[resolution]}",
                f"gp/gpControl/setting/3/{fps_map[fps]}",
                f"gp/gpControl/setting/4/{fov_map[fov]}"
            ]

            for cmd in commands:
                if not self.send_command(cmd):
                    return False
            return True
        except KeyError:
            return False

    def enable_preview_mode(self) -> bool:
        """Enable preview mode on the GoPro using proto_v2 restart for reduced latency"""
        try:
            # First, stop any existing stream
            self.send_command("gp/gpControl/execute?p1=gpStream&c1=stop")
            time.sleep(2)  # Wait for the previous stream to stop

            # Use the proto_v2 restart command for low latency streaming
            response = self.send_command("gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart")
            if not response:
                return False

            # (Optional) Additional settings can be applied here if needed
            time.sleep(3)  # Allow time for the stream to initialize
            return True
        except Exception as e:
            print(f"Error enabling preview mode: {e}")
            return False

    def check_preview_port(self) -> bool:
        """Check if the preview port is available"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.bind(('', self.preview_port))
            print("Successfully bound to preview port")
            sock.close()
            return True
        except Exception as e:
            print(f"Error checking preview port: {e}")
            return False

    def start_preview(self) -> bool:
        try:
            st.info("Initializing low latency preview stream...")

            st.write("Testing GoPro connection...")
            status = self.status()
            if status:
                st.write("GoPro is responding to commands")
            else:
                st.error("GoPro is not responding to commands")
                return False

            st.write("Enabling low latency preview mode...")
            if not self.enable_preview_mode():
                st.error("Failed to enable preview mode on GoPro")
                return False

            # Determine streaming IP based on camera model (Session cameras stream from 10.5.5.100)
            stream_ip = self.ip  # default
            if status and "info" in status and "model_name" in status["info"]:
                model = status["info"]["model_name"]
                if "Session" in model:
                    stream_ip = "10.5.5.100"
            st.write(f"Using stream IP: {stream_ip}")

            st.write("Checking preview port...")
            if not self.check_preview_port():
                st.error("No data received on preview port. Check GoPro connection.")
                return False

            output_path = "stream.m3u8"
            if os.path.exists(output_path):
                os.remove(output_path)

            # Set low latency options (adapted from provided logic)
            latency_options = ['-flags', 'low_delay', '-max_delay', '0', '-probesize', '32']
            udp_options = "?fifo_size=0"

            ffmpeg_cmd = [
                'ffmpeg',
                '-fflags', 'nobuffer'
            ] + latency_options + [
                '-f', 'mpegts',
                '-i', f'udp://{stream_ip}:{self.preview_port}{udp_options}',
                '-pix_fmt', 'yuv420p',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-tune', 'zerolatency',
                '-f', 'hls',
                '-hls_time', '1',
                '-hls_list_size', '3',
                '-hls_flags', 'delete_segments+omit_endlist',
                '-hls_segment_type', 'mpegts',
                output_path
            ]

            # Print FFmpeg command for debugging
            print("FFmpeg command:", " ".join(ffmpeg_cmd))

            self.stream_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            def monitor_ffmpeg():
                while self.stream_process:
                    error = self.stream_process.stderr.readline()
                    if error and 'error' in error.lower():
                        print(f"FFmpeg error: {error.strip()}")

            threading.Thread(target=monitor_ffmpeg, daemon=True).start()

            # Start a keep-alive thread to continuously send UDP messages to the camera
            def send_keep_alive():
                KEEP_ALIVE_PERIOD = 2.5  # seconds
                # The keep-alive message follows the format: _GPHD_:0:0:2:0\n
                message = "_GPHD_:0:0:2:0\n".encode('utf-8')
                udp_port = self.preview_port  # typically 8554
                control_ip = self.ip  # control commands are still sent to self.ip
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                while self.stream_active:
                    try:
                        sock.sendto(message, (control_ip, udp_port))
                    except Exception as e:
                        print("Keep-alive error:", e)
                    time.sleep(KEEP_ALIVE_PERIOD)

            self.stream_active = True
            threading.Thread(target=send_keep_alive, daemon=True).start()

            # Wait for the output HLS file to be created as a sign the stream is up
            timeout = 10
            start_time = time.time()
            while not os.path.exists(output_path):
                if time.time() - start_time > timeout:
                    st.error("Timeout waiting for stream to start")
                    self.stop_preview()
                    return False
                if self.stream_process.poll() is not None:
                    error_output = self.stream_process.stderr.read()
                    st.error(f"FFmpeg process failed: {error_output}")
                    self.stop_preview()
                    return False
                time.sleep(0.5)

            st.success("Low latency preview stream started successfully")
            return True

        except Exception as e:
            st.error(f"Error starting preview: {str(e)}")
            self.stop_preview()
            return False

    def stop_preview(self) -> bool:
        try:
            self.send_command("gp/gpControl/execute?p1=gpStream&c1=stop")

            if self.stream_process:
                self.stream_process.terminate()
                try:
                    self.stream_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.stream_process.kill()
                self.stream_process = None

            self.stream_active = False

            try:
                if os.path.exists("stream.m3u8"):
                    os.remove("stream.m3u8")
                for file in os.listdir():
                    if file.startswith("stream") and file.endswith(".ts"):
                        os.remove(file)
            except Exception as e:
                print(f"Error cleaning up stream files: {e}")

            return True

        except Exception as e:
            print(f"Error stopping preview: {e}")
            return False

def main():
    st.set_page_config(
        page_title="GoPro HERO5 Session Controller",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("GoPro HERO5 Session Controller")

    if "gopro" not in st.session_state:
        st.session_state.gopro = None

    with st.sidebar:
        st.header("Connection Settings")
        gopro_ip = st.text_input("GoPro IP Address", "10.5.5.9")

        if st.button("Connect to GoPro"):
            try:
                controller = GoProController(ip=gopro_ip)
                status = controller.status()
                if status:
                    st.session_state.gopro = controller
                    st.success("Connected to GoPro successfully!")
                else:
                    st.error("Could not connect to GoPro. Check IP and connection.")
            except Exception as e:
                st.error(f"Connection error: {str(e)}")

        st.header("Camera Mode")
        mode_options = ["Video", "Photo", "Burst", "TimeLapse"]
        selected_mode = st.radio("Select Mode", mode_options)

        if st.button("Set Mode"):
            if st.session_state.gopro:
                if st.session_state.gopro.set_mode(selected_mode):
                    st.success(f"Mode set to {selected_mode}")
                else:
                    st.error("Failed to set mode")
            else:
                st.error("Please connect to GoPro first")

        if selected_mode == "Video":
            st.header("Video Settings")
            resolution = st.selectbox("Resolution", ["720p", "1080p", "4K"])
            framerate = st.selectbox("Frame Rate", ["30fps", "60fps"])
            fov = st.selectbox("Field of View", ["Wide", "Medium", "Narrow", "Linear"])

            if st.button("Apply Video Settings"):
                if st.session_state.gopro:
                    if st.session_state.gopro.set_video_settings(resolution, framerate, fov):
                        st.success("Video settings applied successfully")
                    else:
                        st.error("Failed to apply video settings")
                else:
                    st.error("Please connect to GoPro first")

    st.header("Camera Controls")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Start Recording", use_container_width=True):
            if st.session_state.gopro:
                if st.session_state.gopro.start_recording():
                    st.success("Recording started")
                else:
                    st.error("Failed to start recording")
            else:
                st.error("Please connect to GoPro first")

    with col2:
        if st.button("Stop Recording", use_container_width=True):
            if st.session_state.gopro:
                if st.session_state.gopro.stop_recording():
                    st.success("Recording stopped")
                else:
                    st.error("Failed to stop recording")
            else:
                st.error("Please connect to GoPro first")

    with col3:
        if st.button("Take Photo", use_container_width=True):
            if st.session_state.gopro:
                if st.session_state.gopro.take_photo():
                    st.success("Photo taken")
                else:
                    st.error("Failed to take photo")
            else:
                st.error("Please connect to GoPro first")

    st.header("Live Preview")
    preview_enabled = st.checkbox("Enable Preview Stream", value=False)

    if st.session_state.gopro:
        if preview_enabled:
            if not st.session_state.gopro.stream_active:
                if st.session_state.gopro.start_preview():
                    st.video("stream.m3u8")
                else:
                    st.error("Failed to start preview stream")
        else:
            if st.session_state.gopro.stream_active:
                st.session_state.gopro.stop_preview()
    else:
        st.error("Please connect to GoPro first")

    st.markdown("""
    ### Usage Notes
    1. Ensure your computer is connected to the GoPro's WiFi network
    2. The default IP address is usually 10.5.5.9
    3. Connect to GoPro before using any controls
    4. FFmpeg must be installed for preview streaming
    5. For best streaming performance, keep the GoPro and computer in close proximity
    6. If the preview stream is laggy, try disabling and re-enabling it
    """)

if __name__ == "__main__":
    main()
