"""Controle local: coleta, exportação e análise pelo Power Automate."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

STATUS_VALIDOS = {
    "baseline", "exportado", "analisado", "erro_coleta", "erro_envio", "erro_ia"
}


class ControleProcessos:
    def __init__(self, caminho: Path):
        self.conexao = sqlite3.connect(str(caminho))
        self.conexao.execute(
            """CREATE TABLE IF NOT EXISTS processos (
                numero TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                arquivo_entrada TEXT,
                arquivo_saida TEXT,
                erro TEXT,
                atualizado_em TEXT NOT NULL
            )"""
        )
        self.conexao.commit()

    def vazio(self) -> bool:
        return self.conexao.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 0

    def conhecido(self, numero: str) -> bool:
        linha = self.conexao.execute(
            "SELECT status FROM processos WHERE numero = ?", (numero,)
        ).fetchone()
        return linha is not None and linha[0] in {"baseline", "exportado", "analisado"}

    def salvar(self, numero: str, status: str, arquivo_entrada=None, arquivo_saida=None, erro=None):
        if status not in STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {status}")
        self.conexao.execute(
            """INSERT INTO processos(numero,status,arquivo_entrada,arquivo_saida,erro,atualizado_em)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(numero) DO UPDATE SET
                 status=excluded.status,
                 arquivo_entrada=COALESCE(excluded.arquivo_entrada,processos.arquivo_entrada),
                 arquivo_saida=COALESCE(excluded.arquivo_saida,processos.arquivo_saida),
                 erro=excluded.erro,
                 atualizado_em=excluded.atualizado_em""",
            (numero, status, arquivo_entrada, arquivo_saida, erro,
             datetime.now().isoformat(timespec="seconds")),
        )
        self.conexao.commit()

    def registrar_baseline(self, numeros: list[str]):
        for numero in numeros:
            self.salvar(numero, "baseline")

    def fechar(self):
        self.conexao.close()
