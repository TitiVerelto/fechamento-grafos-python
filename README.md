# Fechamento combinatório (v,k,t,m)

Aplicação Tkinter com dois motores:

- **Explícito**: cria o grafo bipartido de incidência entre todos os resultados `M` de tamanho `m` e blocos `B` de tamanho `k`. Existe aresta quando `|M ∩ B| >= t`. Use em instâncias pequenas/médias.
- **Implícito**: não materializa todos os vértices/arestas; cria candidatos a partir de resultados amostrados e usa o mesmo critério de incidência. Use em instâncias gigantescas. A garantia é marcada como amostral, nunca como 100% exata.

O Cascade mantém a melhor solução válida da rodada anterior, calcula graus dos resultados, exclui bilhetes sem resultados exclusivos e repete a redução. Para parar, clique PARAR. Com tempo 0, não há parada automática por tempo; o motor para ao atingir o limite inferior ou por PARAR.

A regra é:

```text
|bilhete ∩ resultado| >= t
```

A saída é formatada como:

```text
00001: 01 02 03 04 05
```

Execute com:

```bash
python main.py
```
