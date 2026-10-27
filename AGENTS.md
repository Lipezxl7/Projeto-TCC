# AGENTS.md

TCC (undergrad thesis) — school-meal management: a Streamlit app that extracts the
menu and recipes from PDFs, counts unique people in video (YOLO + ByteTrack + HSV
appearance re-ID), and computes daily food production (kg) and water use (L).

## Commands

```bash
pip install -r requirements.txt   # torch comes transitively via ultralytics;
                                   # for GPU-specific wheels see the README table
streamlit run app.py               # main entry point (pages: Contagem, Resultado)

# Each module also runs standalone:
python -m modulos.contador arquivos/video.mp4 --no-window   # headless count
python -m modulos.cardapio arquivos/cardapio.pdf             # prompts for month on stdin
python -m modulos.receita                                     # broken by default — see Gotchas
```

- **No tests, no linter, no formatter, no CI.** Do not invent `pytest`/`ruff`/`npm`
  commands. Verify changes by running the affected module against the committed
  fixtures in `arquivos/` (`video.mp4`, `video2.mp4`, `cardapio.pdf`, `receita.pdf`);
  use `--no-window` for headless counting. First run auto-downloads `yolo26n.pt`.
- **Python 3.11–3.13.** 3.14 is NOT recommended (no torch/ultralytics/openvino wheels
  yet). The code itself only needs 3.10+ syntax (`match/case`, `X | None`).

## Architecture

- `app.py` — single-file Streamlit app, the only user-facing entry point. The old
  `main.py` orchestrator was removed in the Streamlit refactor.
- `modulos/` — source of truth, no UI imports (never import `app` from here; `app.py`
  imports `from modulos import ...`). Real package (`__init__.py`):
  `contador.py` (YOLO26 + ByteTrack + HSV re-ID, one worker thread per source),
  `cardapio.py` (menu PDF → JSON/CSV), `receita.py` (recipes PDF → JSON/CSV).
- `arquivos/` — committed PDFs/videos (fixtures) plus generated JSONs. The app's
  Contagem page auto-lists videos (`.mp4/.avi/.mov/.mkv`) from this folder.
- Generated artifacts are gitignored (`*.json`, `*.csv`, `*.pt`, `yolo*/`, `venv/`)
  and regenerate on demand — do not commit them or "fix" their absence.

## Gotchas

- `python -m modulos.receita` looks for `modulos/receita.pdf` (`Path(__file__).parent`)
  and writes `receitas.json/csv` into `modulos/` — it exits 1 with the committed layout.
  The supported path is the app's "Extrair receitas do PDF" button or calling
  `receita.extract_recipes("arquivos/receita.pdf")` programmatically. Don't "fix" the
  standalone `main()` without preserving this.
- `cardapio.executar_extracao` prompts via `input()` when `mes` is `None` — the
  standalone CLI has no `--mes` flag. In headless runs pipe the month in
  (`echo jun | python -m modulos.cardapio ...`) or pass `mes=` programmatically.
- Extraction results are cached: `gerar_cardapio`/`gerar_receitas` in `app.py` are
  no-ops while the JSON exists, and `carregar_receitas` is `@st.cache_data` with the
  path arg excluded from the cache key (leading underscore) — delete `arquivos/*.json`
  and restart the app to force re-extraction.
- `app.py` imports `modulos.contador` lazily (`_get_contador()`) because
  torch/ultralytics are heavy — keep that import inside functions.
- Streamlit counting runs in a daemon thread (`CounterEngine`): frames flow through
  `queue.Queue(maxsize=1)` (a full queue drops frames — intentional), `status_cb`
  feeds the live count, `stop_event` stops the run. The UI re-renders in ~4s slices
  via `st.rerun()` so buttons stay clickable.

## contador.py invariants (do not break)

- **OpenVINO**: for `openvino:*` devices, `load_model()` returns `(model, None)` and
  that `None` is passed to `model.track()` on purpose — never forward the OpenVINO
  device string to `track()` (ultralytics' `select_device()` reads `"GPU"` as CUDA and
  raises `Invalid CUDA device`). Keep `_garantir_openvino_runtime()`, which shims the
  `openvino.runtime` alias removed in OpenVINO 2025+.
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

`CONTEXT.md` is the deep reference (function maps, CLI tables, threading state) but is
**partially stale**: it still documents the removed `main.py` and claims Python 3.14+ is
mandatory. When docs conflict, trust the code — order: `modulos/contador.py` > `app.py`
> `CONTEXT.md` > `README.md`. `README.md` matches the current Streamlit app.
