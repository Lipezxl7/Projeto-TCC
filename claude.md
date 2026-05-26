## Project Overview

**Person Counter** is a Python application that counts unique individuals across video frames using YOLOv8 object detection, ByteTrack multi-object tracking, and HSV histogram-based appearance re-identification. The system handles occlusions, re-entries, and track fragmentation by matching visual features across detections to assign consistent person IDs.

**Language:** Portuguese (comments & output)  
**Primary Use Case:** Counting unique people in surveillance/analysis videos across multiple hardware platforms

---

## Architecture & Structure

```
person_counter.py (single file)
├── Device Selection Layer
│   ├── detect_device()          → User preference or auto-detection
│   └── auto_device_selection()  → Priority: CUDA → MPS → Intel GPU → CPU
├── Model Loading Layer
│   └── load_model()             → YOLO + OpenVINO export/compilation
├── Appearance Features Layer
│   ├── extract_appearance()     → HSV histogram from bounding box crops
│   └── cosine_dist()            → Similarity metric for matching
├── Visualization Layer
│   ├── draw_box()               → Annotate detections with IDs
│   ├── draw_overlay()           → Display unique person count
│   └── resize_for_display()     → Scale frames for window display
├── Core Tracking Logic
│   └── count_unique_people()    → Main processing loop
└── CLI Entry Point
    └── main()                   → Argument parsing & execution
```

---

## Key Concepts & Implementation Details

### Device Abstraction
- **Priority chain:** CUDA (NVIDIA) → MPS (Apple Silicon) → OpenVINO (Intel GPU/CPU) → CPU
- **Critical handling for OpenVINO:** Model compiled *before* ultralytics processes device string to avoid CUDA validation errors
- **Passed device parameter:** Set to `None` for OpenVINO (already compiled), otherwise passed to `model.track()`

### Appearance-Based Re-ID
- **Feature extraction:** HSV color histograms split into two regions (top/bottom of 48×96 crop)
  - Hue bins: 18 | Saturation bins: 8
  - Concatenated into 288-dimensional vector
- **Matching:** Cosine distance with configurable tolerance (default 0.01)
- **Updates:** Running weighted average (70% old, 30% new) when same track observed

### Tracking Strategy
- **Detector:** YOLOv8 (person class only, conf=0.40)
- **Tracker:** ByteTrack with permanent buffer (never expires during video)
  - High threshold: 0.50 | Low threshold: 0.10 | New track threshold: 0.60
- **Association:** Track → Unique Person (on first appearance with valid features)

### Person Identity Assignment
- Each unique person gets canonical feature vector (updated as `0.6 * old + 0.4 * new`)
- Re-entrances detected via appearance matching (if cosine distance ≤ tolerance)
- If no match found → new unique person created

---

## Technologies & Dependencies

| Component | Purpose | Notes |
|-----------|---------|-------|
| **OpenCV** (`cv2`) | Video I/O, frame processing, drawing | Read video, resize, HSV conversion |
| **NumPy** | Array operations | Histogram calculation, distance metrics |
| **PyTorch** (`torch`) | GPU/device detection | CUDA & MPS availability checks |
| **OpenVINO** (`openvino`) | Intel hardware acceleration | GPU/CPU compilation & inference |
| **Ultralytics** (`YOLO`) | Detection & tracking | YOLOv8 + ByteTrack |
| **Argparse** | CLI interface | Argument parsing |
| **Tempfile** | Temporary files | ByteTrack config storage |
| **Pathlib** | Path operations | XML file discovery |

---

## Configuration & Parameters

### CLI Arguments
```
positional:
  video                     Video file path

optional:
  --tolerance (float)       Appearance similarity threshold (0–0.35), default=0.01
  --sample-rate (int)       Feature update frequency (1=every frame), default=1
  --img-size (int)          YOLO input resolution {320,480,640,768}, default=640
  --model (str)             YOLO model file, default=yolo26n.pt
  --device (str)            Hardware: 'cuda'|'mps'|'intel:gpu'|'intel:cpu'|'cpu', default=auto-detect
  --no-window (flag)        Run headless (no display), default=False
```

### ByteTrack Configuration
```yaml
tracker_type: bytetrack
track_high_thresh: 0.50      # High confidence
track_low_thresh: 0.10       # Low confidence
new_track_thresh: 0.60       # New track init
track_buffer: {total_frames} # Never expire during video
match_thresh: 0.80           # Association threshold
fuse_score: true             # Combine detection + track scores
```

---

## Key Functions

### `detect_device(preferred: str | None) → tuple[str, str]`
Resolves hardware device and returns (device_string, description).  
Falls back to auto-selection if preference unavailable.

### `load_model(device: str, model_name: str) → tuple[YOLO, str | None]`
Loads YOLO model and optionally exports to OpenVINO.  
Returns model and resolved device (None for OpenVINO to avoid CUDA errors).

### `extract_appearance(crop: np.ndarray) → np.ndarray | None`
Extracts 288-dim HSV histogram feature from bounding box crop (48×96).  
Returns None if crop too small (<10px in either dimension).

### `cosine_dist(a: np.ndarray, b: np.ndarray) → float`
Computes cosine distance (1 − normalized dot product).  
Returns 1.0 if either vector has zero norm.

### `count_unique_people(...) → int`
Main processing loop:
1. Detects persons with YOLO
2. Tracks with ByteTrack
3. Updates/matches appearance features
4. Draws visualization (if enabled)
5. Returns final unique person count

---

## Usage Examples

### Basic Usage
```bash
python person_counter.py input_video.mp4
```

### Auto-Detect Hardware with Custom Model
```bash
python person_counter.py video.mp4 --model yolo26l.pt
```

### Strict Intel GPU with Relaxed Tolerance
```bash
python person_counter.py video.mp4 --device intel:gpu --tolerance 0.05
```

### Headless Mode (No Window)
```bash
python person_counter.py video.mp4 --no-window --sample-rate 2
```

### High-Speed, Low-Precision
```bash
python person_counter.py video.mp4 --img-size 320 --sample-rate 3
```

---

## Display Output

### Window Elements
- **Bounding boxes:** Color-coded by person ID (confirmed) or gray (pending)
- **Labels:** "Pessoa N" (confirmed) or "identificando..." (awaiting features)
- **Overlay panel:** White text "Pessoas únicas: N" on dark background (60% opacity)

### Console Output
- Processing progress: `[5.2%] | pessoas únicas: 12`
- Hardware info: Device name, OpenVINO execution device, full hardware name
- Final result: Total unique people found

---

## Important Notes

### OpenVINO Handling
- Model *must* be compiled before `model.track()` to prevent CUDA validation errors
- Device parameter passed as `None` to tracker when using OpenVINO (already bound at compile time)
- Automatic XML file discovery in exported model directory

### Tolerance Tuning
- **Too low (0.01):** Over-counts due to false re-match failures
- **Too high (0.35):** Under-counts due to false re-matches across different people
- **Recommended range:** 0.01–0.10 for typical scenarios

### Performance Trade-offs
- **Smaller `img_size` (320):** Faster, less accurate
- **Larger `sample_rate`:** Faster, stale appearance features
- **Larger model (yolo26x):** More accurate, slower

---

## Dependencies Installation

```bash
pip install opencv-python numpy torch openvino ultralytics
```

For GPU support:
- **NVIDIA:** Install CUDA toolkit + `pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118`
- **Apple Silicon:** `pip install torch` (MPS auto-enabled)
- **Intel:** Install OpenVINO runtime separately if not bundled
