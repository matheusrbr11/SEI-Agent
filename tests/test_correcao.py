from automate.correcao import corrigir_formato


def _analise(alertas="Nenhum alerta.", despacho="À SEFAZ/SUBTES,\n\nEm atenção ao despacho, damos ciência.", contexto="Resumo."):
    return (
        f"## Contexto\n{contexto}\n\n"
        "## Proposta\nTipo: CIÊNCIA - Só dá ciência.\n\n### Roteiro\nNão se aplica.\n\n"
        f"### Despacho\n{despacho}\n\n## Alertas\n{alertas}\n"
    )


def test_analise_ja_correta_nao_muda():
    texto = _analise(alertas="- Prazo vencido há 81 dias.\n\n- Documento ausente.")
    assert corrigir_formato(texto) == (texto, [])


def test_despacho_e_roteiro_viram_subsecoes_da_proposta():
    errado = _analise().replace("### Despacho", "## Despacho").replace("### Roteiro", "## Roteiro")
    corrigido, correcoes = corrigir_formato(errado)
    assert corrigido == _analise()
    assert correcoes == [
        "'## Roteiro' virou '### Roteiro' (subseção da Proposta)",
        "'## Despacho' virou '### Despacho' (subseção da Proposta)",
    ]


def test_titulo_igual_antes_da_proposta_nao_e_mexido():
    texto = "## Despacho\nTexto de uma seção antiga.\n\n" + _analise()
    assert corrigir_formato(texto)[0].startswith("## Despacho\n")


def test_linha_preencher_sem_marcador_e_removida_dos_alertas():
    corrigido, correcoes = corrigir_formato(_analise(alertas="- Prazo vencido.\n\n- Preencher: algo (provável fonte: x)"))
    assert corrigido == _analise(alertas="- Prazo vencido.")
    assert correcoes == ["1 linha(s) 'Preencher:' sem marcador [PREENCHER] na análise removida(s) dos Alertas"]


def test_linha_preencher_e_mantida_quando_ha_marcador():
    texto = _analise(
        alertas="- Preencher: nº do documento (provável fonte: sistema)",
        despacho="À SEFAZ/SUBTES,\n\nO documento nº [PREENCHER: nº] foi gerado.",
    )
    assert corrigir_formato(texto) == (texto, [])


def test_se_so_havia_preencher_sem_marcador_vira_nenhum_alerta():
    corrigido, _ = corrigir_formato(_analise(alertas="- Preencher: algo (provável fonte: x)"))
    assert corrigido == _analise(alertas="Nenhum alerta.")


def test_alertas_ganham_marcador_e_linha_em_branco():
    corrigido, correcoes = corrigir_formato(_analise(alertas="1. Prazo vencido.\n2) Documento ausente.\n* Outro fato."))
    assert corrigido == _analise(alertas="- Prazo vencido.\n\n- Documento ausente.\n\n- Outro fato.")
    assert correcoes == ["Alertas reformatados ('- ' no início e uma linha em branco entre eles)"]


def test_nenhum_alerta_nao_e_mexido():
    assert corrigir_formato(_analise(alertas="Nenhum alerta."))[1] == []


def test_frase_partida_no_despacho_e_reunida():
    partido = "À SEFAZ/SUBTES,\n\nEm atendimento ao despacho SEI nº 141137222,\n\nInformamos que anexamos.\n\nRestituímos o processo."
    esperado = "À SEFAZ/SUBTES,\n\nEm atendimento ao despacho SEI nº 141137222, informamos que anexamos.\n\nRestituímos o processo."
    corrigido, correcoes = corrigir_formato(_analise(despacho=partido))
    assert corrigido == _analise(despacho=esperado)
    assert correcoes == ["Despacho: frase partida em dois parágrafos (terminava em vírgula) foi reunida"]


def test_sigla_apos_a_virgula_continua_em_maiusculas():
    partido = "À SEFAZ/SUBTES,\n\nConforme o despacho,\n\nSEI nº 1 foi anexado."
    corrigido, _ = corrigir_formato(_analise(despacho=partido))
    assert "Conforme o despacho, SEI nº 1 foi anexado." in corrigido


def test_vocativo_e_indicacao_de_uso_ficam_em_paragrafos_proprios():
    colado = "(usar somente após a execução)\nÀ SEFAZ/SUBTES,\nEm atenção ao despacho, damos ciência."
    esperado = "(usar somente após a execução)\n\nÀ SEFAZ/SUBTES,\n\nEm atenção ao despacho, damos ciência."
    corrigido, correcoes = corrigir_formato(_analise(despacho=colado))
    assert corrigido == _analise(despacho=esperado)
    assert correcoes == ["Despacho reformatado (linha em branco após o vocativo e entre os parágrafos)"]


def test_correcoes_sao_idempotentes():
    bagunca = (
        _analise(alertas="1. A\n2. Preencher: x (provável fonte: y)", despacho="À X,\nEm atenção,\n\nInformamos.")
        .replace("### Despacho", "## Despacho")
    )
    uma_vez, correcoes = corrigir_formato(bagunca)
    assert correcoes
    assert corrigir_formato(uma_vez) == (uma_vez, [])


def test_linhas_em_branco_repetidas_e_espacos_no_fim():
    texto = _analise(contexto="Resumo.   \n\n\n\nMais.")
    assert "Resumo.\n\nMais." in corrigir_formato(texto)[0]


def test_quebras_de_linha_do_windows():
    corrigido, _ = corrigir_formato(_analise().replace("\n", "\r\n"))
    assert "\r" not in corrigido
