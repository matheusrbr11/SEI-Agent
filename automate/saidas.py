"""Lê as análises geradas pelo Power Automate, corrige o formato e as confere com o JSON de entrada.

Uso:
    python -m automate.saidas                    # processa as análises novas da pasta de saída
    python -m automate.saidas --refazer          # processa todas de novo
    python -m automate.saidas --arquivo X.md     # processa só esse arquivo da pasta de saída

A pasta de saída (SHAREPOINT_PASTA_SAIDA, no .env) só é lida. O resultado vai para automate/saida:
  <nome>.md              a análise com o formato corrigido
  <nome>.validacao.txt   o que foi corrigido e os problemas que restam (ERRO / AVISO)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from automate import teams
from automate.correcao import corrigir_formato
from automate.extracao import usar_nome_atual
from automate.validador import validar_saida
from banco.controle import ControleProcessos
from sei.modelos import nome_seguro

_PROCESSO = re.compile(r"^##\s+Processo\s*$", re.I | re.M)
_ROTULO_DA_IMPRESSAO = "Impressão digital da análise original (SHA-1): "


@dataclass
class Resultado:
    arquivo: str
    numero: str | None = None
    entrada: str | None = None
    correcoes: list[str] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    impressao: str = ""  # SHA-1 da análise original; identifica o conteúdo, e não o horário do arquivo
    corrigido: str = ""  # caminho do .md corrigido que foi gravado

    @property
    def erros(self) -> list[str]:
        return [p for p in self.problemas if p.startswith("ERRO")]

    @property
    def avisos(self) -> list[str]:
        return [p for p in self.problemas if p.startswith("AVISO")]

    @property
    def situacao(self) -> str:
        return "ERRO" if self.erros else "AVISO" if self.avisos else "OK"


def registrar_no_banco(controle: ControleProcessos, resultado: Resultado, teams_enviado: bool | None = None) -> bool:
    """Marca no banco que a análise do processo chegou (`analisado`) e a acrescenta ao historico, com os erros e avisos.

    A análise com ERRO de validação também conta como `analisado`: o processo não deve ser coletado de novo por causa
    disso. O resumo dos ERROs fica na coluna `erro`, e as contagens em `validacao_erros` e `validacao_avisos`.
    `teams_enviado` é None se o envio ao Teams nem foi tentado. False se o processo não está no banco (ou a análise
    não traz o número); o historico recebe a análise de qualquer forma.
    """
    controle.registrar_no_historico(resultado.numero, resultado.arquivo, resultado.problemas)
    if not resultado.numero:
        return False
    erros, avisos = len(resultado.erros), len(resultado.avisos)
    resumo = f"Validação: {erros} ERRO(s)" if erros else None
    return controle.registrar_analise(
        resultado.numero, resultado.corrigido, resumo,
        validacao_erros=erros, validacao_avisos=avisos, teams_enviado=teams_enviado,
    )


def numero_do_processo(markdown: str) -> str | None:
    """Número do processo, na primeira linha com texto depois do título "## Processo"."""
    achado = _PROCESSO.search(markdown)
    if not achado:
        return None
    for linha in markdown[achado.end():].splitlines():
        if linha.strip():
            return None if linha.startswith("#") else linha.strip()
    return None


def localizar_entrada(numero: str, pastas: list[Path | None]) -> Path | None:
    nome = f"ENTRADA_{nome_seguro(numero)}.json"
    return next((pasta / nome for pasta in pastas if pasta and (pasta / nome).is_file()), None)


def _conferir(corrigido: str, resultado: Resultado, pastas_entrada: list[Path | None]) -> str:
    """Troca os nomes antigos de unidades e valida; devolve o texto final."""
    resultado.numero = numero_do_processo(corrigido)
    if resultado.numero is None:
        resultado.problemas.append("ERRO: a seção Processo não traz o número; não foi possível achar o JSON de entrada")
        return corrigido
    caminho = localizar_entrada(resultado.numero, pastas_entrada)
    if caminho is None:
        resultado.problemas.append(
            f"ERRO: JSON de entrada não encontrado: ENTRADA_{nome_seguro(resultado.numero)}.json"
        )
        return corrigido
    resultado.entrada = str(caminho)
    entrada = json.loads(caminho.read_text(encoding="utf-8"))
    try:
        atualizado = usar_nome_atual(corrigido, {documento["nome"] for documento in entrada["documentos"]})
        if atualizado != corrigido:
            resultado.correcoes.append("Nomes antigos de unidades trocados pelos atuais (SUPCONC, SUPGO, SUPAEF)")
            corrigido = atualizado
        resultado.problemas += validar_saida(corrigido, entrada)
    except KeyError as faltando:
        resultado.problemas.append(
            f"ERRO: o JSON de entrada está em formato antigo (falta {faltando}); gere-o de novo com o agente"
        )
    return corrigido


def _relatorio(resultado: Resultado, impressao: str) -> str:
    linhas = [
        f"Análise: {resultado.arquivo}",
        f"{_ROTULO_DA_IMPRESSAO}{impressao}",
        f"Processo: {resultado.numero or 'não identificado'}",
        f"JSON de entrada: {resultado.entrada or 'não encontrado'}",
        f"Situação: {resultado.situacao}",
        "",
        "CORREÇÕES AUTOMÁTICAS (só de formato e de nomes de unidades):",
        *([f"- {c}" for c in resultado.correcoes] or ["- nenhuma"]),
        "",
        "PROBLEMAS QUE RESTAM:",
        *([f"- {p}" for p in resultado.problemas] or ["- nenhum"]),
    ]
    return "\n".join(linhas) + "\n"


def processar_arquivo(origem: Path, pastas_entrada: list[Path | None], destino: Path) -> Resultado:
    """Corrige e valida uma análise; grava o .md corrigido e o relatório em `destino`. A origem não é alterada."""
    resultado = Resultado(arquivo=origem.name, impressao=_impressao_digital(origem))
    corrigido, resultado.correcoes = corrigir_formato(origem.read_text(encoding="utf-8-sig"))
    corrigido = _conferir(corrigido, resultado, pastas_entrada)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / origem.name).write_text(corrigido, encoding="utf-8", newline="\n")
    resultado.corrigido = str(destino / origem.name)
    relatorio = _relatorio(resultado, resultado.impressao)
    (destino / f"{origem.stem}.validacao.txt").write_text(relatorio, encoding="utf-8", newline="\n")
    return resultado


def _impressao_digital(origem: Path) -> str:
    return hashlib.sha1(origem.read_bytes()).hexdigest()


def _ja_processada(origem: Path, destino: Path) -> bool:
    """Já existe relatório desta análise, com o mesmo conteúdo? (O horário do arquivo não serve: o OneDrive o altera.)"""
    pronta = destino / f"{origem.stem}.validacao.txt"
    return pronta.is_file() and f"{_ROTULO_DA_IMPRESSAO}{_impressao_digital(origem)}" in pronta.read_text(encoding="utf-8")


def processar_pasta(
    pasta_saida: Path,
    pastas_entrada: list[Path | None],
    destino: Path,
    refazer: bool = False,
    arquivo: str | None = None,
    estavel_ha: float = 0,
    ignorar_impressoes: set[str] = frozenset(),
    apenas_processos: list[str] | None = None,
) -> list[Resultado]:
    """Processa as análises novas da pasta. `estavel_ha`: ignora arquivos alterados há menos de N segundos (o OneDrive
    ainda pode estar gravando); eles ficam para a próxima passada. `ignorar_impressoes`: conteúdos (SHA-1) que não são
    analisados de jeito nenhum (o que já estava na pasta). `apenas_processos`: se informado, só as análises desses
    processos são analisadas; as demais da pasta são deixadas de lado."""
    candidatos = [pasta_saida / arquivo] if arquivo else sorted(pasta_saida.glob("*.md"))
    desejados = None if apenas_processos is None else {nome_seguro(numero) for numero in apenas_processos}
    resultados = []
    for origem in candidatos:
        try:
            if origem.name.startswith("~$") or not origem.is_file():
                continue
            if estavel_ha and time.time() - origem.stat().st_mtime < estavel_ha:
                continue
            if ignorar_impressoes and _impressao_digital(origem) in ignorar_impressoes:
                continue
            if desejados is not None:
                numero = numero_do_processo(origem.read_text(encoding="utf-8-sig"))
                if not numero or nome_seguro(numero) not in desejados:
                    continue
            if not refazer and not arquivo and _ja_processada(origem, destino):
                continue
            resultados.append(processar_arquivo(origem, pastas_entrada, destino))
        except OSError:  # arquivo ainda sendo sincronizado ou aberto em outro aplicativo
            continue
    return resultados


def impressoes_existentes(pasta_saida: Path | None) -> set[str]:
    """Conteúdos (SHA-1) das análises que já estão na pasta de saída; serve para reconhecer o que chega depois."""
    if pasta_saida is None or not pasta_saida.is_dir():
        return set()
    impressoes = set()
    for origem in pasta_saida.glob("*.md"):
        try:
            impressoes.add(_impressao_digital(origem))
        except OSError:
            continue
    return impressoes


def aguardar_e_processar(
    pasta_saida: Path,
    pastas_entrada: list[Path | None],
    destino: Path,
    aguardados: list[str],
    ja_existentes: set[str],
    espera_maxima: float,
    intervalo: float,
    ao_processar=None,
    estavel_ha: float = 5,
    dormir=time.sleep,
    relogio=time.monotonic,
) -> tuple[list[Resultado], list[str]]:
    """Espera, até `espera_maxima` segundos, a análise de cada processo em `aguardados` e a processa quando chega.

    Só analisa o que aparece de novo e é de um desses processos: o que já estava na pasta (`ja_existentes`, conteúdos
    SHA-1), mesmo do mesmo processo, e as análises de outros processos são deixadas de lado. Devolve (resultados,
    processos que não chegaram a tempo).
    """
    pendentes = {nome_seguro(numero): numero for numero in aguardados}
    resultados: list[Resultado] = []
    limite = relogio() + espera_maxima
    while True:
        novos = processar_pasta(
            pasta_saida, pastas_entrada, destino, estavel_ha=estavel_ha,
            ignorar_impressoes=ja_existentes, apenas_processos=list(pendentes.values()),
        )
        for resultado in novos:
            resultados.append(resultado)
            if ao_processar:
                ao_processar(resultado)
            if resultado.numero:
                pendentes.pop(nome_seguro(resultado.numero), None)
        restante = limite - relogio()
        if not pendentes or restante <= 0:
            return resultados, sorted(pendentes.values())
        dormir(min(intervalo, restante))


def main(argv: list[str] | None = None) -> int:
    import config

    parser = argparse.ArgumentParser(description="Corrige o formato e valida as análises geradas pelo Power Automate.")
    parser.add_argument("--refazer", action="store_true", help="Processa também as análises já processadas.")
    parser.add_argument("--arquivo", help="Nome de um arquivo .md da pasta de saída.")
    parser.add_argument("--sem-teams", action="store_true", help="Não envia as análises pelo Teams.")
    args = parser.parse_args(argv)
    if config.SHAREPOINT_PASTA_SAIDA is None:
        print("Defina SHAREPOINT_PASTA_SAIDA no .env (pasta 'saida' sincronizada pelo OneDrive).")
        return 2
    if not config.SHAREPOINT_PASTA_SAIDA.is_dir():
        print(f"Pasta de saída não encontrada (OneDrive sincronizando?): {config.SHAREPOINT_PASTA_SAIDA}")
        return 2
    pastas_entrada = [config.PASTA_AUTOMATE_ENTRADA, config.SHAREPOINT_PASTA_ENTRADA]
    resultados = processar_pasta(
        config.SHAREPOINT_PASTA_SAIDA, pastas_entrada, config.PASTA_AUTOMATE_SAIDA, args.refazer, args.arquivo
    )
    # --refazer reprocessa o que já foi enviado: não reenvia ao Teams (evita mensagens repetidas)
    enviar_ao_teams = not (args.sem_teams or args.refazer) and teams.configurado()
    codigo = 1 if any(r.erros for r in resultados) else 0
    controle = ControleProcessos(config.CAMINHO_BANCO) if resultados else None  # só registra execução se houve análise
    try:
        if controle:
            controle.iniciar_execucao("saidas", " ".join(argv if argv is not None else sys.argv[1:]))
        for r in resultados:
            print(f"[{r.situacao}] {r.arquivo} (processo {r.numero or '?'}): {len(r.correcoes)} correção(ões), "
                  f"{len(r.erros)} erro(s), {len(r.avisos)} aviso(s)")
            for problema in r.problemas:
                print(f"    {problema}")
            enviado = None  # None: o envio ao Teams nem foi tentado
            if enviar_ao_teams:
                enviado = teams.enviar_resultado(r)
                print(f"    Teams: {'enviada' if enviado else 'NÃO enviada (veja o log)'}")
            try:
                if not registrar_no_banco(controle, r, enviado):
                    print(f"Banco: o processo {r.numero or '?'} ({r.arquivo}) não está no banco; status não atualizado.")
            except Exception as erro:  # a análise já foi corrigida em disco: um problema no banco não a invalida
                print(f"Banco: não foi possível atualizar o status de {r.arquivo}: {erro}")
    finally:
        if controle:
            controle.finalizar_execucao(codigo)
            controle.fechar()
    if resultados:
        print(f"Resultados em: {config.PASTA_AUTOMATE_SAIDA}")
    else:
        existentes = [p for p in config.SHAREPOINT_PASTA_SAIDA.glob("*.md") if not p.name.startswith("~$")]
        if existentes:
            print(
                f"Nenhuma análise nova: as {len(existentes)} análise(s) da pasta de saída já foram processadas com este "
                f"mesmo conteúdo (resultados em {config.PASTA_AUTOMATE_SAIDA}). Use --refazer para processar de novo."
            )
        else:
            print("A pasta de saída não tem nenhuma análise (.md).")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
