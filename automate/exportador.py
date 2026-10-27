"""Exporta um ProcessoSEI como JSON para o gatilho do Power Automate."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from datetime import date, datetime
from pathlib import Path

from automate.extracao import data_assinatura, destinatarios, dominios_de_email, prazos_no_texto, usar_nome_atual_em
from sei.modelos import DocumentoSEI, ProcessoSEI, nome_seguro

SCHEMA_VERSION = "1.2"

# Nossa unidade: SUPCONFI e SUPCONC são a mesma (nome antigo e atual).
_SIGLAS_NOSSAS = r"\b(?:SUPCONC|SUPCONFI)\b"
_NOMES_NOSSOS = (
    "SUPERINTENDENCIA DE CONTROLES FINANCEIROS",
    "SUPERINTENDENCIA DE CONTABILIDADE E CONCILIACAO",
)
_SIGLAS_SUPERIOR = {"SUBAFIN", "SUBTES"}
_SIGLAS_SUBORDINADA = {"COOCB", "COOCONC"}
# O endereçamento ("À SUPCONC,", "com vistas à SUPCONFI") fica nas primeiras linhas do despacho.
_LINHAS_DE_ENDERECAMENTO = 12
_INICIO_DE_ENDERECAMENTO = ("A ", "AO ", "AOS ", "AS ", "C/ VISTAS", "C/VISTAS", "COM VISTAS")
# O destinatário É a nossa unidade (e não, por exemplo, "à chefia da SUPCONFI").
_DESTINO_NOSSO = re.compile(
    r"^(?:A|AS|AO|AOS|COM VISTAS A|COM VISTAS AO|C/ ?VISTAS A|C/ ?VISTAS AO)\s+(?:(?:A|O)\s+)?(?:SEFAZ/)?"
    r"(?:SUPCONC|SUPCONFI|" + "|".join(re.escape(n) for n in _NOMES_NOSSOS) + r")\b"
)

UNIDADE_NAO_INFORMADA = "Unidade não informada"
DOCUMENTO_EXTERNO = "documento externo"
PAPEL_RESPOSTA_NOSSA = "resposta da SUPCONFI"
PAPEL_PEDIDO_A_NOS = "pedido à SUPCONFI"


def _normalizar(texto: str | None) -> str:
    """Maiúsculas e sem acentos, para comparar siglas e nomes."""
    sem_acento = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").upper()


def _formatar(data: date | None) -> str | None:
    return data.strftime("%d/%m/%Y") if data else None


def _eh_nossa(unidade: str | None) -> bool:
    return re.search(_SIGLAS_NOSSAS, _normalizar(unidade)) is not None


def _cita_nossa_unidade(linha: str) -> bool:
    normalizada = _normalizar(linha)
    return re.search(_SIGLAS_NOSSAS, normalizada) is not None or any(n in normalizada for n in _NOMES_NOSSOS)


def _enderecado_a_nos(texto: str | None) -> bool:
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()][:_LINHAS_DE_ENDERECAMENTO]
    return any(
        _normalizar(l).startswith(_INICIO_DE_ENDERECAMENTO) and _cita_nossa_unidade(l) for l in linhas
    )


def _cita_nos(texto: str | None) -> bool:
    return _cita_nossa_unidade(texto or "")


def _destino_e_nosso(destino: str) -> bool:
    return _DESTINO_NOSSO.match(_normalizar(destino)) is not None


def classificar_nivel(unidade: str | None) -> str | None:
    """SUPERIOR / SUBORDINADA / INTERNA / EXTERNA, só pela sigla e pelo prefixo; sem unidade, None."""
    if not unidade or not unidade.strip():
        return None
    normalizada = _normalizar(unidade).strip()
    sigla = normalizada.split("/")[-1].strip()
    if sigla in _SIGLAS_SUPERIOR:
        return "SUPERIOR"
    if sigla in _SIGLAS_SUBORDINADA:
        return "SUBORDINADA"
    if normalizada.startswith("SEFAZ/"):
        return "INTERNA"
    return "EXTERNA"


def _resumo(ordem: int, doc: DocumentoSEI) -> dict:
    return {"ordem": ordem, "nome": doc.nome, "unidade": doc.unidade}


def localizar_despacho_demandante(documentos: list[DocumentoSEI]) -> tuple[int, DocumentoSEI, str] | None:
    """Documento mais recente de outra unidade que pede algo a nós, e o critério usado para achá-lo.

    Do mais forte ao mais fraco: endereçado a nós no cabeçalho; citando nossa unidade no texto;
    simplesmente o último documento de outra unidade.
    """
    de_outras = [(o, d) for o, d in enumerate(documentos, start=1) if not _eh_nossa(d.unidade)]
    for criterio, confere in (("enderecado_a_nos", _enderecado_a_nos), ("citado_no_texto", _cita_nos)):
        for ordem, doc in reversed(de_outras):
            if confere(doc.texto):
                return ordem, doc, criterio
    if de_outras:
        ordem, doc = de_outras[-1]
        return ordem, doc, "ultimo_de_outra_unidade"
    return None


def _assinatura(doc: DocumentoSEI) -> date | None:
    """Só documentos internos (HTML do SEI) têm assinatura eletrônica do próprio SEI."""
    return data_assinatura(doc.texto) if doc.origem_texto == "sei_html" else None


def _destinos(doc: DocumentoSEI) -> list[str]:
    return destinatarios(doc.texto) if doc.origem_texto == "sei_html" else []


def _destinatario(doc: DocumentoSEI, destinos: list[str]) -> str | None:
    """Linhas "À / Ao / Com vistas à" dos documentos internos; "documento externo" nos demais."""
    if doc.origem_texto != "sei_html":
        return DOCUMENTO_EXTERNO
    return " / ".join(destinos) if destinos else None


def _papel(ordem: int, doc: DocumentoSEI, ordens_nossas: set[int], destinos: list[str]) -> str | None:
    """Papéis decididos por regra; None deixa para a IA os que dependem de interpretação."""
    if ordem in ordens_nossas:
        return PAPEL_RESPOSTA_NOSSA
    if any(_destino_e_nosso(destino) for destino in destinos):
        return PAPEL_PEDIDO_A_NOS
    if ordem == 1:
        return "origem"
    if doc.origem_texto != "sei_html":
        return "informação"
    return None


def _item_da_linha_do_tempo(ordem: int, doc: DocumentoSEI, ordens_nossas: set[int]) -> dict:
    destinos = _destinos(doc)
    return {
        "ordem": ordem,
        "nome": doc.nome,
        "unidade": doc.unidade or UNIDADE_NAO_INFORMADA,
        "destinatario": _destinatario(doc, destinos),
        "papel": _papel(ordem, doc, ordens_nossas, destinos),
        "data_assinatura": _formatar(_assinatura(doc)),
    }


def _situacao_resposta(demandante: tuple[int, DocumentoSEI, str] | None, nossas: list[dict]) -> dict | None:
    """Compara a ordem da nossa última manifestação com a do despacho demandante."""
    if not demandante:
        return None
    ordem_demandante = demandante[0]
    if not nossas:
        return {
            "valor": "SEM MANIFESTAÇÃO ANTERIOR",
            "definitivo": True,
            "motivo": "Nenhum documento da SUPCONFI consta no processo.",
        }
    ultima = nossas[-1]
    referencia = f"{ultima['nome']} (ordem {ultima['ordem']})"
    if ultima["ordem"] < ordem_demandante:
        return {
            "valor": "NOVA DEMANDA APÓS RESPOSTA",
            "definitivo": False,
            "motivo": f"Nossa última manifestação, {referencia}, é anterior ao despacho demandante (ordem {ordem_demandante}).",
        }
    return {
        "valor": None,
        "definitivo": False,
        "motivo": (
            f"Nossa última manifestação, {referencia}, é posterior ao despacho demandante "
            f"(ordem {ordem_demandante}). DECIDA: leia essa manifestação e escreva JÁ RESPONDIDO (atendeu ao "
            "pedido) ou RESPOSTA PARCIAL (parte ficou pendente). Não copie esta frase."
        ),
    }


def _competencia(demandante: tuple[int, DocumentoSEI, str] | None) -> str | None:
    """Frase pronta quando a competência decorre do endereçamento; None se a IA precisa decidir."""
    if not demandante:
        return "NÃO FOI POSSÍVEL DETERMINAR. Nenhum despacho demandante foi identificado."
    ordem, doc, criterio = demandante
    if criterio == "enderecado_a_nos":
        return f"COMPETÊNCIA IDENTIFICADA. Pedido endereçado expressamente à SUPCONFI no {doc.nome} (ordem {ordem})."
    return None


def _solicitante_demanda_texto(demandante: tuple[int, DocumentoSEI, str] | None) -> str | None:
    if not demandante:
        return None
    ordem, doc, _ = demandante
    data = _formatar(_assinatura(doc)) or "data de assinatura não identificada nos documentos fornecidos"
    return f"{doc.unidade or UNIDADE_NAO_INFORMADA}, conforme {doc.nome} (ordem {ordem}), de {data}"


def _solicitante_origem(documentos: list[DocumentoSEI]) -> dict | None:
    """Documento de ordem 1: "via" é a unidade dele; se for interno, o solicitante é só a unidade.

    Num documento externo o autor sai do timbre ou da assinatura; os domínios de e-mail ajudam quando o
    texto extraído não traz o timbre.
    """
    if not documentos:
        return None
    primeiro = documentos[0]
    unidade = primeiro.unidade or UNIDADE_NAO_INFORMADA
    interno = primeiro.origem_texto == "sei_html"
    return {
        "via": unidade,
        "texto": unidade if interno else None,
        "dominios_de_email": [] if interno else dominios_de_email(primeiro.texto),
    }


def _prazos_encontrados(documentos: list[DocumentoSEI], hoje: date, chegada: date | None) -> list[dict]:
    """Datas perto de "prazo", "até o dia" etc., uma por data, já comparadas com a referência e a chegada.

    "fontes" lista os documentos que citam a data, na ordem do processo: prorrogações e dilações aparecem
    em documentos posteriores, e é a IA quem decide qual prazo vale.
    """
    por_data: dict[date, list[dict]] = {}
    for ordem, doc in enumerate(documentos, start=1):
        for data, trecho in prazos_no_texto(doc.texto):
            por_data.setdefault(data, []).append({"ordem": ordem, "documento": doc.nome, "trecho": trecho})
    prazos = []
    for data in sorted(por_data):
        dias = (data - hoje).days
        prazos.append({
            "data": _formatar(data),
            "situacao": "VENCIDO" if dias < 0 else "NO PRAZO",
            "dias": abs(dias),
            "chegada": None if chegada is None else ("depois" if chegada > data else "antes"),
            "fontes": por_data[data],
        })
    return prazos


def _lista_de_documentos(docs: list[tuple[int, DocumentoSEI]]) -> str:
    return "; ".join(f"ordem {ordem} - {doc.nome}" for ordem, doc in docs)


def _alertas_automaticos(documentos: list[DocumentoSEI], demandante, nivel: str | None) -> list[str]:
    """Problemas que se descobrem por regra. A IA copia estes alertas e acrescenta os que interpretar."""
    alertas = []
    if not demandante:
        alertas.append(
            "Nenhum documento de outra unidade foi identificado como despacho demandante; não há providência a propor."
        )
    else:
        ordem, doc, criterio = demandante
        referencia = f"{doc.nome}, ordem {ordem}"
        if criterio == "citado_no_texto":
            alertas.append(
                f"O despacho demandante ({referencia}) não é endereçado expressamente à nossa unidade; "
                "apenas cita a SUPCONFI no texto."
            )
        elif criterio == "ultimo_de_outra_unidade":
            alertas.append(
                f"Nenhum documento é endereçado ou cita a nossa unidade; o último documento de outra unidade "
                f"({referencia}) foi adotado como despacho demandante e precisa ser confirmado."
            )
        if not doc.texto:
            alertas.append(
                f"O despacho demandante ({referencia}) está sem texto extraído; a análise do pedido pode estar incompleta."
            )
        if nivel is None:
            alertas.append("A unidade do solicitante da demanda não foi informada pelo SEI.")
    ordem_demandante = demandante[0] if demandante else None
    sem_texto = [
        (o, d) for o, d in enumerate(documentos, start=1)
        if not d.texto and not d.motivo_sem_texto and o != ordem_demandante
    ]
    if sem_texto:
        alertas.append(f"Documentos sem texto extraído: {_lista_de_documentos(sem_texto)}.")
    por_motivo: dict[str, list[tuple[int, DocumentoSEI]]] = {}
    for ordem, doc in enumerate(documentos, start=1):
        if not doc.texto and doc.motivo_sem_texto:
            por_motivo.setdefault(doc.motivo_sem_texto, []).append((ordem, doc))
    for motivo, docs in por_motivo.items():
        alertas.append(f"Documentos não lidos ({motivo}): {_lista_de_documentos(docs)}.")
    return alertas


def calcular_pre_calculado(processo: ProcessoSEI, data_referencia: datetime) -> dict:
    """Campos de regra fixa, para a IA só interpretar em vez de recalcular."""
    documentos = processo.documentos
    demandante = localizar_despacho_demandante(documentos)
    if demandante:
        ordem, doc, criterio = demandante
        chegada = _assinatura(doc)
        despacho = {**_resumo(ordem, doc), "criterio": criterio, "data_assinatura": _formatar(chegada)}
    else:
        doc, despacho, chegada = None, None, None
    nossas = [_resumo(ordem, d) for ordem, d in enumerate(documentos, start=1) if _eh_nossa(d.unidade)]
    ordens_nossas = {n["ordem"] for n in nossas}
    nivel = classificar_nivel(doc.unidade) if doc else None
    return {
        "data_referencia": data_referencia.strftime("%d/%m/%Y"),
        "despacho_demandante": despacho,
        "solicitante_demanda": doc.unidade if doc else None,
        "solicitante_demanda_texto": _solicitante_demanda_texto(demandante),
        "nivel_demanda": nivel,
        "solicitante_origem": _solicitante_origem(documentos),
        "situacao_resposta": _situacao_resposta(demandante, nossas),
        "competencia": _competencia(demandante),
        "manifestacoes_nossas": nossas,
        "linha_do_tempo": [
            _item_da_linha_do_tempo(ordem, d, ordens_nossas) for ordem, d in enumerate(documentos, start=1)
        ],
        "prazos_encontrados": _prazos_encontrados(documentos, data_referencia.date(), chegada),
        "alertas_automaticos": _alertas_automaticos(documentos, demandante, nivel),
    }


def _texto_do_documento(doc: DocumentoSEI) -> str:
    if doc.texto:
        return doc.texto
    return f"[SEM TEXTO EXTRAÍDO: {doc.motivo_sem_texto}]" if doc.motivo_sem_texto else "[SEM TEXTO EXTRAÍDO]"


def preparar_para_automate(processo: ProcessoSEI) -> dict:
    sem_texto = [doc.nome for doc in processo.documentos if not doc.texto]
    agora = datetime.now().astimezone()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "gerado_em": agora.isoformat(timespec="seconds"),
        "status": "aguardando_analise",
        "processo": {
            "numero": processo.numero,
            "tipo": processo.tipo,
            "especificacao": processo.especificacao,
            "interessados": processo.interessados,
            "anotacao": processo.anotacao,
            "marcadores": processo.marcadores,
            "atribuicao": processo.atribuicao,
            "ultima_movimentacao": processo.ultima_movimentacao,
        },
        "controle": {
            "quantidade_documentos": len(processo.documentos),
            "documentos_sem_texto": sem_texto,
            "necessita_revisao_humana": True,
        },
        "pre_calculado": calcular_pre_calculado(processo, agora),
        "documentos": [
            {
                "ordem": ordem,
                "nome": doc.nome,
                "unidade": doc.unidade,
                "origem_texto": doc.origem_texto,
                "texto": _texto_do_documento(doc),
            }
            for ordem, doc in enumerate(processo.documentos, start=1)
        ],
    }
    # A IA recebe só os nomes atuais das unidades (SUPCONFI, SUPHOB, SUPADFIN). O cálculo acima já usou o conteúdo
    # original, e os nomes de documentos ficam como na fonte.
    return usar_nome_atual_em(payload, protegidos={doc.nome for doc in processo.documentos})


def exportar_para_automate(processo: ProcessoSEI, pasta: Path) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"ENTRADA_{nome_seguro(processo.numero)}.json"
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(preparar_para_automate(processo), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporario.replace(destino)  # evita gatilho lendo arquivo incompleto
    return destino


def copiar_para_sharepoint(arquivo: Path, pasta_sincronizada: Path) -> Path:
    """Copia o JSON para a pasta do SharePoint sincronizada pelo OneDrive, que faz o upload."""
    arquivo = Path(arquivo)
    pasta_sincronizada = Path(pasta_sincronizada)
    if not pasta_sincronizada.is_dir():
        raise FileNotFoundError(
            f"Pasta do SharePoint não encontrada (OneDrive sincronizando?): {pasta_sincronizada}"
        )
    destino = pasta_sincronizada / arquivo.name
    shutil.copyfile(arquivo, destino)
    return destino
