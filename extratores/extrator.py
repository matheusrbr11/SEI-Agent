"""Extratores locais para anexos baixados do SEI."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("jupiter.agente.extrator")


def _eh_pdf(caminho: Path) -> bool:
    try:
        with caminho.open("rb") as arquivo:
            return arquivo.read(5) == b"%PDF-"
    except OSError:
        return False


def extrair_pdf(caminho: Path) -> str:
    import pdfplumber
    with pdfplumber.open(str(caminho)) as pdf:
        texto = "\n".join((pagina.extract_text() or "") for pagina in pdf.pages).strip()
    if not texto:
        logger.warning("PDF sem texto; pode exigir OCR: %s", caminho.name)
    return texto


def extrair_word(caminho: Path) -> str:
    from docx import Document
    documento = Document(str(caminho))
    return "\n".join(p.text for p in documento.paragraphs if p.text.strip())


def extrair_conteudo(caminho: Path) -> str:
    caminho = Path(caminho)
    extensao = caminho.suffix.lower()
    try:
        if _eh_pdf(caminho):
            return extrair_pdf(caminho)
        if extensao == ".docx":
            return extrair_word(caminho)
        if extensao in {".txt", ".csv", ".html", ".htm", ".md", ".json"}:
            return caminho.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        logger.exception("Erro ao extrair %s", caminho.name)
    return ""
