"""Chunking da base de precedentes: um trecho por enunciado ou por item, com cabeçalho próprio.

Regras (decididas na EDA, notebook 02):
- só registros buscáveis viram trechos; cancelados, superados e em quarentena ficam fora do índice;
- súmula ou OJ com itens (I, II...): um trecho por item; sem itens: um trecho com o enunciado inteiro;
- tema repetitivo: um trecho com "Questão jurídica: ... Tese: ...";
- todo trecho começa com um cabeçalho "[Súmula 338 do TST — TÍTULO — item I]", para que o trecho se explique sozinho
  na busca e no reranker;
- limite de LIMITE_TOKENS (tokenizador do BGE-M3, cabeçalho incluído). O reranker lê 256 tokens por par
  pergunta–trecho; com ~30 tokens de pergunta, um trecho de até 220 tokens é lido inteiro. Texto maior é dividido
  por frases, repetindo o cabeçalho com "parte k de n".
A unidade de entrega continua sendo o registro inteiro (a busca acha o item; o modelo recebe o enunciado completo).
"""
import hashlib
import json
import re

LIMITE_TOKENS = 220
FRASE = re.compile(r'(?<=[.;:])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ"“(]|\d+[.)]\s|[a-z]\)\s)')


def _sha(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def cabecalho(registro, item=None):
    partes = [registro['nome_citacao'], registro['titulo']]
    if item:
        partes.append(f'item {item}')
    return '[' + ' — '.join(p for p in partes if p) + ']'


def preambulo(registro):
    """Texto antes do item I (caput que introduz ou contextualiza os itens), ou ''."""
    from src.precedentes.estruturacao import ITEM
    m = ITEM.search(registro['texto_busca'])
    return registro['texto_busca'][:m.start()].strip() if m else ''


def por_item(registro):
    return registro['tipo'] != 'tema_repetitivo' and len(registro.get('itens') or []) >= 2


def corpos(registro, sem_origem):
    """[(item, corpo)] do registro: um por item, ou um só com o texto de busca. Quando há caput antes dos itens
    (ex.: OJ 225 da SBDI-1, "Celebrado contrato de concessão...: I - ..."), ele é repetido no início de cada item,
    porque o item sozinho perde o sentido."""
    if por_item(registro):
        cab = preambulo(registro)
        return [(i['item'], f"{cab} {sem_origem(i['texto'])}".strip()) for i in registro['itens']]
    return [(None, registro['texto_busca'])]


def dividir(cab, corpo, contar, limite=LIMITE_TOKENS):
    """Divide o corpo por frases para que cabeçalho + parte caibam no limite. Uma frase maior que o limite
    fica inteira numa parte (registrada como acima do limite)."""
    if contar(f'{cab}\n{corpo}') <= limite:
        return [corpo]
    frases, partes, atual = FRASE.split(corpo), [], ''
    for frase in frases:
        candidato = f'{atual} {frase}'.strip()
        if atual and contar(f'{cab} (parte 99 de 99)\n{candidato}') > limite:
            partes.append(atual)
            atual = frase
        else:
            atual = candidato
    if atual:
        partes.append(atual)
    return partes


def gerar_trechos(registros, contar, sem_origem, limite=LIMITE_TOKENS):
    trechos = []
    for r in registros:
        if not r['buscavel']:
            continue
        for item, corpo in corpos(r, sem_origem):
            cab = cabecalho(r, item)
            partes = dividir(cab, corpo, contar, limite)
            for k, parte in enumerate(partes, 1):
                cab_k = cab if len(partes) == 1 else f'{cab[:-1]} (parte {k} de {len(partes)})]'
                texto = f'{cab_k}\n{parte}'
                trechos.append(dict(
                    chunk_id=_sha(json.dumps([r['id'], item, k, _sha(texto)])), registro_id=r['id'],
                    tipo=r['tipo'], serie=r['serie'], numero=r['numero'], nome_citacao=r['nome_citacao'],
                    item=item, parte=k, partes=len(partes), texto=texto, tokens=contar(texto),
                    situacao=r['situacao'], alerta_vigencia=r.get('alerta_vigencia'),
                    fonte=dict(sigla=r['fonte']['sigla'], sha256=r['fonte']['sha256'],
                               data_referencia=r['fonte'].get('data_referencia')),
                    texto_sha256=_sha(texto)))
    return trechos


def _so_letras(texto):
    return re.sub(r'\W+', '', texto).lower()


def validar(registros, trechos, limite=LIMITE_TOKENS):
    """Problemas: registro buscável sem trecho, registro não buscável com trecho, id repetido, texto perdido ou
    duplicado na divisão (a concatenação dos corpos tem de reproduzir o texto de busca), trecho acima do limite."""
    problemas, avisos = [], []
    por_registro = {}
    for t in trechos:
        por_registro.setdefault(t['registro_id'], []).append(t)
    buscaveis = {r['id'] for r in registros if r['buscavel']}
    problemas += [f'{i}: buscável sem trecho' for i in sorted(buscaveis - set(por_registro))]
    problemas += [f'{i}: não buscável com trecho' for i in sorted(set(por_registro) - buscaveis)]
    ids = [t['chunk_id'] for t in trechos]
    if len(ids) != len(set(ids)):
        problemas.append('chunk_id repetido')
    from src.precedentes.estruturacao import sem_origem
    por_id = {r['id']: r for r in registros}
    for rid, lista in por_registro.items():
        corpo = ''.join(t['texto'].split('\n', 1)[1] for t in lista)
        r = por_id[rid]
        if por_item(r):
            # cada pedaço (caput e cada item) tem de aparecer nos trechos; o caput aparece repetido em cada item
            pedacos = [preambulo(r)] + [sem_origem(i['texto']) for i in r['itens']]
            if not all(_so_letras(p) in _so_letras(corpo) for p in pedacos if p):
                problemas.append(f'{rid}: algum item ou o caput não aparece nos trechos')
        elif _so_letras(corpo) != _so_letras(r['texto_busca']):
            problemas.append(f'{rid}: texto dos trechos não reproduz o texto de busca')
    avisos += [f"{t['registro_id']} parte {t['parte']}: {t['tokens']} tokens (frase única acima do limite)"
               for t in trechos if t['tokens'] > limite]
    return problemas, avisos


def gravar_jsonl(trechos, caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open('w', encoding='utf-8', newline='\n') as f:
        for t in trechos:
            f.write(json.dumps(t, ensure_ascii=False) + '\n')
    return hashlib.sha256(caminho.read_bytes()).hexdigest()
