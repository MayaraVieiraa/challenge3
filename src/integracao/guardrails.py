"""Guardrails de entrada e de saída do fluxo integrado (determinísticos, sem LLM).

Entrada — classifica a pergunta em uma ação e sinaliza riscos:
  responder               pergunta informativa de Direito do Trabalho brasileiro
  orientar_sem_aconselhar relato de caso concreto pedindo o que fazer: regra geral + encaminhamento
  institucional           pergunta sobre a plataforma (sem fundamentação jurídica)
  consulta_individual     situação do próprio processo, valores ou registros pessoais (não acessíveis)
  fora_escopo             outro ramo do direito ou assunto não jurídico
  outra_jurisdicao        direito de outro país
  Sinais transversais: dados_pessoais (mascarados antes da busca e da LLM) e instrucao_suspeita.

Saída — confere a resposta contra as fontes entregues:
  citacao_inexistente     [Fonte N] fora das fontes entregues
  dispositivo_inconsistente   artigo/parágrafo citado não corresponde à fonte, ou número/percentual
                              afirmado não aparece no dispositivo citado
  afirmacao_sem_fonte     proporção alta de frases jurídicas sem citação
  promessa_resultado      garantia de ganho ou de valor
  dados_pessoais_saida    CPF, e-mail ou telefone na resposta (mascarados)
  resposta_alem_do_escopo resposta jurídica desenvolvida quando a entrada pedia recusa/redirecionamento
  sem_fontes              afirmação jurídica sem nenhuma fonte entregue
  consulta_individual_sem_ressalva  entrada de consulta individual cuja resposta não diz que o sistema
                              não tem acesso ao processo/registros da pessoa
  consulta_individual_pede_dados    entrada de consulta individual cuja resposta pede número do processo,
                              documentos ou dados pessoais
  artigo_sem_fonte        artigo citado na resposta que não está em nenhuma fonte entregue (informativo;
                              compara só o número do artigo, não a norma)
  aviso_legal_ausente     resposta sem o aviso de que não substitui orientação profissional (acrescentado)
Validador v3 (verificar_saida(..., versao='v3'), a partir do diagnóstico do advogado revisor):
  norma_fora_das_fontes   lei, súmula, OJ, tema ou artigo de código (CLT, CF, CPC, CC) citado que não aparece em
                              nenhuma fonte entregue (bloqueante)
  sem_marcacao_fonte      resposta jurídica sem nenhuma marcação [Fonte N] (bloqueante)
  lei_citada_com_decisao  frase que cita norma sustentada só por decisões judiciais (informativo)
  citacao_em_lote         mais de duas fontes numa frase (informativo)
  metadado_interno        status de vigência, caminho ou nome de arquivo das fontes na resposta (informativo)
  abertura_categorica     abre com "sim"/"não" e depois condiciona a resposta (informativo)
  Precedentes do TST (fontes com tipo 'precedentes', notebook 07 da integração; todos informativos):
  precedente_fonte_trocada    súmula, OJ ou tema citado com uma [Fonte N] que não o contém, quando outra fonte
                              de precedente entregue o contém
  tema_sem_tese_como_regra    tema afetado e ainda sem tese citado sem dizer que a questão está pendente
  alerta_vigencia_omitido     precedente com alerta de vigência citado sem avisar que pode ter mudado
  precedente_cancelado        súmula, OJ ou tema cancelado, suspenso ou superado citado sem dizer isso
                              (catálogo versionado em src/integracao/situacao_precedentes.json)
Bloqueantes (reprovam a resposta): ver BLOQUEANTES (v1) e BLOQUEANTES_V3; os demais alertas são informativos.
As regras são heurísticas e auditáveis; não substituem revisão humana nem certificam correção jurídica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

AVISO_LEGAL = ('Esta resposta é informativa e não substitui a orientação de um advogado, da Defensoria Pública '
               'ou do sindicato da categoria.')
BLOQUEANTES = {'citacao_inexistente', 'dispositivo_inconsistente', 'promessa_resultado', 'resposta_alem_do_escopo',
               'sem_fontes', 'consulta_individual_sem_ressalva', 'consulta_individual_pede_dados'}


def _sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower()) if unicodedata.category(c) != 'Mn')


def _rx(*padroes):
    return re.compile('|'.join(padroes), re.IGNORECASE)


# --- dados pessoais -------------------------------------------------------------------------------------------
CPF = re.compile(r'(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)')
CNPJ = re.compile(r'(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
TELEFONE = re.compile(r'(?<!\d)(?:\(?\d{2}\)?\s?)?9?\d{4}-?\d{4}(?!\d)')
PROCESSO_CNJ = re.compile(r'(?<!\d)\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}(?!\d)')


def _digitos(valor):
    return re.sub(r'\D', '', str(valor or ''))


def mascarar(texto, processos_preservados=()):
    """Mascara dados pessoais. `processos_preservados`: números CNJ (só dígitos) das decisões entregues como fonte,
    que são públicas e devem continuar identificáveis na resposta."""
    achados = []
    preservados = {_digitos(p) for p in processos_preservados if p}
    for nome, padrao, marca in (('processo', PROCESSO_CNJ, '[PROCESSO]'), ('cnpj', CNPJ, '[CNPJ]'), ('cpf', CPF, '[CPF]'),
                                ('email', EMAIL, '[EMAIL]'), ('telefone', TELEFONE, '[TELEFONE]')):
        protegidos = []

        def trocar(m):
            if nome == 'processo' and _digitos(m.group(0)) in preservados:
                protegidos.append(m.group(0))
                return f'\x00{len(protegidos) - 1}\x00'
            if nome not in achados:
                achados.append(nome)
            return marca
        texto = padrao.sub(trocar, texto)
        # Números de processo preservados ficam fora das buscas seguintes (o telefone casaria com parte deles).
        if nome == 'processo':
            reservados = protegidos
    texto = re.sub(r'\x00(\d+)\x00', lambda m: reservados[int(m.group(1))], texto)
    return texto, achados


# --- regras de entrada (sobre o texto sem acentos) --------------------------------------------------------------
INJECAO = _rx(r'ignor\w* (as |todas as |suas )?(instruc|regras|orientac)', r'esquec\w* (as |suas )?(instruc|regras)',
              r'(prompt|instrucoes) do sistema', r'system prompt', r'voce agora (e|sera)', r'finja (que|ser)',
              r'modo (desenvolvedor|developer)', r'sem (restricoes|filtros|limites)', r'jailbreak')
PAISES = _rx(r'\b(eua|estados unidos|portugal|argentina|espanha|italia|franca|alemanha|inglaterra|reino unido|canada|'
             r'mexico|chile|uruguai|paraguai|japao|china|australia)\b', r'lei (americana|portuguesa|argentina|europeia)')
INSTITUCIONAL = _rx(r'\blexia\b', r'\bplataforma\b', r'\bchatbot\b', r'\b(site|aplicativo|app)\b',
                    r'\bfuncionalidades?\b', r'\bmeus dados\b.*\b(guard|armazen|usad|tratad)', r'\bcadastr', r'\bcomo (uso|usar|utilizar)\b')
INDIVIDUAL = _rx(r'\b(meu|minha|o meu|a minha) (processo|acao|reclamacao|sentenca|alvara|recurso|caso no tribunal)\b',
                 r'\b(situacao|fase|andamento|etapa) (atual )?(d[oe] (meu )?)?processo\b', r'\bprocesso trabalhista (esta )?em andamento\b',
                 r'\balvara\b', r'\bprestacao de contas\b', r'\bconsultar (o )?(numero|andamento|processo)',
                 r'\b(valor exato|saldo|extrato|deposito)\b.*\b(minha|meu)\b', r'\bna minha conta\b',
                 r'\bnumero (e|ou) documentos? (nao|nunca)\b', r'\bfundamento .*\bsentenca do meu\b',
                 r'\bo juiz (mandou|determinou|deu|negou|decidiu|marcou)\b', r'\bcontadoria\b', r'\bliquidacao\b.*\b(processo|juiz)\b')
CASO_CONCRETO = _rx(r'\b(trabalhei|fui (demitid|dispensad|contratad|afastad|promovid)|fiquei|recebi|nao recebi|recusei|levei|precisei|'
                    r'sofri|pedi|assinei|me (demitiram|dispensaram|mandaram|obrigaram)|meu (chefe|patrao|empregador|gerente)|'
                    r'minha (empresa|chefe|patroa|carteira)|estou (afastad|gravida|trabalhando|desempregad)|tenho que)\b',
                    r'\b(o que (devo|posso) fazer|devo (entrar|processar|pedir|aceitar|assinar)|vale a pena|tenho chance|vou ganhar)\b')
TRABALHISTA = _rx(r'\btrabalh', r'\bemprega', r'\bclt\b', r'\bsalari', r'\bferias\b', r'\bfgts\b', r'\bjornada\b', r'\bhoras? extras?\b',
                  r'\bdemiss', r'\bdispensa', r'\brescis', r'\baviso previo\b', r'\bcarteira (de trabalho|assinada)\b', r'\bsindicat',
                  r'\bjusta causa\b', r'\b13\s*[oº°]', r'\bdecimo terceiro\b', r'\brescisao\b', r'\bconvencao\b', r'\bnormas? coletivas?\b',r'\badicional\b', r'\bestabilidade\b', r'\bgestante\b',
                  r'\bdomestic', r'\binss\b', r'\bpis\b', r'\bseguro.desemprego\b', r'\bintervalo\b', r'\bprocesso trabalhista\b',
                  r'\bjustica do trabalho\b', r'\bpreposto\b', r'\bassedio\b', r'\bconvencao coletiva\b', r'\bestagi')
OUTRO_DIREITO = _rx(r'\bimposto de renda\b', r'\btributa', r'\bdividendos?\b', r'\bdivorci', r'\bpensao alimenticia\b', r'\bguarda (do|dos|da) filh',
                    r'\binventario\b', r'\bheranca\b', r'\biptu\b', r'\bipva\b', r'\bmulta de transito\b', r'\bcnh\b', r'\bconsumidor\b',
                    r'\baluguel\b', r'\bdespejo\b', r'\bcrime\b', r'\bpolicia\b', r'\bfalencia\b', r'\bacoes da bolsa\b', r'\breceita federal\b')


@dataclass
class ResultadoEntrada:
    acao: str
    pergunta_sanitizada: str
    sinais: list = field(default_factory=list)
    motivo: str = ''


def verificar_entrada(pergunta):
    texto = (pergunta or '').strip()
    if len(texto) < 8:
        return ResultadoEntrada('fora_escopo', texto, ['pergunta_vazia'], 'Pergunta vazia ou curta demais.')
    texto = texto[:2000]
    sanitizada, pii = mascarar(texto)
    sinais = ['dados_pessoais'] if pii else []
    base = _sem_acento(sanitizada)
    if INJECAO.search(base):
        sinais.append('instrucao_suspeita')
        # Remove as frases com instruções; o restante segue como pergunta, tratado como dado.
        frases = [f for f in re.split(r'(?<=[.!?])\s+', sanitizada) if not INJECAO.search(_sem_acento(f))]
        sanitizada = ' '.join(frases).strip()
        base = _sem_acento(sanitizada)
        if len(sanitizada) < 8:
            return ResultadoEntrada('fora_escopo', sanitizada, sinais, 'Somente instruções, sem pergunta jurídica.')
    if INSTITUCIONAL.search(base):
        return ResultadoEntrada('institucional', sanitizada, sinais, 'Pergunta sobre a plataforma.')
    if PAISES.search(base):
        return ResultadoEntrada('outra_jurisdicao', sanitizada, sinais, 'Pergunta sobre o direito de outro país.')
    trabalhista = bool(TRABALHISTA.search(base))
    if OUTRO_DIREITO.search(base) and not trabalhista:
        return ResultadoEntrada('fora_escopo', sanitizada, sinais, 'Outro ramo do direito.')
    if INDIVIDUAL.search(base):
        return ResultadoEntrada('consulta_individual', sanitizada, sinais, 'Situação de processo, valor ou registro individual.')
    if CASO_CONCRETO.search(base):
        return ResultadoEntrada('orientar_sem_aconselhar', sanitizada, sinais, 'Relato de caso concreto.')
    # Sem sinal claro de outro ramo, a pergunta segue: a suficiência da evidência é decidida pela recuperação.
    if not trabalhista:
        sinais.append('sem_termo_trabalhista')
    return ResultadoEntrada('responder', sanitizada, sinais, 'Pergunta informativa.')


# --- saída ------------------------------------------------------------------------------------------------------
CITACAO = re.compile(r'\[?\(?Fonte\s*(\d+)\)?\]?', re.IGNORECASE)
CITACOES_POSPOSTAS = re.compile(r'(?:(?:\[Fonte[ \t]*\d+\]|\(Fonte[ \t]*\d+\))[ \t]*)+', re.IGNORECASE)
ARTIGO = re.compile(r'\bart(?:igo)?\.?\s*(\d+(?:-[A-Z])?)(?:\s*[ºo°])?', re.IGNORECASE)
PARAGRAFO = re.compile(r'§\s*(\d+)\s*[ºo°]?|par[áa]grafo\s+([úu]nico|\d+)', re.IGNORECASE)
CAPUT = re.compile(r'\bcaput\b', re.IGNORECASE)
# "Art. 73, § 2º", "art. 73, parágrafo único", "Art. 73, caput", "Art. 391-A".
MENCAO = re.compile(r'\bart(?:igo)?\.?\s*(\d+(?:-[A-Z])?)\s*[ºo°]?\s*(?:,\s*(?:§\s*(\d+)\s*[ºo°]?|par[áa]grafo\s+([úu]nico|\d+)|(caput)))?',
                    re.IGNORECASE)
NUMEROS = re.compile(r'(\d+(?:[.,]\d+)?)\s*(%|por cento|minutos?|horas?|dias?|meses|anos?|segundos?)', re.IGNORECASE)
PROMESSA = _rx(r'voce (vai|ira|certamente) (ganhar|receber|conseguir)', r'com certeza (voce )?(ganha|recebe|tem direito)',
               r'(ganho|vitoria|resultado) garantid', r'garanto que', r'nao tem como perder')
JURIDICO = _rx(r'\bart\.?\s*\d', r'\blei\b', r'\bdireito\b', r'\bdeve(m)?\b', r'\bprazo\b', r'\bobrigat', r'\b\d+\s*%', r'\bclt\b',
               r'\bpode(m)?\b', r'\bgarant')


ABREVIACOES = re.compile(r'\b(arts?|inc|incs|al|n|nº|p|pag|par|sr|sra|dr|dra|ex|obs|art)\.(?=\s)', re.IGNORECASE)
RESSALVA_INDIVIDUAL = _rx(r'nao (tenho|temos|consigo|e possivel) (acesso|acessar|consultar|saber|informar|dizer)',
                          r'sem (acesso|o numero|os documentos)', r'(consulte|consultar|verifique) .*(tribunal|advogad|processo|pje|site)',
                          r'nao (foram|foi) (informad|fornecid)')
# Pedido de dados ou documentos do caso: o sistema não acessa processos, então não deve solicitá-los.
PEDIDO_DADOS = re.compile(r'\b(forneca|fornecer|informe|informar|envie|enviar|mande|mandar|compartilhe|compartilhar|anexe|anexar|'
                          r'passe|passar|apresente|apresentar|digite|digitar)\b(\s+\S+){0,6}?\s+(o\s+)?'
                          r'(numero d[oa] (processo|acao)|documentos?|copia|trechos? da sentenca|sentenca|cpf|contracheques?)')


def _artigos_nas_fontes(fontes):
    """Artigos disponíveis nas fontes: o artigo_ref da legislação e os artigos citados no texto (ex.: em decisões)."""
    artigos = set()
    for fonte in fontes:
        ref = _normaliza_artigo(fonte.get('artigo_ref'))
        if ref:
            artigos.add(ref)
        artigos.update(a.upper() for a in ARTIGO.findall(fonte.get('texto', '') or ''))
    return artigos


def frases(texto):
    """Preserva abreviações jurídicas e associa citações após a pontuação à frase anterior.

    Apenas o bloco inicial de citações é anexado, dentro do mesmo parágrafo.
    O texto que vier depois dele continua sendo outra frase, sem herdar fontes.
    """
    protegido = ABREVIACOES.sub(lambda m: m.group(1) + '․', texto)
    partes = []
    for paragrafo in re.split(r'\r?\n[ \t]*\r?\n', protegido):
        frases_paragrafo = []
        for parte in re.split(r'(?<=[.!?:])\s+|\n+', paragrafo):
            parte = parte.strip()
            if (frases_paragrafo and frases_paragrafo[-1].endswith(('.', '!', '?'))
                    and not re.fullmatch(r'\d+\.', frases_paragrafo[-1])):
                citacoes = CITACOES_POSPOSTAS.match(parte)
                if citacoes:
                    frases_paragrafo[-1] += ' ' + citacoes.group().rstrip()
                    parte = parte[citacoes.end():].strip()
            if parte:
                frases_paragrafo.append(parte)
        partes.extend(frases_paragrafo)
    return [f.replace('․', '.') for f in partes if len(f) > 20]


def _normaliza_artigo(valor):
    m = re.search(r'(\d+(?:-[A-Z])?)', str(valor or ''), re.IGNORECASE)
    return m.group(1).upper() if m else None


def dispositivos(texto):
    """Divide o texto de um artigo em caput, parágrafos (§ N, único) e devolve {rótulo: trecho}."""
    partes, atual, rotulo = {}, [], 'caput'
    for linha in re.split(r'(?=§\s*\d+\s*[ºo°]?)|(?=Par[áa]grafo [úu]nico)', texto):
        m = re.match(r'§\s*(\d+)|Par[áa]grafo [úu]nico', linha.strip())
        if m:
            partes[rotulo] = ' '.join(atual)
            rotulo, atual = (f'§{m.group(1)}' if m.group(1) else 'unico'), []
        atual.append(linha)
    partes[rotulo] = ' '.join(atual)
    return partes


# --- validador v3 (2026-11-22): falhas apontadas pelo advogado revisor (notebook 04, seção 8) ---------------------
# Normas citadas pelo número: "Lei 8.036/1990", "Lei nº 13.467", "LC 150", "Decreto-Lei 5.452", "MP 946/2020",
# "Instrução Normativa 1.127", "Decreto Legislativo 6/2020", "Súmula 338", "OJ 394", "Tema 58".
NORMA = re.compile(
    r'\b(?P<tipo>lei\s+complementar|lc|decreto[\s-]+lei|decreto\s+legislativo|decreto|medida\s+provis[óo]ria|mp|'
    r'instru[çc][ãa]o\s+normativa(?:\s+rfb)?|in(?:\s+rfb)?|lei|s[úu]mula(?:\s+vinculante)?|oj|orienta[çc][ãa]o\s+jurisprudencial|tema)'
    r'\s*(?:n[º°o.]*\s*)?(?P<numero>\d{1,2}(?:\.\d{3})|\d{1,5})(?![\d.,]*\d)', re.IGNORECASE)
TIPO_NORMA = (('sumula', ('sumula',)), ('oj', ('oj', 'orientacao jurisprudencial')), ('tema', ('tema',)))
# Códigos citados por sigla ou nome, com o trecho do caminho das fontes de legislação que os identifica.
CODIGOS = {
    'CLT': ('consolidacao-das-leis-do-trabalho', r'CLT|Consolida[çc][ãa]o das Leis do Trabalho'),
    'CF': ('constituicao', r'CF|CF/88|Constitui[çc][ãa]o(?: Federal)?'),
    'CPC': ('codigo-de-processo-civil', r'CPC|C[óo]digo de Processo Civil'),
    'CC': ('codigo-civil', r'CC|C[óo]digo Civil'),
}
_COD = '|'.join(f'(?P<{k}>{v[1]})' for k, v in CODIGOS.items())
ARTIGO_CODIGO = re.compile(rf'\bart(?:igo)?s?\.?\s*(?P<art>\d+(?:-[A-Z])?)\s*[ºo°]?[^.;\n\[]{{0,45}}?\b(?:{_COD})\b'
                           rf'|\b(?:{_COD.replace("?P<", "?P<x")})\b,?\s*\(?\s*(?:em\s+seu\s+)?art(?:igo)?\.?\s*(?P<art2>\d+(?:-[A-Z])?)',
                           re.IGNORECASE)
METADADO_INTERNO = re.compile(r'in_force|status declarado|status_declarado|caminho_relativo|\b[\w-]+\.md\b', re.IGNORECASE)
CONTRAPESO = _rx(r'\bno entanto\b', r'\bcontudo\b', r'\bporem\b', r'\bentretanto\b', r'\bdepende\b', r'\bsalvo\b',
                 r'\bexceto\b', r'\bnao e automatic', r'\bnao se aplica\b')
BLOQUEANTES_V3 = BLOQUEANTES | {'norma_fora_das_fontes', 'sem_marcacao_fonte'}
VERSOES_SAIDA = ('v1', 'v3')


def _sem_pontos(texto):
    """Tira os pontos de milhar entre dígitos ("8.036" → "8036") para comparar números de normas."""
    return re.sub(r'(?<=\d)\.(?=\d{3}\b)', '', texto or '')


def _tipo_norma(rotulo):
    r = _sem_acento(rotulo)
    for tipo, prefixos in TIPO_NORMA:
        if r.startswith(prefixos):
            return tipo
    return 'lei'   # leis, LC, decretos, MP e IN: identificadas pelo número


def normas_citadas(texto):
    """{(tipo, número)} das normas citadas pelo número, com tipo 'lei', 'sumula', 'oj' ou 'tema'."""
    achados = set()
    for m in NORMA.finditer(texto or ''):
        numero = _sem_pontos(m.group('numero')).lstrip('0')
        if numero:
            achados.add((_tipo_norma(m.group('tipo')), numero))
    return achados


_NUMERO_NORMA = r'(?:n[º°o.]*\s*)?'


def _norma_nas_fontes(tipo, numero, fontes):
    for fonte in fontes:
        caminho = _sem_acento(str(fonte.get('caminho') or ''))
        # nome_citacao: fontes de precedente trazem "Súmula 338 do TST" no nome, não no texto do enunciado
        base = _sem_acento(_sem_pontos(' '.join(str(fonte.get(c) or '') for c in ('texto', 'contexto', 'nome_citacao'))))
        if tipo == 'lei':
            # Pelo caminho da fonte de legislação ("lei-8036-1990.md") ou pelo número junto de uma palavra de norma.
            if re.search(rf'-{numero}-', caminho) or re.search(
                    rf'\b(?:lei|lc|complementar|decreto|legislativo|mp|medida provisoria|instrucao normativa|in|rfb)\b'
                    rf'[^.;\n]{{0,25}}?(?<![\d.,]){numero}(?!\d)', base):
                return True
        elif tipo == 'sumula' and re.search(rf'sumula(?:\s+vinculante)?\s*{_NUMERO_NORMA}{numero}\b', base):
            return True
        elif tipo == 'oj' and re.search(rf'(?:\boj\b|orientac\w+ jurisprudencia\w*)[^.]{{0,40}}?\b{numero}\b', base):
            return True
        elif tipo == 'tema' and re.search(rf'\btema\s*{_NUMERO_NORMA}{numero}\b', base):
            return True
    return False


def artigos_de_codigo(texto):
    """{(código, artigo)} citados como 'art. 11 da CLT', 'CLT, art. 11' ou 'art. 51, X, da CF'."""
    achados = set()
    for m in ARTIGO_CODIGO.finditer(texto or ''):
        artigo = (m.group('art') or m.group('art2') or '').upper()
        codigo = next((k for k in CODIGOS if m.group(k) or m.group('x' + k)), None)
        if artigo and codigo:
            achados.add((codigo, artigo))
    return achados


def _artigo_de_codigo_nas_fontes(codigo, artigo, fontes):
    trecho_caminho, nome = CODIGOS[codigo]
    for fonte in fontes:
        if trecho_caminho in (fonte.get('caminho') or '') and _normaliza_artigo(fonte.get('artigo_ref')) == artigo:
            return True
        # Decisões e outras leis que citam o artigo junto do código também contam como "está nas fontes".
        if (codigo, artigo) in artigos_de_codigo(fonte.get('texto') or ''):
            return True
    return False


def alertas_v3(texto, fontes, lista_frases, juridicas):
    """Alertas do validador v3. Bloqueantes: norma_fora_das_fontes e sem_marcacao_fonte (ver BLOQUEANTES_V3)."""
    alertas = []
    if not fontes:
        return alertas
    for tipo, numero in sorted(normas_citadas(texto)):
        if not _norma_nas_fontes(tipo, numero, fontes):
            alertas.append(dict(codigo='norma_fora_das_fontes', detalhe=f'{tipo} {numero} não aparece em nenhuma fonte entregue'))
    for codigo, artigo in sorted(artigos_de_codigo(texto)):
        if not _artigo_de_codigo_nas_fontes(codigo, artigo, fontes):
            alertas.append(dict(codigo='norma_fora_das_fontes', detalhe=f'art. {artigo} da {codigo} não aparece em nenhuma fonte entregue'))
    if juridicas and not CITACAO.search(texto):
        alertas.append(dict(codigo='sem_marcacao_fonte', detalhe='Resposta jurídica sem nenhuma marcação [Fonte N].'))
    for frase in lista_frases:
        citadas = sorted({int(n) for n in CITACAO.findall(frase) if 1 <= int(n) <= len(fontes)})
        if len(citadas) > 2:
            alertas.append(dict(codigo='citacao_em_lote', detalhe=f'{len(citadas)} fontes numa frase', frase=frase.strip()[:200]))
        menciona_norma = ARTIGO.search(frase) or NORMA.search(frase)
        if citadas and menciona_norma and all(fontes[n - 1].get('tipo') == 'jurisprudencia' for n in citadas):
            alertas.append(dict(codigo='lei_citada_com_decisao', detalhe='Norma sustentada só por decisão judicial',
                                frase=frase.strip()[:200]))
    if METADADO_INTERNO.search(texto):
        alertas.append(dict(codigo='metadado_interno', detalhe='Resposta expõe metadado interno das fontes.'))
    if lista_frases:
        abertura = _sem_acento(lista_frases[0])
        if re.match(r'\W*(sim|nao)\b', abertura) and CONTRAPESO.search(_sem_acento(' '.join(lista_frases[1:]))):
            alertas.append(dict(codigo='abertura_categorica', detalhe='Abre com sim/não e depois condiciona a resposta.'))
    alertas.extend(alertas_precedentes(texto, fontes, lista_frases))
    return alertas


# --- Precedentes do TST como terceira fonte (notebook 07 da integração) -----------------------------------------
_CATALOGO_PRECEDENTES = None
# A resposta já avisa que o precedente não vale mais, ou que o tema está pendente, ou que pode ter mudado.
AVISO_INATIVO = _rx(r'cancelad', r'cancelamento', r'superad', r'revogad', r'suspens', r'nao (esta )?mais (em vigor|vigente|aplicavel)')
AVISO_PENDENTE = _rx(r'pendente', r'sem tese', r'ainda nao (ha|foi|tem|fixou|definiu|decidiu)', r'aguarda',
                     r'em (julgamento|discussao|analise)', r'nao (ha|existe) (ainda )?tese', r'afetad', r'indefinid',
                     r'nao foi (fixada|definida)', r'ainda sera (julgad|decidid|definid)')
AVISO_VIGENCIA = _rx(r'alterad', r'cancelad', r'vigencia', r'revisad', r'revist', r'desatualizad', r'modificad',
                     r'pode ter (sido|mudado)', r'superad', r'nao (esta )?mais em vigor')
SUMULA_CITADA = re.compile(r's[úu]mula(?P<vinc>\s+vinculante)?\s*(?:n[º°o.]*\s*)?(?P<num>\d{1,3})(?![\d.,]*\d)(?P<resto>[^.;\n]{0,40})',
                           re.IGNORECASE)
OJ_CITADA = re.compile(r'(?:\bOJ|orienta[çc][ãa]o\s+jurisprudencial)\s*(?:n[º°o.]*\s*)?(?P<num>\d{1,3})(?![\d.,]*\d)(?P<resto>[^.;\n]{0,45})',
                       re.IGNORECASE)
TEMA_CITADO = re.compile(r'\btema\s*(?:n[º°o.]*\s*)?(?P<num>\d{1,4})(?![\d.,]*\d)(?P<resto>[^.;\n]{0,40})', re.IGNORECASE)
OUTRO_TRIBUNAL = re.compile(r'\b(STF|STJ|TRT|TSE|Supremo|repercuss[ãa]o geral)\b', re.IGNORECASE)
NOMES_SITUACAO = {'cancelada': 'cancelado', 'suspensa': 'suspenso', 'tese_superada': 'com tese superada',
                  'cancelamento_noticiado': 'com cancelamento noticiado (fonte não oficial)'}


def catalogo_precedentes():
    """Situação das súmulas, OJs e temas do TST (src/integracao/situacao_precedentes.json, versionado)."""
    global _CATALOGO_PRECEDENTES
    if _CATALOGO_PRECEDENTES is None:
        import json
        from pathlib import Path
        _CATALOGO_PRECEDENTES = json.loads((Path(__file__).with_name('situacao_precedentes.json')).read_text(encoding='utf-8'))
    return _CATALOGO_PRECEDENTES


def _serie_oj(resto):
    r = _sem_acento(resto)
    if re.search(r'transit', r):
        return 'SBDI-1 (transitória)'
    if re.search(r'\bs\.?b?\.?di-?\s*2\b|\bsdi-?ii\b', r):
        return 'SBDI-2'
    if re.search(r'\bs\.?b?\.?di-?\s*1\b|\bsdi-?i\b', r):
        return 'SBDI-1'
    if re.search(r'\bsdc\b', r):
        return 'SDC'
    if re.search(r'pleno|orgao especial', r):
        return 'Tribunal Pleno/Órgão Especial'
    return None


def precedentes_inativos_citados(texto):
    """[(rótulo, situação)] dos precedentes do TST citados no texto que estão cancelados, suspensos ou superados.

    Súmula vinculante e citações seguidas de STF, STJ ou TRT não contam (outra numeração). OJ sem série só conta
    quando todas as OJs com esse número estão inativas. Tema só conta se o trecho falar em IRR, repetitivo ou TST.
    """
    cat, achados = catalogo_precedentes(), []
    for m in SUMULA_CITADA.finditer(texto or ''):
        if m.group('vinc') or OUTRO_TRIBUNAL.search(m.group('resto')):
            continue
        situacao = cat['sumulas'].get(m.group('num').lstrip('0'))
        if situacao:
            achados.append((m.start(), m.end(), f"Súmula {m.group('num')} do TST", situacao))
    for m in OJ_CITADA.finditer(texto or ''):
        series = cat['ojs'].get(m.group('num').lstrip('0'))
        if not series or OUTRO_TRIBUNAL.search(m.group('resto')):
            continue
        serie = _serie_oj(m.group('resto'))
        situacoes = [series[serie]] if serie in series else ([] if serie else list(series.values()))
        if situacoes and all(s in NOMES_SITUACAO for s in situacoes):
            achados.append((m.start(), m.end(), f"OJ {m.group('num')}" + (f' da {serie}' if serie else ''), situacoes[0]))
    for m in TEMA_CITADO.finditer(texto or ''):
        situacao = cat['temas_irr'].get(m.group('num').lstrip('0'))
        if situacao and re.search(r'IRR|repetitiv|TST', m.group('resto'), re.IGNORECASE):
            achados.append((m.start(), m.end(), f"Tema {m.group('num')} de IRR do TST", situacao))
    return achados


def alertas_precedentes(texto, fontes, lista_frases):
    """Alertas informativos sobre precedentes do TST (fontes com tipo 'precedentes').

    precedente_fonte_trocada   súmula, OJ ou tema citado com [Fonte N] que não o contém, embora outra fonte
                               de precedente entregue o contenha
    tema_sem_tese_como_regra   cita um tema afetado e ainda sem tese sem dizer que a questão está pendente
    alerta_vigencia_omitido    cita um precedente com alerta de vigência sem avisar que ele pode ter mudado
    precedente_cancelado       cita súmula, OJ ou tema cancelado, suspenso, superado ou com cancelamento noticiado
                               (quarentena) sem dizer isso
    """
    alertas, texto_sa = [], _sem_acento(texto or '')
    prec = {i + 1: f for i, f in enumerate(fontes) if f.get('tipo') == 'precedentes'}
    for frase in lista_frases:
        citadas = sorted({int(n) for n in CITACAO.findall(frase) if 1 <= int(n) <= len(fontes)})
        if not citadas or not prec:
            continue
        for tipo, numero in sorted(normas_citadas(frase)):
            if tipo == 'lei' or any(_norma_nas_fontes(tipo, numero, [fontes[n - 1]]) for n in citadas):
                continue
            certas = [n for n, f in prec.items() if _norma_nas_fontes(tipo, numero, [f])]
            if certas:
                alertas.append(dict(codigo='precedente_fonte_trocada',
                                    detalhe=f'{tipo} {numero} citada com [Fonte {", ".join(map(str, citadas))}]; '
                                            f'está na [Fonte {", ".join(map(str, certas))}]', frase=frase.strip()[:200]))
    citadas_texto = {int(n) for n in CITACAO.findall(texto or '')}
    for n, f in prec.items():
        if n not in citadas_texto:
            continue
        nome = f.get('nome_citacao') or f'Fonte {n}'
        if f.get('situacao') == 'afetado_sem_tese' and not AVISO_PENDENTE.search(texto_sa):
            alertas.append(dict(codigo='tema_sem_tese_como_regra',
                                detalhe=f'{nome} [Fonte {n}] ainda não tem tese fixada, e a resposta não diz isso'))
        if f.get('alerta_vigencia') and not AVISO_VIGENCIA.search(texto_sa):
            alertas.append(dict(codigo='alerta_vigencia_omitido',
                                detalhe=f'{nome} [Fonte {n}] tem alerta de vigência, e a resposta não avisa'))
    vistos = set()
    for inicio, fim, rotulo, situacao in precedentes_inativos_citados(texto):
        janela = _sem_acento((texto or '')[max(0, inicio - 120):fim + 120])
        if not AVISO_INATIVO.search(janela) and rotulo not in vistos:
            vistos.add(rotulo)
            alertas.append(dict(codigo='precedente_cancelado',
                                detalhe=f'{rotulo} está {NOMES_SITUACAO[situacao]}, e a resposta não diz isso'))
    return alertas


@dataclass
class ResultadoSaida:
    aprovada: bool
    alertas: list
    resposta_final: str


def verificar_saida(resposta, fontes, entrada=None, versao='v1'):
    """fontes: lista na ordem das [Fonte N], cada uma com 'texto' e, na legislação, 'artigo_ref'.

    `versao='v3'` acrescenta os alertas de `alertas_v3` e usa BLOQUEANTES_V3; para isso as fontes devem trazer
    também 'tipo' ('legislacao' ou 'jurisprudencia') e, na legislação, 'caminho'. `versao='v1'` mantém o
    comportamento original.
    """
    if versao not in VERSOES_SAIDA:
        raise ValueError(f'Versão do guardrail de saída desconhecida: {versao}')
    alertas, texto = [], resposta or ''
    processos_fontes = [f.get('processo') for f in fontes] + PROCESSO_CNJ.findall(' '.join(f.get('texto', '') or '' for f in fontes))
    final, pii = mascarar(texto, processos_fontes)
    if pii:
        alertas.append(dict(codigo='dados_pessoais_saida', detalhe=', '.join(pii)))
    lista_frases = frases(texto)
    for numero in {int(n) for n in CITACAO.findall(texto)}:
        if not 1 <= numero <= len(fontes):
            alertas.append(dict(codigo='citacao_inexistente', detalhe=f'Fonte {numero}'))
    for frase in lista_frases:
        citadas =[int(n) for n in CITACAO.findall(frase) if 1 <= int(n) <= len(fontes)]
        artigos = ARTIGO.findall(frase)
        if not citadas or not artigos:
            continue
        mencoes = [(m.group(1).upper(), m.group(2) or m.group(3) or m.group(4)) for m in MENCAO.finditer(frase)]
        for n in citadas:
            fonte = fontes[n - 1]
            ref = _normaliza_artigo(fonte.get('artigo_ref'))
            if ref is None:
                continue  # jurisprudência ou fonte sem artigo: não se aplica
            # Somente os dispositivos mencionados junto do próprio artigo da fonte ("Art. 73, § 2º").
            alvo = set()
            for artigo, dispositivo in mencoes:
                if artigo != ref or not dispositivo:
                    continue
                d = _sem_acento(dispositivo)
                alvo.add('caput' if d == 'caput' else 'unico' if d.startswith('unico') else f'§{d}')
            partes = dispositivos(fonte.get('texto', '')) if alvo else {}
            for rotulo in sorted(alvo):
                if rotulo not in partes:
                    alertas.append(dict(codigo='dispositivo_inconsistente', detalhe=f'{rotulo} não existe no art. {ref} [Fonte {n}]',
                                        frase=frase.strip()[:200]))
                    continue
                trecho = _sem_acento(partes[rotulo])
                for valor, unidade in NUMEROS.findall(frase):
                    if valor.replace(',', '.') not in trecho.replace(',', '.'):
                        alertas.append(dict(codigo='dispositivo_inconsistente',
                                            detalhe=f'"{valor} {unidade}" não aparece no {rotulo} do art. {ref} [Fonte {n}]',
                                            frase=frase.strip()[:200]))
    # Artigo citado na resposta que não está em nenhuma fonte entregue (só compara o número do artigo, não a norma).
    if fontes:
        disponiveis = _artigos_nas_fontes(fontes)
        for artigo in sorted({m.group(1).upper() for m in MENCAO.finditer(texto)} - disponiveis):
            frase = next((f for f in lista_frases if re.search(rf'\bart(?:igo)?\.?\s*{re.escape(artigo)}\b', f, re.IGNORECASE)), '')
            alertas.append(dict(codigo='artigo_sem_fonte', detalhe=f'art. {artigo} não está em nenhuma fonte entregue',
                                frase=frase.strip()[:200]))
    juridicas = [f for f in lista_frases if JURIDICO.search(_sem_acento(f))]
    sem_citacao = [f for f in juridicas if not CITACAO.search(f)]
    # Sem fontes só é falha quando a entrada pedia busca; nas ações de recusa/redirecionamento a resposta não
    # tem fontes por desenho, e o excesso de conteúdo jurídico é tratado por resposta_alem_do_escopo.
    acao_sem_busca = entrada is not None and entrada.acao in ('fora_escopo', 'outra_jurisdicao', 'institucional',
                                                              'consulta_individual')
    if juridicas and not fontes and not acao_sem_busca:
        alertas.append(dict(codigo='sem_fontes', detalhe='Afirmações jurídicas sem nenhuma fonte entregue.'))
    elif len(juridicas) >= 3 and len(sem_citacao) / len(juridicas) > 0.6:
        alertas.append(dict(codigo='afirmacao_sem_fonte', detalhe=f'{len(sem_citacao)} de {len(juridicas)} frases jurídicas sem citação'))
    if PROMESSA.search(_sem_acento(texto)):
        alertas.append(dict(codigo='promessa_resultado', detalhe='Promessa de resultado ou de valor.'))
    if entrada is not None and entrada.acao in ('fora_escopo', 'outra_jurisdicao', 'institucional') and len(juridicas) >= 3:
        alertas.append(dict(codigo='resposta_alem_do_escopo', detalhe=f'Entrada classificada como {entrada.acao}.'))
    if entrada is not None and entrada.acao == 'consulta_individual' and not RESSALVA_INDIVIDUAL.search(_sem_acento(texto)):
        alertas.append(dict(codigo='consulta_individual_sem_ressalva',
                            detalhe='A resposta não informa que o sistema não tem acesso ao processo ou aos registros da pessoa.'))
    if entrada is not None and entrada.acao == 'consulta_individual':
        sem_acento = _sem_acento(texto)
        for m in PEDIDO_DADOS.finditer(sem_acento):
            if not re.search(r'\bnao\s+(\S+\s+)?$', sem_acento[max(0, m.start() - 15):m.start()]):  # "não envie seu CPF" é orientação correta
                alertas.append(dict(codigo='consulta_individual_pede_dados',
                                    detalhe='A resposta pede número do processo, documentos ou dados pessoais.',
                                    frase=texto[m.start():m.end() + 40].strip()))
                break
    if versao == 'v3' and not acao_sem_busca:
        alertas.extend(alertas_v3(texto, fontes, lista_frases, juridicas))
    if 'nao substitui' not in _sem_acento(texto):
        alertas.append(dict(codigo='aviso_legal_ausente', detalhe='Aviso acrescentado.'))
        final = final.rstrip() + '\n\n' + AVISO_LEGAL
    unicos, vistos = [], set()
    for a in alertas:
        chave = (a['codigo'], a['detalhe'])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(a)
    bloqueantes = BLOQUEANTES_V3 if versao == 'v3' else BLOQUEANTES
    aprovada = not any(a['codigo'] in bloqueantes for a in unicos)
    return ResultadoSaida(aprovada, unicos, final)
