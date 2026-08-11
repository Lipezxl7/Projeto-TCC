#!/usr/bin/env python3
"""
main.py - Orquestrador do TCC

FLUXO:
  1. Extrai cardapio do PDF (cardapio.py)
  2. Extrai receitas do PDF (receita.py)
  3. Contagem de pessoas via YOLO + Re-ID (contador.py) [opcional]
  4. Calcula producao e gera Excel para Power BI

CALCULO DE PRODUCAO (PBI):
  Para cada prato do cardapio:
    - Encontra a receita correspondente (fuzzy match + mapeamento manual)
    - Extrai rendimento, porcao e agua da receita
    - Calcula fator = (alunos * porcao_aluno_g) / rendimento_base_g
    - Calcula agua_total_l = (fator * agua_base_g) / 1000
    - Calcula total_a_fazer_kg = (alunos * porcao_aluno_g) / 1000

  Execucao separada por etapa:
    Manha (fund): python main.py --etapa fund --alunos 300 --data 12-05
    Tarde (med):  python main.py --etapa med  --alunos 200 --data 12-05

Saida: Excel 1 aba com 7 colunas para Power BI.

Exemplos:

    # Pipeline completo (fundamental)
    python main.py --cardapio-pdf arquivos/cardapio.pdf --mes jun --receita-pdf arquivos/receita.pdf \
        --etapa fund --alunos 300 --data 12-05 --no-window

    # So o calculo, reaproveitando JSONs ja extraidos
    python main.py --skip-cardapio --skip-receitas --skip-contador \
        --cardapio-json arquivos/cardapio.json --receitas-json arquivos/receitas.json \
        --etapa med --alunos 200 --data 12-05

    # Contagem de pessoas apenas
    # NB: --etapa/--alunos/--data sao required=True no argparse mas sao
    #     usados apenas pela etapa 4 (producao). Para um run de contagem
    #     pura, passe valores placeholder quaisquer.
    python main.py --skip-cardapio --skip-receitas --skip-producao \
        --video arquivos/video1.mp4 --device cuda \
        --etapa fund --alunos 0 --data 01-01
"""

import argparse
import json
import re
import sys
import unicodedata
import difflib
from pathlib import Path

import pandas as pd

from modulos import cardapio
from modulos import receita
from modulos import contador


def formatar_data_para_cardapio(data_str: str) -> str:
    """
    Converte a string recebida no formato DD-MM (ex.: "12-05")
    para o formato usado no cardápio JSON: "DD/mmm".
    Exemplo: "12-05" -> "12/mai"
    Não utiliza datetime; apenas split e mapeamento.
    """
    # dividir em dia e mês (aceita também "12/05" ou "12.05")
    separador = "-" if "-" in data_str else ("/" if "/" in data_str else ".")
    partes = data_str.split(separador)
    if len(partes) != 2:
        raise ValueError("Formato de data inválido, use DD-MM")
    dia, mes_num = partes[0].zfill(2), partes[1].zfill(2)

    mes_abrev = {
        "01": "jan", "02": "fev", "03": "mar", "04": "abr",
        "05": "mai", "06": "jun", "07": "jul", "08": "ago",
        "09": "set", "10": "out", "11": "nov", "12": "dez",
    }.get(mes_num)

    if not mes_abrev:
        raise ValueError(f"Mês desconhecido: {mes_num}")

    return f"{dia}/{mes_abrev}"


BASE_DIR = Path(__file__).parent

PORCAO_FUND_FALLBACK_G = 120
PORCAO_MED_FALLBACK_G = 140

LIMIAR_MATCH_MINIMO = 0.55


def normalizar(texto):
    texto = texto or ""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9 ]", " ", texto).upper()
    return re.sub(r"\s+", " ", texto).strip()


def nome_limpo_receita(nome):
    nome = nome or ""
    nome = re.split(r",| - |\(Receita", nome)[0]
    return nome.strip()


def parse_porcao_gramas(texto):
    if not texto:
        return None
    t = texto.strip().lower()
    m_cozido = re.search(r"\(([\d.,]+)\s*g\s*cozido\)", t)
    if m_cozido:
        return _parse_num(m_cozido.group(1))
    m_g = re.search(r"([\d.,]+)\s*g", t)
    if m_g:
        return _parse_num(m_g.group(1))
    m_num = re.search(r"([\d.,]+)", t)
    if m_num:
        val = _parse_num(m_num.group(1))
        if val and val > 0:
            return val
    return None


def _parse_num(s):
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def carregar_mapeamento_manual(caminho):
    p = Path(caminho)
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8") as f:
        bruto = json.load(f)
    return {normalizar(k): v for k, v in bruto.items()}


def encontrar_receita(prato_nome, receitas, mapeamento_manual, por_nome_normalizado):
    alvo = normalizar(prato_nome)

    if alvo in mapeamento_manual:
        nome_alvo = normalizar(mapeamento_manual[alvo])
        r = por_nome_normalizado.get(nome_alvo)
        if r is not None:
            return r

    palavras_stop = {"FERIADO", "PONTO FACULTATIVO", "RECESSO"}
    if alvo in palavras_stop:
        return None

    pontuados = []
    for r in receitas:
        cand = normalizar(nome_limpo_receita(r.get("nome", "")))
        if not cand:
            continue
        base = difflib.SequenceMatcher(None, alvo, cand).ratio()
        bonus = 0.0
        if alvo == cand:
            bonus = 0.4
        elif alvo in cand:
            frac = len(alvo) / len(cand)
            bonus = 0.15 * frac - 0.10 * (1 - frac)
        elif cand in alvo:
            frac = len(cand) / len(alvo)
            bonus = 0.15 * frac - 0.10 * (1 - frac)
        score = min(max(base + bonus, 0.0), 1.0)
        pontuados.append((score, r))

    if not pontuados:
        return None

    pontuados.sort(key=lambda x: x[0], reverse=True)
    melhor_score, melhor_receita = pontuados[0]

    if melhor_score < LIMIAR_MATCH_MINIMO:
        return None

    return melhor_receita


def extrair_agua_base_g(receita_dict):
    agua_total = 0.0
    for ing in receita_dict.get("ingredientes", []):
        nome_ing = ing.get("ingrediente", "")
        nome_norm = normalizar(nome_ing)
        if "AGUA" in nome_norm or "GUA" in nome_norm:
            qtd = ing.get("quantidade_g_ml")
            if qtd and qtd > 0:
                agua_total += qtd
    return agua_total if agua_total > 0 else None


def calcular_producao_pbi(dados_cardapio, receitas, alunos, etapa,
                          mapeamento_manual, data_str):
    """
    Gera linhas para Excel PBI com 7 colunas:
      Data | Prato | Rendimento_Base_g | Porcao_Aluno_g | Alunos | Agua_Total_L | Total_A_Fazer_kg

    Fórmulas:
      fator = (alunos * porcao_aluno_g) / rendimento_base_g
      agua_total_l = (fator * agua_base_g) / 1000
      total_a_fazer_kg = (alunos * porcao_aluno_g) / 1000

    O cálculo é feito apenas para a data informada em data_str (formato DD-MM).
    """
    target_data = formatar_data_para_cardapio(data_str)
    dias_para_processar = [d for d in dados_cardapio if d.get("data") == target_data]
    if not dias_para_processar:
        print(f"  Aviso: nenhum cardápio encontrado para a data {target_data}")
        return pd.DataFrame(), 0, 0

    por_nome_normalizado = {}
    for r in receitas:
        chave = normalizar(nome_limpo_receita(r.get("nome", "")))
        if chave:
            por_nome_normalizado[chave] = r

    palavras_stop = {"FERIADO", "PONTO FACULTATIVO", "RECESSO"}

    rows = []
    pratos_encontrados = 0
    pratos_nao_encontrados = 0

    pratos_vistos = set()

    for dia in dias_para_processar:
        for prato_nome in dia.get("pratos", []):
            if normalizar(prato_nome) in palavras_stop:
                continue

            prato_key = normalizar(prato_nome)
            if prato_key in pratos_vistos:
                continue
            pratos_vistos.add(prato_key)

            r = encontrar_receita(prato_nome, receitas, mapeamento_manual, por_nome_normalizado)

            if r is None:
                pratos_nao_encontrados += 1
                continue

            rendimento_g = receita.parse_rendimento_gramas(r.get("rendimento"))
            if rendimento_g and rendimento_g > 100000:
                rendimento_g = rendimento_g / 1000
            if not rendimento_g or rendimento_g <= 0:
                pratos_nao_encontrados += 1
                continue

            pratos_encontrados += 1

            if etapa == "fund":
                porcao_g = parse_porcao_gramas(r.get("porcao_fund")) or PORCAO_FUND_FALLBACK_G
            else:
                porcao_g = parse_porcao_gramas(r.get("porcao_em_eja")) or PORCAO_MED_FALLBACK_G

            fator = (alunos * porcao_g) / rendimento_g

            agua_base_g = extrair_agua_base_g(r)
            if agua_base_g is not None:
                agua_total_l = round((fator * agua_base_g) / 1000, 2)
            else:
                agua_total_l = 0

            total_a_fazer_kg = round((alunos * porcao_g) / 1000, 2)

            rows.append({
                "Prato": prato_nome,
                "Rendimento_Base_g": rendimento_g,
                "Porcao_Aluno_g": porcao_g,
                "Alunos": alunos,
                "Agua_Total_L": agua_total_l,
                "Total_A_Fazer_kg": total_a_fazer_kg,
            })

    df = pd.DataFrame(rows)
    return df, pratos_encontrados, pratos_nao_encontrados


def gerar_excel_pbi(df, caminho_saida):
    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Producao", index=False)
        ws = writer.sheets["Producao"]
        ws.freeze_panes = "A2"
        for col_cells in ws.columns:
            max_len = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col_cells
            )
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 3, 50)

    print(f"\nPlanilha PBI salva em: {caminho_saida}")


def rodar_cardapio(caminho_pdf, mes, salvar_json, salvar_csv):
    print("\n=== ETAPA 1/4: Extracao de Cardapio ===")
    if not Path(caminho_pdf).is_file():
        print(f"  Aviso: '{caminho_pdf}' nao encontrado.")
        return []
    dados = cardapio.executar_extracao(caminho_pdf=caminho_pdf, mes=mes,
                                        salvar_json=salvar_json, salvar_csv=salvar_csv)
    print(f"  {len(dados)} dia(s) extraido(s).")
    return dados


def rodar_receitas(caminho_pdf):
    print("\n=== ETAPA 2/4: Extracao de Receitas ===")
    if not Path(caminho_pdf).is_file():
        print(f"  Aviso: '{caminho_pdf}' nao encontrado.")
        return []
    receitas = receita.extract_recipes(caminho_pdf)
    receita.save_json(receitas, str(Path(caminho_pdf).with_suffix(".json")))
    receita.save_csv(receitas, str(Path(caminho_pdf).with_suffix(".csv")))
    print(f"  {len(receitas)} receita(s) extraida(s).")
    return receitas


def rodar_contador(videos, webcams, tolerance, sample_rate, img_size, device, model_name, show_window):
    print("\n=== ETAPA 3/4: Contagem de Pessoas ===")

    sources = []
    for v in videos or []:
        if not Path(v).is_file():
            print(f"  Aviso: video nao encontrado -> {v}")
            continue
        sources.append((False, v, Path(v).name))
    for idx in webcams or []:
        sources.append((True, idx, f"Webcam {idx}"))

    if not sources:
        print("  Nenhuma fonte de video/webcam informada.")
        return {"fontes": [], "pessoas_unicas": 0, "device_desc": "-"}

    resolved_device, device_desc = contador.detect_device(device)
    print(f"  hardware: {device_desc}")
    for _, _, label in sources:
        print(f"  fonte: {label}")

    total_unicas = contador.count_unique_people(
        sources, tolerance=tolerance, sample_rate=sample_rate, img_size=img_size,
        show_window=show_window, device=resolved_device, model_name=model_name,
    )
    print(f"  pessoas unicas: {total_unicas}")

    return {
        "fontes": [label for _, _, label in sources],
        "pessoas_unicas": total_unicas,
        "device_desc": device_desc,
    }


def _carregar_json(caminho):
    p = Path(caminho)
    if not p.is_file():
        print(f"  Aviso: '{caminho}' nao encontrado.")
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    p = argparse.ArgumentParser(description="TCC: cardapio + receitas + producao -> Excel PBI")

    p.add_argument("--cardapio-pdf", default="arquivos/cardapio.pdf")
    p.add_argument("--mes", default=None)
    p.add_argument("--skip-cardapio", action="store_true")
    p.add_argument("--cardapio-json", default="arquivos/cardapio.json")

    p.add_argument("--receita-pdf", default="arquivos/receita.pdf")
    p.add_argument("--skip-receitas", action="store_true")
    p.add_argument("--receitas-json", default="arquivos/receitas.json")

    p.add_argument("--video", nargs="*", default=[], metavar="ARQUIVO")
    p.add_argument("--webcam", type=int, nargs="?", const=0, action="append", metavar="IDX")
    p.add_argument("--skip-contador", action="store_true")
    p.add_argument("--tolerance", type=float, default=0.005)
    p.add_argument("--sample-rate", type=int, default=1)
    p.add_argument("--img-size", type=int, default=640,
                   choices=[320, 480, 640, 768, 1024, 1280, 1536, 2048])
    p.add_argument("--model", default="yolo26x.pt")
    p.add_argument("--device", default=None)
    p.add_argument("--no-window", action="store_true")

    p.add_argument("--etapa", choices=["fund", "med"], required=True,
                   help="Etapa do dia: fund (fundamental) ou med (medio)")
    p.add_argument("--alunos", type=int, required=True,
                   help="Quantidade de alunos presentes")
    p.add_argument("--data", type=str, required=True,
                   help="Data da produção no formato DD-MM (ex.: 12-05)")
    p.add_argument("--skip-producao", action="store_true")
    p.add_argument("--mapeamento", default="arquivos/mapeamento_manual.json")

    p.add_argument("--no-json", action="store_true")
    p.add_argument("--no-csv", action="store_true")
    p.add_argument("--output", default="arquivos/planilha.xlsx")

    return p.parse_args()


def main():
    args = parse_args()

    if args.skip_cardapio:
        dados_cardapio = _carregar_json(args.cardapio_json)
    else:
        dados_cardapio = rodar_cardapio(args.cardapio_pdf, args.mes,
                                         salvar_json=not args.no_json, salvar_csv=not args.no_csv)

    if args.skip_receitas:
        receitas = _carregar_json(args.receitas_json)
    else:
        receitas = rodar_receitas(args.receita_pdf)

    contagem = {"fontes": [], "pessoas_unicas": 0, "device_desc": "-"}
    if not args.skip_contador:
        contagem = rodar_contador(
            videos=args.video, webcams=args.webcam, tolerance=args.tolerance,
            sample_rate=args.sample_rate, img_size=args.img_size, device=args.device,
            model_name=args.model, show_window=not args.no_window,
        )

    if not args.skip_producao:
        print("\n=== ETAPA 4/4: Calculo de Producao PBI ===")
        if args.alunos <= 0:
            print("  Aviso: nenhum aluno informado, calculo sera zerado.")

        mapeamento_manual = carregar_mapeamento_manual(args.mapeamento)
        df, pratos_ok, pratos_fail = calcular_producao_pbi(
            dados_cardapio, receitas, args.alunos, args.etapa,
            mapeamento_manual, args.data
        )
        print(f"  {pratos_ok} prato(s) com receita, {pratos_fail} sem receita (ignorados).")

        gerar_excel_pbi(df, args.output)


if __name__ == "__main__":
    main()
