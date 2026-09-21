from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Limites de segurança: o programa nunca cria C(v,m) gigantesco na memória.
MAX_EXACT_TARGETS = 250_000
CANDIDATES_PER_ROUND = 120


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
        if self.m > self.v:
            raise ValueError("m não pode ser maior que v.")
        # Definição: resultado tem m números e a garantia é t acertos.
        if self.m < self.t:
            raise ValueError("A configuração exige m >= t.")
        if self.k < self.t:
            raise ValueError("Cada bilhete deve ter k >= t.")
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
    stopped: bool
    uncovered_examples: List[Tuple[int, ...]]

    @property
    def percentage(self) -> float:
        return 100.0 if not self.total else 100.0 * self.covered / self.total

    @property
    def complete(self) -> bool:
        return self.exact and self.covered == self.total


def choose(n: int, r: int) -> int:
    return math.comb(n, r) if 0 <= r <= n else 0


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_block(block: Sequence[int]) -> str:
    return ",".join(str(x) for x in block)


def coverage_per_ticket(cfg: Config) -> int:
    """Quantidade exata de resultados de m cobertos por um bilhete de k."""
    return sum(
        choose(cfg.k, i) * choose(cfg.v - cfg.k, cfg.m - i)
        for i in range(cfg.t, min(cfg.k, cfg.m) + 1)
    )


def counting_lower_bound(cfg: Config) -> int:
    per = coverage_per_ticket(cfg)
    return math.ceil(choose(cfg.v, cfg.m) / per) if per else 0


def as_mask(block: Sequence[int]) -> int:
    result = 0
    for number in block:
        result |= 1 << (number - 1)
    return result


def covers(block_mask: int, target_mask: int, t: int) -> bool:
    return (block_mask & target_mask).bit_count() >= t


def timed_out(start: float, seconds: float, stop: threading.Event) -> bool:
    return stop.is_set() or (seconds > 0 and time.monotonic() - start >= seconds)


def make_targets(cfg: Config) -> Tuple[List[Tuple[int, ...]], bool]:
    total = choose(cfg.v, cfg.m)
    if total <= MAX_EXACT_TARGETS:
        return list(combinations(range(1, cfg.v + 1), cfg.m)), True

    # Amostra fixa e limitada para configurações grandes. Isso evita travar o PC.
    sample_size = min(30_000, total)
    targets = set()
    while len(targets) < sample_size:
        targets.add(tuple(sorted(random.sample(range(1, cfg.v + 1), cfg.m))))
    return list(targets), False


def candidate_gain(block: Tuple[int, ...], block_mask: int,
                   target_masks: Sequence[int], uncovered: set[int], t: int) -> List[int]:
    return [i for i in uncovered if covers(block_mask, target_masks[i], t)]


def greedy_cover(cfg: Config, stop: threading.Event,
                 progress: Callable[[str, float], None]) -> Result:
    """Resolve o covering set no universo exato ou na amostra segura."""
    started = time.monotonic()
    targets, exact = make_targets(cfg)
    target_masks = [as_mask(target) for target in targets]
    uncovered = set(range(len(targets)))
    blocks: List[Tuple[int, ...]] = []
    block_masks = set()
    iterations = 0

    while uncovered and not timed_out(started, cfg.seconds, stop):
        best_block: Optional[Tuple[int, ...]] = None
        best_mask = 0
        best_gain: List[int] = []

        # Cada candidato nasce de um resultado ainda não coberto. Assim,
        # o motor constrói bilhetes que realmente cobrem resultados.
        available_uncovered = tuple(uncovered)
        for _ in range(CANDIDATES_PER_ROUND):
            if timed_out(started, cfg.seconds, stop):
                break
            seed_target = targets[random.choice(available_uncovered)]
            remaining = [x for x in range(1, cfg.v + 1) if x not in seed_target]
            extra = random.sample(remaining, cfg.k - cfg.t)
            block = tuple(sorted(set(seed_target[:cfg.t]) | set(extra)))
            if len(block) != cfg.k:
                continue
            block_mask = as_mask(block)
            if block_mask in block_masks:
                continue
            gain = candidate_gain(block, block_mask, target_masks, uncovered, cfg.t)
            if len(gain) > len(best_gain):
                best_block, best_mask, best_gain = block, block_mask, gain

        if best_block is None or not best_gain:
            break
        blocks.append(best_block)
        block_masks.add(best_mask)
        uncovered.difference_update(best_gain)
        iterations += 1
        covered_count = len(targets) - len(uncovered)
        percent = 100.0 * covered_count / max(1, len(targets))
        progress(
            f"{len(blocks)} bilhete(s) | {covered_count}/{len(targets)} resultados "
            f"cobertos | {percent:.2f}%", percent)

    elapsed = time.monotonic() - started
    uncovered_examples = [targets[i] for i in list(uncovered)[:100]]
    return Result(blocks, len(targets) - len(uncovered), len(targets), exact,
                  elapsed, iterations, "cobertura gulosa", stop.is_set(), uncovered_examples)


def solve(cfg: Config, stop: threading.Event,
          progress: Callable[[str, float], None]) -> Result:
    # Uma busca exaustiva por coleções de blocos é impraticável mesmo para
    # tamanhos moderados. O motor abaixo é uma heurística de set-cover real:
    # cada bilhete é escolhido pelo ganho de cobertura |B∩M| >= t.
    return greedy_cover(cfg, stop, progress)


def parse_tickets(text: str, k: int) -> Tuple[List[Tuple[int, ...]], int]:
    valid: List[Tuple[int, ...]] = []
    ignored = 0
    for line in text.splitlines():
        line = line.strip().replace("[", "").replace("]", "").replace("(", "").replace(")", "")
        if not line:
            continue
        for sep in (";", "|", "\t", ","):
            line = line.replace(sep, " ")
        values = []
        for token in line.split():
            token = token.rstrip(".")
            try:
                values.append(int(token))
            except ValueError:
                pass
        values = sorted(set(values))
        if len(values) == k:
            valid.append(tuple(values))
        else:
            ignored += 1
    return list(dict.fromkeys(valid)), ignored


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Fechamento combinatório — (v, k, t, m)")
        self.root.geometry("1280x850")
        self.root.minsize(980, 680)
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.config: Optional[Config] = None
        self.result: Optional[Result] = None
        self.values = {key: tk.StringVar(value=value) for key, value in {
            "v": "20", "k": "8", "t": "5", "m": "5", "seconds": "30"
        }.items()}
        self.mode = tk.StringVar(value="automático")
        self.status = tk.StringVar(value="Pronto.")
        self.build_ui()

    def build_ui(self) -> None:
        root = ttk.Frame(self.root, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=0)
        root.rowconfigure(2, weight=2)

        config = ttk.LabelFrame(root, text="CONFIGURAÇÃO", padding=10)
        config.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        config.columnconfigure(1, weight=1)
        fields = [("Total de números a cercar (v) :", "v"),
                  ("Números por bilhete (k) :", "k"),
                  ("Garantia pretendida (t) :", "t"),
                  ("Condição para acerto (m) :", "m")]
        for row, (label, key) in enumerate(fields):
            ttk.Label(config, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=5)
            spin = tk.Spinbox(config, from_=1, to=100000, textvariable=self.values[key],
                              width=10, justify="center")
            spin.grid(row=row, column=1, sticky="e", padx=(10, 0), pady=5)

        ttk.Label(config, text="Modo do motor:").grid(row=4, column=0, sticky="w", pady=(15, 5))
        ttk.Combobox(config, textvariable=self.mode, state="readonly",
                     values=("automático", "rápido (heurístico)"), width=21).grid(row=4, column=1, sticky="e", pady=(15, 5))
        ttk.Label(config, text="Tempo (0 = sem limite):").grid(row=5, column=0, sticky="w", pady=5)
        tk.Spinbox(config, from_=0, to=86400, textvariable=self.values["seconds"],
                   width=10, justify="center").grid(row=5, column=1, sticky="e", pady=5)

        buttons = ttk.Frame(config)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(15, 0))
        buttons.columnconfigure(0, weight=1); buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="GERAR FECHAMENTO", command=self.start).grid(row=0, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(buttons, text="PARAR", command=self.stop).grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(buttons, text="SALVAR TXT", command=self.save).grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(buttons, text="LIMPAR", command=self.clear).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)

        analysis = ttk.LabelFrame(root, text="ANÁLISE / RESULTADO", padding=6)
        analysis.grid(row=0, column=1, sticky="nsew")
        analysis.rowconfigure(0, weight=1); analysis.columnconfigure(0, weight=1)
        self.analysis = tk.Text(analysis, wrap="word", state="disabled")
        self.analysis.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(analysis, command=self.analysis.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.analysis.configure(yscrollcommand=scrollbar.set)

        progress = ttk.LabelFrame(root, text="PROGRESSO", padding=6)
        progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 5))
        ttk.Label(progress, textvariable=self.status, anchor="w").pack(fill="x")
        self.progress_bar = ttk.Progressbar(progress, maximum=100)
        self.progress_bar.pack(fill="x", pady=(5, 0))

        tickets = ttk.LabelFrame(root, text="BILHETES GERADOS / COLAR JOGOS PARA VALIDAÇÃO", padding=6)
        tickets.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.ticket_text = tk.Text(tickets, wrap="none")
        self.ticket_text.pack(side="left", fill="both", expand=True)
        ticket_scroll = ttk.Scrollbar(tickets, command=self.ticket_text.yview)
        ticket_scroll.pack(side="right", fill="y")
        self.ticket_text.configure(yscrollcommand=ticket_scroll.set)
        ttk.Button(root, text="VALIDAR JOGOS", command=self.validate_games).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def read_config(self) -> Config:
        cfg = Config(*(int(self.values[x].get()) for x in ("v", "k", "t", "m")),
                     self.mode.get(), float(self.values["seconds"].get()))
        cfg.validate()
        return cfg

    def report_text(self, cfg: Config) -> str:
        total = choose(cfg.v, cfg.m)
        per_ticket = coverage_per_ticket(cfg)
        return (f"CONFIGURAÇÃO DO FECHAMENTO\n(v, k, t, m) = ({cfg.v}, {cfg.k}, {cfg.t}, {cfg.m})\n"
                f"Modo do motor: {cfg.mode}\n\nANÁLISE COMBINATÓRIA\n"
                f"Resultados possíveis de m: C({cfg.v},{cfg.m}) = {fmt(total)}\n"
                f"Blocos possíveis de k: C({cfg.v},{cfg.k}) = {fmt(choose(cfg.v,cfg.k))}\n"
                f"Cobertura por bilhete (|B ∩ M| >= t): {fmt(per_ticket)}\n"
                f"Limite inferior por contagem: {fmt(counting_lower_bound(cfg))}\n\n"
                "O motor seleciona bilhetes pelo ganho real de cobertura, isto é, pela condição |B ∩ M| >= t.\n")

    def set_analysis(self, text: str) -> None:
        self.analysis.configure(state="normal")
        self.analysis.delete("1.0", "end")
        self.analysis.insert("end", text)
        self.analysis.configure(state="disabled")

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            self.config = self.read_config()
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))
            return
        self.stop_event.clear()
        self.result = None
        self.progress_bar["value"] = 0
        self.set_analysis(self.report_text(self.config))
        self.worker = threading.Thread(target=self.run_engine, args=(self.config,), daemon=True)
        self.worker.start()

    def run_engine(self, cfg: Config) -> None:
        try:
            def progress(message: str, value: float) -> None:
                self.root.after(0, lambda: (self.status.set(message), self.progress_bar.configure(value=value)))
            result = solve(cfg, self.stop_event, progress)
            self.result = result
            self.root.after(0, lambda: self.show_result(result))
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Erro do motor", str(exc)))

    def show_result(self, result: Result) -> None:
        self.ticket_text.delete("1.0", "end")
        for index, block in enumerate(result.blocks, 1):
            self.ticket_text.insert("end", f"{index}: {format_block(block)}\n")
        cfg = self.config
        analysis = self.report_text(cfg) + (
            f"\nRESULTADO DO FECHAMENTO\nBilhetes gerados: {len(result.blocks)}\n"
            f"Garantia verificada: {result.percentage:.4f}%\n"
            f"Resultados cobertos: {fmt(result.covered)} de {fmt(result.total)}\n"
            f"Resultados não cobertos: {fmt(result.total - result.covered)}\n"
            f"Análise: {'EXATA' if result.exact else 'AMOSTRAL'}\n"
            f"Tempo: {result.elapsed:.2f} s\nIterações: {result.iterations}\n"
            f"{'Execução interrompida pelo usuário.' if result.stopped else ''}\n"
        )
        if result.uncovered_examples:
            analysis += "Exemplos não cobertos:\n" + "\n".join(format_block(x) for x in result.uncovered_examples[:20])
        self.set_analysis(analysis)
        self.progress_bar["value"] = result.percentage
        self.status.set(f"Melhor fechamento: {len(result.blocks)} bilhete(s) | garantia {result.percentage:.4f}%")

    def stop(self) -> None:
        self.stop_event.set()
        self.status.set("Parando com segurança...")

    def clear(self) -> None:
        self.stop_event.set()
        self.result = None
        self.ticket_text.delete("1.0", "end")
        self.set_analysis("")
        self.progress_bar["value"] = 0
        self.status.set("Pronto para nova execução.")

    def validate_games(self) -> None:
        try:
            cfg = self.read_config()
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))
            return
        blocks, ignored = parse_tickets(self.ticket_text.get("1.0", "end"), cfg.k)
        if not blocks:
            messagebox.showwarning("VALIDAR JOGOS", f"Nenhum jogo com exatamente k={cfg.k} números foi encontrado.")
            return
        targets, exact = make_targets(cfg)
        target_masks = [as_mask(target) for target in targets]
        block_masks = [as_mask(block) for block in blocks]
        uncovered = [target for target, target_mask in zip(targets, target_masks)
                     if not any(covers(block_mask, target_mask, cfg.t) for block_mask in block_masks)]
        covered = len(targets) - len(uncovered)
        percentage = 100.0 * covered / max(1, len(targets))

        text = self.report_text(cfg) + (
            f"\nVALIDAÇÃO DOS JOGOS COLADOS\nJogos válidos: {len(blocks)}\n"
            f"Linhas ignoradas: {ignored}\nGarantia existente: {percentage:.4f}%\n"
            f"Resultados cobertos: {fmt(covered)} de {fmt(len(targets))}\n"
            f"Resultados não cobertos: {fmt(len(uncovered))}\n"
            f"Tipo de verificação: {'EXATA' if exact else 'AMOSTRAL'}\n"
        )
        if uncovered:
            text += "\nExemplos de resultados não cobertos:\n" + "\n".join(format_block(x) for x in uncovered[:30])
        else:
            text += "\n🏅 SELO OURO — garantia de 100% na verificação realizada."
        self.set_analysis(text)
        self.status.set(f"Validação concluída: {percentage:.4f}% de garantia")

    def save(self) -> None:
        if not self.result:
            messagebox.showwarning("SALVAR TXT", "Ainda não há fechamento gerado para salvar.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=(("Texto", "*.txt"), ("Todos", "*.*")))
        if path:
            Path(path).write_text(self.ticket_text.get("1.0", "end"), encoding="utf-8")
            messagebox.showinfo("SALVAR TXT", f"Arquivo salvo em:\n{path}")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
