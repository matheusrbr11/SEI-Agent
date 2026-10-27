"""Confere a análise gerada pela IA (.md) contra os campos calculados no JSON de entrada.

Uso:
    python -m automate.validador ANALISE.md ENTRADA.json

Cada problema é uma linha "ERRO: ..." (a análise contraria o que o sistema calculou ou o formato) ou
"AVISO: ..." (merece olhar humano). Código de saída 1 se houver algum ERRO.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from automate.extracao import NOMES_ATUAIS, nomes_antigos_em

SECOES = (
    "Processo",
    "Solicitante Origem",
    "Solicitante Demanda",
    "Contexto",
    "Demanda",
    "Pendências",
    "Informações Relevantes",
    "Proposta",
    "Alertas",
)
TIPOS_DE_PROVIDENCIA = (
    "EXECUÇÃO", "RESPOSTA - DESPACHO", "RESPOSTA - NOTA TÉCNICA", "CIÊNCIA", "FORA DA COMPETÊNCIA", "JÁ RESPONDIDO",
)
COMPETENCIAS = (
    "COMPETÊNCIA IDENTIFICADA", "COMPETÊNCIA PARCIAL", "APARENTEMENTE FORA DA COMPETÊNCIA", "NÃO FOI POSSÍVEL DETERMINAR",
)
SITUACOES = ("SEM MANIFESTAÇÃO ANTERIOR", "JÁ RESPONDIDO", "RESPOSTA PARCIAL", "NOVA DEMANDA APÓS RESPOSTA")
CAMPOS_TECNICOS = (
    "pre_calculado", "origem_texto", "enderecado_a_nos", "citado_no_texto", "ultimo_de_outra_unidade",
    "manifestacoes_nossas", "linha_do_tempo", "despacho_demandante", "nivel_demanda", "solicitante_demanda_texto",
    "solicitante_origem", "situacao_resposta", "alertas_automaticos", "prazos_encontrados", "documentos_sem_texto",
    "data_assinatura", "criterio",
)
MAXIMO_DE_LINHAS_DO_CONTEXTO = 5

_CABECALHO = re.compile(r"^(#{1,2})\s+(.+?)\s*$")
_SUBSECAO = re.compile(r"^###\s+(.+?)\s*$")
_ITEM_DE_LISTA = re.compile(r"^ ?[-*]\s+(.*\S)\s*$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_MARCADOR_PREENCHER = re.compile(r"\[PREENCHER[^\]]*\]")
_LINHA_PREENCHER = re.compile(r"^\s*(?:\d+[.)]\s*|[-*]\s+)?Preencher:", re.I)
_DATA_NO_INICIO = re.compile(r"(\d{2}/\d{2}/\d{4})")
_SITUACAO_E_DIAS = re.compile(r"(NO PRAZO|VENCIDO)\D*?(\d+)\s+dias?")
_CHEGADA = re.compile(r"chegada a nós em (\d{2}/\d{2}/\d{4})\s*\((antes|depois)", re.I)
_ORDEM_DE_CONFERENCIA = r"(?:\d+[.)]\s*|[-*]\s+)?(?:conferir|verificar|confirmar)\b"
_ALERTA_GENERICO = re.compile(
    rf"^\s*{_ORDEM_DE_CONFERENCIA}|:\s*(?:conferir|verificar|confirmar)\b|\b(?:caso haja|se for o caso|se houver)\b", re.I
)
_PENDENCIA_DE_CONFERENCIA = re.compile(rf"^\s*{_ORDEM_DE_CONFERENCIA}", re.I | re.M)
_REPETE_ALERTA_DO_SISTEMA = re.compile(r"sem texto extra[ií]do|não lid[ao]s?\b", re.I)
_PASSO = re.compile(r"^\s*\d+\.\s+\S")
_DETALHE = re.compile(r"^(\s*)[-*]\s*(?:Valor|Data do fato|Conta/origem e destino|Origem dos documentos):", re.I)
_DETALHE_SEM_DADO = re.compile(
    r"^\s*[-*]\s*(?:Valor|Data do fato|Conta/origem e destino|Origem dos documentos):\s*Não identificado", re.I | re.M
)


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _secoes(markdown: str) -> tuple[dict[str, str], list[str], list[str], list[str]]:
    """Corpo de cada seção esperada, a ordem delas, os títulos "##" desconhecidos e os títulos "#"."""
    esperadas = {titulo.casefold(): titulo for titulo in SECOES}
    corpos: dict[str, list[str]] = {}
    desconhecidos: list[str] = []
    nivel_um: list[str] = []
    atual = None
    for linha in markdown.splitlines():
        cabecalho = _CABECALHO.match(linha)
        if not cabecalho:
            if atual:
                corpos[atual].append(linha)
            continue
        if len(cabecalho.group(1)) == 1:
            nivel_um.append(cabecalho.group(2))
            atual = None
            continue
        titulo = esperadas.get(cabecalho.group(2).casefold())
        if titulo and titulo not in corpos:
            atual = titulo
            corpos[atual] = []
        else:
            desconhecidos.append(cabecalho.group(2))
            atual = None
    return {t: "\n".join(linhas).strip() for t, linhas in corpos.items()}, list(corpos), desconhecidos, nivel_um


def _subsecoes(corpo: str) -> tuple[str, dict[str, str]]:
    """Texto antes do primeiro "###" e o corpo de cada "### Título" (em minúsculas)."""
    antes: list[str] = []
    partes: dict[str, list[str]] = {}
    atual = None
    for linha in corpo.splitlines():
        subsecao = _SUBSECAO.match(linha)
        if subsecao:
            atual = subsecao.group(1).casefold()
            partes.setdefault(atual, [])
        elif atual:
            partes[atual].append(linha)
        else:
            antes.append(linha)
    return "\n".join(antes).strip(), {titulo: "\n".join(linhas).strip() for titulo, linhas in partes.items()}


def _itens(corpo: str) -> list[tuple[str, str]]:
    """Itens "- Rótulo: texto" da seção; linhas seguintes e sub-itens recuados fazem parte do item."""
    itens: list[list[str]] = []
    for linha in corpo.splitlines():
        item = _ITEM_DE_LISTA.match(linha)
        if item:
            itens.append([item.group(1)])
        elif itens and linha.strip():
            itens[-1].append(linha.strip())
    resultado = []
    for linhas in itens:
        rotulo, _, resto = " ".join(linhas).partition(":")
        resultado.append((rotulo.strip().casefold(), resto.strip()))
    return resultado


def _item(itens: list[tuple[str, str]], prefixo: str) -> str | None:
    return next((texto for rotulo, texto in itens if rotulo.startswith(prefixo.casefold())), None)


def _conferir_estrutura(secoes: dict[str, str], ordem: list[str], desconhecidos: list[str], nivel_um: list[str]) -> list[str]:
    problemas = [f"ERRO: seção ausente: {titulo}" for titulo in SECOES if titulo not in secoes]
    problemas += [f"ERRO: seção fora do formato (remova ou mova o conteúdo): {titulo}" for titulo in desconhecidos]
    problemas += [f"AVISO: título de nível 1 fora do formato: {titulo}" for titulo in nivel_um]
    if not any("ausente" in p for p in problemas) and ordem != list(SECOES):
        problemas.append("ERRO: as seções estão fora da ordem do formato")
    return problemas


def _emails_da_entrada(entrada: dict) -> set[str]:
    texto = " ".join(documento.get("texto") or "" for documento in entrada["documentos"])
    texto += " " + json.dumps(entrada["pre_calculado"], ensure_ascii=False)
    return {email.lower() for email in _EMAIL.findall(texto)}


def _linhas_coladas(corpo: str) -> bool:
    """Há duas linhas com texto, uma logo abaixo da outra, sem linha em branco entre elas?"""
    linhas = corpo.splitlines()
    return any(acima.strip() and abaixo.strip() for acima, abaixo in zip(linhas, linhas[1:]))


def _conferir_nomes_e_campos(markdown: str, entrada: dict) -> list[str]:
    problemas = []
    conhecidos = _emails_da_entrada(entrada)
    for email in sorted({e.lower() for e in _EMAIL.findall(markdown)} - conhecidos):
        problemas.append(
            f"ERRO: e-mail que não consta nos documentos: {email} (a troca de nomes de unidades não vale para "
            "endereços de e-mail; copie-os como estão)"
        )
    protegidos = {documento["nome"] for documento in entrada["documentos"]}
    for antigo in nomes_antigos_em(markdown, protegidos):
        problemas.append(f"ERRO: a análise usa {antigo}; deve usar {NOMES_ATUAIS[antigo]} (nome atual da unidade)")
    for campo in CAMPOS_TECNICOS:
        if re.search(rf"\b{campo}\b", markdown):
            problemas.append(f"ERRO: nome de campo técnico na análise: {campo}")
    return problemas


def _conferir_cabecalho(secoes: dict[str, str], entrada: dict) -> list[str]:
    problemas = []
    pre = entrada["pre_calculado"]
    if entrada["processo"]["numero"] not in secoes["Processo"]:
        problemas.append("ERRO: a seção Processo não traz o número do processo")
    origem = pre["solicitante_origem"]
    texto_origem = _plano(secoes["Solicitante Origem"])
    if "[" in texto_origem:
        problemas.append("ERRO: o Solicitante Origem tem marcador entre colchetes")
    elif origem and origem["texto"] and texto_origem.rstrip(".") != origem["texto"]:
        problemas.append(f"ERRO: Solicitante Origem deveria ser só {origem['texto']}")
    elif origem and not origem["texto"] and f"(via {origem['via']})" not in texto_origem:
        problemas.append(f"ERRO: Solicitante Origem sem o trecho (via {origem['via']})")
    if pre["solicitante_demanda_texto"]:
        nivel = pre["nivel_demanda"] or "nível não informado"
        esperado = f"{pre['solicitante_demanda_texto']} ({nivel})"
        if _plano(secoes["Solicitante Demanda"]).rstrip(".") != esperado:
            problemas.append(f"ERRO: Solicitante Demanda deveria ser: {esperado}")
    linhas_do_contexto = [linha for linha in secoes["Contexto"].splitlines() if linha.strip()]
    if len(linhas_do_contexto) > MAXIMO_DE_LINHAS_DO_CONTEXTO:
        problemas.append(f"AVISO: o Contexto tem {len(linhas_do_contexto)} linhas; o formato pede até {MAXIMO_DE_LINHAS_DO_CONTEXTO}")
    return problemas


def _conferir_demanda(corpo: str, pre: dict) -> list[str]:
    problemas = []
    if _linhas_coladas(corpo):
        problemas.append("AVISO: na Demanda, cada frase deve ficar separada da seguinte por uma linha em branco")
    despacho = pre["despacho_demandante"]
    if despacho and "Providência específica não identificada" not in corpo:
        referencia = f"{despacho['nome']} (ordem {despacho['ordem']})"
        if referencia not in corpo:
            problemas.append(f"AVISO: a Demanda não cita o despacho demandante como '{referencia}'")
    return problemas


def _conferir_forma_do_despacho(despacho: str) -> list[str]:
    """Linha em branco após o vocativo, entre parágrafos e antes do fecho; frase não pode ser partida em parágrafos."""
    problemas = []
    if _linhas_coladas(despacho):
        problemas.append(
            "AVISO: no Despacho, separe por uma linha em branco o vocativo, cada parágrafo e o fecho"
        )
    for paragrafo in (p.strip() for p in despacho.split("\n\n")):
        if paragrafo.endswith(",") and not paragrafo.startswith(("À ", "(")):
            problemas.append(f"AVISO: no Despacho, a frase parece partida em dois parágrafos (termina em vírgula): {paragrafo}")
    return problemas


def _ja_respondido(secoes: dict[str, str]) -> tuple[bool, bool]:
    """(a Situação de resposta é JÁ RESPONDIDO, o Tipo da Proposta é JÁ RESPONDIDO)."""
    situacao = _item(_itens(secoes["Informações Relevantes"]), "situação de resposta") or ""
    return situacao.startswith("JÁ RESPONDIDO"), _tipo(secoes["Proposta"]).startswith("JÁ RESPONDIDO")


def _tipo(proposta: str) -> str:
    antes, _ = _subsecoes(proposta)
    achado = re.search(r"^\s*Tipo:\s*(.+)$", antes, re.M)
    return _plano(achado.group(1)) if achado else ""


def _conferir_pendencias(corpo: str, ja_respondido: bool) -> list[str]:
    problemas = []
    for linha in corpo.splitlines():
        if _PENDENCIA_DE_CONFERENCIA.match(linha):
            problemas.append(
                "AVISO: pendência que é ordem de conferência (pendência é o que impede ou condiciona a execução): "
                f"{linha.strip()}"
            )
        elif _REPETE_ALERTA_DO_SISTEMA.search(linha):
            problemas.append(
                f"AVISO: pendência repete um alerta do sistema (documentos sem texto ou não lidos): {linha.strip()}"
            )
    if ja_respondido and not _plano(corpo).startswith("Nenhuma pendência: a demanda já foi atendida"):
        problemas.append("ERRO: demanda JÁ RESPONDIDA, mas a seção Pendências não diz 'Nenhuma pendência: a demanda já foi atendida…'")
    return problemas


def _conferir_situacao(texto: str, situacao: dict | None) -> list[str]:
    if not texto.startswith(SITUACOES):
        return ["ERRO: Situação de resposta não começa por um dos valores do formato"]
    if situacao and situacao["definitivo"] and not texto.startswith(situacao["valor"]):
        return [f"ERRO: Situação de resposta deveria ser {situacao['valor']} (calculada pelo sistema)"]
    if situacao and situacao["valor"] and not texto.startswith((situacao["valor"], "JÁ RESPONDIDO")):
        return [f"ERRO: Situação de resposta deveria ser {situacao['valor']} (ou JÁ RESPONDIDO, se justificado)"]
    if situacao and not situacao["valor"] and not texto.startswith(("JÁ RESPONDIDO", "RESPOSTA PARCIAL")):
        return ["ERRO: Situação de resposta deveria ser JÁ RESPONDIDO ou RESPOSTA PARCIAL"]
    return []


def _conferir_prazo(texto: str, pre: dict) -> list[str]:
    prazos = {p["data"]: p for p in pre["prazos_encontrados"]}
    plano = _plano(texto)
    if plano.casefold().startswith("não identificado"):
        problemas = []
        if prazos:
            problemas.append(
                f"AVISO: o sistema encontrou {len(prazos)} prazo(s) nos documentos ({', '.join(prazos)}), "
                "mas a análise diz 'Prazo: não identificado.'"
            )
        if "chegada" in plano.casefold():
            problemas.append("ERRO: Prazo 'não identificado' não deve comparar a chegada com um prazo")
        return problemas
    data = _DATA_NO_INICIO.match(plano)
    situacao = _SITUACAO_E_DIAS.search(plano)
    if not data or not situacao:
        return ["ERRO: o Prazo precisa da data, da situação (NO PRAZO / VENCIDO) e dos dias"]
    candidato = prazos.get(data.group(1))
    if not candidato:
        return [f"AVISO: o prazo {data.group(1)} não está entre os extraídos pelo sistema; confira a situação e os dias"]
    problemas = []
    if situacao.group(1) != candidato["situacao"]:
        problemas.append(f"ERRO: o prazo {data.group(1)} está {candidato['situacao']}, e não {situacao.group(1)}")
    if int(situacao.group(2)) != candidato["dias"]:
        problemas.append(f"ERRO: o prazo {data.group(1)} tem {candidato['dias']} dia(s) de diferença para a data de referência")
    if pre["data_referencia"] not in plano:
        problemas.append(f"ERRO: o Prazo não traz a data de referência {pre['data_referencia']}")
    chegada = pre["despacho_demandante"]["data_assinatura"] if pre["despacho_demandante"] else None
    achada = _CHEGADA.search(plano)
    if chegada and candidato["chegada"] and (not achada or achada.group(1) != chegada or achada.group(2).lower() != candidato["chegada"]):
        problemas.append(f"ERRO: a chegada a nós deveria ser {chegada} ({candidato['chegada']} do prazo)")
    return problemas


def _conferir_informacoes(corpo: str, pre: dict) -> list[str]:
    itens = _itens(corpo)
    problemas = []
    situacao = _item(itens, "situação de resposta")
    if situacao is None and pre["situacao_resposta"]:
        problemas.append("ERRO: faltou o item 'Situação de resposta' em Informações Relevantes")
    elif situacao is not None:
        problemas += _conferir_situacao(situacao, pre["situacao_resposta"])
    manifestacoes = _item(itens, "manifestações anteriores")
    if manifestacoes is None:
        problemas.append("ERRO: faltou o item 'Manifestações anteriores' em Informações Relevantes")
    elif not pre["manifestacoes_nossas"]:
        if manifestacoes.casefold().rstrip(".") != "nenhuma":
            problemas.append("ERRO: não há manifestação nossa no processo, mas o item Manifestações anteriores diz outra coisa")
    else:
        ausentes = [
            m["ordem"] for m in pre["manifestacoes_nossas"] if f"{m['ordem']} - {m['nome']}" not in manifestacoes
        ]
        if len(ausentes) == 1:
            problemas.append(f"AVISO: a manifestação nossa de ordem {ausentes[0]} não aparece em Manifestações anteriores")
        elif ausentes:  # um aviso só, em vez de um por manifestação: processos longos têm dezenas delas
            problemas.append(
                f"AVISO: {len(ausentes)} manifestações nossas não aparecem em Manifestações anteriores "
                f"(ordens {', '.join(map(str, ausentes))})"
            )
        if "resposta da supconfi" in manifestacoes.casefold():
            problemas.append("ERRO: 'resposta da SUPCONFI' não é tipo de documento; use o tipo real (despacho, ofício etc.)")
    prazo = _item(itens, "prazo")
    if prazo is None:
        problemas.append("ERRO: faltou o item 'Prazo' em Informações Relevantes")
    else:
        problemas += _conferir_prazo(prazo, pre)
    competencia = _item(itens, "competência")
    if competencia is None:
        problemas.append("ERRO: faltou o item 'Competência' em Informações Relevantes")
    elif pre["competencia"]:
        if _plano(pre["competencia"]) not in _plano(competencia):
            problemas.append(f"ERRO: Competência deveria ser: {pre['competencia']}")
    elif not competencia.startswith(COMPETENCIAS):
        problemas.append("ERRO: Competência não começa por um dos valores do formato")
    return problemas


def _sem_indicacao_de_uso(despacho: str) -> str:
    """Tira a primeira linha quando ela é só a indicação "(usar somente após a execução)"."""
    linhas = despacho.strip().splitlines()
    if linhas and "usar somente após a execução" in linhas[0] and not linhas[0].lstrip().startswith("À "):
        return "\n".join(linhas[1:]).lstrip()
    return despacho.lstrip()


def _conferir_proposta(proposta: str, pre: dict, situacao_ja_respondido: bool) -> list[str]:
    problemas = []
    tipo = _tipo(proposta)
    _, partes = _subsecoes(proposta)
    roteiro, despacho = partes.get("roteiro"), partes.get("despacho")
    for nome, parte in (("Roteiro", roteiro), ("Despacho", despacho)):
        if parte is None:
            problemas.append(f"ERRO: a Proposta não tem a subseção '### {nome}'")
    if not tipo.startswith(TIPOS_DE_PROVIDENCIA):
        problemas.append("ERRO: o Tipo da Proposta não começa por um dos valores do formato")
    if problemas:
        return problemas
    if situacao_ja_respondido != tipo.startswith("JÁ RESPONDIDO"):
        problemas.append("ERRO: o Tipo da Proposta e a Situação de resposta não batem (JÁ RESPONDIDO vale para os dois)")
    if tipo.startswith("EXECUÇÃO"):
        linhas = roteiro.splitlines()
        if "não se aplica" in roteiro.casefold() or not any(_PASSO.match(linha) for linha in linhas):
            problemas.append("ERRO: EXECUÇÃO exige o Roteiro com passos numerados ('1.', '2.')")
        if any(re.match(r"^[-*]\s+\S", linha) and not _DETALHE.match(linha) for linha in linhas):
            problemas.append("ERRO: o passo do Roteiro começa com '-'; use '1.', '2.'")
        if any(_DETALHE.match(linha) and not _DETALHE.match(linha).group(1) for linha in linhas):
            problemas.append("AVISO: as linhas de detalhe do Roteiro (Valor, Data do fato…) devem ficar recuadas dentro do passo")
        if _DETALHE_SEM_DADO.search(roteiro):
            problemas.append("AVISO: o Roteiro traz linhas 'Não identificado'; omita as linhas que não se aplicam")
        if "usar somente após a execução" not in despacho:
            problemas.append("ERRO: o Despacho de EXECUÇÃO deve trazer a indicação '(usar somente após a execução)'")
    elif _plano(roteiro).rstrip(".") != "Não se aplica":
        problemas.append("ERRO: fora de EXECUÇÃO o Roteiro deve ser apenas 'Não se aplica.'")
    problemas += _conferir_forma_do_despacho(despacho)
    if tipo.startswith("JÁ RESPONDIDO") and "Não há providência a propor" not in despacho:
        problemas.append("ERRO: demanda JÁ RESPONDIDA, mas o Despacho não é 'Não há providência a propor…'")
    elif not tipo.startswith("JÁ RESPONDIDO") and not _sem_indicacao_de_uso(despacho).startswith("À "):
        problemas.append("AVISO: o Despacho deveria começar por 'À [SOLICITANTE DEMANDA],'")
    if pre["despacho_demandante"] is None and (despacho or roteiro) and not tipo.startswith("JÁ RESPONDIDO"):
        problemas.append("AVISO: não há despacho demandante, mas a análise propõe providência")
    return problemas


def _conferir_alertas(corpo: str, secoes: dict[str, str], pre: dict) -> list[str]:
    plano = _plano(corpo)
    problemas = [
        f"ERRO: alerta calculado pelo sistema ausente: {alerta}"
        for alerta in pre["alertas_automaticos"] if _plano(alerta) not in plano
    ]
    if plano.startswith("Nenhum alerta") and len(plano) > len("Nenhum alerta."):
        problemas.append("AVISO: a seção de alertas diz 'Nenhum alerta.' mas traz outros textos")
    elif not plano.startswith("Nenhum alerta"):
        if any(linha.strip() and not linha.lstrip().startswith("- ") for linha in corpo.splitlines()):
            problemas.append("AVISO: cada alerta deve começar com '- '")
        if _linhas_coladas(corpo):
            problemas.append("AVISO: nos Alertas, separe cada alerta do seguinte por uma linha em branco")
    automaticos = [_plano(a) for a in pre["alertas_automaticos"]]
    for linha in corpo.splitlines():
        texto = linha.strip()
        if texto and _plano(texto) not in automaticos and not _LINHA_PREENCHER.match(texto) and _ALERTA_GENERICO.search(texto):
            problemas.append(f"AVISO: alerta genérico ou condicional (alerta é um fato, não uma ordem de conferência): {texto}")
    fora_dos_alertas = "\n".join(c for t, c in secoes.items() if t != "Alertas")
    marcadores = _MARCADOR_PREENCHER.findall(fora_dos_alertas)
    linhas_preencher = [linha for linha in corpo.splitlines() if _LINHA_PREENCHER.match(linha)]
    if marcadores and not linhas_preencher:
        problemas.append(f"ERRO: há {len(marcadores)} marcador(es) [PREENCHER] na análise, mas os Alertas não têm linhas 'Preencher: ...'")
    elif linhas_preencher and not marcadores:
        problemas.append("AVISO: há linhas 'Preencher: ...' nos Alertas, mas nenhum marcador [PREENCHER] na análise")
    elif len(marcadores) != len(linhas_preencher):
        problemas.append(
            f"AVISO: {len(marcadores)} marcador(es) [PREENCHER] na análise e {len(linhas_preencher)} linha(s) 'Preencher:' nos Alertas"
        )
    return problemas


def validar_saida(markdown: str, entrada: dict) -> list[str]:
    """Lista de problemas ("ERRO: ..." / "AVISO: ..."); vazia se a análise confere com o que o sistema calculou."""
    pre = entrada["pre_calculado"]
    secoes, ordem, desconhecidos, nivel_um = _secoes(markdown)
    problemas = _conferir_estrutura(secoes, ordem, desconhecidos, nivel_um)
    problemas += _conferir_nomes_e_campos(markdown, entrada)
    if any("ausente" in p for p in problemas):
        return problemas  # sem as seções, o resto das conferências não faz sentido
    situacao_ja_respondido, tipo_ja_respondido = _ja_respondido(secoes)
    problemas += _conferir_cabecalho(secoes, entrada)
    problemas += _conferir_demanda(secoes["Demanda"], pre)
    problemas += _conferir_pendencias(secoes["Pendências"], situacao_ja_respondido or tipo_ja_respondido)
    problemas += _conferir_informacoes(secoes["Informações Relevantes"], pre)
    problemas += _conferir_proposta(secoes["Proposta"], pre, situacao_ja_respondido)
    problemas += _conferir_alertas(secoes["Alertas"], secoes, pre)
    return problemas


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    markdown = Path(argv[1]).read_text(encoding="utf-8")
    entrada = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    problemas = validar_saida(markdown, entrada)
    for problema in problemas:
        print(problema)
    if not problemas:
        print("OK: a análise confere com o que o sistema calculou.")
    return 1 if any(p.startswith("ERRO") for p in problemas) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
