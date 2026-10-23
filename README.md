<div align="center">

<img src=".github/readme/banner.svg" alt="ferramentas-git — seis ferramentas para todos os seus repositórios do GitHub, em janelas de terminal Catppuccin" width="100%">

**Um só comando para cuidar de todos os seus repositórios do GitHub: caça segredos vazados, faz faxina de branches, confere as demos, faz backup, audita dependências e tira a coautoria do Claude.**

[![Python](https://img.shields.io/badge/python-3.8%2B-a6e3a1?style=for-the-badge&logo=python&logoColor=black)](https://www.python.org/downloads/)
[![Dependências](https://img.shields.io/badge/depend%C3%AAncias-zero-313244?style=for-the-badge)](ferramentas-git.py)
[![Terminais](https://img.shields.io/badge/terminais-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-cba6f7?style=for-the-badge)](#funciona-em-qualquer-terminal)

<img src=".github/readme/menu.png" alt="Menu no terminal: janela com ~/início/, logo </> KESSLERU em blocos e a lista das seis ferramentas" width="520">

</div>

## Rodando

Precisa de **Python 3.8+**, **git** e **curl**. Nada para instalar com pip.

```bash
python ferramentas-git.py            # abre o menu
python ferramentas-git.py segredos   # ou vai direto numa ferramenta
```

Na primeira vez ele procura seu login do GitHub sozinho: a variável `GH_TOKEN`, o `gh`, ou o login que o git já guarda. Se não achar, pede um token (tipo *classic*, com `repo` e `workflow`) e não mostra o que você digita.

## As ferramentas

| Comando | O que faz | Altera alguma coisa? |
| --- | --- | --- |
| `segredos` | Varre o histórico inteiro atrás de chaves, tokens e senhas commitadas sem querer | Não |
| `branches` | Lista as branches já mescladas e apaga as que podem sair | Só depois do seu **SIM** |
| `demos` | Abre o link de demo de cada repositório e avisa quem saiu do ar | Não (oferece preencher o campo "site") |
| `backup` | Baixa e atualiza a branch principal de todos numa pasta | Só a sua pasta local |
| `deps` | Vulnerabilidades e dependências velhas dos projetos JavaScript, sem precisar de Node | Não |
| `coautores` | Tira a coautoria do Claude do histórico | Só depois do seu **SIM** |

<details>
<summary><b>O que cada uma faz por dentro</b></summary>

- **segredos** — lê cada versão de cada arquivo que já existiu, em todas as branches, e procura mais de 20 tipos de chave (GitHub, AWS, OpenAI, Anthropic, Stripe, Discord, Mercado Pago, chave privada, endereço de banco com senha…). Chave em teste, exemplo ou documentação aparece rebaixada, com o motivo; JWT é aberto para saber se é a `service_role` do Supabase (grave) ou a `anon` (pública). Falso positivo vai para `~/.ferramentas-git/segredos-ignorados.txt`.
- **branches** — compara cada branch com a principal e com os PRs: só marca para apagar a que já está inteira na principal ou cujo PR foi mesclado sem commits depois. Guarda o que apagou e desfaz com `--restaurar`. No fim, oferece ligar o "apagar branch após o merge" do GitHub.
- **demos** — pega o link do campo "site", do README e do GitHub Pages, abre cada um e reconhece página de erro disfarçada (deploy apagado da Vercel, Pages desligado, app suspenso no Render/Heroku).
- **backup** — clona só a branch principal. Nas próximas vezes, só puxa o que mudou; se o histórico foi reescrito no GitHub, guarda a cópia velha em `.antigos` antes de baixar de novo; se você mexeu nos arquivos do backup, não atropela. Mantém um `INDICE.md` com o último commit de cada um.
- **deps** — lê `package-lock.json`, `pnpm-lock.yaml` ou `yarn.lock` direto do GitHub e consulta a mesma base de vulnerabilidades do `npm audit`, contando por pacote como ele. Mostra também o que está atrás de versão major e o que foi descontinuado.
- **coautores** — remove `Co-Authored-By: Claude`, `Claude-Session` e "Generated with Claude Code" das mensagens, e põe você como autor onde o Claude aparecia. Mesmos arquivos, datas e quantidade de commits; confere isso antes de enviar e guarda um backup de cada repositório.

</details>

<div align="center">
<img src=".github/readme/backup.png" alt="Tela do backup: seis repositórios baixados e o resumo com o tamanho da pasta" width="520">
</div>

## Opções

| Opção | Efeito |
| --- | --- |
| `Repo1 Repo2` | Só esses repositórios (padrão: todos os seus) |
| `--teste` | Mostra o que faria, sem alterar nada no GitHub |
| `--sim` | Não pede confirmação |
| `--destino PASTA` | Pasta do backup (padrão `~/backup-github`; ele lembra da última) |
| `--forks` | Inclui forks |
| `--restaurar ARQUIVO` | Recria as branches apagadas numa rodada anterior |
| `--ascii` | Só caracteres simples, para terminal que mostra quadradinhos |
| `--sem-cor` | Sem cores (`NO_COLOR` também funciona) |

## Funciona em qualquer terminal

Windows Terminal, cmd e PowerShell, Git Bash, Terminal do macOS, iTerm, VS Code e terminais do Linux. Ele descobre sozinho quantas cores o terminal aguenta (milhões, 256 ou 16) e quais símbolos a fonte tem. Em tela estreita, o logo encolhe para uma linha e nada passa da borda.

## Segurança

- Nada é apagado ou reescrito sem você digitar **SIM**, e `--teste` deixa experimentar sem risco.
- Antes de reescrever histórico, o `coautores` guarda um backup de cada repositório; o `branches` guarda o que apagou e desfaz com `--restaurar`.
- O token nunca vai na linha de comando, onde apareceria na lista de processos: o `curl` recebe pela entrada padrão e o `git` por variável de ambiente.
- Achados de segredos aparecem mascarados (`ghp_…a9`), na tela e no relatório.

Relatórios, cache e backups ficam em `~/.ferramentas-git`.

## Estrutura

```
ferramentas-git.py         a ferramenta inteira, num arquivo só
.github/readme/
  banner.svg               o banner acima
  gerar_banner.py          gera o banner (python .github/readme/gerar_banner.py)
  menu.png, backup.png     capturas de execuções reais, num terminal de 60 colunas
```
