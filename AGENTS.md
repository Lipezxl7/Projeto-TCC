# AGENTS.md

## Project

Person counter CLI — single-file app `contador.py`. YOLO26 + ByteTrack + HSV-histogram re-identification to count **unique** people across video/webcam frames. Supports **multiple sources** with cross-source re-ID (shared person registry). Undergraduate thesis (TCC). Comments and console output are in **Portuguese**.

## Environment

- **Python 3.14+** required (uses `match/case`, PEP 604 `str | None`). Local venv is 3.14.5.
- Activate: `source venv/bin/activate` (or call `venv/bin/python` directly). `venv/` is gitignored.
- Install: `pip install -r requirements.txt`
- GPU extras: NVIDIA needs `torch` built with CUDA; Apple Silicon MPS auto-enables with torch 2.12+; Intel uses OpenVINO (already in `requirements.txt`).

## Commands

- Run: `python contador.py video.mp4` or `python contador.py --webcam`
- Multi-source: `python contador.py a.mp4 b.mp4 --webcam 0` (one thread per source, shared cross-source re-ID)
- **There is no test suite, no linter, no typecheck, no formatter, and no CI.** Do not fabricate `pytest`/`ruff`/`rpm run` invocations — there is nothing to run. Verify changes by executing the script against the committed `video.mp4` fixture (37 MB) or with `--no-window`.

## Docs — what to trust

- **`claude.md` is the authoritative context file** (detailed architecture, function reference). Read it for implementation details.
- **`README.md`** is now UTF-8 and accurate. When README conflicts with `claude.md` or `contador.py`, trust the latter two (source of truth).

## Runtime-generated / gitignored artifacts

- `yolo26n.pt` — auto-downloaded by ultralytics on first run (gitignored via `*.pt`).
- `yolo26n_openvino_model/` — auto-generated on first OpenVINO run (gitignored via `yolo*/`); contains `.xml`/`.bin`/`metadata.yaml`.
- A fresh checkout runs without these; do not commit them or try to "fix" their absence.

## Non-obvious implementation gotchas

- **OpenVINO device handling** (`load_model`, `contador.py:50`): for `intel:gpu`/`intel:cpu`, the model is compiled via `ov.Core().compile_model()` **before** `model.track()`, and `device=None` is passed to `track()`. This is deliberate — ultralytics' `select_device()` would otherwise interpret `"GPU"` as a CUDA device and crash with `Invalid CUDA device`. Do not "simplify" by forwarding the device string to `track()`.
- **ByteTrack config is generated at runtime** (`contador.py:200`) as a temp YAML. `track_buffer` is set to the video's total frame count (so tracks never expire mid-video) or `900` for webcam. To change tracker params, edit that template string, not a checked-in config file.
- **Re-ID magic numbers**: 288-dim HSV histogram (48×96 crop, top/bottom split, 18×8 bins each). Track EMA = `0.7*old + 0.3*new`; person canonical EMA = `0.6*old + 0.4*new`. Default cosine-distance tolerance `0.005` (recommended range 0.003–0.10). These look arbitrary but are tuned — flag before changing.
- **Multi-source threading**: each source gets its own YOLO model instance (required for independent ByteTrack state with `persist=True`) running in a daemon thread. The shared `unique_people` registry is guarded by `people_lock` — the match-or-append block must stay atomic to avoid duplicate person IDs across threads. Do not remove the lock or merge model instances.
- **Main thread owns GUI**: workers draw annotated frames and store them; the main thread calls `cv2.imshow`/`cv2.waitKey` (avoids per-platform threading quirks with OpenCV GUI). Do not move `imshow`/`waitKey` into worker threads.

## CLI constraints

- `video` (positional, `nargs="*"`) and `--webcam` (repeatable, `action="append"`) can be mixed; at least one source required.
- `--webcam` with no value defaults to index 0; repeat for multiple cameras (`--webcam 0 --webcam 1`).
- `--img-size` choices: `320 480 640 768 1024 1280 1536 2048`.
- `--device` values: `cuda | mps | intel:gpu | intel:cpu | cpu` (default: auto-detect via chain CUDA → MPS → Intel GPU → Intel CPU → CPU).

## Conventions

- Commit messages are in Portuguese, casual, no conventional-commits format (see `git log`).
- Remote is on **Codeberg** (`codeberg.org/yLipe/Projeto-TCC`), not GitHub.
