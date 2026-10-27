"""Consulta ao banco do agente, sem precisar abrir o SQLite.

Uso:
    python -m banco.relatorio                      # status, pendentes, desistências e últimas execuções
    python -m banco.relatorio --processo "SEI-040009/001847/2026"   # o histórico de um processo
    python -m banco.relatorio --horas 4 --execucoes 20
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from banco.controle import ControleProcessos

_SEM_DADO = "-"


def _hora(texto: str | None) -> str:
    return texto.replace("T", " ") if texto else _SEM_DADO


def _horas_desde(texto: str, agora: datetime) -> str:
    horas = (agora - datetime.fromisoformat(texto)).total_seconds() / 3600
    return f"{horas:.1f} h"


def montar_relatorio(
    controle: ControleProcessos, tentativas_maximas: int, horas: float = 1, execucoes: int = 10,
    agora: datetime | None = None,
) -> str:
    agora = agora or datetime.now()
    linhas = ["PROCESSOS POR STATUS"]
    contagem = controle.contagem_por_status()
    linhas += [f"  {status}: {total}" for status, total in contagem] or ["  (banco vazio)"]

    pendentes = controle.exportados_sem_analise(horas, agora)
    linhas += ["", f"EXPORTADOS SEM ANÁLISE HÁ MAIS DE {horas:g} H"]
    linhas += [f"  {numero}  exportado em {_hora(desde)} ({_horas_desde(desde, agora)})" for numero, desde in pendentes] or ["  nenhum"]

    desistiram = controle.desistiram(tentativas_maximas)
    linhas += ["", f"DESISTIRAM ({tentativas_maximas} FALHAS SEGUIDAS; o agente não tenta mais sozinho, use --processo)"]
    linhas += [f"  {numero}  {status}, {falhas} falhas: {erro or _SEM_DADO}" for numero, status, falhas, erro in desistiram] or ["  nenhum"]

    linhas += ["", f"ÚLTIMAS {execucoes} EXECUÇÕES"]
    for id_, inicio, fim, modo, selecionados, exportados, falhas, analises, codigo in controle.execucoes_recentes(execucoes):
        situacao = "sem fim registrado (interrompida?)" if fim is None else f"fim {_hora(fim)}"
        totais = (
            f"selecionados {selecionados}, exportados {exportados}, falhas {falhas}, análises {analises}, saída {codigo}"
            if fim else "totais indisponíveis"
        )
        linhas.append(f"  #{id_}  {_hora(inicio)}  {modo or _SEM_DADO}  {situacao}  |  {totais}")
    if not controle.execucoes_recentes(1):
        linhas.append("  nenhuma")
    return "\n".join(linhas) + "\n"


def montar_historico(controle: ControleProcessos, numero: str) -> str:
    eventos = controle.historico_do_processo(numero)
    cabecalho = [f"HISTÓRICO DE {numero}"]
    if not eventos:
        return "\n".join(cabecalho + ["  nenhum evento registrado"]) + "\n"
    return "\n".join(
        cabecalho
        + [f"  {_hora(em)}  exec #{execucao or _SEM_DADO}  {etapa}  {resultado}  {detalhe or ''}".rstrip()
           for em, execucao, etapa, resultado, detalhe in eventos]
    ) + "\n"


def main(argv: list[str] | None = None) -> int:
    import config

    parser = argparse.ArgumentParser(description="Consulta o banco do agente.")
    parser.add_argument("--processo", help="Mostra o histórico desse processo.")
    parser.add_argument("--horas", type=float, default=1, help="Pendentes: exportados há mais de N horas (padrão 1).")
    parser.add_argument("--execucoes", type=int, default=10, help="Quantas execuções listar (padrão 10).")
    args = parser.parse_args(argv)
    if not config.CAMINHO_BANCO.is_file():
        print(f"Banco não encontrado: {config.CAMINHO_BANCO}")
        return 2
    controle = ControleProcessos(config.CAMINHO_BANCO)
    try:
        if args.processo:
            print(montar_historico(controle, args.processo), end="")
        else:
            print(montar_relatorio(controle, config.TENTATIVAS_MAXIMAS, args.horas, args.execucoes), end="")
    finally:
        controle.fechar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
