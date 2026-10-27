"""Modelos de dados usados entre a coleta do SEI e o Power Automate."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


MOTIVO_PLANILHA = "planilha Excel não lida"


@dataclass
class DocumentoSEI:
    nome: str
    texto: Optional[str] = None
    origem_texto: Optional[str] = None
    unidade: Optional[str] = None
    arquivo_local: Optional[str] = None
    motivo_sem_texto: Optional[str] = None  # por que o texto não foi lido, quando foi uma escolha


@dataclass
class ProcessoSEI:
    numero: str
    tipo: Optional[str] = None
    especificacao: Optional[str] = None
    interessados: Optional[str] = None
    anotacao: Optional[str] = None
    marcadores: Optional[str] = None
    atribuicao: Optional[str] = None
    ultima_movimentacao: Optional[str] = None
    documentos: list[DocumentoSEI] = field(default_factory=list)

    def para_dict(self) -> dict:
        return asdict(self)
