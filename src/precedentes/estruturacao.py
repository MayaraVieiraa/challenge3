"""Limpeza e estruturação dos verbetes brutos: um registro por súmula, OJ ou tema, gravado num JSONL único.

Campos de cada registro (ver ESQUEMA): identificação (id, tipo, órgão, número, nome de citação), conteúdo
(título, texto oficial, itens, questão jurídica, tese, referências), vigência (situação oficial, detalhe,
alerta da notícia, buscável) e origem (arquivo, hash, data de referência, páginas).

Regras de vigência:
- súmulas e OJs: situação oficial da coletânea (até 28/06/2024). "cancelada" quando o parêntese de situação diz
  cancelada/cancelamento (exceto cancelamento só de item) ou quando o verbete não tem enunciado (convertido em
  outro). A notícia de cancelamento é fonte não oficial: vira alerta_vigencia e não muda a situação.
- temas: pela tese ("Ainda não fixada" = afetado sem tese; "Superada" = tese superada); a cor do título é
  conferida na EDA.
- buscavel = vigente, tese fixada ou afetado sem tese. Cancelados e superados ficam registrados, fora da busca.
  Cancelamento integral noticiado: continua "vigente" (situação oficial), mas fica fora da busca (quarentena).
"""
import hashlib
import json
import re
from collections import defaultdict

ESQUEMA = ['id', 'tipo', 'orgao', 'serie', 'numero', 'nome_citacao', 'titulo', 'texto', 'texto_busca', 'itens',
           'questao_juridica', 'tese', 'referencias', 'avisos', 'assuntos', 'historico', 'remissoes_trt3',
           'situacao', 'situacao_detalhe', 'alerta_vigencia', 'buscavel', 'fonte', 'texto_sha256']

NOME_ORGAO = {'SUM': None, 'OJ-TP/OE': 'do Tribunal Pleno/Órgão Especial', 'OJ-SDI1': 'da SBDI-1',
              'OJ-SDI1T': 'da SBDI-1 (transitória)', 'OJ-SDI2': 'da SBDI-2', 'OJ-SDC': 'da SDC'}
DATA = r'\d{1,2}\.\d{1,2}\.\d{4}'
REF_PUBLICACAO = re.compile(
    rf'^\s*[-–,]?\s*(?:Res\.|RA\b|DJ\b|DEJT|DO-GB|[Ii]nserid|[Rr]epublicad|divulgad|e\s+\d).{{0,160}}?{DATA}\)?')
CORTE_TITULO = re.compile(r'\s[-–]\s*(?:Res\.|RA\s|DJ\b|DEJT)')
PUBLICACAO_PARENTESE = re.compile(r'^\s*(?:DJ|DEJT|RA|Res\.|[Ii]nserid).{0,120}\d{4}\s*$')
HISTORICO = re.compile(r'\bHistórico\s*:?(?=\s|$)')
ITEM = re.compile(r'(?:^|(?<=[.;:)]\s))([IVX]{1,5})\s*[-–]\s+')
ORIGEM_EX = re.compile(r'\s*\((?:(?:primeira|segunda) parte|parte final)?\s*[-–]?\s*(?:ex|Ex)-[^()]*(?:\([^()]*\)[^()]*)*\)')


def sem_origem(texto):
    """Texto de busca: retira as origens "(ex-Súmula nº ...)" e "(primeira parte - ex-OJ ...)" e o ponto duplicado."""
    return re.sub(r'\.\s*\.(?=\s|$)', '.', _plano(ORIGEM_EX.sub('', texto)))


def _plano(texto):
    """Junta as linhas: hifenização no fim de linha e quebras viram texto corrido."""
    texto = re.sub(r'(\w)-\n(?=[a-zà-ú])', r'\1', texto)
    texto = re.sub(r'-\n', '-', texto)
    return re.sub(r'\s+', ' ', texto).strip()


def _sha(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def _parentese(texto, inicio):
    nivel = 0
    for i in range(inicio, len(texto)):
        nivel += {'(': 1, ')': -1}.get(texto[i], 0)
        if nivel == 0:
            return texto[inicio + 1:i], i + 1
    return texto[inicio + 1:], len(texto)


def _maiusculas(texto):
    letras = [c for c in texto if c.isalpha()]
    return bool(letras) and sum(c.isupper() for c in letras) >= 0.8 * len(letras)


def _cabecalho(corpo):
    """Separa título (maiúsculas, pode ter parênteses como "(ART. 612 DA CLT)"), parêntese de situação
    (primeiro parêntese em minúsculas) e o resto (publicação + enunciado)."""
    i = 0
    while True:
        abre = corpo.find('(', i)
        corte = CORTE_TITULO.search(corpo, i)
        if corte and (abre < 0 or corte.start() < abre):
            return corpo[:corte.start()].strip(' .-–'), corpo[corte.start():], None
        if abre < 0:
            return corpo.strip(' .-–'), '', None
        conteudo, fim = _parentese(corpo, abre)
        if PUBLICACAO_PARENTESE.match(conteudo):  # "(DJ 09.12.2003)": só a publicação, sem situação
            return corpo[:abre].strip(' .-–'), corpo[fim:], None
        if _maiusculas(conteudo):
            i = fim  # parêntese do próprio título
            continue
        return corpo[:abre].strip(' .-–'), corpo[fim:], conteudo


def _itens(texto):
    marcas = list(ITEM.finditer(texto))
    if len(marcas) < 2 or marcas[0].group(1) != 'I':
        return []
    return [dict(item=m.group(1), texto=texto[m.end():(marcas[i + 1].start() if i + 1 < len(marcas) else len(texto))].strip())
            for i, m in enumerate(marcas)]


def _situacao_verbete(detalhe, enunciado):
    d = (detalhe or '').lower()
    parcial = re.search(r'cancelad[oa]s? (?:o|os) ite|cancelamento d[oe]s? ite', d)
    if ('cancelad' in d or 'cancelamento' in d) and not parcial:
        return 'cancelada'
    if not enunciado:
        return 'cancelada'  # sem enunciado: convertido ou incorporado em outro verbete
    return 'vigente'


def estruturar_verbete(bruto, fonte, alertas):
    linhas = bruto['texto_bruto'].split('\n')
    remissoes = [_plano(l.lstrip('• ')) for l in linhas if l.strip().startswith('•')]
    texto = '\n'.join(l for l in linhas if not l.strip().startswith('•'))
    corpo, historico = (HISTORICO.split(texto, maxsplit=1) + [''])[:2]
    corpo = _plano(corpo)
    corpo = re.sub(rf"^{re.escape(bruto['serie'])}-\s?{bruto['numero']}\s*", '', corpo)
    titulo, resto, detalhe = _cabecalho(corpo)
    while (m := REF_PUBLICACAO.match(resto)):
        resto = resto[m.end():]
    enunciado = resto.strip(' .-–') if resto.strip(' .-–') else ''
    if enunciado and not enunciado.endswith(('.', ')', ';', '"', '”')):
        enunciado = resto.strip(' -–')
    if detalhe and re.match(r'^\s*(DJ|DEJT|[Ii]nserid|Res\.)', detalhe):
        publicacao, detalhe = detalhe, None  # parêntese só com a publicação, sem situação
    situacao = _situacao_verbete(detalhe, enunciado)
    numero, serie = bruto['numero'], bruto['serie']
    nome = f'Súmula {numero} do TST' if serie == 'SUM' else f'OJ {numero} {NOME_ORGAO[serie]} do TST'
    alerta = alertas.get(bruto['codigo'])
    return dict(
        id=f"TST-{serie.replace('/', '')}-{numero}", tipo=bruto['tipo'], orgao=bruto['orgao'], serie=serie,
        numero=numero, nome_citacao=nome, titulo=titulo, texto=enunciado,
        texto_busca=sem_origem(enunciado), itens=_itens(enunciado), questao_juridica=None,
        tese=None, referencias=None, avisos=[], assuntos=[], historico=_plano(historico) or None,
        remissoes_trt3=remissoes, situacao=situacao, situacao_detalhe=detalhe,
        alerta_vigencia=(f"cancelamento noticiado (fonte não oficial; alcance: {alerta['alcance']})" if alerta else None),
        # cancelamento integral noticiado: fora da busca até conferir a resolução oficial (quarentena reversível)
        buscavel=situacao == 'vigente' and bool(enunciado) and not (alerta and alerta['alcance'] == 'integral'),
        fonte=dict(fonte, paginas=[bruto['pagina_inicial'], bruto['pagina_final']]), texto_sha256=_sha(enunciado))


ROTULOS_TEMA = re.compile(r'^(Questão jurídica|Tese|Referência legislativa e jurisprudência)\s*:\s*', re.M)


def _campos_tema(texto_bruto):
    linhas = texto_bruto.split('\n')
    avisos = [l.replace('[AVISO]', '').strip() for l in linhas if l.startswith('[AVISO]')]
    texto = '\n'.join(l for l in linhas if not l.startswith('[AVISO]'))
    partes = ROTULOS_TEMA.split(texto)
    titulo, campos = partes[0], dict(zip(partes[1::2], partes[2::2]))
    titulo = re.sub(r'^\s*(IRR|IAC|IRDR)\s*(?:n?º?\s*)?\d+\s*[–-]\s*', '', _plano(titulo)).strip(' .')
    campos = {k: _plano(v) for k, v in campos.items()}
    if campos.get('Tese', '').startswith('Ainda não fixada'):
        campos['Tese'] = 'Ainda não fixada.'  # às vezes o número da página seguinte cola no fim
    return titulo, campos, avisos


def _situacao_tema(tese):
    t = (tese or '').lower()
    if not t or t.startswith('ainda não fixada'):
        return 'afetado_sem_tese'
    if t.startswith('superada'):
        return 'tese_superada'
    return 'tese_fixada'


def estruturar_temas(brutos, fonte):
    """Um registro por tema: o mesmo tema aparece em vários assuntos e na seção de suspensões."""
    grupos = defaultdict(list)
    for b in brutos:
        grupos[b['codigo']].append(b)
    registros = []
    for codigo, ocorrencias in grupos.items():
        versoes = []
        for b in ocorrencias:
            titulo, campos, avisos = _campos_tema(b['texto_bruto'])
            versoes.append((b, titulo, campos, avisos))
        # a seção de suspensões traz o tema resumido (às vezes sem tese): prefere a versão com tese, a mais longa
        b, titulo, campos, _ = max(versoes, key=lambda v: ('Tese' in v[2], len(v[0]['texto_bruto'])))
        teses = {re.sub(r'\W+', ' ', v[2]['Tese']).strip().lower() for v in versoes if v[2].get('Tese')}
        tese, questao = campos.get('Tese'), campos.get('Questão jurídica')
        situacao = _situacao_tema(tese)
        sub, numero = b['subtipo'], b['numero']
        texto = ' '.join(x for x in [f'Questão jurídica: {questao}' if questao else None,
                                     f'Tese: {tese}' if tese else None] if x)
        registros.append(dict(
            id=f'TST-{sub}-{numero}', tipo='tema_repetitivo', orgao='TST (Tribunal Pleno / SBDI-1)', serie=sub,
            numero=numero, nome_citacao=(f'Tema {numero} de IRR do TST' if sub == 'IRR' else f'{sub} {numero} do TST'),
            titulo=titulo, texto=texto, texto_busca=texto, itens=[], questao_juridica=questao, tese=tese,
            referencias=campos.get('Referência legislativa e jurisprudência'),
            avisos=sorted({a for v in versoes for a in v[3]}),
            assuntos=sorted({o['assunto'] for o in ocorrencias
                             if o['assunto'] and not o['assunto'].startswith('INCIDENTES COM DETERMINAÇÃO')}),
            historico=None, remissoes_trt3=[],
            situacao=situacao, situacao_detalhe=None if len(teses) <= 1 else 'versões divergentes no índice',
            alerta_vigencia=None, buscavel=situacao in ('tese_fixada', 'afetado_sem_tese') and bool(texto),
            cor_titulo=b['situacao_cor'], ocorrencias=len(ocorrencias),
            fonte=dict(fonte, paginas=sorted({o['pagina_inicial'] for o in ocorrencias})), texto_sha256=_sha(texto)))
    return sorted(registros, key=lambda r: ({'IRR': 0, 'IAC': 1, 'IRDR': 2}[r['serie']], r['numero']))


def validar(registros):
    """Problemas que impedem gravar: id repetido, campo obrigatório vazio, registro buscável sem texto."""
    problemas = []
    ids = [r['id'] for r in registros]
    problemas += [f'id repetido: {i}' for i in sorted({i for i in ids if ids.count(i) > 1})]
    for r in registros:
        for campo in ('id', 'tipo', 'numero', 'nome_citacao', 'situacao', 'fonte'):
            if r.get(campo) in (None, ''):
                problemas.append(f"{r.get('id')}: {campo} vazio")
        if r['buscavel'] and not r['texto_busca']:
            problemas.append(f"{r['id']}: buscável sem texto")
    return problemas


def gravar_jsonl(registros, caminho):
    problemas = validar(registros)
    if problemas:
        raise ValueError(f'{len(problemas)} problemas; nada foi gravado: {problemas[:10]}')
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open('w', encoding='utf-8') as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return _sha(caminho.read_text(encoding='utf-8'))
