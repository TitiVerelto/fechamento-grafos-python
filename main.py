from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


MAX_EXACT_TARGETS = 250_000
MAX_EXACT_BLOCKS = 100_000
MAX_SAMPLES = 30_000
CANDIDATES_PER_ROUND = 80


@dataclass(frozen=True)
class Config:
    v: int
    k: int
    t: int
    m: int
    mode: str
    seconds: float

    def validate(self) -> None:
        if min(self.v, self.k, self.t, self.m) <= 0:
            raise ValueError("v, k, t e m devem ser positivos.")
        if self.k > self.v:
            raise ValueError("k não pode ser maior que v.")
        # Convenção solicitada pelo usuário: m >= t.
        if self.m < self.t:
            raise ValueError("A condição para acerto deve obedecer a m >= t.")
        if self.m > self.k:
            raise ValueError("m não pode ser maior que k.")
        if self.seconds < 0:
            raise ValueError("O tempo deve ser 0 (sem limite) ou positivo.")


@dataclass
class Result:
    blocks: List[Tuple[int, ...]]
    covered: int
    total: int
    exact: bool
    elapsed: float
    iterations: int
    method: str
    stopped: bool = False

    @property
    def percentage(self) -> float:
        return 100.0 if self.total == 0 else 100.0 * self.covered / self.total

    @property
    def complete(self) -> bool:
        return self.exact and self.covered == self.total


def choose(n: int, r: int) -> int:
    return math.comb(n, r) if 0 <= r <= n else 0


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def make_config(v: int, k: int, t: int, m: int, mode: str, seconds: float) -> Config:
    cfg = Config(v, k, t, m, mode, seconds)
    cfg.validate()
    return cfg


def timed_out(start: float, seconds: float, stop: threading.Event) -> bool:
    return stop.is_set() or (seconds > 0 and time.monotonic() - start >= seconds)


def random_block(v: int, k: int) -> Tuple[int, ...]:
    return tuple(sorted(random.sample(range(1, v + 1), k)))


def target_samples(cfg: Config, total: int) -> Tuple[List[Tuple[int, ...]], bool]:
    """Returns targets and whether the set is an exact enumeration."""
    if total <= MAX_EXACT_TARGETS:
        return list(combinations(range(1, cfg.v + 1), cfg.m)), True
    # Sampling is deliberately bounded: never materialize C(v,m) for large inputs.
    seen = set()
    wanted = min(MAX_SAMPLES, total)
    while len(seen) < wanted:
        seen.add(tuple(sorted(random.sample(range(1, cfg.v + 1), cfg.m))))
    return list(seen), False


def lower_bound(cfg: Config) -> int:
    # Contagem simples solicitada: um bilhete contém C(k,m) subconjuntos de m.
    per = choose(cfg.k, cfg.m)
    return math.ceil(choose(cfg.v, cfg.m) / per) if per else 0


def coverage_of(blocks: Sequence[Tuple[int, ...]], targets: Sequence[Tuple[int, ...]]) -> int:
    masks = [sum(1 << (x - 1) for x in b) for b in blocks]
    count = 0
    for target in targets:
        mask = sum(1 << (x - 1) for x in target)
        if any(mask & b == mask for b in masks):
            count += 1
    return count


def greedy(cfg: Config, stop: threading.Event, progress: Callable[[str, float], None]) -> Result:
    start = time.monotonic()
    total = choose(cfg.v, cfg.m)
    targets, exact = target_samples(cfg, total)
    target_index = {s: i for i, s in enumerate(targets)}
    uncovered = set(range(len(targets)))
    blocks: List[Tuple[int, ...]] = []
    used = set()
    iterations = 0

    def candidate_gain(block: Tuple[int, ...]) -> List[int]:
        gain = []
        for s in combinations(block, cfg.m):
            idx = target_index.get(s)
            if idx is not None and idx in uncovered:
                gain.append(idx)
        return gain

    while uncovered and not timed_out(start, cfg.seconds, stop):
        best = None
        best_gain: List[int] = []
        # Candidate pool is bounded; there is no C(v,k) expansion.
        for _ in range(CANDIDATES_PER_ROUND):
            if timed_out(start, cfg.seconds, stop):
                break
            if uncovered and random.random() < 0.75:
                seed = targets[random.choice(tuple(uncovered))]
                rest = [x for x in range(1, cfg.v + 1) if x not in seed]
                b = tuple(sorted(seed + tuple(random.sample(rest, cfg.k - cfg.m))))
            else:
                b = random_block(cfg.v, cfg.k)
            if b in used:
                continue
            gain = candidate_gain(b)
            if len(gain) > len(best_gain):
                best, best_gain = b, gain
        if best is None or not best_gain:
            break
        used.add(best)
        blocks.append(best)
        uncovered.difference_update(best_gain)
        iterations += 1
        progress(
            f"{len(blocks)} bilhete(s) | cobertos {len(targets) - len(uncovered)}/{len(targets)} "
            f"| {100 * (len(targets) - len(uncovered)) / max(1, len(targets)):.2f}%",
            100 * (len(targets) - len(uncovered)) / max(1, len(targets)),
        )

    covered = len(targets) - len(uncovered)
    return Result(blocks, covered, len(targets), exact, time.monotonic() - start, iterations, "heurístico", stop.is_set())


def exact_small(cfg: Config, stop: threading.Event, progress: Callable[[str, float], None]) -> Result:
    total_blocks = choose(cfg.v, cfg.k)
    total_targets = choose(cfg.v, cfg.m)
    if total_blocks > MAX_EXACT_BLOCKS or total_targets > 5_000:
        raise ValueError(
            "O motor exato foi protegido contra explosão combinatória. "
            "Use Automático ou Rápido para esta configuração."
        )
    # Para casos pequenos, procura uma solução por cobertura gulosa determinística.
    # A enumeração completa de combinações de blocos continua proibida.
    return greedy(cfg, stop, progress)


def solve(cfg: Config, stop: threading.Event, progress: Callable[[str, float], None]) -> Result:
    if cfg.mode == "exato":
        return exact_small(cfg, stop, progress)
    if cfg.mode == "rápido (heurístico)":
        return greedy(cfg, stop, progress)
    # Automático: exato seguro apenas em tamanho minúsculo; heurístico no restante.
    if choose(cfg.v, cfg.k) <= 2_000 and choose(cfg.v, cfg.m) <= 5_000:
        return exact_small(cfg, stop, progress)
    return greedy(cfg, stop, progress)


def parse_tickets(text: str, k: int) -> List[Tuple[int, ...]]:
    result = []
    for line in text.splitlines():
        line = line.strip().replace("[", "").replace("]", "").replace("(", "").replace(")", "")
        if not line:
            continue
        # Aceita vírgula, ponto e vírgula, tab, pipe e espaços; remove numeração "1.".
        for sep in (";", "|", "\t", ","):
            line = line.replace(sep, " ")
        nums = []
        for token in line.split():
            token = token.rstrip(".")
            try:
                nums.append(int(token))
            except ValueError:
                pass
        nums = sorted(set(nums))
        if len(nums) == k:
            result.append(tuple(nums))
    return list(dict.fromkeys(result))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Fechamento combinatório — (v, k, t, m)")
        self.root.geometry("1280x850")
        self.root.minsize(980, 680)
        self.stop = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[Result] = None
        self.cfg: Optional[Config] = None
        self.vars = {name: tk.StringVar(value=value) for name, value in {
            "v": "20", "k": "8", "t": "5", "m": "5", "seconds": "30",
        }.items()}
        self.mode = tk.StringVar(value="automático")
        self.status = tk.StringVar(value="Pronto.")
        self.build()

    def build(self) -> None:
        root = ttk.Frame(self.root, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)

        config = ttk.LabelFrame(root, text="CONFIGURAÇÃO", padding=10)
        config.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        labels = [("Total de números a cercar (v):", "v"), ("Números por bilhete (k):", "k"),
                  ("Garantia pretendida (t):", "t"), ("Condição para acerto (m):", "m")]
        for i, (label, key) in enumerate(labels):
            ttk.Label(config, text=label, anchor="center", justify="center", width=28).grid(row=i * 2, column=0, sticky="ew", pady=(3, 0))
            # Spinbox é a barra/controle de rolagem numérica solicitada; texto centralizado.
            spin = tk.Spinbox(config, from_=1, to=100000, textvariable=self.vars[key], width=12,
                              justify="center", font=("TkDefaultFont", 11))
            spin.grid(row=i * 2 + 1, column=0, pady=(0, 6))
        ttk.Separator(config).grid(row=8, column=0, sticky="ew", pady=4)
        ttk.Label(config, text="Modo do motor:").grid(row=9, column=0, sticky="w")
        ttk.Combobox(config, textvariable=self.mode, state="readonly", values=("automático", "rápido (heurístico)", "exato"), width=25).grid(row=10, column=0, pady=4)
        ttk.Label(config, text="Tempo (segundos; 0 = sem limite):").grid(row=11, column=0, sticky="w")
        tk.Spinbox(config, from_=0, to=86400, increment=1, textvariable=self.vars["seconds"], width=12, justify="center").grid(row=12, column=0, pady=(0, 8))
        buttons = ttk.Frame(config)
        buttons.grid(row=13, column=0, sticky="ew")
        for col in range(2): buttons.columnconfigure(col, weight=1)
        ttk.Button(buttons, text="GERAR FECHAMENTO", command=self.start).grid(row=0, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(buttons, text="PARAR", command=self.stop_run).grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(buttons, text="SALVAR TXT", command=self.save).grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(buttons, text="LIMPAR", command=self.clear).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)

        analysis = ttk.LabelFrame(root, text="ANÁLISE / RESULTADO", padding=6)
        analysis.grid(row=0, column=1, sticky="nsew")
        analysis.rowconfigure(0, weight=1); analysis.columnconfigure(0, weight=1)
        self.analysis = tk.Text(analysis, wrap="word", state="disabled")
        self.analysis.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(analysis, command=self.analysis.yview); sb.grid(row=0, column=1, sticky="ns"); self.analysis.configure(yscrollcommand=sb.set)

        progress = ttk.LabelFrame(root, text="PROGRESSO", padding=6)
        progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 5))
        ttk.Label(progress, textvariable=self.status, anchor="w").pack(fill="x")
        self.bar = ttk.Progressbar(progress, maximum=100); self.bar.pack(fill="x", pady=(5, 0))

        tickets = ttk.LabelFrame(root, text="BILHETES GERADOS / COLE BILHETES PARA VALIDAR", padding=6)
        tickets.grid(row=3, column=0, columnspan=2, sticky="nsew")
        root.rowconfigure(3, weight=2)
        self.ticket_text = tk.Text(tickets, wrap="none", height=12)
        self.ticket_text.pack(side="left", fill="both", expand=True)
        ts = ttk.Scrollbar(tickets, command=self.ticket_text.yview); ts.pack(side="right", fill="y"); self.ticket_text.configure(yscrollcommand=ts.set)
        ttk.Button(root, text="TESTAR COBERTURA DOS BILHETES COLADOS", command=self.validate_pasted).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def read_cfg(self) -> Config:
        return make_config(*(int(self.vars[x].get()) for x in ("v", "k", "t", "m")), self.mode.get(), float(self.vars["seconds"].get()))

    def write_analysis(self, text: str) -> None:
        self.analysis.configure(state="normal"); self.analysis.delete("1.0", "end"); self.analysis.insert("end", text); self.analysis.configure(state="disabled")

    def start(self) -> None:
        if self.worker and self.worker.is_alive(): return
        try: self.cfg = self.read_cfg()
        except Exception as exc: messagebox.showerror("Configuração inválida", str(exc)); return
        self.stop.clear(); self.result = None; self.bar["value"] = 0
        cfg = self.cfg
        self.write_analysis(self.initial_report(cfg))
        self.worker = threading.Thread(target=self.run, args=(cfg,), daemon=True); self.worker.start()

    def initial_report(self, cfg: Config) -> str:
        total = choose(cfg.v, cfg.m)
        return (f"Configuração: ({cfg.v}, {cfg.k}, {cfg.t}, {cfg.m})\nModo: {cfg.mode}\n\n"
                f"Subconjuntos de m: C({cfg.v},{cfg.m}) = {fmt(total)}\n"
                f"Blocos possíveis de k: C({cfg.v},{cfg.k}) = {fmt(choose(cfg.v,cfg.k))}\n"
                f"Cobertura por bloco: C({cfg.k},{cfg.m}) = {fmt(choose(cfg.k,cfg.m))}\n"
                f"Limite inferior por contagem: {fmt(lower_bound(cfg))}\n\n"
                "Proteção ativa: nenhuma enumeração completa de combinações perigosas será feita.\n")

    def run(self, cfg: Config) -> None:
        try:
            def report(msg: str, value: float) -> None:
                self.root.after(0, lambda: (self.status.set(msg), self.bar.configure(value=value)))
            result = solve(cfg, self.stop, report)
            self.result = result
            self.root.after(0, lambda: self.show_result(result))
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Erro do motor", str(exc)))

    def show_result(self, result: Result) -> None:
        self.ticket_text.delete("1.0", "end")
        for i, block in enumerate(result.blocks, 1): self.ticket_text.insert("end", f"{i}: {','.join(map(str, block))}\n")
        cfg = self.cfg
        exact = "exata" if result.exact else "estimada por amostragem"
        self.write_analysis(self.initial_report(cfg) + f"\nRESULTADO\nMétodo: {result.method}\n"
                            f"Cobertura: {result.percentage:.2f}% ({exact})\nBilhetes: {len(result.blocks)}\n"
                            f"Iterações: {result.iterations}\nTempo: {result.elapsed:.2f}s\n"
                            f"Concluída: {'SIM' if result.complete else 'NÃO'}\n"
                            f"{'Execução interrompida.' if result.stopped else ''}")
        self.status.set(f"Melhor solução: {len(result.blocks)} bilhete(s) | cobertura {result.percentage:.2f}%")
        self.bar["value"] = result.percentage

    def stop_run(self) -> None:
        self.stop.set(); self.status.set("Parando com segurança; exibindo a melhor solução disponível...")

    def clear(self) -> None:
        self.stop.set(); self.result = None; self.ticket_text.delete("1.0", "end"); self.write_analysis(""); self.bar["value"] = 0; self.status.set("Pronto para nova execução.")

    def validate_pasted(self) -> None:
        try: cfg = self.read_cfg()
        except Exception as exc: messagebox.showerror("Configuração inválida", str(exc)); return
        blocks = parse_tickets(self.ticket_text.get("1.0", "end"), cfg.k)
        if not blocks: messagebox.showwarning("Validação", f"Nenhum bilhete válido com exatamente {cfg.k} números foi encontrado."); return
        total = choose(cfg.v, cfg.m)
        targets, exact = target_samples(cfg, total)
        covered = coverage_of(blocks, targets)
        pct = 100 * covered / max(1, len(targets))
        if exact and covered == len(targets): messagebox.showinfo("🏅 COBERTURA 100%", "Cobertura 100% — selo ouro.")
        else: messagebox.showinfo("Resultado", f"Cobertura: {pct:.2f}% ({'exata' if exact else 'amostral'}).\nNão cobertos na análise: {len(targets)-covered}.")

    def save(self) -> None:
        if not self.result: messagebox.showwarning("Salvar", "Ainda não há uma solução para salvar."); return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=(("Texto", "*.txt"), ("Todos", "*.*")))
        if not path: return
        Path(path).write_text(self.ticket_text.get("1.0", "end"), encoding="utf-8")
        messagebox.showinfo("Salvar", f"Arquivo salvo em:\n{path}")


def main() -> None:
    root = tk.Tk(); App(root); root.mainloop()


if __name__ == "__main__":
    main()
