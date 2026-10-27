# AGENTS.md

TCC (undergrad thesis) — school-meal management: a Streamlit app that extracts the
menu and recipes from PDFs, counts unique people in video (YOLO + ByteTrack + HSV
appearance re-ID), and computes daily food production (kg) and water use (L).

## Commands

```bash
pip install -r requirements.txt        # torch comes transitively via ultralytics;
                                        # for GPU-specific wheels see the README table
pip install -r requirements-dev.txt     # pytest (dev only)
streamlit run app.py                    # main entry point (pages: Contagem, Resultado)
pytest                                  # light suite — needs pdfplumber/pandas only, NO torch

# Each module also runs standalone:
python -m modulos.contador arquivos/video.mp4 --no-window    # headless count
python -m modulos.cardapio arquivos/cardapio.pdf --mes jun   # --mes omitted → prompts on stdin
python -m modulos.receita                                   # uses arquivos/receita.pdf by default
```

- **No linter, no formatter, no CI.** Tests cover the pure calculation logic
  (`modulos/calculo.py`) and both PDF extractors against the committed fixtures.
  Vision-stage changes must be verified by running `modulos.contador` against
  `arquivos/video.mp4` / `video2.mp4` with `--no-window` (first run auto-downloads
  `yolo26n.pt`; requires torch, so it can't run everywhere).
- **Python 3.11–3.13.** 3.14 is NOT recommended (no torch/ultralytics/openvino wheels
  yet). The code itself only needs 3.10+ syntax (`match/case`, `X | None`).

## Architecture

- `app.py` — single-file Streamlit app, the only user-facing entry point. Owns
  paths (`arquivos/`), caching, and user feedback; no business logic.
- `modulos/` — source of truth, no UI imports (never import `app` from here; and
  `calculo.py` must stay importable without streamlit — the tests import it
  directly). Real package (`__init__.py`):
  `calculo.py` (pure Resultado logic: pt-BR quantity parsing, date normalization,
  recipe matching, day calculation), `contador.py` (YOLO26 + ByteTrack + HSV
  re-ID, one worker thread per source), `cardapio.py` (menu PDF → JSON/CSV),
  `receita.py` (recipes PDF → JSON/CSV).
- `arquivos/` — committed PDFs/videos (fixtures) plus generated JSONs. The app's
  Contagem page auto-lists videos (`.mp4/.avi/.mov/.mkv`) from this folder.
- Generated artifacts are gitignored (`*.json`, `*.csv`, `*.pt`, `yolo*/`, `venv/`)
  and regenerate on demand — do not commit them or "fix" their absence.

## Gotchas

- A requested device that is unavailable makes `detect_device()` print a ⚠️ warning
  and fall back to auto — and the Streamlit UI shows `st.warning` with the hardware
  actually in use. If `intel:gpu` keeps falling back on Linux/Intel, the OS is
  missing the Intel compute runtime (Level-Zero/OpenCL driver — `intel-compute-runtime`
  on Arch, `intel-opencl-icd` on Debian/Ubuntu); OpenVINO can only use devices it
  can see (`ov.Core().available_devices`).
- `modulos.receita`'s CLI resolves its default PDF **relative to the repo root**
  (`arquivos/receita.pdf`) — run it from the repo root or pass a path. It writes
  `arquivos/receitas.json` + `receitas.csv` (the exact names the app reads).
- `cardapio.executar_extracao` prompts via `input()` when `mes` is `None` and
  **raises** on read errors — the CLI catches and exits 1, the app shows
  `st.error`. Pipe the month in for headless runs (`echo jun | ...`) or use `--mes`.
- The app's extraction buttons **always regenerate** (overwrite the JSONs) and
  show success/error feedback. `carregar_receitas` in `app.py` is the
  `@st.cache_data` wrapper — it is `.clear()`ed after regenerating, so don't add
  "JSON exists → skip" no-ops back onto the button path.
- `app.py` imports `modulos.contador` lazily (`_get_contador()`) because
  torch/ultralytics are heavy — keep that import inside functions.
- Streamlit counting runs in a daemon thread (`CounterEngine`): frames flow through
  `queue.Queue(maxsize=1)` (a full queue drops frames — intentional), `status_cb`
  feeds the live count, `stop_event` stops the run. The UI re-renders in ~4s slices
  via `st.rerun()` so buttons stay clickable.
- `calcular_dia`'s DataFrame column names (`Prato`, `Receita`, `Porção (g)`,
  `Fator`, `Água (L)`, `kg a produzir`, `Avisos`) are a UI contract — the metrics
  table and CSV/Excel export reference them by name.

## contador.py invariants (do not break)

- **OpenVINO**: for `openvino:*` devices, `load_model()` returns
  `(model, "intel:gpu" | "intel:cpu")` — ultralytics' *native* Intel device string
  (needs `ultralytics>=8.4`), which `select_device()` passes through untouched and
  the OpenVINO backend maps to the real device (warning + AUTO/CPU fallback if
  unavailable, torch pinned to CPU). Never pass raw OpenVINO names (`"GPU"`/`"CPU"`)
  to `track()` — those DO crash `select_device()` with `Invalid CUDA device`. Keep
  `_garantir_openvino_runtime()`, which shims the `openvino.runtime` alias removed
  in OpenVINO 2025+.
- **One YOLO model instance per source** — required for independent ByteTrack state
  (`persist=True`). Never share a model across sources.
- **`shared.people_lock` guards the match-or-append person-registry block** — it must
  stay atomic; removing it duplicates person IDs across threads.
- **Main thread owns the GUI**: workers only draw and store `latest_frame` (or push to
  `frame_queue`); only the main loop calls `cv2.imshow`/`waitKey`.
- **ByteTrack config is a runtime-generated temp YAML** (deleted on cleanup) — there is
  no checked-in config. Edit the `cfg` string in `count_unique_people()`.
  `track_buffer` = total frame count for videos, 900 for webcams.
- **Re-ID constants are tuned — flag before changing**: 0.7/0.3 track EMA, 0.6/0.4
  person EMA + L2 normalization, 1.2× bottom-half weight, default tolerance 0.005
  (recommended 0.003–0.10; too low over-counts, too high merges people).
- **Track→person mapping is sticky**: once `track_to_person[tid]` is set it is never
  re-resolved, even as features drift.
- Keep the NaN/inf box filter and worker-error propagation (`shared.error` →
  `RuntimeError`) — both fix real crashes (ByteTrack `LinAlgError`, silent thread death).

## Conventions

- **Portuguese everywhere in code**: comments, console strings, UI labels, and commit
  messages (casual, no conventional-commits). Keep new code and commits in Portuguese.
- Remote is **Codeberg** (`codeberg.org/yLipe/Projeto-TCC`), not GitHub.

## Docs

`CONTEXT.md` is the deep reference (architecture tables, contador internals, CLI
tables) and is current. When docs conflict, trust the code — order:
`modulos/` > `app.py` > `CONTEXT.md` > `README.md`.
