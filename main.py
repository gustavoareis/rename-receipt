#!/usr/bin/env python3
"""
Renomeador de Recibos (Ceará Sem Fome)
========================================
Lê PDFs escaneados dentro da pasta "recibos_entrada", faz OCR em cada um,
extrai o NOME da pessoa e o MÊS/ANO do recibo, e gera cópias renomeadas
no padrão:

    RECIBO <MES> <NOME>.pdf

As cópias renomeadas vão para a pasta "recibos_renomeados" (os arquivos
originais NÃO são apagados nem alterados).

REQUISITOS (rodar uma vez, no terminal):
    sudo apt-get install tesseract-ocr tesseract-ocr-por poppler-utils
    pip install pdf2image pytesseract pillow

COMO USAR:
    1. Coloque os PDFs escaneados dentro da pasta "recibos_entrada"
       (ela é criada automaticamente na primeira execução, se não existir).
    2. Rode:  python3 renomear_recibos.py
    3. Os arquivos renomeados aparecem em "recibos_renomeados".
    4. Confira o resumo impresso no final — PDFs em que o nome ou o mês
       não puderam ser lidos automaticamente ficam listados em
       "revisar_manualmente" e precisam ser renomeados à mão.
"""

import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from pdf2image import convert_from_path
import pytesseract

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

PASTA_ENTRADA = Path("recibos_entrada")
PASTA_SAIDA = Path("recibos_renomeados")
PASTA_REVISAR = PASTA_SAIDA / "revisar_manualmente"

DPI_OCR = 300          # resolução usada para converter o PDF em imagem antes do OCR
IDIOMA_OCR = "por"      # português

# --- SÓ NO WINDOWS: se o script não achar o Tesseract/Poppler sozinho,
# preencha os caminhos abaixo (troque pelo caminho real da sua instalação)
# e depois remova o "#" do começo da linha para ativar.
# Exemplo de caminho do Tesseract:
# CAMINHO_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Exemplo de caminho da pasta "bin" do Poppler:
# CAMINHO_POPPLER = r"C:\poppler-24.08.0\Library\bin"
CAMINHO_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CAMINHO_POPPLER = r"C:\poppler\Library\bin"

if CAMINHO_TESSERACT:
    pytesseract.pytesseract.tesseract_cmd = CAMINHO_TESSERACT

MESES = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO",
]

# ---------------------------------------------------------------------------
# FUNÇÕES
# ---------------------------------------------------------------------------

def ocr_pdf(caminho_pdf: Path) -> str:
    """Converte todas as páginas do PDF em imagem e roda OCR, juntando o texto."""
    kwargs = {"dpi": DPI_OCR}
    if CAMINHO_POPPLER:
        kwargs["poppler_path"] = CAMINHO_POPPLER
    imagens = convert_from_path(str(caminho_pdf), **kwargs)
    texto_completo = ""
    for imagem in imagens:
        texto_completo += pytesseract.image_to_string(imagem, lang=IDIOMA_OCR)
        texto_completo += "\n"
    return texto_completo


def normalizar(texto: str) -> str:
    """Remove acentos e deixa em maiúsculas, para facilitar comparações."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper()


def extrair_nome(texto: str) -> str | None:
    """
    Procura o padrão 'EU, <NOME>, AGENTE...' (com pequenas variações que o
    OCR pode gerar) e devolve o nome já limpo.
    """
    padroes = [
        r"EU,\s*([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ\s]{4,80}?),\s*AGENTE",
        r"EU,\s*([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ\s]{4,80}?),\s*(?:RG|CPF)",
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.IGNORECASE)
        if m:
            nome = m.group(1)
            nome = re.sub(r"\s+", " ", nome).strip()
            return nome.upper()
    return None


def extrair_mes(texto: str) -> str | None:
    """
    Procura o padrão 'MÊS DE <MES>/<ANO>' (tolerando erros de OCR em
    acentos) e devolve o nome do mês em maiúsculas, sem acento
    (ex: 'AGOSTO'). Se o mês reconhecido não bater com a lista de meses
    válidos, tenta aproximar pela palavra mais parecida.
    """
    texto_norm = normalizar(texto)
    m = re.search(r"MES\s+DE\s+([A-Z]+)\s*/\s*(\d{4})", texto_norm)
    if not m:
        return None
    mes_bruto = m.group(1)

    if mes_bruto in [normalizar(mes) for mes in MESES]:
        idx = [normalizar(mes) for mes in MESES].index(mes_bruto)
        return MESES[idx]

    # fallback: pega o mês da lista cujo início bate com o texto lido
    for mes in MESES:
        if normalizar(mes)[:4] == mes_bruto[:4]:
            return mes

    return mes_bruto  # devolve como veio, para revisão manual não perder a pista


def montar_nome_arquivo(mes: str, nome: str) -> str:
    """Monta o nome final do arquivo, removendo caracteres inválidos."""
    base = f"RECIBO {mes} {nome}"
    base = re.sub(r'[\\/*?:"<>|]', "", base)   # caracteres proibidos em nomes de arquivo
    base = re.sub(r"\s+", " ", base).strip()
    return base + ".pdf"


def caminho_sem_conflito(caminho: Path) -> Path:
    """Se já existir um arquivo com esse nome, adiciona (2), (3)... até ficar livre."""
    if not caminho.exists():
        return caminho
    contador = 2
    while True:
        candidato = caminho.with_name(f"{caminho.stem} ({contador}){caminho.suffix}")
        if not candidato.exists():
            return candidato
        contador += 1


# ---------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------------

def main():
    PASTA_ENTRADA.mkdir(exist_ok=True)
    PASTA_SAIDA.mkdir(exist_ok=True)
    PASTA_REVISAR.mkdir(exist_ok=True)

    pdfs = sorted(PASTA_ENTRADA.glob("*.pdf")) + sorted(PASTA_ENTRADA.glob("*.PDF"))

    if not pdfs:
        print(f"Nenhum PDF encontrado em '{PASTA_ENTRADA}/'. Coloque os arquivos lá e rode de novo.")
        return

    sucesso, falhas = [], []

    for caminho_pdf in pdfs:
        print(f"Processando: {caminho_pdf.name} ...", end=" ")
        try:
            texto = ocr_pdf(caminho_pdf)
        except Exception as e:
            print(f"ERRO no OCR: {type(e).__name__}: {e}")
            falhas.append((caminho_pdf, f"erro de OCR: {e}"))
            shutil.copy2(caminho_pdf, PASTA_REVISAR / caminho_pdf.name)
            continue

        nome = extrair_nome(texto)
        mes = extrair_mes(texto)

        if not nome or not mes:
            motivo = []
            if not nome:
                motivo.append("nome não encontrado")
            if not mes:
                motivo.append("mês não encontrado")
            print(f"NÃO IDENTIFICADO ({', '.join(motivo)})")
            falhas.append((caminho_pdf, ", ".join(motivo)))
            shutil.copy2(caminho_pdf, PASTA_REVISAR / caminho_pdf.name)
            continue

        novo_nome = montar_nome_arquivo(mes, nome)
        destino = caminho_sem_conflito(PASTA_SAIDA / novo_nome)
        shutil.copy2(caminho_pdf, destino)
        print(f"OK -> {destino.name}")
        sucesso.append((caminho_pdf.name, destino.name))

    # -----------------------------------------------------------------
    # RESUMO
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Concluído: {len(sucesso)} renomeados com sucesso, {len(falhas)} para revisar manualmente.")
    if falhas:
        print(f"\nOs originais que não puderam ser lidos automaticamente foram copiados para:")
        print(f"  {PASTA_REVISAR}/")
        print("Motivo de cada um:")
        for caminho, motivo in falhas:
            print(f"  - {caminho.name}: {motivo}")
    print(f"\nArquivos renomeados estão em: {PASTA_SAIDA}/")


if __name__ == "__main__":
    main()