# Fechamento combinatório (v, k, t, m)

Aplicação desktop em Python/Tkinter, sem dependências externas.

## Executar

```bash
python main.py
```

Python 3.9+ é recomendado. Tkinter normalmente já vem incluído no Python para Windows.

## Modelo utilizado

A aplicação valida `m >= t`, conforme a convenção solicitada. A cobertura é calculada sobre subconjuntos de tamanho `m`: cada subconjunto deve estar contido em pelo menos um bilhete de tamanho `k`. Quando o número de subconjuntos é muito grande, o motor trabalha com amostragem limitada e informa claramente que o resultado é estimado, evitando travar o computador.

Os motores disponíveis são:

- **Automático**: escolhe enumeração exata apenas quando ela é segura; caso contrário usa heurística limitada.
- **Rápido (heurístico)**: busca gulosa/randomizada com limite de memória e tempo.
- **Exato (pequeno)**: enumera somente instâncias pequenas; recusa automaticamente instâncias perigosas.

A validação de bilhetes colados usa enumeração exata somente dentro do limite seguro e também informa quando a análise é amostral.
