'''CARDAPIO.PY
FUNCIONALIDADES DE EXTRAÇÃO DE CARDÁPIO DO PDF

O QUE ELE FAZ:
1. Lê o PDF do cardápio.
2. identifica as datas e os pratos.
3. Salva os dados em JSON e CSV (mesmo padrão de receita.py).

Erros de leitura sobem como exceção — o chamador decide como mostrar
(o app.py usa st.error, o CLI imprime e sai com código 1).
'''


import pdfplumber
import json
import re
import os
import csv
import argparse
import sys


def save_json(dados_cardapio, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dados_cardapio, f, indent=2, ensure_ascii=False)
    print(f"JSON saved: {output_path} ({len(dados_cardapio)} dias)")


def save_csv(dados_cardapio, output_path):
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["data", "prato"])
        for dia in dados_cardapio:
            pratos = dia.get("pratos") or [""]
            for prato in pratos:
                writer.writerow([dia.get("data", ""), prato])
    print(f"CSV saved: {output_path} ({len(dados_cardapio)} dias)")


def executar_extracao(caminho_pdf="cardapio.pdf", arquivo_saida=None, mes=None,
                      salvar_json=True, salvar_csv=True):
    """
    Extrai o cardápio do PDF informado.

    mes: mês a filtrar (ex: "jun"). Se None, pergunta interativamente (input()).
    salvar_json / salvar_csv: se True, grava o resultado em .json / .csv
        (mesma base de nome, derivada de caminho_pdf ou de arquivo_saida).

    Lança exceção se o PDF não puder ser lido.

    Retorna: lista de dicts [{"data": "...", "pratos": [...]}, ...]
    """
    if arquivo_saida is None:
        base, _ = os.path.splitext(caminho_pdf)
        arquivo_saida = base + ".json"
    base_saida, _ = os.path.splitext(arquivo_saida)
    caminho_json = base_saida + ".json"
    caminho_csv = base_saida + ".csv"

    if mes is None:
        mes = input("qual e o mes do cardapio? exemplo (janeiro = jan): ")

    print("⏳ [Cardápio] Lendo o PDF do cardápio...")
    dados_cardapio = []
    indice_por_data = {}  # mapeia "data" -> índice em dados_cardapio, para agrupar os pratos

    # Regex detecta QUALQUER data (dia/mês): 1-2 dígitos + / ou - + 3 letras
    # Exemplos: 1/jan, 01/Fev, 1-MAR, 01/Abr, etc.
    data_regex = re.compile(r"(\d{1,2})[/-]([A-Za-z]{3})", re.IGNORECASE)

    # Mapeia abreviação (minúscula) para número do mês
    # Suporta tanto português (jan, fev, mar...) quanto inglês (jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec)
    mes_map = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
        # Inglês
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    # Mapeia entrada do usuário (pt) para inglês do PDF
    mes_pt_para_en = {
        "jan": "jan", "fev": "feb", "mar": "mar", "abr": "apr", "mai": "may", "jun": "jun",
        "jul": "jul", "ago": "aug", "set": "sep", "out": "oct", "nov": "nov", "dez": "dec"
    }
    
    mes_lower = mes.lower()
    # Converte entrada pt para en se necessário
    mes_en = mes_pt_para_en.get(mes_lower, mes_lower)
    mes_num = mes_map.get(mes_lower, 0)

    def _celula_e_do_mes(celula):
        """Verifica se a célula contém uma data do mês solicitado."""
        if not isinstance(celula, str):
            return False
        m = data_regex.search(celula)
        if not m:
            return False
        # m.group(2) = mês (3 letras) - vem em inglês do PDF (Jan, Feb, Mar...)
        mes_celula = m.group(2).lower()
        # Compara com a versão em inglês do mês solicitado
        return mes_celula == mes_en

    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            tabelas = pagina.extract_tables()
            if not tabelas:
                continue

            for tabela in tabelas:
                # Encontra a linha que contém as datas (geralmente linha índice 1)
                data_row_idx = None
                for r_idx, linha in enumerate(tabela):
                    if any(_celula_e_do_mes(c) for c in linha):
                        data_row_idx = r_idx
                        break

                if data_row_idx is None:
                    continue

                # Processa as colunas da linha de datas
                for i, celula in enumerate(tabela[data_row_idx]):
                    if not _celula_e_do_mes(celula):
                        continue

                    # Pega APENAS o almoço (segunda refeição) - índice data_row_idx + 2
                    # Ordem no PDF: Café da manhã (linha +1), Almoço (linha +2), Lanche (linha +3)
                    ref_row_idx = data_row_idx + 2
                    if ref_row_idx < len(tabela):
                        ref_linha = tabela[ref_row_idx]
                        if i < len(ref_linha):
                            refeicao = ref_linha[i]
                            if refeicao:
                                texto_bruto = str(refeicao).strip()

                                # 1. Remove os parênteses contendo os ingredientes primeiro
                                texto_sem_ingredientes = re.sub(r'\(.*?\)', '', texto_bruto, flags=re.DOTALL)

                                # Divide em linhas brutas limpas
                                linhas_brutas = [l.strip() for l in texto_sem_ingredientes.split('\n') if l.strip()]

                                # 2. TRATAMENTO DE QUEBRA DE LINHA DA MESMA COMIDA (ex: COM REPOLHO)
                                linhas_corrigidas = []
                                for l in linhas_brutas:
                                    if not linhas_corrigidas:
                                        linhas_corrigidas.append(l)
                                    else:
                                        ultima_linha = linhas_corrigidas[-1].upper()
                                        if re.search(r'\b(COM|DE|AO|A|EM|E|OU)$', ultima_linha):
                                            linhas_corrigidas[-1] = linhas_corrigidas[-1] + " " + l
                                        else:
                                            linhas_corrigidas.append(l)

                                # 3. Processa e separa caso haja mais de um prato na mesma linha por conectivos
                                for linha_prato in linhas_corrigidas:
                                    pratos_divididos = re.split(r'\s+E\s+|\s+OU\s+|,', linha_prato, flags=re.IGNORECASE)

                                    for prato_bruto in pratos_divididos:
                                        prato_final = " ".join(prato_bruto.split()).upper().strip()

                                        if prato_final and len(prato_final) > 2 and "REFEIÇÃO" not in prato_final:
                                            if celula not in indice_por_data:
                                                indice_por_data[celula] = len(dados_cardapio)
                                                dados_cardapio.append({
                                                    "data": celula,
                                                    "pratos": []
                                                })
                                            idx = indice_por_data[celula]
                                            if prato_final not in dados_cardapio[idx]["pratos"]:
                                                dados_cardapio[idx]["pratos"].append(prato_final)

    if salvar_json:
        save_json(dados_cardapio, caminho_json)
    if salvar_csv:
        save_csv(dados_cardapio, caminho_csv)
    if not salvar_json and not salvar_csv:
        print(f"✔ [Cardápio] Extrato concluído ({len(dados_cardapio)} dias).")

    return dados_cardapio


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrai dados do cardápio em PDF para JSON e CSV.")
    parser.add_argument(
        "caminho_pdf",
        nargs="?",
        default="cardapio.pdf",
        help="Caminho para o arquivo PDF do cardápio (padrão: cardapio.pdf)"
    )
    parser.add_argument(
        "--mes",
        default=None,
        help="Mês a filtrar (jan, fev, ..., dez). Se omitido, pergunta interativamente."
    )
    args = parser.parse_args()

    try:
        executar_extracao(caminho_pdf=args.caminho_pdf, mes=args.mes)
    except Exception as e:
        print(f"❌ [Cardápio] Erro na leitura: {e}")
        sys.exit(1)