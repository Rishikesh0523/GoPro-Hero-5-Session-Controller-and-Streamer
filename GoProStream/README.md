# GoProStream

**GoProStream** is a Python-based tool for handling and displaying GoPro camera streams over HTTP/UDP. It provides various streaming and recording options—including low-latency local streaming for OBS—making it simpler to manage and broadcast GoPro footage in real time.

---

## Dependencies

- **FFmpeg**: Must be installed and accessible via the command line.  
- **urllib**: Included by default in most Python installations (Python 3).  

---

## Configuration Flags

- **VERBOSE = False**  
  Toggles verbose output for FFmpeg.

- **RECORD = False**  
  Sends a record command to the camera; the camera must be in video mode.

- **STREAM = False**  
  Creates a local low-latency stream (e.g., for OBS) via FFmpeg; the camera must be in video mode.

- **SAVE = False**  
  Enables saving the GoPro live feed to your local machine.

- **SAVE_FILENAME = "goprofeed2"**  
  Specifies the default filename for saved recordings.

- **SAVE_FORMAT = "mp4"**  
  Defines the output file format for recorded videos.

- **SAVE_LOCATION = "/home/konrad/Videos/"**  
  Sets the directory in which to save the recorded files (modify this path as needed).
