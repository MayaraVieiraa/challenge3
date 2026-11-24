"""Separa os verbetes brutos dos PDFs: um registro por súmula, OJ ou tema, ainda sem limpeza.

Coletânea do TRT-3 (2024), 2ª parte (TST), p. 65-256: cada verbete começa numa linha com o código
oficial (SUM-338, OJ-SDI1-394, ...). As notas remissivas ao TRT-3 (linhas com "•") ficam no bloco bruto e
são separadas na estruturação. A parte de IRR da coletânea (p. 258-266) não é usada: o índice de 2026 a substitui.

Índice de IRR (19/11/2026), parte temática, p. 12-121: cada tema começa num título em negrito
"IRR 128 – ..."; a cor do título indica a situação (legenda da p. 2). O mesmo tema aparece em mais de um
assunto e na seção de suspensões; a deduplicação é feita na estruturação.
"""
import re
from pathlib import Path

PAGINAS_TST_TRT3 = (65, 256)
PAGINAS_TEMAS_IRR = (12, 121)

SERIES = {  # código na coletânea -> (tipo, órgão)
    'SUM': ('sumula', 'Tribunal Pleno'),
    'OJ-TP/OE': ('orientacao_jurisprudencial', 'Tribunal Pleno/Órgão Especial'),
    'OJ-SDI1': ('orientacao_jurisprudencial', 'SBDI-1'),
    'OJ-SDI1T': ('orientacao_jurisprudencial', 'SBDI-1 (transitória)'),
    'OJ-SDI2': ('orientacao_jurisprudencial', 'SBDI-2'),
    'OJ-SDC': ('orientacao_jurisprudencial', 'SDC'),
}
INICIO_VERBETE = re.compile(r'^\s*(SUM|OJ-TP/OE|OJ-SDI1T|OJ-SDI1|OJ-SDI2|OJ-SDC)-\s?(\d+)(?!\d)\s*(.*)$')

CORES_IRR = {'0070c0': 'azul', 'ffc000': 'mostarda', 'ffcc00': 'mostarda', 'ff0000': 'vermelho'}
INICIO_TEMA = re.compile(r'^\s*(IRR|IAC|IRDR)\s*(?:n?º?\s*)?(\d+)\s*[–-]\s*(.*)$')
SO_SIGLA = re.compile(r'^\s*(IRR|IAC|IRDR)\s*$')


CABECALHO_SECAO = re.compile(r'^\s*(SÚMULAS - TST|ORIENTAÇÕES JURISPRUDENCIAIS D.{0,60}TST)\s*$')


def _linhas_trt3(pagina):
    """Linhas da página sem o cabeçalho (número, título da seção e a palavra SUMÁRIO)."""
    linhas = pagina.get_text().splitlines()
    for i, l in enumerate(linhas[:10]):
        if l.strip() == 'SUMÁRIO':
            return [l for l in linhas[i + 1:] if not CABECALHO_SECAO.match(l)]
    return []  # página de abertura de seção (só o nome da seção), sem verbetes


def _titulo_em_maiusculas(resto):
    """O título oficial vem em maiúsculas; um código seguido de texto em minúsculas é redação antiga no histórico."""
    letras = [c for c in resto.split('(')[0][:25] if c.isalpha()]
    return not letras or sum(c.isupper() for c in letras) >= 0.8 * len(letras)


def verbetes_tst_trt3(caminho, paginas=PAGINAS_TST_TRT3):
    """Blocos brutos das súmulas e OJs do TST na coletânea do TRT-3."""
    import pymupdf

    doc = pymupdf.open(caminho)
    registros, atual = [], None
    for n in range(paginas[0], paginas[1] + 1):
        for linha in _linhas_trt3(doc[n - 1]):
            m = INICIO_VERBETE.match(linha)
            if m and _titulo_em_maiusculas(m.group(3)):
                atual = dict(serie=m.group(1), numero=int(m.group(2)), codigo=f'{m.group(1)}-{m.group(2)}',
                             tipo=SERIES[m.group(1)][0], orgao=SERIES[m.group(1)][1],
                             pagina_inicial=n, pagina_final=n, linhas=[linha.strip()])
                registros.append(atual)
            elif atual is not None:
                atual['linhas'].append(linha.rstrip())
                atual['pagina_final'] = n
    doc.close()
    for r in registros:
        r['texto_bruto'] = '\n'.join(r.pop('linhas')).strip()
    return registros


def temas_irr(caminho, paginas=PAGINAS_TEMAS_IRR):
    """Blocos brutos dos temas do índice de IRR, com a cor do título e o assunto em que aparecem."""
    import pymupdf

    doc = pymupdf.open(caminho)
    registros, atual, assunto, sigla_pendente, no_titulo, ultimo_foi_assunto = [], None, None, None, False, False
    for n in range(paginas[0], paginas[1] + 1):
        linhas = _linhas_por_posicao(doc[n - 1])
        if linhas and linhas[0][0].isdigit():
            linhas = linhas[1:]  # número da página
        for texto, cor, negrito in linhas:
            if sigla_pendente and re.match(r'^\d+\s*[–-]', texto):  # "IRR" numa linha e "299 – ..." na seguinte
                texto, sigla_pendente = f'{sigla_pendente} {texto}', None
            m = INICIO_TEMA.match(texto)
            if m and not _titulo_em_maiusculas(m.group(3)):
                m = None
            if negrito and SO_SIGLA.match(texto):
                sigla_pendente = texto.strip()
                continue
            if m:
                atual = dict(subtipo=m.group(1), numero=int(m.group(2)), codigo=f'{m.group(1)}-{int(m.group(2))}',
                             tipo='tema_repetitivo', cor_titulo=cor, situacao_cor=CORES_IRR.get(cor, 'sem_cor'),
                             assunto=assunto, pagina_inicial=n, pagina_final=n, linhas=[texto])
                registros.append(atual)
                no_titulo, ultimo_foi_assunto = True, False
                continue
            eh_assunto = (negrito and cor == '000000' and texto.upper() == texto and len(texto) < 90
                          and sum(c.isalpha() for c in texto) >= 3)
            if atual is None or (eh_assunto and not no_titulo and not texto.startswith(('Questão', 'Tese', 'Referência'))):
                if eh_assunto:  # título de assunto entre temas (ex.: "ADICIONAL DE INSALUBRIDADE"), às vezes em 2 linhas
                    assunto = f'{assunto} {texto}' if ultimo_foi_assunto else texto
                    ultimo_foi_assunto = True
                continue
            ultimo_foi_assunto = False
            rotulo = re.match(r'^(Questão jurídica|Tese|Referência legislativa e jurisprudência)\s*:', texto)
            if rotulo:
                no_titulo = False
            if cor == 'ffffff':
                texto = f'[AVISO] {texto}'  # faixa colorida, ex.: "IRR com determinação de suspensão no TST"
            atual['linhas'].append(texto)
            atual['pagina_final'] = n
    doc.close()
    for r in registros:
        r['texto_bruto'] = '\n'.join(r.pop('linhas')).strip()
    return registros


def _linhas_por_posicao(pagina, tolerancia=3):
    """Linhas da página na ordem de leitura, juntando pedaços na mesma altura (títulos justificados vêm
    palavra a palavra, às vezes em blocos diferentes). Cada linha: (texto, cor do 1º trecho, negrito)."""
    pedacos = []
    for bloco in pagina.get_text('dict')['blocks']:
        for l in bloco.get('lines', []):
            spans = [s for s in l['spans'] if s['text'].strip()]
            if spans:
                pedacos.append((l['bbox'][1], l['bbox'][0], ' '.join(s['text'].strip() for s in spans),
                                f"{spans[0]['color']:06x}", bool(spans[0]['flags'] & 16)))
    pedacos.sort(key=lambda p: (round(p[0]), p[1]))
    linhas = []
    for y, x, texto, cor, negrito in pedacos:
        if linhas and abs(y - linhas[-1][0]) < tolerancia:
            linhas[-1][1].append((x, texto))
        else:
            linhas.append([y, [(x, texto)], cor, negrito])
    return [(re.sub(r'\s+', ' ', ' '.join(t for _, t in sorted(partes))).strip(), cor, negrito)
            for _, partes, cor, negrito in linhas]


ITEM_NOTICIA = re.compile(
    r'^(Súmula|OJ|PN)\s+(\d+)\s*(?:\((Item\s+[IVX]+)\))?\s*(?:\((SDI-1|SDC|SDI-2)\))?\s*[–-]\s*(.+)$', re.M)
SERIE_NOTICIA = {('Súmula', None): 'SUM', ('OJ', 'SDI-1'): 'OJ-SDI1', ('OJ', 'SDI-2'): 'OJ-SDI2',
                 ('OJ', 'SDC'): 'OJ-SDC', ('PN', None): 'PN'}


def cancelamentos_noticia(caminho):
    """Enunciados citados na notícia de cancelamento (fonte não oficial)."""
    import pymupdf

    doc = pymupdf.open(caminho)
    texto = '\n'.join(p.get_text() for p in doc)
    doc.close()
    itens, achados = [], list(ITEM_NOTICIA.finditer(texto))
    for i, m in enumerate(achados):
        serie = SERIE_NOTICIA.get((m.group(1), m.group(4)))
        bloco = texto[m.end():achados[i + 1].start() if i + 1 < len(achados) else len(texto)]
        parcial = re.search(r'Trechos cancelados:\s*([^\n]+)', bloco)
        itens.append(dict(serie=serie, numero=int(m.group(2)), codigo=f'{serie}-{m.group(2)}',
                          titulo_noticia=m.group(5).strip(),
                          alcance=(m.group(3) or (parcial.group(1).strip() if parcial else 'integral'))))
    return itens


def texto_paginas(caminho, paginas):
    import pymupdf

    doc = pymupdf.open(Path(caminho))
    try:
        return {n: doc[n - 1].get_text() for n in paginas}
    finally:
        doc.close()
