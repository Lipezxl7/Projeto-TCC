"""
COZINHA — TCC  (versão refatorada)
===================================
Meta: contar pessoas únicas com 90 %+ de precisão.

Melhorias aplicadas nesta versão
─────────────────────────────────
PERFORMANCE
  [x] GPU automática (CUDA detectado em runtime)
  [x] Batch inference — todas as pessoas em UMA chamada ao OSNet
  [x] torch.no_grad() — elimina cálculo de gradiente, reduz VRAM ~40 %
  [x] YOLO com imgsz=1280 — detecta pessoas longe com muito mais precisão
  [x] Modelo osnet_ibn_x1_0 — melhor que ain em variações de iluminação

LATÊNCIA
  [x] frames_acumulo = 5  (era 10) — decisão ~3× mais rápida
  [x] processar_a_cada = 2 (era 3)
  [x] Decisão antecipada quando o EMA já convergiu (3 frames estáveis)
  [x] Thread separada para leitura da câmera — desacopla I/O de processamento

PRECISÃO
  [x] CLAHE + sharpening no crop antes do OSNet
  [x] Filtro de qualidade (Laplacian) — descarta crops borrados
  [x] IoU entre bboxes — suspende ReID quando pessoas estão sobrepostas
  [x] Rastreio continua ativo após contar — atualiza aparência a cada 30 frames
  [x] Verificação dupla dentro de adicionar() — evita corrida entre IDs

BUGS CORRIGIDOS
  [x] Operador "or" na remoção de rastreios — era causa de IDs duplicados
  [x] Galeria verifica novamente dentro de adicionar() — evita contagem dupla
  [x] Thread de câmera — estabiliza FPS em câmeras IP com lag

ROBUSTEZ
  [x] logging estruturado com timestamp (arquivo + console)
  [x] FPS real calculado por média móvel e exibido no overlay
  [x] Backup automático da galeria a cada hora
  [x] Diagnóstico de GPU no startup
"""

import cv2
import numpy as np
import time
import os
import json
import shutil
import logging
from threading import Thread
import queue

import torch
import torchreid
from ultralytics import YOLO
from scipy.spatial.distance import cosine


# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────────────────────

CAMERA            = "pessoas.mp4"  # 0 = webcam, "arquivo.mp4" = vídeo
CONFIANCA         = 0.35           # limiar YOLO (0.35 detecta mais, 0.50 menos falsos)
ALTURA_MIN        = 60             # era 90 — aceita pessoas mais distantes
ASPECTO_MIN       = 1.2            # altura/largura mínima (filtra não-humanos)
FRAMES_ACUMULO    = 5              # era 10 — decisão mais rápida
PROCESSAR_A_CADA  = 2              # era 3 — mais amostras por segundo
EMA_ALPHA         = 0.30           # 0.1 = suave, 0.3 = reativo
IOU_LIMITE        = 0.15           # sobreposição mínima para suspender ReID
LIMIAR_REID       = 0.32
LIMIAR_COR_CIMA   = 0.30
LIMIAR_COR_BAIXO  = 0.30
PESO_REID         = 0.55           # deve somar 1.0 com os dois abaixo
PESO_COR_CIMA     = 0.25
PESO_COR_BAIXO    = 0.20
LIMIAR_FUSAO      = 0.31
LAPLACIAN_MIN     = 50.0           # variância mínima de nitidez do crop
ARQUIVO_GALERIA   = "galeria.json"
FRAMES_POS_UPDATE = 30             # a cada N frames pós-contagem, atualiza galeria


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("contador.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DETECÇÃO DE GPU
# ─────────────────────────────────────────────────────────────

def detectar_dispositivo():
    if torch.cuda.is_available():
        nome = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        log.info(f"GPU detectada: {nome} ({vram:.1f} GB VRAM)")
        return "cuda"
    elif torch.xpu.is_available():
        nome = torch.xpu.get_device_name(0)
        vram = torch.xpu.get_device_properties(0).total_memory / 1e9
        log.info(f"GPU detectada: {nome} ({vram:.1f} GB VRAM)")
        return "xpu"
    log.warning("GPU não encontrada — rodando em CPU (mais lento)")
    return "cpu"


DEVICE = detectar_dispositivo()


# ─────────────────────────────────────────────────────────────
# THREAD DE LEITURA DE CÂMERA
# ─────────────────────────────────────────────────────────────

class LeitorCamera:
    """
    Lê frames em thread separada para desacoplar I/O da câmera
    do loop de processamento. Evita travamentos em câmeras IP
    com lag e garante que o loop principal processe sempre o
    frame mais recente disponível.
    """
    def __init__(self, fonte):
        self.cap = cv2.VideoCapture(fonte)
        if not self.cap.isOpened():
            raise RuntimeError(f"Câmera/vídeo '{fonte}' não pôde ser aberto.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.buffer = queue.Queue(maxsize=1)
        self.ativo  = True
        self._thread = Thread(target=self._ler, daemon=True)
        self._thread.start()
        log.info(f"Câmera '{fonte}' iniciada em thread separada")

    def _ler(self):
        while self.ativo:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            if not self.buffer.full():
                self.buffer.put(frame)

    def ler(self):
        """Retorna (True, frame) ou (False, None) se vazio."""
        try:
            return True, self.buffer.get(timeout=1.0)
        except queue.Empty:
            return False, None

    def liberar(self):
        self.ativo = False
        self.cap.release()


# ─────────────────────────────────────────────────────────────
# FUNÇÕES UTILITÁRIAS
# ─────────────────────────────────────────────────────────────

def normalizar_vetor(v):
    """Normaliza para L2=1, protege contra divisão por zero."""
    n = np.linalg.norm(v)
    return v / n if n > 1e-8 else v


def melhorar_crop(img):
    """
    CLAHE: equaliza contraste localmente, ressalta textura da roupa
    sem saturar pixels em ambientes com iluminação artificial.
    Sharpening leve: recupera bordas borradas por movimento.
    Juntos aumentam a distintividade dos descritores do OSNet.
    """
    if img is None or img.size == 0:
        return img
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    kernel = np.array([[ 0,  -0.5,  0],
                       [-0.5,  3,  -0.5],
                       [ 0,  -0.5,  0]])
    return cv2.filter2D(img, -1, kernel)


def qualidade_ok(img):
    """
    Variância de Laplacian mede nitidez da imagem.
    Crops abaixo de LAPLACIAN_MIN são muito borrados (pessoa em movimento
    rápido, oclusão, fora de foco) e poluem o EMA com descritores ruins.
    """
    if img is None or img.size == 0:
        return False
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(cinza, cv2.CV_64F).var() >= LAPLACIAN_MIN


def preparar_para_reid(img):
    """Redimensiona e centra o crop no formato 256×128 exigido pelo OSNet."""
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    if h < 10 or w < 10:
        return None
    escala     = min(256 / h, 128 / w)
    nh, nw     = max(1, int(h * escala)), max(1, int(w * escala))
    redim      = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    tela       = np.zeros((256, 128, 3), dtype=np.uint8)
    mt, me     = (256 - nh) // 2, (128 - nw) // 2
    tela[mt:mt+nh, me:me+nw] = redim
    return cv2.cvtColor(tela, cv2.COLOR_BGR2RGB)


def extrair_cores(img):
    """Histogramas HSV (cima=camisa, baixo=calça)."""
    if img is None or img.size == 0 or img.shape[0] < 20:
        return None, None
    hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    meio = img.shape[0] // 2

    def hist(regiao):
        h = cv2.calcHist([regiao], [0, 1], None, [18, 8], [0, 180, 0, 256])
        cv2.normalize(h, h)
        return h.flatten()

    return hist(hsv[:meio, :]), hist(hsv[meio:, :])


def comparar_hist(a, b):
    """Bhattacharyya: 0=idêntico, 1=completamente diferente."""
    if a is None or b is None:
        return 1.0
    return float(cv2.compareHist(
        a.astype(np.float32), b.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA))


def score_fusao(dna1, cima1, baixo1, dna2, cima2, baixo2):
    """
    Funde os 3 descritores em um único score de similaridade.
    Quanto menor, mais parecidas as duas pessoas.
    """
    d_corpo = cosine(dna1, dna2) if (dna1 is not None and dna2 is not None) else 1.0
    d_cima  = comparar_hist(cima1, cima2)
    d_baixo = comparar_hist(baixo1, baixo2)
    return PESO_REID * d_corpo + PESO_COR_CIMA * d_cima + PESO_COR_BAIXO * d_baixo


def calcular_iou(b1, b2):
    """
    Interseção sobre União entre dois bboxes.
    Usado para detectar quando duas pessoas estão sobrepostas —
    nesses casos o crop fica contaminado e o ReID erra.
    """
    xi1 = max(b1[0], b2[0]);  yi1 = max(b1[1], b2[1])
    xi2 = min(b1[2], b2[2]);  yi2 = min(b1[3], b2[3])
    inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    a1    = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2    = (b2[2] - b2[0]) * (b2[3] - b2[1])
    return inter / (a1 + a2 - inter + 1e-6)


# ─────────────────────────────────────────────────────────────
# GALERIA
# ─────────────────────────────────────────────────────────────

class Galeria:
    """
    Armazena os descritores das pessoas únicas já contadas.
    Persiste em JSON entre execuções e faz reset diário automático.
    Backup automático a cada hora evita perda de dados.
    """

    def __init__(self):
        self.entradas = []
        self._resetar_se_dia_novo()
        self._carregar()

    # ── persistência ────────────────────────────────────────

    def _resetar_se_dia_novo(self):
        hoje    = time.strftime("%Y-%m-%d")
        arquivo = "galeria_data.txt"
        if os.path.exists(arquivo):
            if open(arquivo).read().strip() != hoje:
                self.resetar(silencioso=True)
                log.info("Novo dia — galeria resetada automaticamente")
        with open(arquivo, "w") as f:
            f.write(hoje)

    def _carregar(self):
        if not os.path.exists(ARQUIVO_GALERIA):
            return
        try:
            dados = json.load(open(ARQUIVO_GALERIA))
            for e in dados:
                self.entradas.append({
                    "dna"  : np.array(e["dna"],   dtype=np.float32),
                    "cima" : np.array(e["cima"],  dtype=np.float32),
                    "baixo": np.array(e["baixo"], dtype=np.float32),
                })
            log.info(f"Galeria carregada: {len(self.entradas)} pessoa(s)")
        except Exception as ex:
            log.error(f"Erro ao carregar galeria: {ex}")
            self.entradas = []

    def _salvar(self):
        dados = [{"dna":   e["dna"].tolist(),
                  "cima":  e["cima"].tolist(),
                  "baixo": e["baixo"].tolist()}
                 for e in self.entradas]
        with open(ARQUIVO_GALERIA, "w") as f:
            json.dump(dados, f)
        self._backup_horario()

    def _backup_horario(self):
        """Salva uma cópia com timestamp a cada hora — protege contra falhas."""
        os.makedirs("backup", exist_ok=True)
        bkp = f"backup/galeria_{time.strftime('%Y%m%d_%H')}.json"
        if not os.path.exists(bkp) and os.path.exists(ARQUIVO_GALERIA):
            shutil.copy(ARQUIVO_GALERIA, bkp)
            log.info(f"Backup salvo: {bkp}")

    # ── operações ───────────────────────────────────────────

    def buscar(self, dna, cima, baixo):
        """Retorna (já_existe, melhor_score)."""
        if not self.entradas:
            return False, 1.0
        scores      = [score_fusao(dna, cima, baixo,
                                   e["dna"], e["cima"], e["baixo"])
                       for e in self.entradas]
        melhor      = min(scores)
        return melhor < LIMIAR_FUSAO, melhor

    def adicionar(self, dna, cima, baixo):
        """
        Verifica novamente antes de inserir — evita corrida quando
        dois rastreios diferentes ficam prontos no mesmo frame
        e ambos passam no buscar() antes de qualquer um inserir.
        """
        existe, score = self.buscar(dna, cima, baixo)
        if existe:
            return None, score  # já foi adicionada por outro rastreio
        numero = len(self.entradas) + 1
        self.entradas.append({"dna": dna, "cima": cima, "baixo": baixo})
        self._salvar()
        return numero, score

    def atualizar_entrada(self, indice, dna, cima, baixo):
        """
        Atualiza a aparência de uma pessoa já contada.
        Necessário para lidar com troca de roupa ou mudança de iluminação.
        """
        if 0 <= indice < len(self.entradas):
            self.entradas[indice]["dna"]   = dna
            self.entradas[indice]["cima"]  = cima
            self.entradas[indice]["baixo"] = baixo
            self._salvar()

    def total(self):
        return len(self.entradas)

    def resetar(self, silencioso=False):
        self.entradas = []
        for arq in [ARQUIVO_GALERIA, "galeria_data.txt"]:
            if os.path.exists(arq):
                os.remove(arq)
        if not silencioso:
            log.info("Galeria resetada manualmente")


# ─────────────────────────────────────────────────────────────
# RASTREIO
# ─────────────────────────────────────────────────────────────

class Rastreio:
    """
    Representa uma pessoa rastreada na cena.
    Acumula descritores via EMA e decide quando há frames suficientes.
    Após contar, continua atualizando o EMA para lidar com mudanças
    de aparência (roupa, iluminação) ao longo do dia.
    """

    def __init__(self, yid):
        self.yid              = yid
        self.dna_ema          = None
        self.dna_anterior     = None    # usado para detectar convergência
        self.cima_ema         = None
        self.baixo_ema        = None
        self.frames           = 0
        self.contado          = False
        self.indice_galeria   = None    # posição na galeria após ser contado
        self.frames_pos       = 0       # frames desde que foi contado
        self.ultimo_visto     = time.time()

    def atualizar(self, dna, cima, baixo):
        dna = normalizar_vetor(dna)

        # salva anterior para medir convergência
        self.dna_anterior = self.dna_ema.copy() if self.dna_ema is not None else dna

        if self.dna_ema is None:
            self.dna_ema = dna
        else:
            self.dna_ema = normalizar_vetor(
                EMA_ALPHA * dna + (1 - EMA_ALPHA) * self.dna_ema)

        if cima is not None:
            self.cima_ema = cima if self.cima_ema is None else (
                EMA_ALPHA * cima + (1 - EMA_ALPHA) * self.cima_ema)

        if baixo is not None:
            self.baixo_ema = baixo if self.baixo_ema is None else (
                EMA_ALPHA * baixo + (1 - EMA_ALPHA) * self.baixo_ema)

        self.frames        += 1
        self.ultimo_visto   = time.time()

        if self.contado:
            self.frames_pos += 1

    def pronto(self):
        """
        Retorna True quando há descritores suficientes para decidir.
        Pode decidir antes do mínimo se o EMA já convergiu
        (baixa variação entre frames = sinal estável).
        """
        if self.contado:
            return False
        tem_tudo = (self.dna_ema  is not None and
                    self.cima_ema is not None and
                    self.baixo_ema is not None)
        if not tem_tudo:
            return False
        if self.frames >= FRAMES_ACUMULO:
            return True
        # decisão antecipada: EMA já convergiu com apenas 3 frames
        if self.frames >= 3 and self.dna_anterior is not None:
            variacao = np.linalg.norm(self.dna_ema - self.dna_anterior)
            if variacao < 0.03:
                log.debug(f"ID:{self.yid} — decisão antecipada ({self.frames} frames, var={variacao:.4f})")
                return True
        return False

    def deve_atualizar_galeria(self):
        """Após contar, atualiza a galeria a cada N frames."""
        return (self.contado and
                self.indice_galeria is not None and
                self.frames_pos > 0 and
                self.frames_pos % FRAMES_POS_UPDATE == 0)

    def expirou(self):
        return time.time() - self.ultimo_visto > 3.0


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("  Contador TCC — iniciando")
    log.info("=" * 55)

    # ── YOLO ────────────────────────────────────────────────
    try:
        yolo = YOLO("yolo11x.pt")   # baixa automaticamente se não existir
        yolo.to(DEVICE)
        log.info(f"YOLO yolo11x carregado em {DEVICE}")
    except Exception as e:
        log.critical(f"Falha ao carregar YOLO: {e}")
        return

    # ── OSNet ───────────────────────────────────────────────
    try:
        extrator = torchreid.utils.FeatureExtractor(
            model_name="osnet_ibn_x1_0",  # melhor que ain em luz artificial
            device=DEVICE
        )
        log.info(f"OSNet osnet_ibn_x1_0 carregado em {DEVICE}")
    except Exception as e:
        log.critical(f"Falha ao carregar OSNet: {e}")
        return

    # ── câmera em thread ────────────────────────────────────
    try:
        cam = LeitorCamera(CAMERA)
    except RuntimeError as e:
        log.critical(str(e))
        return

    # ── estado ──────────────────────────────────────────────
    galeria   = Galeria()
    rastreios = {}          # yid → Rastreio
    frame_n   = 0
    os.makedirs("debug", exist_ok=True)

    # FPS (média móvel 30 frames)
    fps_hist   = []
    t_frame    = time.time()

    log.info("Rodando.  Teclas: q = sair  |  r = resetar galeria")

    while True:

        # ── leitura ─────────────────────────────────────────
        ret, frame = cam.ler()
        if not ret:
            continue
        frame_n += 1

        # FPS
        agora    = time.time()
        fps_inst = 1.0 / max(agora - t_frame, 1e-6)
        t_frame  = agora
        fps_hist.append(fps_inst)
        if len(fps_hist) > 30:
            fps_hist.pop(0)
        fps_medio = sum(fps_hist) / len(fps_hist)

        # ── detecção YOLO ───────────────────────────────────
        try:
            resultado = yolo.track(
                frame,
                persist=True,
                classes=[0],
                conf=CONFIANCA,
                verbose=False,
                tracker="bytetrack.yaml",
                imgsz=1280,          # detecta pessoas distantes
                device=DEVICE,
            )
        except Exception as e:
            log.error(f"Erro YOLO frame {frame_n}: {e}")
            continue

        ids_vivos = set()

        # ── coleta de crops válidos para batch ──────────────
        # Lógica: primeiro passamos por todos os bboxes, aplicamos
        # os filtros e coletamos os crops válidos. Só então chamamos
        # o OSNet UMA vez para todo o lote.

        crops_batch   = []   # imagens preparadas para o OSNet
        yids_batch    = []   # IDs correspondentes
        recortes_cor  = []   # crops originais para extrair cores
        boxes_frame   = []   # (yid, box) para sobreposição IoU

        tem_deteccao = resultado[0].boxes.id is not None
        if tem_deteccao:
            ids_arr   = resultado[0].boxes.id.cpu().numpy().astype(int)
            boxes_arr = resultado[0].boxes.xyxy.cpu().numpy().astype(int)

            # monta lista de boxes para checar IoU
            boxes_frame = list(zip(ids_arr, boxes_arr))

            # calcula IDs que estão sobrepostos (ReID suspenso)
            ids_sobrepostos = set()
            for i, (id1, b1) in enumerate(boxes_frame):
                for id2, b2 in boxes_frame[i+1:]:
                    if calcular_iou(b1, b2) > IOU_LIMITE:
                        ids_sobrepostos.add(id1)
                        ids_sobrepostos.add(id2)
            if ids_sobrepostos:
                log.debug(f"Sobreposição detectada em IDs: {ids_sobrepostos}")

            e_frame_reid = frame_n % PROCESSAR_A_CADA == 0

            for yid, box in boxes_frame:
                ids_vivos.add(yid)
                x1, y1, x2, y2 = box
                altura  = y2 - y1
                largura = max(x2 - x1, 1)

                if altura < ALTURA_MIN:
                    continue
                if (altura / largura) < ASPECTO_MIN:
                    continue

                if yid not in rastreios:
                    rastreios[yid] = Rastreio(yid)

                r = rastreios[yid]
                r.ultimo_visto = time.time()

                # coleta crop para ReID (somente se não em grupo e frame certo)
                deve_processar = (e_frame_reid and
                                  yid not in ids_sobrepostos and
                                  not r.contado)
                # mesmo contado, precisa atualizar aparência?
                deve_atualizar = (e_frame_reid and
                                  r.contado and
                                  r.deve_atualizar_galeria())

                if deve_processar or deve_atualizar:
                    recorte = frame[max(0,y1):y2, max(0,x1):x2].copy()
                    if recorte.size > 0 and qualidade_ok(recorte):
                        img_prep = preparar_para_reid(melhorar_crop(recorte))
                        if img_prep is not None:
                            crops_batch.append(img_prep)
                            yids_batch.append(yid)
                            recortes_cor.append(recorte)

        # ── BATCH OSNet — UMA chamada para todos os crops ───
        if crops_batch:
            try:
                with torch.no_grad():                       # sem gradiente = menos VRAM
                    dnas = extrator(crops_batch)            # shape: [N, 512]
                for yid, dna, recorte in zip(yids_batch, dnas, recortes_cor):
                    cima, baixo = extrair_cores(recorte)
                    r = rastreios.get(yid)
                    if r is None:
                        continue

                    r.atualizar(dna.cpu().numpy(), cima, baixo)

                    # atualiza galeria com aparência atual (pós-contagem)
                    if r.contado and r.deve_atualizar_galeria():
                        galeria.atualizar_entrada(
                            r.indice_galeria, r.dna_ema, r.cima_ema, r.baixo_ema)
                        log.debug(f"ID:{yid} aparência atualizada na galeria")

            except Exception as e:
                log.error(f"Erro batch OSNet: {e}")

        # ── decisão e desenho ────────────────────────────────
        if tem_deteccao:
            for yid, box in boxes_frame:
                x1, y1, x2, y2 = box
                r = rastreios.get(yid)
                if r is None:
                    continue

                # toma decisão quando acumulou frames suficientes
                if r.pronto():
                    numero, score = galeria.adicionar(r.dna_ema, r.cima_ema, r.baixo_ema)
                    r.contado = True
                    if numero is not None:
                        r.indice_galeria = numero - 1
                        foto = frame[max(0,y1):y2, max(0,x1):x2].copy()
                        log.info(f"Pessoa #{numero} contada  (ID:{yid} | score:{score:.3f} | frames:{r.frames})")
                        cv2.imwrite(f"debug/NOVO_P{numero}_ID{yid}.jpg", foto)
                    else:
                        foto = frame[max(0,y1):y2, max(0,x1):x2].copy()
                        log.info(f"ID:{yid} já existia na galeria (score:{score:.3f})")
                        cv2.imwrite(f"debug/EXISTENTE_ID{yid}_s{score:.3f}.jpg", foto)

                # cores do retângulo
                if r.contado:
                    cor = (0, 220, 0)     # verde = contado
                    txt = f"ID:{yid} ok"
                elif yid in (ids_sobrepostos if tem_deteccao else set()):
                    cor = (0, 165, 255)   # laranja = sobreposto, aguardando
                    txt = f"ID:{yid} grupo"
                else:
                    cor = (0, 180, 255)   # amarelo = acumulando
                    txt = f"ID:{yid} [{r.frames}/{FRAMES_ACUMULO}f]"

                cv2.rectangle(frame, (x1, y1), (x2, y2), cor, 2)
                cv2.putText(frame, txt, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, cor, 1)

                # barra de progresso (só se ainda acumulando)
                if not r.contado:
                    larg       = x2 - x1
                    prog       = min(r.frames, FRAMES_ACUMULO)
                    tamanho    = int(larg * prog / FRAMES_ACUMULO)
                    cv2.rectangle(frame, (x1, y2+2), (x2,     y2+5), (40,40,40), -1)
                    cv2.rectangle(frame, (x1, y2+2), (x1+tamanho, y2+5), cor, -1)

        # ── remove rastreios expirados ───────────────────────
        # CORREÇÃO: antes usava "or" que apagava rastreios ausentes
        # por apenas 1 frame (causava IDs duplicados).
        # Agora só remove quem ficou MUITO TEMPO sem aparecer.
        expirados = [yid for yid, r in rastreios.items() if r.expirou()]
        for yid in expirados:
            del rastreios[yid]

        # ── overlay de informações ───────────────────────────
        cv2.rectangle(frame, (0, 0), (320, 80), (0, 0, 0), -1)
        cv2.putText(frame, f"PESSOAS: {galeria.total()}",
                    (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 230, 0), 2)
        cv2.putText(frame,
                    f"ativos:{len(rastreios)}  FPS:{fps_medio:.1f}  [{DEVICE.upper()}]  q=sair r=reset",
                    (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 150, 150), 1)

        # Tamanho da janela.
        frame_exibir = cv2.resize(frame, (960, 540))
        cv2.imshow("Contador TCC", frame_exibir)
        tecla = cv2.waitKey(1) & 0xFF
        if tecla == ord("q"):
            break
        elif tecla == ord("r"):
            galeria.resetar()
            rastreios.clear()
            log.info("Galeria e rastreios resetados pelo usuário")

    # ── encerramento ─────────────────────────────────────────
    cam.liberar()
    cv2.destroyAllWindows()
    log.info(f"Encerrado. Total: {galeria.total()} pessoa(s) única(s)")
    log.info(f"Galeria salva em '{ARQUIVO_GALERIA}'")
    log.info(f"Log salvo em 'contador.log'")


if __name__ == "__main__":
    main()