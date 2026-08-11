# CONTEXT.md

Authoritative context file for this repository. Read this first.
Source of truth order when anything conflicts: **`modulos/contador.py` > `main.py` > `CONTEXT.md` > `README.md`**.

---

## Project

**TCC — Regulamento Alimentar Escolar** — a Python pipeline that integrates **four stages** for school-meal management:

1. **Cardápio extraction** (`modulos/cardapio.py`) — reads a menu PDF and produces structured JSON/CSV of dates + dishes.
2. **Receitas extraction** (`modulos/receita.py`) — reads a recipes PDF and produces structured JSON/CSV of ingredients, servings, and cooking instructions.
3. **Person counting** (`modulos/contador.py`) — counts **unique individuals** across video/webcam frames using **YOLO26** (person detection), **ByteTrack** (multi-object tracking), and **HSV-histogram appearance re-identification**. Handles occlusions, re-entries, and track fragmentation so the same physical person receives a consistent ID — even across **multiple simultaneous sources** (videos + webcams) via a shared person registry and cross-source re-ID.
4. **Production calculation for Power BI** (`main.py`) — cross-references menu + recipes via fuzzy matching (with optional manual mapping), computes water and total-to-produce per dish, and writes a `.xlsx` ready for Power BI.

- **Type:** Undergraduate thesis (Trabalho de Conclusão de Curso — TCC).
- **Language of code comments / labels / console output:** **Portuguese**. `CONTEXT.md` and `README.md` are also in Portuguese.
- **Shape:** Multi-module orchestration — `main.py` (orchestrator, ~440 lines) imports from `modulos/` (a Python package containing `cardapio.py`, `receita.py`, `contador.py`). See "Structure" below.
- **Repository:** https://codeberg.org/yLipe/Projeto-TCC (Codeberg, **not** GitHub).
- **Python:** 3.14+ required (uses `match/case`, PEP 604 `str | None`).

---

## Structure

```
Projeto-TCC/
├── main.py                  # Orquestrador de 4 etapas (cardápio + receitas + contagem + PBI)
├── modulos/
│   ├── __init__.py          # package marker (empty)
│   ├── cardapio.py          # Extração do cardápio (PDF -> JSON/CSV)
│   ├── receita.py           # Extração de receitas (PDF -> JSON/CSV)
│   └── contador.py          # Contagem de pessoas unicas (~450 linhas, single-file)
├── arquivos/                # Fixtures e saídas
│   ├── cardapio.pdf
│   ├── receita.pdf
│   ├── video.mp4
│   ├── video2.mp4
│   ├── i2v6ti.mp4
│   ├── planilha.xlsx        # exemplo de saída PBI
│   └── TCC_Regulamento_Alimentar (1).docx
├── requirements.txt
├── .gitignore
├── CONTEXT.md
└── README.md
```

`main.py` imports the modules via `from modulos import cardapio, receita, contador` (`main.py:51`). Each module under `modulos/` is also runnable standalone via `python -m modulos.<name>`.

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

### GPU extras (only needed for the counting stage)
- **NVIDIA:** PyTorch built with CUDA — `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130`.
- **Apple Silicon:** `pip install torch` (MPS auto-enables with PyTorch 2.12+).
- **Intel:** OpenVINO is already in `requirements.txt` — nothing extra to install.
- **Generic CPU:** Always works as a fallback; no extras.

### Runtime requirements
- PDF fixtures (`arquivos/cardapio.pdf`, `arquivos/receita.pdf`) for stages 1–2.
- A video file (any OpenCV-supported format) or a connected webcam for stage 3.
- A display server (X11/Wayland) unless using `--no-window` (stage 3).
- GPU drivers appropriate for the selected `--device` (stage 3).

---

## Commands

### Full pipeline (orchestrator)

```bash
# Pipeline completo (manhã — fundamental)
python main.py --cardapio-pdf arquivos/cardapio.pdf --mes jun \
    --receita-pdf arquivos/receita.pdf --video arquivos/video.mp4 \
    --etapa fund --alunos 300 --data 12-05 --no-window

# Reaproveitando JSONs já extraídos
python main.py --skip-cardapio --skip-receitas --skip-contador \
    --cardapio-json arquivos/cardapio.json --receitas-json arquivos/receitas.json \
    --etapa med --alunos 200 --data 12-05

# Só contagem
python main.py --skip-cardapio --skip-receitas --skip-producao \
    --video arquivos/video.mp4 --device cuda
```

### Per-stage (standalone)

- **Cardápio:** `python -m modulos.cardapio arquivos/cardapio.pdf`
- **Receitas:** `python -m modulos.receita` (uses `arquivos/receita.pdf` by internal default)
- **Contagem — single video:** `python -m modulos.contador arquivos/video.mp4`
- **Contagem — webcam (default index 0):** `python -m modulos.contador --webcam`
- **Contagem — second webcam:** `python -m modulos.contador --webcam 1`
- **Contagem — multi-source (one daemon thread per source, shared cross-source re-ID):**
  - `python -m modulos.contador arquivos/a.mp4 arquivos/b.mp4` — two videos
  - `python -m modulos.contador arquivos/video.mp4 --webcam 0` — video + webcam
  - `python -m modulos.contador --webcam 0 --webcam 1` — two webcams
  - `python -m modulos.contador arquivos/a.mp4 arquivos/b.mp4 --webcam 0` — mix

### Verification & tooling status
- **There is NO test suite, NO linter, NO typecheck, NO formatter, and NO CI.**
- Do **not** fabricate `pytest` / `ruff` / `npm run` / `tox` invocations — there is nothing to run.
- Verify changes by executing the script against the committed `arquivos/video.mp4` / `arquivos/video2.mp4` / `arquivos/i2v6ti.mp4` fixtures — or with `--no-window` for headless runs.

---

## Architecture

### `main.py` — orchestrator (`main.py:1`)

Four-stage pipeline wired by `main()` (`main.py:399`). Each stage can be skipped via its `--skip-*` flag, allowing re-use of cached JSONs from previous runs. Defaults point at `arquivos/` so a fresh checkout runs end-to-end without arguments beyond `--etapa`/`--alunos`/`--data`.

Key functions:

| Function | Location | Purpose |
|----------|----------|---------|
| `formatar_data_para_cardapio(data_str)` | `main.py:56` | Converts `DD-MM` → `DD/mmm` (the JSON's date format) without `datetime`. |
| `normalizar(texto)` | `main.py:90` | ASCII-folds, uppercases, collapses whitespace — used for fuzzy matching. |
| `nome_limpo_receita(nome)` | `main.py:97` | Strips trailing qualifiers ("`, - (Receita ...`") from recipe names. |
| `parse_porcao_gramas(texto)` | `main.py:103` | Extracts the porção (g) from a free-text string; prefers "(N g cozido)". |
| `carregar_mapeamento_manual(caminho)` | `main.py:129` | Loads `mapeamento_manual.json` (optional prato→receita override). |
| `encontrar_receita(prato, receitas, manual, por_nome)` | `main.py:138` | Matches a prato to a receita: manual map first, then `difflib` ratio + bonus heuristics; `LIMIAR_MATCH_MINIMO = 0.55`. |
| `extrair_agua_base_g(receita_dict)` | `main.py:181` | Sums the `quantidade_g_ml` of any ingrediente whose name contains "AGUA". |
| `calcular_producao_pbi(dados_cardapio, receitas, alunos, etapa, manual, data_str)` | `main.py:193` | Builds the PBI DataFrame: `fator = (alunos*porcao)/rendimento`, `agua_total_l = fator*agua_base/1000`, `total_a_fazer_kg = (alunos*porcao)/1000`. Filters by `data_str`. |
| `gerar_excel_pbi(df, caminho_saida)` | `main.py:279` | Writes `.xlsx` with `openpyxl`, frozen header, auto-width columns. |
| `rodar_cardapio(...)` | `main.py:294` | Stage-1 wrapper: calls `modulos.cardapio.executar_extracao`. |
| `rodar_receitas(caminho_pdf)` | `main.py:305` | Stage-2 wrapper: calls `modulos.receita.extract_recipes`, saves JSON/CSV beside the PDF. |
| `rodar_contador(...)` | `main.py:317` | Stage-3 wrapper: builds sources, calls `contador.detect_device` + `contador.count_unique_people`. |
| `parse_args()` | `main.py:360` | argparse — see CLI table below. |
| `main()` | `main.py:399` | Entry point: wires stages 1–4 according to `--skip-*` flags. |

Constants: `PORCAO_FUND_FALLBACK_G = 120`, `PORCAO_MED_FALLBACK_G = 140`, `LIMIAR_MATCH_MINIMO = 0.55` (`main.py:84`–`87`).

### `modulos/contador.py` — person counter (single-file, ~450 lines)

```
modulos/contador.py (single file – all counting logic, ~450 lines)
├── Device Selection Layer
│   ├── auto_device_selection()   → CUDA → MPS → Intel GPU → Intel CPU → CPU      [modulos/contador.py:16]
│   └── detect_device()            → match/case on user pref; fallback to auto      [modulos/contador.py:31]
├── Model Loading Layer
│   └── load_model()               → YOLO load; optional OpenVINO export + compile   [modulos/contador.py:53]
├── Appearance Features Layer
│   ├── extract_appearance()       → 360-dim HSV histogram (48×96, top/bottom split, V-chan + 1.2× bottom) [modulos/contador.py:122]
│   └── cosine_dist()              → 1 − normalized dot product                      [modulos/contador.py:144]
├── Visualization Layer
│   ├── COLORS                     → 8-color BGR palette (cyclic by person ID)       [modulos/contador.py:106]
│   ├── draw_box()                 → color-coded box + label (or gray if unconfirmed)[modulos/contador.py:152]
│   └── draw_overlay()             → semi-transparent "Pessoas unicas: N" panel       [modulos/contador.py:172]
├── Multi-Source / Threading Layer
│   ├── _Shared (dataclass)        → shared registry: unique_people + lock + stop    [modulos/contador.py:190]
│   ├── _Source (dataclass)        → per-source state: model, tracker, dicts, cap    [modulos/contador.py:197]
│   ├── _worker()                  → per-source daemon thread main loop              [modulos/contador.py:214]
│   └── _print_status()            → throttled combined progress line (≤10 Hz)       [modulos/contador.py:282]
├── Core Orchestration
│   └── count_unique_people()      → builds sources, spawns threads, owns GUI loop   [modulos/contador.py:294]
└── CLI Entry Point
    ├── NumerarPessoas()           → argparse, validation, device detect, summary    [modulos/contador.py:381]
    └── __main__                   → prints final count                              [modulos/contador.py:450]
```

**Note:** The CLI entry function is `NumerarPessoas()` (renamed from `main()` in commit `9dbac85`) — but only when running `modulos.contador` directly; the orchestrator in `main.py` calls `count_unique_people()` and `detect_device()` programmatically and bypasses `NumerarPessoas()`.

### `modulos/cardapio.py` — cardápiopio extractor

Reads `arquivos/cardapio.pdf` (or any PDF path) with `pdfplumber`. For each page, looks for cells containing `/<mes>` (e.g. `/jun`), then walks 3 rows down to the refeição row, strips parenthesised ingredient lists, fixes line breaks in compound dish names (lines ending in `COM|DE|AO|A|EM|E|OU` get concatenated with the next), splits on `E|OU|,`, uppercases, and deduplicates per date. Output: a list of `{"data": "DD/mmm", "pratos": ["...", "..."]}` dicts, saved as both JSON and CSV beside the PDF.

Key functions:
- `executar_extracao(caminho_pdf, arquivo_saida, mes, salvar_json, salvar_csv)` (`modulos/cardapio.py:36`) — main extractor.
- `save_json(dados, path)` / `save_csv(dados, path)` (`modulos/cardapio.py:19`, `:25`) — writers.

If `mes` is `None` it prompts via `input()`. Run standalone: `python -m modulos.cardapio <pdf>`.

### `modulos/receita.py` — recipe extractor

Reads `arquivos/receita.pdf` with `pdfplumber`. For each page that contains `Nome da preparação:`, extracts the recipe name, etapa de ensino, tipo de atendimento, faixa etária, modo de preparo, and a footer block (rendimento, porção fundamental, porção EJA/E.M., tempo de preparo, medidas caseiras). The ingredientes are parsed from the page's tables: rows between the "INGREDIENTE" header and the footer. Each ingredient is `{ingrediente, quantidade_g_ml, medida_caseira}`.

Key functions:
- `extract_recipes(pdf_path)` (`modulos/receita.py:161`) — main extractor; returns a list of recipe dicts.
- `parse_rendimento_gramas(texto)` (`modulos/receita.py:82`) — converts `12 kg` / `12 litros` / `12000 g` → grams (kg/litros × 1000). Returns `None` when the unit is `alunos` (no weight).
- `parse_footer_row(row_text, footer)` (`modulos/receita.py:30`) — regex-driven inference of the footer fields, fairly tolerant of spacing/typography.
- `save_json(recipes, path)` / `save_csv(recipes, path)` (`modulos/receita.py:216`, `:222`) — writers.
- `main()` (`modulos/receita.py:260`) — standalone entry that uses `Path(__file__).parent / "receita.pdf"` (i.e. expects the file at the module's own directory). **When invoked via `python -m modulos.receita`, that resolves to `modulos/receita.pdf`, not `arquivos/receita.pdf`** — prefer passing via `main.py` to use the `arquivos/` default.

---

## contador.py — Key Concepts & Implementation Details

### Device abstraction
- **Priority chain:** CUDA (NVIDIA) → MPS (Apple Silicon) → OpenVINO Intel GPU → OpenVINO Intel CPU → plain CPU.
- **CLI input → internal string mapping:** `intel:gpu` → `openvino:GPU`; `intel:cpu` → `openvino:CPU`. Other values (`cuda`, `mps`, `cpu`) pass through unchanged.
- **Fallback:** If a user-preferred device is unavailable, `detect_device()` silently falls back to `auto_device_selection()`.
- `detect_device()` reads `ov.Core().available_devices` once per call.

### OpenVINO handling (critical — do not "simplify")
For `openvino:*` devices, `load_model()` (`modulos/contador.py:53`):
1. Exports the `.pt` model to OpenVINO IR format **only on first run** (cached in `{stem}_openvino_model/`, auto-discovered via `Path.glob("*.xml")`).
2. Explicitly compiles the IR via `ov.Core().compile_model(xml, ov_target)` and prints `EXECUTION_DEVICES` + `FULL_DEVICE_NAME` for verification. On failure it prints a warning and continues (intending OpenVINO's default CPU).
3. Returns `YOLO(ov_path)` with **`device_para_track = None`**.

The returned `None` is passed to `model.track()` (see `_worker`, `modulos/contador.py:214`). This is the actual fix for the CUDA crash: ultralytics' `select_device()` would otherwise interpret `"GPU"` as a CUDA device and raise `Invalid CUDA device`. **Do not forward the OpenVINO device string to `track()`** and do not merge this path with the non-OpenVINO branch. The explicit pre-compile is primarily for verification/early-failure surfacing — the `compiled` object is not reused; ultralytics re-loads `YOLO(ov_path)` internally.

### Appearance-based re-identification
`extract_appearance(crop)` (`modulos/contador.py:122`):
- Returns `None` if `crop` is `None`, empty, smaller than **10 px** in either dimension, or with extreme aspect ratio (`w/h < 0.15` or `w/h > 6.0`).
- Resizes crop to **48×96** (width×height), converts to HSV.
- Splits into **top half** (`hsv[:48]`) and **bottom half** (`hsv[48:]`) — i.e. upper/lower body.
- Per region: 2D H-S histogram with **H=18 bins** (range 0–180), **S=8 bins** (range 0–256), normalized via `cv2.normalize` (default `NORM_MINMAX`) then flattened → 144 dims/region, **plus** a 1D V histogram with **18 bins** (range 0–256), normalized → 18 dims/region.
- Bottom-half features are **spatially weighted by 1.2×** (bottom region is more pose-invariant).
- Concatenates both regions → **360-dimensional** feature vector (168 dims top + 180 dims bottom including the 1.2× weight).

`cosine_dist(a, b)` (`modulos/contador.py:144`): `1 − dot(a,b)/(‖a‖·‖b‖)`; returns `1.0` if either norm is zero.

### Re-ID magic numbers (tuned — flag before changing)
- **Track-level feature EMA:** `0.7 * old + 0.3 * new` (`modulos/contador.py:244`).
- **Person-level canonical EMA:** `0.6 * old + 0.4 * new` (`modulos/contador.py:258`), **followed by L2 normalization** to keep canonical vectors on the unit sphere.
- **Default cosine-distance tolerance:** `0.005` (recommended range **0.003–0.10**).
- **Spatial weight (bottom half):** `1.2×` — bottom-body features are more stable across poses.
- These look arbitrary but are tuned. Do not adjust without explicit intent.

### Tracking strategy
- **Detector:** YOLO26, person class only (`classes=[0]`), `conf=0.50`, `iou=0.60`, `verbose=False`, `persist=True`.
- **Tracker:** ByteTrack via a **runtime-generated temp YAML** (`modulos/contador.py:306`):
  ```yaml
  tracker_type: bytetrack
  track_high_thresh: 0.55      # high-confidence threshold
  track_low_thresh: 0.10      # low-confidence threshold
  new_track_thresh: 0.65      # new-track initialization
  track_buffer: {buf}         # video: total frame count; webcam/unknown: 900
  match_thresh: 0.75          # association threshold
  fuse_score: true            # combine detection + track scores
  ```
- **`track_buffer` (`buf`) logic** (`modulos/contador.py:300`): `buf = total if total > 0 and not is_webcam else 900`. So a video whose frame count is detectable gets `buf = total frames` (tracks never expire mid-video); webcams **and** videos with `total <= 0` get `buf = 900`.
- To change tracker params, edit the `cfg` template string in `count_unique_people()` — there is **no checked-in config file**. The temp YAML is deleted on cleanup.

### Person identity assignment (atomic, lock-guarded)
In `_worker()` (`modulos/contador.py:249`):
- Feature extraction only runs when `frame_num % sample_rate == 0` and `extract_appearance` returns non-`None`.
- A track is assigned a person **only on first appearance with a valid feature**, guarded by `shared.people_lock`. The match-or-append block must stay atomic to avoid duplicate person IDs across threads.
- Matching: linear scan of `shared.unique_people`; entry with the **minimum** cosine distance that is also `≤ tolerance` wins → that person's canonical vector is EMA-updated, **L2-normalized**, and `track_to_person[tid] = best_idx + 1` (1-based). This avoids a borderline match on an early entry stealing the track from a closer person later in the list.
- No match → append `feat` (L2-normalized) as a new person; `track_to_person[tid] = len(unique_people)`.
- **A track keeps its first-assigned person for the entire run** — the `if tid not in track_to_person` guard means later feature drift on that track never re-resolves its identity.
- Unconfirmed tracks (no person ID yet) are drawn gray with label `identificando...`.

### Multi-source threading (critical invariants)
- **One YOLO model instance per source** (`modulos/contador.py:294`, `load_model` called per source). Required for independent ByteTrack state with `persist=True`. **Do not merge model instances across sources.**
- Each source runs in a **daemon thread** (`modulos/contador.py:324`); `persist=True` keeps ByteTrack state alive across frames within that source.
- The shared registry (`_Shared`: `unique_people`, `people_lock`, `stop_event`) is the cross-source bridge — the same physical person in different sources receives the same person ID. **Do not remove `people_lock`.**
- **Main thread owns the GUI:** workers only draw annotations and store `latest_frame`; the main thread calls `cv2.imshow` / `cv2.waitKey` (`modulos/contador.py:335`). This avoids per-platform OpenCV GUI threading quirks. **Do not move `imshow`/`waitKey` into worker threads.**
- `latest_frame` is written by the worker and read by the main thread without a lock — intentional; worst case is a torn read, which is acceptable.
- Shutdown: `Q` key sets `stop_event`; workers exit; threads joined with `timeout=5`; each `cap.release()`; temp tracker YAMLs `os.unlink`'d (errors ignored); `cv2.destroyAllWindows()`.

### Color palette
- 8 predefined BGR colors (`COLORS`, `modulos/contador.py:106`), assigned cyclically by person ID: `COLORS[(person_id - 1) % 8]`.
- Unconfirmed tracks drawn in gray `(160, 160, 160)`.

---

## CLI Arguments

### `main.py` (orchestrator)
Defined in `parse_args()` (`main.py:360`). Stage-skip flags let you re-use cached JSONs (stages 1–2) or skip the count (stage 3) or skip the PBI build (stage 4).

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--cardapio-pdf` | str | `arquivos/cardapio.pdf` | PDF do cardápio |
| `--mes` | str | asks via `input()` | Mês a filtrar (`jan`, `fev`, ..., `dez`) |
| `--skip-cardapio` | flag | off | Pula extração do cardápio, usa `--cardapio-json` |
| `--cardapio-json` | str | `arquivos/cardapio.json` | JSON do cardápio (entrada/saída) |
| `--receita-pdf` | str | `arquivos/receita.pdf` | PDF das receitas |
| `--skip-receitas` | flag | off | Pula extração das receitas, usa `--receitas-json` |
| `--receitas-json` | str | `arquivos/receitas.json` | JSON das receitas (entrada/saída) |
| `--video` | path(s) | `[]` | Um ou mais arquivos de vídeo (`nargs="*"`) |
| `--webcam [IDX]` | int | índice 0 | Webcam como fonte; repetitível |
| `--skip-contador` | flag | off | Pula a etapa de contagem |
| `--tolerance` | float | `0.005` | Tolерância da re-ID (0.003–0.10) |
| `--sample-rate` | int | `1` | Atualiza aparência a cada N frames |
| `--img-size` | int | `640` | Resolução YOLO: `320 480 640 768 1024 1280 1536 2048` |
| `--model` | str | `yolo26x.pt` | Modelo YOLO (`yolo26n`→`s`→`m`→`l`→`x`) |
| `--device` | str | auto | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu` |
| `--no-window` | flag | off | Modo headless |
| `--etapa` | str | **obrigatório**¹ | `fund` (fundamental) ou `med` (médio/EJA) |
| `--alunos` | int | **obrigatório**¹ | Quantidade de alunos |
| `--data` | str | **obrigatório**¹ | Data no formato `DD-MM` |
| `--skip-producao` | flag | off | Pula a planilha PBI |
| `--mapeamento` | str | `arquivos/mapeamento_manual.json` | JSON com mapeamento manual prato→receita (opcional) |
| `--no-json` | flag | off | Não salva JSONs das extrações |
| `--no-csv` | flag | off | Não salva CSVs das extrações |
| `--output` | str | `arquivos/planilha.xlsx` | Planilha de saída PBI |

¹ `--etapa`, `--alunos` e `--data` são `required=True` no argparse e sempre precisam ser passados, mesmo em runs que pulam a etapa 4 (ex.: `--skip-producao`). São usados apenas por `calcular_producao_pbi()` — em runs só de contagem passe valores placeholder (ex.: `--etapa fund --alunos 0 --data 01-01`). Para torná-los condicionais, valide em `main()` ao invés de usar `required=True`.

### `modulos/contador.py` (standalone)
Defined in `NumerarPessoas()` (`modulos/contador.py:381`). `video` (positional, `nargs="*"`) and `--webcam` (`action="append"`, `nargs="?"`, `const=0`) **can be freely mixed** — they are **NOT** mutually exclusive. At least one source is required.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `video` (positional) | path(s) | — | One or more video files (`nargs="*"`) |
| `--webcam [IDX]` | int | index `0` | Webcam as source; repeatable (`--webcam 0 --webcam 1`) |
| `--tolerance` | float | `0.005` | Appearance similarity threshold. Help text says `0–0.35`; **not range-enforced**. Recommended `0.003–0.10` |
| `--sample-rate` | int | `1` | Update appearance every N frames (`1` = every frame) |
| `--img-size` | int | `640` | YOLO input resolution. Choices: `320 480 640 768 1024 1280 1536 2048` |
| `--model` | str | `yolo26n.pt` | YOLO model file (`yolo26n`→`s`→`m`→`l`→`x`) or path to a custom `.pt` |
| `--device` | str | auto | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu`. Auto-detected when omitted |
| `--no-window` | flag | off | Run headless (no display) |

### `--device` values & auto-detect chain
`cuda | mps | intel:gpu | intel:cpu | cpu` (default: auto-detect via CUDA → MPS → Intel GPU → Intel CPU → CPU).

---

## In-Memory State (contador)

```python
# Per source (_Source):
track_features:  dict[int, np.ndarray]  # track_id → appearance vector (running EMA, 360-dim)
track_to_person: dict[int, int]         # track_id → unique person number (1-based)
latest_frame:    object                 # last annotated frame, for main-thread display
frame_num:       int                   # frame counter (drives sample_rate)
done:            threading.Event        # source exhausted / disconnected

# Shared across sources (_Shared):
unique_people:   list[np.ndarray]       # canonical feature representative per person (EMA-updated)
people_lock:     threading.Lock         # guards match-or-append block (atomic)
stop_event:      threading.Event        # cooperative shutdown (Q key or source end)
```

---

## Technologies & Dependencies

### Direct (`requirements.txt`)
| Package | Purpose | Notes |
|---------|---------|-------|
| **opencv-python** | Video I/O, frame processing, HSV, drawing (contador) | `cv2.VideoCapture`, `cv2.calcHist`, `cv2.imshow` |
| **numpy** | Array ops, histogram math (contador) | distance metrics, feature concat |
| **ultralytics** | YOLO26 detection + ByteTrack tracking (contador) | `YOLO`, `model.track(persist=True)` |
| **openvino** | Intel hardware acceleration (contador) | GPU/CPU compile via `ov.Core()` |
| **pandas** | Production DataFrame + Excel writer (main.py) | `pd.DataFrame`, `pd.ExcelWriter` |
| **pdfplumber** | PDF table/text extraction (cardapio.py, receita.py) | `pdfplumber.open`, `page.extract_tables`, `page.extract_text` |

### Transitive
| Package | Purpose |
|---------|---------|
| **torch** (PyTorch) | GPU/device detection (CUDA & MPS), YOLO backend |
| **torchvision** | Required by ultralytics |
| **PyYAML** | ByteTrack tracker config parsing |
| **lap** | Linear assignment for ByteTrack |
| **openpyxl** | `.xlsx` writer engine used by pandas |

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

- `yolo26n.pt` / `yolo26x.pt` etc. — auto-downloaded by ultralytics on first run (gitignored via `*.pt`, ~5.3 MB – ~20 MB).
- `*_openvino_model/` — auto-generated on first OpenVINO run (gitignored via `yolo*/`); contains `.xml` / `.bin` / `metadata.yaml`.
- ByteTrack YAML — created in a `tempfile.NamedTemporaryFile` at startup, deleted on cleanup (never committed).
- `*.json` and `*.csv` produced from PDF extraction — gitignored (regenerable from the checked-in PDFs).
- A fresh checkout runs without any of these; **do not commit them or try to "fix" their absence.**

`.gitignore` contents: `*.pt`, `.vscode/`, `venv/`, `yolo*/`, `__pycache__/`, `*.json`, `*.csv`.

---

## Non-obvious Implementation Gotchas (do-not-break list)

1. **OpenVINO device handling** (`load_model`, `modulos/contador.py:53`): compile via `ov.Core().compile_model()` for verification; pass `device=None` to `track()`. Do **not** forward the OpenVINO device string to `track()` — ultralytics' `select_device()` would interpret `"GPU"` as CUDA and crash with `Invalid CUDA device`.
2. **ByteTrack config is runtime-generated** (`modulos/contador.py:306`). `track_buffer = total frames` for videos with a detectable frame count; `900` for webcams **and** videos with `total <= 0`. Edit the `cfg` template string, not a config file.
3. **Re-ID magic numbers** (360-dim HSV, 0.7/0.3 track EMA, 0.6/0.4 person EMA + L2-norm, 1.2× bottom weight, tolerance 0.005) are tuned — flag before changing.
4. **Multi-source threading**: one YOLO per source (independent ByteTrack `persist=True` state); shared `unique_people` guarded by `people_lock`; the match-or-append block must stay atomic. Do not remove the lock or merge model instances.
5. **Main thread owns the GUI**: workers draw + store `latest_frame`; only the main thread calls `cv2.imshow`/`cv2.waitKey`. Do not move these into worker threads.
6. **Track identity is sticky**: once `track_to_person[tid]` is set, it is never re-resolved, even as features drift.
7. **CLI source mixing** (`modulos/contador.py` standalone): `video` and `--webcam` are **not** mutually exclusive — they are designed to be combined.
8. **`modulos.receita`'s standalone `main()`** uses `Path(__file__).parent / "receita.pdf"` — i.e. expects the PDF inside `modulos/`, which will fail via `python -m modulos.receita`. Prefer invoking via `python main.py` (which uses the `--receita-pdf` default of `arquivos/receita.pdf`) or pass the path explicitly. **Do not "fix" the standalone main to look in `arquivos/` without considering that the orchestrator is the supported path.**
9. **`main.py` defaults to `arquivos/` paths** — moving the PDFs again will break out-of-the-box runs. Keep fixtures in `arquivos/` or update all `--*-pdf` / `--*-json` / `--output` / `--mapeamento` defaults together.
10. **`modulos/` is a real Python package** (`__init__.py` present); imports inside `main.py` are `from modulos import cardapio, receita, contador` (NOT `import cardapio`). Adding new modules requires keeping the package marker.

---

## Conventions

- **Commit messages:** Portuguese, casual, no conventional-commits format (see `git log`).
- **Remote:** Codeberg (`codeberg.org/yLipe/Projeto-TCC`), not GitHub.
- **Code style:** comments and console strings in Portuguese; no linter/formatter enforced.
- **Module organization:** orchestrator at repo root, all stage modules under `modulos/`, all fixtures/outputs under `arquivos/`.
