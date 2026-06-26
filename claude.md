## Project Overview

**Person Counter (Contador de Pessoas)** is a Python CLI application that counts **unique individuals** across video frames using YOLO26 object detection, ByteTrack multi-object tracking, and HSV histogram-based appearance re-identification. The system handles occlusions, re-entries, and track fragmentation by matching visual features across detections to assign consistent person IDs.

**Language:** Portuguese (comments, labels & console output)
**Primary Use Case:** Counting unique people in surveillance/analysis videos across multiple hardware platforms
**Repository:** https://codeberg.org/yLipe/Projeto-TCC.git
**Python:** 3.14+
**Testing:** No automated tests — manual verification only
**Architecture:** Single-file Python application (`contador.py`, 375 lines)

---

## Architecture & Structure

```
contador.py (single file – all logic)
├── Device Selection Layer
│   ├── detect_device()          → User preference with match/case or auto-detection
│   └── auto_device_selection()  → Priority: CUDA → MPS → Intel GPU → Intel CPU → CPU
├── Model Loading Layer
│   └── load_model()             → YOLO + optional OpenVINO export/compilation
├── Appearance Features Layer
│   ├── extract_appearance()     → HSV histogram from bounding box crops (48×96, 2 regions)
│   └── cosine_dist()            → Similarity metric (1 − normalized dot product)
├── Visualization Layer
│   ├── draw_box()               → Annotate detections with IDs (color-coded or gray)
│   ├── draw_overlay()           → Display unique person count overlay
│   └── (WINDOW_NORMAL)          → Resizable OpenCV display window
├── Core Tracking Logic
│   └── count_unique_people()    → Main processing loop (video or webcam)
└── CLI Entry Point
    └── main()                   → Argument parsing & execution
```

---

## Key Concepts & Implementation Details

### Device Abstraction
- **Priority chain:** CUDA (NVIDIA) → MPS (Apple Silicon) → OpenVINO (Intel GPU) → OpenVINO (Intel CPU) → CPU
- **Critical handling for OpenVINO:** Model compiled *before* ultralytics processes device string to avoid CUDA validation errors
- **Passed device parameter:** Set to `None` for OpenVINO (already compiled at model level), otherwise passed to `model.track()`
- **Fallback:** If user-specified device is unavailable, silently falls back to `auto_device_selection()`

### Appearance-Based Re-ID
- **Feature extraction:** HSV color histograms split into two body regions (top/bottom of 48×96 crop)
  - Hue bins: 18 | Saturation bins: 8
  - Concatenated into **288-dimensional** vector (18×8×2 = 288)
- **Matching:** Cosine distance with configurable tolerance (default **0.005**)
- **Track-level feature update:** Running weighted average (**70% old, 30% new**)
- **Person-level canonical update:** Running weighted average (**60% old, 40% new**)
- **Minimum crop size:** 10px in either dimension (otherwise returns None)

### Tracking Strategy
- **Detector:** YOLO26 (person class only, conf=0.40, iou=0.60)
- **Tracker:** ByteTrack with persistent buffer
  - High threshold: 0.50 | Low threshold: 0.10 | New track threshold: 0.60
  - **Video mode:** track_buffer = total frame count (never expires during video)
  - **Webcam mode:** track_buffer = 900 frames
- **Association:** Track → Unique Person (on first appearance with valid features)

### Person Identity Assignment
- Each unique person gets a canonical feature vector (updated as `0.6 * old + 0.4 * new`)
- Re-entrances detected via appearance matching (if cosine distance ≤ tolerance)
- If no match found → new unique person created
- Track-to-person mapping persists for entire run

### Color Palette
- 8 predefined BGR colors assigned cyclically by person ID (`COLORS` list)
- Unconfirmed tracks (no person ID yet) drawn in gray (160, 160, 160)

---

## Technologies & Dependencies

### Direct Dependencies (requirements.txt)

| Package | Purpose | Notes |
|---------|---------|-------|
| **opencv-python** | Video I/O, frame processing, HSV, drawing | `cv2.VideoCapture`, `cv2.calcHist`, `cv2.imshow` |
| **numpy** | Array operations, histogram math | Distance metrics, feature concatenation |
| **ultralytics** | YOLO26 detection + ByteTrack tracking | `YOLO`, `model.track()` with persist=True |
| **openvino** | Intel hardware acceleration | GPU/CPU compilation via `ov.Core()` |

### Transitive Dependencies

| Package | Purpose |
|---------|---------|
| **torch** (PyTorch) | GPU/device detection (CUDA & MPS availability), YOLO backend |
| **torchvision** | Required by ultralytics |
| **PyYAML** | ByteTrack tracker config parsing |
| **lap** | Linear assignment for ByteTrack |

---

## Configuration & Parameters

### CLI Arguments
```
positional:
  video                     Video file path (optional if --webcam used)

optional:
  --webcam [IDX]            Use webcam as source (default index: 0)
  --tolerance (float)       Appearance similarity threshold (0–0.35), default=0.005
  --sample-rate (int)       Feature update frequency (1=every frame), default=1
  --img-size (int)          YOLO input resolution, default=640
                            choices: {320, 480, 640, 768, 1024, 1280, 1536, 2048}
  --model (str)             YOLO model file, default=yolo26n.pt
  --device (str)            Hardware override: 'cuda'|'mps'|'intel:gpu'|'intel:cpu'|'cpu'
                            default=auto-detect
  --no-window (flag)        Run headless (no display), default=False
```

**Note:** `video` and `--webcam` are mutually exclusive (via `add_mutually_exclusive_group`).

### ByteTrack Configuration (generated at runtime)
```yaml
tracker_type: bytetrack
track_high_thresh: 0.50      # High confidence threshold
track_low_thresh: 0.10       # Low confidence threshold
new_track_thresh: 0.60       # New track initialization
track_buffer: {total_frames} # Video: total frames; Webcam: 900
match_thresh: 0.80           # Association threshold
fuse_score: true             # Combine detection + track scores
```

### In-Memory State
```python
track_features:  dict[int, np.ndarray]  # track_id → appearance vector (running EMA)
track_to_person: dict[int, int]         # track_id → unique person number
unique_people:   list[np.ndarray]       # canonical feature representative per person
```

---

## Key Functions

### `auto_device_selection(intel_available_devices: list) → tuple[str, str]`
Returns (device_string, description) by priority: CUDA → MPS → Intel GPU → Intel CPU → CPU.

### `detect_device(preferred: str | None) → tuple[str, str]`
Resolves hardware device using match/case on user preference. Falls back to auto-selection if preference is unavailable.

### `load_model(device: str, model_name: str = "yolo26n.pt") → tuple[YOLO, str | None]`
Loads YOLO model. For OpenVINO devices: exports to IR format on first run (cached in `{stem}_openvino_model/`), compiles via `ov.Core()`, returns device=None. Otherwise returns (model, device_string).

### `extract_appearance(crop: np.ndarray) → np.ndarray | None`
Extracts 288-dim HSV histogram feature from bounding box crop. Resizes to 48×96, splits top/bottom, computes 18×8 H-S histogram per region. Returns None if crop < 10px.

### `cosine_dist(a: np.ndarray, b: np.ndarray) → float`
Computes cosine distance (1 − normalized dot product). Returns 1.0 if either vector has zero norm.

### `draw_box(frame, x1, y1, x2, y2, person_id, confirmed) → None`
Draws color-coded bounding box (from COLORS palette) and label ("Pessoa N" or "identificando...") with filled background rectangle.

### `draw_overlay(frame, unique_count) → None`
Draws semi-transparent (60% opacity) dark panel at top-left with white text "Pessoas unicas: N".

### `count_unique_people(...) → int`
Main processing loop. Processes video/webcam frames through YOLO+ByteTrack, manages appearance features and person identity mapping, handles visualization. Returns final unique person count.

### `main() → None`
CLI entry point. Parses arguments, validates video file existence, detects device, prints configuration summary, calls `count_unique_people()`, prints result.

---

## Usage Examples

### Basic Video Processing
```bash
python contador.py video.mp4
```

### Webcam Mode
```bash
python contador.py --webcam              # default camera (index 0)
python contador.py --webcam 1            # second camera
```

### Auto-Detect Hardware with Custom Model
```bash
python contador.py video.mp4 --model yolo26l.pt
```

### Strict Intel GPU with Relaxed Tolerance
```bash
python contador.py video.mp4 --device intel:gpu --tolerance 0.05
```

### Headless Mode (No Window)
```bash
python contador.py video.mp4 --no-window --sample-rate 2
```

### High-Speed, Low-Precision
```bash
python contador.py video.mp4 --img-size 320 --sample-rate 3
```

### High-Accuracy Mode
```bash
python contador.py video.mp4 --img-size 1536 --model yolo26x.pt --tolerance 0.003
```

---

## Display Output

### Window Elements
- **Window:** Resizable (`cv2.WINDOW_NORMAL`), titled "Person Counter | pressione Q para sair"
- **Bounding boxes:** Color-coded by person ID (8-color palette, cyclic) or gray if unconfirmed
- **Labels:** "Pessoa N" (confirmed) or "identificando..." (awaiting feature match)
- **Overlay panel:** White text "Pessoas unicas: N" on dark semi-transparent background (60% opacity)
- **Exit:** Press Q to quit early

### Console Output
- **Video mode:** Progress `%` and count — e.g., `[5.2%] | pessoas únicas: 12`
- **Webcam mode:** Frame number and count — e.g., `Webcam ativa | frame: 42 | pessoas unicas: 3`
- **Startup:** Source, model, hardware, tolerance, sample-rate, img-size
- **OpenVINO:** Requested device, actual execution device, full hardware name
- **Final result:** `Pessoas únicas encontradas: N`

---

## Important Notes

### OpenVINO Handling
- Model *must* be compiled via `ov.Core().compile_model()` before `model.track()` to prevent CUDA validation errors
- Device parameter passed as `None` to tracker when using OpenVINO (already bound at compile time)
- Automatic XML file discovery in exported model directory via `Path.glob("*.xml")`
- OpenVINO export is cached — only runs on first execution (creates `{stem}_openvino_model/` directory)
- If compilation fails, falls back to default OpenVINO CPU device with warning

### Tolerance Tuning
- **Too low (e.g., 0.001):** Over-counts due to false re-match failures (same person split into multiple IDs)
- **Too high (e.g., 0.35):** Under-counts due to false re-matches (different people merged)
- **Recommended range:** 0.003–0.10 for typical scenarios
- **Default (0.005):** Conservative — works well for distinct clothing colors

### Performance Trade-offs
- **Smaller `img_size` (320):** Faster, less accurate detection
- **Larger `sample_rate` (3+):** Faster, but appearance features become stale between updates
- **Larger model (yolo26x):** More accurate detection, significantly slower
- **Model size progression:** n (nano, 5.3 MB) → s → m → l → x (most accurate)

### Model Files
- `yolo26n.pt` — Gitignored (5.3 MB, auto-downloaded by ultralytics on first use)
- `yolo26n_openvino_model/` — Auto-generated on first OpenVINO run (yolo26n.xml + yolo26n.bin + metadata.yaml)

---

## Setup & Dependencies

```bash
# Create virtual environment
python3.14 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

For GPU support:
- **NVIDIA:** Install CUDA toolkit + PyTorch with CUDA: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130`
- **Apple Silicon:** `pip install torch` (MPS auto-enabled with PyTorch 2.12+)
- **Intel:** OpenVINO is included in `requirements.txt` — no separate install needed

### Runtime Requirements
- Video file (MP4 or any OpenCV-supported format) or connected webcam
- Display server (X11/Wayland) unless using `--no-window`
- GPU drivers appropriate for the selected device
