"""Camada 1 da revisão do juiz: checagem automática, sem LLM, das afirmações que o juiz não considerou apoiadas.

Para cada afirmação marcada como `parcial`, `sem_apoio` ou `contradita`, procura nas fontes entregues ao gerador:
- as referências jurídicas e os números citados (artigo, súmula, OJ, lei, percentuais, horas, prazos);
- a cobertura lexical: a fração das palavras de conteúdo da afirmação que aparece na fonte.

A checagem só aponta indícios. Cobertura alta não prova apoio (uma negação ou um número trocado passam), e
`contradita` nunca é tratada como falso alarme. A decisão final é da pessoa que revisa.
"""
import re
import unicodedata

LIMIAR_APOIO = 0.75   # cobertura a partir da qual a afirmação parece estar no texto da fonte
LIMIAR_POUCO = 0.40   # cobertura abaixo da qual a afirmação parece não estar em fonte nenhuma

_STOP = set('''
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com sem sob sobre
entre ate apos e ou mas nem que se ao aos a as como quando onde qual quais quanto cada todo toda todos todas
outro outra outros outras esse essa esses essas este esta estes estas isso isto aquele aquela ele ela eles elas
seu sua seus suas lhe lhes ser sao foi era sera seja sejam esta estao estar ter tem tera tenha deve devem pode
podem podera nao sim mais menos muito muita tambem ja ainda apenas so mesmo mesma assim entao porem contudo caso
fonte fontes conforme segundo acordo forma casos caso exemplo
'''.split())


def _sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def _normalizar(texto):
    return _sem_acento(texto or '').lower()


def palavras(texto):
    """Palavras de conteúdo, reduzidas aos 6 primeiros caracteres (aproxima plural e flexões)."""
    tokens = re.findall(r'[a-z]+|\d+', _normalizar(texto))
    return {t[:6] for t in tokens if t not in _STOP and (len(t) >= 4 or t.isdigit())}


def referencias(texto):
    """Referências jurídicas e números citados, normalizados (ex.: 'art 73', 'sumula 60', 'n 20')."""
    t = _normalizar(texto).replace('º', '').replace('°', '')
    t = re.sub(r'(?<=\d)\.(?=\d{3}\b)', '', t)   # 13.467 -> 13467
    refs = set()
    padroes = dict(art=r'\bart(?:igo)?s?\.?\s*(\d+)', sumula=r'\bsumulas?\s*(?:n\.?\s*|no\s*)?(\d+)',
                   oj=r'\b(?:oj|orientac\w* jurisprudencia\w*)\s*(?:n\.?\s*|no\s*)?(\d+)',
                   lei=r'\blei\s*(?:complementar\s*)?(?:n\.?\s*|no\s*)?(\d+)')
    for tipo, padrao in padroes.items():
        refs |= {f'{tipo} {int(n)}' for n in re.findall(padrao, t)}
    refs |= {f'n {int(n)}' for n in re.findall(r'\d+', t)}
    return refs


def separar_entrada(texto):
    """Desfaz `juiz.montar_entrada`: pergunta, ação, fontes numeradas, referência e resposta avaliada."""
    m_fontes = texto.index('\n\nFONTES ENTREGUES AO ASSISTENTE:\n')
    m_resposta = texto.rindex('\n\nRESPOSTA A AVALIAR:\n')
    cabeca = texto[:m_fontes]
    pergunta, acao = cabeca.removeprefix('PERGUNTA:\n').split('\n\nAÇÃO ESPERADA: ', 1)
    meio = texto[m_fontes + len('\n\nFONTES ENTREGUES AO ASSISTENTE:\n'):m_resposta]
    referencia = None
    marca_ref = '\n\nRESPOSTA DE REFERÊNCIA (curadoria):\n'
    if marca_ref in meio:
        meio, referencia = meio.rsplit(marca_ref, 1)
    fontes = []
    if meio.strip() != '(nenhuma)':
        partes = re.split(r'(?m)^\[Fonte (\d+)\] ', meio)
        for i in range(1, len(partes), 2):
            rotulo, _, corpo = partes[i + 1].partition('\n')
            fontes.append(dict(n=int(partes[i]), rotulo=rotulo.strip(), texto=corpo.strip()))
    resposta = texto[m_resposta + len('\n\nRESPOSTA A AVALIAR:\n'):]
    return dict(pergunta=pergunta.strip(), acao=acao.strip(), fontes=fontes, referencia=referencia, resposta=resposta)


def cobertura(afirmacao, texto_fonte):
    alvo = palavras(afirmacao)
    return len(alvo & palavras(texto_fonte)) / len(alvo) if alvo else 0.0


def melhor_trecho(afirmacao, texto_fonte, limite=500):
    """Frase (ou parágrafo curto) da fonte com mais palavras em comum com a afirmação."""
    alvo = palavras(afirmacao)
    pedacos = [p.strip() for p in re.split(r'(?<=[.;:])\s+|\n+', texto_fonte or '') if len(p.strip()) > 15]
    if not pedacos or not alvo:
        return ''
    melhor = max(pedacos, key=lambda p: len(alvo & palavras(p)))
    return melhor[:limite]


def numeros_fonte(valor):
    """Fonte citada pelo juiz como número, texto ('2', 'Fonte 2', '2 e 4') ou lista; devolve os números."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return [n for v in valor for n in numeros_fonte(v)]
    return [int(n) for n in re.findall(r'\d+', str(valor))]


def checar_afirmacao(afirmacao, fontes):
    """Indícios sobre uma afirmação que o juiz não considerou apoiada.

    sinal:
      referencia_ausente  cita artigo, súmula ou número que não aparece em fonte nenhuma (juiz provavelmente certo)
      pouco_apoio         cobertura baixa em todas as fontes (juiz provavelmente certo)
      apoio_textual       cobertura alta e todas as referências presentes (possível falso alarme do juiz)
      inconclusivo        nem um caso nem outro, ou afirmação `contradita` (precisa de leitura)
    """
    texto = afirmacao.get('texto') or ''
    por_n = {f['n']: f for f in fontes}
    completo = {f['n']: f'{f["rotulo"]}\n{f["texto"]}' for f in fontes}
    refs = referencias(texto)
    ausentes = sorted(_ausentes(refs, referencias('\n'.join(completo.values()))))
    coberturas = {n: cobertura(texto, t) for n, t in completo.items()}
    n_melhor = max(coberturas, key=coberturas.get) if coberturas else None
    cob_melhor = coberturas.get(n_melhor, 0.0)
    citadas = [n for n in numeros_fonte(afirmacao.get('fonte')) if n in por_n]   # o juiz às vezes cita várias
    n_citada = max(citadas, key=coberturas.get) if citadas else None
    cob_citada = round(coberturas[n_citada], 2) if n_citada else None
    # a fonte que melhor sustenta precisa ter, ela mesma, todos os números e referências da afirmação
    n_apoio = n_citada if n_citada and coberturas[n_citada] >= LIMIAR_APOIO else n_melhor
    fora_da_fonte = sorted(_ausentes(refs, referencias(completo[n_apoio]))) if n_apoio else sorted(refs)
    if ausentes:
        sinal = 'referencia_ausente'
    elif cob_melhor < LIMIAR_POUCO:
        sinal = 'pouco_apoio'
    elif (coberturas.get(n_apoio, 0) >= LIMIAR_APOIO and not fora_da_fonte and len(palavras(texto)) >= 5
          and afirmacao.get('suporte') != 'contradita'):
        sinal = 'apoio_textual'
    else:
        sinal = 'inconclusivo'
    return dict(sinal=sinal, referencias_ausentes=', '.join(ausentes),
                referencias_fora_da_fonte=', '.join(r for r in fora_da_fonte if r not in ausentes),
                cobertura_citada=cob_citada, cobertura_melhor=round(cob_melhor, 2), fonte_melhor=n_melhor,
                fonte_trecho=n_apoio, trecho=melhor_trecho(texto, por_n[n_apoio]['texto']) if n_apoio else '')


def _ausentes(refs_afirmacao, refs_fonte):
    """Referências da afirmação que não estão na fonte. O número de uma lei vale se aparecer em qualquer forma
    (o rótulo da fonte traz só o nome do arquivo, como l8213.md)."""
    faltam = set()
    for r in refs_afirmacao - refs_fonte:
        tipo, numero = r.split(' ')
        if tipo == 'lei' and f'n {numero}' in refs_fonte:
            continue
        faltam.add(r)
    # um número que só aparece dentro de uma referência tipada já é contado nela
    tipados = {r.split(' ')[1] for r in faltam if not r.startswith('n ')}
    return {r for r in faltam if not (r.startswith('n ') and r.split(' ')[1] in tipados)}


NAO_APOIADAS = ('parcial', 'sem_apoio', 'contradita')


def triar(julgamento, fontes):
    """Motivos da reprovação e triagem da resposta a partir das checagens das afirmações.

    triagem:
      revisar_notas               correção ou comportamento abaixo de 2, ou o próprio modelo reprovou:
                                  a checagem não avalia isso, a pessoa precisa ler
      provavel_reprovacao_correta alguma afirmação com referência ausente ou pouco apoio
      provavel_falso_alarme       todas as afirmações não apoiadas têm apoio textual nas fontes
      inconclusiva                demais casos
    """
    motivos = []
    if julgamento.get('veredito') == 'reprovada':
        motivos.append('o modelo reprovou')
    for criterio in ('fidelidade', 'correcao', 'comportamento'):
        nota = julgamento.get(criterio)
        if isinstance(nota, (int, float)) and nota < 2:
            motivos.append(f'{criterio} = {nota:g}')
    afirmacoes = [a for a in julgamento.get('afirmacoes') or [] if a.get('suporte') in NAO_APOIADAS]
    contagem = {s: sum(a.get('suporte') == s for a in afirmacoes) for s in NAO_APOIADAS}
    motivos += [f'{n} afirmação(ões) {s}' for s, n in contagem.items() if n]
    checagens = [checar_afirmacao(a, fontes) for a in afirmacoes]
    sinais = {c['sinal'] for c in checagens}
    notas_fora = [c for c in ('correcao', 'comportamento')
                  if isinstance(julgamento.get(c), (int, float)) and julgamento[c] < 2]
    if notas_fora or julgamento.get('veredito') == 'reprovada':
        triagem = 'revisar_notas'
    elif sinais & {'referencia_ausente', 'pouco_apoio'}:
        triagem = 'provavel_reprovacao_correta'
    elif checagens and sinais == {'apoio_textual'}:
        triagem = 'provavel_falso_alarme'
    else:
        triagem = 'inconclusiva'
    return dict(triagem=triagem, motivos='; '.join(motivos), afirmacoes=afirmacoes, checagens=checagens)
