#!/usr/bin/env python3
import pdfplumber
import json
import re
import csv
import argparse
import sys
from pathlib import Path


def clean_text(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_number(text):
    if text is None:
        return None
    cleaned = clean_text(text)
    m = re.search(r"[\d]+[\d.,]*", cleaned)
    if not m:
        return None
    num_str = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(num_str)
    except (ValueError, TypeError):
        return None


def parse_footer_row(row_text, footer):
    if "Rendimento" in row_text:
        rm = re.search(r"Rendimento\s*\(?\s*g?\s*\)?:\s*(\d[\d.,]*\s*(?:kg|g|gramas|KG|Kg|litros|alunos)?)", row_text, re.IGNORECASE)
        if rm:
            footer["rendimento"] = clean_text(rm.group(1))
        alunos_rm = re.search(r"Rendimento:\s*\d+\s*alunos\s+Peso da por[çc][aã]o:\s*([\d,]+\s*g(?:\s+\w+)?)", row_text, re.IGNORECASE)
        if alunos_rm:
            footer["porcao_fund"] = clean_text(alunos_rm.group(1))
        alunos_em = re.search(r"EJA:\s*Rendimento:\s*\d+\s*alunos\s+Peso da por[çc][aã]o\s*\(?g?\)?:\s*([\d,]+\s*g(?:\s+\w+)?)", row_text, re.IGNORECASE)
        if alunos_em:
            footer["porcao_em_eja"] = clean_text(alunos_em.group(1))
    if "Peso da por" in row_text:
        if "porcao_fund" not in footer:
            fm = re.search(r"Fund[^:]*:\s*(.*?)(?:\s*Peso|\s*EM|\s*Tempo|$)", row_text, re.IGNORECASE)
            if fm:
                raw = clean_text(fm.group(1))
                gm = re.search(r"([\d,]+\s*(?:\(.*?\))?\s*g(?:\s*\(.*?\))?)", raw, re.IGNORECASE)
                if not gm:
                    gm = re.search(r"(aprox\.?\s*[\d,]+\s*(?:a\s*[\d,]+)?\s*g)", raw, re.IGNORECASE)
                if not gm:
                    gm = re.search(r"([\d,]+)", raw, re.IGNORECASE)
                if gm:
                    footer["porcao_fund"] = clean_text(gm.group(1))
        if "porcao_em_eja" not in footer:
            em = re.search(r"EM[^:]*:\s*(.*?)(?:\s*Tempo|\s*Medida|$)", row_text, re.IGNORECASE)
            if em:
                raw = clean_text(em.group(1))
                gm = re.search(r"([\d,]+\s*(?:\(.*?\))?\s*g(?:\s*\(.*?\))?)", raw, re.IGNORECASE)
                if not gm:
                    gm = re.search(r"(aprox\.?\s*[\d,]+\s*(?:a\s*[\d,]+)?\s*g)", raw, re.IGNORECASE)
                if not gm:
                    gm = re.search(r"([\d,]+)", raw, re.IGNORECASE)
                if gm:
                    footer["porcao_em_eja"] = clean_text(gm.group(1))
    if "Tempo de preparo" in row_text:
        tm = re.search(
            r"Tempo de preparo:\s*(\d+\s*(?:h|hora|horas|minuto|minutos|min)(?:\s*e\s*\d+\s*(?:minuto|minutos|min|h|hora|horas))?)",
            row_text, re.IGNORECASE
        )
        if tm:
            footer["tempo_preparo"] = clean_text(tm.group(1))
    if "Medida casei" in row_text:
        if "medida_caseira_fund" not in footer:
            mf = re.search(r"Fund[^:]*:\s*(.+?)(?:\s*Medida caseira EM|$)", row_text, re.IGNORECASE)
            if mf and clean_text(mf.group(1)):
                footer["medida_caseira_fund"] = clean_text(mf.group(1))
        if "medida_caseira_em_eja" not in footer:
            me = re.search(r"Medida caseira EM[^:]*:\s*(.+?)$", row_text, re.IGNORECASE)
            if me and clean_text(me.group(1)):
                footer["medida_caseira_em_eja"] = clean_text(me.group(1))


def extract_from_table(table):
    ingredientes = []
    footer = {}
    header_found = False

    for row in table:
        cells = [(c.replace("\n", " ").strip() if c else "") for c in row]
        row_text = " ".join(cells)
        row_norm = re.sub(r"\s+", "", row_text.upper())

        if "INGREDIENTE" in row_norm or "INGREDENTE" in row_norm:
            header_found = True
            continue

        is_footer = any(kw in row_text for kw in ["Rendimento", "Peso da por", "Medida casei", "Tempo de preparo"])
        if is_footer:
            parse_footer_row(row_text, footer)
            continue

        if not header_found:
            continue

        is_skip = any(kw in row_text for kw in ["Total", "Porção", "Modo de preparo", "Foto"])
        if is_skip:
            continue

        name = cells[0] if cells else ""
        if not name:
            continue
        ingredientes.append({
            "ingrediente": name,
            "quantidade_g_ml": parse_number(cells[1]) if len(cells) > 1 else None,
            "medida_caseira": cells[2] if len(cells) > 2 else "",
        })

    return ingredientes, footer


def extract_recipes(pdf_path):
    recipes = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            text_clean = clean_text(text)

            if not re.search(r"Nome da prepara[çc][aã]o", text_clean):
                continue
            if re.search(r"Nome da prepara[çc][aã]o.*\.\.\.+\s*\d", text_clean):
                continue

            nome_match = re.search(r"Nome da prepara[çc][aã]o:\s*(.+)", text)
            recipe_name = clean_text(nome_match.group(1)) if nome_match else ""
            recipe_name = re.sub(r"\s*\.\.\..*$", "", recipe_name)

            etapa_match = re.search(r"ETAPA DE ENSINO:\s*(.+?)(?:\n|TIPO)", text)
            etapa = clean_text(etapa_match.group(1)) if etapa_match else ""

            tipo_match = re.search(r"TIPO DE ATENDIMENTO:\s*(.+?)(?:\n|FAIXA)", text)
            tipo_atendimento = clean_text(tipo_match.group(1)) if tipo_match else ""

            faixa_match = re.search(r"FAIXA ET[aÁ]RIA:\s*(.+?)(?:\n|Nome)", text)
            faixa_etaria = clean_text(faixa_match.group(1)) if faixa_match else ""

            modo_match = re.search(r"Modo de preparo:(.+?)(?:Rendimento|Peso da por)", text, re.DOTALL)
            modo_preparo = clean_text(modo_match.group(1)) if modo_match else ""

            ingredientes = []
            footer = {}
            for table in page.extract_tables():
                ings, tfoot = extract_from_table(table)
                ingredientes.extend(ings)
                footer.update({k: v for k, v in tfoot.items() if v})

            recipes.append({
                "pagina": page_num,
                "nome": recipe_name,
                "etapa_ensino": etapa,
                "tipo_atendimento": tipo_atendimento,
                "faixa_etaria": faixa_etaria,
                "ingredientes": ingredientes,
                "modo_preparo": modo_preparo,
                "rendimento": footer.get("rendimento", ""),
                "tempo_preparo": footer.get("tempo_preparo", ""),
                "porcao_fund": footer.get("porcao_fund", ""),
                "porcao_em_eja": footer.get("porcao_em_eja", ""),
                "medida_caseira_fund": footer.get("medida_caseira_fund", ""),
                "medida_caseira_em_eja": footer.get("medida_caseira_em_eja", ""),
            })

    return recipes


def save_json(recipes, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=2)
    print(f"JSON saved: {output_path} ({len(recipes)} recipes)")


def save_csv(recipes, output_path):
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pagina", "nome", "etapa_ensino", "tipo_atendimento",
            "faixa_etaria", "ingrediente", "quantidade_g_ml",
            "medida_caseira", "modo_preparo", "rendimento",
            "tempo_preparo", "porcao_fund", "porcao_em_eja",
            "medida_caseira_fund", "medida_caseira_em_eja",
        ])
        for recipe in recipes:
            if recipe["ingredientes"]:
                for ing in recipe["ingredientes"]:
                    writer.writerow([
                        recipe["pagina"], recipe["nome"],
                        recipe["etapa_ensino"], recipe["tipo_atendimento"],
                        recipe["faixa_etaria"],
                        ing["ingrediente"], ing["quantidade_g_ml"],
                        ing["medida_caseira"],
                        recipe["modo_preparo"], recipe["rendimento"],
                        recipe["tempo_preparo"], recipe["porcao_fund"],
                        recipe["porcao_em_eja"],
                        recipe["medida_caseira_fund"],
                        recipe["medida_caseira_em_eja"],
                    ])
            else:
                writer.writerow([
                    recipe["pagina"], recipe["nome"],
                    recipe["etapa_ensino"], recipe["tipo_atendimento"],
                    recipe["faixa_etaria"], "", "", "",
                    recipe["modo_preparo"], recipe["rendimento"],
                    recipe["tempo_preparo"], recipe["porcao_fund"],
                    recipe["porcao_em_eja"], recipe["medida_caseira_fund"],
                    recipe["medida_caseira_em_eja"],
                ])
    print(f"CSV saved: {output_path} ({len(recipes)} recipes)")


def main():
    parser = argparse.ArgumentParser(
        description="Extrai as receitas do PDF para JSON e CSV.")
    parser.add_argument(
        "caminho_pdf", nargs="?", default=None,
        help="Caminho para o PDF das receitas (padrão: arquivos/receita.pdf)")
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parent.parent  # raiz do repositório
    if args.caminho_pdf:
        pdf_path = Path(args.caminho_pdf)
        json_path = pdf_path.with_suffix(".json")
    else:
        pdf_path = raiz / "arquivos" / "receita.pdf"
        json_path = raiz / "arquivos" / "receitas.json"  # nome que o app.py lê
    csv_path = json_path.with_suffix(".csv")

    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Scraping: {pdf_path}")
    recipes = extract_recipes(str(pdf_path))
    print(f"Found {len(recipes)} recipes")

    save_json(recipes, json_path)
    save_csv(recipes, csv_path)
    print("Done!")


if __name__ == "__main__":
    main()