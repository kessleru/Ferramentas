#!/usr/bin/env python3
# ferramentas-git — utilidades para todos os seus repositórios do GitHub.
#
#   python ferramentas-git.py               abre o menu
#   python ferramentas-git.py segredos      caça chaves e senhas no histórico
#   python ferramentas-git.py branches      apaga branches já mescladas
#   python ferramentas-git.py demos         confere se os sites das demos estão no ar
#   python ferramentas-git.py backup        baixa/atualiza a branch principal de todos
#   python ferramentas-git.py deps          vulnerabilidades e dependências velhas
#   python ferramentas-git.py coautores     tira a coautoria do Claude do histórico
#
# Depois do comando: nomes de repositórios (só eles), --teste (não altera nada no GitHub),
# --sim (não pede confirmação), --destino PASTA (backup), --forks (inclui forks),
# --restaurar ARQUIVO (branches: recria as que foram apagadas numa rodada anterior),
# --ascii (terminal que mostra quadradinhos no lugar dos símbolos), --sem-cor.
#
# Precisa de Python 3.8+, git e curl. O git-filter-repo (só para o coautores) se instala sozinho.

import argparse
import base64
import getpass
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

DONO = os.environ.get('FERRAMENTAS_GIT_DONO', 'kessleru')
CASA = Path(os.environ.get('FERRAMENTAS_GIT_CASA') or Path.home() / '.ferramentas-git')

# Catppuccin Frappé, a paleta do kessleru.com.br
PALETA = {
    'texto': (198, 208, 245), 'sub': (165, 173, 206), 'apagado': (131, 139, 167),
    'superficie': (81, 87, 109), 'fundo': (65, 69, 89),
    'verde': (166, 209, 137), 'vermelho': (231, 130, 132), 'amarelo': (229, 200, 144),
    'pessego': (239, 159, 118), 'azul': (140, 170, 238), 'roxo': (202, 158, 230),
}

# o favicon do portfólio ("</>") e o nome, em meio-blocos: 3 linhas de altura
LOGO_SIMBOLO = [' ▄▀   █ ▀▄ ', '▀▄  ▄▀   ▄▀', '  ▀ ▀   ▀  ']
LOGO_NOME = ['█ █ █▀▀ █▀▀ █▀▀ █   █▀▀ █▀▄ █ █',
             '█▀▄ █▀  ▀▀█ ▀▀█ █   █▀  █▀▄ █ █',
             '▀ ▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀ ▀▀▀']

FERRAMENTAS = [
    ('segredos', 'segredos.sh', 'chaves e senhas vazadas'),
    ('branches', 'branches.sh', 'apaga as já mescladas'),
    ('demos', 'demos.sh', 'os sites estão no ar?'),
    ('backup', 'backup.sh', 'cópia da branch principal'),
    ('deps', 'deps.sh', 'falhas e versões velhas'),
    ('coautores', 'coautores.sh', 'tira a coautoria do Claude'),
]


# ═══════════════════════════════ utilidades ═══════════════════════════════

def agora_iso():
    return datetime.now(timezone.utc).isoformat()


def carimbo():
    return datetime.now().strftime('%Y-%m-%d_%H%M%S')


def ha_quanto(iso):
    try:
        t = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return ''
    s = (datetime.now(timezone.utc) - t).total_seconds()
    if s < 3600:
        return 'agora há pouco'
    if s < 86400:
        return f'há {int(s // 3600)} h'
    d = int(s // 86400)
    if d < 60:
        return f'há {d} dia' + ('s' if d > 1 else '')
    if d < 730:
        return f'há {d // 30} meses'
    return f'há {d // 365} anos'


def texto(b):
    return b.decode('utf-8', 'replace') if isinstance(b, bytes) else (b or '')


def corta(s, n):
    s = str(s)
    if n <= 0:
        return ''
    return s if len(s) <= n else (s[:n - 1] + '…' if n > 1 else s[:n])


ANSI = re.compile(r'\033\[[0-9;]*m')


def vlen(s):
    return len(ANSI.sub('', s))


def roda(cmd, cwd=None, entrada=None, env=None, tempo=None):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd, input=entrada, env=env,
                              capture_output=True, timeout=tempo)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or b'', b'tempo esgotado')
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, b'', f'{cmd[0]} não encontrado'.encode())


def tamanho_pasta(p):
    total = 0
    for raiz, _, arquivos in os.walk(p):
        for a in arquivos:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total


def humano(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return f'{n:.0f} {u}' if u in ('B', 'KB') else f'{n:.1f} {u}'.replace('.', ',')
        n /= 1024


def carrega_estado():
    try:
        return json.loads((CASA / 'estado.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def salva_estado(estado):
    CASA.mkdir(parents=True, exist_ok=True)
    (CASA / 'estado.json').write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding='utf-8')


# ═══════════════════════════════ terminal ═══════════════════════════════

def _xterm256(r, g, b):
    niveis = [0, 95, 135, 175, 215, 255]

    def perto(c):
        return min(range(6), key=lambda i: abs(niveis[i] - c))

    ri, gi, bi = perto(r), perto(g), perto(b)
    d_cubo = (niveis[ri] - r) ** 2 + (niveis[gi] - g) ** 2 + (niveis[bi] - b) ** 2
    ci = max(0, min(23, int(round(((r + g + b) / 3 - 8) / 10))))
    cv = 8 + ci * 10
    d_cinza = sum((cv - c) ** 2 for c in (r, g, b))
    return 232 + ci if d_cinza < d_cubo else 16 + 36 * ri + 6 * gi + bi


# terminais sem cor real ficam com a paleta de 16 cores mais próxima (código ANSI de frente)
CORES16 = {'texto': 97, 'sub': 37, 'apagado': 90, 'superficie': 90, 'fundo': 90, 'verde': 92, 'vermelho': 91,
           'amarelo': 93, 'pessego': 33, 'azul': 94, 'roxo': 95}
# console antigo do Windows (cmd/PowerShell fora do Windows Terminal) e console do Linux: as fontes
# não têm esses símbolos e mostrariam quadradinhos
TROCA_SIMPLES = str.maketrans({'✓': '+', '✗': 'x', '↳': '>', '↑': '^', '↻': '*', '→': '->', '●': '•', '◆': '♦'})
# último recurso (--ascii, ou terminal que não fala UTF-8): só caracteres ASCII
TROCA_ASCII = str.maketrans({'✓': '+', '✗': 'x', '·': '.', '…': '...', '─': '-', '●': '*', '◆': '>', '■': '#',
                             '█': '#', '▀': '"', '▄': '_', '↳': '>', '↑': '^', '↻': '*', '→': '->', '—': '-',
                             '•': '*', '♦': '>', '🔒': ''})


class Terminal:
    def __init__(self, ascii_forcado=False, sem_cor=False):
        env = os.environ
        if os.name == 'nt':
            os.system('')  # liga as sequências ANSI no console do Windows 10+
        cod_original = (getattr(sys.stdout, 'encoding', '') or '').lower().replace('-', '')
        for fluxo in (sys.stdout, sys.stderr):
            try:
                fluxo.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, ValueError):
                pass
        # o Git Bash (mintty) entrega pipes ao Python, que então acha que não está num terminal
        mintty = bool(env.get('MSYSTEM')) or env.get('TERM_PROGRAM') == 'mintty'
        win_moderno = 'WT_SESSION' in env or 'TERM_PROGRAM' in env or mintty or env.get('ConEmuANSI') == 'ON'
        termo = env.get('TERM', '')
        self.tty = sys.stdout.isatty() or mintty
        self.interativo = sys.stdin.isatty() or mintty
        self.cor = (self.tty and not sem_cor and 'NO_COLOR' not in env and termo != 'dumb') or bool(env.get('FORCE_COLOR'))
        ct = env.get('COLORTERM', '').lower()
        if (ct in ('truecolor', '24bit') or 'WT_SESSION' in env or mintty
                or env.get('TERM_PROGRAM') in ('vscode', 'iTerm.app', 'WezTerm', 'Hyper', 'ghostty')):
            self.modo_cor = 24
        elif (os.name == 'nt' or '256' in termo or env.get('TERM_PROGRAM') == 'Apple_Terminal'
              or termo.startswith(('xterm', 'screen', 'tmux', 'rxvt', 'alacritty', 'kitty', 'foot', 'wezterm'))):
            self.modo_cor = 256
        else:
            self.modo_cor = 16
        # o Python força UTF-8 até em locale "C", então quem diz se o terminal entende UTF-8 é o idioma
        idioma = env.get('LC_ALL') or env.get('LC_CTYPE') or env.get('LANG') or ''
        sem_utf8 = os.name != 'nt' and ((idioma and 'utf' not in idioma.lower()) or (cod_original and 'utf8' not in cod_original))
        if ascii_forcado or env.get('FERRAMENTAS_GIT_ASCII') or sem_utf8:
            self.nivel = 'ascii'
        elif (os.name == 'nt' and not win_moderno) or termo == 'linux':
            self.nivel = 'simples'
        else:
            self.nivel = 'pleno'
        self.largura = max(36, min(shutil.get_terminal_size((72, 24)).columns - 1, 78))
        self.trava = threading.RLock()
        self.vivo_txt = ''

    def _adapta(self, txt):
        if self.nivel == 'pleno':
            return txt
        if self.nivel == 'simples':
            return txt.translate(TROCA_SIMPLES)
        import unicodedata
        txt = txt.translate(TROCA_ASCII)
        return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode()

    def _cod(self, nome, fundo=False):
        r, g, b = PALETA[nome]
        if self.modo_cor == 16:
            return f'\033[{CORES16[nome] + (10 if fundo else 0)}m'
        camada = 48 if fundo else 38
        if self.modo_cor == 24:
            return f'\033[{camada};2;{r};{g};{b}m'
        return f'\033[{camada};5;{_xterm256(r, g, b)}m'

    def p(self, txt, cor=None, negrito=False, fundo=None):
        if not self.cor or (cor is None and not negrito and fundo is None):
            return str(txt)
        s = ('\033[1m' if negrito else '') + (self._cod(cor) if cor else '') + (self._cod(fundo, True) if fundo else '')
        return s + str(txt) + '\033[0m'

    def escreve(self, txt=''):
        with self.trava:
            if self.vivo_txt and self.tty:
                sys.stdout.write('\r\033[2K')
            sys.stdout.write(self._adapta(txt) + '\n')
            if self.vivo_txt and self.tty:
                sys.stdout.write(self.vivo_txt)
            sys.stdout.flush()

    def vivo(self, txt):
        if not self.tty:
            return
        with self.trava:
            self.vivo_txt = self._adapta(txt)
            sys.stdout.write('\r\033[2K' + self.vivo_txt)
            sys.stdout.flush()

    def para_vivo(self):
        with self.trava:
            if self.vivo_txt and self.tty:
                sys.stdout.write('\r\033[2K')
                sys.stdout.flush()
            self.vivo_txt = ''

    def limpa(self):
        if self.tty:
            sys.stdout.write('\033[2J\033[H')

    # ---- peças visuais ----
    def cabecalho(self, caminho='início'):
        w = self.largura
        bolas = ' '.join(self.p('●', c) for c in ('vermelho', 'amarelo', 'verde'))
        titulo = 'ferramentas-git — Visual Studio Code' if w >= 60 else 'ferramentas-git'
        esp = max(2, (w - 6 - len(titulo)) // 2)
        self.escreve()
        self.escreve(' ' + bolas + ' ' * esp + self.p(titulo, 'apagado'))
        self.escreve(' ' + self.p('~', 'verde') + self.p(f'/{caminho}/', 'texto') + self.p('█', 'verde'))
        self.escreve(' ' + self.p('─' * (w - 1), 'superficie'))
        self.escreve()
        if w >= 48 and self.nivel != 'ascii':
            for s, n in zip(LOGO_SIMBOLO, LOGO_NOME):
                self.escreve('  ' + self.p(s, 'texto') + '   ' + self.p(n, 'verde'))
        else:
            self.escreve('  ' + self.p('</>', 'texto', True) + '  ' + self.p('KESSLERU', 'verde', True))
        self.escreve()

    def titulo(self, txt):
        self.escreve('  ' + self.p('>', 'verde', True) + ' ' + self.p(txt, 'texto', True))

    def aba(self, arquivo, descricao=''):
        self.escreve()
        extra = '  ' + self.p(corta(descricao, self.largura - len(arquivo) - 9), 'apagado') if descricao else ''
        self.escreve('  ' + self.p(f' ◆ {arquivo} ', 'texto', fundo='fundo') + extra)
        self.escreve('  ' + self.p('─' * (self.largura - 2), 'fundo'))

    def prompt(self, pasta, txt):
        self.escreve('  ' + self.p('~', 'verde') + self.p(f'/{pasta}/', 'sub') + ' '
                     + self.p('>', 'verde') + ' ' + self.p(corta(txt, self.largura - len(pasta) - 7), 'texto'))

    def item(self, icone, cor, nome, detalhe='', recuo=2, cor_nome='texto'):
        w = self.largura
        d = vlen(detalhe)
        if d and recuo + 6 + min(len(nome), 16) + d > w:
            self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + self.p(corta(nome, w - recuo - 2), cor_nome))
            self.escreve(' ' * (recuo + 2) + detalhe)
            return
        n = corta(nome, w - recuo - 5 - d)
        if not d:
            self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + self.p(n, cor_nome))
            return
        pontos = max(1, w - recuo - 2 - len(n) - 2 - d)
        self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + self.p(n, cor_nome) + ' '
                     + self.p('·' * pontos, 'superficie') + ' ' + detalhe)

    def partes(self, itens, recuo=4):
        # junta com " · " e quebra a linha entre itens, nunca no meio de um
        linha, larg = '', 0
        for it in itens:
            n = vlen(it)
            if linha and recuo + larg + 3 + n > self.largura:
                self.escreve(' ' * recuo + linha)
                linha, larg = '', 0
            if linha:
                linha += self.p(' · ', 'apagado')
                larg += 3
            linha += it
            larg += n
        if linha:
            self.escreve(' ' * recuo + linha)

    def paragrafo(self, txt, recuo=4, cor='sub'):
        for linha in textwrap.wrap(txt, max(20, self.largura - recuo), break_on_hyphens=False):
            self.escreve(' ' * recuo + self.p(linha, cor))

    def ok(self, txt):
        self.escreve('  ' + self.p('✓', 'verde') + ' ' + txt)

    def aviso(self, txt):
        self.escreve('  ' + self.p('!', 'amarelo', True) + ' ' + self.p(txt, 'amarelo'))

    def erro(self, txt):
        self.escreve('  ' + self.p('✗', 'vermelho', True) + ' ' + self.p(txt, 'vermelho'))

    def nota(self, txt, recuo=2):
        self.escreve(' ' * recuo + self.p(txt, 'apagado'))

    def pergunta(self, txt):
        try:
            return input(self._adapta('  ' + self.p('~', 'verde') + self.p(f'/{txt}/', 'sub') + ' ' + self.p('> ', 'verde')))
        except EOFError:
            return ''


def _espera(self, txt):
    try:
        input(self._adapta('  ' + self.p(txt, 'apagado') + ' '))
    except EOFError:
        pass


Terminal.espera = _espera


def caminho_curto(p, n=None):
    s = str(p)
    casa = str(Path.home())
    if s.startswith(casa):
        s = '~' + s[len(casa):]
    return corta_esq(s, n) if n else s


class Progresso:
    QUADROS = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, term, total, rotulo):
        self.t, self.total, self.rotulo = term, max(total, 1), rotulo
        self.n, self.atual, self._i = 0, '', 0
        self._parar = threading.Event()
        self._fio = threading.Thread(target=self._gira, daemon=True)
        if term.nivel != 'pleno':
            self.QUADROS = '|/-\\'
        # sem cor, quadrado cheio e vazio seriam iguais
        self.cheio = '#' if term.nivel == 'ascii' else '■'
        self.vazio = '■' if term.cor else ('-' if term.nivel == 'ascii' else '·')

    def __enter__(self):
        if self.t.tty:
            self._fio.start()
        return self

    def __exit__(self, *_):
        self._parar.set()
        if self._fio.is_alive():
            self._fio.join()
        self.t.para_vivo()

    def avanca(self, atual=''):
        self.n += 1
        self.atual = atual

    def _desenho(self):
        t = self.t
        q = self.QUADROS[self._i % len(self.QUADROS)]
        self._i += 1
        conta = f'{self.n}/{self.total}'
        larg = max(6, min(20, t.largura - len(self.rotulo) - len(conta) - 24))
        cheio = int(larg * self.n / self.total)
        barra = t.p(self.cheio * cheio, 'verde') + t.p(self.vazio * (larg - cheio), 'fundo')
        resto = t.largura - 8 - len(self.rotulo) - larg - len(conta)
        return (f'  {t.p(q, "verde")} {t.p(self.rotulo, "sub")} {barra} {t.p(conta, "texto")} '
                f'{t.p(corta(self.atual, resto), "apagado")}')

    def _gira(self):
        while not self._parar.wait(0.08):
            self.t.vivo(self._desenho())


class Relatorio:
    def __init__(self, nome):
        self.nome, self.linhas = nome, [f'ferramentas-git · {nome} · {datetime.now():%d/%m/%Y %H:%M}', '']

    def add(self, *linhas):
        self.linhas.extend(linhas)

    def salva(self):
        pasta = CASA / 'relatorios'
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / f'{self.nome}-{carimbo()}.txt'
        arq.write_text('\n'.join(self.linhas) + '\n', encoding='utf-8')
        return arq


def confirma(ctx, pergunta):
    t = ctx.t
    if ctx.args.sim:
        return True
    if not t.interativo:
        t.aviso('Sem terminal para confirmar; use --sim para seguir sem perguntar.')
        return False
    t.escreve()
    t.escreve('  ' + t.p(pergunta, 'amarelo'))
    return t.pergunta('digite SIM').strip().lower() == 'sim'


# ═══════════════════════════════ GitHub ═══════════════════════════════

class ErroAPI(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def obter_token():
    for var in ('GH_TOKEN', 'GITHUB_TOKEN'):
        if os.environ.get(var):
            return os.environ[var].strip()
    if shutil.which('gh'):
        r = roda(['gh', 'auth', 'token'], tempo=20)
        if r.returncode == 0 and r.stdout.strip():
            return texto(r.stdout).strip()
    r = roda(['git', 'credential', 'fill'], entrada=b'protocol=https\nhost=github.com\n\n',
             env=dict(os.environ, GIT_TERMINAL_PROMPT='0'), tempo=180)
    for linha in texto(r.stdout).splitlines():
        if linha.startswith('password='):
            return linha[9:].strip()
    return None


class GitHub:
    API = 'https://api.github.com'

    def __init__(self, term, sem_login=False):
        self.t, self.token, self.login = term, None, None
        if not shutil.which('curl'):
            raise SystemExit('ERRO: preciso do curl instalado.')
        if not sem_login:
            self._entrar()

    def requisita(self, url, metodo='GET', corpo=None, aceita=None, tempo=40):
        if url.startswith('/'):
            url = self.API + url
        do_github = url.startswith(self.API)
        aceita = aceita or ('application/vnd.github+json' if do_github else 'application/json')
        # o token vai pela configuração no stdin do curl, nunca na linha de comando
        cfg = [f'url = "{url}"', f'header = "Accept: {aceita}"', 'header = "User-Agent: ferramentas-git"']
        if do_github:
            cfg.append('header = "X-GitHub-Api-Version: 2022-11-28"')
            if self.token:
                cfg.append(f'header = "Authorization: Bearer {self.token}"')
        if metodo != 'GET':
            cfg.append(f'request = "{metodo}"')
        args = ['curl', '-sS', '-K', '-', '--max-time', str(tempo), '-w', '\n%{http_code}']
        arq_corpo = None
        if corpo is not None:
            CASA.mkdir(parents=True, exist_ok=True)
            arq_corpo = CASA / f'.corpo-{os.getpid()}-{threading.get_ident()}.json'
            arq_corpo.write_text(json.dumps(corpo), encoding='utf-8')
            args += ['-H', 'Content-Type: application/json', '--data-binary', f'@{arq_corpo}']
        try:
            status, dados = 0, b''
            for tentativa in range(3):
                r = roda(args, entrada='\n'.join(cfg).encode(), tempo=tempo + 10)
                dados, _, cod = r.stdout.rpartition(b'\n')
                status = int(cod) if cod.strip().isdigit() else 0
                if status in (0, 502, 503, 504) and tentativa < 2:
                    time.sleep(1.5 * (tentativa + 1))
                    continue
                break
            return status, dados
        finally:
            if arq_corpo:
                try:
                    arq_corpo.unlink()
                except OSError:
                    pass

    def json(self, url, **kw):
        status, dados = self.requisita(url, **kw)
        if status == 0 or status >= 400:
            try:
                msg = json.loads(dados).get('message', '')
            except (ValueError, AttributeError):
                msg = texto(dados)[:160]
            raise ErroAPI(status, msg or f'HTTP {status}')
        return json.loads(dados) if dados.strip() else None

    def paginas(self, url):
        sep = '&' if '?' in url else '?'
        tudo = []
        for pagina in range(1, 200):
            lote = self.json(f'{url}{sep}per_page=100&page={pagina}')
            if not lote:
                break
            tudo.extend(lote)
            if len(lote) < 100:
                break
        return tudo

    def bruto(self, full, caminho, ref):
        status, dados = self.requisita(f'/repos/{full}/contents/{quote(caminho)}?ref={quote(ref)}',
                                       aceita='application/vnd.github.raw')
        return dados if status == 200 else None

    def _entrar(self):
        t = self.t
        self.token = obter_token()
        if self.token and not self._valida():
            self.token = None
        if not self.token and self.t.interativo:
            t.aviso('Não achei seu login do GitHub.')
            t.paragrafo('Crie um token em github.com/settings/tokens (tipo "classic", marcando "repo" e '
                        '"workflow") e cole aqui. Ele não aparece na tela.')
            try:
                digitado = getpass.getpass('  token: ').strip()
            except (EOFError, KeyboardInterrupt):
                digitado = ''
            if digitado:
                self.token = digitado
                if self._valida():
                    self._guarda(digitado)
                else:
                    t.erro('Esse token não foi aceito pelo GitHub.')
                    self.token = None
        if self.token:
            t.ok(f'conectado como {t.p(self.login, "verde")}')
        else:
            t.aviso(f'Sem login: só os repositórios públicos de {DONO}, e nada pode ser alterado.')

    def _valida(self):
        try:
            self.login = self.json('/user')['login']
            return True
        except (ErroAPI, KeyError, TypeError):
            return False

    def _guarda(self, token):
        if texto(roda(['git', 'config', 'credential.helper']).stdout).strip():
            roda(['git', 'credential', 'approve'],
                 entrada=f'protocol=https\nhost=github.com\nusername={self.login or DONO}\npassword={token}\n\n'.encode())

    def env_git(self):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
        if self.token:
            b64 = base64.b64encode(f'x-access-token:{self.token}'.encode()).decode()
            n = int(env.get('GIT_CONFIG_COUNT') or 0)
            env['GIT_CONFIG_COUNT'] = str(n + 1)
            env[f'GIT_CONFIG_KEY_{n}'] = 'http.https://github.com/.extraheader'
            env[f'GIT_CONFIG_VALUE_{n}'] = f'AUTHORIZATION: basic {b64}'
        return env

    def repos(self, nomes=None, forks=False, arquivados=True):
        if nomes:
            def um(n):
                full = n if '/' in n else f'{DONO}/{n}'
                try:
                    return self.json(f'/repos/{full}')
                except ErroAPI as e:
                    return {'_erro': f'{full}: {e}'}

            with ThreadPoolExecutor(8) as ex:
                res = list(ex.map(um, nomes))
            lista = []
            for r in res:
                if '_erro' in r:
                    self.t.aviso(r['_erro'])
                else:
                    lista.append(r)
        elif self.token:
            lista = self.paginas('/user/repos?affiliation=owner')
        else:
            lista = self.paginas(f'/users/{DONO}/repos?type=owner')
        lista = [r for r in lista if (forks or not r.get('fork')) and (arquivados or not r.get('archived'))]
        return sorted(lista, key=lambda r: r['name'].lower())


class Ctx:
    def __init__(self, args, term):
        self.args, self.t = args, term
        self.estado = carrega_estado()
        self._gh = None

    @property
    def gh(self):
        if self._gh is None:
            self._gh = GitHub(self.t, sem_login=self.args.sem_login)
        return self._gh


def escolhe_repos(ctx, arquivados=True, precisa_login=False):
    t, gh = ctx.t, ctx.gh
    if precisa_login and not gh.token and not ctx.args.sem_login:
        t.erro('Essa ferramenta altera o GitHub e precisa de login.')
        return []
    try:
        lista = gh.repos(ctx.args.repos or None, forks=ctx.args.forks, arquivados=arquivados)
    except ErroAPI as e:
        t.erro(f'O GitHub recusou a lista de repositórios: {e}')
        return []
    pub = sum(1 for r in lista if not r.get('private'))
    priv = len(lista) - pub
    total = f'{len(lista)} repositório{"s" if len(lista) != 1 else ""}'
    texto = f'{total} · {pub} público{"s" if pub != 1 else ""} · {priv} privado{"s" if priv != 1 else ""}'
    if len(texto) + 13 > t.largura:
        texto = f'{total} · {priv} privado{"s" if priv != 1 else ""}'
    t.prompt('repos', texto)
    return lista


def em_paralelo(t, itens, funcao, rotulo, nome=lambda x: x['name'], fios=6):
    resultados, falhas = {}, []
    with Progresso(t, len(itens), rotulo) as pr:
        with ThreadPoolExecutor(fios) as ex:
            futuros = {ex.submit(funcao, it): it for it in itens}
            for f in as_completed(futuros):
                it = futuros[f]
                try:
                    resultados[nome(it)] = f.result()
                except Exception as e:  # um repositório com problema não derruba os outros
                    falhas.append((nome(it), str(e) or e.__class__.__name__))
                pr.avanca(nome(it))
    return resultados, falhas


# ═══════════════════════════════ 1. segredos ═══════════════════════════════

NIVEIS = {'critico': ('CRÍTICO', 'vermelho', 0), 'alto': ('ALTO', 'pessego', 1),
          'medio': ('MÉDIO', 'amarelo', 2), 'baixo': ('BAIXO', 'azul', 3), 'info': ('INFO', 'apagado', 4)}

REGRAS = [
    ('chave_privada', 'Chave privada', r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----', 'alto'),
    ('aws', 'Chave de acesso da AWS', r'\b((?:AKIA|ASIA)[0-9A-Z]{16})\b', 'alto'),
    ('github', 'Token do GitHub', r'\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b', 'alto'),
    ('openai', 'Chave da OpenAI', r'\b(sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}T3BlbkFJ[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{40,})', 'alto'),
    ('anthropic', 'Chave da Anthropic', r'\b(sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{80,})', 'alto'),
    ('google', 'Chave de API do Google', r'\b(AIza[0-9A-Za-z_-]{35})\b', 'medio'),
    ('google_oauth', 'Segredo OAuth do Google', r'\b(GOCSPX-[A-Za-z0-9_-]{28})\b', 'alto'),
    ('conta_servico', 'Conta de serviço do Google', r'"type"\s*:\s*"service_account"', 'alto'),
    ('slack', 'Token do Slack', r'\b(xox[baprs]-[A-Za-z0-9-]{10,})', 'alto'),
    ('slack_webhook', 'Webhook do Slack', r'(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+)', 'alto'),
    ('discord_webhook', 'Webhook do Discord', r'(https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+)', 'alto'),
    ('discord_bot', 'Token de bot do Discord', r'\b([MNO][A-Za-z\d_-]{23,27}\.[\w-]{6}\.[\w-]{27,40})\b', 'alto'),
    ('stripe', 'Chave secreta do Stripe', r'\b((?:sk|rk)_live_[0-9a-zA-Z]{24,})', 'alto'),
    ('stripe_teste', 'Chave de teste do Stripe', r'\b(sk_test_[0-9a-zA-Z]{24,})', 'baixo'),
    ('sendgrid', 'Chave do SendGrid', r'\b(SG\.[\w-]{22}\.[\w-]{43})\b', 'alto'),
    ('npm', 'Token do npm', r'\b(npm_[A-Za-z0-9]{36})\b', 'alto'),
    ('npmrc', 'Token num .npmrc', r'_authToken\s*=\s*([^\s$][^\s]{10,})', 'alto'),
    ('telegram', 'Token de bot do Telegram', r'\b(\d{8,10}:AA[\w-]{33})\b', 'alto'),
    ('mercadopago', 'Token do Mercado Pago', r'\b(APP_USR-\d{10,}-\d{6}-[a-f0-9]{32}-\d{6,})\b', 'alto'),
    ('jwt', 'Token JWT', r'\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})', 'medio'),
    ('url_senha', 'Endereço de banco com senha',
     r'\b((?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|mariadb|rediss?|amqps?|mssql)://([^\s:/@\'"]+):([^\s@/\'"]+)@([^\s/:\'"?,]+)[^\s\'"]*)', 'alto'),
]
REGRAS = [(i, n, re.compile(r), nv) for i, n, r, nv in REGRAS]

RE_ENV = re.compile(r'^\s*(?:export\s+)?([A-Za-z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|PASS|PWD|API_?KEY|PRIVATE|ACCESS_?KEY|'
                    r'CLIENT_?SECRET|CREDENTIAL|DATABASE_URL|DB_URL)[A-Za-z0-9_]*)\s*=\s*[\'"]?([^\'"\s#]+)', re.M | re.I)
RE_CODIGO = re.compile(r'(?i)\b(?:secret|token|password|senha|api[_-]?key|client[_-]?secret|private[_-]?key)\w*'
                       r'\s*[:=]\s*[\'"]([^\'"\s]{12,})[\'"]')
RE_FALSO = re.compile(r'(?i)(x{4,}|\*{4,}|\.{3}|your|seu[_-]|sua[_-]|minha[_-]|my[_-]?(secret|key|token|pass)|example|exemplo|'
                      r'change|troque|altere|placeholder|dummy|fake|sample|test|redacted|<[^>]*>|\$\{|\{\{|\$[A-Z_]|'
                      r'process\.env|import\.meta|os\.environ|getenv|0{6,}|123456|abcdef|^(password|senha|secret|null|'
                      r'undefined|none|true|false|admin|root)$)')
HOSTS_LOCAIS = ('localhost', '127.0.0.1', '0.0.0.0', 'db', 'database', 'postgres', 'mongo', 'mongodb', 'mysql',
                'redis', 'host.docker.internal')
ENV_EXEMPLOS = {'example', 'exemplo', 'sample', 'template', 'dist', 'modelo', 'defaults'}
EXT_BINARIA = set('png jpg jpeg gif webp avif ico bmp tif tiff svg pdf zip gz tgz rar 7z woff woff2 ttf otf eot '
                  'mp4 mp3 wav ogg webm mov avi mkv psd ai fig sketch exe dll so dylib jar class wasm bin pyc docx xlsx pptx'.split())
LOCKS = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'composer.lock', 'Cargo.lock', 'poetry.lock',
         'Gemfile.lock', 'bun.lockb', 'go.sum'}
PASTAS_FORA = ('node_modules/', 'vendor/', 'dist/', 'build/', '.next/', 'coverage/')
NOMES_SENSIVEIS = [
    (re.compile(r'\.(p12|pfx|jks|keystore)$', re.I), 'Chaveiro de certificado (tem chave privada)', 'alto'),
    (re.compile(r'(^|/)\.htpasswd$'), 'Arquivo de senhas do Apache', 'alto'),
    (re.compile(r'\.(sqlite3?|db)$', re.I), 'Banco de dados commitado', 'info'),
]


RE_TESTE = re.compile(r'(?i)(^|/)(__fixtures__|fixtures?|__tests__|tests?|spec|__mocks__|mocks?|exemplos?|examples?|'
                      r'exercicios?|docs?)/|\.(test|spec)\.[a-z]+$|\.md$')
# provedores com formato inconfundível continuam sérios mesmo em teste/documentação
REGRAS_FORTES = {'aws', 'github', 'openai', 'anthropic', 'google_oauth', 'slack', 'slack_webhook', 'discord_webhook',
                 'stripe', 'sendgrid', 'npm', 'npmrc', 'telegram', 'mercadopago', 'conta_servico'}


def corta_esq(s, n):
    return s if len(s) <= n else '…' + s[-(n - 1):]


def entropia(s):
    if not s:
        return 0.0
    c = Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in c.values())


def falso(v):
    return bool(RE_FALSO.search(v))


def fora_da_varredura(caminho):
    base = caminho.rsplit('/', 1)[-1]
    ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
    return (ext in EXT_BINARIA or base in LOCKS or base.endswith(('.min.js', '.min.css', '.map'))
            or any(('/' + p) in ('/' + caminho) for p in PASTAS_FORA))


def classifica_jwt(tok):
    try:
        meio = tok.split('.')[1]
        dados = json.loads(base64.urlsafe_b64decode(meio + '=' * (-len(meio) % 4)))
    except (ValueError, IndexError):
        return None
    if not isinstance(dados, dict):
        return None
    papel = dados.get('role')
    if papel == 'service_role':
        return 'alto', 'Chave service_role do Supabase', 'dá acesso total ao banco, ignorando as regras de segurança'
    if papel == 'anon':
        return 'baixo', 'Chave anon do Supabase', 'é pública por design; confira se as políticas RLS estão ligadas'
    exp = dados.get('exp')
    if isinstance(exp, (int, float)) and exp < time.time():
        return 'baixo', 'Token JWT vencido', 'já expirou; só importa se o segredo que o assinou também vazou'
    return 'medio', 'Token JWT', ''


def acha_no_texto(txt, caminho):
    base = caminho.rsplit('/', 1)[-1]
    eh_env = base == '.env' or (base.startswith('.env.') and base.split('.', 2)[2].lower() not in ENV_EXEMPLOS)
    achados = []

    def novo(regra, nome, nivel, valor, pos, dica=''):
        if len(achados) < 40:
            achados.append({'regra': regra, 'nome': nome, 'nivel': nivel, 'valor': valor,
                            'linha': txt.count('\n', 0, pos) + 1, 'dica': dica})

    for regra, nome, rx, nivel in REGRAS:
        for m in rx.finditer(txt):
            valor = m.group(1) if m.groups() else m.group(0)
            dica = ''
            nv, nm = nivel, nome
            if regra == 'conta_servico':
                if '"private_key"' not in txt:
                    continue
                em = re.search(r'"client_email"\s*:\s*"([^"]+)"', txt)
                valor = em.group(1) if em else caminho
            elif regra == 'jwt':
                cl = classifica_jwt(valor)
                if not cl:
                    continue
                nv, nm, dica = cl
            elif regra == 'url_senha':
                senha, host = m.group(3), m.group(4).lower()
                if falso(senha) or len(senha) < 4:
                    continue
                if host in HOSTS_LOCAIS or host.startswith('192.168.'):
                    nv, dica = 'baixo', 'aponta para um banco local de desenvolvimento'
            elif regra == 'google':
                dica = 'se for a apiKey do Firebase web, é pública por design; confira as restrições no console'
            elif regra == 'chave_privada':
                valor = m.group(0)
            novo(regra, nm, nv, valor, m.start(), dica)
    if eh_env:
        for m in RE_ENV.finditer(txt):
            chave, valor = m.group(1), m.group(2)
            if len(valor) < 6 or falso(valor) or any(a['valor'] in valor or valor in a['valor'] for a in achados):
                continue
            forte = entropia(valor) >= 3.0 or len(valor) >= 16
            novo('env', f'{chave} num {base}', 'alto' if forte else 'medio', valor, m.start(),
                 '' if forte else 'valor curto/óbvio, mas está commitado')
    for m in RE_CODIGO.finditer(txt):
        valor = m.group(1)
        if falso(valor) or entropia(valor) < 3.5 or any(valor in a['valor'] or a['valor'] in valor for a in achados):
            continue
        novo('codigo', 'Possível segredo no código', 'medio', valor, m.start(), 'confira se é uma chave de verdade')
    return achados


def le_blobs(pasta, shas, env):
    proc = subprocess.Popen(['git', '-C', str(pasta), 'cat-file', '--batch'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)

    def escreve():
        try:
            for s in shas:
                proc.stdin.write(s.encode() + b'\n')
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    fio = threading.Thread(target=escreve, daemon=True)
    fio.start()
    for _ in shas:
        cab = proc.stdout.readline()
        if not cab:
            break
        partes = cab.split()
        if len(partes) < 3:
            continue
        tam = int(partes[2])
        dados = proc.stdout.read(tam)
        proc.stdout.read(1)
        yield partes[0].decode(), dados
    fio.join()
    proc.wait()


def atualiza_cache(r, env):
    pasta = CASA / 'cache' / (r['full_name'].replace('/', '__') + '.git')
    url = f'https://github.com/{r["full_name"]}.git'
    if pasta.exists():
        f = roda(['git', '-C', pasta, 'fetch', '-q', '--prune', '--force', url,
                  '+refs/heads/*:refs/heads/*', '+refs/tags/*:refs/tags/*'], env=env, tempo=900)
        if f.returncode == 0:
            return pasta
        shutil.rmtree(pasta, ignore_errors=True)
    pasta.parent.mkdir(parents=True, exist_ok=True)
    c = roda(['git', 'clone', '-q', '--bare', url, pasta], env=env, tempo=900)
    if c.returncode != 0:
        raise RuntimeError(corta(texto(c.stderr).strip().splitlines()[-1] if c.stderr.strip() else 'clone falhou', 70))
    return pasta


def varre_repo(r, env):
    pasta = atualiza_cache(r, env)
    lista = texto(roda(['git', '-C', pasta, 'rev-list', '--all', '--objects'], tempo=600).stdout)
    caminhos = {}
    for linha in lista.splitlines():
        sha, _, cam = linha.partition(' ')
        if cam and sha not in caminhos:
            caminhos[sha] = cam
    if not caminhos:
        return []
    chk = roda(['git', '-C', pasta, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'],
               entrada=('\n'.join(caminhos) + '\n').encode(), tempo=600)
    brutos = defaultdict(list)  # (regra, valor) -> [(blob, caminho, linha, achado)]
    ler = []
    for linha in texto(chk.stdout).splitlines():
        partes = linha.split()
        if len(partes) != 3 or partes[1] != 'blob':
            continue
        sha, tam, cam = partes[0], int(partes[2]), caminhos[partes[0]]
        for rx, nome, nivel in NOMES_SENSIVEIS:
            if rx.search(cam):
                dica = 'pode ter dados pessoais de quem usou o sistema' if nivel == 'info' else ''
                brutos[('arquivo', cam)].append((sha, cam, 0, {'regra': 'arquivo', 'nome': nome, 'nivel': nivel,
                                                               'valor': cam, 'linha': 0, 'dica': dica}))
        if tam <= 1_000_000 and not fora_da_varredura(cam):
            ler.append(sha)
    for sha, dados in le_blobs(pasta, ler, None):
        if b'\0' in dados[:8000]:
            continue
        cam = caminhos[sha]
        for a in acha_no_texto(dados.decode('utf-8', 'replace'), cam):
            brutos[(a['regra'], a['valor'])].append((sha, cam, a['linha'], a))
    if not brutos:
        return []
    atuais = set()
    for linha in texto(roda(['git', '-C', pasta, 'ls-tree', '-r', 'HEAD']).stdout).splitlines():
        partes = linha.split(None, 3)
        if len(partes) == 4:
            atuais.add(partes[2])
    achados = []
    for (regra, valor), ocorr in brutos.items():
        blob, cam, ln, a = ocorr[0]
        nivel, dica = a['nivel'], a['dica']
        if regra not in REGRAS_FORTES and nivel not in ('baixo', 'info') and all(RE_TESTE.search(o[1]) for o in ocorr):
            nivel, dica = 'baixo', 'está em teste, exemplo ou documentação; provavelmente fictício'
        if nivel == 'alto' and not r.get('private'):
            nivel = 'critico'
        log = texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%ad (%h)', '--date=short',
                          f'--find-object={blob}']).stdout).strip().splitlines()
        desde = log[-1] if log else ''
        achados.append(dict(a, nivel=nivel, dica=dica, caminho=cam, linha=ln, lugares=len({o[1] for o in ocorr}),
                            atual=any(o[0] in atuais for o in ocorr), desde=desde,
                            id=hashlib.sha1(f'{r["full_name"]}:{regra}:{valor}'.encode()).hexdigest()[:12]))
    return sorted(achados, key=lambda a: NIVEIS[a['nivel']][2])


def mascara(a):
    v = a['valor']
    if a['regra'] == 'chave_privada':
        return '-----BEGIN … PRIVATE KEY-----'
    if a['regra'] in ('arquivo', 'conta_servico'):
        return v
    if len(v) <= 8:
        return v[:2] + '…'
    return f'{v[:4]}…{v[-2:]} ({len(v)} car.)'


def carrega_ignorados():
    try:
        linhas = (CASA / 'segredos-ignorados.txt').read_text(encoding='utf-8').splitlines()
    except OSError:
        return set()
    return {l.split('#')[0].strip() for l in linhas if l.split('#')[0].strip()}


def ferramenta_segredos(ctx):
    t = ctx.t
    repos = escolhe_repos(ctx, arquivados=True)
    if not repos:
        return
    env = ctx.gh.env_git()
    res, falhas = em_paralelo(t, repos, lambda r: varre_repo(r, env), 'varrendo', fios=4)
    ignorados = carrega_ignorados()
    rel = Relatorio('segredos')
    total = Counter()
    limpos = 0
    t.escreve()
    for r in sorted(repos, key=lambda r: min([NIVEIS[a['nivel']][2] for a in res.get(r['name'], [])] or [9])):
        achados = [a for a in res.get(r['name'], []) if a['id'] not in ignorados]
        if r['name'] not in res:
            continue
        if not achados:
            limpos += 1
            continue
        pior = NIVEIS[achados[0]['nivel']]
        vis = 'público' if not r.get('private') else 'privado'
        t.item('✗' if pior[2] <= 1 else '!' if pior[2] == 2 else '·', pior[1], r['name'], t.p(vis, 'apagado'))
        rel.add(f'{r["full_name"]} ({vis})')
        for a in achados:
            rot, cor, _ = NIVEIS[a['nivel']]
            total[a['nivel']] += 1
            onde = a['caminho'] + (f':{a["linha"]}' if a['linha'] else '')
            if a['lugares'] > 1:
                onde += f' (+{a["lugares"] - 1})'
            larg = t.largura - 12
            onde_atual = 'no código atual' if a['atual'] else 'só no histórico'
            quando = (f'desde {a["desde"]} · ' if a['desde'] else '') + f'id {a["id"]}'
            t.escreve('    ' + t.p(f'{rot:<7}', cor, True) + ' ' + t.p(corta(a['nome'], larg), 'texto'))
            t.escreve(' ' * 12 + t.p(corta_esq(onde, larg), 'sub'))
            if a['regra'] == 'arquivo':
                t.escreve(' ' * 12 + t.p(onde_atual, 'apagado'))
            else:
                t.escreve(' ' * 12 + t.p(corta(mascara(a), larg - len(onde_atual) - 3), 'sub') + t.p(' · ' + onde_atual, 'apagado'))
            t.escreve(' ' * 12 + t.p(corta(quando, larg), 'apagado'))
            if a['dica']:
                for l in textwrap.wrap(a['dica'], larg):
                    t.escreve(' ' * 12 + t.p(l, 'apagado'))
            rel.add(f'  [{rot}] {a["nome"]} — {onde} — {mascara(a)} — {onde_atual} — {quando}'
                    + (f' — {a["dica"]}' if a['dica'] else ''))
        t.escreve()
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
        rel.add(f'FALHA {nome}: {erro}')
    t.escreve()
    if total:
        plural = {'critico': 'críticos', 'alto': 'altos', 'medio': 'médios', 'baixo': 'baixos', 'info': 'info'}
        partes = [t.p(f'{total[n]} ' + (NIVEIS[n][0].lower() if total[n] == 1 else plural[n]), NIVEIS[n][1])
                  for n in NIVEIS if total[n]]
        t.titulo('resumo')
        t.partes(partes + [t.p(f'{limpos} repositório{"s" if limpos != 1 else ""} limpo{"s" if limpos != 1 else ""}', 'apagado')])
        if total['critico'] or total['alto']:
            t.escreve()
            t.paragrafo('O que fazer: revogue a chave no painel do serviço e gere outra. Apagar do histórico '
                        'não desfaz o vazamento — em repositório público, robôs copiam chaves em minutos.', 4, 'texto')
        t.paragrafo(f'Falso positivo? Ponha o id em {caminho_curto(CASA / "segredos-ignorados.txt")} (um por linha).', 4, 'apagado')
    else:
        t.ok(f'Nenhum segredo encontrado em {limpos} repositórios.')
    rel.add('', f'{sum(total.values())} achados, {limpos} repositórios limpos')
    t.nota(f'relatório: {caminho_curto(rel.salva(), t.largura - 16)}', 4)


# ═══════════════════════════════ 2. branches ═══════════════════════════════

def analisa_branches(gh, r):
    full, padrao = r['full_name'], r['default_branch']
    branches = [b for b in gh.paginas(f'/repos/{full}/branches') if b['name'] != padrao]
    if not branches:
        return []
    abertos, mesclados = set(), {}
    for p in gh.paginas(f'/repos/{full}/pulls?state=open'):
        if (p.get('head') or {}).get('repo') and p['head']['repo']['full_name'] == full:
            abertos.add(p['head']['ref'])
    for p in gh.json(f'/repos/{full}/pulls?state=closed&per_page=100&sort=updated&direction=desc') or []:
        if p.get('merged_at') and (p.get('head') or {}).get('repo') and p['head']['repo']['full_name'] == full:
            mesclados.setdefault(p['head']['ref'], (p['number'], p['head']['sha']))
    saida = []
    for b in branches:
        nome, sha = b['name'], b['commit']['sha']
        item = {'nome': nome, 'sha': sha, 'apagar': False}
        if b.get('protected'):
            item['motivo'] = 'protegida'
        elif nome in abertos:
            item['motivo'] = 'tem PR aberto'
        else:
            cmp = gh.json(f'/repos/{full}/compare/{quote(padrao, safe="")}...{quote(nome, safe="")}')
            frente = cmp.get('ahead_by', 0)
            commits = cmp.get('commits') or []
            data = (commits[-1] if commits else cmp.get('merge_base_commit', {}))['commit']['committer']['date']
            item['data'] = data
            if frente == 0:
                item.update(apagar=True, motivo='tudo já está na ' + padrao)
            elif nome in mesclados and mesclados[nome][1] == sha:
                item.update(apagar=True, motivo=f'PR #{mesclados[nome][0]} mesclado')
            elif nome in mesclados:
                item['motivo'] = f'PR #{mesclados[nome][0]} mesclado, mas tem commits depois'
            else:
                item['motivo'] = f'{frente} commit{"s" if frente > 1 else ""} fora da {padrao} · {ha_quanto(data)}'
        saida.append(item)
    return saida


def ferramenta_branches(ctx):
    t, gh = ctx.t, ctx.gh
    if ctx.args.restaurar:
        return restaura_branches(ctx, Path(ctx.args.restaurar))
    repos = escolhe_repos(ctx, arquivados=False, precisa_login=not ctx.args.teste)
    if not repos:
        return
    res, falhas = em_paralelo(t, repos, lambda r: analisa_branches(gh, r), 'analisando', fios=6)
    por_nome = {r['name']: r for r in repos}
    apagar, manter = [], 0
    t.escreve()
    for nome in sorted(res, key=str.lower):
        itens = res[nome]
        if not itens:
            continue
        t.escreve('  ' + t.p(nome, 'texto', True) + t.p(f'  {len(itens)} branch' + ('es' if len(itens) > 1 else ''), 'apagado'))
        for b in sorted(itens, key=lambda b: not b['apagar']):
            if b['apagar']:
                t.item('✓', 'verde', b['nome'], t.p(b['motivo'], 'verde'), recuo=4)
                apagar.append((por_nome[nome], b))
            else:
                t.item('·', 'apagado', b['nome'], t.p(b['motivo'], 'apagado'), recuo=4, cor_nome='sub')
                manter += 1
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    t.escreve()
    sem_branch = sum(1 for v in res.values() if not v)
    t.titulo('resumo')
    t.partes([t.p(f'{len(apagar)} podem ser apagadas', 'verde'), t.p(f'{manter} ficam', 'sub'),
              t.p(f'{sem_branch} só com a branch principal', 'apagado')])
    if apagar and not ctx.args.teste and confirma(ctx, f'Apagar {len(apagar)} branch(es) no GitHub?'):
        CASA.joinpath('branches-apagadas').mkdir(parents=True, exist_ok=True)
        arq = CASA / 'branches-apagadas' / f'{carimbo()}.json'
        feitas = []
        with Progresso(t, len(apagar), 'apagando') as pr:
            for r, b in apagar:
                st, _ = gh.requisita(f'/repos/{r["full_name"]}/git/refs/heads/{quote(b["nome"], safe="/")}', metodo='DELETE')
                if st == 204:
                    feitas.append({'repo': r['full_name'], 'branch': b['nome'], 'sha': b['sha']})
                else:
                    t.erro(f'{r["name"]}/{b["nome"]}: GitHub respondeu {st}')
                pr.avanca(b['nome'])
        arq.write_text(json.dumps(feitas, indent=2), encoding='utf-8')
        t.ok(f'{len(feitas)} apagadas.')
        t.nota(f'para desfazer: python {Path(sys.argv[0]).name} branches --restaurar "{caminho_curto(arq)}"', 4)
    sem_auto = [r for r in repos if r.get('delete_branch_on_merge') is False]
    if sem_auto and not ctx.args.teste:
        t.escreve()
        t.paragrafo(f'{len(sem_auto)} repositórios não apagam a branch sozinhos depois do merge do PR. '
                    'Ligando essa opção, a faxina passa a ser automática.', 4, 'sub')
        if confirma(ctx, f'Ligar "apagar branch após o merge" nesses {len(sem_auto)}?'):
            ok = sum(1 for r in sem_auto
                     if gh.requisita(f'/repos/{r["full_name"]}', metodo='PATCH', corpo={'delete_branch_on_merge': True})[0] == 200)
            t.ok(f'ligado em {ok} repositórios.')


def restaura_branches(ctx, arq):
    t, gh = ctx.t, ctx.gh
    try:
        itens = json.loads(arq.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        t.erro(f'Não consegui ler {arq}: {e}')
        return
    t.prompt('branches', f'recriando {len(itens)} branch(es) de {arq.name}')
    if ctx.args.teste or not confirma(ctx, 'Recriar essas branches no GitHub?'):
        return
    for it in itens:
        st, _ = gh.requisita(f'/repos/{it["repo"]}/git/refs', metodo='POST',
                             corpo={'ref': f'refs/heads/{it["branch"]}', 'sha': it['sha']})
        detalhe = {201: t.p('recriada', 'verde'), 422: t.p('já existe', 'apagado')}.get(st, t.p(f'falhou ({st})', 'vermelho'))
        t.item('✓' if st == 201 else '·', 'verde' if st == 201 else 'apagado', f'{it["repo"].split("/")[-1]}/{it["branch"]}', detalhe)


# ═══════════════════════════════ 3. demos ═══════════════════════════════

HOSTS_DEMO = ('vercel.app', 'netlify.app', 'github.io', 'pages.dev', 'onrender.com', 'railway.app', 'fly.dev',
              'herokuapp.com', 'surge.sh', 'firebaseapp.com', 'web.app', 'glitch.me', 'kessleru.com.br')
PALAVRAS_DEMO = re.compile(r'(?i)demo|ao vivo|ver site|site|deploy|live|preview|acess|online|no ar')
SINAIS_404 = [
    ('deployment_not_found', 'o deploy não existe mais na Vercel'),
    ('the deployment could not be found', 'o deploy não existe mais na Vercel'),
    ('deployment_paused', 'deploy pausado na Vercel'),
    ('this deployment is temporarily paused', 'deploy pausado na Vercel'),
    ("there isn't a github pages site here", 'o GitHub Pages está desligado'),
    ('site not found · github pages', 'o GitHub Pages está desligado'),
    ("looks like you've followed a broken link", 'página não encontrada (Netlify)'),
    ('service suspended', 'serviço suspenso (Render)'),
    ('no such app', 'o app não existe (Heroku)'),
    ("there's nothing here, yet", 'o app não existe (Heroku)'),
]
ERROS_CURL = {6: 'o domínio não existe', 7: 'conexão recusada', 28: 'demorou mais de 20 s', 35: 'erro de HTTPS',
              47: 'redirecionamentos demais', 51: 'certificado HTTPS inválido', 52: 'o servidor não respondeu',
              56: 'a conexão caiu', 58: 'certificado HTTPS inválido', 60: 'certificado HTTPS inválido'}
CFG_DEPLOY = {'vercel.json', 'netlify.toml', 'firebase.json', 'render.yaml', 'fly.toml', 'CNAME'}


def links_de_demo(md, repo=''):
    achados = []
    for alt, url in re.findall(r'\[!\[([^\]]*)\]\([^)]*\)\]\((https?://[^)\s]+)\)', md):
        achados.append((alt, url))
    for txt, url in re.findall(r'(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)', md):
        achados.append((txt, url))
    for url, txt in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', md, re.S | re.I):
        achados.append((re.sub(r'<[^>]+>', ' ', txt), url))
    saida = []
    for txt, url in achados:
        url = url.rstrip('.,;')
        host = (urlparse(url).hostname or '').lower()
        if not host or host.endswith(('github.com', 'shields.io', 'githubusercontent.com', 'npmjs.com', 'npmjs.org')):
            continue
        if re.search(r'\.(png|jpe?g|gif|svg|webp)(\?|$)', url, re.I):
            continue
        # host de deploy só conta sozinho se for seu (seu usuário ou o nome do repositório no endereço);
        # link de crédito para o github.io de outra pessoa não é a sua demo
        meu = DONO.lower() in host or (repo and re.sub(r'[^a-z0-9]', '', repo.lower())[:10] in re.sub(r'[^a-z0-9]', '', host))
        if PALAVRAS_DEMO.search(txt) or (host.endswith(HOSTS_DEMO) and meu):
            saida.append(url)
    return saida


def coleta_demos(gh, r):
    full, ramo = r['full_name'], r.get('default_branch') or 'main'
    urls = []
    if r.get('homepage'):
        urls.append((r['homepage'].strip(), 'campo site'))
    md = gh.bruto(full, 'README.md', ramo)
    if md is None:
        st, dados = gh.requisita(f'/repos/{full}/readme', aceita='application/vnd.github.raw')
        md = dados if st == 200 else b''
    for u in links_de_demo(texto(md), r['name']):
        urls.append((u, 'README'))
    if r.get('has_pages'):
        try:
            urls.append((gh.json(f'/repos/{full}/pages')['html_url'], 'GitHub Pages'))
        except (ErroAPI, KeyError, TypeError):
            pass
    vistos, unicos = set(), []
    for u, origem in urls:
        if not re.match(r'https?://', u):
            u = 'https://' + u
        chave = u.rstrip('/').lower()
        if chave not in vistos:
            vistos.add(chave)
            unicos.append((u, origem))
    cfg = []
    if not unicos:
        try:
            raiz = gh.json(f'/repos/{full}/contents/?ref={quote(ramo)}') or []
            cfg = sorted(x['name'] for x in raiz if x.get('name') in CFG_DEPLOY)
        except ErroAPI:
            pass
    return {'urls': unicos, 'cfg': cfg}


def checa_url(url):
    marca = '\n__ferramentas_git__'
    r = roda(['curl', '-sS', '-L', '--compressed', '--max-time', '20', '--max-redirs', '8',
              '-A', 'Mozilla/5.0 (ferramentas-git; verificador de demos)', '-o', '-',
              '-w', marca + '%{http_code} %{time_total}', url], tempo=30)
    corpo, _, fim = r.stdout.rpartition(marca.encode())
    partes = texto(fim).split()
    status = int(partes[0]) if partes and partes[0].isdigit() else 0
    tempo = float(partes[1].replace(',', '.')) if len(partes) > 1 else 0.0
    if r.returncode != 0 and status == 0:
        return {'nivel': 'quebrado', 'msg': ERROS_CURL.get(r.returncode, f'erro de rede (curl {r.returncode})'), 'tempo': tempo}
    pagina = corpo[:300_000].decode('utf-8', 'replace')
    m = re.search(r'<title[^>]*>(.*?)</title>', pagina, re.S | re.I)
    titulo = ' '.join(html.unescape(m.group(1)).split()) if m else ''
    baixo = pagina.lower()
    sinal = next((msg for s, msg in SINAIS_404 if s in baixo), None)
    if sinal:
        return {'nivel': 'quebrado', 'msg': sinal, 'tempo': tempo}
    if status in (401, 403):
        return {'nivel': 'protegido', 'msg': 'pede login (proteção de deploy?)', 'tempo': tempo}
    if status >= 400:
        return {'nivel': 'quebrado', 'msg': f'HTTP {status}', 'tempo': tempo}
    if tempo > 3:
        return {'nivel': 'lento', 'msg': f'lento: {tempo:.1f} s'.replace('.', ','), 'tempo': tempo, 'titulo': titulo}
    rapido = f'{int(tempo * 1000)} ms' if tempo < 1 else f'{tempo:.1f} s'.replace('.', ',')
    return {'nivel': 'ok', 'msg': rapido, 'tempo': tempo, 'titulo': titulo}


def ferramenta_demos(ctx):
    t, gh = ctx.t, ctx.gh
    repos = escolhe_repos(ctx, arquivados=True)
    if not repos:
        return
    coleta, falhas = em_paralelo(t, repos, lambda r: coleta_demos(gh, r), 'lendo READMEs', fios=6)
    todas = sorted({u for c in coleta.values() for u, _ in c['urls']})
    checagem, _ = em_paralelo(t, todas, checa_url, 'abrindo sites', nome=lambda u: u, fios=8)
    estilo = {'ok': ('✓', 'verde'), 'lento': ('!', 'amarelo'), 'protegido': ('!', 'amarelo'), 'quebrado': ('✗', 'vermelho')}
    rel = Relatorio('demos')
    cont = Counter()
    sem_demo, so_cfg, preencher = [], [], []
    t.escreve()
    for r in repos:
        c = coleta.get(r['name'])
        if c is None:
            continue
        if not c['urls']:
            (so_cfg if c['cfg'] else sem_demo).append((r['name'], c['cfg']))
            continue
        t.escreve('  ' + t.p(r['name'], 'texto', True))
        rel.add(r['full_name'])
        bom = None
        for u, origem in c['urls']:
            ch = checagem.get(u, {'nivel': 'quebrado', 'msg': 'não verificado'})
            ic, cor = estilo[ch['nivel']]
            cont[ch['nivel']] += 1
            host = re.sub(r'^https?://', '', u).rstrip('/')
            extra = ch['msg'] + (f' · "{ch["titulo"]}"' if ch.get('titulo') else '')
            t.item(ic, cor, host, t.p(corta(extra, max(12, t.largura - len(host) - 12)), cor if ch['nivel'] != 'ok' else 'apagado'), recuo=4)
            rel.add(f'  [{ch["nivel"]}] {u} ({origem}) — {extra}')
            if ch['nivel'] == 'ok' and bom is None:
                bom = u
        if not r.get('homepage') and bom:
            preencher.append((r, bom))
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    t.escreve()
    t.titulo('resumo')
    t.partes([t.p(f'{cont[n]} {rot}', estilo[n][1]) for n, rot in
              (('ok', 'no ar'), ('lento', 'lentos'), ('protegido', 'pedem login'), ('quebrado', 'fora do ar')) if cont[n]]
             + [t.p(f'{len(sem_demo)} sem demo', 'apagado')])
    if so_cfg:
        t.escreve()
        t.paragrafo('Têm configuração de deploy mas nenhum link de demo no README nem no campo "site":', 4, 'sub')
        for nome, cfg in so_cfg:
            t.item('?', 'amarelo', nome, t.p(', '.join(cfg), 'apagado'), recuo=4)
            rel.add(f'{nome}: tem {", ".join(cfg)} mas nenhum link de demo')
    if preencher and gh.token and not ctx.args.teste:
        t.escreve()
        t.paragrafo(f'{len(preencher)} repositórios têm demo no ar mas o campo "site" do GitHub está vazio '
                    '(é o link que aparece no topo da página do repositório).', 4, 'sub')
        for r, u in preencher:
            t.item('+', 'verde', r['name'], t.p(re.sub(r'^https?://', '', u), 'apagado'), recuo=4)
        if confirma(ctx, 'Preencher o campo "site" desses repositórios?'):
            ok = sum(1 for r, u in preencher
                     if gh.requisita(f'/repos/{r["full_name"]}', metodo='PATCH', corpo={'homepage': u})[0] == 200)
            t.ok(f'preenchido em {ok}.')
    t.nota(f'relatório: {caminho_curto(rel.salva(), t.largura - 16)}', 4)


# ═══════════════════════════════ 4. backup ═══════════════════════════════

def git_txt(pasta, *args, env=None):
    r = roda(['git', '-C', pasta] + list(args), env=env, tempo=600)
    return r.returncode, texto(r.stdout).strip(), texto(r.stderr).strip()


def clona_principal(full, ramo, pasta, env):
    r = roda(['git', 'clone', '-q', '--single-branch', '--branch', ramo, '--no-tags',
              f'https://github.com/{full}.git', pasta], env=env, tempo=1800)
    erro = texto(r.stderr)
    if r.returncode != 0:
        shutil.rmtree(pasta, ignore_errors=True)
        if 'empty repository' in erro or 'not found in upstream' in erro:
            return 'vazio', 'repositório vazio'
        raise RuntimeError(corta(erro.strip().splitlines()[-1] if erro.strip() else 'clone falhou', 70))
    return None


def backup_repo(r, destino, env):
    full, nome = r['full_name'], r['name']
    ramo = r.get('default_branch') or 'main'
    pasta = destino / nome
    if not pasta.exists():
        vazio = clona_principal(full, ramo, pasta, env)
        if vazio:
            return vazio
        _, n, _ = git_txt(pasta, 'rev-list', '--count', 'HEAD')
        return 'novo', f'{n} commits'
    cod, url, _ = git_txt(pasta, 'remote', 'get-url', 'origin')
    if cod != 0 or not re.sub(r'\.git$', '', url.lower().rstrip('/')).endswith(full.lower()):
        return 'conflito', 'a pasta tem outro repositório'
    _, local, _ = git_txt(pasta, 'branch', '--show-current')
    antigos = destino / '.antigos'
    if local != ramo:
        antigos.mkdir(exist_ok=True)
        shutil.move(str(pasta), str(antigos / f'{nome}-{carimbo()}'))
        clona_principal(full, ramo, pasta, env)
        return 'refeito', f'a principal mudou de {local or "?"} para {ramo}; cópia velha em .antigos'
    cod, _, erro = git_txt(pasta, 'fetch', '-q', '--no-tags', 'origin', ramo, env=env)
    if cod != 0:
        raise RuntimeError(corta(erro.splitlines()[-1] if erro else 'fetch falhou', 70))
    _, atual, _ = git_txt(pasta, 'rev-parse', 'HEAD')
    _, novo, _ = git_txt(pasta, 'rev-parse', 'FETCH_HEAD')
    if atual == novo:
        return 'em_dia', ''
    _, sujo, _ = git_txt(pasta, 'status', '--porcelain')
    if sujo:
        return 'sujo', 'tem arquivos mexidos à mão; não atualizei'
    if git_txt(pasta, 'merge-base', '--is-ancestor', atual, novo)[0] == 0:
        _, n, _ = git_txt(pasta, 'rev-list', '--count', f'{atual}..{novo}')
        git_txt(pasta, 'merge', '-q', '--ff-only', 'FETCH_HEAD')
        return 'atualizado', f'+{n} commit' + ('s' if n != '1' else '')
    # o histórico foi reescrito no GitHub (ex.: coautores): guarda a cópia velha e baixa de novo
    antigos.mkdir(exist_ok=True)
    shutil.move(str(pasta), str(antigos / f'{nome}-{carimbo()}'))
    clona_principal(full, ramo, pasta, env)
    return 'refeito', 'histórico mudou no GitHub; cópia velha em .antigos'


def escreve_indice(destino, repos):
    linhas = ['# Backup dos repositórios', '', f'Atualizado em {datetime.now():%d/%m/%Y %H:%M} pelo ferramentas-git.', '',
              '| Repositório | Branch | Último commit | Mensagem |', '| --- | --- | --- | --- |']
    for r in repos:
        pasta = destino / r['name']
        if not (pasta / '.git').exists():
            continue
        _, info, _ = git_txt(pasta, 'log', '-1', '--format=%ad\t%s', '--date=short')
        data, _, msg = info.partition('\t')
        vis = '🔒 ' if r.get('private') else ''
        linhas.append(f'| {vis}{r["name"]} | {r.get("default_branch")} | {data} | {msg.replace("|", "/")[:70]} |')
    (destino / 'INDICE.md').write_text('\n'.join(linhas) + '\n', encoding='utf-8')


def ferramenta_backup(ctx):
    t, gh = ctx.t, ctx.gh
    destino = Path(ctx.args.destino or ctx.estado.get('backup_destino') or Path.home() / 'backup-github').expanduser()
    destino.mkdir(parents=True, exist_ok=True)
    ctx.estado['backup_destino'] = str(destino)
    t.prompt('backup', f'pasta: {caminho_curto(destino, t.largura - 22)}')
    repos = escolhe_repos(ctx, arquivados=True)
    if not repos:
        return
    env = gh.env_git()
    res, falhas = em_paralelo(t, repos, lambda r: backup_repo(r, destino, env), 'baixando', fios=4)
    estilo = {'novo': ('+', 'verde', 'baixado'), 'atualizado': ('↑', 'verde', 'atualizado'), 'em_dia': ('✓', 'apagado', 'em dia'),
              'refeito': ('↻', 'amarelo', 'baixado de novo'), 'sujo': ('!', 'amarelo', 'pulado'),
              'conflito': ('!', 'vermelho', 'conflito'), 'vazio': ('·', 'apagado', 'vazio')}
    cont = Counter()
    t.escreve()
    for r in repos:
        if r['name'] not in res:
            continue
        st, det = res[r['name']]
        ic, cor, rot = estilo[st]
        cont[st] += 1
        if st == 'em_dia':
            continue
        t.item(ic, cor, r['name'], t.p(rot + (f' · {det}' if det else ''), cor if st != 'novo' else 'sub'))
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    nomes = {r['name'] for r in repos}
    orfaos = sorted(p.name for p in destino.iterdir() if p.is_dir() and not p.name.startswith('.')
                    and (p / '.git').exists() and p.name not in nomes) if not ctx.args.repos else []
    if orfaos:
        t.escreve()
        t.paragrafo('Só existem no backup (apagados ou renomeados no GitHub, mantidos aqui):', 4, 'sub')
        for o in orfaos:
            t.item('·', 'apagado', o, recuo=4, cor_nome='sub')
    escreve_indice(destino, repos)
    t.escreve()
    t.titulo('resumo')
    plural = {'novo': 'baixados', 'atualizado': 'atualizados', 'refeito': 'baixados de novo', 'em_dia': 'em dia',
              'sujo': 'pulados', 'vazio': 'vazios'}
    partes = [f'{cont[k]} ' + (estilo[k][2] if cont[k] == 1 else plural[k])
              for k in ('novo', 'atualizado', 'refeito', 'em_dia', 'sujo', 'vazio') if cont[k]]
    t.partes([t.p(x, 'texto') for x in partes])
    t.escreve('    ' + t.p(f'{humano(tamanho_pasta(destino))} em {caminho_curto(destino, t.largura - 18)}', 'apagado'))


# ═══════════════════════════════ 5. deps ═══════════════════════════════

RE_VER = re.compile(r'^\s*[v=]?(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?(?:-([0-9A-Za-z.-]+))?')
SEVERIDADE = {'critical': ('crítica', 'vermelho', 0), 'high': ('alta', 'pessego', 1),
              'moderate': ('moderada', 'amarelo', 2), 'low': ('baixa', 'azul', 3), 'info': ('info', 'apagado', 4)}
LOCKFILES = ('package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock')


def sev_txt(sev, n):
    rotulo = SEVERIDADE[sev][0]
    return f'{n} {rotulo}' + ('s' if n > 1 and rotulo != 'info' else '')


def chave_ver(v):
    m = RE_VER.match(v or '')
    if not m:
        return None
    num = [int(x) if x and x.isdigit() else 0 for x in (m.group(1), m.group(2), m.group(3))]
    pre = m.group(4)
    if pre is None:
        return (*num, 1, ())
    return (*num, 0, tuple((0, int(p), '') if p.isdigit() else (1, 0, p) for p in pre.split('.')))


def satisfaz(versao, faixa):
    kv = chave_ver(versao)
    if kv is None:
        return False
    for alt in faixa.split('||'):
        alt = alt.strip()
        if alt in ('', '*'):
            return True
        ok = True
        for op, ver in re.findall(r'(<=|>=|<|>|=)?\s*(v?\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?)', alt):
            kc = chave_ver(ver)
            if kc is None:
                continue
            if (op == '<' and not kv < kc) or (op == '<=' and not kv <= kc) or (op == '>' and not kv > kc) \
                    or (op == '>=' and not kv >= kc) or (op in ('', '=') and kv[:3] != kc[:3]):
                ok = False
                break
        if ok:
            return True
    return False


def defasagem(atual, ultima):
    a, u = chave_ver(atual), chave_ver(ultima)
    if not a or not u or a >= u:
        return None
    if u[0] > a[0] or (a[0] == 0 and u[1] > a[1]):
        return 'major'
    return 'minor' if u[1] > a[1] else 'patch'


def limpa_ver(v):
    v = (v or '').strip().strip('\'"').split('(')[0]
    return None if not v or v.startswith(('link:', 'file:', 'workspace:')) else v


def le_npm_lock(txt):
    d = json.loads(txt)
    todos, topo = defaultdict(set), {}
    if d.get('packages'):
        for chave, info in d['packages'].items():
            if not chave or info.get('link') or not info.get('version'):
                continue
            nome = info.get('name') or chave.rsplit('node_modules/', 1)[-1]
            todos[nome].add(info['version'])
            if chave.count('node_modules/') == 1:
                topo.setdefault(nome, info['version'])
    else:
        def anda(deps, nivel):
            for nome, info in (deps or {}).items():
                if info.get('version'):
                    todos[nome].add(info['version'])
                    if nivel == 0:
                        topo.setdefault(nome, info['version'])
                anda(info.get('dependencies'), nivel + 1)
        anda(d.get('dependencies'), 0)
    return todos, topo


def le_pnpm_lock(txt):
    todos, topo = defaultdict(set), {}
    secao = tipo = dep = None
    for linha in txt.splitlines():
        if not linha.strip() or linha.lstrip().startswith('#'):
            continue
        ind = len(linha) - len(linha.lstrip(' '))
        s = linha.strip()
        if ind == 0:
            secao, tipo, dep = s.rstrip(':'), None, None
            continue
        if secao in ('packages', 'snapshots') and ind == 2 and s.endswith(':'):
            chave = s[:-1].strip('\'"').lstrip('/').split('(')[0]
            if '@' in chave[1:]:
                i = chave.rindex('@')
                nome, v = chave[:i], chave[i + 1:]
            elif '/' in chave[1:]:
                nome, v = chave.rsplit('/', 1)
            else:
                continue
            v = limpa_ver(v.split('_')[0])
            if v:
                todos[nome].add(v)
        elif secao == 'importers':
            if ind == 4:
                tipo = s.rstrip(':')
            elif ind == 6 and tipo in ('dependencies', 'devDependencies', 'optionalDependencies'):
                if s.endswith(':'):
                    dep = s[:-1].strip('\'"')
                else:
                    n, _, v = s.partition(':')
                    if limpa_ver(v):
                        topo.setdefault(n.strip('\'"'), limpa_ver(v))
            elif ind == 8 and s.startswith('version:') and dep and limpa_ver(s[8:]):
                topo.setdefault(dep, limpa_ver(s[8:]))
        elif secao in ('dependencies', 'devDependencies', 'optionalDependencies'):
            if ind == 2:
                if s.endswith(':'):
                    dep = s[:-1].strip('\'"')
                else:
                    n, _, v = s.partition(':')
                    if limpa_ver(v):
                        topo.setdefault(n.strip('\'"'), limpa_ver(v))
            elif ind == 4 and s.startswith('version:') and dep and limpa_ver(s[8:]):
                topo.setdefault(dep, limpa_ver(s[8:]))
    return todos, topo


def le_yarn_lock(txt, diretas):
    todos, por_faixa = defaultdict(set), {}
    specs = None
    for linha in txt.splitlines():
        if not linha.strip() or linha.startswith('#'):
            continue
        if not linha.startswith(' ') and linha.rstrip().endswith(':'):
            specs = [x.strip().strip('"') for x in linha.rstrip()[:-1].split(',')]
        elif specs and linha.strip().startswith('version'):
            m = re.match(r'version:?\s+"?([^"\s]+)"?', linha.strip())
            if m:
                for sp in specs:
                    i = sp.rindex('@') if '@' in sp[1:] else len(sp)
                    nome, faixa = sp[:i], sp[i + 1:].replace('npm:', '')
                    todos[nome].add(m.group(1))
                    por_faixa[(nome, faixa)] = m.group(1)
            specs = None
    topo = {}
    for nome, faixa in diretas.items():
        v = por_faixa.get((nome, faixa)) or (max(todos[nome], key=lambda x: chave_ver(x) or ()) if todos.get(nome) else None)
        if v:
            topo[nome] = v
    return todos, topo


def acha_projetos(caminhos):
    pkgs = sorted(c for c in caminhos if c.rsplit('/', 1)[-1] == 'package.json' and 'node_modules/' not in c)
    locks = {}
    for c in caminhos:
        base = c.rsplit('/', 1)[-1]
        if base in LOCKFILES and 'node_modules/' not in c:
            pasta = c.rsplit('/', 1)[0] if '/' in c else ''
            if pasta not in locks or LOCKFILES.index(base) < LOCKFILES.index(locks[pasta].rsplit('/', 1)[-1]):
                locks[pasta] = c
    projetos = {}
    for p in pkgs:
        pasta = p.rsplit('/', 1)[0] if '/' in p else ''
        dono, cand = None, pasta
        while True:
            if cand in locks:
                dono = cand
                break
            if not cand:
                break
            cand = cand.rsplit('/', 1)[0] if '/' in cand else ''
        chave = dono if dono is not None else pasta
        projetos.setdefault(chave, {'lock': locks.get(dono) if dono is not None else None, 'pkgs': []})['pkgs'].append(p)
    return projetos


def analisa_deps_repo(gh, r):
    full, ramo = r['full_name'], r.get('default_branch') or 'main'
    try:
        arvore = gh.json(f'/repos/{full}/git/trees/{quote(ramo)}?recursive=1')
    except ErroAPI as e:
        if e.status in (404, 409):
            return []
        raise
    caminhos = [x['path'] for x in arvore.get('tree', []) if x.get('type') == 'blob']
    saida = []
    for pasta, info in sorted(acha_projetos(caminhos).items()):
        diretas = {}
        for p in info['pkgs']:
            try:
                pj = json.loads(texto(gh.bruto(full, p, ramo) or b'{}'))
            except ValueError:
                continue
            for campo in ('dependencies', 'devDependencies', 'optionalDependencies'):
                for n, v in (pj.get(campo) or {}).items():
                    if isinstance(v, str) and not re.match(r'(file|link|workspace|git\+|github:|https?):', v):
                        diretas.setdefault(n, v)
        if not diretas:
            continue
        todos, topo, gerenciador = defaultdict(set), {}, 'sem lockfile'
        if info['lock']:
            bruto = texto(gh.bruto(full, info['lock'], ramo) or b'')
            base = info['lock'].rsplit('/', 1)[-1]
            try:
                if base in ('package-lock.json', 'npm-shrinkwrap.json'):
                    todos, topo = le_npm_lock(bruto)
                    gerenciador = 'npm'
                elif base == 'pnpm-lock.yaml':
                    todos, topo = le_pnpm_lock(bruto)
                    gerenciador = 'pnpm'
                else:
                    todos, topo = le_yarn_lock(bruto, diretas)
                    gerenciador = 'yarn'
            except (ValueError, KeyError):
                gerenciador = 'lockfile ilegível'
        versoes_diretas = {}
        for n, faixa in diretas.items():
            v = topo.get(n)
            if not v:
                m = re.search(r'\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?', faixa)
                v = m.group(0) if m else None
                if v and not todos.get(n):
                    todos[n].add(v)
            if v:
                versoes_diretas[n] = v
        saida.append({'pasta': pasta or '.', 'gerenciador': gerenciador, 'diretas': versoes_diretas,
                      'todos': {k: sorted(v) for k, v in todos.items()}})
    return saida


def audita(gh, todos):
    corpo = {n: vs for n, vs in todos.items() if vs}
    if not corpo:
        return []
    st, dados = gh.requisita('https://registry.npmjs.org/-/npm/v1/security/advisories/bulk', metodo='POST', corpo=corpo, tempo=60)
    if st != 200:
        raise RuntimeError(f'base de vulnerabilidades do npm respondeu {st}')
    achados = []
    for nome, avisos in json.loads(dados).items():
        for a in avisos:
            afetadas = [v for v in corpo.get(nome, []) if satisfaz(v, a.get('vulnerable_versions', ''))]
            if afetadas:
                achados.append({'pacote': nome, 'versoes': afetadas, 'sev': a.get('severity', 'info'),
                                'titulo': a.get('title', ''), 'url': a.get('url', ''), 'id': a.get('id')})
    return achados


def ultima_versao(gh, nome, cache, trava):
    with trava:
        if nome in cache:
            return cache[nome]
    st, dados = gh.requisita(f'https://registry.npmjs.org/{nome.replace("/", "%2F")}/latest', tempo=30)
    info = None
    if st == 200:
        try:
            d = json.loads(dados)
            info = {'versao': d.get('version'), 'descontinuado': d.get('deprecated')}
        except ValueError:
            pass
    with trava:
        cache[nome] = info
    return info


def ferramenta_deps(ctx):
    t, gh = ctx.t, ctx.gh
    repos = escolhe_repos(ctx, arquivados=False)
    if not repos:
        return
    projetos, falhas = em_paralelo(t, repos, lambda r: analisa_deps_repo(gh, r), 'lendo projetos', fios=6)
    lista = [(nome, p) for nome, ps in projetos.items() for p in ps]
    if not lista:
        t.ok('Nenhum projeto JavaScript encontrado.')
        return
    auditorias, f2 = em_paralelo(t, lista, lambda np: audita(gh, np[1]['todos']), 'checando vulnerabilidades',
                                 nome=lambda np: f'{np[0]}:{np[1]["pasta"]}', fios=4)
    falhas += f2
    cache, trava = {}, threading.Lock()
    pacotes = sorted({n for _, p in lista for n in p['diretas']})
    em_paralelo(t, pacotes, lambda n: ultima_versao(gh, n, cache, trava), 'conferindo versões', nome=lambda n: n, fios=10)
    rel = Relatorio('deps')
    linhas_resumo = []
    for nome, p in lista:
        vulns = auditorias.get(f'{nome}:{p["pasta"]}', [])
        # conta por pacote (com a pior falha dele), como o npm audit, e não por aviso
        por_pacote = {}
        for v in vulns:
            if v['pacote'] not in por_pacote or SEVERIDADE[v['sev']][2] < SEVERIDADE[por_pacote[v['pacote']]][2]:
                por_pacote[v['pacote']] = v['sev']
        cont = Counter(por_pacote.values())
        velhas = []
        abandonadas = []
        for n, v in p['diretas'].items():
            info = cache.get(n)
            if not info or not info['versao']:
                continue
            d = defasagem(v, info['versao'])
            if d:
                velhas.append((d, n, v, info['versao']))
            if info.get('descontinuado'):
                abandonadas.append(n)
        majors = [x for x in velhas if x[0] == 'major']
        risco = cont['critical'] * 100 + cont['high'] * 30 + cont['moderate'] * 5 + cont['low'] + len(majors) * 2 + len(abandonadas) * 3
        linhas_resumo.append((risco, nome, p, vulns, cont, velhas, majors, abandonadas))
    linhas_resumo.sort(key=lambda x: (-x[0], x[1].lower()))
    limpos = 0
    t.escreve()
    for risco, nome, p, vulns, cont, velhas, majors, abandonadas in linhas_resumo:
        rotulo = nome + ('' if p['pasta'] == '.' else f' · {p["pasta"]}')
        rel.add(f'{rotulo} ({p["gerenciador"]}): ' + ', '.join(sev_txt(s, cont[s]) for s in SEVERIDADE if cont[s])
                + f'; {len(velhas)} desatualizadas ({len(majors)} major)')
        if not vulns and not majors and not abandonadas:
            limpos += 1
            continue
        pior = min((SEVERIDADE[v['sev']][2] for v in vulns), default=9)
        cor = SEVERIDADE[[k for k, v in SEVERIDADE.items() if v[2] == pior][0]][1] if pior < 9 else 'amarelo'
        t.item('✗' if pior <= 1 else '!', cor, rotulo, t.p(p['gerenciador'], 'apagado'))
        if vulns:
            n_pac = sum(cont.values())
            t.partes([t.p(f'{n_pac} pacote{"s" if n_pac > 1 else ""} com falha:', 'sub')]
                     + [t.p(sev_txt(s, cont[s]), SEVERIDADE[s][1]) for s in SEVERIDADE if cont[s]], recuo=6)
            vistos = set()
            for v in sorted(vulns, key=lambda v: SEVERIDADE[v['sev']][2]):
                if v['pacote'] in vistos or len(vistos) >= 3:
                    continue
                vistos.add(v['pacote'])
                tipo = 'direta' if v['pacote'] in p['diretas'] else 'indireta'
                linha = f'↳ {v["pacote"]} {v["versoes"][0]} ({tipo}) · {v["titulo"]}'
                t.escreve('      ' + t.p(corta(linha, t.largura - 8), 'sub'))
            for v in vulns:
                rel.add(f'    [{SEVERIDADE[v["sev"]][0]}] {v["pacote"]} {", ".join(v["versoes"])} — {v["titulo"]} — {v["url"]}')
        if majors:
            exemplos = ', '.join(f'{n} {a}→{u}' for _, n, a, u in sorted(majors)[:3])
            t.escreve('      ' + t.p(corta(f'{len(velhas)} desatualizadas, {len(majors)} major: {exemplos}', t.largura - 8), 'apagado'))
            for d, n, a, u in sorted(velhas):
                rel.add(f'    [{d}] {n} {a} → {u}')
        if abandonadas:
            t.escreve('      ' + t.p(corta('descontinuadas: ' + ', '.join(abandonadas), t.largura - 8), 'amarelo'))
            rel.add('    descontinuadas: ' + ', '.join(abandonadas))
        t.escreve()
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    total = Counter()
    for x in linhas_resumo:
        total.update(x[4])
    t.escreve()
    t.titulo('resumo')
    t.partes([t.p(sev_txt(s, total[s]), SEVERIDADE[s][1]) for s in SEVERIDADE if total[s]]
             or [t.p('nenhuma vulnerabilidade', 'verde')])
    t.partes([t.p(f'{len(lista)} projetos', 'apagado'), t.p(f'{limpos} sem pendências', 'apagado')])
    t.paragrafo('Nada foi alterado. Para corrigir: npm audit fix (ou pnpm audit --fix); as majors, atualize uma de '
                'cada vez e rode os testes.', 4, 'apagado')
    t.nota(f'relatório: {caminho_curto(rel.salva(), t.largura - 16)}', 4)


# ═══════════════════════════════ 6. coautores ═══════════════════════════════

PADRAO_MSG = re.compile(r'Co-Authored-By:.*(claude|anthropic)|Claude-Session:|Generated with \[?Claude Code|claude\.ai/code/session_', re.I)
PADRAO_AUTOR = re.compile(r'anthropic\.com|^claude <', re.I)

MSG_CB = r'''
import re
padroes = [
    rb'(?im)^[ \t]*Co-Authored-By:[^\n]*(?:claude|anthropic)[^\n]*\n?',
    rb'(?im)^[ \t]*Claude-Session:[^\n]*\n?',
    rb'(?im)^[^\n]*Generated with \[?Claude Code[^\n]*\n?',
    rb'(?im)^[ \t]*https://claude\.ai/code/session_[^\n]*\n?',
]
novo = message
for p in padroes:
    novo = re.sub(p, b'', novo)
if novo == message:
    return message
novo = re.sub(rb'\n{3,}', b'\n\n', novo).rstrip() + b'\n'
return novo if novo.strip() else message
'''

COMMIT_CB = r'''
import os
nome = os.environ['AUTOR_NOME'].encode()
email = os.environ['AUTOR_EMAIL'].encode()
def eh_claude(n, e):
    return b'anthropic.com' in e.lower() or n.strip().lower() == b'claude'
if eh_claude(commit.author_name, commit.author_email):
    commit.author_name, commit.author_email = nome, email
if eh_claude(commit.committer_name, commit.committer_email):
    commit.committer_name, commit.committer_email = nome, email
'''


def prepara_filter_repo(t):
    if roda(['git', 'filter-repo', '--version']).returncode == 0:
        return ['git', 'filter-repo']
    t.nota('preparando o git-filter-repo (só na primeira vez)…')
    roda([sys.executable, '-m', 'pip', 'install', '--user', '--quiet', 'git-filter-repo'], tempo=300)
    r = roda([sys.executable, '-c', 'import git_filter_repo; print(git_filter_repo.__file__)'])
    caminho = texto(r.stdout).strip() if r.returncode == 0 else ''
    if not caminho:
        destino = CASA / 'bin' / 'git_filter_repo.py'
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            roda(['curl', '-fsSL', '-o', destino,
                  'https://raw.githubusercontent.com/newren/git-filter-repo/main/git-filter-repo'], tempo=120)
        caminho = str(destino) if destino.exists() else ''
    if not caminho or roda([sys.executable, caminho, '--version']).returncode != 0:
        return None
    return [sys.executable, caminho]


def conta_marcas(pasta):
    msgs = texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%B']).stdout)
    autores = texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%an <%ae>%n%cn <%ce>']).stdout)
    return (sum(1 for l in msgs.splitlines() if PADRAO_MSG.search(l))
            + sum(1 for l in autores.splitlines() if PADRAO_AUTOR.search(l)))


def dono_do_repo(pasta):
    c = Counter(l for l in texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%an|%ae']).stdout).splitlines()
                if l and not re.search(r'anthropic\.com|^claude\||\[bot\]|noreply@github\.com', l, re.I))
    if not c:
        return DONO, f'{DONO}@users.noreply.github.com'
    nome, _, email = c.most_common(1)[0][0].partition('|')
    return os.environ.get('AUTOR_NOME_FIXO', nome), os.environ.get('AUTOR_EMAIL_FIXO', email)


def limpa_coautoria(r, trabalho, backups, filtro, env):
    full, nome = r['full_name'], r['name']
    pasta = trabalho / f'{nome}.git'
    c = roda(['git', 'clone', '-q', '--bare', f'https://github.com/{full}.git', pasta], env=env, tempo=1800)
    if c.returncode != 0:
        raise RuntimeError('não consegui clonar')
    antes = conta_marcas(pasta)
    if antes == 0:
        shutil.rmtree(pasta, ignore_errors=True)
        return 'limpo', 0, 0
    roda(['git', '-C', pasta, 'bundle', 'create', backups / f'{nome}.bundle', '--all'])
    autor, email = dono_do_repo(pasta)
    commits = texto(roda(['git', '-C', pasta, 'rev-list', '--all', '--count']).stdout).strip()
    f = roda(filtro + ['--force', '--quiet', '--message-callback', MSG_CB, '--commit-callback', COMMIT_CB],
             cwd=pasta, env=dict(env, AUTOR_NOME=autor, AUTOR_EMAIL=email), tempo=1800)
    if f.returncode != 0:
        raise RuntimeError('o git-filter-repo falhou')
    depois = conta_marcas(pasta)
    commits_depois = texto(roda(['git', '-C', pasta, 'rev-list', '--all', '--count']).stdout).strip()
    if depois or commits != commits_depois:
        raise RuntimeError(f'verificação falhou (restaram {depois}, commits {commits}→{commits_depois})')
    roda(['git', '-C', pasta, 'remote', 'add', 'origin', f'https://github.com/{full}.git'])
    return 'pronto', antes, int(commits)


def ferramenta_coautores(ctx):
    t, gh = ctx.t, ctx.gh
    repos = escolhe_repos(ctx, arquivados=False, precisa_login=not ctx.args.teste)
    if not repos:
        return
    filtro = prepara_filter_repo(t)
    if not filtro:
        t.erro('Não consegui preparar o git-filter-repo (precisa de pip ou de internet).')
        return
    c = carimbo()
    trabalho, backups = CASA / 'trabalho' / f'coautores-{c}', CASA / 'backups' / f'coautores-{c}'
    trabalho.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)
    env = gh.env_git()
    res, falhas = em_paralelo(t, repos, lambda r: limpa_coautoria(r, trabalho, backups, filtro, env), 'limpando', fios=4)
    prontos = [r for r in repos if res.get(r['name'], ('',))[0] == 'pronto']
    t.escreve()
    for r in prontos:
        _, marcas, commits = res[r['name']]
        t.item('✓', 'verde', r['name'], t.p(f'{marcas} marca{"s" if marcas > 1 else ""} · {commits} commits iguais', 'sub'))
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    limpos = sum(1 for v in res.values() if v[0] == 'limpo')
    t.escreve()
    t.titulo('resumo')
    t.partes([t.p(f'{len(prontos)} com coautoria do Claude', 'verde' if prontos else 'texto'),
              t.p(f'{limpos} já limpos', 'apagado')])
    if not prontos:
        shutil.rmtree(trabalho, ignore_errors=True)
        shutil.rmtree(backups, ignore_errors=True)
        return
    t.nota(f'backup do histórico original: {caminho_curto(backups, t.largura - 36)}', 4)
    if ctx.args.teste:
        t.nota('modo teste: nada foi enviado ao GitHub.', 4)
        return
    if not confirma(ctx, f'Sobrescrever o histórico desses {len(prontos)} no GitHub (force-push de todas as branches e tags)?'):
        t.nota('cancelado; nada foi enviado.', 4)
        return
    enviados = 0
    with Progresso(t, len(prontos), 'enviando') as pr:
        for r in prontos:
            pasta = trabalho / f'{r["name"]}.git'
            a = roda(['git', '-C', pasta, 'push', '-q', '--force', '--all', 'origin'], env=env, tempo=1800)
            b = roda(['git', '-C', pasta, 'push', '-q', '--force', '--tags', 'origin'], env=env, tempo=1800) if a.returncode == 0 else a
            if a.returncode == 0 and b.returncode == 0:
                enviados += 1
                shutil.rmtree(pasta, ignore_errors=True)
            else:
                erro = texto(a.stderr or b.stderr)
                motivo = ('o token precisa da permissão workflow' if 'workflow' in erro
                          else 'branch protegida: libere o force-push em Settings > Rules' if 'protected' in erro
                          else corta(erro.strip().splitlines()[-1] if erro.strip() else 'push recusado', 60))
                t.erro(f'{r["name"]}: {motivo}')
            pr.avanca(r['name'])
    t.ok(f'{enviados} enviados.')
    t.nota('A lista "Contributors" da página do GitHub demora algumas horas para se atualizar.', 4)
    t.nota(f'para desfazer: git clone --mirror "{caminho_curto(backups)}/<repo>.bundle" x && cd x && '
           f'git push --mirror --force https://github.com/{DONO}/<repo>.git', 4)


# ═══════════════════════════════ menu e entrada ═══════════════════════════════

EXECUTA = {'segredos': ferramenta_segredos, 'branches': ferramenta_branches, 'demos': ferramenta_demos,
           'backup': ferramenta_backup, 'deps': ferramenta_deps, 'coautores': ferramenta_coautores}


def roda_ferramenta(ctx, cmd):
    arquivo, desc = next((a, d) for c, a, d in FERRAMENTAS if c == cmd)
    ctx.t.aba(arquivo, desc)
    inicio = time.time()
    EXECUTA[cmd](ctx)
    ctx.estado[cmd] = agora_iso()
    salva_estado(ctx.estado)
    ctx.t.nota(f'concluído em {time.time() - inicio:.0f} s', 4)


def menu(ctx):
    t = ctx.t
    while True:
        t.limpa()
        t.cabecalho('início')
        t.titulo('Olá! O que vamos fazer hoje?')
        t.escreve()
        for i, (cmd, _, desc) in enumerate(FERRAMENTAS, 1):
            quando = ha_quanto(ctx.estado.get(cmd, ''))
            esq = f'  {t.p(str(i), "verde", True)}  {t.p(f"{cmd:<10}", "texto")} {t.p(corta(desc, t.largura - 16), "sub")}'
            if quando and vlen(esq) + len(quando) + 2 <= t.largura:
                esq += ' ' * (t.largura - vlen(esq) - len(quando)) + t.p(quando, 'apagado')
            t.escreve(esq)
        t.escreve(f'  {t.p("0", "verde", True)}  {t.p("sair", "apagado")}')
        t.escreve()
        escolha = t.pergunta('início').strip().lower()
        if escolha in ('0', 'q', 'sair', ''):
            return
        cmd = FERRAMENTAS[int(escolha) - 1][0] if escolha.isdigit() and 0 < int(escolha) <= len(FERRAMENTAS) else (
            escolha if escolha in EXECUTA else None)
        if not cmd:
            continue
        t.escreve()
        t.nota('Enter = todos os repositórios, ou digite os nomes separados por espaço', 2)
        ctx.args.repos = t.pergunta(f'{cmd}/repos').split()
        if cmd in ('branches', 'coautores'):
            t.nota('só simular primeiro, sem alterar nada? s = sim, Enter = não', 2)
            ctx.args.teste = t.pergunta(f'{cmd}/simular').strip().lower() in ('s', 'sim')
        roda_ferramenta(ctx, cmd)
        t.escreve()
        t.espera('Enter para voltar ao menu')


def main():
    p = argparse.ArgumentParser(prog='ferramentas-git', description='Ferramentas para todos os seus repositórios do GitHub.')
    p.add_argument('comando', nargs='?', choices=list(EXECUTA), help='sem comando, abre o menu')
    p.add_argument('repos', nargs='*', help='só esses repositórios (padrão: todos)')
    p.add_argument('--teste', action='store_true', help='não altera nada no GitHub')
    p.add_argument('--sim', action='store_true', help='não pede confirmação')
    p.add_argument('--destino', help='backup: pasta de destino (padrão ~/backup-github)')
    p.add_argument('--forks', action='store_true', help='inclui forks')
    p.add_argument('--restaurar', metavar='ARQUIVO', help='branches: recria as branches apagadas')
    p.add_argument('--sem-login', action='store_true', help='não usa token; só o acesso que o git já tem')
    p.add_argument('--ascii', action='store_true', help='só caracteres simples (terminal que mostra quadradinhos)')
    p.add_argument('--sem-cor', action='store_true', help='sem cores')
    args = p.parse_args()
    t = Terminal(ascii_forcado=args.ascii, sem_cor=args.sem_cor)
    ctx = Ctx(args, t)
    for ferramenta in ('git', 'curl'):
        if not shutil.which(ferramenta):
            t.erro(f'Preciso do {ferramenta} instalado.')
            return 1
    try:
        if args.comando:
            t.cabecalho(args.comando)
            roda_ferramenta(ctx, args.comando)
        else:
            menu(ctx)
    except KeyboardInterrupt:
        t.para_vivo()
        t.escreve()
        t.aviso('interrompido.')
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
