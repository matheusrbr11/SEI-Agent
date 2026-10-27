"""Controle local (SQLite): o que já foi tratado, o que aconteceu com cada processo e o diário das execuções.

Três tabelas:
  processos   uma linha por processo, com o estado atual (a que decide o que o agente pega na próxima execução);
  execucoes   uma linha por execução do agente (início, fim, totais e código de saída);
  historico   uma linha por acontecimento (coleta, entrega, análise, Teams...), só acrescentada, nunca sobrescrita.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

STATUS_VALIDOS = {
    "baseline", "exportado", "analisado", "erro_coleta", "erro_envio", "erro_ia"
}
STATUS_CONHECIDOS = {"baseline", "exportado", "analisado"}  # o agente não pega de novo
STATUS_DE_ERRO = {"erro_coleta", "erro_envio", "erro_ia"}

ETAPAS = {
    "selecionado", "coleta", "json_gerado", "json_reaproveitado", "entrega", "analise", "teams", "desistiu",
}
RESULTADOS = {"ok", "aviso", "erro"}

VERSAO_DO_ESQUEMA = 1

# Colunas acrescentadas na versão 1; um banco criado antes dela as recebe em _migrar.
_COLUNAS_DA_VERSAO_1 = {
    "falhas_seguidas": "INTEGER NOT NULL DEFAULT 0",  # erros seguidos desde o último sucesso
    "exportado_em": "TEXT",
    "analisado_em": "TEXT",
    "teams_enviado": "INTEGER",  # 1 enviado, 0 falhou, NULL não tentado
    "validacao_erros": "INTEGER",
    "validacao_avisos": "INTEGER",
}


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ControleProcessos:
    def __init__(self, caminho: Path):
        self.conexao = sqlite3.connect(str(caminho))
        self.execucao_id: int | None = None
        self._migrar()

    def _migrar(self) -> None:
        """Cria o que falta e leva um banco antigo à versão atual, sem perder as linhas que ele já tem."""
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
        existentes = {linha[1] for linha in self.conexao.execute("PRAGMA table_info(processos)")}
        for coluna, definicao in _COLUNAS_DA_VERSAO_1.items():
            if coluna not in existentes:
                self.conexao.execute(f"ALTER TABLE processos ADD COLUMN {coluna} {definicao}")
        self.conexao.execute(
            """CREATE TABLE IF NOT EXISTS execucoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inicio TEXT NOT NULL,
                fim TEXT,
                modo TEXT,
                argumentos TEXT,
                selecionados INTEGER,
                exportados INTEGER,
                falhas INTEGER,
                analises INTEGER,
                codigo_saida INTEGER
            )"""
        )
        self.conexao.execute(
            """CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execucao_id INTEGER,
                numero TEXT NOT NULL,
                etapa TEXT NOT NULL,
                resultado TEXT NOT NULL,
                detalhe TEXT,
                em TEXT NOT NULL
            )"""
        )
        self.conexao.execute("CREATE INDEX IF NOT EXISTS idx_historico_numero ON historico(numero)")
        self.conexao.execute(f"PRAGMA user_version = {VERSAO_DO_ESQUEMA}")
        self.conexao.commit()

    # --- processos: estado atual

    def vazio(self) -> bool:
        return self.conexao.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 0

    def conhecido(self, numero: str) -> bool:
        linha = self.conexao.execute(
            "SELECT status FROM processos WHERE numero = ?", (numero,)
        ).fetchone()
        return linha is not None and linha[0] in STATUS_CONHECIDOS

    def linha(self, numero: str) -> dict | None:
        """A linha do processo como dicionário (coluna -> valor), ou None se ele não está no banco."""
        cursor = self.conexao.execute("SELECT * FROM processos WHERE numero = ?", (numero,))
        valores = cursor.fetchone()
        return None if valores is None else dict(zip([c[0] for c in cursor.description], valores))

    def desistiu(self, numero: str, tentativas_maximas: int) -> bool:
        """O processo está em erro e já falhou `tentativas_maximas` vezes seguidas: o agente para de tentar."""
        linha = self.linha(numero)
        return bool(linha) and linha["status"] in STATUS_DE_ERRO and linha["falhas_seguidas"] >= tentativas_maximas

    def salvar(self, numero: str, status: str, arquivo_entrada=None, arquivo_saida=None, erro=None):
        """Grava o estado do processo. Erros somam em `falhas_seguidas`; qualquer outro status zera a contagem.

        Um novo `exportado` começa um ciclo novo: os dados da análise anterior (data, validação, Teams, caminho) saem
        da linha. Eles continuam no historico.
        """
        if status not in STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {status}")
        agora = _agora()
        self.conexao.execute(
            """INSERT INTO processos(numero,status,arquivo_entrada,arquivo_saida,erro,atualizado_em,
                                     falhas_seguidas,exportado_em)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(numero) DO UPDATE SET
                 status=excluded.status,
                 arquivo_entrada=COALESCE(excluded.arquivo_entrada,processos.arquivo_entrada),
                 arquivo_saida=CASE WHEN excluded.status='exportado' THEN NULL
                                    ELSE COALESCE(excluded.arquivo_saida,processos.arquivo_saida) END,
                 erro=excluded.erro,
                 atualizado_em=excluded.atualizado_em,
                 falhas_seguidas=CASE WHEN excluded.falhas_seguidas>0
                                      THEN processos.falhas_seguidas+1 ELSE 0 END,
                 exportado_em=COALESCE(excluded.exportado_em,processos.exportado_em),
                 analisado_em=CASE WHEN excluded.status='exportado' THEN NULL ELSE processos.analisado_em END,
                 teams_enviado=CASE WHEN excluded.status='exportado' THEN NULL ELSE processos.teams_enviado END,
                 validacao_erros=CASE WHEN excluded.status='exportado' THEN NULL ELSE processos.validacao_erros END,
                 validacao_avisos=CASE WHEN excluded.status='exportado' THEN NULL ELSE processos.validacao_avisos END""",
            (numero, status, arquivo_entrada, arquivo_saida, erro, agora,
             1 if status in STATUS_DE_ERRO else 0, agora if status == "exportado" else None),
        )
        self.conexao.commit()

    def registrar_analise(
        self, numero: str, arquivo_saida: str, erro: str | None = None, *,
        validacao_erros: int | None = None, validacao_avisos: int | None = None, teams_enviado: bool | None = None,
    ) -> bool:
        """Marca o processo como `analisado`, com o caminho da análise corrigida e o resultado da validação.

        `erro` guarda o resumo da validação quando há ERRO; `teams_enviado` é None se o envio nem foi tentado.
        Só atualiza uma linha que já existe e devolve False se não houver: o número vem do texto da análise e, se não
        bater com nenhum processo do banco, não deve criar uma linha solta (que passaria a valer como "conhecida").
        """
        agora = _agora()
        cursor = self.conexao.execute(
            """UPDATE processos SET status='analisado', arquivo_saida=?, erro=?, atualizado_em=?, falhas_seguidas=0,
                                    analisado_em=?, validacao_erros=?, validacao_avisos=?, teams_enviado=?
               WHERE numero=?""",
            (arquivo_saida, erro, agora, agora, validacao_erros, validacao_avisos,
             None if teams_enviado is None else int(teams_enviado), numero),
        )
        self.conexao.commit()
        return cursor.rowcount > 0

    def registrar_baseline(self, numeros: list[str]):
        for numero in numeros:
            self.salvar(numero, "baseline")

    # --- execucoes e historico: o diário

    def iniciar_execucao(self, modo: str, argumentos: str = "") -> int:
        """Abre uma linha em `execucoes`; os eventos registrados depois passam a pertencer a ela."""
        cursor = self.conexao.execute(
            "INSERT INTO execucoes(inicio, modo, argumentos) VALUES(?,?,?)", (_agora(), modo, argumentos)
        )
        self.conexao.commit()
        self.execucao_id = cursor.lastrowid
        return self.execucao_id

    def registrar_evento(self, numero: str, etapa: str, resultado: str, detalhe: str | None = None) -> None:
        """Acrescenta um acontecimento ao historico. `detalhe` leva só mensagens curtas, nunca conteúdo de processo."""
        if etapa not in ETAPAS:
            raise ValueError(f"Etapa inválida: {etapa}")
        if resultado not in RESULTADOS:
            raise ValueError(f"Resultado inválido: {resultado}")
        self.conexao.execute(
            "INSERT INTO historico(execucao_id, numero, etapa, resultado, detalhe, em) VALUES(?,?,?,?,?,?)",
            (self.execucao_id, numero, etapa, resultado, detalhe, _agora()),
        )
        self.conexao.commit()

    def finalizar_execucao(self, codigo_saida: int) -> None:
        """Fecha a linha da execução com os totais, tirados do historico, e o código de saída."""
        if self.execucao_id is None:
            return

        def contar(condicao: str) -> int:
            return self.conexao.execute(
                f"SELECT COUNT(DISTINCT numero) FROM historico WHERE execucao_id = ? AND {condicao}", (self.execucao_id,)
            ).fetchone()[0]

        self.conexao.execute(
            """UPDATE execucoes SET fim=?, selecionados=?, exportados=?, falhas=?, analises=?, codigo_saida=?
               WHERE id=?""",
            (_agora(), contar("etapa='selecionado'"), contar("etapa='entrega' AND resultado IN ('ok','aviso')"),
             contar("etapa IN ('coleta','entrega') AND resultado='erro'"), contar("etapa='analise'"),
             codigo_saida, self.execucao_id),
        )
        self.conexao.commit()

    # --- consultas (usadas por banco.relatorio)

    def contagem_por_status(self) -> list[tuple[str, int]]:
        return self.conexao.execute("SELECT status, COUNT(*) FROM processos GROUP BY status ORDER BY 2 DESC").fetchall()

    def exportados_sem_analise(self, horas: float, agora: datetime | None = None) -> list[tuple[str, str]]:
        """(número, quando foi exportado) dos processos exportados há mais de `horas` e ainda sem análise."""
        limite = ((agora or datetime.now()) - timedelta(hours=horas)).isoformat(timespec="seconds")
        return self.conexao.execute(
            """SELECT numero, COALESCE(exportado_em, atualizado_em) AS desde FROM processos
               WHERE status='exportado' AND desde < ? ORDER BY desde""",
            (limite,),
        ).fetchall()

    def desistiram(self, tentativas_maximas: int) -> list[tuple[str, str, int, str | None]]:
        """(número, status, falhas seguidas, último erro) dos processos que o agente parou de tentar."""
        return self.conexao.execute(
            """SELECT numero, status, falhas_seguidas, erro FROM processos
               WHERE status IN ('erro_coleta','erro_envio','erro_ia') AND falhas_seguidas >= ? ORDER BY atualizado_em""",
            (tentativas_maximas,),
        ).fetchall()

    def execucoes_recentes(self, limite: int = 10) -> list[tuple]:
        return self.conexao.execute(
            """SELECT id, inicio, fim, modo, selecionados, exportados, falhas, analises, codigo_saida
               FROM execucoes ORDER BY id DESC LIMIT ?""",
            (limite,),
        ).fetchall()

    def historico_do_processo(self, numero: str) -> list[tuple]:
        return self.conexao.execute(
            "SELECT em, execucao_id, etapa, resultado, detalhe FROM historico WHERE numero = ? ORDER BY id", (numero,)
        ).fetchall()

    def fechar(self):
        self.conexao.close()
