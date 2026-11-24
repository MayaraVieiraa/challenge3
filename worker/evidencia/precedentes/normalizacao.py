"""Normalização de texto para a busca por palavras (índice lexical) da base de precedentes.

Aplica-se SÓ ao texto que vai para o índice e à pergunta, nunca ao texto guardado ou entregue ao modelo (que continua
o texto oficial, com "art. 7º", "Lei nº 8.036" e "§ 1º"). Sem remoção de stopwords: todas as palavras ficam no índice.

Regras (cada uma resolve um descasamento observado no índice padrão do PostgreSQL):
  1. "§" e "§§"            -> "paragrafo" / "paragrafos"      ("§ 1º" virava só "1")
  2. "art." / "arts."      -> "artigo" / "artigos"            ("art" e "artigo" eram palavras diferentes)
  3. "nº", "n.º", "n°", "no." antes de número -> removido     ("Lei nº 8.036" = "Lei 8.036")
  4. ordinal colado ao número: "7º", "7°", "7o", "1ª", "1a" -> "7", "1"   ("7º" e "7" eram palavras diferentes)
  5. ponto de milhar: "8.036", "1.046" -> "8036", "1046"     (a pergunta pode vir sem o ponto);
     barra entre números separada: "8036/1990" -> "8036 / 1990" (senão vira uma palavra só)
  6. numeral romano isolado em maiúsculas (I a XXXIX): "XIII" -> "inc13"
     (o radicalizador do português transformava "xiii" em "xii", juntando os incisos XII e XIII)
  7. minúsculas e sem acento ("não" = "nao"), espaços simples
"""
import re
import unicodedata

VERSAO = 'normalizacao-lexica-v1'
ROMANO = re.compile(r'\b(X{0,3})(IX|IV|V?I{0,3})\b')
VALOR = {'I': 1, 'V': 5, 'X': 10}


def _romano_para_int(s):
    total, anterior = 0, 0
    for c in reversed(s):
        v = VALOR[c]
        total = total - v if v < anterior else total + v
        anterior = max(anterior, v)
    return total


def _romano(m):
    s = m.group(0)
    return f'inc{_romano_para_int(s)}' if s else s


def normalizar(texto):
    t = unicodedata.normalize('NFKC', texto or '')
    t = t.replace('§§', ' paragrafos ').replace('§', ' paragrafo ')
    t = re.sub(r'\barts\.', 'artigos ', t, flags=re.I)
    t = re.sub(r'\bart\.', 'artigo ', t, flags=re.I)
    t = re.sub(r'\bn\s*\.?\s*[º°o]\s*\.?\s*(?=\d)', ' ', t, flags=re.I)
    t = re.sub(r'(?<=\d)\s?[º°ª](?!\w)', '', t)
    t = re.sub(r'(?<=\d)[oa](?![\wº°])', '', t)
    t = re.sub(r'(?<=\d)\.(?=\d{3}(?!\d))', '', t)
    t = re.sub(r'(?<=\d)/(?=\d)', ' / ', t)  # "8036/1990" -> "8036 / 1990": número da lei e ano viram palavras separadas
    t = ROMANO.sub(_romano, t)
    t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', t.lower()).strip()


# Configuração de busca textual sem stopwords: mesmo radicalizador (snowball português), sem lista de stopwords.
DDL_CONFIG = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_ts_dict d JOIN pg_namespace n ON n.oid = d.dictnamespace
                 WHERE n.nspname = 'lex_precedentes' AND d.dictname = 'pt_radical') THEN
    CREATE TEXT SEARCH DICTIONARY lex_precedentes.pt_radical (TEMPLATE = snowball, Language = portuguese);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
                 WHERE n.nspname = 'lex_precedentes' AND c.cfgname = 'pt_sem_stopwords') THEN
    CREATE TEXT SEARCH CONFIGURATION lex_precedentes.pt_sem_stopwords (COPY = pg_catalog.portuguese);
    ALTER TEXT SEARCH CONFIGURATION lex_precedentes.pt_sem_stopwords
      ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part WITH lex_precedentes.pt_radical;
  END IF;
END $$;
"""
CONFIG = 'lex_precedentes.pt_sem_stopwords'
