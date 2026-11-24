"""Avaliação da recuperação na base de precedentes (notebook 06).

Gabaritos:
  A (especialista): perguntas reais da amostra do advogado revisor em que ele apontou o precedente do TST decisivo.
  B (prata, automático): trechos de acórdãos da base de jurisprudência que citam exatamente um precedente do TST.
    A citação é mascarada ("Súmula nº 338 do TST" -> "[precedente]") e o resto do trecho vira a pergunta: a base
    acha o precedente que o tribunal aplicou só pela descrição do caso? Trechos que transcrevem o texto do
    precedente são descartados (a busca só estaria copiando), e cada precedente entra no máximo MAX_POR_PRECEDENTE vezes.
Buscas comparadas: semântica (BGE-M3), por palavras (texto normalizado, sem stopwords, IDF), híbrida (RRF das duas)
e híbrida + reranker (bge-reranker-v2-m3, como na busca integrada). Métricas no nível do registro (o precedente).
"""
import hashlib
import re

RRF_K = 60
MAX_POR_PRECEDENTE = 3
JANELA = 250  # caracteres de cada lado da citação usados como pergunta (perto do tamanho de uma pergunta real;
              # o reranker lê 256 tokens por par pergunta–trecho)

# Citação de precedente do TST no texto de um acórdão -> (série, número, item)
CITACAO = re.compile(
    r'(?P<tipo>S[úu]mula|Orienta[çc][ãa]o Jurisprudencial|\bOJ\b)\s*(?:n[º°o.]*\s*)?(?P<num>\d{1,3})'
    r'(?:\s*,?\s*(?:item|inciso)?\s*(?P<item>[IVX]{1,5})\b)?'
    r'(?P<resto>\s*/\s*TST\b|[^.;\n]{0,45}?\b(?:do\s+(?:c\.\s*|col\.\s*|colendo\s+)?TST|da\s+(?:SBDI|SDI|SDC)[-\s]?(?P<sec>[12I]+)?(?:\s*/\s*TST|\s+do\s+TST)?))',
    re.I)


def registro_da_citacao(m):
    tipo, num = m.group('tipo').lower(), int(m.group('num'))
    if tipo.startswith('s'):
        return f'TST-SUM-{num}'
    resto = (m.group(0) or '').upper().replace(' ', '')
    if 'SDC' in resto:
        return f'TST-OJ-SDC-{num}'
    if re.search(r'S?B?DI-?(2|II)', resto):
        return f'TST-OJ-SDI2-{num}'
    if 'TRANSIT' in resto:
        return f'TST-OJ-SDI1T-{num}'
    return f'TST-OJ-SDI1-{num}'


def _palavras(texto):
    return re.findall(r'\w+', texto.lower())


def transcreve(texto, enunciado, n=10):
    """True se o trecho contém alguma sequência de n palavras seguidas do enunciado (transcrição)."""
    p = _palavras(enunciado)
    alvo = ' ' + ' '.join(_palavras(texto)) + ' '
    return any(' ' + ' '.join(p[i:i + n]) + ' ' in alvo for i in range(max(0, len(p) - n + 1)))


def gabarito_prata(linhas, registros, limite=300):
    """linhas: [(chunk_id, registro_id_acordao, texto)] já em ordem determinística. Devolve itens com a pergunta
    mascarada e o precedente esperado; o texto fica só em memória (o CSV versionado leva apenas identificadores)."""
    por_id = {r['id']: r for r in registros}
    usados, itens, descartes = {}, [], dict(varios_precedentes=0, nao_buscavel=0, transcricao=0, curto=0, excesso=0)
    for chunk_id, acordao, texto in linhas:
        citacoes = list(CITACAO.finditer(texto))
        ids = {registro_da_citacao(m) for m in citacoes}
        if len(ids) != 1:
            descartes['varios_precedentes'] += bool(ids)
            continue
        esperado = ids.pop()
        r = por_id.get(esperado)
        if not r or not r['buscavel']:
            descartes['nao_buscavel'] += 1
            continue
        if usados.get(esperado, 0) >= MAX_POR_PRECEDENTE:
            descartes['excesso'] += 1
            continue
        m = citacoes[0]
        janela = texto[max(0, m.start() - JANELA):m.end() + JANELA]
        pergunta = CITACAO.sub('[precedente]', janela)
        pergunta = re.sub(rf'\b(?:s[úu]mula|oj|orienta[çc][ãa]o jurisprudencial)\s*(?:n[º°o.]*\s*)?{r["numero"]}\b', '[precedente]',
                          pergunta, flags=re.I)
        if len(pergunta) < 200:
            descartes['curto'] += 1
            continue
        if transcreve(pergunta, r['texto_busca']):
            descartes['transcricao'] += 1
            continue
        usados[esperado] = usados.get(esperado, 0) + 1
        item = (m.group('item') or '').upper() or None
        itens.append(dict(id=f'prata-{hashlib.sha256(chunk_id.encode()).hexdigest()[:12]}', chunk_origem=chunk_id,
                          acordao=acordao, esperado=esperado, item=item, tipo=r['tipo'], pergunta=pergunta))
        if len(itens) >= limite:
            break
    return itens, descartes


def rrf(listas, k=RRF_K):
    escores = {}
    for lista in listas:
        for pos, ident in enumerate(lista, 1):
            escores[ident] = escores.get(ident, 0) + 1 / (k + pos)
    return sorted(escores, key=lambda i: (-escores[i], i))


def ordem_registros(chunks, chunk_para_registro):
    return list(dict.fromkeys(chunk_para_registro[c] for c in chunks))


def metricas(posicoes):
    """posicoes: lista com a posição (1..) do esperado ou None. Hit@1/3/5 e MRR@10."""
    n = len(posicoes)
    hit = lambda k: sum(1 for p in posicoes if p and p <= k) / n
    mrr = sum(1 / p for p in posicoes if p and p <= 10) / n
    return {'Hit@1': round(hit(1), 3), 'Hit@3': round(hit(3), 3), 'Hit@5': round(hit(5), 3), 'MRR@10': round(mrr, 3), 'n': n}
