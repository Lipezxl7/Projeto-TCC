'''CALCULO.PY
LÓGICA PURA DA TELA "RESULTADO" (fonte de verdade — NÃO importa Streamlit)

O QUE ELE FAZ:
1. Parsing de quantidades em texto livre (formato pt-BR) -> gramas.
2. Normalização de datas em vários formatos -> chave 'dd/mm'.
3. Busca de receita por slug exato ou sobreposição de tokens (>= 50%).
4. Cálculo da produção do dia: kg de alimento e litros de água.

O app.py só adiciona por cima os decorators de cache (@st.cache_data) e
os caminhos de `arquivos/`; toda a regra de negócio mora aqui.
'''

import json
import re
import unicodedata
from datetime import date

import pandas as pd

SEGMENTOS = ["Fundamental", "Ensino Médio"]
SEG_CAMPO = {"Fundamental": "porcao_fund_g", "Ensino Médio": "porcao_em_g"}
MESES = {m: i + 1 for i, m in enumerate(
    ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"])}
MESES_NOMES = list(MESES.keys())

STOP = {"de", "do", "da", "com", "ao", "a", "e", "em", "no", "na", "the"}


def sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c))


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(texto).lower())


def tokens(texto: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", sem_acento(texto).lower()) if t and t not in STOP}


def numero_br(num: str) -> float:
    """Converte número no formato pt-BR para float.

    Vírgula é sempre decimal ('1,5' -> 1.5). Ponto é separador de milhar
    quando seguido de exatamente 3 dígitos ('1.500' -> 1500,
    '1.234.567' -> 1234567) e decimal nos demais casos ('1.5' -> 1.5,
    '0.75' -> 0.75). Isso evita ler '1.5 kg' como 15 g.
    """
    s = num.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    # sem vírgula: remove apenas os pontos de milhar (seguem exatamente 3 dígitos)
    s = re.sub(r"\.(?=\d{3}(\D|$))", "", s)
    return float(s)


def parse_gramas(texto) -> float:
    """'12kg' -> 12000 | '50g (120g cozido)' -> 120 (prefere o parêntese)."""
    if texto is None:
        return 0.0
    if isinstance(texto, (int, float)):
        return float(texto)
    s = str(texto).lower()
    m = re.search(r"\((\d[\d.,]*)\s*(kg|g|gramas|l|litros|ml)?", s) or \
        re.search(r"(\d[\d.,]*)\s*(kg|g|gramas|l|litros|ml)?", s)
    if not m:
        return 0.0
    try:
        valor = numero_br(m.group(1))
    except ValueError:
        return 0.0
    if (m.group(2) or "").strip() in ("kg", "l", "litros"):
        valor *= 1000.0
    return valor


def carregar_receitas(caminho: str) -> dict[str, dict]:
    """Lê o receitas.json e normaliza as fichas técnicas, indexadas por slug do nome."""
    with open(caminho, "r", encoding="utf-8") as f:
        brutas = json.load(f)
    banco = {}
    for r in brutas:
        ings = []
        for ing in r.get("ingredientes", []):
            qtd = ing.get("quantidade_g_ml")
            if qtd is None:
                qtd = ing.get("peso_base_g")
            ings.append({
                "nome": ing.get("ingrediente") or ing.get("nome") or "",
                "qtd": float(qtd) if isinstance(qtd, (int, float)) else parse_gramas(qtd),
            })
        chave = slug(r.get("nome", ""))
        if chave:
            banco[chave] = {
                "nome": r.get("nome", ""),
                "rendimento_g": parse_gramas(r.get("rendimento", "")),
                "porcao_fund_g": parse_gramas(r.get("porcao_fund", "")),
                "porcao_em_g": parse_gramas(r.get("porcao_em_eja", "")),
                "ingredientes": ings,
            }
    return banco


def buscar_receita(banco: dict, prato: str) -> dict | None:
    """Match exato por slug ou maior sobreposição de tokens (>= 50%)."""
    chave = slug(prato)
    if chave in banco:
        return banco[chave]
    toks = tokens(prato)
    melhor, melhor_score = None, 0.0
    for rec in banco.values():
        inter = len(toks & tokens(rec["nome"]))
        if inter:
            score = inter / max(len(toks), 1)
            if score > melhor_score:
                melhor, melhor_score = rec, score
    return melhor if melhor_score >= 0.5 else None


def normalizar_data(valor) -> str:
    """Qualquer data -> chave 'dd/mm' do cardápio."""
    if isinstance(valor, date):
        return valor.strftime("%d/%m")
    s = str(valor).strip()
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})[/-](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})/([a-zç]+)", s, re.IGNORECASE)
    if m and m.group(2).lower().rstrip(".") in MESES:
        return f"{int(m.group(1)):02d}/{MESES[m.group(2).lower().rstrip('.')]:02d}"
    return ""


def pratos_do_dia(caminho_cardapio, data) -> list[str]:
    """Pratos do cardápio para a data (ou [] se não houver cardápio/data)."""
    try:
        with open(caminho_cardapio, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    chave = normalizar_data(data)
    for d in dados:
        if normalizar_data(d.get("data", "")) == chave:
            return [p for p in d.get("pratos", []) if p and "REFEIÇÃO" not in p.upper()]
    return []


def eh_agua(nome: str) -> bool:
    n = sem_acento(nome).lower()
    return "agua" in n


def calcular_dia(alunos: int, pratos: list[str], segmento: str,
                 banco: dict) -> pd.DataFrame:
    """Linhas: prato, receita, porção, fator, água (L), kg a produzir, avisos.

    água (L): soma a água de TODOS os ingredientes 'água' da receita
    (cada um escalado pelo fator). kg a produzir = porção × alunos / 1000.
    """
    campo = SEG_CAMPO.get(segmento, "porcao_em_g")
    linhas = []
    for nome in pratos:
        rec = buscar_receita(banco, nome)
        if rec is None:
            linhas.append({"Prato": nome, "Receita": "—", "Porção (g)": 0.0, "Fator": 0.0,
                           "Água (L)": 0.0, "kg a produzir": 0.0, "Avisos": "sem ficha técnica"})
            continue

        porcao = rec.get(campo) or 0.0
        rend = rec.get("rendimento_g") or 0.0
        fator = (porcao * alunos) / rend if porcao > 0 and rend > 0 else 0.0
        kg_total = porcao * alunos / 1000.0

        agua = 0.0
        for ing in rec.get("ingredientes", []):
            qtd = float(ing.get("qtd") or 0.0)
            if eh_agua(ing["nome"]):
                agua += qtd * fator / 1000.0

        linhas.append({"Prato": nome, "Receita": rec["nome"], "Porção (g)": porcao,
                       "Fator": round(fator, 2), "Água (L)": round(agua, 2),
                       "kg a produzir": round(kg_total, 2), "Avisos": ""})

    return pd.DataFrame(linhas)
