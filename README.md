# Fechamento combinatório `(v,k,t,m)`

Aplicação desktop Tkinter sem dependências externas.

## Definição implementada

Para todo resultado `M` com `m` números, o programa procura bilhete `B` com `k` números tal que:

```text
|B ∩ M| >= t
```

As restrições são `k <= v`, `m <= v`, `m >= t` e `k >= t`.

A cobertura de um bilhete é calculada corretamente por:

```text
sum(C(k,i) * C(v-k,m-i) for i in range(t, min(k,m)+1))
```

O limite inferior exibido é o limite por contagem:

```text
ceil(C(v,m) / cobertura_por_bilhete)
```

## Execução

```bash
python main.py
```

## Motor

O motor é uma heurística de **set cover**: cria candidatos de `k` números contendo `t` números de resultados ainda não cobertos e escolhe o candidato que cobre a maior quantidade de resultados pela condição real `|B ∩ M| >= t`.

Quando `C(v,m)` cabe no limite seguro, a verificação é exata. Em configurações muito grandes, o programa usa uma amostra limitada e informa `AMOSTRAL`, sem tentar alocar combinações gigantescas e travar o computador.

O botão **VALIDAR JOGOS** lê os jogos colados na área de bilhetes, calcula a porcentagem de garantia, lista resultados não cobertos e exibe o selo ouro quando a verificação exata chega a 100%.
