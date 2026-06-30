# CONTEXT.md

Authoritative context file for this repository. Read this first.
Source of truth order when anything conflicts: **`contador.py` > `CONTEXT.md` > `README.md`**.

---

## Project

**Person Counter (Contador de Pessoas)** — a Python CLI that counts **unique individuals** across video/webcam frames using **YOLO26** (person detection), **ByteTrack** (multi-object tracking), and **HSV-histogram appearance re-identification**. It handles occlusions, re-entries, and track fragmentation by matching visual features so the same physical person receives a consistent ID — even across **multiple simultaneous sources** (videos + webcams) via a shared person registry and cross-source re-ID.

- **Type:** Undergraduate thesis (Trabalho de Conclusão de Curso — TCC).
- **Language of code comments / labels / console output:** **Portuguese**. This doc and `README.md` are in English.
- **Shape:** Single-file application — `contador.py` (435 lines). No subpackages, no modules.
- **Repository:** https://codeberg.org/yLipe/Projeto-TCC (Codeberg, **not** GitHub).
- **Python:** 3.14+ required (uses `match/case`, PEP 604 `str | None`).

---

## Environment & Setup

- **Python 3.14+** is mandatory. The local venv is 3.14.5.
- Activate: `source venv/bin/activate` (or call `venv/bin/python` directly). `venv/` is gitignored.
- Install: `pip install -r requirements.txt`

```bash
python3.14 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### GPU extras
- **NVIDIA:** PyTorch built with CUDA — `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130`.
- **Apple Silicon:** `pip install torch` (MPS auto-enables with PyTorch 2.12+).
- **Intel:** OpenVINO is already in `requirements.txt` — nothing extra to install.
- **Generic CPU:** Always works as a fallback; no extras.

### Runtime requirements
- A video file (any OpenCV-supported format) or a connected webcam.
- A display server (X11/Wayland) unless using `--no-window`.
- GPU drivers appropriate for the selected `--device`.

---

## Commands

- **Single video:** `python contador.py video.mp4`
- **Webcam (default index 0):** `python contador.py --webcam`
- **Second webcam:** `python contador.py --webcam 1`
- **Multi-source (one daemon thread per source, shared cross-source re-ID):**
  - `python contador.py a.mp4 b.mp4` — two videos
  - `python contador.py video.mp4 --webcam 0` — video + webcam
  - `python contador.py --webcam 0 --webcam 1` — two webcams
  - `python contador.py a.mp4 b.mp4 --webcam 0` — mix of all of the above

### Verification & tooling status
- **There is NO test suite, NO linter, NO typecheck, NO formatter, and NO CI.**
- Do **not** fabricate `pytest` / `ruff` / `npm run` / `tox` invocations — there is nothing to run.
- Verify changes by executing the script against the committed `video.mp4` fixture (~37 MB) — or `video2.mp4` (same size, a copy) — or with `--no-window` for headless runs.

---

## Architecture & Structure

Single file, layered:

```
contador.py (single file – all logic, 435 lines)
├── Device Selection Layer
│   ├── auto_device_selection()   → CUDA → MPS → Intel GPU → Intel CPU → CPU      [contador.py:16]
│   └── detect_device()           → match/case on user pref; fallback to auto      [contador.py:31]
├── Model Loading Layer
│   └── load_model()              → YOLO load; optional OpenVINO export + compile   [contador.py:53]
├── Appearance Features Layer
│   ├── extract_appearance()      → 288-dim HSV histogram (48×96, top/bottom split) [contador.py:122]
│   └── cosine_dist()             → 1 − normalized dot product                      [contador.py:136]
├── Visualization Layer
│   ├── COLORS                    → 8-color BGR palette (cyclic by person ID)       [contador.py:106]
│   ├── draw_box()                → color-coded box + label (or gray if unconfirmed)[contador.py:144]
│   └── draw_overlay()            → semi-transparent "Pessoas unicas: N" panel       [contador.py:162]
├── Multi-Source / Threading Layer
│   ├── _Shared (dataclass)       → shared registry: unique_people + lock + stop    [contador.py:179]
│   ├── _Source (dataclass)       → per-source state: model, tracker, dicts, cap    [contador.py:186]
│   ├── _worker()                 → per-source daemon thread main loop              [contador.py:204]
│   └── _print_status()           → throttled combined progress line (≤10 Hz)       [contador.py:269]
├── Core Orchestration
│   └── count_unique_people()     → builds sources, spawns threads, owns GUI loop   [contador.py:281]
└── CLI Entry Point
    ├── NumerarPessoas()          → argparse, validation, device detect, summary    [contador.py:366]
    └── __main__                  → prints final count                              [contador.py:434]
```

**Note:** The CLI entry function is `NumerarPessoas()` (renamed from `main()` in commit `9dbac85`). It returns the final unique-person count, which `__main__` prints.

---

## Key Concepts & Implementation Details

### Device abstraction
- **Priority chain:** CUDA (NVIDIA) → MPS (Apple Silicon) → OpenVINO Intel GPU → OpenVINO Intel CPU → plain CPU.
- **CLI input → internal string mapping:** `intel:gpu` → `openvino:GPU`; `intel:cpu` → `openvino:CPU`. Other values (`cuda`, `mps`, `cpu`) pass through unchanged.
- **Fallback:** If a user-preferred device is unavailable, `detect_device()` silently falls back to `auto_device_selection()`.
- `detect_device()` reads `ov.Core().available_devices` once per call.

### OpenVINO handling (critical — do not "simplify")
For `openvino:*` devices, `load_model()` (`contador.py:53`):
1. Exports the `.pt` model to OpenVINO IR format **only on first run** (cached in `{stem}_openvino_model/`, auto-discovered via `Path.glob("*.xml")`).
2. Explicitly compiles the IR via `ov.Core().compile_model(xml, ov_target)` and prints `EXECUTION_DEVICES` + `FULL_DEVICE_NAME` for verification. On failure it prints a warning and continues (intending OpenVINO's default CPU).
3. Returns `YOLO(ov_path)` with **`device_para_track = None`**.

The returned `None` is passed to `model.track()` (see `_worker`, `contador.py:210`). This is the actual fix for the CUDA crash: ultralytics' `select_device()` would otherwise interpret `"GPU"` as a CUDA device and raise `Invalid CUDA device`. **Do not forward the OpenVINO device string to `track()`** and do not merge this path with the non-OpenVINO branch. The explicit pre-compile is primarily for verification/early-failure surfacing — the `compiled` object is not reused; ultralytics re-loads `YOLO(ov_path)` internally.

### Appearance-based re-identification
`extract_appearance(crop)` (`contador.py:122`):
- Returns `None` if `crop` is `None`, empty, or smaller than **10 px** in either dimension.
- Resizes crop to **48×96** (width×height), converts to HSV.
- Splits into **top half** (`hsv[:48]`) and **bottom half** (`hsv[48:]`) — i.e. upper/lower body.
- Per region: 2D H-S histogram with **H=18 bins** (range 0–180), **S=8 bins** (range 0–256), normalized via `cv2.normalize` (default `NORM_MINMAX`) then flattened → 144 dims/region.
- Concatenates both regions → **288-dimensional** feature vector.

`cosine_dist(a, b)` (`contador.py:136`): `1 − dot(a,b)/(‖a‖·‖b‖)`; returns `1.0` if either norm is zero.

### Re-ID magic numbers (tuned — flag before changing)
- **Track-level feature EMA:** `0.7 * old + 0.3 * new` (`contador.py:234`).
- **Person-level canonical EMA:** `0.6 * old + 0.4 * new` (`contador.py:248`).
- **Default cosine-distance tolerance:** `0.005` (recommended range **0.003–0.10**).
- These look arbitrary but are tuned. Do not adjust without explicit intent.

### Tracking strategy
- **Detector:** YOLO26, person class only (`classes=[0]`), `conf=0.40`, `iou=0.60`, `verbose=False`, `persist=True`.
- **Tracker:** ByteTrack via a **runtime-generated temp YAML** (`contador.py:303`):
  ```yaml
  tracker_type: bytetrack
  track_high_thresh: 0.50      # high-confidence threshold
  track_low_thresh: 0.10       # low-confidence threshold
  new_track_thresh: 0.60       # new-track initialization
  track_buffer: {buf}          # video: total frame count; webcam/unknown: 900
  match_thresh: 0.80           # association threshold
  fuse_score: true             # combine detection + track scores
  ```
- **`track_buffer` (`buf`) logic** (`contador.py:300`): `buf = total if total > 0 and not is_webcam else 900`. So a video whose frame count is detectable gets `buf = total frames` (tracks never expire mid-video); webcams **and** videos with `total <= 0` get `buf = 900`.
- To change tracker params, edit the `cfg` template string in `count_unique_people()` — there is **no checked-in config file**. The temp YAML is deleted on cleanup.

### Person identity assignment (atomic, lock-guarded)
In `_worker()` (`contador.py:239`):
- Feature extraction only runs when `frame_num % sample_rate == 0` and `extract_appearance` returns non-`None`.
- A track is assigned a person **only on first appearance with a valid feature**, guarded by `shared.people_lock`. The match-or-append block must stay atomic to avoid duplicate person IDs across threads.
- Matching: linear scan of `shared.unique_people`; first entry with `cosine_dist(feat, rep) <= tolerance` wins → that person's canonical vector is EMA-updated and `track_to_person[tid] = matched_idx + 1` (1-based).
- No match → append `feat` as a new person; `track_to_person[tid] = len(unique_people)`.
- **A track keeps its first-assigned person for the entire run** — the `if tid not in track_to_person` guard means later feature drift on that track never re-resolves its identity.
- Unconfirmed tracks (no person ID yet) are drawn gray with label `identificando...`.

### Multi-source threading (critical invariants)
- **One YOLO model instance per source** (`contador.py:292`, `load_model` called per source). Required for independent ByteTrack state with `persist=True`. **Do not merge model instances across sources.**
- Each source runs in a **daemon thread** (`contador.py:322`); `persist=True` keeps ByteTrack state alive across frames within that source.
- The shared registry (`_Shared`: `unique_people`, `people_lock`, `stop_event`) is the cross-source bridge — the same physical person in different sources receives the same person ID. **Do not remove `people_lock`.**
- **Main thread owns the GUI:** workers only draw annotations and store `latest_frame`; the main thread calls `cv2.imshow` / `cv2.waitKey` (`contador.py:333`). This avoids per-platform OpenCV GUI threading quirks. **Do not move `imshow`/`waitKey` into worker threads.**
- `latest_frame` is written by the worker and read by the main thread without a lock — intentional; worst case is a torn read, which is acceptable.
- Shutdown: `Q` key sets `stop_event`; workers exit; threads joined with `timeout=5`; each `cap.release()`; temp tracker YAMLs `os.unlink`'d (errors ignored); `cv2.destroyAllWindows()`.

### Color palette
- 8 predefined BGR colors (`COLORS`, `contador.py:106`), assigned cyclically by person ID: `COLORS[(person_id - 1) % 8]`.
- Unconfirmed tracks drawn in gray `(160, 160, 160)`.

---

## CLI Arguments

Defined in `NumerarPessoas()` (`contador.py:366`). `video` (positional, `nargs="*"`) and `--webcam` (`action="append"`, `nargs="?"`, `const=0`) **can be freely mixed** — they are **NOT** mutually exclusive. At least one source is required.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `video` (positional) | path(s) | — | One or more video files (`nargs="*"`) |
| `--webcam [IDX]` | int | index `0` | Webcam as source; repeatable (`--webcam 0 --webcam 1`) |
| `--tolerance` | float | `0.005` | Appearance similarity threshold. Help text says `0–0.35`; **not range-enforced** (any float accepted). Recommended `0.003–0.10` |
| `--sample-rate` | int | `1` | Update appearance every N frames (`1` = every frame) |
| `--img-size` | int | `640` | YOLO input resolution. Choices: `320 480 640 768 1024 1280 1536 2048` |
| `--model` | str | `yolo26n.pt` | YOLO model file (`yolo26n`→`s`→`m`→`l`→`x`) or path to a custom `.pt` |
| `--device` | str | auto | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu`. Auto-detected when omitted |
| `--no-window` | flag | off | Run headless (no display) |

### `--device` values & auto-detect chain
`cuda | mps | intel:gpu | intel:cpu | cpu` (default: auto-detect via CUDA → MPS → Intel GPU → Intel CPU → CPU).

---

## In-Memory State

```python
# Per source (_Source):
track_features:  dict[int, np.ndarray]  # track_id → appearance vector (running EMA, 288-dim)
track_to_person: dict[int, int]         # track_id → unique person number (1-based)
latest_frame:    object                 # last annotated frame, for main-thread display
frame_num:       int                    # frame counter (drives sample_rate)
done:            bool                   # source exhausted / disconnected

# Shared across sources (_Shared):
unique_people:   list[np.ndarray]       # canonical feature representative per person (EMA-updated)
people_lock:     threading.Lock         # guards match-or-append block (atomic)
stop_event:      threading.Event        # cooperative shutdown (Q key or source end)
```

---

## Key Functions

### `auto_device_selection(intel_available_devices: list) → tuple[str, str]` — `contador.py:16`
Returns `(device_string, description)` by priority: CUDA → MPS → `openvino:GPU` → `openvino:CPU` → `cpu`.

### `detect_device(preferred: str | None = None) → tuple[str, str]` — `contador.py:31`
Resolves hardware via `match/case` on user preference; falls back to `auto_device_selection()` if the preference is unavailable or `None`.

### `load_model(device: str, model_name: str = "yolo26n.pt") → tuple[YOLO, str | None]` — `contador.py:53`
Loads YOLO. For `openvino:*`: exports to IR on first run (cached), compiles via `ov.Core()` for verification, returns `(YOLO(ov_path), None)`. Otherwise returns `(YOLO(model_name), device)`.

### `extract_appearance(crop: np.ndarray) → np.ndarray | None` — `contador.py:122`
288-dim HSV histogram (48×96 crop, top/bottom split, 18×8 bins each). Returns `None` if crop < 10 px.

### `cosine_dist(a: np.ndarray, b: np.ndarray) → float` — `contador.py:136`
`1 − normalized dot product`; `1.0` if either vector has zero norm.

### `draw_box(frame, x1, y1, x2, y2, person_id, confirmed) → None` — `contador.py:144`
Color-coded bounding box + filled-background label (`"Pessoa N"` or `"identificando..."`).

### `draw_overlay(frame, unique_count) → None` — `contador.py:162`
Semi-transparent (60% opacity) dark panel, top-left, white text `"Pessoas unicas: N"`.

### `_worker(src, shared, tolerance, sample_rate, img_size, show_window) → None` — `contador.py:204`
Per-source daemon-thread loop: reads frames, runs `model.track`, updates track features (EMA), assigns person IDs (atomic match-or-append under `people_lock`), draws annotations, stores `latest_frame`.

### `_print_status(states, shared) → None` — `contador.py:269`
Prints a combined `\r`-overwriting progress line: `"label: X.X%  |  label: frame N  |  pessoas únicas: M"`. Throttled to ≤10 Hz by the caller.

### `count_unique_people(sources, tolerance=0.005, sample_rate=1, img_size=640, show_window=True, device="cpu", model_name="yolo26n.pt") → int` — `contador.py:281`
Builds per-source `_Source` state (model + tracker YAML + `VideoCapture`), spawns one daemon thread per source, owns the GUI/status main loop, runs cleanup, returns `len(shared.unique_people)`.

### `NumerarPessoas() → int` — `contador.py:366`
CLI entry point: argparse, validates video files exist, builds `sources` list, resolves device, prints config summary, calls `count_unique_people()`, returns the count.

---

## Technologies & Dependencies

### Direct (`requirements.txt`)
| Package | Purpose | Notes |
|---------|---------|-------|
| **opencv-python** | Video I/O, frame processing, HSV, drawing | `cv2.VideoCapture`, `cv2.calcHist`, `cv2.imshow` |
| **numpy** | Array ops, histogram math | distance metrics, feature concat |
| **ultralytics** | YOLO26 detection + ByteTrack tracking | `YOLO`, `model.track(persist=True)` |
| **openvino** | Intel hardware acceleration | GPU/CPU compile via `ov.Core()` |

### Transitive
| Package | Purpose |
|---------|---------|
| **torch** (PyTorch) | GPU/device detection (CUDA & MPS), YOLO backend |
| **torchvision** | Required by ultralytics |
| **PyYAML** | ByteTrack tracker config parsing |
| **lap** | Linear assignment for ByteTrack |

---

## Display Output

### Window
- **Window title:** `Person Counter  |  {label}  |  pressione Q` (one window per source when `show_window`).
- Resizable (`cv2.WINDOW_NORMAL`).
- Bounding boxes color-coded by person ID (8-color cyclic palette); gray for unconfirmed tracks.
- Labels: `"Pessoa N"` (confirmed) or `"identificando..."` (awaiting feature match).
- Top-left overlay panel: `"Pessoas unicas: N"` (global count across **all** sources), 60% opacity.
- Press **Q** to quit early.

### Console
- **Startup:** lists sources (📹 webcam / 🎬 video), model, hardware description, tolerance, sample-rate, img-size.
- **OpenVINO:** prints requested device, actual `EXECUTION_DEVICES`, and `FULL_DEVICE_NAME`.
- **Progress:** combined per-source line (`\r`-overwriting, ≤10 Hz): `label: X.X%` for videos, `label: frame N` for webcams, then `pessoas únicas: M`.
- **Final:** `Pessoas únicas encontradas: N`.

---

## Tolerance Tuning

- **Too low (e.g. 0.001):** over-counts — legitimate re-matches fail, splitting one person into multiple IDs.
- **Too high (e.g. 0.35):** under-counts — different people merge into one ID.
- **Recommended range:** `0.003–0.10` for typical scenarios.
- **Default (`0.005`):** conservative; works well for distinct clothing colors.

## Performance Trade-offs
- **Smaller `--img-size` (320):** faster, less accurate detection.
- **Larger `--sample-rate` (3+):** faster, but appearance features go stale between updates.
- **Larger model (`yolo26x`):** more accurate, significantly slower.
- **Model size progression:** `n` (nano, ~5.3 MB) → `s` → `m` → `l` → `x` (most accurate).

---

## Usage Examples

```bash
# Basic video
python contador.py video.mp4

# Webcam (default 0, or second camera)
python contador.py --webcam
python contador.py --webcam 1

# Multi-source with cross-source re-ID
python contador.py a.mp4 b.mp4 --webcam 0 --tolerance 0.02

# Auto-detect hardware with a bigger model
python contador.py video.mp4 --model yolo26l.pt

# Strict Intel GPU with relaxed tolerance
python contador.py video.mp4 --device intel:gpu --tolerance 0.05

# Headless
python contador.py video.mp4 --no-window --sample-rate 2

# High speed, low precision
python contador.py video.mp4 --img-size 320 --sample-rate 3

# High accuracy
python contador.py video.mp4 --img-size 1536 --model yolo26x.pt --tolerance 0.003
```

---

## Runtime-generated / gitignored artifacts

- `yolo26n.pt` — auto-downloaded by ultralytics on first run (gitignored via `*.pt`, ~5.3 MB).
- `yolo26n_openvino_model/` — auto-generated on first OpenVINO run (gitignored via `yolo*/`); contains `.xml` / `.bin` / `metadata.yaml`.
- ByteTrack YAML — created in a `tempfile.NamedTemporaryFile` at startup, deleted on cleanup (never committed).
- A fresh checkout runs without any of these; **do not commit them or try to "fix" their absence.**

`.gitignore` contents: `*.pt`, `.vscode/`, `venv/`, `yolo*/`, `__pycache__/`.

---

## Non-obvious Implementation Gotchas (do-not-break list)

1. **OpenVINO device handling** (`load_model`, `contador.py:53`): compile via `ov.Core().compile_model()` for verification; pass `device=None` to `track()`. Do **not** forward the OpenVINO device string to `track()` — ultralytics' `select_device()` would interpret `"GPU"` as CUDA and crash with `Invalid CUDA device`.
2. **ByteTrack config is runtime-generated** (`contador.py:303`). `track_buffer = total frames` for videos with a detectable frame count; `900` for webcams **and** videos with `total <= 0`. Edit the `cfg` template string, not a config file.
3. **Re-ID magic numbers** (288-dim HSV, 0.7/0.3 track EMA, 0.6/0.4 person EMA, tolerance 0.005) are tuned — flag before changing.
4. **Multi-source threading**: one YOLO per source (independent ByteTrack `persist=True` state); shared `unique_people` guarded by `people_lock`; the match-or-append block must stay atomic. Do not remove the lock or merge model instances.
5. **Main thread owns the GUI**: workers draw + store `latest_frame`; only the main thread calls `cv2.imshow`/`cv2.waitKey`. Do not move these into worker threads.
6. **Track identity is sticky**: once `track_to_person[tid]` is set, it is never re-resolved, even as features drift.
7. **CLI source mixing**: `video` and `--webcam` are **not** mutually exclusive — they are designed to be combined.

---

## Conventions

- **Commit messages:** Portuguese, casual, no conventional-commits format (see `git log`).
- **Remote:** Codeberg (`codeberg.org/yLipe/Projeto-TCC`), not GitHub.
- **Code style:** comments and console strings in Portuguese; no linter/formatter enforced.
