"""TCC — Gestão do Refeitório Escolar | App Streamlit (arquivo único).

Rodar com:
    streamlit run app.py

Estrutura:
  modulos/   -> fontes de verdade (calculo, cardapio, receita, contador)
  arquivos/  -> PDFs, vídeos e JSONs gerados (cardapio.json, receitas.json)

Telas (menu lateral):
  🎬 Contagem   -> vídeo + IA (YOLO/ByteTrack) contando alunos únicos
  📊 Resultado  -> produção do dia em kg de alimento e litros de água
"""
from __future__ import annotations

import io
import queue
import threading
import time
from datetime import date
from pathlib import Path

import streamlit as st

from modulos import calculo

RAIZ = Path(__file__).resolve().parent
ARQUIVOS = RAIZ / "arquivos"

# ═══════════════════════════════════════════════════════════════════
#  CAMINHOS
# ═══════════════════════════════════════════════════════════════════

def _caminho(*partes: str) -> Path:
    return ARQUIVOS.joinpath(*partes)


CARDAPIO_PDF = _caminho("cardapio.pdf")
RECEITA_PDF = _caminho("receita.pdf")
CARDAPIO_JSON = _caminho("cardapio.json")
RECEITAS_JSON = _caminho("receitas.json")

# ═══════════════════════════════════════════════════════════════════
#  GERAÇÃO DE DADOS (modulos)
# ═══════════════════════════════════════════════════════════════════

def gerar_cardapio(mes: str) -> int:
    """Extrai o cardápio do PDF usando modulos.cardapio.

    Sobrescreve o cardapio.json existente. Lança exceção em falha (a UI mostra).
    """
    if not CARDAPIO_PDF.exists():
        raise FileNotFoundError(f"PDF do cardápio não encontrado: {CARDAPIO_PDF}")
    from modulos import cardapio
    dados = cardapio.executar_extracao(
        str(CARDAPIO_PDF), str(CARDAPIO_JSON), mes=mes,
        salvar_json=True, salvar_csv=False)
    return len(dados)


def gerar_receitas() -> int:
    """Extrai as receitas do PDF usando modulos.receita.

    Sobrescreve o receitas.json existente. Lança exceção em falha (a UI mostra).
    """
    if not RECEITA_PDF.exists():
        raise FileNotFoundError(f"PDF das receitas não encontrado: {RECEITA_PDF}")
    from modulos import receita
    recipes = receita.extract_recipes(str(RECEITA_PDF))
    receita.save_json(recipes, str(RECEITAS_JSON))
    return len(recipes)


@st.cache_data(show_spinner="Carregando fichas técnicas...")
def carregar_receitas(caminho: str) -> dict[str, dict]:
    return calculo.carregar_receitas(caminho)


# ═══════════════════════════════════════════════════════════════════
#  CONTAGEM: engine em thread + fila de frames (para o Streamlit)
# ═══════════════════════════════════════════════════════════════════

_MODULO_CONTADOR = None

# device pedido na UI -> device resolvido esperado (p/ avisar quando cai p/ outro)
_DISPOSITIVO_ESPERADO = {
    "cuda": "cuda", "mps": "mps",
    "intel:gpu": "openvino:GPU", "intel:cpu": "openvino:CPU", "cpu": "cpu",
}


def _get_contador():
    """Importa modulos.contador apenas quando necessário (torch/ultralytics)."""
    global _MODULO_CONTADOR
    if _MODULO_CONTADOR is None:
        from modulos import contador
        _MODULO_CONTADOR = contador
    return _MODULO_CONTADOR


class CounterEngine:
    def __init__(self, video_path: str, modelo: str = "yolo26n.pt",
                 device: str | None = None, tolerancia: float = 0.005,
                 sample_rate: int = 3, img_size: int = 640):
        self.video_path = video_path
        self.modelo = modelo
        self.device_pedido = device  # bruto, p/ avisar quando cair p/ outro
        self.device, self.device_desc = _get_contador().detect_device(device)
        self.tolerancia = tolerancia
        self.sample_rate = sample_rate
        self.img_size = img_size
        self._fila: queue.Queue = queue.Queue(maxsize=1)
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.done = False
        self.final_count: int | None = None
        self.live_count = 0
        self.error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._parar.clear()
        self.done, self.final_count, self.error = False, None, None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._parar.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_frame(self, timeout: float = 0.1):
        try:
            return self._fila.get(timeout=timeout)
        except queue.Empty:
            return None

    def has_pending(self) -> bool:
        return not self._fila.empty()

    def _run(self) -> None:
        try:
            total = _get_contador().count_unique_people(
                [(False, self.video_path, "video")],
                tolerance=self.tolerancia,
                sample_rate=self.sample_rate,
                img_size=self.img_size,
                show_window=False,
                device=self.device,
                model_name=self.modelo,
                frame_queue=self._fila,
                status_cb=lambda n: self._set_live(n),
                stop_event=self._parar,
            )
            self.final_count = total
            self.live_count = total
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.done = True

    def _set_live(self, n: int) -> None:
        self.live_count = n


def _engine() -> CounterEngine | None:
    return st.session_state.get("engine")


def _criar_engine(video, modelo, device, tolerancia, sample_rate, img_size) -> CounterEngine:
    eng = _engine()
    if eng is not None:
        eng.stop()
    eng = CounterEngine(str(video), modelo, device, tolerancia, sample_rate, img_size)
    st.session_state["engine"] = eng
    st.session_state.pop("contagem_final", None)
    return eng

# ═══════════════════════════════════════════════════════════════════
#  TELA 1 — CONTAGEM
# ═══════════════════════════════════════════════════════════════════

def _listar_videos() -> list[str]:
    exts = ("*.mp4", "*.avi", "*.mov", "*.mkv")
    return sorted(p.name for ext in exts for p in ARQUIVOS.glob(ext) if p.is_file())


def tela_contagem() -> None:
    st.title("Contagem alunos")
    st.caption("Detecção **YOLO** + **ByteTrack** + correspondência de aparência (HSV).")

    videos = _listar_videos()

    with st.sidebar:
        st.header(" Contagem")
        video = st.selectbox(" Vídeo", videos if videos else ["—"])
        modelo = st.selectbox(" Modelo YOLO",
                              ["yolo26n.pt", "yolo26x.pt", "yolo11x.pt",
                               "yolov8s.pt", "yolov8n.pt"])
        tolerancia = st.slider(" Tolerância", 0.001, 0.35, 0.005, 0.001,
                               help="Menor = exige mais semelhança para contar como a mesma pessoa.")
        sample_rate = st.slider(" Sample rate", 1, 10, 3)
        img_size = st.selectbox(" Resolução", [320, 480, 640, 768, 1024], index=2)
        device = st.selectbox(" Hardware",
                              ["auto", "cpu", "intel:gpu", "intel:cpu", "cuda", "mps"],
                              help="'auto' escolhe o melhor disponível.")

    if not videos:
        st.warning("Nenhum vídeo (.mp4/.avi/.mov/.mkv) na pasta `arquivos/`.")
        return

    eng = _engine()
    if eng is not None and eng.video_path != str(ARQUIVOS / video):
        eng.stop()
        st.session_state.pop("engine", None)
        st.rerun()

    if eng is not None and eng.error:
        st.error(f"❌ Erro na contagem: {eng.error}")
        st.session_state.pop("engine", None)
        st.rerun()

    # Mostra sempre o hardware que está rodando DE VERDADE — o detect_device
    # pode fazer fallback (ex.: GPU indisponível → CPU) e antes isso era invisível.
    if eng is not None:
        st.caption(f"🖥️ Hardware em uso: {eng.device_desc}")
        esperado = _DISPOSITIVO_ESPERADO.get(eng.device_pedido or "")
        if esperado and eng.device != esperado:
            st.warning(
                f"⚠️ **{eng.device_pedido}** não está disponível nesta máquina — "
                f"rodando em: **{eng.device_desc}**. "
                "Verifique o driver: no Linux/Intel o OpenVINO só lista a GPU com o "
                "compute runtime da Intel instalado (Arch: `sudo pacman -S "
                "intel-compute-runtime`; depois confira com "
                "`python -c \"import openvino as ov; print(ov.Core().available_devices)\"`)."
            )

    c1, c2, c3 = st.columns([1, 1, 2])
    iniciar = c1.button("▶️ Iniciar contagem", type="primary",
                        disabled=eng is not None and eng.running)
    parar = c2.button("⏹️ Parar", disabled=eng is None or not eng.running)

    if iniciar:
        try:
            _get_contador()  # valida dependências de visão antes de começar
        except ImportError:
            st.error("Dependências de visão computacional não instaladas "
                     "(torch / ultralytics / opencv / openvino).")
            st.code("pip install torch ultralytics opencv-python openvino", language="bash")
            return
        eng = _criar_engine(ARQUIVOS / video, modelo, None if device == "auto" else device,
                            tolerancia, sample_rate, img_size)
        eng.start()

    if parar and eng is not None:
        eng.stop()

    # Exibição ao vivo (fatia de ~4s por rerun; assim o "Parar" fica clicável)
    if eng is not None and (eng.running or eng.has_pending()):
        ph = st.empty()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4.0:
            frame = eng.get_frame(timeout=0.05)
            if frame is not None:
                ph.image(frame, channels="BGR")
            if not eng.running and not eng.has_pending():
                break
            time.sleep(0.02)
        st.rerun()

    if eng is not None:
        st.metric("👥 Pessoas únicas (ao vivo)", eng.live_count)
        if eng.done and eng.final_count is not None:
            st.session_state["contagem_final"] = eng.final_count
            st.success(f" Contagem concluída: **{eng.final_count}** aluno(s).")
            if st.button(" Ver o gasto do dia"):
                st.session_state["pagina"] = "Resultado"
                st.rerun()
        elif not eng.running and not eng.has_pending() and not eng.done:
            st.info("Configure e clique em **▶️ Iniciar contagem**.")

    elif "contagem_final" in st.session_state:
        st.metric(" Alunos (última contagem)", st.session_state["contagem_final"])
        if st.button(" Ver o gasto do dia"):
            st.session_state["pagina"] = "Resultado"
            st.rerun()

# ═══════════════════════════════════════════════════════════════════
#  TELA 2 — RESULTADO / GASTO DO DIA
# ═══════════════════════════════════════════════════════════════════

def tela_resultado() -> None:
    st.title(" Resultado do dia")
    st.caption("Produção estimada do dia (kg de alimento e litros de água) "
               "com base na contagem de alunos.")

    eng = _engine()
    if eng is not None and eng.done and eng.final_count is not None:
        st.session_state["contagem_final"] = eng.final_count

    # Geração dos dados (os botões SEMPRE regeneram, sobrescrevendo os JSONs)
    with st.expander(" Geração dos dados (PDFs)", expanded=not RECEITAS_JSON.exists()):
        faltando = []
        if not RECEITAS_JSON.exists():
            faltando.append("receitas.json")
        if not CARDAPIO_JSON.exists():
            faltando.append("cardapio.json")
        if faltando:
            st.caption(f"Faltando gerar: {', '.join(faltando)}")
        c_rec, c_car = st.columns(2)
        if c_rec.button("Extrair receitas do PDF"):
            try:
                n = gerar_receitas()
                carregar_receitas.clear()
                st.success(f"receitas.json gerado ({n} receitas).")
            except Exception as e:
                st.error(f"Falha ao extrair receitas: {e}")
        mes_sel = c_car.selectbox("Mês do cardápio", calculo.MESES_NOMES,
                                  index=date.today().month - 1)
        if c_car.button("Extrair cardápio do PDF"):
            try:
                n = gerar_cardapio(mes_sel)
                st.success(f"cardapio.json gerado ({n} dias).")
            except Exception as e:
                st.error(f"Falha ao extrair cardápio: {e}")

    if not RECEITAS_JSON.exists():
        st.warning("Gere as receitas (`Extrair receitas do PDF`) antes de calcular.")
        return

    banco = carregar_receitas(str(RECEITAS_JSON))

    default_alunos = st.session_state.get("contagem_final", 0)
    c_data, c_seg, c_alu = st.columns([2, 2, 1])
    data_dia = c_data.date_input(" Data", value=date.today())
    segmento = c_seg.selectbox(" Segmento", calculo.SEGMENTOS)
    alunos = c_alu.number_input(" Alunos", min_value=0,
                                value=int(default_alunos), step=1)
    if default_alunos:
        st.caption(f"Valor da última contagem: **{default_alunos}** (editável acima).")

    pratos_auto = calculo.pratos_do_dia(CARDAPIO_JSON, data_dia)
    opcoes = list(dict.fromkeys(pratos_auto + sorted(r["nome"] for r in banco.values())))
    pratos = st.multiselect(
        "Pratos do dia (automático pelo cardápio, editável)",
        options=opcoes, default=pratos_auto)

    if not pratos:
        st.warning("Selecione ao menos um prato.")
        return

    df = calculo.calcular_dia(alunos, pratos, segmento, banco)
    agua_total = df["Água (L)"].sum()
    kg_total = df["kg a produzir"].sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("👥 Alunos", f"{alunos}")
    m2.metric("🍽️ Pratos", f"{len(pratos)}")
    m3.metric("💧 Água total", f"{agua_total:.2f} L")
    m4.metric("🥣 Gasto do dia", f"{kg_total:.2f} kg")

    st.dataframe(df, width="stretch", hide_index=True)

    if (df["Avisos"] == "sem ficha técnica").any():
        st.warning("Alguns pratos não têm ficha técnica no receitas.json. "
                   "Ajuste a seleção ou gere novamente as receitas.")

    # Exportação
    st.divider()
    col_x, col_y = st.columns(2)
    fname = f"producao_{data_dia.strftime('%Y-%m-%d')}"
    col_x.download_button("📥 Baixar CSV", df.to_csv(index=False, sep=";", encoding="utf-8-sig"),
                           file_name=f"{fname}.csv", mime="text/csv", width="stretch")
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="producao")
    col_y.download_button("📥 Baixar Excel", buf.getvalue(),
                          file_name=f"{fname}.xlsx", width="stretch",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ═══════════════════════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="TCC — Refeitório", page_icon="", layout="wide")

if "pagina" not in st.session_state:
    st.session_state["pagina"] = "Contagem"

with st.sidebar:
    st.header(" Refeitório — TCC")
    pagina = st.radio("Navegação", ["Contagem", "Resultado"],
                      index=0 if st.session_state["pagina"] == "Contagem" else 1,
                      key="nav")
    st.session_state["pagina"] = pagina

if pagina == "Contagem":
    tela_contagem()
else:
    tela_resultado()
