# CONTEXT.md

Authoritative context file for this repository. Read this first (after `AGENTS.md`).
Source of truth order when anything conflicts: **`modulos/` > `app.py` > `CONTEXT.md` > `README.md`**.

> **Current shape (2026-10):** `app.py` is the user-facing entry point — a
> single-file Streamlit app with two pages ("Contagem" and "Resultado").
> Pure business logic lives in `modulos/calculo.py` (UI-free, unit-tested).
> The old `main.py` orchestrator **no longer exists**; the CLI modules
> (`python -m modulos.<name>`) remain supported and are now all runnable
> from a fresh checkout. There is a light pytest suite (`tests/`) that does
> **not** require torch/ultralytics.

---

## Project

**TCC — Regulamento Alimentar Escolar** — a Python + Streamlit pipeline for school-meal management:

1. **Cardápio extraction** (`modulos/cardapio.py`) — reads a menu PDF and produces structured JSON/CSV of dates + dishes.
2. **Receitas extraction** (`modulos/receita.py`) — reads a recipes PDF and produces structured JSON/CSV of ingredients, servings, and cooking instructions.
3. **Person counting** (`modulos/contador.py`) — counts **unique individuals** across video/webcam frames using **YOLO26** (person detection), **ByteTrack** (multi-object tracking), and **HSV-histogram appearance re-identification**. Handles occlusions, re-entries, and track fragmentation so the same physical person receives a consistent ID — even across **multiple simultaneous sources** (videos + webcams) via a shared person registry and cross-source re-ID.
4. **Production calculation** (`modulos/calculo.py`, surfaced by the "Resultado" page) — cross-references menu + recipes via fuzzy matching, computes water and total-to-produce per dish, and exports CSV/Excel.

- **Type:** Undergraduate thesis (Trabalho de Conclusão de Curso — TCC).
- **Language of code comments / labels / console output:** **Portuguese**. `CONTEXT.md`, `README.md` and `AGENTS.md` are in English prose; keep code/UI/commits in Portuguese.
- **Repository:** https://codeberg.org/yLipe/Projeto-TCC (Codeberg, **not** GitHub).
- **Python:** 3.11–3.13. **3.14 is NOT recommended** (torch/ultralytics/openvino wheels missing as of 2026-10). The code itself only needs 3.10+ syntax (`match/case`, PEP 604 `X | None`).

---

## Structure

```
Projeto-TCC/
├── app.py                  # App Streamlit (Contagem + Resultado) — arquivo único
├── modulos/                # fontes de verdade (nunca importam a UI)
│   ├── __init__.py         # package marker
│   ├── calculo.py          # lógica pura do Resultado (parsing, matching, cálculo)
│   ├── cardapio.py         # Extração do cardápio (PDF -> JSON/CSV)
│   ├── receita.py          # Extração de receitas (PDF -> JSON/CSV)
│   └── contador.py         # Contagem de pessoas únicas (single-file)
├── tests/                  # pytest (lógica pura + extratores de PDF)
│   ├── test_calculo.py
│   ├── test_cardapio.py    # integração contra arquivos/cardapio.pdf real
│   └── test_receita.py
├── arquivos/               # Fixtures e saídas
│   ├── cardapio.pdf        # só contém JUNHO (mes="jun")
│   ├── receita.pdf         # 134 receitas
│   ├── video.mp4, video2.mp4
│   └── TCC_Regulamento_Alimentar (1).docx
├── requirements.txt         # runtime (pisos mínimos: ultralytics>=8.3, streamlit>=1.49)
├── requirements-dev.txt     # pytest>=7
├── pyproject.toml           # config do pytest (pythonpath, testpaths)
├── AGENTS.md                # rampa rápida para agentes de IA
├── CONTEXT.md
└── README.md
```

`app.py` imports the modules via `from modulos import calculo` (plus lazy
`from modulos import cardapio, receita, contador` inside functions). Each module
under `modulos/` is also runnable standalone via `python -m modulos.<name>`.

---

## Environment & Setup

- **Python 3.11–3.13** (see warning above).
- Activate: `source venv/bin/activate` (or call `venv/bin/python` directly). `venv/` is gitignored.
- Install: `pip install -r requirements.txt` (+ `pip install -r requirements-dev.txt` for tests).

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### GPU extras (only needed for the counting stage)
- **NVIDIA:** PyTorch built with CUDA + the proprietary NVIDIA driver (no CUDA Toolkit needed — the wheels bundle the CUDA runtime). See the README's hardware tables.
- **Apple Silicon:** `pip install torch` (MPS; the driver ships with macOS).
- **Intel:** OpenVINO is already in `requirements.txt`; the **GPU** additionally needs the OS compute driver — Arch: `intel-compute-runtime`, Debian/Ubuntu: `intel-opencl-icd` (see README's "Pacotes de sistema").
- **Generic CPU:** Always works as a fallback; no extras.

### Runtime requirements
- PDF fixtures (`arquivos/cardapio.pdf`, `arquivos/receita.pdf`) for the extraction stages.
- A video file (any OpenCV-supported format) or a connected webcam for the counting stage.
- A display server (X11/Wayland) for the counting CLI window, unless `--no-window`.
- GPU drivers appropriate for the selected `--device` (counting stage).

---

## Commands

### App (uso principal)

```bash
streamlit run app.py
```

### Per-stage (standalone)

- **Cardápio:** `python -m modulos.cardapio arquivos/cardapio.pdf --mes jun`
  (omit `--mes` → prompts via `input()`; outputs land beside the PDF:
  `arquivos/cardapio.json` + `cardapio.csv`)
- **Receitas:** `python -m modulos.receita` — defaults to `arquivos/receita.pdf`
  and writes `arquivos/receitas.json` + `receitas.csv` (the names the app reads);
  accepts an optional PDF path argument.
- **Contagem — single video:** `python -m modulos.contador arquivos/video.mp4`
- **Contagem — webcam (default index 0):** `python -m modulos.contador --webcam`
- **Contagem — multi-source (one daemon thread per source, shared cross-source re-ID):**
  - `python -m modulos.contador arquivos/a.mp4 arquivos/b.mp4` — two videos
  - `python -m modulos.contador arquivos/video.mp4 --webcam 0` — video + webcam
  - `python -m modulos.contador --webcam 0 --webcam 1` — two webcams

### Tests

```bash
pip install -r requirements-dev.txt
pytest            # ou: pytest tests/test_calculo.py -k agua
```

The suite needs only pdfplumber + pandas + pytest (no torch). It covers the
pure calculation logic and both PDF extractors against the committed fixtures.

### Tooling status
- **No linter, no formatter, no CI** (Codeberg would use Woodpecker, not GitHub Actions).
- Verify counting-stage changes by running the module against the committed
  `arquivos/video.mp4` / `arquivos/video2.mp4` — use `--no-window` for headless runs.

---

## Architecture

### `app.py` — Streamlit app (single file)

Two pages selected by a sidebar radio ("Contagem" / "Resultado"), stored in
`st.session_state["pagina"]`.

Key pieces:

| Piece | Purpose |
|-------|---------|
| `gerar_cardapio(mes)` | Extracts the menu PDF → `arquivos/cardapio.json`. **Overwrites** the existing JSON; raises on failure (UI shows `st.error`). |
| `gerar_receitas()` | Extracts the recipes PDF → `arquivos/receitas.json`. Same overwrite/raise contract. |
| `carregar_receitas(caminho)` | `@st.cache_data` wrapper over `calculo.carregar_receitas`; the app calls `.clear()` after regenerating. |
| `CounterEngine` | Runs `contador.count_unique_people()` in a daemon thread; feeds frames via `queue.Queue(maxsize=1)` (full queue drops frames — intentional), `status_cb` for the live count, `stop_event` for the stop button. UI re-renders in ~4s slices via `st.rerun()` so buttons stay clickable. |
| `_get_contador()` | Lazy import of `modulos.contador` (torch/ultralytics are heavy). |
| `tela_contagem()` | Video picker from `arquivos/` (mp4/avi/mov/mkv), YOLO model/tolerance/sample-rate/img-size/device pickers, Iniciar/Parar buttons, live frames. |
| `tela_resultado()` | Extraction buttons (always regenerate + success/error feedback), month selector (defaults to the **current month**), date/segment/alunos inputs, dish multiselect (auto-filled from the menu), metrics + table + CSV/Excel export. |

### `modulos/calculo.py` — pure Resultado logic (UI-free, tested)

| Function | Purpose |
|----------|---------|
| `sem_acento` / `slug` / `tokens` | Text normalization; `tokens` drops stopwords (`STOP`). |
| `numero_br(num)` | pt-BR number parsing: comma is always decimal; a dot is thousands only when followed by exactly 3 digits (`'1.500'` → 1500, `'1.5'` → 1.5). |
| `parse_gramas(texto)` | Free-text quantity → grams. Prefers parenthesised values (`'50g (120g cozido)'` → 120); `kg`/`l`/`litros` × 1000; numeric passthrough; unparseable → 0.0. |
| `carregar_receitas(caminho)` | Reads `receitas.json`, normalizes each recipe into `{nome, rendimento_g, porcao_fund_g, porcao_em_g, ingredientes:[{nome, qtd}]}`, indexed by slug. Tolerates `quantidade_g_ml`↔`peso_base_g` and `ingrediente`↔`nome` key variants. |
| `buscar_receita(banco, prato)` | Exact slug match, else best token-overlap ≥ 50%. |
| `normalizar_data(valor)` | `date`, ISO, `DD-MM`, `DD/MM`, `DD/mmm` → `'dd/mm'` key. |
| `pratos_do_dia(caminho_cardapio, data)` | Dishes for a date (or `[]`); drops `"REFEIÇÃO"` pseudo-dishes. |
| `eh_agua(nome)` | Substring `"agua"` after accent-folding. |
| `calcular_dia(alunos, pratos, segmento, banco)` | Per-dish rows: `fator = (porcao×alunos)/rendimento`, `Água (L) = Σ(agua_g × fator)/1000` (**sums every water ingredient**), `kg a produzir = porcao×alunos/1000`. Missing recipe → `"sem ficha técnica"` warning row. |

**Column names are a UI contract** (`Prato`, `Receita`, `Porção (g)`, `Fator`,
`Água (L)`, `kg a produzir`, `Avisos`) — the metrics/table/export depend on them.

### `modulos/contador.py` — person counter (single file)

```
modulos/contador.py (single file – all counting logic)
├── Device Selection Layer
│   ├── auto_device_selection()   → CUDA → MPS → Intel GPU → Intel CPU → CPU
│   └── detect_device()            → match/case on user pref; silent fallback to auto
├── Model Loading Layer
│   ├── _garantir_openvino_runtime() → shim for the 'openvino.runtime' alias removed in OpenVINO 2025+
│   └── load_model()               → YOLO load; optional OpenVINO export + compile
├── Appearance Features Layer
│   ├── extract_appearance()       → 324-dim HSV histogram (48×96 crop, top/bottom split, V-chan + 1.2× bottom)
│   └── cosine_dist()              → 1 − normalized dot product
├── Visualization Layer
│   ├── COLORS                     → 8-color BGR palette (cyclic by person ID)
│   ├── draw_box()                 → color-coded box + label (gray if unconfirmed)
│   └── draw_overlay()             → semi-transparent "Pessoas unicas: N" panel
├── Multi-Source / Threading Layer
│   ├── _Shared (dataclass)        → shared registry: unique_people + lock + stop + error
│   ├── _Source (dataclass)        → per-source state: model, tracker, dicts, cap
│   ├── _worker()                  → per-source daemon thread main loop
│   └── _print_status()            → throttled combined progress line (≤10 Hz)
├── Core Orchestration
│   └── count_unique_people()      → builds sources, spawns threads, owns GUI loop
└── CLI Entry Point
    ├── NumerarPessoas()           → argparse, validation, device detect, summary
    └── __main__                   → prints final count
```

**Note:** the CLI entry function is `NumerarPessoas()`; the Streamlit app calls
`count_unique_people()` + `detect_device()` programmatically and bypasses it.

### `modulos/cardapio.py` — menu extractor

Reads `arquivos/cardapio.pdf` (or any PDF path) with `pdfplumber`. For each page,
looks for cells containing `/<mes>` (e.g. `/jun`), then walks 3 rows down to the
refeição row, strips parenthesised ingredient lists, fixes line breaks in compound
dish names (lines ending in `COM|DE|AO|A|EM|E|OU` get concatenated with the next),
splits on `E|OU|,`, uppercases, and deduplicates per date. Output: a list of
`{"data": "DD/mmm", "pratos": ["...", "..."]}` dicts, saved as JSON and CSV beside
the PDF.

Key functions:
- `executar_extracao(caminho_pdf, arquivo_saida, mes, salvar_json, salvar_csv)` —
  main extractor. `mes=None` prompts via `input()`. **Raises** on read errors
  (the CLI prints and exits 1; the app shows `st.error`).
- `save_json` / `save_csv` — writers.

CLI: `python -m modulos.cardapio <pdf> [--mes jun]`.

### `modulos/receita.py` — recipe extractor

Reads the recipes PDF with `pdfplumber`. For each page containing
`Nome da preparação:`, extracts the recipe name, etapa de ensino, tipo de
atendimento, faixa etária, modo de preparo, and a footer block (rendimento,
porção fundamental, porção EJA/E.M., tempo de preparo, medidas caseiras).
Ingredients are parsed from the page's tables: rows between the "INGREDIENTE"
header and the footer. Each ingredient is `{ingrediente, quantidade_g_ml, medida_caseira}`.

Key functions:
- `extract_recipes(pdf_path)` — main extractor; returns a list of recipe dicts.
- `parse_number(text)` — tolerant numeric parsing (pt-BR: dot=thousands, comma=decimal).
- `parse_footer_row(row_text, footer)` — regex-driven footer inference, fairly tolerant of spacing/typography.
- `save_json` / `save_csv` — writers.
- `main()` — CLI: optional PDF path argument; defaults to
  `arquivos/receita.pdf` at the **repo root** and writes
  `arquivos/receitas.json` + `receitas.csv` (the names the app reads).

---

## contador.py — Key Concepts & Implementation Details

### Device abstraction
- **Priority chain:** CUDA (NVIDIA) → MPS (Apple Silicon) → OpenVINO Intel GPU → OpenVINO Intel CPU → plain CPU.
- **CLI input → internal string mapping:** `intel:gpu` → `openvino:GPU`; `intel:cpu` → `openvino:CPU`. Other values (`cuda`, `mps`, `cpu`) pass through unchanged.
- **Fallback:** if a user-preferred device is unavailable, `detect_device()` prints a ⚠️ warning (requested device + what it fell back to) and falls back to `auto_device_selection()`.
- `detect_device()` reads `ov.Core().available_devices` once per call.

### OpenVINO handling (critical — do not "simplify")
For `openvino:*` devices, `load_model()`:
1. Calls `_garantir_openvino_runtime()` first — old ultralytics does
   `from openvino.runtime import Core`, an alias removed in OpenVINO 2025+;
   the shim injects a module pointing at the new `openvino`.
2. Exports the `.pt` model to OpenVINO IR **only on first run** (cached in
   `{stem}_openvino_model/`, auto-discovered via `Path.glob("*.xml")`).
3. Returns `YOLO(ov_path)` with **`device_para_track = "intel:gpu" | "intel:cpu"`** —
   ultralytics' *native* Intel device string (requires `ultralytics>=8.4`).
4. Runs one dummy `model.predict(..., device=dispositivo)` to fail early with a
   clear message if the ultralytics/openvino combo or the device plugin breaks.

Why this is safe (and why `None` was used before): ultralytics ≥8.4's
`select_device()` passes `intel:*` strings through untouched (no CUDA resolution),
and its OpenVINO backend maps `intel:gpu` → OpenVINO `GPU`, logs the resolved
device, warns, and falls back to `AUTO`/`CPU` if unavailable — torch stays on CPU.
**Never pass raw OpenVINO device names (`"GPU"`/`"CPU"`) to `track()`** — those DO
crash `select_device()` with `Invalid CUDA device` (the crash that created the old
`None` workaround).

**OS prerequisite (the usual "GPU não funciona" culprit):** OpenVINO only lists the
Intel GPU if the system has the Intel compute runtime (Level-Zero/OpenCL "NEO"
driver; Arch package `intel-compute-runtime`). Without it
`ov.Core().available_devices == ['CPU']` and every GPU request falls back — now with
a ⚠️ from `detect_device()` and an `st.warning` in the app.

### Appearance-based re-identification
`extract_appearance(crop)`:
- Returns `None` if `crop` is `None`, empty, smaller than **10 px** in either dimension, or with extreme aspect ratio (`w/h < 0.15` or `w/h > 6.0`).
- Resizes crop to **48×96** (width×height), converts to HSV.
- Splits into **top half** (`hsv[:48]`) and **bottom half** (`hsv[48:]`) — upper/lower body.
- Per region: 2D H-S histogram with **H=18 bins** (0–180), **S=8 bins** (0–256), normalized, flattened → 144 dims, **plus** a 1D V histogram with **18 bins**, normalized → 18 dims. → **162 dims per region**.
- Bottom-half features are **spatially weighted by 1.2×** (more pose-invariant).
- Concatenates both regions → **324-dimensional** feature vector.

`cosine_dist(a, b)`: `1 − dot(a,b)/(‖a‖·‖b‖)`; returns `1.0` if either norm is zero.

### Re-ID magic numbers (tuned — flag before changing)
- **Track-level feature EMA:** `0.7 * old + 0.3 * new`.
- **Person-level canonical EMA:** `0.6 * old + 0.4 * new`, **followed by L2 normalization** (unit sphere).
- **Default cosine-distance tolerance:** `0.005` (recommended range **0.003–0.10**).
- **Spatial weight (bottom half):** `1.2×`.
- These look arbitrary but are tuned. Do not adjust without explicit intent.

### Tracking strategy
- **Detector:** YOLO26, person class only (`classes=[0]`), `conf=0.50`, `iou=0.60`, `verbose=False`, `persist=True`.
- **Tracker:** ByteTrack via a **runtime-generated temp YAML** (in `count_unique_people()`):
  ```yaml
  tracker_type: bytetrack
  track_high_thresh: 0.55
  track_low_thresh: 0.10
  new_track_thresh: 0.65
  track_buffer: {buf}   # video: total frame count; webcam/unknown: 900
  match_thresh: 0.75
  fuse_score: true
  ```
- To change tracker params, edit the `cfg` template string — there is **no checked-in config file**. The temp YAML is deleted on cleanup.

### Person identity assignment (atomic, lock-guarded)
In `_worker()`:
- Feature extraction only runs when `frame_num % sample_rate == 0` and `extract_appearance` returns non-`None`.
- A track is assigned a person **only on first appearance with a valid feature**, guarded by `shared.people_lock`. The match-or-append block must stay atomic to avoid duplicate person IDs across threads.
- Matching: linear scan of `shared.unique_people`; the entry with **minimum** cosine distance that is also `≤ tolerance` wins → that person's canonical vector is EMA-updated, **L2-normalized**, and `track_to_person[tid] = best_idx + 1` (1-based).
- No match → append `feat` (L2-normalized) as a new person.
- **A track keeps its first-assigned person for the entire run** — later feature drift never re-resolves its identity.
- Unconfirmed tracks (no person ID yet) are drawn gray with label `identificando...`.

### Multi-source threading (critical invariants)
- **One YOLO model instance per source** (required for independent ByteTrack state with `persist=True`). **Do not merge model instances across sources.**
- Each source runs in a **daemon thread**; the shared registry (`_Shared`: `unique_people`, `people_lock`, `stop_event`, `error`) is the cross-source bridge — the same physical person in different sources receives the same person ID. **Do not remove `people_lock`.**
- **Main thread owns the GUI:** workers only draw annotations and store `latest_frame`; the main thread calls `cv2.imshow` / `cv2.waitKey`. (In the Streamlit path, workers push to `frame_queue` instead and there is no `cv2` window.) **Do not move `imshow`/`waitKey` into worker threads.**
- `latest_frame` is written by the worker and read by the main thread without a lock — intentional; worst case is a torn read.
- Worker errors are caught, stored in `shared.error`, and re-raised as `RuntimeError` by `count_unique_people()` after the join — prevents silent thread death.
- Invalid boxes (NaN/inf from the tracker) are filtered before use — prevents ByteTrack's `LinAlgError`.
- Shutdown: `Q` key sets `stop_event`; threads joined with `timeout=5`; each `cap.release()`; temp tracker YAMLs unlinked; `cv2.destroyAllWindows()`.

### Color palette
- 8 predefined BGR colors (`COLORS`), assigned cyclically by person ID: `COLORS[(person_id - 1) % 8]`.
- Unconfirmed tracks drawn in gray `(160, 160, 160)`.

---

## CLI Arguments

### `modulos/contador.py` (standalone)
Defined in `NumerarPessoas()`. `video` (positional, `nargs="*"`) and `--webcam` (`action="append"`, `nargs="?"`, `const=0`) **can be freely mixed** — they are **NOT** mutually exclusive. At least one source is required.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `video` (positional) | path(s) | — | One or more video files (`nargs="*"`) |
| `--webcam [IDX]` | int | index `0` | Webcam as source; repeatable (`--webcam 0 --webcam 1`) |
| `--tolerance` | float | `0.005` | Appearance similarity threshold. Help text says `0–0.35`; **not range-enforced**. Recommended `0.003–0.10` |
| `--sample-rate` | int | `3` | Update appearance every N frames |
| `--img-size` | int | `640` | YOLO input resolution. Choices: `320 480 640 768 1024 1280 1536 2048` |
| `--model` | str | `yolo26n.pt` | YOLO model file (`yolo26n`→`s`→`m`→`l`→`x`) or path to a custom `.pt` |
| `--device` | str | auto | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu` |
| `--no-window` | flag | off | Run headless (no display) |

The Streamlit `CounterEngine` uses the same defaults (tolerance 0.005,
sample-rate 3, img-size 640, model `yolo26n.pt`).

### `modulos/cardapio.py` (standalone)
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `caminho_pdf` (positional) | path | `cardapio.pdf` | Menu PDF |
| `--mes` | str | prompts via `input()` | Month to filter (`jan`…`dez`) |

### `modulos/receita.py` (standalone)
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `caminho_pdf` (positional, optional) | path | `arquivos/receita.pdf` (repo root) | Recipes PDF. Outputs `receitas.json`/`receitas.csv` beside it (or by the PDF's stem for custom paths) |

---

## In-Memory State (contador)

```python
# Per source (_Source):
track_features:  dict[int, np.ndarray]  # track_id → appearance vector (running EMA, 324-dim)
track_to_person: dict[int, int]         # track_id → unique person number (1-based)
latest_frame:    object                 # last annotated frame, for main-thread display
frame_num:       int                    # frame counter (drives sample_rate)
done:            threading.Event        # source exhausted / disconnected

# Shared across sources (_Shared):
unique_people:   list[np.ndarray]       # canonical feature representative per person (EMA-updated)
people_lock:     threading.Lock         # guards match-or-append block (atomic)
stop_event:      threading.Event        # cooperative shutdown (Q key or source end)
error:           str | None             # first worker error (re-raised after join)
```

---

## Technologies & Dependencies

### Direct (`requirements.txt`)
| Package | Purpose | Notes |
|---------|---------|-------|
| **opencv-python** | Video I/O, frame processing, HSV, drawing (contador) | `cv2.VideoCapture`, `cv2.calcHist`, `cv2.imshow` |
| **numpy** | Array ops, histogram math (contador) | distance metrics, feature concat |
| **ultralytics** (≥8.4) | YOLO26 detection + ByteTrack tracking (contador) | `YOLO`, `model.track(persist=True)`; yolo26 models need ≥8.3, native `intel:gpu`/`intel:cpu` devices need ≥8.4 |
| **openvino** | Intel hardware acceleration (contador) | GPU/CPU compile via `ov.Core()` |
| **pandas** | Production DataFrame + Excel writer | `pd.DataFrame`, `pd.ExcelWriter` |
| **pdfplumber** | PDF table/text extraction (cardapio, receita) | `page.extract_tables`, `page.extract_text` |
| **openpyxl** | `.xlsx` writer engine used by pandas | |
| **streamlit** (≥1.49) | App UI | `width="stretch"` requires the AdvancedLayouts API (verified: present since 1.49) |

### Dev (`requirements-dev.txt`)
| Package | Purpose |
|---------|---------|
| **pytest** (≥7) | Test runner; config in `pyproject.toml` (`pythonpath=["."]`, `testpaths=["tests"]`) |

### Transitive
| Package | Purpose |
|---------|---------|
| **torch** (PyTorch) | GPU/device detection (CUDA & MPS), YOLO backend — pulled in by ultralytics |
| **torchvision** | Required by ultralytics |
| **PyYAML** | ByteTrack tracker config parsing |
| **lap** | Linear assignment for ByteTrack |

---

## Display Output (contador)

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

## Tolerance Tuning (contador)

- **Too low (e.g. 0.001):** over-counts — legitimate re-matches fail, splitting one person into multiple IDs.
- **Too high (e.g. 0.35):** under-counts — different people merge into one ID.
- **Recommended range:** `0.003–0.10` for typical scenarios.
- **Default (`0.005`):** conservative; works well for distinct clothing colors.

## Performance Trade-offs (contador)
- **Smaller `--img-size` (320):** faster, less accurate detection.
- **Larger `--sample-rate` (3+):** faster, but appearance features go stale between updates.
- **Larger model (`yolo26x`):** more accurate, significantly slower.
- **Model size progression:** `n` (nano, ~5.3 MB) → `s` → `m` → `l` → `x` (most accurate).

---

## Runtime-generated / gitignored artifacts

- `yolo26n.pt` / `yolo26x.pt` etc. — auto-downloaded by ultralytics on first run (gitignored via `*.pt`).
- `*_openvino_model/` — auto-generated on first OpenVINO run (gitignored via `yolo*/`); contains `.xml` / `.bin` / `metadata.yaml`.
- ByteTrack YAML — created in a `tempfile.NamedTemporaryFile` at startup, deleted on cleanup (never committed).
- `*.json` and `*.csv` produced from PDF extraction — gitignored (regenerable from the checked-in PDFs, or from the app's buttons).
- A fresh checkout runs without any of these; **do not commit them or try to "fix" their absence.**

`.gitignore` contents: `*.pt`, `.vscode/`, `venv/`, `yolo*/`, `__pycache__/`, `*.json`, `*.csv`.

---

## Non-obvious Implementation Gotchas (do-not-break list)

1. **OpenVINO device handling** (`load_model`): shim the `openvino.runtime` alias, then pass ultralytics' **native** `device="intel:gpu"|"intel:cpu"` string (requires `ultralytics>=8.4`) to `track()` — never raw OpenVINO names (`"GPU"`/`"CPU"`), which crash `select_device()` with `Invalid CUDA device`. The OpenVINO GPU also needs the system compute driver (`intel-compute-runtime` on Arch) or it won't appear in `ov.Core().available_devices` and requests fall back (with a ⚠️ warning).
2. **ByteTrack config is runtime-generated** (the `cfg` string in `count_unique_people()`). `track_buffer` = total frames for videos with a detectable frame count; `900` for webcams **and** videos with `total <= 0`. Edit the template string, not a config file.
3. **Re-ID magic numbers** (324-dim HSV, 0.7/0.3 track EMA, 0.6/0.4 person EMA + L2-norm, 1.2× bottom weight, tolerance 0.005) are tuned — flag before changing.
4. **Multi-source threading**: one YOLO per source (independent ByteTrack `persist=True` state); shared `unique_people` guarded by `people_lock`; the match-or-append block must stay atomic. Do not remove the lock or merge model instances.
5. **Main thread owns the GUI**: workers draw + store `latest_frame` (or push to `frame_queue`); only the main thread calls `cv2.imshow`/`cv2.waitKey`.
6. **Track identity is sticky**: once `track_to_person[tid]` is set, it is never re-resolved.
7. **CLI source mixing** (`modulos/contador.py` standalone): `video` and `--webcam` are **not** mutually exclusive — they are designed to be combined.
8. **Keep NaN/inf box filtering and worker-error propagation** — they fix real crashes (ByteTrack `LinAlgError`, silent thread death).
9. **`modulos/` never imports the UI** (`app.py`/streamlit). `calculo.py` in particular must stay importable without streamlit — the tests import it directly. `app.py` owns paths (`arquivos/`), caching (`@st.cache_data`), and feedback; `calculo.py` owns the math.
10. **Regeneration is explicit**: the app's extraction buttons always overwrite the JSONs; `carregar_receitas` (the cached wrapper) is cleared after regenerating so stale data never shows. Don't reintroduce silent "JSON exists → skip" no-ops on button clicks.
11. **`modulos/` is a real Python package** (`__init__.py` present); imports are `from modulos import calculo, cardapio, ...` (NOT `import calculo`). Adding new modules requires keeping the package marker.
12. **`calcular_dia` column names are a UI contract** — `tela_resultado` sums `Água (L)` / `kg a produzir` and filters `Avisos == "sem ficha técnica"` by name.

---

## Conventions

- **Commit messages:** Portuguese, casual, no conventional-commits format (see `git log`).
- **Remote:** Codeberg (`codeberg.org/yLipe/Projeto-TCC`), not GitHub.
- **Code style:** comments and console strings in Portuguese; no linter/formatter enforced.
- **Module organization:** app at repo root, all stage modules under `modulos/`, all fixtures/outputs under `arquivos/`, tests under `tests/`.
- **Docs for agents:** `AGENTS.md` is the quick ramp-up; this file is the deep reference.
