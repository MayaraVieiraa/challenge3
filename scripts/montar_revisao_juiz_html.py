"""Página local de revisão humana do juiz (mesmo conteúdo da planilha de scripts/montar_revisao_juiz.py, legível).

Abre no navegador, sem internet. As marcações ficam guardadas no próprio navegador (localStorage) e o botão
"Exportar marcações" baixa um arquivo JSON para importar depois (scripts/importar_revisao_juiz.py).

NÃO publicar: a página tem perguntas protegidas e trechos de decisões.
Saída: output/integracao/revisao_juiz/revisao_juiz_27b[_llama].html (fora do Git).
Uso: python scripts/montar_revisao_juiz_html.py [--llama]
"""
from html import escape
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from montar_revisao_juiz import ORDEM_TRIAGEM, carregar, montar, sortear_cego

TRIAGEM = dict(
    provavel_falso_alarme=('Provável falso alarme', 'as afirmações que o juiz recusou parecem estar nas fontes'),
    inconclusiva=('Inconclusiva', 'a checagem automática não conseguiu decidir'),
    provavel_reprovacao_correta=('Provável reprovação correta', 'há artigo, número ou trecho que não está nas fontes'),
    revisar_notas=('Revisar notas', 'nota baixa em correção ou comportamento: a checagem não avalia isso'))
SINAL = dict(apoio_textual='parece estar na fonte', inconclusivo='inconclusivo', pouco_apoio='pouco apoio nas fontes',
             referencia_ausente='referência ausente das fontes')


def md(texto):
    """Markdown mínimo das respostas (negrito, itálico, títulos, listas), com [Fonte N] destacado."""
    blocos, lista = [], []

    def inline(t):
        t = escape(t)
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'<em>\1</em>', t)
        return re.sub(r'\[(Fontes? [\d ,e]+)\]', r'<span class="cita">[\1]</span>', t)

    def fechar_lista():
        if lista:
            blocos.append('<ul>' + ''.join(f'<li>{i}</li>' for i in lista) + '</ul>')
            lista.clear()

    for linha in (texto or '').splitlines():
        s = linha.strip()
        if not s:
            fechar_lista()
            continue
        m = re.match(r'^(?:[-*•]|\d+[.)])\s+(.*)', s)
        if m:
            lista.append(inline(m.group(1)))
            continue
        fechar_lista()
        h = re.match(r'^#{1,6}\s+(.*)', s)
        blocos.append(f'<h4>{inline(h.group(1))}</h4>' if h else f'<p>{inline(s)}</p>')
    fechar_lista()
    return '\n'.join(blocos)


def opcoes(chave, valores):
    nome = escape(chave)
    return '<div class="opcoes" data-chave="%s">%s</div>' % (nome, ''.join(
        f'<button type="button" data-valor="{escape(v)}">{escape(v)}</button>' for v in valores))


def observacao(chave):
    return f'<textarea data-chave="{escape(chave)}" rows="2" placeholder="Observação (opcional)"></textarea>'


def bloco_fontes(fontes):
    if not len(fontes):
        return '<p class="nota">Nenhuma fonte foi entregue ao assistente.</p>'
    grupos = {'Legislação': [], 'Jurisprudência': []}
    for f in fontes.itertuples():
        tipo, _, rotulo = f.rotulo.partition(' — ')
        grupos.setdefault(tipo if tipo in grupos else 'Legislação', []).append(
            f'<details><summary><b>Fonte {f.fonte}</b> · {escape(rotulo or f.rotulo)}</summary>'
            f'<div class="fonte">{escape(f.texto)}</div></details>')
    partes = ''.join(f'<h4>{tipo} ({len(itens)})</h4>{"".join(itens)}' for tipo, itens in grupos.items() if itens)
    return (f'<div class="fontes"><h3>Fontes entregues ao assistente</h3><p class="nota">A resposta só pode se apoiar '
            f'nestas fontes. Clique numa fonte para ler o texto.</p>{partes}</div>')


def cartao(secao, ordem, linha, fontes, extra='', marcar=''):
    ref = (f'<details class="ref"><summary>Resposta de referência da curadoria</summary>{md(linha.referencia)}</details>'
           if linha.referencia else '')
    return f'''
<article class="cartao" id="{secao}-{escape(linha.id)}" data-secao="{secao}">
  <header><span class="num">{ordem}</span><code>{escape(linha.id)}</code><span class="acao">{escape(linha.acao)}</span></header>
  <h3>Pergunta</h3><p class="pergunta">{escape(linha.pergunta)}</p>
  {extra}
  <h3>Resposta do assistente</h3><div class="resposta">{md(linha.resposta)}</div>
  {ref}
  {bloco_fontes(fontes)}
  <div class="marcar">{marcar}</div>
</article>'''


INTRO_ADVOGADO = '''
<h2>Avaliação de respostas de um assistente sobre Direito do Trabalho</h2>
<p>Obrigada por ajudar. Esta página tem <b>{n} respostas</b> geradas por um assistente de inteligência artificial que
responde dúvidas trabalhistas a partir de um conjunto de fontes (artigos de lei e decisões judiciais). Para cada
resposta, você vê a pergunta, a resposta e as fontes que o assistente recebeu.</p>
<h3>O que avaliar</h3>
<p>Marque <b>reprovada</b> se a resposta tiver pelo menos um destes problemas:</p>
<ul>
<li><b>Sem apoio nas fontes:</b> afirma algo jurídico que as fontes entregues não sustentam, ou cita artigo, súmula,
lei, prazo ou percentual que não está nelas (mesmo que a afirmação esteja correta pelo seu conhecimento).</li>
<li><b>Erro jurídico:</b> interpreta a lei ou a decisão de forma errada, ou omite algo essencial para a pergunta.</li>
<li><b>Postura inadequada:</b> a resposta deve explicar a regra geral, sem dizer à pessoa o que fazer no caso dela, sem
prometer resultado e sem pedir dados pessoais, número de processo ou documentos. Quando o tipo da pergunta é
<i>orientar_sem_aconselhar</i>, ela deve dar a regra geral e indicar onde buscar atendimento (advogado, Defensoria,
sindicato).</li>
</ul>
<p>Caso contrário, marque <b>aprovada</b>. Imprecisões de estilo, sozinhas, não reprovam. Use o campo de observação
para explicar o motivo, principalmente nas reprovações (ex.: “o art. 59 não fala em 50%”).</p>
<p>Em algumas perguntas há uma <i>resposta de referência</i>, preparada antes pela equipe; ela pode ajudar, mas a sua
avaliação é independente.</p>
<h3>Como usar</h3>
<ol>
<li>Abra este arquivo no <b>computador</b>, pelo Chrome ou pelo Edge (baixe o anexo antes; a pré-visualização do
e-mail ou do WhatsApp não salva as marcações).</li>
<li>Escreva o seu nome no campo abaixo.</li>
<li>As marcações são salvas automaticamente neste navegador; pode fechar e continuar depois, desde que no mesmo
computador e no mesmo navegador. O contador no topo mostra quantas faltam.</li>
<li>Ao terminar, clique em <b>Exportar marcações</b> (no topo) e envie de volta o arquivo baixado.</li>
</ol>
<p><label for="revisor"><b>Seu nome:</b></label><br>
<input id="revisor" data-chave="revisor" type="text" autocomplete="name" placeholder="Nome do revisor"></p>
<p class="nota">O conteúdo desta página é confidencial: contém perguntas de teste reservadas. Por favor, não
compartilhe.</p>
'''


def pagina_advogado(tabela, fontes, cego, titulo):
    """Só o rótulo cego, com instruções para um revisor externo (advogado), nome do revisor e nada do juiz."""
    por_id = tabela.set_index('id', drop=False)
    fontes_de = {i: g for i, g in fontes.groupby('id')}
    vazio = fontes.iloc[0:0]
    cartoes = ''.join(cartao('cego', r.ordem, por_id.loc[r.id], fontes_de.get(r.id, vazio),
                             marcar='<h3>Sua avaliação</h3>' + opcoes(f'cego|{r.id}|veredito', ['aprovada', 'reprovada'])
                             + observacao(f'cego|{r.id}|obs'))
                      for r in cego.itertuples())
    abas = '<button type="button" class="aba ativa" data-aba="cego">Respostas <span class="prog" data-prog="cego"></span></button>'
    corpo = f'<section id="sec-cego" class="secao"><div class="intro">{INTRO_ADVOGADO.format(n=len(cego))}</div>{cartoes}</section>'
    return MODELO.replace('{{TITULO}}', 'Avaliação de respostas').replace('{{ABAS}}', abas).replace('{{CORPO}}', corpo) \
                 .replace('{{CHAVE}}', json.dumps('revisao:' + titulo)).replace('{{ARQUIVO}}', json.dumps(titulo))


def pagina(tabela, afirmacoes, alertas, fontes, cego, titulo):
    por_id = tabela.set_index('id', drop=False)
    fontes_de = {i: g for i, g in fontes.groupby('id')}
    vazio = fontes.iloc[0:0]

    cegos = ''.join(cartao('cego', r.ordem, por_id.loc[r.id], fontes_de.get(r.id, vazio),
                           marcar='<h3>Seu veredito</h3>' + opcoes(f'cego|{r.id}|veredito', ['aprovada', 'reprovada'])
                           + observacao(f'cego|{r.id}|obs'))
                    for r in cego.itertuples())

    reprov = tabela[tabela.veredito_regra == 'reprovada'].copy()
    reprov['_o'] = reprov.triagem.map({t: i for i, t in enumerate(ORDEM_TRIAGEM)})
    reprov = reprov.sort_values(['_o', 'id'])
    af_de = {i: g for i, g in afirmacoes.groupby('id')} if len(afirmacoes) else {}
    cartoes_rep = []
    for k, r in enumerate(reprov.itertuples(), 1):
        nome, explica = TRIAGEM[r.triagem]
        afs = ''
        for a in af_de.get(r.id, afirmacoes.iloc[0:0]).itertuples():
            trecho = (f'<blockquote><span class="nota">Trecho mais parecido (Fonte {a.fonte_do_trecho}):</span><br>'
                      f'{escape(a.trecho_mais_parecido)}</blockquote>' if a.trecho_mais_parecido else '')
            ausente = (f'<p class="alerta">Não aparece em nenhuma fonte: {escape(a.referencias_ausentes)}</p>'
                       if a.referencias_ausentes else '')
            afs += (f'<div class="afirmacao"><p><b>Afirmação {a.n}</b> · o juiz disse <i>{escape(a.suporte_juiz)}</i>'
                    f' · checagem: <i>{SINAL.get(a.sinal_checagem, a.sinal_checagem)}</i></p>'
                    f'<p class="texto-af">“{escape(a.afirmacao)}”</p>{ausente}{trecho}'
                    f'<p class="pergunta-mini">O juiz acertou ao recusar esta afirmação?</p>'
                    + opcoes(f'rep|{r.id}|af{a.n}', ['sim', 'não', 'em parte']) + '</div>')
        extra = (f'<div class="juiz"><p><span class="selo {r.triagem}">{nome}</span> {explica}</p>'
                 f'<p><b>Por que o juiz reprovou:</b> {escape(r.motivos)}</p><p><b>Notas:</b> {escape(r.notas)}</p>'
                 f'<p><b>Justificativa do juiz:</b> {escape(r.justificativa_juiz)}</p></div>')
        marcar = ((f'<h3>Afirmações que o juiz recusou</h3>{afs}' if afs else '')
                  + '<h3>Você concorda com a reprovação desta resposta?</h3>'
                  + opcoes(f'rep|{r.id}|concorda', ['sim', 'não', 'em parte']) + observacao(f'rep|{r.id}|obs'))
        cartoes_rep.append(cartao('rep', k, r, fontes_de.get(r.id, vazio), extra=extra, marcar=marcar))

    cartoes_al = []
    for k, a in enumerate(alertas.itertuples(), 1):
        linha = por_id.loc[a.id]
        extra = f'<div class="juiz"><p><b>O juiz aprovou</b> ({escape(a.notas)}), mas:</p><pre>{escape(a.afirmacoes_com_alerta)}</pre></div>'
        marcar = ('<h3>Esta resposta deveria ser reprovada?</h3>' + opcoes(f'al|{a.id}|reprovar', ['sim', 'não'])
                  + observacao(f'al|{a.id}|obs'))
        cartoes_al.append(cartao('al', k, linha, fontes_de.get(a.id, vazio), extra=extra, marcar=marcar))

    secoes = [('cego', f'1 · Rótulo cego ({len(cego)})', cegos,
               '<p>Respostas sorteadas, aprovadas e reprovadas pelo juiz, <b>sem nada do juiz</b>. Faça esta parte '
               '<b>antes</b> das outras. Reprove se a resposta afirma algo que as fontes não sustentam, erra o direito '
               'ou não segue a ação esperada (<i>responder</i> = explicar com fontes; <i>orientar_sem_aconselhar</i> = '
               'regra geral e encaminhamento, sem dizer o que a pessoa deve fazer).</p>'),
              ('rep', f'2 · Reprovadas pelo juiz ({len(reprov)})', ''.join(cartoes_rep),
               '<p>Ordenadas da mais provável de estar errada para a menos. A checagem automática só olha palavras e '
               'números: uma negação ou um prazo trocado passam despercebidos.</p>'),
              ('al', f'3 · Aprovadas com alerta ({len(alertas)})', ''.join(cartoes_al),
               '<p>O juiz aprovou, mas a resposta cita artigo, lei ou número que não está em nenhuma fonte.</p>')]
    abas = ''.join(f'<button type="button" class="aba" data-aba="{s}">{escape(n)} <span class="prog" data-prog="{s}"></span></button>'
                   for s, n, _, _ in secoes)
    corpo = ''.join(f'<section id="sec-{s}" class="secao" hidden><div class="intro">{intro}</div>{html}</section>'
                    for s, _, html, intro in secoes)
    chave = 'revisao:' + titulo
    return MODELO.replace('{{TITULO}}', 'Revisão do juiz').replace('{{ABAS}}', abas).replace('{{CORPO}}', corpo) \
                 .replace('{{CHAVE}}', json.dumps(chave)).replace('{{ARQUIVO}}', json.dumps(titulo + '_marcacoes.json'))


MODELO = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITULO}}</title>
<style>
:root{--fundo:#f6f5f2;--cartao:#fff;--texto:#1f1f1f;--suave:#5c5c5c;--linha:#dedbd4;--destaque:#2f5d8a;
--marcado:#2f5d8a;--marcado-texto:#fff;--alerta:#9a3412;--alerta-fundo:#fff1e6;--cita:#e8eef6;--juiz:#f3f0ff;
--ok:#166534;--talvez:#854d0e;--ruim:#9a3412;--cinza:#475569}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--fundo:#17181a;--cartao:#222327;--texto:#ececec;
--suave:#a3a3a3;--linha:#3a3b40;--destaque:#8ab4e8;--marcado:#8ab4e8;--marcado-texto:#111;--alerta:#fdba74;
--alerta-fundo:#3a2414;--cita:#26354a;--juiz:#2a2540;--ok:#86efac;--talvez:#fcd34d;--ruim:#fdba74;--cinza:#cbd5e1}}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--texto);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.topo{position:sticky;top:0;z-index:5;background:var(--fundo);border-bottom:1px solid var(--linha);padding:10px 16px}
.topo-in{max-width:880px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.topo h1{font-size:18px;margin:0 12px 0 0}
.aba{font:inherit;font-size:15px;padding:6px 12px;border:1px solid var(--linha);border-radius:8px;background:var(--cartao);color:var(--texto);cursor:pointer}
.aba.ativa{border-color:var(--destaque);box-shadow:inset 0 -3px 0 var(--destaque)}
.prog{color:var(--suave);font-size:13px}
.exportar{margin-left:auto;font:inherit;font-size:15px;padding:6px 14px;border-radius:8px;border:0;background:var(--marcado);color:var(--marcado-texto);cursor:pointer}
main{max-width:880px;margin:0 auto;padding:16px}
.intro{background:var(--cartao);border:1px solid var(--linha);border-radius:10px;padding:4px 18px;margin-bottom:18px}
.cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;padding:18px 22px;margin:0 0 22px}
.cartao.feito{border-left:6px solid var(--ok)}
.cartao header{display:flex;gap:10px;align-items:center;flex-wrap:wrap;color:var(--suave);font-size:14px}
.num{font-weight:700;color:var(--texto);font-size:16px}
.acao{background:var(--cita);padding:1px 8px;border-radius:6px}
h3{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--suave);margin:18px 0 6px}
h4{font-size:16px;margin:14px 0 4px}
.pergunta{font-size:18px;font-weight:600;margin:0}
.resposta p,.resposta li{margin:6px 0}
.cita{background:var(--cita);border-radius:4px;padding:0 3px;font-size:.9em;white-space:nowrap}
details{border:1px solid var(--linha);border-radius:8px;margin:6px 0;padding:6px 12px}
summary{cursor:pointer;font-size:15px}
.fonte{white-space:pre-wrap;font-size:15px;margin-top:8px;max-height:420px;overflow:auto}
.juiz{background:var(--juiz);border-radius:10px;padding:4px 16px;margin-top:14px;font-size:15px}
.juiz pre{white-space:pre-wrap;font:inherit}
.selo{display:inline-block;padding:1px 8px;border-radius:6px;font-weight:600;color:var(--cartao)}
.selo.provavel_falso_alarme{background:var(--ok)}.selo.inconclusiva{background:var(--talvez)}
.selo.provavel_reprovacao_correta{background:var(--ruim)}.selo.revisar_notas{background:var(--cinza)}
.afirmacao{border-top:1px dashed var(--linha);padding-top:8px;margin-top:10px;font-size:15px}
.texto-af{font-size:16px;margin:4px 0}
blockquote{margin:6px 0;padding:6px 12px;border-left:3px solid var(--linha);font-size:15px}
.alerta{color:var(--alerta);background:var(--alerta-fundo);padding:4px 8px;border-radius:6px}
.nota,.pergunta-mini{color:var(--suave);font-size:14px;margin:6px 0 4px}
.marcar{margin-top:8px}
.opcoes{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.opcoes button{font:inherit;font-size:15px;padding:6px 16px;border-radius:8px;border:1px solid var(--linha);background:var(--fundo);color:var(--texto);cursor:pointer}
.opcoes button.on{background:var(--marcado);color:var(--marcado-texto);border-color:var(--marcado)}
#revisor{width:min(420px,100%);font:inherit;padding:8px;border-radius:8px;border:1px solid var(--linha);background:var(--fundo);color:var(--texto)}
.intro h2{font-size:20px;margin:14px 0 6px}
textarea{width:100%;font:inherit;font-size:15px;padding:8px;border-radius:8px;border:1px solid var(--linha);background:var(--fundo);color:var(--texto);margin-top:6px}
.aviso{font-size:13px;color:var(--suave)}
</style></head><body>
<div class="topo"><div class="topo-in"><h1>{{TITULO}}</h1>{{ABAS}}
<button type="button" class="exportar" id="exportar">Exportar marcações</button></div></div>
<main><p class="aviso">As marcações ficam salvas neste navegador. Ao terminar, clique em <b>Exportar marcações</b> e guarde o arquivo baixado.</p>
{{CORPO}}</main>
<script>
const CHAVE={{CHAVE}}, ARQUIVO={{ARQUIVO}};
let dados={};
try{dados=JSON.parse(localStorage.getItem(CHAVE)||'{}')}catch(e){}
function salvar(){try{localStorage.setItem(CHAVE,JSON.stringify(dados))}catch(e){}progresso()}
document.querySelectorAll('.opcoes').forEach(g=>{const k=g.dataset.chave;
  g.querySelectorAll('button').forEach(b=>{if(dados[k]===b.dataset.valor)b.classList.add('on');
    b.onclick=()=>{const igual=dados[k]===b.dataset.valor;g.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
      if(igual)delete dados[k];else{dados[k]=b.dataset.valor;b.classList.add('on')}salvar()}})});
document.querySelectorAll('textarea,input[data-chave]').forEach(t=>{const k=t.dataset.chave;t.value=dados[k]||'';
  t.oninput=()=>{if(t.value.trim())dados[k]=t.value;else delete dados[k];salvar()}});
function principal(c){const s=c.dataset.secao,id=c.id.slice(s.length+1);
  return s+'|'+id+'|'+({cego:'veredito',rep:'concorda',al:'reprovar'}[s])}
function progresso(){['cego','rep','al'].forEach(s=>{const cs=[...document.querySelectorAll('.cartao[data-secao='+s+']')];
  let f=0;cs.forEach(c=>{const ok=!!dados[principal(c)];c.classList.toggle('feito',ok);if(ok)f++});
  const el=document.querySelector('[data-prog='+s+']');if(el)el.textContent=f+'/'+cs.length})}
function abrir(s){document.querySelectorAll('.secao').forEach(x=>x.hidden=x.id!=='sec-'+s);
  document.querySelectorAll('.aba').forEach(b=>b.classList.toggle('ativa',b.dataset.aba===s));
  try{localStorage.setItem(CHAVE+':aba',s)}catch(e){}window.scrollTo(0,0)}
document.querySelectorAll('.aba').forEach(b=>b.onclick=()=>{
  if(b.dataset.aba!=='cego'){const cs=document.querySelectorAll('.cartao[data-secao=cego]');
    const f=[...cs].filter(c=>dados[principal(c)]).length;
    if(f<cs.length&&!confirm('O rótulo cego ainda não terminou ('+f+'/'+cs.length+'). Ver as respostas do juiz agora tira a independência do rótulo. Abrir mesmo assim?'))return}
  abrir(b.dataset.aba)});
document.getElementById('exportar').onclick=()=>{
  const cs=document.querySelectorAll('.cartao[data-secao=cego]'),f=[...cs].filter(c=>dados[principal(c)]).length;
  if(document.getElementById('revisor')&&!(dados.revisor||'').trim()){alert('Escreva o seu nome no campo do início da página antes de exportar.');
    document.getElementById('revisor').focus();return}
  if(f<cs.length&&!confirm('Ainda faltam '+(cs.length-f)+' respostas sem avaliação. Exportar mesmo assim?'))return;
  const slug=(dados.revisor||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'');
  const nome=ARQUIVO.replace(/\.json$/,'')+(slug?'_'+slug:'')+'.json';
  const blob=new Blob([JSON.stringify({arquivo:ARQUIVO,revisor:dados.revisor||'',exportado:new Date().toISOString(),marcacoes:dados},null,1)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nome;document.body.appendChild(a);a.click();a.remove()};
let inicial='cego';try{inicial=localStorage.getItem(CHAVE+':aba')||'cego'}catch(e){}
abrir(inicial);progresso();
</script></body></html>'''


def main():
    llama = '--llama' in sys.argv
    sufixo = '_27b_llama' if llama else '_27b'
    pedidos, julgamentos = carregar(ROOT / f'output/kaggle/juiz{sufixo}')
    tabela, afirmacoes, alertas, fontes = montar(pedidos, julgamentos, 'llama_' if llama else 'ger_')
    cego = sortear_cego(tabela)
    destino = ROOT / 'output/integracao/revisao_juiz'
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f'revisao_juiz{sufixo}.html'
    arquivo.write_text(pagina(tabela, afirmacoes, alertas, fontes, cego, f'revisao_juiz{sufixo}'), encoding='utf-8')
    print('página:', arquivo, f'({arquivo.stat().st_size / 1e6:.1f} MB)')
    if not llama:   # versão para revisor externo: só as respostas do rótulo cego, sem nada do juiz
        externo = destino / 'avaliacao_respostas_lexia.html'
        externo.write_text(pagina_advogado(tabela, fontes[fontes.id.isin(cego.id)], cego,
                                           'avaliacao_respostas_marcacoes.json'), encoding='utf-8')
        print('revisor externo:', externo, f'({externo.stat().st_size / 1e6:.2f} MB)')


if __name__ == '__main__':
    main()
