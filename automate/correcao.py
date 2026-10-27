"""Correções de FORMATO, por regra fixa, na análise gerada pela IA. O conteúdo das frases não é alterado."""
from __future__ import annotations

import re

_PROPOSTA = re.compile(r"^##\s+Proposta\s*$", re.I)
_SUBSECAO_COMO_SECAO = re.compile(r"^##\s+(Roteiro|Despacho)\s*$", re.I)
_TITULO_DE_SECAO = re.compile(r"^##\s+\S")
_ALERTAS = re.compile(r"^##\s+Alertas\s*$", re.I)
_DESPACHO = re.compile(r"^###\s+Despacho\s*$", re.I)
_TITULO_DE_SUBSECAO_OU_SECAO = re.compile(r"^#{2,3}\s+\S")
_LINHA_PREENCHER = re.compile(r"^\s*(?:\d+[.)]\s*|[-*]\s+)?Preencher:", re.I)
_MARCADOR_DE_LISTA = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")
_INDICACAO_DE_USO = "usar somente após a execução"
_ABRE_DOCUMENTS = re.compile(r"^\s*<documents>\s*", re.I)
_FECHA_DOCUMENTS = re.compile(r"\s*</documents>\s*$", re.I)


def _sem_bordas(linhas: list[str]) -> list[str]:
    """Sem as linhas em branco do começo e do fim."""
    inicio, fim = 0, len(linhas)
    while inicio < fim and not linhas[inicio]:
        inicio += 1
    while fim > inicio and not linhas[fim - 1]:
        fim -= 1
    return linhas[inicio:fim]


def _fim_da_secao(linhas: list[str], inicio: int, parar_em_subsecao: bool = False) -> int:
    padrao = _TITULO_DE_SUBSECAO_OU_SECAO if parar_em_subsecao else _TITULO_DE_SECAO
    return next((i for i in range(inicio + 1, len(linhas)) if padrao.match(linhas[i])), len(linhas))


def _sem_marcacao_documents(linhas: list[str], correcoes: list[str]) -> list[str]:
    """A IA às vezes devolve a análise dentro de "<documents> ... </documents>". No Teams o "<documents>" abre um parágrafo e o
    primeiro "## Processo" aparece como texto cru."""
    texto = "\n".join(linhas)
    sem_marcas = _FECHA_DOCUMENTS.sub("", _ABRE_DOCUMENTS.sub("", texto, count=1), count=1)
    if sem_marcas == texto:
        return linhas
    correcoes.append("Marcação <documents> do começo/fim da análise removida")
    return sem_marcas.split("\n")


def _nivel_das_subsecoes(linhas: list[str], correcoes: list[str]) -> list[str]:
    """"## Roteiro" e "## Despacho" depois de "## Proposta" são subseções: "### ..."."""
    na_proposta = False
    resultado = []
    for linha in linhas:
        if _PROPOSTA.match(linha):
            na_proposta = True
        elif na_proposta and (achado := _SUBSECAO_COMO_SECAO.match(linha)):
            correcoes.append(f"'## {achado.group(1)}' virou '### {achado.group(1)}' (subseção da Proposta)")
            linha = f"### {achado.group(1)}"
        resultado.append(linha)
    return resultado


def _remover_preencher_sem_marcador(linhas: list[str], correcoes: list[str]) -> list[str]:
    """Linha "Preencher: ..." nos Alertas só vale se houver um marcador [PREENCHER] na análise."""
    inicio = next((i for i, linha in enumerate(linhas) if _ALERTAS.match(linha)), None)
    if inicio is None:
        return linhas
    fim = _fim_da_secao(linhas, inicio)
    if any("[PREENCHER" in linha for linha in linhas[:inicio] + linhas[fim:]):
        return linhas
    sobraram = [linha for linha in linhas[inicio + 1:fim] if not _LINHA_PREENCHER.match(linha)]
    removidas = (fim - inicio - 1) - len(sobraram)
    if not removidas:
        return linhas
    correcoes.append(f"{removidas} linha(s) 'Preencher:' sem marcador [PREENCHER] na análise removida(s) dos Alertas")
    if not any(linha.strip() for linha in sobraram):
        sobraram = ["Nenhum alerta."]
    return linhas[:inicio + 1] + sobraram + linhas[fim:]


def _formatar_alertas(linhas: list[str], correcoes: list[str]) -> list[str]:
    """Cada alerta começa com "- " e fica separado do seguinte por uma linha em branco."""
    inicio = next((i for i, linha in enumerate(linhas) if _ALERTAS.match(linha)), None)
    if inicio is None:
        return linhas
    fim = _fim_da_secao(linhas, inicio)
    itens = [linha.strip() for linha in linhas[inicio + 1:fim] if linha.strip()]
    if not itens or (len(itens) == 1 and itens[0].startswith("Nenhum alerta")):
        return linhas
    novos = [f"- {_MARCADOR_DE_LISTA.sub('', item)}" for item in itens]
    bloco: list[str] = []
    for novo in novos:
        bloco += [novo, ""]
    if _sem_bordas([l.rstrip() for l in linhas[inicio + 1:fim]]) == _sem_bordas(bloco):
        return linhas
    correcoes.append("Alertas reformatados ('- ' no início e uma linha em branco entre eles)")
    return linhas[:inicio + 1] + bloco + linhas[fim:]


def _paragrafos(linhas: list[str]) -> list[list[str]]:
    paragrafos: list[list[str]] = [[]]
    for linha in linhas:
        if linha.strip():
            paragrafos[-1].append(linha)
        elif paragrafos[-1]:
            paragrafos.append([])
    return [p for p in paragrafos if p]


def _minuscula_inicial(texto: str) -> str:
    """Minúscula na primeira letra de uma palavra comum ("Informamos"); siglas ("SEI") ficam como estão."""
    if len(texto) > 1 and texto[0].isupper() and not texto[1].isupper():
        return texto[0].lower() + texto[1:]
    return texto


def _formatar_despacho(linhas: list[str], correcoes: list[str]) -> list[str]:
    """Linha em branco após o vocativo e a indicação de uso; frase partida em dois parágrafos volta a ser uma só."""
    inicio = next((i for i, linha in enumerate(linhas) if _DESPACHO.match(linha)), None)
    if inicio is None:
        return linhas
    fim = _fim_da_secao(linhas, inicio, parar_em_subsecao=True)
    paragrafos = _paragrafos(linhas[inicio + 1:fim])
    if not paragrafos:
        return linhas
    separados: list[list[str]] = []
    for paragrafo in paragrafos:  # vocativo e indicação de uso ficam sozinhos no parágrafo
        while len(paragrafo) > 1 and (
            (paragrafo[0].startswith("À ") and paragrafo[0].rstrip().endswith(","))
            or (_INDICACAO_DE_USO in paragrafo[0] and paragrafo[0].lstrip().startswith("("))
        ):
            separados.append([paragrafo[0]])
            paragrafo = paragrafo[1:]
        separados.append(paragrafo)
    juntos: list[list[str]] = []
    for paragrafo in separados:
        anterior = juntos[-1] if juntos else None
        if anterior and len(anterior) == 1 and anterior[0].rstrip().endswith(",") and not anterior[0].startswith(("À ", "(")):
            juntos[-1] = [f"{anterior[0].rstrip()} {_minuscula_inicial(paragrafo[0].lstrip())}", *paragrafo[1:]]
        else:
            juntos.append(paragrafo)
    bloco: list[str] = []
    for paragrafo in juntos:
        bloco += [*paragrafo, ""]
    if _sem_bordas([l.rstrip() for l in linhas[inicio + 1:fim]]) == _sem_bordas(bloco):
        return linhas
    if len(juntos) < len(separados):
        correcoes.append("Despacho: frase partida em dois parágrafos (terminava em vírgula) foi reunida")
    else:
        correcoes.append("Despacho reformatado (linha em branco após o vocativo e entre os parágrafos)")
    return linhas[:inicio + 1] + bloco + linhas[fim:]


def _espacos_em_branco(linhas: list[str]) -> list[str]:
    """No máximo uma linha em branco seguida; sem espaços no fim das linhas."""
    resultado: list[str] = []
    for linha in (l.rstrip() for l in linhas):
        if linha or (resultado and resultado[-1]):
            resultado.append(linha)
    while resultado and not resultado[-1]:
        resultado.pop()
    return resultado


def corrigir_formato(markdown: str) -> tuple[str, list[str]]:
    """Devolve a análise com o formato corrigido e a lista do que foi corrigido (vazia se nada mudou)."""
    correcoes: list[str] = []
    linhas = markdown.replace("\r\n", "\n").split("\n")
    linhas = _sem_marcacao_documents(linhas, correcoes)
    linhas = _nivel_das_subsecoes(linhas, correcoes)
    linhas = _remover_preencher_sem_marcador(linhas, correcoes)
    linhas = _formatar_alertas(linhas, correcoes)
    linhas = _formatar_despacho(linhas, correcoes)
    return "\n".join(_espacos_em_branco(linhas)) + "\n", correcoes
