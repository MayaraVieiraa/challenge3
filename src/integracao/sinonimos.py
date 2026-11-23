"""Sinônimos jurídicos para a pergunta: o usuário diz "13º salário", a súmula diz "gratificação natalina".

A avaliação da base de precedentes (notebook 06 de precedentes) mostrou o caso: a pergunta sobre horas extras no
13º salário não encontrou a Súmula 45 do TST ("...integra o cálculo da gratificação natalina") em nenhuma busca.

`expandir(pergunta)` acrescenta ao fim da pergunta, entre parênteses, os termos equivalentes que faltam. A pergunta
original não é alterada. A expansão é usada só quando a configuração da busca pede (`expandir_sinonimos=True`), para
não mudar os resultados já medidos. Cada grupo reúne formas usadas por quem pergunta e pelos textos legais.

O grupo ('rescisão indireta', 'justa causa do empregador') foi retirado: na busca por palavras, "justa causa" puxa
decisões sobre justa causa do empregado e tirou dos 10 primeiros a decisão certa de uma pergunta do gabarito de
jurisprudência (notebook 07 da integração, seção 8).
"""
import re
import unicodedata

GRUPOS = [
    ('13º salário', '13º', 'décimo terceiro salário', 'décimo terceiro', 'gratificação natalina'),
    ('hora extra', 'horas extras', 'serviço extraordinário', 'serviço suplementar', 'horas suplementares'),
    ('DSR', 'RSR', 'descanso semanal remunerado', 'repouso semanal remunerado'),
    ('FGTS', 'fundo de garantia do tempo de serviço'),
    ('carteira de trabalho', 'CTPS', 'carteira de trabalho e previdência social'),
    ('auxílio-doença', 'benefício por incapacidade temporária'),
    ('aposentadoria por invalidez', 'benefício por incapacidade permanente'),
    ('trabalho noturno', 'adicional noturno', 'hora noturna'),
    ('pedido de demissão', 'demissão a pedido do empregado'),
    ('demissão sem justa causa', 'dispensa sem justa causa', 'despedida sem justa causa'),
    ('trabalho em feriado', 'trabalho no feriado', 'trabalho em dia de feriado', 'feriado trabalhado', 'feriados trabalhados'),
    ('salário-maternidade', 'licença-maternidade', 'licença à gestante'),
    ('empregada doméstica', 'empregado doméstico', 'trabalhador doméstico'),
    ('terceirização', 'prestação de serviços a terceiros', 'contrato de prestação de serviços'),
]


def _norm(texto):
    t = unicodedata.normalize('NFD', texto.lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'(\d+)\s*[ºo°](?![a-z])', r'\1º', t)  # "13º" = "13o" = "13°"; o ordinal fica (13 de maio ≠ 13º)
    return re.sub(r'\s+', ' ', t)


def _presente(termo, texto_norm):
    padrao = re.escape(_norm(termo))
    if re.fullmatch(r'\d+º', _norm(termo)):
        # ordinal sozinho ("13º"): não vale depois de "art.", "artigo", "inciso" ou "§" (ex.: "art. 13º")
        padrao = r'(?<!art\. )(?<!artigo )(?<!inciso )(?<!§ )' + padrao
    return re.search(rf'(?<!\w){padrao}(?!\w)', texto_norm) is not None


def termos_faltantes(pergunta):
    """Termos equivalentes aos que aparecem na pergunta e que ela ainda não contém."""
    t = _norm(pergunta)
    faltam = []
    for grupo in GRUPOS:
        if any(_presente(termo, t) for termo in grupo):
            faltam += [termo for termo in grupo if not _presente(termo, t) and termo not in faltam]
    return faltam


def expandir(pergunta):
    faltam = termos_faltantes(pergunta)
    return f'{pergunta} ({"; ".join(faltam)})' if faltam else pergunta
