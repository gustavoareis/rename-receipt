#!/usr/bin/env python3
"""
Renomeador de Recibos (Ceará Sem Fome)
========================================
Lê PDFs escaneados dentro da pasta "recibos_entrada", faz OCR PÁGINA POR
PÁGINA em cada um, identifica em quais páginas começa um novo recibo
(procurando o NOME da pessoa e o MÊS/ANO), e gera cópias renomeadas no
padrão:

    RECIBO <MES> <NOME>.pdf

As cópias renomeadas vão para a pasta "recibos_renomeados" (os arquivos
originais NÃO são apagados nem alterados).

NOVIDADE: se um único PDF de entrada contiver MAIS DE UM recibo (por
exemplo, o recibo da Maria de fevereiro seguido do recibo do João de
março, tudo no mesmo arquivo escaneado), o script agora detecta isso
página a página e separa automaticamente em PDFs individuais — um para
cada recibo encontrado, incluindo as páginas de anexo/comprovante que
vierem logo depois de cada recibo (até a página onde começa o próximo
recibo).

REQUISITOS (rodar uma vez, no terminal):
    sudo apt-get install tesseract-ocr tesseract-ocr-por poppler-utils
    pip install pdf2image pytesseract pillow pypdf

COMO USAR:
    1. Coloque os PDFs escaneados dentro da pasta "recibos_entrada"
       (ela é criada automaticamente na primeira execução, se não existir).
    2. Rode:  python3 renomear_recibos.py
    3. Os arquivos renomeados aparecem em "recibos_renomeados".
    4. Confira o resumo impresso no final — PDFs (ou trechos de PDFs) em
       que o nome ou o mês não puderam ser lidos automaticamente ficam
       listados em "revisar_manualmente" e precisam ser renomeados à mão.
"""

import re
import shutil
import unicodedata
from pathlib import Path

from pdf2image import convert_from_path
import pytesseract
from pypdf import PdfReader, PdfWriter

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

PASTA_ENTRADA = Path("recibos_entrada")
PASTA_SAIDA = Path("recibos_renomeados")
PASTA_REVISAR = PASTA_SAIDA / "revisar_manualmente"

DPI_OCR = 300          # resolução usada para converter o PDF em imagem antes do OCR
IDIOMA_OCR = "por"      # português

# --- SÓ NO WINDOWS: se o script não achar o Tesseract/Poppler sozinho,
# preencha os caminhos abaixo (troque pelo caminho real da sua instalação).
CAMINHO_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CAMINHO_POPPLER = r"C:\poppler\Library\bin"

if CAMINHO_TESSERACT:
    pytesseract.pytesseract.tesseract_cmd = CAMINHO_TESSERACT

MESES = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO",
]

# ---------------------------------------------------------------------------
# FUNÇÕES DE OCR E TEXTO
# ---------------------------------------------------------------------------

def ocr_paginas(caminho_pdf: Path) -> list[str]:
    """Converte cada página do PDF em imagem e roda OCR, devolvendo uma
    lista com o texto de cada página (na mesma ordem do PDF)."""
    kwargs = {"dpi": DPI_OCR}
    if CAMINHO_POPPLER:
        kwargs["poppler_path"] = CAMINHO_POPPLER
    imagens = convert_from_path(str(caminho_pdf), **kwargs)
    return [pytesseract.image_to_string(img, lang=IDIOMA_OCR) for img in imagens]


def normalizar(texto: str) -> str:
    """Remove acentos e deixa em maiúsculas, para facilitar comparações."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper()


def extrair_nome(texto: str) -> str | None:
    """Procura o padrão 'EU, <NOME>, AGENTE...' (com pequenas variações que
    o OCR pode gerar) e devolve o nome já limpo."""
    padroes = [
        r"EU,\s*([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ\s]{4,80}?),\s*AGENTE",
        r"EU,\s*([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ\s]{4,80}?),\s*PORTADOR",
        r"EU,\s*([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ\s]{4,80}?),\s*(?:RG|CPF)",
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.IGNORECASE)
        if m:
            nome = re.sub(r"\s+", " ", m.group(1)).strip()
            return nome.upper()
    return None


def extrair_mes(texto: str) -> str | None:
    """Procura o padrão 'MÊS DE <MES>/<ANO>' (tolerando erros de OCR em
    acentos) e devolve o nome do mês em maiúsculas, sem acento."""
    texto_norm = normalizar(texto)
    m = re.search(r"MES\s+DE\s+([A-Z]+)\s*/\s*(\d{4})", texto_norm)
    if not m:
        return None
    mes_bruto = m.group(1)

    meses_norm = [normalizar(mes) for mes in MESES]
    if mes_bruto in meses_norm:
        return MESES[meses_norm.index(mes_bruto)]

    for mes, mes_norm in zip(MESES, meses_norm):
        if mes_norm[:4] == mes_bruto[:4]:
            return mes

    return mes_bruto  # devolve como veio, para revisão manual não perder a pista


def montar_nome_arquivo(mes: str, nome: str) -> str:
    """Monta o nome final do arquivo, removendo caracteres inválidos."""
    base = f"RECIBO {mes} {nome}"
    base = re.sub(r'[\\/*?:"<>|]', "", base)
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


def salvar_paginas(caminho_pdf: Path, indice_inicio: int, indice_fim: int, destino: Path):
    """Copia as páginas [indice_inicio, indice_fim) do PDF original para um
    novo arquivo PDF em 'destino'."""
    leitor = PdfReader(str(caminho_pdf))
    escritor = PdfWriter()
    for i in range(indice_inicio, indice_fim):
        escritor.add_page(leitor.pages[i])
    with open(destino, "wb") as f:
        escritor.write(f)


# ---------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------------

def processar_pdf(caminho_pdf: Path, sucesso: list, falhas: list):
    print(f"Processando: {caminho_pdf.name} ...")

    try:
        textos_paginas = ocr_paginas(caminho_pdf)
    except Exception as e:
        print(f"  ERRO no OCR: {type(e).__name__}: {e}")
        falhas.append((caminho_pdf.name, f"erro de OCR: {e}"))
        shutil.copy2(caminho_pdf, PASTA_REVISAR / caminho_pdf.name)
        return

    total_paginas = len(textos_paginas)

    # Para cada página, tenta identificar se ela É O INÍCIO de um recibo
    # (ou seja, tem nome E mês reconhecíveis nela mesma).
    inicios = []  # lista de (indice_pagina, nome, mes)
    for i, texto in enumerate(textos_paginas):
        nome = extrair_nome(texto)
        mes = extrair_mes(texto)
        if nome and mes:
            inicios.append((i, nome, mes))

    if not inicios:
        # Nenhuma página do arquivo permitiu identificar nome + mês.
        print("  NÃO IDENTIFICADO (nome/mês não encontrados em nenhuma página)")
        falhas.append((caminho_pdf.name, "nome/mês não encontrados em nenhuma página"))
        shutil.copy2(caminho_pdf, PASTA_REVISAR / caminho_pdf.name)
        return

    # Se a primeira página com recibo identificado não é a página 0, as
    # páginas anteriores ficam "órfãs" (não sabemos a quem pertencem).
    primeiro_inicio = inicios[0][0]
    if primeiro_inicio > 0:
        nome_orfao = f"{caminho_pdf.stem} - paginas 1-{primeiro_inicio} SEM RECIBO IDENTIFICADO.pdf"
        destino_orfao = caminho_sem_conflito(PASTA_REVISAR / nome_orfao)
        salvar_paginas(caminho_pdf, 0, primeiro_inicio, destino_orfao)
        print(f"  AVISO: páginas 1-{primeiro_inicio} não pertencem a nenhum recibo "
              f"identificado -> {destino_orfao.name}")
        falhas.append((caminho_pdf.name,
                        f"páginas 1-{primeiro_inicio} sem recibo identificado"))

    if len(inicios) == 1:
        # Caso normal: um único recibo no arquivo (possivelmente com
        # páginas de anexo depois). Mantém o comportamento antigo: copia
        # o arquivo inteiro a partir da página do recibo.
        idx, nome, mes = inicios[0]
        novo_nome = montar_nome_arquivo(mes, nome)
        destino = caminho_sem_conflito(PASTA_SAIDA / novo_nome)
        salvar_paginas(caminho_pdf, idx, total_paginas, destino)
        print(f"  OK -> {destino.name}")
        sucesso.append((caminho_pdf.name, destino.name))
        return

    # Mais de um recibo detectado no mesmo arquivo -> separar em PDFs
    # individuais. Cada recibo leva consigo as páginas seguintes até a
    # página onde o próximo recibo começa (anexos/comprovantes).
    print(f"  {len(inicios)} recibos detectados neste arquivo -> separando...")
    for pos, (idx, nome, mes) in enumerate(inicios):
        fim = inicios[pos + 1][0] if pos + 1 < len(inicios) else total_paginas
        novo_nome = montar_nome_arquivo(mes, nome)
        destino = caminho_sem_conflito(PASTA_SAIDA / novo_nome)
        salvar_paginas(caminho_pdf, idx, fim, destino)
        print(f"    OK -> páginas {idx + 1}-{fim} -> {destino.name}")
        sucesso.append((f"{caminho_pdf.name} (pág. {idx + 1}-{fim})", destino.name))


def main():
    PASTA_ENTRADA.mkdir(exist_ok=True)
    PASTA_SAIDA.mkdir(exist_ok=True)
    PASTA_REVISAR.mkdir(exist_ok=True)

    # Usa um dict para não processar o mesmo arquivo duas vezes em sistemas
    # de arquivos que não diferenciam maiúsculas/minúsculas (ex: Windows),
    # onde "*.pdf" e "*.PDF" podem capturar o mesmo arquivo duas vezes.
    encontrados = {}
    for padrao in ("*.pdf", "*.PDF"):
        for caminho in PASTA_ENTRADA.glob(padrao):
            encontrados[caminho.resolve()] = caminho
    pdfs = sorted(encontrados.values(), key=lambda p: p.name)

    if not pdfs:
        print(f"Nenhum PDF encontrado em '{PASTA_ENTRADA}/'. Coloque os arquivos lá e rode de novo.")
        return

    sucesso, falhas = [], []

    for caminho_pdf in pdfs:
        try:
            processar_pdf(caminho_pdf, sucesso, falhas)
        except Exception as e:
            print(f"  ERRO inesperado: {type(e).__name__}: {e}")
            falhas.append((caminho_pdf.name, f"erro inesperado: {e}"))
            shutil.copy2(caminho_pdf, PASTA_REVISAR / caminho_pdf.name)

    print("\n" + "=" * 60)
    print(f"Concluído: {len(sucesso)} recibo(s) renomeado(s) com sucesso, "
          f"{len(falhas)} pendência(s) para revisar manualmente.")
    if falhas:
        print(f"\nOs trechos que não puderam ser lidos automaticamente foram "
              f"copiados para:\n  {PASTA_REVISAR}/")
        print("Motivo de cada um:")
        for nome_arquivo, motivo in falhas:
            print(f"  - {nome_arquivo}: {motivo}")
    print(f"\nArquivos renomeados estão em: {PASTA_SAIDA}/")


if __name__ == "__main__":
    main()