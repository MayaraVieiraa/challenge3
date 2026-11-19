"""Kernel do Kaggle (GPU T4): roda pedidos de LLM no Ollama (geração com Qwen3 8B ou julgamento com Gemma 3 12B).

Campos opcionais por pedido: `think` (False por padrão; None para modelos sem raciocínio) e `formato`
('json' para saída estruturada).

Lê pedidos.jsonl do dataset privado, gera uma resposta por pedido que precisa de LLM e grava respostas.jsonl
de forma incremental em /kaggle/working. Cada resposta é validada (não vazia, não cortada, sem raciocínio
interno); uma resposta cortada é refeita com limite maior de tokens. Mesma versão do Ollama do ambiente local.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

OLLAMA_VERSAO = '0.40.16'
LIMITE_SEGUNDOS = 11 * 3600          # para antes do limite de 12 h da sessão
SAIDA = Path('/kaggle/working/respostas.jsonl')
OBSERVABILIDADE = Path('/kaggle/working/observabilidade.jsonl')
URL = 'http://127.0.0.1:11434'
RUN_ID = str(uuid.uuid4())


def sh(comando):
    print('$', comando, flush=True)
    subprocess.run(comando, shell=True, check=True)


def chamar(caminho, corpo=None, timeout=1800):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(URL + caminho, dados, {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def registrar_evento(pergunta_id, status, segundos, metricas, tipo_erro=None):
    evento = dict(
        timestamp=datetime.now(timezone.utc).isoformat(),
        run_id=RUN_ID,
        etapa='geracao_llm',
        status=status,
        duracao_ms=round(segundos * 1000, 2),
        pergunta_id_sha256=hashlib.sha256(pergunta_id.encode('utf-8')).hexdigest(),
        metricas=metricas,
        tipo_erro=tipo_erro,
    )
    with OBSERVABILIDADE.open('a', encoding='utf-8', newline='\n') as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False, allow_nan=False) + '\n')


def problema_saida_estruturada(formato, texto):
    if not isinstance(formato, dict):
        return None
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return 'structured_output'
    if not isinstance(dados, dict):
        return 'structured_output'
    obrigatorios = set(formato.get('required', []))
    propriedades = formato.get('properties', {})
    if dados.keys() != obrigatorios:
        return 'structured_output'
    for campo, schema in propriedades.items():
        valor = dados.get(campo)
        if schema.get('type') == 'string' and (not isinstance(valor, str) or not valor.strip()):
            return 'structured_output'
        if schema.get('type') == 'array':
            tipo_item = schema.get('items', {}).get('type')
            if not isinstance(valor, list):
                return 'structured_output'
            if tipo_item == 'string' and any(not isinstance(item, str) or not item.strip() for item in valor):
                return 'structured_output'
    return None


inicio = time.monotonic()
OBSERVABILIDADE.write_text('', encoding='utf-8')
sh('apt-get install -y -q zstd > /dev/null 2>&1 || true')
sh(f'curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION={OLLAMA_VERSAO} sh')
log = open('/kaggle/working/ollama.log', 'w')
subprocess.Popen(['ollama', 'serve'], env={**os.environ, 'OLLAMA_KEEP_ALIVE': '-1'}, stdout=log, stderr=log)
for _ in range(60):
    try:
        chamar('/api/tags', timeout=5)
        break
    except Exception:
        time.sleep(2)

arquivo = glob.glob('/kaggle/input/**/pedidos.jsonl', recursive=True)[0]
pedidos = [json.loads(l) for l in open(arquivo, encoding='utf-8') if l.strip()]
modelos = sorted({p['modelo'] for p in pedidos if p.get('precisa_llm')})
for m in modelos:
    sh(f'ollama pull {m}')
print(chamar('/api/version'), flush=True)

feitos = set()
if SAIDA.exists():
    feitos = {json.loads(l)['pergunta_id'] for l in SAIDA.read_text(encoding='utf-8').splitlines() if l.strip()}
pendentes = [p for p in pedidos if p.get('precisa_llm') and p['pergunta_id'] not in feitos]
print(f'{len(pedidos)} pedidos, {len(pendentes)} para gerar', flush=True)

with SAIDA.open('a', encoding='utf-8') as saida:
    for i, p in enumerate(pendentes, 1):
        if time.monotonic() - inicio > LIMITE_SEGUNDOS:
            print('limite de tempo atingido; respostas parciais salvas (as pendentes ficam para outra execução)', flush=True)
            break
        opcoes = dict(p['opcoes'])
        tentativas, r, texto = [], {}, None
        for tentativa in range(3):
            t = time.monotonic()
            try:
                corpo = dict(model=p['modelo'], messages=p['mensagens'], stream=False, options=opcoes)
                if p.get('think', False) is not None:   # None = modelo sem modo de raciocínio (ex.: Gemma)
                    corpo['think'] = p.get('think', False)
                if p.get('formato'):
                    corpo['format'] = p['formato']
                r = chamar('/api/chat', corpo)
            except Exception as erro:
                tentativas.append(dict(erro=str(erro)[:300]))
                time.sleep(10)
                continue
            texto = r['message']['content']
            problema = ('cortada' if r.get('done_reason') == 'length' else
                        'vazia' if len(texto.strip()) < 80 else
                        'raciocinio' if re.search(r'</?think>', texto) else
                        problema_saida_estruturada(p.get('formato'), texto))
            tentativas.append(dict(segundos=round(time.monotonic() - t, 1), done_reason=r.get('done_reason'), problema=problema))
            if problema is None:
                break
            if problema == 'cortada':
                opcoes['num_predict'] = int(opcoes.get('num_predict', 1200)) * 2
        registro = dict(pergunta_id=p['pergunta_id'], pedido_sha256=p['pedido_sha256'], modelo=p['modelo'], opcoes=opcoes,
                        resposta=texto if 'erro' not in tentativas[-1] else None,
                        done_reason=r.get('done_reason') if 'erro' not in tentativas[-1] else None,
                        prompt_tokens=r.get('prompt_eval_count'), tokens_saida=r.get('eval_count'),
                        segundos=sum(x.get('segundos', 0) for x in tentativas), tentativas=tentativas)
        saida.write(json.dumps(registro, ensure_ascii=False) + '\n')
        saida.flush()
        problema_final = tentativas[-1].get('problema')
        houve_erro = 'erro' in tentativas[-1]
        registrar_evento(
            p['pergunta_id'],
            'erro' if houve_erro else ('resposta_invalida' if problema_final else 'ok'),
            registro['segundos'],
            {
                'tentativas': len(tentativas),
                'prompt_tokens': registro['prompt_tokens'] or 0,
                'tokens_saida': registro['tokens_saida'] or 0,
            },
            'chamada_llm' if houve_erro else ('saida_invalida' if problema_final else None),
        )
        print(f'{i}/{len(pendentes)} {p["pergunta_id"]} {registro["segundos"]:.1f}s {tentativas[-1]}', flush=True)

linhas = [json.loads(l) for l in SAIDA.read_text(encoding='utf-8').splitlines() if l.strip()]
resumo = dict(pedidos_llm=sum(1 for p in pedidos if p.get('precisa_llm')), respostas=len(linhas),
              validas=sum(1 for l in linhas if l['resposta'] and l['tentativas'][-1].get('problema') is None),
              segundos_medios=round(sum(l['segundos'] for l in linhas) / max(len(linhas), 1), 1),
              ollama=chamar('/api/version'), gpu=subprocess.run('nvidia-smi --query-gpu=name,memory.total --format=csv,noheader',
                                                                 shell=True, capture_output=True, text=True).stdout.strip())
Path('/kaggle/working/resumo.json').write_text(json.dumps(resumo, indent=2), encoding='utf-8')
print(resumo, flush=True)
