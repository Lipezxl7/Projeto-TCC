import cv2
import numpy as np
import argparse
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
import torch
import openvino as ov
from ultralytics import YOLO

# Auto selecao baseada no que previsivelmente e o mais top tlgd.
def auto_device_selection(intel_available_devices: list) -> tuple[str, str]:
    # Sequencia CUDA -> MPS -> Intel GPU -> Intel CPU -> CPU

    if torch.cuda.is_available():
        return "cuda", f"NVIDIA GPU – {torch.cuda.get_device_name(0)} - Automatico"
    elif torch.backends.mps.is_built() and torch.backends.mps.is_available():
        return "mps", "Apple Silicon (MPS) - Automatico"
    elif "GPU" in intel_available_devices:
        return "openvino:GPU", "Intel GPU (OpenVINO) - Automatico"
    elif "CPU" in intel_available_devices:
        return "openvino:CPU", "Intel CPU (OpenVINO) - Automatico"

    return "cpu", "CPU"

# Deteccao de dispotivo insano feito pelo nego malandro.
def detect_device(preferred: str | None = None) -> tuple[str, str]:
    intel_available_devices = ov.Core().available_devices

    if preferred:
        p = preferred.lower()

        match p:
            case "cuda" if torch.cuda.is_available():
                return "cuda", f"NVIDIA GPU – {torch.cuda.get_device_name(0)}"
            case "mps" if torch.backends.mps.is_built() and torch.backends.mps.is_available():
                return "mps", "Apple Silicon (MPS)"
            case "intel:gpu" if "GPU" in intel_available_devices:
                return "openvino:GPU", "Intel GPU (OpenVINO)"
            case "intel:cpu" if "CPU" in intel_available_devices:
                return "openvino:CPU", "Intel CPU (OpenVINO)"
            case "cpu":
                return "cpu", "CPU"
            case _:
                return auto_device_selection(intel_available_devices)

    return auto_device_selection(intel_available_devices)

def load_model(device: str, model_name: str = "yolo26n.pt"):
    """
    Carrega o modelo YOLO correto para o device.
    Para Intel/OpenVINO: exporta yolo26n para o formato OpenVINO na
    primeira execucao e compila diretamente via openvino.Core() apontando
    para o device correto (CPU ou GPU Intel).

    Retorna (model, device_para_track):
      - OpenVINO: device_para_track = None  (nao passa ao track, evita erro CUDA)
      - Demais:   device_para_track = device string normal
    """

    if device.startswith("openvino:"):
        ov_target = device.split(":", 1)[1]   # "CPU" ou "GPU"
        stem    = model_name.replace(".pt", "")
        ov_path = f"{stem}_openvino_model"

        if not os.path.isdir(ov_path):
            print("  Exportando modelo para OpenVINO (so na 1a execucao)...")
            YOLO(model_name).export(format="openvino", half=False, dynamic=True)
            print("  Exportacao concluida.\n")

        # Compila o modelo diretamente via OpenVINO Core apontando para o
        # device correto (CPU ou GPU Intel). Isso e feito ANTES do ultralytics
        # tentar validar o device string via select_device(), que interpretaria
        # "GPU" como um device CUDA invalido e lancaria 'Invalid CUDA device'.
        try:
            core     = ov.Core()
            xml_file = next(Path(ov_path).glob("*.xml"))
            compiled = core.compile_model(str(xml_file), ov_target)

            # Verificacao: confirma qual device o OpenVINO realmente usou
            actual_device = compiled.get_property("EXECUTION_DEVICES")
            full_name     = core.get_property(ov_target, "FULL_DEVICE_NAME")
            print(f"  OpenVINO device solicitado : {ov_target}")
            print(f"  OpenVINO device em uso     : {actual_device}")
            print(f"  Nome completo do hardware  : {full_name}")

        except Exception as e:
            print(f"  Aviso: nao foi possivel compilar para {ov_target}: {e}")
            print("  Usando OpenVINO com device padrao (CPU).")

        # None como device: model.track() nao recebera "GPU"/"CPU" e nao
        # tentara resolver via PyTorch/CUDA, evitando o erro que eu tava tentando resolver a 1 hora.
        return YOLO(ov_path), None

    return YOLO(model_name), device


# ──────────────────────────────────────────────
#  PALETA DE CORES (BGR) – uma por pessoa única
# ──────────────────────────────────────────────

COLORS = [
    ( 80, 200,  80),  # verde
    ( 80, 120, 220),  # azul
    (220, 160,  40),  # laranja
    (160,  80, 220),  # roxo
    ( 40, 200, 200),  # ciano
    (220,  80, 180),  # rosa
    (220, 200,  40),  # amarelo
    (100, 180, 255),  # azul claro
]

# ──────────────────────────────────────────────
# APARÊNCIA: histograma HSV em duas regiões
# ──────────────────────────────────────────────
# Aqui foi IA pura, nao me leve a mal isso valeu mais a pena que usar osnet.

def extract_appearance(crop: np.ndarray) -> np.ndarray | None:
    if crop is None or crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
        return None
    img = cv2.resize(crop, (48, 96))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    def hist(region):
        h = cv2.calcHist([region], [0, 1], None, [18, 8], [0, 180, 0, 256])
        cv2.normalize(h, h)
        return h.flatten()

    return np.concatenate([hist(hsv[:48]), hist(hsv[48:])])


def cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return 1.0 if denom == 0 else float(1 - np.dot(a, b) / denom)

# ──────────────────────────────────────────────
#  DISPLAY
# ──────────────────────────────────────────────

def draw_box(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int,
             person_id: int, confirmed: bool) -> None:
    """Desenha bounding box e label da pessoa no frame."""
    color = COLORS[(person_id - 1) % len(COLORS)] if confirmed else (160, 160, 160)
    label = f"Pessoa {person_id}" if confirmed else "identificando..."

    # Caixa
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # Fundo do label
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    lx, ly = x1, max(y1 - 4, th + 6)
    cv2.rectangle(frame, (lx, ly - th - 6), (lx + tw + 8, ly + 2), color, -1)

    # Texto do label
    cv2.putText(frame, label, (lx + 4, ly - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)

def draw_overlay(frame: np.ndarray, unique_count: int) -> None:
    """Painel superior com total de pessoas únicas."""
    text  = f"Pessoas unicas: {unique_count}"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
    pad = 10

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (tw + pad * 2 + 4, th + pad * 2), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    cv2.putText(frame, text, (pad + 2, th + pad),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)

# ──────────────────────────────────────────────
#  MULTISOURCE – estado por fonte e registro compartilhado
# ──────────────────────────────────────────────

@dataclass
class _Shared:
    unique_people: list = field(default_factory=list)
    people_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class _Source:
    idx: int
    label: str
    window: str
    is_webcam: bool
    cap: cv2.VideoCapture
    model: YOLO
    resolved_device: str | None
    tracker_path: str
    total_frames: int
    track_features: dict = field(default_factory=dict)
    track_to_person: dict = field(default_factory=dict)
    frame_num: int = 0
    done: bool = False
    latest_frame: object = None


def _worker(src: _Source, shared: _Shared, tolerance: float,
            sample_rate: int, img_size: int, show_window: bool) -> None:
    track_kwargs = dict(
        persist=True, tracker=src.tracker_path, classes=[0],
        conf=0.40, iou=0.60, imgsz=img_size, verbose=False,
    )
    if src.resolved_device is not None:
        track_kwargs["device"] = src.resolved_device

    while not shared.stop_event.is_set() and not src.done:
        ret, frame = src.cap.read()
        if not ret:
            if src.is_webcam:
                print(f"\n  Perda de conexao com {src.label}.")
            src.done = True
            break

        results = src.model.track(frame, **track_kwargs)

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
            track_ids = results[0].boxes.id.int().cpu().numpy()

            for box, tid in zip(boxes, track_ids):
                x1, y1, x2, y2 = box

                if src.frame_num % sample_rate == 0:
                    crop = frame[max(0, y1):y2, max(0, x1):x2]
                    feat = extract_appearance(crop)
                    if feat is not None:
                        src.track_features[tid] = (
                            0.7 * src.track_features[tid] + 0.3 * feat
                            if tid in src.track_features else feat
                        )

                if tid not in src.track_to_person and tid in src.track_features:
                    feat = src.track_features[tid]
                    with shared.people_lock:
                        matched_idx = next(
                            (i for i, rep in enumerate(shared.unique_people)
                             if cosine_dist(feat, rep) <= tolerance),
                            None,
                        )
                        if matched_idx is not None:
                            shared.unique_people[matched_idx] = (
                                0.6 * shared.unique_people[matched_idx] + 0.4 * feat
                            )
                            src.track_to_person[tid] = matched_idx + 1
                        else:
                            shared.unique_people.append(feat)
                            src.track_to_person[tid] = len(shared.unique_people)

                if show_window:
                    person_id = src.track_to_person.get(tid, 0)
                    draw_box(frame, x1, y1, x2, y2,
                             person_id=person_id,
                             confirmed=(person_id > 0))

        if show_window:
            draw_overlay(frame, len(shared.unique_people))
            src.latest_frame = frame

        src.frame_num += 1


def _print_status(states: list[_Source], shared: _Shared) -> None:
    parts = []
    for s in states:
        if s.is_webcam:
            parts.append(f"{s.label}: frame {s.frame_num}")
        else:
            pct = s.frame_num / max(s.total_frames, 1) * 100
            parts.append(f"{s.label}: {pct:4.1f}%")
    line = "  |  ".join(parts) + f"  |  pessoas únicas: {len(shared.unique_people)}"
    print("\r" + line.ljust(90), end="", flush=True)


def count_unique_people(
        sources: list[tuple[bool, int | str, str]],
        tolerance: float = 0.005,
        sample_rate: int = 1, img_size: int = 640,
        show_window: bool = True, device: str = "cpu",
        model_name: str = "yolo26n.pt") -> int:

    shared = _Shared()
    states: list[_Source] = []

    for i, (is_w, value, label) in enumerate(sources):
        model, resolved_device = load_model(device, model_name)

        cap = cv2.VideoCapture(int(value)) if is_w else cv2.VideoCapture(value)
        if not cap.isOpened():
            if is_w:
                raise RuntimeError(f"Não foi possível abrir a webcam {value}")
            raise FileNotFoundError(f"Não foi possível abrir: {value}")

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        buf = total if total > 0 and not is_w else 900

        cfg = (f"tracker_type: bytetrack\ntrack_high_thresh: 0.50\n"
               f"track_low_thresh: 0.10\nnew_track_thresh: 0.60\n"
               f"track_buffer: {buf}\nmatch_thresh: 0.80\nfuse_score: true\n")
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        tmp.write(cfg)
        tmp.close()

        win = f"Person Counter  |  {label}  |  pressione Q" if show_window else ""
        if show_window:
            cv2.namedWindow(win, cv2.WINDOW_NORMAL)

        states.append(_Source(
            idx=i, label=label, window=win, is_webcam=is_w,
            cap=cap, model=model, resolved_device=resolved_device,
            tracker_path=tmp.name, total_frames=total,
        ))

    threads = []
    for s in states:
        t = threading.Thread(target=_worker, daemon=True,
                             args=(s, shared, tolerance, sample_rate,
                                   img_size, show_window))
        t.start()
        threads.append(t)

    last_print = 0.0
    while not shared.stop_event.is_set():
        if all(s.done for s in states):
            break

        if show_window:
            for s in states:
                if s.latest_frame is not None:
                    cv2.imshow(s.window, s.latest_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("\n  Interrompido pelo usuário.")
                shared.stop_event.set()
                break
        else:
            time.sleep(0.01)

        now = time.monotonic()
        if now - last_print >= 0.1:
            last_print = now
            _print_status(states, shared)

    shared.stop_event.set()
    for t in threads:
        t.join(timeout=5)

    for s in states:
        s.cap.release()
        try:
            os.unlink(s.tracker_path)
        except OSError:
            pass

    if show_window:
        cv2.destroyAllWindows()
    print()
    return len(shared.unique_people)


def main():
    parser = argparse.ArgumentParser(
        description="Contador de pessoas insano",
    )
    parser.add_argument("video", nargs="*", metavar="ARQUIVO",
        help="Caminho(s) para arquivo(s) de vídeo (um ou mais).")
    parser.add_argument("--webcam", type=int, nargs="?", const=0,
        action="append", metavar="IDX",
        help="Usa webcam como fonte. IDX é o índice da câmera (padrão: 0). "
             "Repita o flag para usar várias webcams.")
    parser.add_argument("--tolerance", type=float, default=0.005,
        metavar="N",
        help="Limiar de similaridade de aparência (0–0.35). Padrão: 0.005")
    parser.add_argument("--sample-rate", type=int, default=1,
        metavar="N",
        help="Atualiza aparência 1× a cada N frames. Padrão: 1")
    parser.add_argument("--img-size", type=int, default=640,
        choices=[320, 480, 640, 768, 1024, 1280, 1536, 2048],
        metavar="N",
        help="Resolução de entrada do YOLO (320/480/640/768/1024/1280/1536/2048). Padrão: 640")
    parser.add_argument("--model", type=str, default="yolo26n.pt",
        metavar="MODEL",
        help="Modelo YOLO a usar. Exemplos: yolo26n.pt (padrão, mais rápido), "
             "yolo26s.pt, yolo26m.pt, yolo26l.pt, yolo26x.pt (mais preciso). "
             "Aceita também caminho para um modelo customizado (.pt).")
    parser.add_argument("--device", type=str, default=None,
        metavar="DEVICE",
        help="Hardware: 'cuda' (NVIDIA), 'mps' (Apple Silicon), 'intel:gpu' (Intel GPU), 'intel:cpu' (Intel CPU), 'cpu'. "
             "Padrão: detecta automaticamente.")
    parser.add_argument("--no-window", action="store_true",
        help="Roda sem abrir janelas (modo headless).")
    args = parser.parse_args()

    sources: list[tuple[bool, int | str, str]] = []
    for p in args.video:
        if not os.path.isfile(p):
            print(f"Erro: arquivo não encontrado → {p}")
            sys.exit(1)
        sources.append((False, p, os.path.basename(p)))
    for idx in args.webcam or []:
        sources.append((True, idx, f"Webcam {idx}"))

    if not sources:
        parser.error("especifique ao menos uma fonte (arquivo de vídeo ou --webcam).")

    device, device_desc = detect_device(args.device)

    print()
    for is_w, val, label in sources:
        print(f"  {'📹' if is_w else '🎬'}  {label}")
    print(f"    modelo:       {args.model}")
    print(f"    hardware:     {device_desc}")
    print(f"    tolerância:   {args.tolerance}  "
          f"sample-rate: {args.sample_rate}  "
          f"img-size: {args.img_size}\n")

    count = count_unique_people(
        sources,
        tolerance=args.tolerance,
        sample_rate=args.sample_rate,
        img_size=args.img_size,
        show_window=not args.no_window,
        device=device,
        model_name=args.model,
    )

    print(f"\n  Pessoas únicas encontradas: {count}\n")

if __name__ == "__main__":
    main()
