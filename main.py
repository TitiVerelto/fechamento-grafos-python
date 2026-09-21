from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, Optional

MAX_EXPLICIT_RESULTS = 120_000
MAX_EXPLICIT_BLOCKS = 120_000
IMPLICIT_SAMPLES = 25_000

@dataclass(frozen=True)
class Config:
    v: int; k: int; t: int; m: int; mode: str; seconds: float
    def validate(self):
        if min(self.v, self.k, self.t, self.m) <= 0: raise ValueError('v, k, t e m devem ser positivos.')
        if self.k > self.v or self.m > self.v: raise ValueError('k e m não podem ser maiores que v.')
        if self.t > self.k or self.t > self.m: raise ValueError('t deve ser menor ou igual a k e m.')
        if self.seconds < 0: raise ValueError('O tempo deve ser 0 ou positivo.')

@dataclass
class Result:
    blocks: list[tuple[int, ...]]; covered: int; total: int; exact: bool
    elapsed: float; rounds: int; stopped: bool; method: str; missing: list[tuple[int, ...]]
    @property
    def pct(self): return 100.0 * self.covered / self.total if self.total else 100.0
    @property
    def complete(self): return self.exact and self.covered == self.total

def C(n, r): return math.comb(n, r) if 0 <= r <= n else 0
def fmt(n): return f'{n:,}'.replace(',', '.')
def mask(xs):
    z = 0
    for x in xs: z |= 1 << (x - 1)
    return z
def intersects(b, r, t): return (b & r).bit_count() >= t
def stop_now(start, limit, event): return event.is_set() or (limit > 0 and time.monotonic() - start >= limit)
def ticket_coverage(c):
    lo = max(c.t, c.m - (c.v - c.k)); hi = min(c.k, c.m)
    return sum(C(c.k, i) * C(c.v-c.k, c.m-i) for i in range(lo, hi+1))
def lower_bound(c): return math.ceil(C(c.v,c.m) / ticket_coverage(c))
def fmt_ticket(i, b): return f'{i:05d}: ' + ' '.join(f'{x:02d}' for x in b)

def sample_results(c, exact=False):
    total = C(c.v, c.m)
    if exact:
        return list(combinations(range(1,c.v+1), c.m)), True
    n = min(IMPLICIT_SAMPLES, total); out=set()
    while len(out) < n: out.add(tuple(sorted(random.sample(range(1,c.v+1), c.m))))
    return list(out), False

def candidate_from_result(r, c):
    # A candidate contains t numbers of r, therefore it is incident to r.
    chosen = random.sample(r, c.t)
    rest = [x for x in range(1,c.v+1) if x not in chosen]
    return tuple(sorted(chosen + random.sample(rest, c.k-c.t)))

def evaluate(blocks, results, c):
    bm=[mask(b) for b in blocks]; covered=0; missing=[]
    for r in results:
        rm=mask(r)
        if any(intersects(b,rm,c.t) for b in bm): covered += 1
        elif len(missing)<100: missing.append(r)
    return covered, missing

def incidence(blocks, results, c):
    rms=[mask(r) for r in results]
    return [[i for i,r in enumerate(rms) if intersects(mask(b),r,c.t)] for b in blocks]

def reduce_solution(blocks, results, c, event, progress):
    # Bipartite graph reduction: degree 1 result vertices make a block essential.
    current=list(dict.fromkeys(blocks)); changed=True; removed=0
    while changed and not event.is_set():
        changed=False; adj=incidence(current, results, c)
        degrees=[0]*len(results)
        for ids in adj:
            for r in ids: degrees[r]+=1
        order=list(range(len(current))); random.shuffle(order)
        for i in order:
            if i >= len(current): continue
            if any(degrees[r] == 1 for r in adj[i]): continue
            trial=current[:i]+current[i+1:]
            ok,_=evaluate(trial,results,c)
            if ok == len(results):
                current=trial; removed+=1; changed=True
                progress(f'Exclusão aceita: -1 bilhete | atual {len(current)}', 0)
                break
    return current, removed

def construct(c, results, event, start, progress):
    rms=[mask(r) for r in results]; uncovered=(1<<len(results))-1; selected=[]; selected_set=set()
    # Explicit graph: candidates are all k-blocks. Implicit: candidate blocks are sampled.
    if c.mode == 'explícito':
        candidates=list(combinations(range(1,c.v+1), c.k))
    else: candidates=[]
    while uncovered and not stop_now(start,c.seconds,event):
        pool=candidates if candidates else [candidate_from_result(results[random.randrange(len(results))],c) for _ in range(160)]
        best=None; bestbits=0; bestgain=-1
        for b in pool:
            if b in selected_set: continue
            bm=mask(b); bits=0
            for i,rm in enumerate(rms):
                if uncovered & (1<<i) and intersects(bm,rm,c.t): bits |= 1<<i
            gain=bits.bit_count()
            if gain > bestgain: best,bestbits,bestgain=b,bits,gain
        if best is None or bestgain <= 0: break
        selected.append(best); selected_set.add(best); uncovered &= ~bestbits
        progress(f'Construção: {len(selected)} bilhetes | {len(results)-uncovered.bit_count()}/{len(results)} cobertos', 100*(len(results)-uncovered.bit_count())/len(results))
        if candidates: candidates.remove(best)
    return selected

def engine(c, event, progress):
    started=time.monotonic(); total=C(c.v,c.m)
    exact=(c.mode=='explícito')
    results, exact_results=sample_results(c, exact)
    best=None; best_cov=0; rounds=0; lower=lower_bound(c)
    while not stop_now(started,c.seconds,event):
        rounds += 1
        candidate=construct(c,results,event,started,progress)
        covered,missing=evaluate(candidate,results,c)
        if covered > best_cov: best_cov=covered
        # Only accept a candidate as the current best when it is fully valid
        # for the universe being analyzed.
        if covered == len(results):
            candidate,_=reduce_solution(candidate,results,c,event,progress)
            covered,missing=evaluate(candidate,results,c)
            if covered == len(results) and (best is None or len(candidate)<len(best)):
                best=list(candidate)
                progress(f'Rodada {rounds}: melhor solução válida = {len(best)}',100)
                if len(best) <= lower: break
        progress(f'Cascade rodada {rounds} | melhor cobertura {100*best_cov/len(results):.3f}% | melhor válida: {len(best) if best else "nenhuma"}',100*best_cov/len(results))
        # In implicit mode, an endless 0-limit run still needs a useful cycle;
        # it stops only by user or lower bound, as requested.
    if best is None:
        candidate=construct(c,results,event,started,progress); covered,missing=evaluate(candidate,results,c)
        best=candidate; best_cov=covered
    else: covered,missing=evaluate(best,results,c)
    return Result(best,covered,len(results),exact_results,time.monotonic()-started,rounds,event.is_set(),'Grafo bipartido + Cascade',missing)

def parse_games(text,k):
    out=[]; ignored=0
    for line in text.splitlines():
        if ':' in line: line=line.split(':',1)[1]
        for ch in '[](),;|\t': line=line.replace(ch,' ')
        try: nums=sorted(set(int(x.rstrip('.')) for x in line.split()))
        except ValueError: nums=[]
        if len(nums)==k: out.append(tuple(nums))
        elif line.strip(): ignored+=1
    return list(dict.fromkeys(out)),ignored

def validate_games(c,games):
    results,exact=sample_results(c,c.mode=='explícito'); covered,missing=evaluate(games,results,c)
    return covered,len(results),exact,missing

class App:
    def __init__(self,root):
        self.root=root; root.title('Fechamento combinatório (v,k,t,m)'); root.geometry('1320x880'); root.minsize(1000,700)
        self.stop_event=threading.Event(); self.worker=None; self.cfg=None; self.result=None
        self.v={x:tk.StringVar(value=y) for x,y in {'v':'20','k':'8','t':'5','m':'5','seconds':'30'}.items()}
        self.mode=tk.StringVar(value='implícito'); self.status=tk.StringVar(value='Pronto.'); self.build()
    def build(self):
        root=ttk.Frame(self.root,padding=10); root.pack(fill='both',expand=True); root.columnconfigure(1,weight=1); root.rowconfigure(0,weight=1); root.rowconfigure(2,weight=2)
        cf=ttk.LabelFrame(root,text='CONFIGURAÇÃO',padding=12); cf.grid(row=0,column=0,sticky='nsew',padx=(0,10)); cf.columnconfigure(1,weight=1)
        fields=[('Total de números a cercar (v) :','v'),('Números por bilhete (k)       :','k'),('Garantia pretendida (t)       :','t'),('Condição para acerto (m)      :','m')]
        for i,(label,key) in enumerate(fields):
            ttk.Label(cf,text=label).grid(row=i,column=0,sticky='w',pady=5); tk.Spinbox(cf,from_=1,to=100000,width=10,justify='center',textvariable=self.v[key]).grid(row=i,column=1,sticky='e',pady=5)
        ttk.Label(cf,text='Modo do motor:').grid(row=4,column=0,sticky='w',pady=(15,5)); ttk.Combobox(cf,textvariable=self.mode,state='readonly',values=('implícito','explícito'),width=17).grid(row=4,column=1,sticky='e',pady=(15,5))
        ttk.Label(cf,text='Tempo (0 = sem limite):').grid(row=5,column=0,sticky='w'); tk.Spinbox(cf,from_=0,to=86400,width=10,justify='center',textvariable=self.v['seconds']).grid(row=5,column=1,sticky='e')
        bf=ttk.Frame(cf); bf.grid(row=6,column=0,columnspan=2,sticky='ew',pady=(15,0)); bf.columnconfigure(0,weight=1); bf.columnconfigure(1,weight=1)
        ttk.Button(bf,text='GERAR FECHAMENTO',command=self.start).grid(row=0,column=0,columnspan=2,sticky='ew',pady=2); ttk.Button(bf,text='PARAR',command=self.stop).grid(row=1,column=0,sticky='ew',padx=(0,2)); ttk.Button(bf,text='SALVAR TXT',command=self.save).grid(row=1,column=1,sticky='ew',padx=(2,0)); ttk.Button(bf,text='LIMPAR',command=self.clear).grid(row=2,column=0,columnspan=2,sticky='ew',pady=2)
        af=ttk.LabelFrame(root,text='ANÁLISE / RESULTADO',padding=6); af.grid(row=0,column=1,sticky='nsew'); af.rowconfigure(0,weight=1); af.columnconfigure(0,weight=1); self.analysis=tk.Text(af,state='disabled',wrap='word'); self.analysis.grid(row=0,column=0,sticky='nsew'); s=ttk.Scrollbar(af,command=self.analysis.yview); s.grid(row=0,column=1,sticky='ns'); self.analysis.configure(yscrollcommand=s.set)
        pf=ttk.LabelFrame(root,text='PROGRESSO',padding=6); pf.grid(row=1,column=0,columnspan=2,sticky='ew',pady=6); ttk.Label(pf,textvariable=self.status).pack(fill='x'); self.bar=ttk.Progressbar(pf,maximum=100); self.bar.pack(fill='x')
        tf=ttk.LabelFrame(root,text='BILHETES GERADOS / COLAR JOGOS PARA VALIDAÇÃO',padding=6); tf.grid(row=2,column=0,columnspan=2,sticky='nsew'); self.tickets=tk.Text(tf,wrap='none'); self.tickets.pack(side='left',fill='both',expand=True); ts=ttk.Scrollbar(tf,command=self.tickets.yview); ts.pack(side='right',fill='y'); self.tickets.configure(yscrollcommand=ts.set); ttk.Button(root,text='VALIDAR JOGOS',command=self.validate).grid(row=3,column=0,columnspan=2,sticky='ew')
    def read(self):
        c=Config(*(int(self.v[x].get()) for x in ('v','k','t','m')),self.mode.get(),float(self.v['seconds'].get())); c.validate(); return c
    def set_analysis(self,s): self.analysis.config(state='normal'); self.analysis.delete('1.0','end'); self.analysis.insert('end',s); self.analysis.config(state='disabled')
    def report(self,c): return f'CONFIGURAÇÃO\n(v,k,t,m)=({c.v},{c.k},{c.t},{c.m})\nModo: {c.mode}\n\nRESULTADOS: C({c.v},{c.m}) = {fmt(C(c.v,c.m))}\nBLOCOS POSSÍVEIS: C({c.v},{c.k}) = {fmt(C(c.v,c.k))}\nCOBERTURA POR BILHETE: {fmt(ticket_coverage(c))}\nLIMITE INFERIOR POR CONTAGEM: {fmt(lower_bound(c))}\nREGRA: |bilhete ∩ resultado| >= t\n'
    def start(self):
        if self.worker and self.worker.is_alive(): return
        try: self.cfg=self.read()
        except Exception as e: messagebox.showerror('Configuração inválida',str(e)); return
        self.stop_event.clear(); self.result=None; self.bar['value']=0; self.set_analysis(self.report(self.cfg)); self.worker=threading.Thread(target=self.run,args=(self.cfg,),daemon=True); self.worker.start()
    def run(self,c):
        try:
            def p(msg,val): self.root.after(0,lambda:(self.status.set(msg),self.bar.configure(value=val)))
            r=engine(c,self.stop_event,p); self.result=r; self.root.after(0,lambda:self.show(r))
        except Exception as e: self.root.after(0,lambda:messagebox.showerror('Erro',str(e)))
    def show(self,r):
        self.tickets.delete('1.0','end')
        for i,b in enumerate(r.blocks,1): self.tickets.insert('end',fmt_ticket(i,b)+'\n')
        c=self.cfg; state='SIM' if r.complete else 'NÃO'; typ='EXATA' if r.exact else 'AMOSTRAL'
        self.set_analysis(self.report(c)+f'\nRESULTADO\nBilhetes: {len(r.blocks)}\nCobertos: {fmt(r.covered)} de {fmt(r.total)}\nNão cobertos: {fmt(r.total-r.covered)}\nGarantia: {r.pct:.4f}%\nFechamento completo: {state}\nValidação: {typ}\nRodadas Cascade: {r.rounds}\nTempo: {r.elapsed:.2f}s\n')
        self.status.set(f'Melhor solução: {len(r.blocks)} bilhete(s) | {r.pct:.4f}%'); self.bar['value']=r.pct
    def stop(self): self.stop_event.set(); self.status.set('Parando com segurança...')
    def clear(self): self.stop_event.set(); self.result=None; self.tickets.delete('1.0','end'); self.set_analysis(''); self.bar['value']=0; self.status.set('Pronto.')
    def validate(self):
        try: c=self.read(); games,ignored=parse_games(self.tickets.get('1.0','end'),c.k); 
        except Exception as e: messagebox.showerror('Configuração inválida',str(e)); return
        if not games: messagebox.showwarning('VALIDAR JOGOS',f'Nenhum jogo com exatamente k={c.k} números.'); return
        covered,total,exact,missing=validate_games(c,games); pct=100*covered/total; text=self.report(c)+f'\nVALIDAÇÃO DOS JOGOS\nJogos válidos: {len(games)}\nLinhas ignoradas: {ignored}\nCobertos: {fmt(covered)} de {fmt(total)}\nNão cobertos: {fmt(total-covered)}\nGarantia: {pct:.4f}%\nTipo: {"EXATA" if exact else "AMOSTRAL"}\n'
        if exact and covered==total: text+='\n🏅 SELO OURO — garantia de 100% confirmada.\n'
        else: text+='\nA garantia de 100% NÃO foi confirmada.\nExemplos não cobertos:\n'+'\n'.join(' '.join(f'{x:02d}' for x in q) for q in missing)
        self.set_analysis(text); self.status.set(f'Validação: {pct:.4f}%')
    def save(self):
        if not self.result: messagebox.showwarning('SALVAR TXT','Não há resultado para salvar.'); return
        p=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=(('Texto','*.txt'),('Todos','*.*')))
        if p: Path(p).write_text(self.tickets.get('1.0','end'),encoding='utf-8')

def main():
    root=tk.Tk(); App(root); root.mainloop()
if __name__=='__main__': main()
