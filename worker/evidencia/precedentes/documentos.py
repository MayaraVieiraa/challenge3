"""Catálogo dos documentos recebidos para a base de precedentes e inventário dos arquivos.

Os PDFs ficam em dados/raw/precedentes/ como foram baixados, sem edição, e fora do Git (o maior tem 238 MB).
O inventário registra o hash SHA-256 de cada arquivo; é ele que identifica a versão usada na base.
"""
import hashlib
from pathlib import Path

import pandas as pd

PASTA_PADRAO = Path(__file__).resolve().parents[2] / 'dados/raw/precedentes'

# papel: fonte_principal | fonte_vigencia | referencia | fora_do_escopo
# destino: para onde o conteúdo vai (esta base, a base de legislação ou nenhuma)
CATALOGO = [
    dict(arquivo='arquivo-versao-eletronica-28-6-2024-1.pdf', sigla='TRT3_2024',
         titulo='Jurisprudência consolidada com notas remissivas - TRT da 3ª Região e TST',
         emissor='TRT da 3ª Região (SEJPAC)', data_referencia='2024-06-28', papel='fonte_principal',
         destino='base de precedentes',
         uso='Súmulas e OJs do TST (2ª parte, p. 65-256), no formato oficial com situação e histórico de cada verbete.'),
    dict(arquivo='Índice Temático IRRs - versão Novembro 19_11_2026.pdf', sigla='IRR_2026',
         titulo='Índice temático dos incidentes de recursos repetitivos (IRR, IAC e IRDR) do TST',
         emissor='TST', data_referencia='2026-11-19', papel='fonte_principal', destino='base de precedentes',
         uso='Temas repetitivos (parte temática, p. 12-121): questão jurídica, tese e referências; situação pela cor do título.'),
    dict(arquivo='cancelamento_36_enunciados_tst.pdf', sigla='NOTICIA_CANCELAMENTO',
         titulo='Cancelamento de 36 enunciados do TST (notícia)', emissor='não oficial (notícia)',
         data_referencia=None, papel='fonte_vigencia', destino='base de precedentes (só alerta)',
         uso='Lista de enunciados noticiados como cancelados depois de 06/2024; vira alerta de vigência, '
             'não altera a situação oficial até a resolução do TST ser conferida.'),
    dict(arquivo='Índice Temático de Repercussão Geral - Temas de Interesse da Justiça do Trabalho versão 19_11_2026_compressed.pdf',
         sigla='RG_STF_2026', titulo='Índice temático de repercussão geral - temas de interesse da Justiça do Trabalho',
         emissor='TST (Gabinete da Presidência)', data_referencia='2026-11-19', papel='referencia',
         destino='etapa posterior (precedentes do STF)',
         uso='Repercussão geral, súmulas vinculantes e controle concentrado do STF. Fica para a etapa do STF.'),
    dict(arquivo='acordao_168.pdf', sigla='ACORDAO_168',
         titulo='Acórdão do Tribunal Pleno do TST - reafirmação de jurisprudência (Súmula 462)', emissor='TST',
         data_referencia=None, papel='referencia', destino='nenhuma (dados pessoais)',
         uso='Exemplo de reafirmação de tese em IRR. Contém nomes das partes; a tese já está no índice de IRR.'),
    dict(arquivo='Juris_consolidada.pdf', sigla='TRT2_2021', titulo='JurisConsolidada - TRT da 2ª Região',
         emissor='TRT da 2ª Região', data_referencia='2021-12-06', papel='fora_do_escopo', destino='nenhuma',
         uso='Mais antiga que a coletânea do TRT-3 e redundante para o TST.'),
    dict(arquivo='nova_lei_escala_de_trabalho.pdf', sigla='EC_141_2026',
         titulo='Emenda Constitucional nº 141, de 16/10/2026 (jornada de 40 horas e dois dias de repouso)',
         emissor='Presidência da República (Planalto)', data_referencia='2026-10-16', papel='fora_do_escopo',
         destino='base de legislação (atualizar o art. 7º da CF)',
         uso='Não é precedente: é norma constitucional. Página em imagem, sem camada de texto.'),
    dict(arquivo='DOC-SF268825244035-20260528.pdf', sigla='AUTOGRAFO_EC_2026',
         titulo='Autógrafo da proposta de emenda constitucional enviado pela Câmara', emissor='Câmara dos Deputados / Senado Federal',
         data_referencia='2026-05-28', papel='fora_do_escopo', destino='nenhuma (versão de tramitação)',
         uso='Texto em tramitação da mesma emenda; a versão oficial é a EC 141.'),
    # Cópias baixadas duas vezes: mesmo hash do original; ficam registradas, mas não são lidas.
    dict(arquivo='arquivo-versao-eletronica-28-6-2024-1 (1).pdf', sigla='TRT3_2024_COPIA',
         titulo='Cópia idêntica da coletânea do TRT-3', emissor='TRT da 3ª Região (SEJPAC)',
         data_referencia='2024-06-28', papel='duplicata', destino='nenhuma (cópia de TRT3_2024)',
         uso='Mesmo hash de arquivo-versao-eletronica-28-6-2024-1.pdf; não é lida na extração.'),
    dict(arquivo='Índice Temático de Repercussão Geral - Temas de Interesse da Justiça do Trabalho versão 19_11_2026_compressed (1).pdf',
         sigla='RG_STF_2026_COPIA', titulo='Cópia idêntica do índice de repercussão geral',
         emissor='TST (Gabinete da Presidência)', data_referencia='2026-11-19', papel='duplicata',
         destino='nenhuma (cópia de RG_STF_2026)',
         uso='Mesmo hash do índice de repercussão geral; não é lida.'),
]


def sha256(caminho, bloco=1 << 20):
    h = hashlib.sha256()
    with open(caminho, 'rb') as f:
        while parte := f.read(bloco):
            h.update(parte)
    return h.hexdigest()


def inventario(pasta=PASTA_PADRAO):
    """Uma linha por PDF da pasta: catálogo + hash, tamanho, páginas e camada de texto."""
    import pymupdf

    pasta = Path(pasta)
    por_nome = {c['arquivo']: c for c in CATALOGO}
    linhas = []
    for pdf in sorted(pasta.glob('*.pdf')):
        doc = pymupdf.open(pdf)
        caracteres = [len(p.get_text().strip()) for p in doc]
        meta = por_nome.get(pdf.name, dict(arquivo=pdf.name, sigla=None, papel='nao_catalogado'))
        linhas.append(dict(meta, sha256=sha256(pdf), tamanho_mb=round(pdf.stat().st_size / 2**20, 1),
                           paginas=len(doc), caracteres_texto=sum(caracteres),
                           paginas_sem_texto=sum(c < 20 for c in caracteres),
                           camada_texto=sum(caracteres) > 20 * len(doc),
                           metadado_criacao=(doc.metadata or {}).get('creationDate') or None))
        doc.close()
    faltando = sorted(set(por_nome) - {l['arquivo'] for l in linhas})
    df = pd.DataFrame(linhas)
    df.attrs['faltando'] = faltando
    return df
