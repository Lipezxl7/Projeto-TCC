# Contador de Pessoas

Contador de pessoas únicas em vídeos e webcams usando **YOLO26**, **ByteTrack** e re-identificação por histograma HSV. Detecta, rastreia e diferencia indivíduos — mesmo após oclusões e reentradas — atribuindo IDs consistentes entre todas as fontes.

Trabalho de Conclusão de Curso (TCC).

---

## Funcionalidades

- Detecção de pessoas via YOLO26 com rastreamento ByteTrack
- Re-identificação entre fontes (cross-source re-ID) por histograma HSV
- Suporte a múltiplas fontes simultâneas com contagem unificada
- Aceleração automática: CUDA (NVIDIA), MPS (Apple Silicon), OpenVINO (Intel GPU/CPU)
- Cada fonte recebe sua própria janela de visualização em tempo real
- Modo headless (`--no-window`) para execução sem interface gráfica

---

## Instalação

> **Requer Python 3.14+** (usa `match/case` e anotações de tipo PEP 604).

```bash
python3.14 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### GPU (opcional)

| Hardware | Instruções |
|----------|------------|
| **NVIDIA** | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130` |
| **Apple Silicon** | `pip install torch` (MPS ativo automaticamente com PyTorch 2.12+) |
| **Intel** | OpenVINO já está em `requirements.txt` — nenhuma instalação extra |

---

## Uso

### Fonte única

```bash
python contador.py video.mp4                # arquivo de vídeo
python contador.py --webcam                 # webcam padrão (índice 0)
python contador.py --webcam 1               # segunda webcam
```

### Múltiplas fontes

Cada fonte roda em sua própria thread com janela independente. Pessoas são identificadas entre fontes — a mesma pessoa em vídeos/webcams diferentes recebe o mesmo ID.

```bash
python contador.py a.mp4 b.mp4                     # dois vídeos
python contador.py video.mp4 --webcam 0            # vídeo + webcam
python contador.py --webcam 0 --webcam 1           # duas webcams
```

### Parâmetros

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `video` (posicional) | — | Um ou mais arquivos de vídeo |
| `--webcam [IDX]` | índice 0 | Webcam como fonte; repita para múltiplas (`--webcam 0 --webcam 1`) |
| `--tolerance` | `0.005` | Limiar de similaridade de aparência (faixa recomendada: 0.003–0.10) |
| `--sample-rate` | `1` | Atualiza aparência a cada N frames |
| `--img-size` | `640` | Resolução de entrada do YOLO (`320 480 640 768 1024 1280 1536 2048`) |
| `--model` | `yolo26n.pt` | Modelo YOLO (`yolo26n` → `yolo26s` → `yolo26m` → `yolo26l` → `yolo26x`) |
| `--device` | auto | `cuda`, `mps`, `intel:gpu`, `intel:cpu` ou `cpu` |
| `--no-window` | desligado | Roda sem abrir janelas (modo headless) |

### Exemplos

```bash
# Alta precisão
python contador.py video.mp4 --img-size 1536 --model yolo26x.pt --tolerance 0.003

# Alta velocidade
python contador.py video.mp4 --img-size 320 --sample-rate 3

# Intel GPU com tolerância relaxada
python contador.py video.mp4 --device intel:gpu --tolerance 0.05

# Headless (sem janela)
python contador.py video.mp4 --no-window --sample-rate 2

# Multi-fonte com cross-source re-ID
python contador.py corredor1.mp4 corredor2.mp4 --webcam 0 --tolerance 0.02
```

---

## Como funciona

```
contador.py
├── Detecção de dispositivo
│   ├── detect_device()            → Preferência do usuário ou auto-detecção
│   └── auto_device_selection()    → CUDA → MPS → Intel GPU → Intel CPU → CPU
├── Carregamento do modelo
│   └── load_model()               → YOLO + exportação/compilação OpenVINO
├── Re-identificação por aparência
│   ├── extract_appearance()       → Histograma HSV 288-dim (região superior + inferior)
│   └── cosine_dist()              → Distância cosseno (1 − produto normalizado)
├── Visualização
│   ├── draw_box()                 → Bounding box colorida por ID da pessoa
│   └── draw_overlay()             → Painel com contagem de pessoas únicas
├── Processamento multi-fonte
│   ├── _worker()                  → Thread por fonte (YOLO independente, ByteTrack persistente)
│   ├── _Shared                    → Registro compartilhado de pessoas únicas (lock)
│   └── _Source                    → Estado por fonte (modelo, tracker, dicionários)
└── CLI
    └── NumerarPessoas()          → Argumentos, configuração, orquestração
```

### Re-identificação

Para cada detecção, é extraído um vetor de aparência de **288 dimensões** a partir de um recorte de 48×96 pixels convertido para HSV e dividido em região superior e inferior do corpo. A correspondência usa distância cosseno com tolerância configurável:

- **Tolerância baixa** (ex: 0.001) → morte de correspondências legítimas → super-contagem
- **Tolerância alta** (ex: 0.10+) → fusão de pessoas diferentes → sub-contagem
- **Padrão** (0.005) → bom equilíbrio para cores de roupa distintas

### Multi-fonte

Cada fonte roda em uma thread dedicada com sua própria instância YOLO (necessária para estado ByteTrack independente via `persist=True`). O registro de pessoas únicas é compartilhado entre fontes e protegido por lock — garantindo que a mesma pessoa em fontes diferentes receba o mesmo ID.

---

## Hardware suportado

O sistema detecta automaticamente o melhor dispositivo disponível:

| Dispositivo | Flag | Notas |
|-------------|------|-------|
| NVIDIA GPU | `--device cuda` | Requer PyTorch com CUDA |
| Apple Silicon | `--device mps` | Automático com PyTorch 2.12+ |
| Intel GPU | `--device intel:gpu` | Via OpenVINO |
| Intel CPU | `--device intel:cpu` | Via OpenVINO |
| CPU genérico | `--device cpu` | Fallback universal |

---

## Dependências

**Diretas** (`requirements.txt`): `opencv-python`, `numpy`, `ultralytics`, `openvino`

**Transitivas**: `torch` (detectação de GPU + backend YOLO), `torchvision`, `PyYAML`, `lap`

O modelo `yolo26n.pt` é baixado automaticamente pelo ultralytics na primeira execução. O diretório `yolo26n_openvino_model/` é gerado automaticamente na primeira execução com OpenVINO. Ambos são gitignored.

---

## Saída

### Janela

- Bounding boxes coloridas por ID da pessoa (paleta cíclica de 8 cores)
- Labels: `"Pessoa N"` (identificada) ou `"identificando..."` (aguardando correspondência)
- Painel superior: `"Pessoas unicas: N"` (contagem global entre todas as fontes)
- Pressione **Q** para interromper

### Console

- Progresso por fonte e contagem unificada em tempo real
- Informações de dispositivo OpenVINO (solicitado vs. executado)
- Resultado final: `"Pessoas únicas encontradas: N"`

---

## Licença

Este projeto é parte de um Trabalho de Conclusão de Curso. Repositório: [codeberg.org/yLipe/Projeto-TCC](https://codeberg.org/yLipe/Projeto-TCC)
