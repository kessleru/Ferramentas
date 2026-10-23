#!/usr/bin/env python3
# ferramentas — onze ferramentas num arquivo só, em duas partes.
#
#   python ferramentas.py                abre o menu
#
#   PARTE 1 · seus repositórios no GitHub
#   python ferramentas.py segredos       caça chaves e senhas no histórico
#   python ferramentas.py branches       apaga branches já mescladas
#   python ferramentas.py demos          confere se os sites das demos estão no ar
#   python ferramentas.py backup         baixa/atualiza a branch principal de todos
#   python ferramentas.py deps           vulnerabilidades e dependências velhas
#   python ferramentas.py coautores      tira a coautoria do Claude do histórico
#
#   PARTE 2 · seu computador e seus sites
#   python ferramentas.py faxina         libera espaço de projetos parados (node_modules, venv, builds, caches)
#   python ferramentas.py portas         quem está usando cada porta, e encerra quem você escolher
#   python ferramentas.py raiox SITE     acessibilidade, SEO, desempenho, segurança e links de um site
#   python ferramentas.py peso SITE      o que cada página carrega, o que mais pesa e quanto dá para economizar
#   python ferramentas.py atualizar      atualiza sistema, linguagens, pacotes globais e extensões do PC
#
# Opções de todas: --teste (só mostra, não altera nada), --sim (não pergunta), --ascii, --sem-cor.
# Cada ferramenta tem as suas: python ferramentas.py backup --help
#
# Precisa de Python 3.8+. A parte 1 usa git e curl; o raio-x e o peso usam curl.
# O git-filter-repo (só para o coautores) se instala sozinho.

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
import stat
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

def _pasta_da_casa():
    escolhida = os.environ.get('FERRAMENTAS_CASA') or os.environ.get('FERRAMENTAS_GIT_CASA')
    if escolhida:
        return Path(escolhida)
    nova, velha = Path.home() / '.ferramentas', Path.home() / '.ferramentas-git'
    # a pasta se chamava .ferramentas-git: leva junto relatórios, cache, backups e o estado
    if velha.is_dir() and not nova.exists():
        try:
            velha.rename(nova)
        except OSError:
            return velha
    return nova


CASA = _pasta_da_casa()

# ═══════════════════════════════ núcleo: utilidades ═══════════════════════════════

def agora_iso():
    return datetime.now(timezone.utc).isoformat()


def carimbo():
    return datetime.now().strftime('%Y-%m-%d_%H%M%S')


def ha_quanto_iso(iso):
    try:
        t = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return ''
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
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


def roda(cmd, cwd=None, entrada=None, env=None, tempo=None):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd, input=entrada, env=env,
                              capture_output=True, timeout=tempo)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or b'', b'tempo esgotado')
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, b'', f'{cmd[0]} não encontrado'.encode())
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 126, b'', str(e).encode())


def tamanho_pasta(p):
    total = 0
    for raiz, _, arquivos in os.walk(p):
        for a in arquivos:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total


def carrega_estado():
    try:
        estado = json.loads((CASA / 'estado.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return estado if isinstance(estado, dict) else {}


def salva_estado(estado):
    try:
        CASA.mkdir(parents=True, exist_ok=True)
        (CASA / 'estado.json').write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass  # sem gravar o estado, o menu só não mostra "há quanto tempo"; a ferramenta já rodou


# ═══════════════════════════════ núcleo: terminal ═══════════════════════════════

PALETA = {  # Catppuccin Frappé, a paleta do kessleru.com.br
    'texto': (198, 208, 245), 'sub': (165, 173, 206), 'apagado': (131, 139, 167),
    'superficie': (81, 87, 109), 'fundo': (65, 69, 89),
    'verde': (166, 209, 137), 'vermelho': (231, 130, 132), 'amarelo': (229, 200, 144),
    'pessego': (239, 159, 118), 'azul': (140, 170, 238), 'roxo': (202, 158, 230),
    'teal': (129, 200, 190), 'escuro': (35, 38, 52),
}
CORES16 = {'texto': 97, 'sub': 37, 'apagado': 90, 'superficie': 90, 'fundo': 90, 'verde': 92, 'vermelho': 91,
           'amarelo': 93, 'pessego': 33, 'azul': 94, 'roxo': 95, 'teal': 96, 'escuro': 30}
LOGO_SIMBOLO = [' ▄▀   █ ▀▄ ', '▀▄  ▄▀   ▄▀', '  ▀ ▀   ▀  ']
LOGO_NOME = ['█ █ █▀▀ █▀▀ █▀▀ █   █▀▀ █▀▄ █ █',
             '█▀▄ █▀  ▀▀█ ▀▀█ █   █▀  █▀▄ █ █',
             '▀ ▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀ ▀▀▀']
TROCA_SIMPLES = str.maketrans({'✓': '+', '✗': 'x', '↳': '>', '↻': '*', '↑': '^', '→': '->', '●': '•', '◆': '♦',
                               '◇': '♦', '›': '>', '╮': '┐', '╯': '┘'})  # ┌ └ ├ │ existem na fonte do console antigo
TROCA_ASCII = str.maketrans({'✓': '+', '✗': 'x', '·': '.', '…': '...', '─': '-', '●': '*', '◆': '>', '■': '#',
                             '█': '#', '▀': '"', '▄': '_', '↳': '>', '↑': '^', '↻': '*', '→': '->', '—': '-',
                             '•': '*', '♦': '>', '↓': 'v', '₂': '2', '🔒': '', '≈': '~', '×': 'x',
                             '◇': '*', '│': '|', '┌': '+', '└': '+', '›': '>', '╮': '+', '╯': '+', '├': '+'})
# cor e link clicável (OSC 8) não ocupam espaço na tela
ANSI = re.compile(r'\033\[[0-9;]*m|\033\]8;;[^\033]*\033\\')


def vlen(s):
    return len(ANSI.sub('', s))


def corta(s, n):
    s = str(s)
    return s if len(s) <= n else (s[:n - 1] + '…' if n > 1 else s[:max(n, 0)])


def corta_esq(s, n):
    if len(s) <= n:
        return s
    return '…' + s[-(n - 1):] if n > 1 else '…'[:max(n, 0)]


def corta_visivel(s, n):
    """Corta um texto com cores em n caracteres visíveis, sem quebrar as sequências de cor."""
    if vlen(s) <= n:
        return s
    saida, vistos, pos = [], 0, 0
    for m in ANSI.finditer(s):
        trecho = s[pos:m.start()]
        if vistos + len(trecho) >= n:
            saida.append(trecho[:max(0, n - vistos)])
            vistos = n
            break
        saida.append(trecho + m.group())
        vistos += len(trecho)
        pos = m.end()
    else:
        saida.append(s[pos:][:max(0, n - vistos)])
    return ''.join(saida) + ('\033[0m' if '\033[' in s else '')  # sem cor, nada de código de escape


def caminho_curto(p, n=None):
    s, casa = str(p), str(Path.home())
    if s.startswith(casa):
        s = '~' + s[len(casa):]
    s = s.replace('\\', '/')
    return corta_esq(s, n) if n else s


def humano(n):
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or u == 'TB':
            return f'{n:.0f} {u}' if u in ('B', 'KB') else f'{n:.1f} {u}'.replace('.', ',')
        n /= 1024


def _xterm256(r, g, b):
    niveis = [0, 95, 135, 175, 215, 255]

    def perto(c):
        return min(range(6), key=lambda i: abs(niveis[i] - c))

    ri, gi, bi = perto(r), perto(g), perto(b)
    d_cubo = (niveis[ri] - r) ** 2 + (niveis[gi] - g) ** 2 + (niveis[bi] - b) ** 2
    ci = max(0, min(23, int(round(((r + g + b) / 3 - 8) / 10))))
    d_cinza = sum((8 + ci * 10 - c) ** 2 for c in (r, g, b))
    return 232 + ci if d_cinza < d_cubo else 16 + 36 * ri + 6 * gi + bi


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
        self.cor = not sem_cor and ((self.tty and 'NO_COLOR' not in env and termo != 'dumb') or bool(env.get('FORCE_COLOR')))
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
        if ascii_forcado or env.get('FERRAMENTAS_ASCII') or env.get('FERRAMENTAS_GIT_ASCII') or sem_utf8:
            self.nivel = 'ascii'
        elif (os.name == 'nt' and not win_moderno) or termo == 'linux':
            self.nivel = 'simples'
        else:
            self.nivel = 'pleno'
        self.links = self.cor and self.tty and _aceita_links(env)
        # a guia lateral e os dois espaços depois dela ocupam duas colunas: o conteúdo é montado
        # para `largura` e cabe na tela
        self.largura = max(36, min(shutil.get_terminal_size((72, 24)).columns - 3, 78))
        self.trava = threading.RLock()
        self.vivo_txt = ''
        self.guia = False
        self._vazia = False
        self._caixa = None

    def _adapta(self, txt):
        if self.nivel == 'pleno':
            return txt
        if self.nivel == 'simples':
            return txt.translate(TROCA_SIMPLES)
        import unicodedata
        return unicodedata.normalize('NFKD', txt.translate(TROCA_ASCII)).encode('ascii', 'ignore').decode()

    def _rgb(self, rgb, fundo=False, nome=None):
        if self.modo_cor == 16:
            return f'\033[{CORES16.get(nome, 37) + (10 if fundo else 0)}m'
        camada = 48 if fundo else 38
        if self.modo_cor == 24:
            return f'\033[{camada};2;{rgb[0]};{rgb[1]};{rgb[2]}m'
        return f'\033[{camada};5;{_xterm256(*rgb)}m'

    def _cod(self, nome, fundo=False):
        return self._rgb(PALETA[nome], fundo, nome)

    def p(self, txt, cor=None, negrito=False, fundo=None):
        if not self.cor or (cor is None and not negrito and fundo is None):
            return str(txt)
        s = ('\033[1m' if negrito else '') + (self._cod(cor) if cor else '') + (self._cod(fundo, True) if fundo else '')
        return s + str(txt) + '\033[0m'

    def degrade(self, txt, cores, negrito=False):
        """Pinta cada coluna com uma cor entre as da lista (o logo, por exemplo)."""
        if not self.cor or self.modo_cor == 16:
            return self.p(txt, cores[0], negrito)
        pontos = [PALETA[c] for c in cores]
        saida, n = [], max(len(txt) - 1, 1)
        for i, ch in enumerate(txt):
            if ch == ' ':
                saida.append(ch)
                continue
            pos = i / n * (len(pontos) - 1)
            a, b = pontos[int(pos)], pontos[min(int(pos) + 1, len(pontos) - 1)]
            f = pos - int(pos)
            rgb = tuple(round(x + (y - x) * f) for x, y in zip(a, b))
            saida.append(self._rgb(rgb) + ch)
        return ('\033[1m' if negrito else '') + ''.join(saida) + '\033[0m'

    def selo(self, txt, cor):
        """Etiqueta com fundo colorido, como os PASS/FAIL do Vitest; sem cor vira [TEXTO]."""
        if not self.cor:
            return f'[{txt}]'
        return self.p(f' {txt} ', 'escuro', True, fundo=cor)

    def link(self, txt, alvo):
        # OSC 8: o texto vira clicável nos terminais que entendem; nos outros, fica só o texto
        if not self.links or not alvo:
            return txt
        if not re.match(r'[a-z]+://', str(alvo)):
            try:
                alvo = Path(alvo).resolve().as_uri()
            except (OSError, ValueError):
                return txt
        return f'\033]8;;{alvo}\033\\{txt}\033]8;;\033\\'

    def caminho(self, arq, n=None):
        return self.link(caminho_curto(arq, n), arq)

    def titulo_janela(self, txt):
        if self.tty and self.cor:
            sys.stdout.write(f'\033]0;{txt}\007')

    def _com_guia(self, txt):
        # dentro de um bloco, a linha ganha a guia lateral no lugar dos dois espaços do começo
        if not self.guia:
            return txt
        barra = ' ' + self.p('│', 'superficie')
        if not txt:
            return barra
        return barra + '  ' + (txt[2:] if txt.startswith('  ') else txt)

    def escreve(self, txt='', guia=True):
        if self._caixa is not None and guia:
            self._caixa['linhas'].append(txt)
            return
        vazia = not ANSI.sub('', txt).strip()
        if vazia and self._vazia:
            return  # duas linhas em branco seguidas viram uma
        self._vazia = vazia
        linha = self._adapta(self._com_guia(txt) if guia else txt)
        with self.trava:
            if self.vivo_txt and self.tty:
                sys.stdout.write('\r\033[2K')
            sys.stdout.write(linha + '\n')
            if self.vivo_txt and self.tty:
                sys.stdout.write(self.vivo_txt)
            sys.stdout.flush()

    def vivo(self, txt, guia=True):
        if not self.tty:
            return
        with self.trava:
            # linha viva mais larga que a tela quebra, e o \r só apaga o último pedaço: corta antes
            linha = self._com_guia(txt) if guia else txt
            self.vivo_txt = self._adapta(corta_visivel(linha, self.largura + 2))
            sys.stdout.write('\r\033[2K' + self.vivo_txt)
            sys.stdout.flush()

    def para_vivo(self):
        with self.trava:
            if self.vivo_txt and self.tty:
                sys.stdout.write('\r\033[2K')
                sys.stdout.flush()
            self.vivo_txt = ''

    def logo(self):
        self.escreve(guia=False)
        if self.largura >= 46 and self.nivel != 'ascii':
            for s, n in zip(LOGO_SIMBOLO, LOGO_NOME):
                self.escreve('  ' + self.p(s, 'texto') + '   ' + self.degrade(n, ('verde', 'teal', 'azul')), guia=False)
        else:
            self.escreve('  ' + self.p('</>', 'texto', True) + '  ' + self.degrade('KESSLERU', ('verde', 'teal', 'azul'), True), guia=False)

    def cabecalho(self, caminho, extra=''):
        """Abre um bloco: a primeira linha, com o nome da ferramenta, e a guia lateral daí para baixo."""
        self.escreve(guia=False)
        marca = self.p('┌', 'superficie')
        if caminho == 'início':
            nome = self.p('ferramentas', 'texto', True)
            self.titulo_janela('ferramentas')
        else:
            nome = self.p('ferramentas', 'apagado') + self.p(' › ', 'fundo') + self.p(f' {caminho} ', 'texto', True, fundo='fundo')
            self.titulo_janela(f'ferramentas › {caminho}')
        self.escreve(' ' + marca + '  ' + nome + (self.p('  ' + extra, 'apagado') if extra else ''), guia=False)
        self.guia = True
        self.escreve()

    def fim(self, txt='', nivel='ok'):
        """Fecha o bloco aberto pelo cabeçalho; o ícone diz como terminou."""
        self.fecha_caixa()
        if not self.guia:
            return
        self.para_vivo()
        self.escreve()
        self.guia = False
        icone = {'ok': self.p('✓', 'verde') if self.nivel != 'ascii' else '', 'aviso': self.p('!', 'amarelo', True),
                 'erro': self.p('■', 'vermelho'), 'nada': ''}[nivel]
        self.escreve(' ' + self.p('└', 'superficie') + '  ' + (icone + ' ' if icone else '') + self.p(txt, 'apagado'), guia=False)

    def titulo(self, txt, caixa=False):
        self.fecha_caixa()
        if caixa and self.guia and self.nivel != 'ascii':
            # o resumo vai numa caixa (como o "note" do Clack); o conteúdo é montado mais estreito
            self._caixa = {'titulo': txt, 'linhas': []}
            self.largura -= 3
            return
        self.escreve()
        self.escreve(' ' + self.p('◇', 'verde') + '  ' + self.p(txt, 'texto', True), guia=False)

    def fecha_caixa(self):
        cx, self._caixa = self._caixa, None
        if cx is None:
            return
        self.largura += 3
        linhas = [l[2:] if l.startswith('  ') else l for l in cx['linhas']]
        while linhas and not ANSI.sub('', linhas[0]).strip():
            linhas.pop(0)
        while linhas and not ANSI.sub('', linhas[-1]).strip():
            linhas.pop()
        larg = max([vlen(l) for l in linhas] + [len(cx['titulo']) + 3]) + 2
        borda = lambda s: self.p(s, 'superficie')
        self.escreve()
        self.escreve(' ' + self.p('◇', 'verde') + '  ' + self.p(cx['titulo'], 'texto', True) + ' '
                     + borda('─' * (larg - len(cx['titulo']) - 1) + '╮'), guia=False)
        for l in [''] + linhas + ['']:
            self.escreve(' ' + borda('│') + '  ' + l + ' ' * (larg - vlen(l)) + borda('│'), guia=False)
        self.escreve(' ' + borda('├' + '─' * (larg + 2) + '╯'), guia=False)
        self._vazia = False

    def aba(self, arquivo, descricao=''):
        # a descrição da ferramenta logo abaixo do cabeçalho, discreta
        if descricao:
            self.escreve('  ' + self.p(corta(descricao, self.largura - 4), 'apagado'))
            self.escreve()

    def prompt(self, pasta, txt, alvo=None):
        txt = corta(txt, self.largura - len(pasta) - 6)
        self.escreve('  ' + self.p(f'~/{pasta}', 'apagado') + '  ' + self.link(self.p(txt, 'texto'), alvo))

    def item(self, icone, cor, nome, detalhe='', recuo=2, cor_nome='texto', alvo=None):
        w, d = self.largura, vlen(detalhe)
        nomeia = lambda n: self.link(self.p(n, cor_nome), alvo)  # o link entra depois do corte
        if d and recuo + 6 + min(len(nome), 16) + d > w:
            self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + nomeia(corta(nome, w - recuo - 2)))
            self.escreve(' ' * (recuo + 2) + corta_visivel(detalhe, w - recuo - 2))
            return
        n = corta(nome, w - recuo - 5 - d)
        if not d:
            self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + nomeia(n))
            return
        pontos = max(1, w - recuo - 2 - len(n) - 2 - d)
        self.escreve(' ' * recuo + self.p(icone, cor) + ' ' + nomeia(n) + ' '
                     + self.p('·' * pontos, 'fundo') + ' ' + detalhe)

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

    def _mensagem(self, icone, cor_icone, txt, cor):
        if vlen(txt) != len(txt):  # já vem colorido: não dá para quebrar sem estragar as cores
            self.escreve('  ' + icone + ' ' + txt)
            return
        for i, linha in enumerate(textwrap.wrap(txt, max(20, self.largura - 4), break_on_hyphens=False) or ['']):
            self.escreve(('  ' + icone if i == 0 else '   ') + ' ' + (self.p(linha, cor) if cor else linha))

    def ok(self, txt):
        self._mensagem(self.p('✓', 'verde'), 'verde', txt, None)

    def aviso(self, txt):
        self._mensagem(self.p('!', 'amarelo', True), 'amarelo', txt, 'amarelo')

    def erro(self, txt):
        self._mensagem(self.p('✗', 'vermelho', True), 'vermelho', txt, 'vermelho')

    def nota(self, txt, recuo=2):
        self.escreve(' ' * recuo + self.p(txt, 'apagado'))

    def relatorio(self, arq, rotulo='relatório', recuo=4):
        """A linha "relatório: caminho", com o caminho clicável onde o terminal deixa."""
        self.escreve(' ' * recuo + self.p(f'{rotulo}: ', 'apagado')
                     + self.p(self.caminho(arq, max(12, self.largura - recuo - len(rotulo) - 2)), 'sub'))

    def pergunta(self, txt):
        self.fecha_caixa()
        rotulo = self._com_guia('  ' + self.p(txt, 'sub') + ' ' + self.p('› ', 'verde'))
        try:
            return input(self._adapta(rotulo))
        except EOFError:
            return ''


def _aceita_links(env):
    # mesma régua do pacote supports-hyperlinks (usado pelo npm e pelo Vite)
    if env.get('FORCE_HYPERLINK'):
        return env['FORCE_HYPERLINK'] != '0'
    if 'WT_SESSION' in env:
        return True
    if os.name == 'nt' or env.get('CI'):
        return False
    prog, ver = env.get('TERM_PROGRAM', ''), env.get('TERM_PROGRAM_VERSION', '')
    num = tuple(int(x) for x in re.findall(r'\d+', ver)[:2]) or (0,)
    if prog == 'iTerm.app':
        return num >= (3, 1)
    if prog == 'vscode':
        return num >= (1, 72) or bool(env.get('CURSOR_TRACE_ID'))
    if prog in ('WezTerm', 'ghostty', 'zed', 'WarpTerminal'):
        return True
    vte = env.get('VTE_VERSION', '')
    if vte.isdigit():
        return vte != '5000' and int(vte) >= 5000
    return env.get('TERM') in ('alacritty', 'xterm-kitty')


class Progresso:
    QUADROS = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, term, total, rotulo, registro=True):
        # total None = não se sabe quanto falta: mostra só a contagem
        self.t, self.total, self.rotulo, self.registro = term, total, rotulo, registro
        self.n, self.atual, self._i = 0, '', 0
        self._parar = threading.Event()
        self._fio = threading.Thread(target=self._gira, daemon=True)
        if term.nivel != 'pleno':
            self.QUADROS = '|/-\\'
        self.cheio = '#' if term.nivel == 'ascii' else '■'
        self.vazio = '■' if term.cor else ('-' if term.nivel == 'ascii' else '·')
        self.inicio = time.time()

    def __enter__(self):
        self.t.fecha_caixa()
        self.inicio = time.time()
        if self.t.tty:
            if self.t.cor:
                sys.stdout.write('\033[?25l')  # esconde o cursor enquanto gira (ele piscava no meio da linha)
            self._fio.start()
        return self

    def __exit__(self, tipo, *_):
        self._parar.set()
        if self._fio.is_alive():
            self._fio.join()
        self.t.para_vivo()
        if self.t.tty and self.t.cor:
            sys.stdout.write('\033[?25h')
            sys.stdout.flush()
        # deixa um registro do passo, como o spinner do Clack: o que foi feito e quanto demorou
        dur = time.time() - self.inicio
        if self.registro and (dur >= 1 or tipo is not None) and self.t.guia:
            conta = (f'{self.n:,}'.replace(',', '.') if self.total is None else f'{self.n}/{self.total}')
            conta = '' if self.total is None and not self.n else conta + ' · '  # passo sem contagem: só o tempo
            if tipo is KeyboardInterrupt:
                icone, fim = self.t.p('■', 'vermelho'), 'interrompido'
            else:
                icone, fim = self.t.p('◇', 'verde' if tipo is None else 'vermelho'), _duracao(dur)
            self.t.escreve(' ' + icone + '  ' + self.t.p(self.rotulo, 'sub') + self.t.p(f'  {conta}{fim}', 'apagado'),
                           guia=False)

    def avanca(self, atual='', n=1):
        self.n += n
        self.atual = atual

    def _desenho(self):
        t = self.t
        q = t.p(self.QUADROS[self._i % len(self.QUADROS)], 'verde')
        self._i += 1
        dur = time.time() - self.inicio
        tempo = f' · {_duracao(dur)}' if dur >= 3 else ''
        if self.total is None:
            conta = (f'{self.n:,}'.replace(',', '.') if self.n else '') + (tempo[3:] if not self.n else tempo)
            resto = t.largura - 6 - len(self.rotulo) - len(conta)
            return (f' {q}  {t.p(self.rotulo, "sub")} {t.p(conta, "texto")} '
                    f'{t.p(corta_esq(self.atual, max(0, resto)), "apagado")}')
        total = max(self.total, 1)
        conta = f'{self.n}/{total}'
        larg = max(6, min(20, t.largura - len(self.rotulo) - len(conta) - 26))
        cheio = int(larg * self.n / total)
        barra = t.p(self.cheio * cheio, 'verde') + t.p(self.vazio * (larg - cheio), 'fundo')
        resto = t.largura - 7 - len(self.rotulo) - larg - len(conta) - len(tempo)
        return (f' {q}  {t.p(self.rotulo, "sub")} {barra} {t.p(conta, "texto")}{t.p(tempo, "apagado")} '
                f'{t.p(corta(self.atual, resto), "apagado")}')

    def _gira(self):
        while not self._parar.wait(0.08):
            self.t.vivo(self._desenho(), guia=False)


def _duracao(s):
    if s < 1:
        return f'{s * 1000:.0f} ms'
    if s < 90:
        return f'{s:.0f} s' if s >= 10 else f'{s:.1f} s'.replace('.', ',')
    return f'{s // 60:.0f} min {s % 60:02.0f} s'


class Relatorio:
    def __init__(self, nome):
        self.nome, self.linhas = nome, [f'ferramentas · {nome} · {datetime.now():%d/%m/%Y %H:%M}', '']

    def add(self, *linhas):
        self.linhas.extend(linhas)

    def salva(self):
        pasta = CASA / 'relatorios'
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / f'{self.nome}-{datetime.now():%Y-%m-%d_%H%M%S}.txt'
        arq.write_text('\n'.join(self.linhas) + '\n', encoding='utf-8')
        return arq


def confirma(t, args, pergunta):
    if args.sim:
        return True
    if not t.interativo:
        t.aviso('Sem terminal para confirmar; use --sim para seguir sem perguntar.')
        return False
    t.fecha_caixa()
    t.escreve()
    t.escreve(' ' + t.p('◆', 'amarelo') + '  ' + t.p(pergunta, 'amarelo', True), guia=False)
    return t.pergunta('digite SIM para confirmar').strip().lower() == 'sim'

# ███████████████████████████████████████████████████████████████████████████
#
#   PARTE 1 · SEUS REPOSITÓRIOS NO GITHUB
#   segredos · branches · demos · backup · deps · coautores
#
# ███████████████████████████████████████████████████████████████████████████

# ═══════════════════════════════ GitHub: login e API ═══════════════════════════════

class ErroAPI(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


URL_NOVO_TOKEN = 'https://github.com/settings/tokens/new?scopes=repo,workflow&description=ferramentas'
ESCOPOS_ESCRITA = {'repo', 'workflow'}


def _arquivo_token():
    return CASA / 'token'


def obter_token():
    """Procura um login já feito, do mais explícito para o mais implícito. Devolve (token, de onde veio)."""
    for var in ('GH_TOKEN', 'GITHUB_TOKEN'):
        if os.environ.get(var):
            return os.environ[var].strip(), f'variável {var}'
    if shutil.which('gh'):
        r = roda(['gh', 'auth', 'token'], tempo=20)
        if r.returncode == 0 and r.stdout.strip():
            return texto(r.stdout).strip(), 'GitHub CLI (gh)'
    try:
        guardado = _arquivo_token().read_text(encoding='utf-8').strip()
        if guardado:
            return guardado, caminho_curto(_arquivo_token())
    except OSError:
        pass
    # o gerenciador de credenciais do git (o do Windows e o do macOS já vêm ligados)
    r = roda(['git', 'credential', 'fill'], entrada=b'protocol=https\nhost=github.com\n\n',
             env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never'), tempo=60)
    for linha in texto(r.stdout).splitlines():
        if linha.startswith('password='):
            return linha[9:].strip(), 'gerenciador de credenciais do git'
    return None, None


def traduz_erro_github(status, msg):
    baixo = (msg or '').lower()
    if status == 401:
        return 'o GitHub recusou o login (token vencido ou revogado); troque com: python ferramentas.py login --trocar'
    if status in (403, 429) and 'rate limit' in baixo:
        return 'limite de consultas do GitHub atingido (sem login são só 60 por hora); faça login ou espere um pouco'
    if status == 403 and 'saml' in baixo:
        return 'a organização exige liberar o token no SSO: em github.com/settings/tokens, clique em "Configure SSO"'
    if status == 403 and ('resource not accessible' in baixo or 'must have admin' in baixo):
        return 'o token não tem permissão para isso (crie um com "repo" e "workflow")'
    if status == 404:
        return 'não encontrado (ou o login atual não tem acesso)'
    return msg


class GitHub:
    API = 'https://api.github.com'

    def __init__(self, term, sem_login=False, estado=None):
        self.t, self.token, self.login, self.origem, self.escopos, self.perfil = term, None, None, None, None, None
        self.estado = estado if estado is not None else {}
        if not shutil.which('curl'):
            raise SystemExit('ERRO: preciso do curl instalado.')
        if not sem_login:
            self._entrar()
        self.dono = self._descobre_dono()

    def requisita(self, url, metodo='GET', corpo=None, aceita=None, tempo=40, cabecalhos=None):
        if url.startswith('/'):
            url = self.API + url
        do_github = url.startswith(self.API)
        aceita = aceita or ('application/vnd.github+json' if do_github else 'application/json')
        # o token vai pela configuração no stdin do curl, nunca na linha de comando
        cfg = [f'url = "{url}"', f'header = "Accept: {aceita}"', 'header = "User-Agent: ferramentas"']
        if do_github:
            cfg.append('header = "X-GitHub-Api-Version: 2022-11-28"')
            if self.token:
                cfg.append(f'header = "Authorization: Bearer {self.token}"')
        if metodo != 'GET':
            cfg.append(f'request = "{metodo}"')
        # -L: repositório renomeado responde 301 apontando para o endereço novo
        args = ['curl', '-sS', '-L', '-K', '-', '--max-time', str(tempo), '-w', '\n%{http_code}']
        arq_corpo = arq_cab = None
        if corpo is not None:
            CASA.mkdir(parents=True, exist_ok=True)
            arq_corpo = CASA / f'.corpo-{os.getpid()}-{threading.get_ident()}.json'
            arq_corpo.write_text(json.dumps(corpo), encoding='utf-8')
            args += ['-H', 'Content-Type: application/json', '--data-binary', f'@{arq_corpo}']
        if cabecalhos is not None:
            CASA.mkdir(parents=True, exist_ok=True)
            arq_cab = CASA / f'.cab-{os.getpid()}-{threading.get_ident()}.txt'
            args += ['-D', str(arq_cab)]
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
            if arq_cab is not None and arq_cab.exists():
                for l in arq_cab.read_text('utf-8', 'replace').splitlines():
                    k, _, v = l.partition(':')
                    if v:
                        cabecalhos[k.strip().lower()] = v.strip()
            return status, dados
        finally:
            for arq in (arq_corpo, arq_cab):
                if arq:
                    try:
                        arq.unlink()
                    except OSError:
                        pass

    def json(self, url, **kw):
        status, dados = self.requisita(url, **kw)
        if status == 0 or status >= 400:
            try:
                msg = json.loads(dados).get('message', '')
            except (ValueError, AttributeError):
                msg = texto(dados)[:160]
            raise ErroAPI(status, traduz_erro_github(status, msg) or f'HTTP {status}')
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
        self.token, self.origem = obter_token()
        if self.token:
            erro = self._valida()
            if erro:
                t.aviso(f'O login de {self.origem} não funcionou: {erro}')
                self.token = self.origem = None
        if not self.token and t.interativo:
            self.pede_token()
        if self.token:
            t.ok(f'conectado como {t.p(self.login, "verde")}' + t.p(f'  via {self.origem}', 'apagado'))
        else:
            t.aviso('Sem login: só repositórios públicos, nada pode ser alterado, e o GitHub deixa 60 consultas por hora.')

    def pede_token(self):
        """Pede um token, com o formulário do GitHub já preenchido. Devolve True se entrou."""
        t = self.t
        t.escreve()
        t.titulo('login no GitHub')
        t.paragrafo('Para ver os repositórios privados e poder alterar alguma coisa, a ferramenta precisa de um '
                    'token. O formulário abre já marcado com "repo" e "workflow"; escolha a validade e clique em '
                    '"Generate token".', 2, 'sub')
        # com link clicável, um texto curto basta; sem, o endereço inteiro precisa aparecer para copiar
        rotulo = 'github.com/settings/tokens/new  (repo + workflow)' if t.links else URL_NOVO_TOKEN
        t.escreve('  ' + t.p(t.link(rotulo, URL_NOVO_TOKEN), 'azul'))
        gcm = roda(['git', 'credential-manager', '--version'], tempo=15).returncode == 0
        t.paragrafo('a = abrir no navegador' + (' · g = entrar pelo navegador (Git Credential Manager)' if gcm else '')
                    + ' · Enter = continuar sem login · ou cole o token', 2, 'apagado')
        for _ in range(3):
            try:
                resp = getpass.getpass(t._adapta(t._com_guia('  ' + t.p('token', 'sub') + ' ' + t.p('› ', 'verde')))).strip()
            except (EOFError, KeyboardInterrupt):
                return False
            if not resp:
                return False
            if resp.lower() in ('a', 'abrir'):
                import webbrowser
                if not webbrowser.open(URL_NOVO_TOKEN):
                    t.aviso('não consegui abrir o navegador; copie o endereço acima.')
                continue
            if resp.lower() == 'g' and gcm:
                # o gerenciador do Git abre o login do GitHub no navegador e devolve um token (repo + workflow)
                t.nota('abrindo o login do GitHub no navegador…', 2)
                r = roda(['git', 'credential', 'fill'], entrada=b'protocol=https\nhost=github.com\n\n',
                         env=dict(os.environ, GCM_INTERACTIVE='always'), tempo=300)
                resp = next((l[9:].strip() for l in texto(r.stdout).splitlines() if l.startswith('password=')), '')
                if not resp:
                    t.aviso('o login pelo navegador não terminou.')
                    continue
            self.token = resp
            erro = self._valida()
            if erro:
                t.erro(f'Esse token não foi aceito: {erro}')
                self.token = None
                continue
            self.origem = 'token colado agora'
            self._guarda(resp)
            return True
        return False

    def _valida(self):
        cab = {}
        st, dados = self.requisita('/user', cabecalhos=cab)
        if st != 200:
            try:
                msg = json.loads(dados).get('message', '')
            except (ValueError, AttributeError):
                msg = ''
            return traduz_erro_github(st, msg) or f'HTTP {st}'
        try:
            self.perfil = json.loads(dados)
            self.login = self.perfil['login']
        except (ValueError, KeyError, TypeError):
            return 'resposta inesperada do GitHub'
        # token "classic" diz as permissões no cabeçalho; o "fine-grained" não diz (escopos = None)
        escopos = {e.strip() for e in cab.get('x-oauth-scopes', '').split(',') if e.strip()}
        self.escopos = escopos or None  # vazio ou ausente: token sem lista de escopos (fine-grained, app)
        return None

    def falta_permissao(self, precisa=ESCOPOS_ESCRITA):
        """O que falta no token para alterar o GitHub (vazio = tudo certo, ou o token não diz)."""
        if self.escopos is None:
            return set()
        tem = set(self.escopos) | ({'repo'} if 'public_repo' in self.escopos else set())
        return set(precisa) - tem

    def _guarda(self, token):
        t = self.t
        if texto(roda(['git', 'config', 'credential.helper']).stdout).strip():
            r = roda(['git', 'credential', 'approve'],
                     entrada=f'protocol=https\nhost=github.com\nusername={self.login}\npassword={token}\n\n'.encode())
            if r.returncode == 0:
                t.ok('token guardado no gerenciador de credenciais do git: não vai ser pedido de novo.')
                return
        if not t.interativo:
            return
        t.paragrafo(f'Guardar o token neste computador? Ele fica em {caminho_curto(_arquivo_token())}, que só o seu '
                    'usuário consegue ler. s = sim, Enter = não (vai ser pedido de novo na próxima vez)', 2, 'apagado')
        if t.pergunta('guardar').strip().lower() in ('s', 'sim'):
            try:
                CASA.mkdir(parents=True, exist_ok=True)
                arq = _arquivo_token()
                # cria já com permissão só do dono, antes de escrever o segredo
                fd = os.open(str(arq), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(token + '\n')
                t.ok(f'guardado em {caminho_curto(arq)}. Para apagar: python ferramentas.py login --sair')
            except OSError as e:
                t.erro(f'não consegui guardar: {e}')

    def _descobre_dono(self):
        if self.login:
            return self.login
        dono = os.environ.get('FERRAMENTAS_DONO') or os.environ.get('FERRAMENTAS_GIT_DONO') or self.estado.get('usuario_github')
        if not dono and self.t.interativo:
            self.t.paragrafo('Qual é o seu usuário do GitHub? (é o nome que aparece em github.com/usuario)', 2, 'apagado')
            dono = self.t.pergunta('usuário').strip().lstrip('@')
            if dono:
                self.estado['usuario_github'] = dono
                salva_estado(self.estado)
        return dono or ''

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
                if '/' not in n and not self.dono:
                    return {'_erro': f'{n}: diga o dono junto (dono/{n}), ou faça login'}
                full = n if '/' in n else f'{self.dono}/{n}'
                try:
                    r = self.json(f'/repos/{full}')
                except ErroAPI as e:
                    return {'_erro': f'{full}: {e}'}
                return r if isinstance(r, dict) and 'name' in r else {'_erro': f'{full}: resposta inesperada do GitHub'}

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
        elif self.dono:
            lista = self.paginas(f'/users/{self.dono}/repos?type=owner')
        else:
            raise ErroAPI(0, 'sem login e sem usuário: diga os repositórios (dono/nome) ou defina FERRAMENTAS_DONO')
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
            self._gh = GitHub(self.t, sem_login=getattr(self.args, 'sem_login', False), estado=self.estado)
        return self._gh


def escolhe_repos(ctx, arquivados=True, precisa_login=False):
    t, gh = ctx.t, ctx.gh
    if precisa_login:
        if not gh.token:
            t.erro('Essa ferramenta altera o GitHub e precisa de login (rode de novo e cole um token, ou use --teste).')
            return []
        falta = gh.falta_permissao(precisa_login if isinstance(precisa_login, (set, frozenset)) else ESCOPOS_ESCRITA)
        if falta:
            t.erro(f'O token não tem a permissão {", ".join(sorted(falta))}, que essa ferramenta usa para alterar o GitHub.')
            t.paragrafo(f'Crie outro em {URL_NOVO_TOKEN} e troque com: python ferramentas.py login --trocar', 4, 'apagado')
            return []
    try:
        lista = gh.repos(ctx.args.repos or None, forks=ctx.args.forks, arquivados=arquivados)
    except ErroAPI as e:
        t.erro(f'Não consegui a lista de repositórios: {e}')
        return []
    pub = sum(1 for r in lista if not r.get('private'))
    priv = len(lista) - pub
    total = f'{len(lista)} repositório{"s" if len(lista) != 1 else ""}'
    texto = f'{total} · {pub} público{"s" if pub != 1 else ""} · {priv} privado{"s" if priv != 1 else ""}'
    if len(texto) + 13 > t.largura:
        texto = f'{total} · {priv} privado{"s" if priv != 1 else ""}'
    t.prompt('repos', texto)
    return lista


def _apaga_login(t):
    apagou = []
    if _arquivo_token().exists():
        _arquivo_token().unlink()
        apagou.append(caminho_curto(_arquivo_token()))
    if texto(roda(['git', 'config', 'credential.helper']).stdout).strip():
        if roda(['git', 'credential', 'reject'], entrada=b'protocol=https\nhost=github.com\n\n').returncode == 0:
            apagou.append('gerenciador de credenciais do git')
    t.ok('login apagado de: ' + ', '.join(apagou) if apagou else 'não havia login guardado pela ferramenta.')
    if os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'):
        t.aviso('A variável GH_TOKEN/GITHUB_TOKEN continua definida no seu terminal: tire-a para sair de vez.')


def _troca_login(ctx):
    t = ctx.t
    gh = GitHub(t, sem_login=True, estado=ctx.estado)
    if not gh.pede_token():
        t.aviso('nada mudou.')
        return False
    gh.dono = gh.login
    ctx._gh = gh
    t.ok(f'agora conectado como {t.p(gh.login, "verde")}')
    return True


def mostra_perfil(ctx):
    t, gh = ctx.t, ctx.gh
    if not gh.token:
        t.paragrafo('Sem login: as ferramentas do GitHub só veem repositórios públicos e não alteram nada.', 2, 'apagado')
        if gh.dono:
            t.item('●', 'azul', 'usuário (sem login)', t.p(gh.dono, 'texto'), alvo=f'https://github.com/{gh.dono}')
        return False
    perfil = gh.perfil or {}
    t.titulo('perfil', caixa=True)
    nome = perfil.get('name') or gh.login
    t.escreve('  ' + t.link(t.p(nome, 'texto', True), perfil.get('html_url')) + t.p(f'  @{gh.login}', 'apagado'))
    if perfil.get('bio'):
        t.paragrafo(perfil['bio'], 2, 'sub')
    numeros = []
    if perfil.get('public_repos') is not None:
        privados = perfil.get('total_private_repos')
        numeros.append(f'{perfil["public_repos"]} repositórios públicos' + (f' · {privados} privados' if privados is not None else ''))
    if perfil.get('followers') is not None:
        numeros.append(f'{pl(perfil["followers"], "seguidor", "seguidores")} · seguindo {perfil.get("following", 0)}')
    for n in numeros:
        t.escreve('  ' + t.p(n, 'sub'))
    if perfil.get('created_at'):
        t.escreve('  ' + t.p(f'no GitHub desde {perfil["created_at"][:4]}', 'apagado'))
    t.titulo('login', caixa=True)
    t.item('●', 'verde', 'vem de', t.p(gh.origem or '?', 'sub'))
    if gh.escopos is None:
        t.item('●', 'azul', 'permissões', t.p('token fine-grained (veja no GitHub)', 'sub'))
    else:
        falta = gh.falta_permissao()
        t.item('●' if not falta else '!', 'verde' if not falta else 'amarelo', 'permissões',
               t.p(', '.join(sorted(gh.escopos)) or 'nenhuma', 'sub'))
        if falta:
            t.paragrafo(f'falta {", ".join(sorted(falta))}: branches, coautores e o preenchimento do campo "site" '
                        'não vão funcionar', 4, 'amarelo')
    cab = {}
    gh.requisita('/rate_limit', cabecalhos=cab)
    if cab.get('x-ratelimit-remaining'):
        t.item('●', 'verde', 'consultas restantes', t.p(f'{cab["x-ratelimit-remaining"]} de {cab.get("x-ratelimit-limit", "?")}', 'sub'))
    t.fecha_caixa()
    return True


def ferramenta_login(ctx):
    t, args = ctx.t, ctx.args
    if getattr(args, 'sair', False):
        _apaga_login(t)
        return 0
    if getattr(args, 'trocar', False):
        if _arquivo_token().exists():
            _arquivo_token().unlink()
        if not _troca_login(ctx):
            return 1
    logado = mostra_perfil(ctx)
    if not t.interativo or args.sim:
        return 0 if logado else 1
    while True:
        t.escreve()
        opcoes = ('t = trocar o token · s = sair (apagar o login) · Enter = voltar' if logado
                  else 'e = entrar (colar um token ou abrir o navegador) · Enter = voltar')
        t.paragrafo(opcoes, 2, 'apagado')
        r = t.pergunta('login').strip().lower()
        if r in ('t', 'e', 'trocar', 'entrar'):
            if _troca_login(ctx):
                logado = mostra_perfil(ctx)
        elif r in ('s', 'sair') and logado:
            if confirma(t, args, 'Apagar o login guardado neste computador?'):
                _apaga_login(t)
                ctx._gh = None
                return 0
        else:
            return 0 if logado else 1


# ═══════════════════════════════ configuração ═══════════════════════════════

# chave → (rótulo, tipo, opções ou padrão, ajuda); "escolha" alterna entre as opções
CONFIG = [
    ('usuario_github', 'usuário do GitHub', 'texto', '', 'usado sem login (com login, vale o do token)'),
    ('backup_destino', 'pasta do backup', 'pasta', str(Path.home() / 'backup-github'), 'onde o backup guarda os repositórios'),
    ('cores', 'cores', 'escolha', ['automático', 'sem cor'], '"sem cor" é o mesmo que --sem-cor em toda ferramenta'),
    ('simbolos', 'símbolos', 'escolha', ['automático', 'simples'], '"simples" é o --ascii, para terminal que mostra quadradinhos'),
    ('dispositivo', 'raio-x e peso medem como', 'escolha', ['celular', 'computador'], 'o Lighthouse simula esse aparelho'),
    ('faxina_dias', 'faxina: parado depois de', 'numero', 30, 'dias sem mexer para o projeto contar como parado'),
    ('atualizar_pular', 'atualizar sempre pula', 'texto', '', 'grupos ou gerenciadores separados por vírgula (ex.: editores,pip)'),
]
CONFIG_CLI = {'usuario': 'usuario_github', 'backup': 'backup_destino', 'cores': 'cores', 'simbolos': 'simbolos',
              'dispositivo': 'dispositivo', 'faxina-dias': 'faxina_dias', 'atualizar-pular': 'atualizar_pular'}


def config(chave, padrao=None):
    """Lê uma preferência salva (as mesmas chaves do estado.json)."""
    estado = carrega_estado()
    valor = estado.get(chave)
    return padrao if valor in (None, '') else valor


def _valor_config(estado, chave, tipo, padrao):
    v = estado.get(chave)
    if v in (None, ''):
        v = padrao[0] if tipo == 'escolha' else padrao
    return v


def _mostra_valor(v, tipo):
    if tipo == 'pasta':
        return caminho_curto(v)
    if tipo == 'numero':
        return f'{v} dias'
    return str(v) if v not in (None, '') else '(nada)'


def _define(estado, chave, tipo, opcoes, valor):
    if tipo == 'numero':
        if not str(valor).isdigit() or int(valor) < 1:
            raise ValueError('use um número de dias maior que zero')
        valor = int(valor)
    elif tipo == 'escolha':
        if valor not in opcoes:
            raise ValueError('opções: ' + ', '.join(opcoes))
    elif tipo == 'pasta' and valor:
        valor = str(Path(valor).expanduser())
    estado[chave] = valor
    salva_estado(estado)


def tamanho_casa():
    return tamanho_pasta(CASA) if CASA.exists() else 0


def ferramenta_config(ctx):
    t, args, estado = ctx.t, ctx.args, ctx.estado
    if getattr(args, 'chave', None):
        chave = CONFIG_CLI.get(args.chave)
        if not chave:
            t.erro(f'"{args.chave}" não é uma configuração. Existem: {", ".join(CONFIG_CLI)}')
            return 1
        _, rotulo, tipo, opcoes, _ = next(c for c in CONFIG if c[0] == chave)
        try:
            _define(estado, chave, tipo, opcoes, args.valor if args.valor is not None else '')
        except ValueError as e:
            t.erro(str(e))
            return 1
        t.ok(f'{rotulo} → {_mostra_valor(_valor_config(estado, chave, tipo, opcoes), tipo)}')
        return 0
    while True:
        t.titulo('preferências', caixa=True)
        for i, (chave, rotulo, tipo, opcoes, _) in enumerate(CONFIG, 1):
            v = _mostra_valor(_valor_config(estado, chave, tipo, opcoes), tipo)
            if chave == 'usuario_github' and ctx._gh is not None and ctx._gh.login:
                v = f'{ctx._gh.login} (do login)'
            _linha_config(t, i, rotulo, corta(v, t.largura - 8), 'sub')
        n = len(CONFIG) + 1
        _linha_config(t, n, 'limpar relatórios e cache', corta_esq(f'{humano(tamanho_casa())} em {caminho_curto(CASA)}',
                                                                    t.largura - 8), 'apagado')
        t.fecha_caixa()
        if not t.interativo:
            t.paragrafo('Para mudar sem menu: python ferramentas.py config CHAVE VALOR (chaves: '
                        + ', '.join(CONFIG_CLI) + ')', 2, 'apagado')
            return 0
        t.escreve()
        t.paragrafo('número para mudar · Enter = voltar', 2, 'apagado')
        r = t.pergunta('config').strip()
        if not r.isdigit() or not 1 <= int(r) <= n:
            return 0
        if int(r) == n:
            _limpa_dados(t, args)
            continue
        chave, rotulo, tipo, opcoes, ajuda = CONFIG[int(r) - 1]
        atual = _valor_config(estado, chave, tipo, opcoes)
        if tipo == 'escolha':
            novo = opcoes[(opcoes.index(atual) + 1) % len(opcoes)] if atual in opcoes else opcoes[0]
        else:
            t.paragrafo(f'{ajuda}. Agora: {_mostra_valor(atual, tipo)}. Enter = manter, "-" = voltar ao padrão', 2, 'apagado')
            novo = t.pergunta(rotulo).strip()
            if not novo:
                continue
            if novo == '-':
                estado.pop(chave, None)
                salva_estado(estado)
                continue
        try:
            _define(estado, chave, tipo, opcoes, novo)
            t.ok(f'{rotulo} → {_mostra_valor(estado[chave], tipo)}')
            if chave in ('cores', 'simbolos'):
                t.paragrafo('vale a partir da próxima vez que abrir a ferramenta', 4, 'apagado')
        except ValueError as e:
            t.erro(str(e))


def _linha_config(t, n, rotulo, valor, cor):
    esq = f'  {t.p(f"{n:>2}", "verde", True)}  {t.p(rotulo, "texto")}'
    if vlen(esq) + 2 + len(valor) <= t.largura:
        t.escreve(esq + ' ' * (t.largura - vlen(esq) - len(valor)) + t.p(valor, cor))
    else:  # tela estreita: o valor desce para a linha de baixo
        t.escreve(esq)
        t.escreve(' ' * 8 + t.p(valor, cor))


def _limpa_dados(t, args):
    # backups (do coautores), cofre do token e estado ficam: são coisas que não se recriam
    pastas = [CASA / p for p in ('relatorios', 'cache', 'tmp', 'raiox', 'peso', 'atualizar')]
    existentes = [p for p in pastas if p.exists()]
    total = sum(tamanho_pasta(p) for p in existentes)
    if not existentes:
        t.ok('nada para limpar.')
        return
    t.paragrafo('Sai: relatórios, cache dos repositórios, histórico do raio-x e do peso, logs do atualizar. '
                'Ficam: backups do coautores, login e preferências.', 2, 'apagado')
    if confirma(t, args, f'Apagar {humano(total)} de relatórios e cache?'):
        for p in existentes:
            shutil.rmtree(p, ignore_errors=True)
        t.ok(f'{humano(total)} liberados.')


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
            # selo de largura fixa: o texto de baixo alinha com o nome, qualquer que seja o nível
            rec = 4 + 9 + 1
            larg = t.largura - rec
            onde_atual = 'no código atual' if a['atual'] else 'só no histórico'
            quando = (f'desde {a["desde"]} · ' if a['desde'] else '') + f'id {a["id"]}'
            selo = t.selo(f'{rot:<7}', cor) if t.cor else f'{"[" + rot + "]":<9}'
            t.escreve('    ' + selo + ' ' + t.p(corta(a['nome'], larg), 'texto'))
            t.escreve(' ' * rec + t.p(corta_esq(onde, larg), 'sub'))
            if a['regra'] == 'arquivo':
                t.escreve(' ' * rec + t.p(onde_atual, 'apagado'))
            else:
                t.escreve(' ' * rec + t.p(corta(mascara(a), larg - len(onde_atual) - 3), 'sub') + t.p(' · ' + onde_atual, 'apagado'))
            t.escreve(' ' * rec + t.p(corta(quando, larg), 'apagado'))
            if a['dica']:
                for l in textwrap.wrap(a['dica'], larg):
                    t.escreve(' ' * rec + t.p(l, 'apagado'))
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
        t.titulo('resumo', caixa=True)
        t.partes(partes + [t.p(f'{limpos} repositório{"s" if limpos != 1 else ""} limpo{"s" if limpos != 1 else ""}', 'apagado')])
        if total['critico'] or total['alto']:
            t.escreve()
            t.paragrafo('O que fazer: revogue a chave no painel do serviço e gere outra. Apagar do histórico '
                        'não desfaz o vazamento — em repositório público, robôs copiam chaves em minutos.', 4, 'texto')
        t.paragrafo(f'Falso positivo? Ponha o id em {caminho_curto(CASA / "segredos-ignorados.txt")} (um por linha).', 4, 'apagado')
    else:
        t.ok(f'Nenhum segredo encontrado em {pl(limpos, "repositório")}.')
    rel.add('', f'{sum(total.values())} achados, {limpos} repositórios limpos')
    t.relatorio(rel.salva())


# ═══════════════════════════════ 2. branches ═══════════════════════════════

# branches que vivem para sempre, mesmo iguais à principal: deploy, homologação, Pages
BRANCHES_FIXAS = re.compile(r'^(develop|development|dev|staging|stage|homolog|homologacao|production|prod|'
                            r'release(s)?([/-].*)?|gh-pages|pages|docs)$', re.I)


def analisa_branches(gh, r):
    full, padrao = r['full_name'], r['default_branch']
    branches = [b for b in gh.paginas(f'/repos/{full}/branches') if b['name'] != padrao]
    if not branches:
        return []
    fonte_pages = None
    if r.get('has_pages'):
        try:
            fonte_pages = ((gh.json(f'/repos/{full}/pages') or {}).get('source') or {}).get('branch')
        except ErroAPI:
            pass
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
        elif nome == fonte_pages:
            item['motivo'] = 'publica o GitHub Pages'
        elif BRANCHES_FIXAS.match(nome):
            item['motivo'] = 'branch de deploy ou de uso contínuo'
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
                item['motivo'] = f'{frente} commit{"s" if frente > 1 else ""} fora da {padrao} · {ha_quanto_iso(data)}'
        saida.append(item)
    return saida


def ferramenta_branches(ctx):
    t, gh = ctx.t, ctx.gh
    if ctx.args.restaurar:
        return restaura_branches(ctx, Path(ctx.args.restaurar))
    repos = escolhe_repos(ctx, arquivados=False, precisa_login={'repo'} if not ctx.args.teste else False)
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
    t.titulo('resumo', caixa=True)
    t.partes([t.p(f'{len(apagar)} podem ser apagadas', 'verde'), t.p(f'{manter} ficam', 'sub'),
              t.p(f'{sem_branch} só com a branch principal', 'apagado')])
    if apagar and not ctx.args.teste and confirma(ctx.t, ctx.args, f'Apagar {len(apagar)} branch(es) no GitHub?'):
        CASA.joinpath('branches-apagadas').mkdir(parents=True, exist_ok=True)
        arq = CASA / 'branches-apagadas' / f'{carimbo()}.json'
        feitas = []
        with Progresso(t, len(apagar), 'apagando') as pr:
            for r, b in apagar:
                ref = quote(b['nome'], safe='/')
                # se alguém mandou commit depois da análise, a branch não é mais a mesma: fica
                try:
                    agora = gh.json(f'/repos/{r["full_name"]}/git/refs/heads/{ref}')['object']['sha']
                except (ErroAPI, KeyError, TypeError):
                    agora = None
                if agora != b['sha']:
                    t.aviso(f'{r["name"]}/{b["nome"]}: mudou depois da análise, ficou')
                    pr.avanca(b['nome'])
                    continue
                st, _ = gh.requisita(f'/repos/{r["full_name"]}/git/refs/heads/{ref}', metodo='DELETE')
                if st == 204:
                    feitas.append({'repo': r['full_name'], 'branch': b['nome'], 'sha': b['sha']})
                else:
                    t.erro(f'{r["name"]}/{b["nome"]}: GitHub respondeu {st}')
                pr.avanca(b['nome'])
        arq.write_text(json.dumps(feitas, indent=2), encoding='utf-8')
        t.ok(f'{len(feitas)} apagadas.')
        t.nota(f'para desfazer: python {Path(sys.argv[0]).name} branches --restaurar "{caminho_curto(arq)}"', 4)
    # mudar a configuração do repositório exige ser admin dele e um token com "repo"
    sem_auto = [r for r in repos if r.get('delete_branch_on_merge') is False and (r.get('permissions') or {}).get('admin')
                and not gh.falta_permissao({'repo'})]
    if sem_auto and not ctx.args.teste:
        t.escreve()
        t.paragrafo(f'{len(sem_auto)} repositórios não apagam a branch sozinhos depois do merge do PR. '
                    'Ligando essa opção, a faxina passa a ser automática.', 4, 'sub')
        if confirma(ctx.t, ctx.args, f'Ligar "apagar branch após o merge" nesses {len(sem_auto)}?'):
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
    if ctx.args.teste or not confirma(ctx.t, ctx.args, 'Recriar essas branches no GitHub?'):
        return
    for it in itens:
        st, _ = gh.requisita(f'/repos/{it["repo"]}/git/refs', metodo='POST',
                             corpo={'ref': f'refs/heads/{it["branch"]}', 'sha': it['sha']})
        detalhe = {201: t.p('recriada', 'verde'), 422: t.p('já existe', 'apagado')}.get(st, t.p(f'falhou ({st})', 'vermelho'))
        t.item('✓' if st == 201 else '·', 'verde' if st == 201 else 'apagado', f'{it["repo"].split("/")[-1]}/{it["branch"]}', detalhe)


# ═══════════════════════════════ 3. demos ═══════════════════════════════

HOSTS_DEMO = ('vercel.app', 'netlify.app', 'github.io', 'pages.dev', 'onrender.com', 'railway.app', 'fly.dev',
              'herokuapp.com', 'surge.sh', 'firebaseapp.com', 'web.app', 'glitch.me')
# palavra forte já basta; palavra fraca ("site", "acesse") só conta se o endereço for seu ou de deploy,
# senão "site do MDN" e "guia de acessibilidade" viravam a demo do projeto
PALAVRAS_DEMO = re.compile(r'(?i)\b(demo|demonstra[cç][aã]o|ao vivo|live|preview|deploy|no ar)\b')
PALAVRAS_FRACAS = re.compile(r'(?i)\b(site|acesse|acessar|acesso|online|ver o projeto|abrir)\b')
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


def links_de_demo(md, repo='', dono=''):
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
        meu = (dono and dono.lower() in host) or (repo and re.sub(r'[^a-z0-9]', '', repo.lower())[:10] in re.sub(r'[^a-z0-9]', '', host))
        de_deploy = host.endswith(HOSTS_DEMO)
        if PALAVRAS_DEMO.search(txt) or ((meu or de_deploy) and PALAVRAS_FRACAS.search(txt)) or (de_deploy and meu):
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
    for u in links_de_demo(texto(md), r['name'], r.get('owner', {}).get('login', '')):
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
    marca = '\n__ferramentas__'
    r = roda(['curl', '-sS', '-L', '--compressed', '--max-time', '20', '--max-redirs', '8',
              '-A', 'Mozilla/5.0 (ferramentas; verificador de demos)', '-o', '-',
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
        return {'nivel': 'protegido', 'msg': f'acesso bloqueado ({status}): proteção de deploy ou anti-robô', 'tempo': tempo}
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
            t.item(ic, cor, host, alvo=u, detalhe=t.p(corta(extra, max(12, t.largura - len(host) - 12)), cor if ch['nivel'] != 'ok' else 'apagado'), recuo=4)
            rel.add(f'  [{ch["nivel"]}] {u} ({origem}) — {extra}')
            if ch['nivel'] == 'ok' and bom is None:
                bom = u
        if not r.get('homepage') and bom:
            preencher.append((r, bom))
    for nome, erro in falhas:
        t.erro(f'{nome}: {erro}')
    t.escreve()
    t.titulo('resumo', caixa=True)
    t.partes([t.p(f'{cont[n]} {rot}', estilo[n][1]) for n, rot in
              (('ok', 'no ar'), ('lento', 'lentos'), ('protegido', 'bloqueados'), ('quebrado', 'fora do ar')) if cont[n]]
             + [t.p(f'{len(sem_demo)} sem demo', 'apagado')])
    if so_cfg:
        t.escreve()
        t.paragrafo('Têm configuração de deploy mas nenhum link de demo no README nem no campo "site":', 4, 'sub')
        for nome, cfg in so_cfg:
            t.item('?', 'amarelo', nome, t.p(', '.join(cfg), 'apagado'), recuo=4)
            rel.add(f'{nome}: tem {", ".join(cfg)} mas nenhum link de demo')
    if preencher and gh.token and not ctx.args.teste and gh.falta_permissao({'repo'}):
        t.paragrafo(f'{pl(len(preencher), "repositório")} com demo no ar e o campo "site" vazio; para preencher sozinho, '
                    'o token precisa da permissão "repo".', 4, 'apagado')
    elif preencher and gh.token and not ctx.args.teste:
        t.escreve()
        t.paragrafo(f'{len(preencher)} repositórios têm demo no ar mas o campo "site" do GitHub está vazio '
                    '(é o link que aparece no topo da página do repositório).', 4, 'sub')
        for r, u in preencher:
            t.item('+', 'verde', r['name'], t.p(re.sub(r'^https?://', '', u), 'apagado'), recuo=4)
        if confirma(ctx.t, ctx.args, 'Preencher o campo "site" desses repositórios?'):
            ok = sum(1 for r, u in preencher
                     if gh.requisita(f'/repos/{r["full_name"]}', metodo='PATCH', corpo={'homepage': u})[0] == 200)
            t.ok(f'preenchido em {ok}.')
    t.relatorio(rel.salva())


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
        cod, _, erro = git_txt(pasta, 'merge', '-q', '--ff-only', 'FETCH_HEAD')
        if cod != 0:
            return 'sujo', corta(f'não deu para atualizar: {erro.splitlines()[-1] if erro else "merge falhou"}', 60)
        return 'atualizado', f'+{n} commit' + ('s' if n != '1' else '')
    # o histórico foi reescrito no GitHub (ex.: coautores): guarda a cópia velha e baixa de novo
    antigos.mkdir(exist_ok=True)
    shutil.move(str(pasta), str(antigos / f'{nome}-{carimbo()}'))
    clona_principal(full, ramo, pasta, env)
    return 'refeito', 'histórico mudou no GitHub; cópia velha em .antigos'


def escreve_indice(destino, repos):
    # o índice vem do disco, não só dos repositórios desta rodada: rodar "backup Um" não apaga os outros
    arq = destino / 'INDICE.md'
    privados = {r['name'] for r in repos if r.get('private')}
    try:
        privados |= set(re.findall(r'^\| 🔒 ([^|]+?) \|', arq.read_text(encoding='utf-8'), re.M))
    except OSError:
        pass
    privados -= {r['name'] for r in repos if not r.get('private')}
    linhas = ['# Backup dos repositórios', '', f'Atualizado em {datetime.now():%d/%m/%Y %H:%M} pelo ferramentas.', '',
              '| Repositório | Branch | Último commit | Mensagem |', '| --- | --- | --- | --- |']
    for pasta in sorted((p for p in destino.iterdir() if p.is_dir() and not p.name.startswith('.')), key=lambda p: p.name.lower()):
        if not (pasta / '.git').exists():
            continue
        _, ramo, _ = git_txt(pasta, 'branch', '--show-current')
        _, info, _ = git_txt(pasta, 'log', '-1', '--format=%ad\t%s', '--date=short')
        data, _, msg = info.partition('\t')
        vis = '🔒 ' if pasta.name in privados else ''
        linhas.append(f'| {vis}{pasta.name} | {ramo} | {data} | {msg.replace("|", "/")[:70]} |')
    arq.write_text('\n'.join(linhas) + '\n', encoding='utf-8')


def acha_renomeados(gh, destino, repos):
    """Pasta com o nome antigo de um repositório renomeado no GitHub: troca o nome em vez de baixar tudo de novo."""
    faltam = {r['full_name'].lower(): r for r in repos if not (destino / r['name']).exists()}
    nomes = {r['name'].lower() for r in repos}
    feitos = []
    if not faltam:
        return feitos
    for pasta in destino.iterdir():
        if not pasta.is_dir() or pasta.name.startswith('.') or pasta.name.lower() in nomes or not (pasta / '.git').exists():
            continue
        _, url, _ = git_txt(pasta, 'remote', 'get-url', 'origin')
        m = re.search(r'github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$', url)
        if not m:
            continue
        try:
            atual = (gh.json(f'/repos/{m.group(1)}') or {}).get('full_name', '').lower()
        except ErroAPI:
            continue
        r = faltam.pop(atual, None)
        if r:
            pasta.rename(destino / r['name'])
            git_txt(destino / r['name'], 'remote', 'set-url', 'origin', f'https://github.com/{r["full_name"]}.git')
            feitos.append((pasta.name, r['name']))
    return feitos


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
    for velho, novo in acha_renomeados(gh, destino, repos):
        t.item('→', 'azul', f'{velho} → {novo}', t.p('renomeado no GitHub; pasta renomeada', 'apagado'))
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
    t.titulo('resumo', caixa=True)
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
LOCKFILES = ('package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock')


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
                    if nome.startswith('__') or faixa.startswith(('workspace:', 'link:', 'portal:', 'patch:')):
                        continue
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


# ---- Python: poetry.lock, uv.lock, Pipfile.lock e requirements*.txt, auditados pela base OSV ----
LOCKS_PY = ('poetry.lock', 'uv.lock', 'Pipfile.lock')
GERENCIADOR_PY = {'poetry.lock': 'poetry', 'uv.lock': 'uv', 'Pipfile.lock': 'pipenv'}


def nome_py(n):
    # PEP 503: "Flask_SQLAlchemy" e "flask-sqlalchemy" são o mesmo pacote
    return re.sub(r'[-_.]+', '-', n.strip().lower())


def le_lock_toml(txt):
    """poetry.lock e uv.lock: um bloco [[package]] por pacote, com name e version."""
    pacotes = {}
    for bloco in re.split(r'^\[\[package\]\]\s*$', txt, flags=re.M)[1:]:
        cabeca = bloco.split('\n[', 1)[0]
        n = re.search(r'^name\s*=\s*"([^"]+)"', cabeca, re.M)
        v = re.search(r'^version\s*=\s*"([^"]+)"', cabeca, re.M)
        # no uv.lock o próprio projeto aparece como pacote "editable"/"virtual": não é dependência
        if n and v and not re.search(r'^source\s*=\s*\{[^}]*\b(editable|virtual)\b', cabeca, re.M):
            pacotes[nome_py(n.group(1))] = v.group(1)
    return pacotes


def le_pipfile_lock(txt):
    d = json.loads(txt)
    return {nome_py(n): (i.get('version') or '').lstrip('=') for sec in ('default', 'develop')
            for n, i in (d.get(sec) or {}).items() if isinstance(i, dict) and (i.get('version') or '').startswith('==')}


def le_requirements(txt):
    fixas, nomes = {}, []
    for l in txt.splitlines():
        l = l.split('#', 1)[0].split(';', 1)[0].strip()
        if not l or l.startswith(('-', 'git+', 'http:', 'https:', 'file:', '.', '/')):
            continue
        m = re.match(r'([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)', l)
        if not m:
            continue
        n = nome_py(m.group(1))
        nomes.append(n)
        v = re.match(r'===?\s*([0-9][^\s,]*)\s*$', m.group(3))
        if v:
            fixas[n] = v.group(1)
    return fixas, nomes


def nomes_pyproject(txt):
    nomes = []
    m = re.search(r'^\s*dependencies\s*=\s*\[(.*?)\]', txt, re.M | re.S)
    if m:
        nomes += [nome_py(x) for x in re.findall(r'["\']\s*([A-Za-z0-9][A-Za-z0-9._-]*)', m.group(1))]
    for sec in re.findall(r'^\[tool\.poetry\.(?:group\.\w+\.)?(?:dev-)?dependencies\]\s*$(.*?)(?=^\[|\Z)', txt, re.M | re.S):
        nomes += [nome_py(x) for x in re.findall(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=', sec, re.M) if x.lower() != 'python']
    return nomes


def projetos_python(caminhos):
    pastas = defaultdict(list)
    for c in caminhos:
        pasta, _, base = c.rpartition('/')
        if any(p in c.split('/') for p in ('node_modules', 'venv', '.venv', 'site-packages')):
            continue
        if base in LOCKS_PY or base in ('pyproject.toml', 'Pipfile') or re.match(r'requirements[\w.-]*\.txt$', base):
            pastas[pasta].append(c)
    return pastas


def analisa_python(gh, full, ramo, pasta, arquivos):
    bases = {a.rpartition('/')[2]: a for a in arquivos}
    lock = next((bases[b] for b in LOCKS_PY if b in bases), None)
    todos, nomes, fixas = {}, [], {}
    for b, a in bases.items():
        txt = texto(gh.bruto(full, a, ramo) or b'')
        if b == 'pyproject.toml':
            nomes += nomes_pyproject(txt)
        elif b.startswith('requirements'):
            f, n = le_requirements(txt)
            fixas.update(f)
            nomes += n
        elif b == 'Pipfile':
            nomes += [nome_py(x) for x in re.findall(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=', txt, re.M)
                      if x.lower() not in ('url', 'verify_ssl', 'name', 'python_version')]
        elif a == lock:
            try:
                todos = le_pipfile_lock(txt) if b == 'Pipfile.lock' else le_lock_toml(txt)
            except ValueError:
                todos = {}
    if not todos:
        todos = dict(fixas)  # sem lockfile, só dá para auditar o que tem versão fixa (==)
    nomes = list(dict.fromkeys(nomes)) or list(todos)
    diretas = {n: todos[n] for n in nomes if n in todos}
    if not todos and not nomes:
        return None
    return {'pasta': pasta or '.', 'eco': 'PyPI', 'gerenciador': GERENCIADOR_PY.get(lock.rpartition('/')[2], 'pip') if lock else 'pip',
            'diretas': diretas, 'todos': {n: [v] for n, v in todos.items()},
            'sem_versao': [n for n in nomes if n not in todos]}


def audita_osv(gh, todos, eco):
    pares = [(n, v) for n, vs in todos.items() for v in vs]
    achados_brutos = []
    for i in range(0, len(pares), 500):
        lote = pares[i:i + 500]
        st, dados = gh.requisita('https://api.osv.dev/v1/querybatch', metodo='POST', tempo=60,
                                 corpo={'queries': [{'package': {'name': n, 'ecosystem': eco}, 'version': v} for n, v in lote]})
        if st != 200:
            raise RuntimeError(f'a base de vulnerabilidades OSV respondeu {st}')
        for (n, v), r in zip(lote, json.loads(dados).get('results', [])):
            achados_brutos += [(n, v, x['id']) for x in (r or {}).get('vulns') or []]
    if not achados_brutos:
        return []

    def detalhe(i):
        st, d = gh.requisita(f'https://api.osv.dev/v1/vulns/{quote(i)}', tempo=30)
        try:
            return i, json.loads(d) if st == 200 else {}
        except ValueError:
            return i, {}

    with ThreadPoolExecutor(8) as ex:
        detalhes = dict(ex.map(detalhe, sorted({x[2] for x in achados_brutos})))
    achados = []
    por_pacote = defaultdict(list)
    for n, v, i in achados_brutos:
        por_pacote[(n, v)].append(i)
    for (n, v), ids in por_pacote.items():
        vistos = set()
        # o mesmo problema vem com dois nomes (PYSEC-… e GHSA-…): fica um, de preferência o GHSA, que tem gravidade
        for i in sorted(ids, key=lambda x: (not x.startswith('GHSA'), x)):
            if i in vistos:
                continue
            d = detalhes.get(i, {})
            vistos |= {i, *d.get('aliases', [])}
            sev = ((d.get('database_specific') or {}).get('severity') or 'moderate').lower()
            titulo = d.get('summary') or (d.get('details') or '').strip().split('\n')[0]
            achados.append({'pacote': n, 'versoes': [v], 'sev': sev if sev in SEVERIDADE else 'moderate',
                            'titulo': corta(titulo or i, 110), 'url': f'https://osv.dev/vulnerability/{i}', 'id': i})
    return achados


def le_bun_lock(txt):
    """bun.lock (texto, Bun 1.2+): em "packages", cada chave aponta para ["nome@versão", ...]."""
    todos, topo = defaultdict(set), {}
    for chave, nome, versao in re.findall(r'"([^"]+)":\s*\[\s*"((?:@[^@"/]+/)?[^@"]+)@([^"]+)"', txt):
        if versao.startswith(('workspace:', 'file:', 'link:')):
            continue
        todos[nome].add(versao)
        if chave == nome:
            topo[nome] = versao
    return todos, topo


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
                elif base == 'bun.lock':
                    todos, topo = le_bun_lock(bruto)
                    gerenciador = 'bun'
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
        saida.append({'pasta': pasta or '.', 'eco': 'npm', 'gerenciador': gerenciador, 'diretas': versoes_diretas,
                      'todos': {k: sorted(v) for k, v in todos.items()}})
    for pasta, arquivos in sorted(projetos_python(caminhos).items()):
        proj = analisa_python(gh, full, ramo, pasta, arquivos)
        if proj:
            saida.append(proj)
    return saida


def audita(gh, projeto):
    if projeto.get('eco') == 'PyPI':
        return audita_osv(gh, projeto['todos'], 'PyPI')
    corpo = {n: vs for n, vs in projeto['todos'].items() if vs}
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


def ultima_versao(gh, eco, nome, cache, trava):
    with trava:
        if (eco, nome) in cache:
            return cache[(eco, nome)]
    if eco == 'PyPI':
        v = _pypi(nome)
        info = {'versao': v, 'descontinuado': None} if v else None
        with trava:
            cache[(eco, nome)] = info
        return info
    st, dados = gh.requisita(f'https://registry.npmjs.org/{nome.replace("/", "%2F")}/latest', tempo=30)
    info = None
    if st == 200:
        try:
            d = json.loads(dados)
            info = {'versao': d.get('version'), 'descontinuado': d.get('deprecated')}
        except ValueError:
            pass
    with trava:
        cache[(eco, nome)] = info
    return info


def ferramenta_deps(ctx):
    t, gh = ctx.t, ctx.gh
    repos = escolhe_repos(ctx, arquivados=False)
    if not repos:
        return
    projetos, falhas = em_paralelo(t, repos, lambda r: analisa_deps_repo(gh, r), 'lendo projetos', fios=6)
    lista = [(nome, p) for nome, ps in projetos.items() for p in ps]
    if not lista:
        t.ok('Nenhum projeto JavaScript ou Python encontrado.')
        return
    auditorias, f2 = em_paralelo(t, lista, lambda np: audita(gh, np[1]), 'checando vulnerabilidades',
                                 nome=lambda np: f'{np[0]}:{np[1]["pasta"]}', fios=4)
    falhas += f2
    cache, trava = {}, threading.Lock()
    pacotes = sorted({(p['eco'], n) for _, p in lista for n in p['diretas']})
    em_paralelo(t, pacotes, lambda en: ultima_versao(gh, en[0], en[1], cache, trava), 'conferindo versões',
                nome=lambda en: en[1], fios=10)
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
            info = cache.get((p['eco'], n))
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
            t.partes([t.p(f'{n_pac} pacote{"s" if n_pac > 1 else ""} com falha', 'sub')]
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
            t.escreve('      ' + t.p(corta(f'{pl(len(velhas), "desatualizada")}, {len(majors)} major: {exemplos}', t.largura - 8), 'apagado'))
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
    t.titulo('resumo', caixa=True)
    t.partes([t.p(sev_txt(s, total[s]), SEVERIDADE[s][1]) for s in SEVERIDADE if total[s]]
             or [t.p('nenhuma vulnerabilidade', 'verde')])
    t.partes([t.p(pl(len(lista), 'projeto'), 'apagado'), t.p(f'{limpos} sem pendências', 'apagado')])
    ecos = {p['eco'] for _, p in lista}
    dicas = (['npm audit fix (ou pnpm audit --fix)'] if 'npm' in ecos else []) + \
            (['pip install -U pacote (ou poetry update pacote, uv lock --upgrade-package pacote)'] if 'PyPI' in ecos else [])
    t.paragrafo('Nada foi alterado. Para corrigir: ' + '; '.join(dicas) + '. As majors, atualize uma de cada vez e rode '
                'os testes.', 4, 'apagado')
    sem_versao = [(nome, p) for nome, p in lista if p.get('sem_versao')]
    if sem_versao:
        t.paragrafo(f'{pl(len(sem_versao), "projeto Python")} sem lockfile nem versão fixa (==) em parte das '
                    'dependências: essas não dá para auditar.', 4, 'apagado')
    t.relatorio(rel.salva())


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


FILTER_REPO_VERSAO = '2.47.0'


def prepara_filter_repo(t):
    if roda(['git', 'filter-repo', '--version']).returncode == 0:
        return ['git', 'filter-repo']
    t.nota('preparando o git-filter-repo (só na primeira vez)…')
    # versão fixa: o script roda com acesso ao seu histórico, então não pode mudar sem você saber
    roda([sys.executable, '-m', 'pip', 'install', '--user', '--quiet', f'git-filter-repo=={FILTER_REPO_VERSAO}'], tempo=300)
    r = roda([sys.executable, '-c', 'import git_filter_repo; print(git_filter_repo.__file__)'])
    caminho = texto(r.stdout).strip() if r.returncode == 0 else ''
    if not caminho:
        destino = CASA / 'bin' / f'git_filter_repo-{FILTER_REPO_VERSAO}.py'
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            roda(['curl', '-fsSL', '-o', destino,
                  f'https://raw.githubusercontent.com/newren/git-filter-repo/v{FILTER_REPO_VERSAO}/git-filter-repo'], tempo=120)
        caminho = str(destino) if destino.exists() else ''
    if not caminho or roda([sys.executable, caminho, '--version']).returncode != 0:
        return None
    return [sys.executable, caminho]


def conta_marcas(pasta):
    msgs = texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%B']).stdout)
    autores = texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%an <%ae>%n%cn <%ce>']).stdout)
    return (sum(1 for l in msgs.splitlines() if PADRAO_MSG.search(l))
            + sum(1 for l in autores.splitlines() if PADRAO_AUTOR.search(l)))


def dono_do_repo(pasta, login):
    c = Counter(l for l in texto(roda(['git', '-C', pasta, 'log', '--all', '--format=%an|%ae']).stdout).splitlines()
                if l and not re.search(r'anthropic\.com|^claude\||\[bot\]|noreply@github\.com', l, re.I))
    if not c:
        return login, f'{login}@users.noreply.github.com'
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
    autor, email = dono_do_repo(pasta, r.get('owner', {}).get('login', ''))
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
    repos = escolhe_repos(ctx, arquivados=False, precisa_login={'repo', 'workflow'} if not ctx.args.teste else False)
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
    t.titulo('resumo', caixa=True)
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
    if not confirma(ctx.t, ctx.args, f'Sobrescrever o histórico desses {len(prontos)} no GitHub (force-push de todas as branches e tags)?'):
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
           f'git push --mirror --force https://github.com/{gh.dono}/<repo>.git', 4)

# ███████████████████████████████████████████████████████████████████████████
#
#   PARTE 2 · SEU COMPUTADOR E SEUS SITES
#   faxina · portas · raio-x · peso · atualizar
#
# ███████████████████████████████████████████████████████████████████████████

# ███████████████████████████████████████████████████████████████████████████
#
#   PARTE 2 · SEU COMPUTADOR E SEUS SITES
#   faxina · portas · raio-x · peso · atualizar
#
# ███████████████████████████████████████████████████████████████████████████

# ███████████████████████████████████████████████████████████████████████████
#
#   PARTE 2 · SEU COMPUTADOR E SEUS SITES
#   faxina · portas · raio-x · peso · atualizar
#
# ███████████████████████████████████████████████████████████████████████████

# ═══════════════════════════════ 7. faxina ═══════════════════════════════

def idade_projeto(dias, parado=True):
    if dias is None:
        return 'sem data'
    if dias < 1:
        return 'mexido hoje'
    verbo = 'parado há' if parado else 'mexido há'
    if dias < 60:
        return f'{verbo} {dias} dia' + ('s' if dias > 1 else '')
    if dias < 730:
        return f'{verbo} {dias // 30} meses'
    return f'{verbo} {dias // 365} anos'


# pasta -> (grupo, arquivos que precisam estar ao lado; vazio = vale em qualquer lugar)
PACOTES_JS = {'package.json'}
ALVOS = {
    'node_modules': ('dependências', PACOTES_JS),
    '.next': ('build', PACOTES_JS), '.nuxt': ('build', PACOTES_JS), '.svelte-kit': ('build', PACOTES_JS),
    '.turbo': ('cache', PACOTES_JS), '.parcel-cache': ('cache', PACOTES_JS), '.angular': ('cache', PACOTES_JS),
    '.astro': ('cache', PACOTES_JS), '.expo': ('cache', PACOTES_JS),
    'coverage': ('build', PACOTES_JS), 'out': ('build', PACOTES_JS),
    'dist': ('build', PACOTES_JS | {'pyproject.toml', 'setup.py'}),
    'build': ('build', PACOTES_JS | {'pyproject.toml', 'setup.py', 'build.gradle', 'build.gradle.kts', 'pubspec.yaml'}),
    'target': ('build', {'Cargo.toml', 'pom.xml'}),
    '.gradle': ('cache', {'build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts'}),
    '.dart_tool': ('cache', {'pubspec.yaml'}),
    '__pycache__': ('cache', set()), '.pytest_cache': ('cache', set()), '.mypy_cache': ('cache', set()),
    '.ruff_cache': ('cache', set()), '.tox': ('cache', set()),
}
NOMES_VENV = {'venv', '.venv', 'env', 'virtualenv'}
# saída de build pode estar commitada (ex.: o dist que publica o GitHub Pages): essas conferem o git
PODE_SER_VERSIONADO = {'dist', 'build', 'out', 'target', 'coverage'}
MARCAS_PROJETO = {'.git', 'package.json', 'pyproject.toml', 'requirements.txt', 'setup.py', 'Cargo.toml', 'pom.xml',
                  'build.gradle', 'build.gradle.kts', 'pubspec.yaml', 'go.mod'}
PULAR = {'Windows', 'Program Files', 'Program Files (x86)', 'ProgramData', '$Recycle.Bin', 'System Volume Information',
         'AppData', 'Library', 'Applications', 'proc', 'sys', 'dev', 'snap', 'Pictures', 'Music', 'Videos', 'Movies'}
PROFUNDIDADE = 9


def eh_link(e):
    # symlink, ou junção/ponto de nova análise do Windows (o npm e o pnpm usam): nunca seguir
    try:
        if e.is_symlink():
            return True
        if os.name == 'nt':
            return bool(e.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except OSError:
        return True
    return False


def tamanho(p):
    total, pilha = 0, [p]
    while pilha:
        atual = pilha.pop()
        try:
            with os.scandir(atual) as it:
                for e in it:
                    try:
                        if eh_link(e):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            pilha.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            # arquivo com vários "hard links" (o pnpm faz isso) só libera espaço quando
                            # some de todos os lugares: conta a parte dele
                            nl = getattr(st, 'st_nlink', 1) or 1
                            total += st.st_size // nl
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def raiz_do_projeto(pasta, limite, cache):
    if pasta in cache:
        return cache[pasta]
    atual, achado = pasta, None
    while True:
        try:
            nomes = set(os.listdir(atual))
        except OSError:
            nomes = set()
        if '.git' in nomes:
            achado = atual
            break
        if achado is None and nomes & MARCAS_PROJETO:
            achado = atual
        if os.path.normcase(atual) == os.path.normcase(limite) or os.path.dirname(atual) == atual:
            break
        atual = os.path.dirname(atual)
    cache[pasta] = achado or pasta
    return cache[pasta]


def estado_git(pasta_pai, nome):
    r = subprocess.run(['git', '-C', pasta_pai, 'ls-files', '--', nome], capture_output=True)
    if r.returncode != 0:
        return 'sem_git'
    return 'versionado' if r.stdout.strip() else 'livre'


def varre(raizes, pr):
    alvos, cache_raiz = [], {}
    tem_git = shutil.which('git') is not None
    for raiz in raizes:
        pilha = [(raiz, 0)]
        while pilha:
            pasta, prof = pilha.pop()
            pr.avanca(caminho_curto(pasta))
            try:
                with os.scandir(pasta) as it:
                    entradas = list(it)
            except OSError:
                continue
            nomes = {e.name for e in entradas}
            for e in entradas:
                try:
                    if eh_link(e) or not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                nome = e.name
                grupo = None
                if nome in ALVOS:
                    g, exige = ALVOS[nome]
                    if not exige or nomes & exige:
                        grupo = g
                elif nome in NOMES_VENV and os.path.isfile(os.path.join(e.path, 'pyvenv.cfg')):
                    grupo, nome = 'dependências', nome
                if grupo:
                    estado = estado_git(pasta, nome) if tem_git else 'sem_git'
                    # versionado nunca sai; nome ambíguo (build, dist…) fora do git pode ser código-fonte
                    if estado == 'versionado' or (nome in PODE_SER_VERSIONADO and estado != 'livre'):
                        continue
                    alvos.append({'caminho': e.path, 'nome': nome, 'grupo': grupo,
                                  'projeto': raiz_do_projeto(pasta, raiz, cache_raiz)})
                    continue
                if nome.startswith('.') or nome in PULAR or prof >= PROFUNDIDADE:
                    continue
                pilha.append((e.path, prof + 1))
    return alvos


def dias_parado(projeto, nomes_alvo):
    # o mais recente entre o último commit e os arquivos da raiz: trabalho sem commit também conta
    agora = time.time()
    ultimo = 0
    if os.path.isdir(os.path.join(projeto, '.git')) and shutil.which('git'):
        r = subprocess.run(['git', '-C', projeto, 'log', '-1', '--format=%ct'], capture_output=True)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            ultimo = int(r.stdout.strip())
    try:
        with os.scandir(projeto) as it:
            for e in it:
                if e.name in nomes_alvo or e.name in ('.git',):
                    continue
                try:
                    ultimo = max(ultimo, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return int((agora - ultimo) // 86400) if ultimo else None


def roda_cmd(cmd, tempo=60):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=tempo)
        return r.returncode, r.stdout.decode('utf-8', 'replace').strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ''


def caches_globais():
    casa = Path.home()
    local = Path(os.environ.get('LOCALAPPDATA') or casa / 'AppData' / 'Local')
    xdg = Path(os.environ.get('XDG_CACHE_HOME') or casa / '.cache')
    mac = casa / 'Library' / 'Caches'
    win = os.name == 'nt'
    lista = []

    def por_comando(nome, programa, pergunta, padrao, limpeza, obs=''):
        exe = shutil.which(programa)
        caminho = None
        if exe:
            cod, saida = roda_cmd([exe] + pergunta, 20)
            if cod == 0 and saida and os.path.isdir(saida.splitlines()[-1].strip()):
                caminho = saida.splitlines()[-1].strip()
        caminho = caminho or next((str(p) for p in padrao if p.is_dir()), None)
        if caminho:
            lista.append({'nome': nome, 'caminho': caminho, 'comando': [exe] + limpeza if exe else None, 'obs': obs})

    por_comando('npm', 'npm', ['config', 'get', 'cache'], [local / 'npm-cache', casa / '.npm'],
                ['cache', 'clean', '--force'])
    por_comando('pnpm', 'pnpm', ['store', 'path'], [local / 'pnpm' / 'store', casa / '.local' / 'share' / 'pnpm' / 'store',
                                                     casa / 'Library' / 'pnpm' / 'store'],
                ['store', 'prune'], 'só apaga o que nenhum projeto usa')
    por_comando('yarn', 'yarn', ['cache', 'dir'], [local / 'Yarn' / 'Cache', xdg / 'yarn', mac / 'Yarn'], ['cache', 'clean'])
    exe_py = sys.executable
    cod, saida = roda_cmd([exe_py, '-m', 'pip', 'cache', 'dir'], 20)
    if cod == 0 and saida and os.path.isdir(saida.splitlines()[-1]):
        lista.append({'nome': 'pip', 'caminho': saida.splitlines()[-1], 'comando': [exe_py, '-m', 'pip', 'cache', 'purge'], 'obs': ''})
    por_comando('bun', 'bun', ['pm', 'cache'], [casa / '.bun' / 'install' / 'cache'], ['pm', 'cache', 'rm'])
    pastas = [
        ('Playwright', [local / 'ms-playwright', xdg / 'ms-playwright', mac / 'ms-playwright'], 'baixa de novo com "npx playwright install"'),
        ('Cypress', [local / 'Cypress' / 'Cache', xdg / 'Cypress', mac / 'Cypress'], ''),
        ('node-gyp', [local / 'node-gyp', xdg / 'node-gyp', mac / 'node-gyp'], ''),
        ('Electron', [local / 'electron' / 'Cache', xdg / 'electron', mac / 'electron'], ''),
        ('Gradle', [casa / '.gradle' / 'caches'], ''),
        ('Maven', [casa / '.m2' / 'repository'], 'o próximo build Java baixa tudo de novo'),
        ('Deno', [local / 'deno', xdg / 'deno', mac / 'deno'], ''),
    ]
    for nome, candidatos, obs in pastas:
        achado = next((str(p) for p in candidatos if p.is_dir()), None)
        if achado and not any(os.path.normcase(achado) == os.path.normcase(c['caminho']) for c in lista):
            lista.append({'nome': nome, 'caminho': achado, 'comando': None, 'obs': obs})
    return [c for c in lista if not (win and c['caminho'].lower().startswith(os.environ.get('SystemRoot', 'C:\\Windows').lower()))]


def apaga(caminho):
    # no Windows: caminho maior que 260 caracteres precisa do prefixo \\?\, e arquivo somente
    # leitura (comum dentro de node_modules e .git) precisa perder o atributo antes
    alvo = caminho
    if os.name == 'nt':
        alvo = os.path.abspath(caminho)
        if alvo.startswith('\\\\') and not alvo.startswith('\\\\?\\'):
            alvo = '\\\\?\\UNC\\' + alvo[2:]  # pasta de rede: \\servidor\pasta
        elif not alvo.startswith('\\\\?\\'):
            alvo = '\\\\?\\' + alvo
    erros = []

    def ao_errar(funcao, p, _info):
        try:
            os.chmod(p, stat.S_IWRITE)
            funcao(p)
        except OSError as e:
            erros.append(e)

    if sys.version_info >= (3, 12):
        shutil.rmtree(alvo, onexc=lambda f, p, e: ao_errar(f, p, e))
    else:
        shutil.rmtree(alvo, onerror=ao_errar)
    if os.path.exists(caminho):
        raise OSError(str(erros[0]) if erros else 'não consegui apagar tudo')


def pontos_de_medida(caminhos):
    # um ponto por disco, escolhido ANTES de apagar: a pasta-mãe continua existindo depois
    pontos = {}
    for c in caminhos:
        mae = os.path.dirname(os.path.abspath(c))
        try:
            pontos.setdefault(os.stat(mae).st_dev, mae)
        except OSError:
            pass
    return list(pontos.values())


def espaco_livre(pontos):
    total = 0
    for p in pontos:
        try:
            total += shutil.disk_usage(p).free
        except OSError:
            pass
    return total


def ferramenta_faxina(t, args):
    if args.dias is None:
        args.dias = int(config('faxina_dias', 30))
    raizes = [os.path.abspath(os.path.expanduser(p)) for p in (args.pastas or [str(Path.home())])]
    for r in raizes:
        if not os.path.isdir(r):
            t.erro(f'{r} não é uma pasta.')
            return 1
    t.prompt('faxina', 'procurando em ' + ', '.join(caminho_curto(r) for r in raizes))

    with Progresso(t, None, 'pastas vistas') as pr:
        alvos = varre(raizes, pr)
        caches = caches_globais()
    medir = alvos + caches
    with Progresso(t, len(medir), 'medindo') as pr:
        with ThreadPoolExecutor(8) as ex:
            futuros = {ex.submit(tamanho, a['caminho']): a for a in medir}
            for f in as_completed(futuros):
                futuros[f]['tamanho'] = f.result()
                pr.avanca(futuros[f]['nome'])
    alvos = [a for a in alvos if a['tamanho'] >= 1024 * 1024 or a['grupo'] == 'dependências']
    caches = [c for c in caches if c['tamanho'] >= 1024 * 1024]

    projetos = {}
    for a in alvos:
        projetos.setdefault(a['projeto'], {'alvos': [], 'caminho': a['projeto']})['alvos'].append(a)
    for p in projetos.values():
        p['tamanho'] = sum(a['tamanho'] for a in p['alvos'])
        p['dias'] = dias_parado(p['caminho'], {a['nome'] for a in p['alvos']})
        p['parado'] = p['dias'] is not None and p['dias'] >= args.dias
    ordem = sorted(projetos.values(), key=lambda p: -p['tamanho'])

    rel = Relatorio('faxina')
    t.escreve()
    if not ordem and not caches:
        t.ok('Nada para limpar: nenhum node_modules, venv, build ou cache encontrado.')
        return 0
    mostrar = 15
    for p in ordem[:mostrar]:
        cor = 'amarelo' if p['parado'] else 'apagado'
        t.item('●' if p['parado'] else '·', cor, caminho_curto(p['caminho']),
               t.p(humano(p['tamanho']), 'texto') + t.p(' · ' + idade_projeto(p['dias'], p['parado']), cor))
        pedacos = sorted(p['alvos'], key=lambda a: -a['tamanho'])
        resumo = {}
        for a in pedacos:
            resumo[a['nome']] = resumo.get(a['nome'], 0) + a['tamanho']
        t.partes([t.p(f'{n} {humano(s)}', 'sub') for n, s in list(resumo.items())[:4]]
                 + ([t.p(f'+{len(resumo) - 4}', 'apagado')] if len(resumo) > 4 else []), recuo=6)
    for p in ordem:
        rel.add(f'{p["caminho"]} — {humano(p["tamanho"])} — {idade_projeto(p["dias"], p["parado"])}')
        for a in p['alvos']:
            rel.add(f'    {a["caminho"]} ({a["grupo"]}) {humano(a["tamanho"])}')
    if len(ordem) > mostrar:
        resto = ordem[mostrar:]
        t.nota(f'  e mais {len(resto)} projetos menores ({humano(sum(p["tamanho"] for p in resto))})', 2)
    if caches:
        t.escreve()
        t.titulo('caches globais')
        for c in sorted(caches, key=lambda c: -c['tamanho']):
            t.item('·', 'azul', c['nome'], t.p(humano(c['tamanho']), 'texto'), recuo=4)
            if c['obs']:
                t.nota(corta(c['obs'], t.largura - 8), 6)
            rel.add(f'cache {c["nome"]}: {c["caminho"]} — {humano(c["tamanho"])}')

    parados = [p for p in ordem if p['parado']]
    opcoes = [
        ('1', f'projetos parados há {args.dias}+ dias', parados, sum(p['tamanho'] for p in parados), f'{len(parados)} projetos'),
        ('2', 'todos os projetos', ordem, sum(p['tamanho'] for p in ordem), f'{len(ordem)} projetos'),
        ('3', 'caches globais', caches, sum(c['tamanho'] for c in caches), ', '.join(c['nome'] for c in caches[:3])
         + ('…' if len(caches) > 3 else '')),
    ]
    t.escreve()
    t.titulo('o que dá para liberar')
    for num, rotulo, itens, total, detalhe in opcoes:
        esq = f'  {t.p(num, "verde", True)}  {t.p(rotulo, "texto")}'
        dir_ = t.p(humano(total), 'verde' if total else 'apagado')
        t.escreve(esq + ' ' * max(1, t.largura - vlen(esq) - vlen(dir_)) + dir_)
        if detalhe:
            t.nota(f'     {corta(detalhe, t.largura - 6)}', 0)
    rel.add('', *(f'{r}: {humano(s)}' for _, r, _, s, _ in opcoes))
    arq = rel.salva()

    if args.teste:
        t.escreve()
        t.nota('modo teste: nada foi apagado.', 4)
        t.relatorio(arq)
        return 0
    if args.sim:
        escolha = {'1'}
    elif not t.interativo:
        t.aviso('Sem terminal para escolher; use --sim para limpar os projetos parados.')
        return 0
    else:
        t.escreve()
        t.nota('escolha um ou mais números (ex.: 1 3); Enter = 1', 2)
        escolha = set(re.findall(r'[123]', t.pergunta('faxina/limpar'))) or {'1'}
    lixo = []
    if '2' in escolha:
        lixo += [a for p in ordem for a in p['alvos']]
    elif '1' in escolha:
        lixo += [a for p in parados for a in p['alvos']]
    if '3' in escolha:
        lixo += caches
    if not lixo:
        t.ok('Nada selecionado.')
        return 0
    total = sum(a['tamanho'] for a in lixo)
    if not confirma(t, args, f'Apagar {len(lixo)} pastas ({humano(total)})? Tudo se recria com npm/pnpm/pip install.'):
        t.nota('cancelado; nada foi apagado.', 4)
        return 0

    pontos = pontos_de_medida([a['caminho'] for a in lixo])
    livre_antes = espaco_livre(pontos)
    falhas = []
    with Progresso(t, len(lixo), 'apagando') as pr:
        for a in lixo:
            try:
                if a.get('comando'):
                    cod, _ = roda_cmd(a['comando'], 600)
                    if cod != 0:
                        raise OSError(f'{" ".join(os.path.basename(x) for x in a["comando"][:2])} falhou')
                else:
                    apaga(a['caminho'])
            except OSError as e:
                falhas.append((a, str(e)))
            pr.avanca(a['nome'])
    medido = espaco_livre(pontos) - livre_antes
    falhou = {id(a) for a, _ in falhas}
    estimado = sum(a['tamanho'] for a in lixo if id(a) not in falhou)
    # outro programa pode ter escrito ou apagado no disco ao mesmo tempo: só confia no que é plausível
    liberado = medido if 0 < medido <= estimado * 1.2 + 64 * 1024 * 1024 else estimado
    t.escreve()
    for a, erro in falhas[:8]:
        t.erro(caminho_curto(a['caminho'], t.largura - 6))
        t.nota(corta(erro, t.largura - 6), 4)
    if falhas:
        t.paragrafo('O que falhou costuma estar em uso: feche o editor ou o servidor de desenvolvimento e rode de novo.',
                    4, 'apagado')
    t.titulo('resumo', caixa=True)
    t.partes([t.p(f'{humano(liberado)} liberados', 'verde'),
              t.p(f'{len(lixo) - len(falhas)} pastas apagadas', 'texto')]
             + ([t.p(f'{len(falhas)} falharam', 'vermelho')] if falhas else []))
    t.paragrafo('Para voltar a usar um projeto: npm install (ou pnpm install, ou pip install -r requirements.txt).',
                4, 'apagado')
    return 0


# ═══════════════════════════════ 8. portas ═══════════════════════════════

PORTAS_CONHECIDAS = {
    3000: 'React/Next/Express', 3001: 'servidor de dev', 3333: 'API', 4000: 'servidor de dev', 4173: 'Vite (preview)',
    4200: 'Angular', 5000: 'Flask', 5173: 'Vite', 5174: 'Vite', 5432: 'PostgreSQL', 5555: 'Prisma Studio',
    6006: 'Storybook', 6379: 'Redis', 3306: 'MySQL', 8000: 'Django/uvicorn', 8080: 'servidor de dev',
    8081: 'Metro (Expo)', 9229: 'depurador do Node', 19000: 'Expo', 24678: 'Vite (recarga)', 27017: 'MongoDB',
}
PORTAS_DEV = {3000, 3001, 3333, 4000, 4173, 4200, 5000, 5173, 5174, 5555, 6006, 8000, 8080, 8081, 19000, 24678}
FRAMEWORKS = [
    (r'[\\/]next[\\/]|next(\.js)? (dev|start)', 'Next.js'), (r'[\\/]vite[\\/]|\bvite\b', 'Vite'),
    (r'react-scripts', 'Create React App'), (r'[\\/]nuxt|nuxi', 'Nuxt'), (r'[\\/]astro[\\/]|\bastro\b', 'Astro'),
    (r'@nestjs|nest start', 'NestJS'), (r'storybook', 'Storybook'), (r'prisma studio|[\\/]prisma[\\/]', 'Prisma Studio'),
    (r'expo|metro', 'Expo'), (r'webpack', 'webpack'), (r'nodemon', 'nodemon'), (r'\btsx\b', 'tsx'),
    (r'ts-node', 'ts-node'), (r'json-server', 'json-server'), (r'live-server', 'Live Server'),
    (r'uvicorn', 'uvicorn'), (r'gunicorn', 'gunicorn'), (r'flask', 'Flask'), (r'manage\.py', 'Django'),
    (r'http\.server', 'http.server'), (r'vercel', 'vercel dev'), (r'--watch', 'node --watch'),
]
FRAMEWORKS = [(re.compile(r, re.I), n) for r, n in FRAMEWORKS]
SISTEMA = {'system', 'svchost.exe', 'wininit.exe', 'services.exe', 'lsass.exe', 'csrss.exe', 'smss.exe',
           'init', 'systemd', 'launchd', 'kernel_task'}


def roda_txt(cmd, tempo=20):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=tempo)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ''
    return r.returncode, r.stdout.decode('utf-8', 'replace')


def _endereco_hex(h):
    import socket
    dados = bytes.fromhex(h)
    if len(dados) == 4:
        return socket.inet_ntop(socket.AF_INET, dados[::-1])
    # o kernel grava IPv6 em palavras de 4 bytes na ordem da máquina
    return socket.inet_ntop(socket.AF_INET6, b''.join(dados[i:i + 4][::-1] for i in range(0, 16, 4)))


def _info_linux(pid):
    info = {'nome': None, 'cmd': '', 'cwd': None, 'inicio': None, 'usuario': None}
    if pid is None:
        return info
    base = f'/proc/{pid}'
    try:
        info['nome'] = open(f'{base}/comm').read().strip()
        info['cmd'] = open(f'{base}/cmdline', 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
    except OSError:
        pass
    try:
        info['cwd'] = os.readlink(f'{base}/cwd')
    except OSError:
        pass
    try:
        import pwd
        info['usuario'] = pwd.getpwuid(os.stat(base).st_uid).pw_name
    except (OSError, KeyError, ImportError):
        pass
    try:
        campos = open(f'{base}/stat').read().rsplit(')', 1)[1].split()
        boot = next(int(l.split()[1]) for l in open('/proc/stat') if l.startswith('btime'))
        info['inicio'] = boot + int(campos[19]) / os.sysconf('SC_CLK_TCK')
    except (OSError, StopIteration, ValueError, IndexError):
        pass
    return info


def _ouvintes_linux():
    alvo = {}
    for arq in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            linhas = open(arq).read().splitlines()[1:]
        except OSError:
            continue
        for l in linhas:
            c = l.split()
            if len(c) < 10 or c[3] != '0A':  # 0A = LISTEN
                continue
            end, porta = c[1].split(':')
            alvo[c[9]] = (int(porta, 16), _endereco_hex(end))
    donos = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            fds = os.listdir(f'/proc/{pid}/fd')
        except OSError:
            continue  # processo de outro usuário: só o administrador vê
        for fd in fds:
            try:
                link = os.readlink(f'/proc/{pid}/fd/{fd}')
            except OSError:
                continue
            if link.startswith('socket:[') and link[8:-1] in alvo:
                donos.setdefault(link[8:-1], int(pid))
    return [dict({'porta': p, 'endereco': e, 'pid': donos.get(i)}, **_info_linux(donos.get(i))) for i, (p, e) in alvo.items()]


def _etime(txt):
    # formato do ps: [[DD-]HH:]MM:SS
    dias, _, resto = txt.strip().rpartition('-')
    partes = [int(x) for x in resto.split(':') if x.isdigit()]
    seg = 0
    for x in partes:
        seg = seg * 60 + x
    return seg + (int(dias) * 86400 if dias.isdigit() else 0)


def _ouvintes_lsof():
    cod, out = roda_txt(['lsof', '-nP', '-iTCP', '-sTCP:LISTEN', '-FpcLn'])
    res, pid, nome, usuario = [], None, None, None
    for l in out.splitlines():
        k, v = l[:1], l[1:]
        if k == 'p':
            pid = int(v)
        elif k == 'c':
            nome = v
        elif k == 'L':
            usuario = v
        elif k == 'n' and ':' in v:
            end, _, porta = v.rpartition(':')
            end = end.strip('[]')
            if porta.isdigit():
                res.append({'porta': int(porta), 'endereco': '0.0.0.0' if end == '*' else end, 'pid': pid,
                            'nome': nome, 'usuario': usuario, 'cmd': '', 'cwd': None, 'inicio': None})
    for pid in {r['pid'] for r in res}:
        _, linha = roda_txt(['ps', '-o', 'etime=', '-o', 'command=', '-p', str(pid)])
        etime, _, cmd = linha.strip().partition(' ')
        _, cwd = roda_txt(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'])
        cwd = next((l[1:] for l in cwd.splitlines() if l.startswith('n')), None)
        for r in res:
            if r['pid'] == pid:
                r.update(cmd=cmd.strip(), cwd=cwd, inicio=time.time() - _etime(etime) if etime else None)
    return res


def _ouvintes_windows():
    res = []
    for proto in ('TCP', 'TCPv6'):
        _, out = roda_txt(['netstat', '-ano', '-p', proto])
        for l in out.splitlines():
            c = l.split()
            # porta escutando = endereço remoto zerado; não depende de "LISTENING", que muda com o idioma
            if len(c) >= 5 and c[0].upper().startswith('TCP') and c[2] in ('0.0.0.0:0', '[::]:0') and c[-1].isdigit():
                end, _, porta = c[1].rpartition(':')
                if porta.isdigit():
                    res.append({'porta': int(porta), 'endereco': end.strip('[]'), 'pid': int(c[-1]),
                                'nome': None, 'cmd': '', 'cwd': None, 'inicio': None, 'usuario': None})
    pids = sorted({r['pid'] for r in res if r['pid'] > 4})
    info = {}
    if pids:
        filtro = ' OR '.join(f'ProcessId={p}' for p in pids)
        script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter '" + filtro + "' | "
                  "Select-Object ProcessId,Name,CommandLine,@{n='Inicio';e={$_.CreationDate.ToUniversalTime().ToString('o')}} | "
                  "ConvertTo-Json -Compress")
        cod, out = roda_txt(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], 40)
        try:
            dados = json.loads(out) if out.strip() else []
            for d in (dados if isinstance(dados, list) else [dados]):
                inicio = None
                if d.get('Inicio'):
                    try:
                        inicio = datetime.fromisoformat(d['Inicio'][:26].rstrip('Z')).replace(tzinfo=timezone.utc).timestamp()
                    except ValueError:
                        pass
                info[d['ProcessId']] = {'nome': d.get('Name'), 'cmd': d.get('CommandLine') or '', 'inicio': inicio}
        except ValueError:
            pass
        if not info:
            _, out = roda_txt(['tasklist', '/FO', 'CSV', '/NH'])
            for l in out.splitlines():
                partes = [x.strip('"') for x in l.split('","')]
                if len(partes) > 1 and partes[1].isdigit():
                    info[int(partes[1])] = {'nome': partes[0], 'cmd': '', 'inicio': None}
    for r in res:
        r.update(info.get(r['pid'], {'nome': 'System' if r['pid'] in (0, 4) else None}))
    return res


def ouvintes():
    if os.name == 'nt':
        brutos = _ouvintes_windows()
    elif os.path.exists('/proc/net/tcp'):
        brutos = _ouvintes_linux()
    else:
        brutos = _ouvintes_lsof()
    # a mesma porta costuma aparecer em IPv4 e IPv6: junta, e "rede" ganha de "só este PC"
    juntos = {}
    for r in brutos:
        chave = (r['porta'], r['pid'])
        atual = juntos.setdefault(chave, dict(r, enderecos=set()))
        atual['enderecos'].add(r['endereco'])
    for r in juntos.values():
        r['rede'] = any(e in ('0.0.0.0', '::', '*') for e in r['enderecos'])
        r['framework'] = next((n for rx, n in FRAMEWORKS if rx.search(r.get('cmd') or '')), None)
        if not r.get('cwd'):
            # sem a pasta atual (Windows), o caminho do node_modules na linha de comando entrega o projeto
            m = re.search(r'([A-Za-z]:)?[\\/][^"\s]*?(?=[\\/]node_modules[\\/])', r.get('cmd') or '')
            r['projeto'] = m.group(0) if m else None
        else:
            r['projeto'] = r['cwd']
        r['dev'] = bool(r['framework']) or r['porta'] in PORTAS_DEV
    return sorted(juntos.values(), key=lambda r: r['porta'])


def tempo_rodando(inicio):
    if not inicio:
        return ''
    s = max(0, time.time() - inicio)
    if s < 60:
        return 'agora'
    if s < 3600:
        return f'{int(s // 60)} min'
    if s < 86400:
        return f'{int(s // 3600)} h'
    return f'{int(s // 86400)} dia' + ('s' if s >= 2 * 86400 else '')


def _vivo(pid):
    if os.name == 'nt':
        # CSV: "nome","pid",...; procurar o número solto no texto confundia com a coluna de memória
        _, out = roda_txt(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'])
        return any(len(c) > 1 and c[1] == str(pid) for c in (l.strip().strip('"').split('","') for l in out.splitlines()))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _descendentes(pid):
    _, out = roda_txt(['ps', '-A', '-o', 'pid=', '-o', 'ppid='])
    filhos = {}
    for l in out.splitlines():
        c = l.split()
        if len(c) == 2 and c[0].isdigit() and c[1].isdigit():
            filhos.setdefault(int(c[1]), []).append(int(c[0]))
    ordem, fila = [], [pid]
    while fila:
        atual = fila.pop()
        for f in filhos.get(atual, []):
            ordem.append(f)
            fila.append(f)
    return ordem


def encerra(pid):
    # primeiro pede para fechar (o servidor salva o que precisa); só força se não obedecer em 3 s
    import signal
    for forcar in (False, True):
        if os.name == 'nt':
            roda_txt(['taskkill', '/PID', str(pid), '/T'] + (['/F'] if forcar else []))
        else:
            for p in list(reversed(_descendentes(pid))) + [pid]:
                try:
                    os.kill(p, signal.SIGKILL if forcar else signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        for _ in range(30):
            if not _vivo(pid):
                return 'forçado' if forcar else 'fechou'
            time.sleep(0.1)
    return None


def porta_livre(inicio):
    import socket
    for p in range(inicio, min(inicio + 500, 65536)):
        livre = True
        for end in ('127.0.0.1', '0.0.0.0'):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind((end, p))
            except OSError:
                livre = False
            finally:
                s.close()
        if livre:
            return p
    return None


def mostra_ouvinte(t, r, detalhado=False):
    rotulo = r['framework'] or r.get('nome') or '?'
    if not r['framework'] and r['porta'] in PORTAS_CONHECIDAS and not r['dev']:
        rotulo = f'{rotulo} ({PORTAS_CONHECIDAS[r["porta"]]})'
    pedacos = []
    if r.get('projeto'):
        pedacos.append(t.p(corta(os.path.basename(r['projeto'].rstrip('/\\')) or r['projeto'], 22), 'sub'))
    if r.get('inicio'):
        pedacos.append(t.p(tempo_rodando(r['inicio']), 'apagado'))
    if r['rede'] and r['dev']:
        pedacos.append(t.p('rede', 'amarelo'))
    t.item('●' if r['dev'] else '·', 'verde' if r['dev'] else 'apagado', f'{r["porta"]:<5} {rotulo}',
           t.p(' · ', 'apagado').join(pedacos), cor_nome='texto' if r['dev'] else 'sub')
    if detalhado:
        if r.get('projeto'):
            t.nota(caminho_curto(r['projeto'], t.largura - 8), 8)
        if r.get('cmd'):
            t.nota(corta(r['cmd'], t.largura - 8), 8)
        t.nota(f'processo {r["pid"]}' + (f' · {r["nome"]}' if r.get('nome') else '')
               + (f' · usuário {r["usuario"]}' if r.get('usuario') else ''), 8)
        if r['rede'] and r['dev']:
            t.paragrafo('Aberto para a rede toda: qualquer pessoa no mesmo Wi-Fi acessa esse servidor. '
                        'Se não for de propósito, rode com --host 127.0.0.1 (ou localhost).', 8, 'amarelo')


def encerra_com_confirmacao(t, args, r):
    nome = (r.get('nome') or '').lower()
    if r['pid'] in (None, 0, 1, 4) or nome in SISTEMA:
        t.erro('É um processo do sistema; não vou encerrar.')
        return
    if r.get('usuario') and r['usuario'] != _usuario_atual():
        t.aviso(f'Esse processo é do usuário {r["usuario"]}: pode precisar de administrador.')
    rotulo = r['framework'] or r.get('nome') or f'processo {r["pid"]}'
    if not confirma(t, args, f'Encerrar {rotulo} (processo {r["pid"]}) na porta {r["porta"]}?'):
        t.nota('nada foi encerrado.', 4)
        return
    resultado = encerra(r['pid'])
    if resultado == 'fechou':
        t.ok(f'{rotulo} fechou. A porta {r["porta"]} está livre.')
    elif resultado == 'forçado':
        t.ok(f'{rotulo} não respondeu e foi encerrado à força. A porta {r["porta"]} está livre.')
    else:
        t.erro('Não consegui encerrar; tente de novo como administrador.')


def _usuario_atual():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return None


def ferramenta_portas(t, args):
    if args.livre is not None:
        p = porta_livre(args.livre)
        if p is None:
            t.erro(f'Nenhuma porta livre entre {args.livre} e {args.livre + 499}.')
        else:
            t.prompt('portas', f'próxima porta livre a partir da {args.livre}:')
            t.escreve('    ' + t.p(str(p), 'verde', True))
        return 0
    with Progresso(t, None, 'olhando as portas') as pr:
        lista = ouvintes()
        pr.avanca('', len(lista))
    if args.porta:
        da_porta = [r for r in lista if r['porta'] == args.porta]
        if not da_porta:
            t.ok(f'A porta {args.porta} está livre.')
            return 0
        t.prompt('portas', f'quem está na {args.porta}')
        t.escreve()
        for r in da_porta:
            mostra_ouvinte(t, r, detalhado=True)
        if args.matar or (t.interativo and not args.teste):
            t.escreve()
            for r in da_porta:
                encerra_com_confirmacao(t, args, r)
        return 0
    visiveis = lista if args.todas else [r for r in lista if r['dev'] or r['porta'] < 10000]
    escondidas = len(lista) - len(visiveis)
    dev = sum(1 for r in visiveis if r['dev'])
    t.prompt('portas', f'{len(visiveis)} porta{"s" if len(visiveis) != 1 else ""} abertas · {dev} de desenvolvimento')
    t.escreve()
    if not visiveis:
        t.ok('Nenhuma porta aberta.')
    for r in visiveis:
        mostra_ouvinte(t, r)
    if escondidas:
        t.paragrafo(f'+ {escondidas} portas altas de sistema (veja com --todas)', 4, 'apagado')
    sem_dono = sum(1 for r in visiveis if r['pid'] is None)
    if sem_dono:
        t.paragrafo(f'{sem_dono} sem processo visível: são de outro usuário (rode como administrador para ver).',
                    4, 'apagado')
    expostas = [r for r in visiveis if r['rede'] and r['dev']]
    if expostas:
        t.escreve()
        um = len(expostas) == 1
        t.paragrafo(f'{len(expostas)} servidor{"" if um else "es"} de desenvolvimento '
                    f'abert{"o" if um else "os"} para a rede toda (marcado{"" if um else "s"} com "rede"). '
                    'Quem estiver no mesmo Wi-Fi consegue acessar.', 4, 'amarelo')
    if t.interativo and not args.teste and visiveis:
        t.escreve()
        t.nota('digite uma porta para ver os detalhes e encerrar; Enter = sair', 2)
        escolha = t.pergunta('portas/encerrar').strip()
        if escolha.isdigit():
            alvo = [r for r in visiveis if r['porta'] == int(escolha)]
            if not alvo:
                t.ok(f'A porta {escolha} está livre.')
            for r in alvo:
                t.escreve()
                mostra_ouvinte(t, r, detalhado=True)
                encerra_com_confirmacao(t, args, r)
    return 0


# ═══════════════════════════════ 9. raio-x ═══════════════════════════════

UA_NAVEGADOR = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0 Safari/537.36 ferramentas/raiox')
ERROS_REDE = {6: 'o domínio não existe', 7: 'conexão recusada', 28: 'demorou demais', 35: 'erro de HTTPS',
              47: 'redirecionamentos demais', 51: 'certificado HTTPS inválido', 52: 'o servidor não respondeu',
              56: 'a conexão caiu', 58: 'certificado HTTPS inválido', 60: 'certificado HTTPS inválido'}
CATEGORIAS = [('desempenho', 'desempenho'), ('acessibilidade', 'acessibilidade'), ('boas-praticas', 'boas práticas'),
              ('seo', 'SEO'), ('seguranca', 'segurança'), ('links', 'links')]
PESO_NIVEL = {'falha': 0, 'aviso': 2, 'info': 3, 'ok': 3}


def _arquivo_tmp(sufixo):
    pasta = CASA / 'tmp'
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f'r{os.getpid()}-{threading.get_ident()}-{time.monotonic_ns()}{sufixo}'


def busca(url, metodo='GET', tempo=25, seguir=True, corpo=True):
    cab, saida = _arquivo_tmp('.h'), _arquivo_tmp('.b')
    fmt = '\t'.join(['%{http_code}', '%{url_effective}', '%{http_version}', '%{time_starttransfer}',
                     '%{time_total}', '%{size_download}'])
    args = ['curl', '-sS', '--compressed', '--max-time', str(tempo), '-A', UA_NAVEGADOR, '-D', str(cab),
            '-o', str(saida) if corpo else os.devnull, '-w', fmt]
    if seguir:
        args += ['-L', '--max-redirs', '10']
    if metodo == 'HEAD':
        args += ['-I']
    args.append(url)
    res = {'url': url, 'status': 0, 'url_final': url, 'http': '', 'ttfb': 0.0, 'total': 0.0, 'baixado': 0,
           'cabecalhos': {}, 'cookies': [], 'cadeia': [], 'corpo': b'', 'erro': None}
    try:
        r = subprocess.run(args, capture_output=True, timeout=tempo + 10)
        partes = r.stdout.decode('utf-8', 'replace').strip().split('\t')
        if len(partes) >= 6 and partes[0].isdigit():
            num = lambda x: float(x.replace(',', '.') or 0)
            res.update(status=int(partes[0]), url_final=partes[1] or url, http=partes[2], ttfb=num(partes[3]),
                       total=num(partes[4]), baixado=int(num(partes[5])))
        if r.returncode != 0 and not res['status']:
            res['erro'] = ERROS_REDE.get(r.returncode, f'erro de rede (curl {r.returncode})')
        if cab.exists():
            for bloco in re.split(r'\r?\n\r?\n', cab.read_text('utf-8', 'replace').strip()):
                linhas = bloco.splitlines()
                if not linhas or not linhas[0].upper().startswith('HTTP'):
                    continue
                status = linhas[0].split()[1] if len(linhas[0].split()) > 1 else '?'
                hdr, cookies = {}, []
                for l in linhas[1:]:
                    k, _, v = l.partition(':')
                    k, v = k.strip().lower(), v.strip()
                    if k == 'set-cookie':
                        cookies.append(v)
                    elif k:
                        hdr[k] = v
                res['cadeia'].append((status, hdr.get('location', '')))
                res['cabecalhos'], res['cookies'] = hdr, cookies
        if corpo and saida.exists():
            res['corpo'] = saida.read_bytes()
    except (OSError, subprocess.TimeoutExpired):
        res['erro'] = 'demorou demais'
    finally:
        for f in (cab, saida):
            try:
                f.unlink()
            except OSError:
                pass
    return res


def acha_navegador():
    if os.environ.get('CHROME_PATH') and os.path.exists(os.environ['CHROME_PATH']):
        return os.environ['CHROME_PATH']
    cands = []
    if os.name == 'nt':
        for base in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
            if base:
                cands += [os.path.join(base, *p) for p in (('Google', 'Chrome', 'Application', 'chrome.exe'),
                                                          ('Microsoft', 'Edge', 'Application', 'msedge.exe'),
                                                          ('BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
                                                          ('Chromium', 'Application', 'chrome.exe'))]
    elif sys.platform == 'darwin':
        cands = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                 '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                 '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
                 '/Applications/Chromium.app/Contents/MacOS/Chromium']
    else:
        cands = [shutil.which(n) for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
                                           'microsoft-edge', 'brave-browser')]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _flags_navegador():
    flags = ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--mute-audio']
    if os.name != 'nt' and hasattr(os, 'geteuid') and os.geteuid() == 0:
        flags.append('--no-sandbox')  # o Chrome se recusa a abrir como root sem isso
    return flags


def dom_renderizado(nav, url):
    try:
        r = subprocess.run([nav] + _flags_navegador() + ['--virtual-time-budget=8000', '--dump-dom', url],
                           capture_output=True, timeout=90)
        html = r.stdout.decode('utf-8', 'replace')
        return html if '<' in html else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def roda_lighthouse(url, nav, desktop, categorias='performance,accessibility,best-practices,seo'):
    npx = shutil.which('npx')
    if not npx:
        return None, 'sem Node instalado (o Lighthouse roda com npx)'
    if not nav:
        return None, 'nenhum Chrome, Edge ou Brave encontrado'
    saida = _arquivo_tmp('.json')
    cmd = [npx, '--yes', 'lighthouse@12', url, '--output=json', f'--output-path={saida}', '--quiet',
           '--chrome-flags=' + ' '.join(_flags_navegador()), '--locale=pt-BR',
           '--only-categories=' + categorias]
    if desktop:
        cmd.append('--preset=desktop')
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=420, env=dict(os.environ, CHROME_PATH=nav))
    except (OSError, subprocess.TimeoutExpired):
        return None, 'o Lighthouse demorou demais'
    if not saida.exists():
        erro = [l for l in r.stderr.decode('utf-8', 'replace').splitlines() if l.strip()]
        return None, corta(erro[-1] if erro else 'o Lighthouse falhou', 70)
    try:
        dados = json.loads(saida.read_text(encoding='utf-8'))
    except ValueError:
        return None, 'resposta do Lighthouse ilegível'
    finally:
        saida.unlink()
    return dados, None


VAZIOS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
CAPTURA = {'a', 'button', 'label', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'summary'}
MARCOS = {'main': 'main', 'nav': 'navigation', 'header': 'banner', 'footer': 'contentinfo'}


class LeitorHTML:
    def __init__(self, html):
        from html.parser import HTMLParser
        leitor = self

        class _P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                leitor._abre(tag, {k: (v if v is not None else '') for k, v in attrs})

            def handle_startendtag(self, tag, attrs):
                leitor._abre(tag, {k: (v if v is not None else '') for k, v in attrs})
                if tag in CAPTURA:
                    leitor._fecha(tag)

            def handle_endtag(self, tag):
                leitor._fecha(tag)

            def handle_data(self, data):
                leitor._dado(data)

        self.lang = None
        self.titulo = None
        self.metas, self.links, self.titulos, self.imgs, self.scripts = [], [], [], [], []
        self.campos, self.botoes, self.ancoras, self.iframes, self.midias, self.jsonld = [], [], [], [], [], []
        self.rotulos_for, self.marcos, self.ids = set(), set(), Counter()
        self.estilos_head = self.tabindex_pos = self.elementos = 0
        self._head = self._corpo = False
        self._label = 0
        self._codigo = None
        self._pilha = []
        self._texto = []
        try:
            p = _P(convert_charrefs=True)
            p.feed(html)
            p.close()
        except Exception:  # HTML muito quebrado: fica com o que deu para ler
            pass
        self.texto = ' '.join(self._texto)

    def _abre(self, tag, a):
        self.elementos += 1
        if a.get('id'):
            self.ids[a['id']] += 1
        ti = (a.get('tabindex') or '').strip()
        if ti.isdigit() and int(ti) > 0:
            self.tabindex_pos += 1
        if a.get('role') in MARCOS.values():
            self.marcos.add(a['role'])
        if tag in MARCOS:
            self.marcos.add(MARCOS[tag])
        if tag == 'html':
            self.lang = a.get('lang') or a.get('xml:lang')
        elif tag == 'head':
            self._head = True
        elif tag == 'body':
            self._head, self._corpo = False, True
        elif tag == 'meta':
            self.metas.append(a)
        elif tag == 'link':
            self.links.append(a)
            if self._head and 'stylesheet' in (a.get('rel') or '').lower():
                self.estilos_head += 1
        elif tag == 'img':
            self.imgs.append(a)
            for el in self._pilha:
                el['imgs'].append(a.get('alt'))
        elif tag in ('script', 'style'):
            if tag == 'script':
                self.scripts.append(dict(a, _head=self._head))
            self._codigo = [] if (a.get('type') or '').lower() == 'application/ld+json' else False
        elif tag in ('input', 'select', 'textarea'):
            self.campos.append(dict(a, _tag=tag, _em_label=self._label > 0))
        elif tag == 'iframe':
            self.iframes.append(a)
        elif tag in ('video', 'audio'):
            self.midias.append(dict(a, _tag=tag))
        if tag == 'label':
            self._label += 1
            if a.get('for'):
                self.rotulos_for.add(a['for'])
        if tag in CAPTURA:
            self._pilha.append({'tag': tag, 'a': a, 'texto': [], 'imgs': []})

    def _fecha(self, tag):
        if tag == 'head':
            self._head = False
        elif tag == 'label' and self._label:
            self._label -= 1
        elif tag in ('script', 'style'):
            if isinstance(self._codigo, list):
                self.jsonld.append(''.join(self._codigo))
            self._codigo = None
        if tag in CAPTURA:
            for i in range(len(self._pilha) - 1, -1, -1):
                if self._pilha[i]['tag'] == tag:
                    self._registra(self._pilha.pop(i))
                    break

    def _dado(self, d):
        if self._codigo is not None:
            if isinstance(self._codigo, list):
                self._codigo.append(d)
            return
        for el in self._pilha:
            el['texto'].append(d)
        if self._corpo and d.strip():
            self._texto.append(d.strip())

    def _registra(self, el):
        a, tag = el['a'], el['tag']
        txt = ' '.join(''.join(el['texto']).split())
        nome = (txt or (a.get('aria-label') or '').strip() or (a.get('title') or '').strip()
                or ' '.join(x for x in el['imgs'] if x) or ('(aria-labelledby)' if a.get('aria-labelledby') else ''))
        if tag == 'title':
            if self.titulo is None:
                self.titulo = txt
        elif tag[0] == 'h' and tag[1:].isdigit():
            self.titulos.append((int(tag[1]), txt))
        elif tag == 'a':
            self.ancoras.append({'href': a.get('href'), 'nome': nome, 'texto': txt, 'target': a.get('target'),
                                 'rel': a.get('rel') or ''})
        elif tag == 'button':
            self.botoes.append({'nome': nome, 'classe': a.get('class') or '', 'id': a.get('id') or ''})

    def meta(self, chave):
        for m in self.metas:
            if (m.get('name') or m.get('property') or '').lower() == chave:
                return (m.get('content') or '').strip()
        return None

    def link_rel(self, rel):
        return [l for l in self.links if rel in (l.get('rel') or '').lower().split()]


def pl(n, sing, plur=None):
    return f'{n} {sing if n == 1 else (plur or sing + "s")}'


def ach(cat, nivel, ident, titulo, exemplos=None, dica='', ref=''):
    return {'cat': cat, 'nivel': nivel, 'id': ident, 'titulo': titulo, 'exemplos': exemplos or [], 'dica': dica, 'ref': ref}


GENERICOS = re.compile(r'^(clique aqui|clique|aqui|saiba mais|leia mais|veja mais|mais|link|click here|here|read more|learn more)$', re.I)


def checa_acessibilidade(d):
    A = []
    A.append(ach('acessibilidade', 'ok' if d.lang else 'falha', 'lang', 'idioma da página (<html lang>)',
                 dica='ponha <html lang="pt-BR">: o leitor de tela usa isso para escolher a voz', ref='WCAG 3.1.1'))
    A.append(ach('acessibilidade', 'ok' if d.titulo else 'falha', 'titulo', 'título da página',
                 dica='todo documento precisa de <title>', ref='WCAG 2.4.2'))
    # imagem escondida do leitor de tela, ou com nome por aria, não precisa de alt (como no axe)
    sem_alt = [i for i in d.imgs if 'alt' not in i and (i.get('aria-hidden') or '').lower() != 'true'
               and (i.get('role') or '').lower() not in ('presentation', 'none')
               and not (i.get('aria-label') or i.get('aria-labelledby') or i.get('title'))]
    A.append(ach('acessibilidade', 'falha' if sem_alt else 'ok', 'img-alt',
                 pl(len(sem_alt), 'imagem', 'imagens') + ' sem texto alternativo' if sem_alt else 'imagens com texto alternativo',
                 [f'<img src="{corta(i.get("src", ""), 40)}">' for i in sem_alt[:3]],
                 'descreva a imagem em alt="…"; se for só decoração, use alt=""', 'WCAG 1.1.1'))
    sem_nome_a = [x for x in d.ancoras if x['href'] is not None and not x['nome']]
    A.append(ach('acessibilidade', 'falha' if sem_nome_a else 'ok', 'link-nome',
                 pl(len(sem_nome_a), 'link') + ' sem nome' if sem_nome_a else 'links com nome',
                 [f'<a href="{corta(x["href"] or "", 40)}">' for x in sem_nome_a[:3]],
                 'link só com ícone precisa de aria-label="…" (ou alt na imagem dentro dele)', 'WCAG 2.4.4'))
    sem_nome_b = [b for b in d.botoes if not b['nome']]
    A.append(ach('acessibilidade', 'falha' if sem_nome_b else 'ok', 'botao-nome',
                 pl(len(sem_nome_b), 'botão', 'botões') + ' sem nome' if sem_nome_b else 'botões com nome',
                 [f'<button{" id=" + chr(34) + b["id"] + chr(34) if b["id"] else ""}{" class=" + chr(34) + corta(b["classe"], 24) + chr(34) if b["classe"] else ""}>' for b in sem_nome_b[:3]],
                 'botão só com ícone precisa de aria-label="…"', 'WCAG 4.1.2'))
    campos = [c for c in d.campos if (c.get('type') or 'text').lower() not in ('hidden', 'submit', 'button', 'reset', 'image')]
    sem_rotulo, so_placeholder = [], []
    for c in campos:
        tem = c['_em_label'] or (c.get('id') and c['id'] in d.rotulos_for) or c.get('aria-label') or c.get('aria-labelledby') or c.get('title')
        if not tem:
            (so_placeholder if c.get('placeholder') else sem_rotulo).append(c)
    A.append(ach('acessibilidade', 'falha' if sem_rotulo else 'aviso' if so_placeholder else 'ok', 'campo-rotulo',
                 pl(len(sem_rotulo) + len(so_placeholder), 'campo') + ' sem rótulo' if sem_rotulo or so_placeholder else 'campos com rótulo',
                 [f'<{c["_tag"]} name="{c.get("name", "")}"' + (f' placeholder="{corta(c["placeholder"], 20)}"' if c.get('placeholder') else '') + '>'
                  for c in (sem_rotulo + so_placeholder)[:3]],
                 'use <label for="id">; placeholder some quando a pessoa digita e não substitui o rótulo', 'WCAG 1.3.1 · 3.3.2'))
    pessoais = [c for c in campos if not c.get('autocomplete') and ((c.get('type') or '').lower() in ('email', 'tel')
                or re.search(r'e-?mail|^nome|name|telefone|phone|celular|cep|endere', c.get('name') or c.get('id') or '', re.I))]
    if pessoais:
        A.append(ach('acessibilidade', 'aviso', 'autocomplete', pl(len(pessoais), 'campo pessoal', 'campos pessoais') + ' sem autocomplete',
                     [f'<input name="{c.get("name", "")}" type="{c.get("type", "text")}">' for c in pessoais[:3]],
                     'autocomplete="email", "tel", "name"… deixa o navegador preencher; ajuda quem tem dificuldade motora ou cognitiva',
                     'WCAG 1.3.5'))
    h1 = [t for n, t in d.titulos if n == 1]
    if not d.titulos:
        A.append(ach('acessibilidade', 'falha', 'titulos', 'nenhum título (h1…h6) na página',
                     dica='os títulos são o "sumário" de quem usa leitor de tela', ref='WCAG 1.3.1'))
    else:
        A.append(ach('acessibilidade', 'ok' if len(h1) == 1 else 'aviso', 'h1',
                     'um h1 na página' if len(h1) == 1 else (f'{len(h1)} h1 na página' if h1 else 'a página não tem h1'),
                     [corta(t, 50) for t in h1[:3]], 'deixe um único h1 com o assunto principal', 'WCAG 1.3.1'))
        pulos, ant = [], 0
        for n, t in d.titulos:
            if ant and n > ant + 1:
                pulos.append(f'h{ant} → h{n} ("{corta(t, 30)}")')
            ant = n
        A.append(ach('acessibilidade', 'aviso' if pulos else 'ok', 'ordem-titulos',
                     'títulos pulam de nível' if pulos else 'títulos em ordem', pulos[:3],
                     'não pule níveis: depois de h2 vem h3', 'WCAG 1.3.1'))
    dup = [i for i, n in d.ids.items() if n > 1]
    A.append(ach('acessibilidade', 'aviso' if dup else 'ok', 'ids', pl(len(dup), 'id repetido', 'ids repetidos') if dup else 'ids únicos',
                 [f'id="{i}"' for i in dup[:3]], 'aria-labelledby e <label for> se perdem com id repetido', 'WCAG 4.1.2'))
    A.append(ach('acessibilidade', 'aviso' if d.tabindex_pos else 'ok', 'tabindex',
                 pl(d.tabindex_pos, 'elemento') + ' com tabindex positivo' if d.tabindex_pos else 'ordem do Tab natural',
                 dica='tabindex maior que 0 bagunça a ordem do teclado; use 0 ou -1', ref='WCAG 2.4.3'))
    sem_titulo = [f for f in d.iframes if not (f.get('title') or f.get('aria-label'))]
    if d.iframes:
        A.append(ach('acessibilidade', 'falha' if sem_titulo else 'ok', 'iframe', pl(len(sem_titulo), 'iframe') + ' sem título' if sem_titulo else 'iframes com título',
                     [f'<iframe src="{corta(f.get("src", ""), 40)}">' for f in sem_titulo[:3]], 'dê title="…" ao iframe', 'WCAG 4.1.2'))
    auto = [m for m in d.midias if 'autoplay' in m and 'muted' not in m]
    if auto:
        A.append(ach('acessibilidade', 'falha', 'autoplay', pl(len(auto), 'mídia tocando som sozinha', 'mídias tocando som sozinhas'),
                     [f'<{m["_tag"]} src="{corta(m.get("src", ""), 40)}" autoplay>' for m in auto[:3]], dica='som automático atrapalha o leitor de tela: use muted ou tire o autoplay', ref='WCAG 1.4.2'))
    vp = (d.meta('viewport') or '').lower().replace(' ', '')
    bloqueia = 'user-scalable=no' in vp or 'user-scalable=0' in vp or re.search(r'maximum-scale=(1(\.0)?|0\.\d+)(,|$)', vp)
    A.append(ach('acessibilidade', 'falha' if bloqueia else 'ok', 'zoom', 'zoom bloqueado no celular' if bloqueia else 'zoom liberado no celular',
                 [vp] if bloqueia else [], 'tire user-scalable=no e maximum-scale do viewport', 'WCAG 1.4.4'))
    A.append(ach('acessibilidade', 'ok' if 'main' in d.marcos else 'aviso', 'main',
                 'região principal marcada (<main>)' if 'main' in d.marcos else 'sem <main>',
                 dica='envolva o conteúdo principal em <main>: leitores de tela pulam direto para ele', ref='WCAG 1.3.1'))
    # link de pular de verdade: aponta para o conteúdo, ou diz "pular"; "#sobre" no menu não conta
    primeiros = [a for a in d.ancoras[:5] if (a['href'] or '').startswith('#') and len(a['href']) > 1 and (
        re.search(r'main|conte[uú]do|content|principal|inicio-conteudo', a['href'], re.I)
        or re.search(r'pular|saltar|ir para o conte|skip', a['nome'] or '', re.I))]
    A.append(ach('acessibilidade', 'ok' if primeiros else 'info', 'pular', 'link "pular para o conteúdo"' if primeiros else 'sem link "pular para o conteúdo"',
                 dica='um link no começo que leva ao <main> poupa dezenas de Tabs', ref='WCAG 2.4.1'))
    genericos = [a for a in d.ancoras if GENERICOS.match((a['texto'] or '').strip())]
    if genericos:
        A.append(ach('acessibilidade', 'aviso', 'link-generico', pl(len(genericos), 'link') + ' com texto genérico',
                     [f'"{a["texto"]}" → {corta(a["href"] or "", 30)}' for a in genericos[:3]],
                     'fora de contexto, "clique aqui" não diz para onde vai; descreva o destino', 'WCAG 2.4.4'))
    return A


def checa_seo(d, bruto, url, robots, sitemap, renderizado):
    S = []
    t = (d.titulo or '').strip()
    S.append(ach('seo', 'falha' if not t else 'aviso' if not 10 <= len(t) <= 65 else 'ok', 'seo-titulo',
                 f'título: {len(t)} caracteres' if t else 'sem título', [corta(t, 60)] if t else [],
                 'entre 10 e 65 caracteres aparece inteiro no Google'))
    desc = d.meta('description') or ''
    S.append(ach('seo', 'falha' if not desc else 'aviso' if not 50 <= len(desc) <= 165 else 'ok', 'descricao',
                 f'descrição: {len(desc)} caracteres' if desc else 'sem meta description', [corta(desc, 60)] if desc else [],
                 'entre 50 e 165 caracteres; é o texto embaixo do link no Google'))
    robots_meta = (d.meta('robots') or '').lower()
    noindex = 'noindex' in robots_meta
    S.append(ach('seo', 'falha' if noindex else 'ok', 'noindex', 'a página pede para NÃO aparecer no Google (noindex)' if noindex
                 else 'página indexável', [robots_meta] if noindex else [], 'tire o noindex se a página deve aparecer na busca'))
    can = d.link_rel('canonical')
    S.append(ach('seo', 'ok' if can else 'aviso', 'canonical', 'URL canônica definida' if can else 'sem link canonical',
                 [can[0].get('href', '')] if can else [], '<link rel="canonical" href="…"> evita conteúdo duplicado'))
    S.append(ach('seo', 'ok' if d.meta('viewport') else 'falha', 'viewport', 'viewport para celular' if d.meta('viewport') else 'sem meta viewport',
                 dica='sem viewport o Google considera a página ruim no celular'))
    if robots is not None:
        if robots['bloqueia']:
            S.append(ach('seo', 'falha', 'robots', 'robots.txt bloqueia o site inteiro', ['User-agent: * / Disallow: /'],
                         'isso tira o site do Google; deixe só o que precisa esconder'))
        else:
            S.append(ach('seo', 'ok' if robots['existe'] else 'info', 'robots', 'robots.txt presente' if robots['existe'] else 'sem robots.txt',
                         dica='não é obrigatório, mas é onde se aponta o sitemap'))
    if sitemap is not None:
        S.append(ach('seo', 'ok' if sitemap else 'info', 'sitemap', f'sitemap com {sitemap} URLs' if sitemap else 'sem sitemap.xml',
                     dica='o sitemap ajuda o Google a achar todas as páginas'))
    # prévia em redes sociais: o WhatsApp, o LinkedIn e o Facebook leem o HTML bruto, sem rodar JavaScript
    og_falta = [k for k in ('og:title', 'og:description', 'og:image') if not bruto.meta(k)]
    og_so_js = [k for k in og_falta if d.meta(k)]
    S.append(ach('seo', 'falha' if og_so_js else 'aviso' if og_falta else 'ok', 'open-graph',
                 ('Open Graph só aparece depois do JavaScript' if og_so_js else f'falta {", ".join(og_falta)}' if og_falta
                  else 'prévia para redes sociais (Open Graph)'), [],
                 'WhatsApp, LinkedIn e Facebook não rodam JavaScript: as tags og: precisam estar no HTML que o servidor manda'))
    if renderizado and not (bruto.titulo or '').strip() and t:
        S.append(ach('seo', 'aviso', 'titulo-js', 'o título só aparece depois do JavaScript',
                     dica='coloque o <title> no index.html; robôs simples veem a página sem título'))
    S.append(ach('seo', 'ok' if d.meta('twitter:card') or bruto.meta('twitter:card') else 'info', 'twitter',
                 'cartão do X/Twitter' if d.meta('twitter:card') or bruto.meta('twitter:card') else 'sem twitter:card', dica='<meta name="twitter:card" content="summary_large_image">'))
    icone = d.link_rel('icon') or d.link_rel('shortcut') or d.link_rel('apple-touch-icon')
    S.append(ach('seo', 'ok' if icone else 'aviso', 'favicon', 'favicon definido' if icone else 'sem favicon no HTML',
                 dica='<link rel="icon" href="/favicon.svg">'))
    validos, quebrados = 0, 0
    for bloco in d.jsonld:
        try:
            json.loads(bloco)
            validos += 1
        except ValueError:
            quebrados += 1
    S.append(ach('seo', 'falha' if quebrados else 'ok' if validos else 'info', 'jsonld',
                 pl(quebrados, 'bloco') + ' JSON-LD com erro' if quebrados else pl(validos, 'bloco') + ' de dados estruturados' if validos
                 else 'sem dados estruturados (JSON-LD)', dica='dados estruturados (schema.org) geram resultados ricos no Google'))
    return S


def checa_desempenho(pag, d, recursos):
    P = []
    ttfb = pag['ttfb']
    P.append(ach('desempenho', 'falha' if ttfb > 1.8 else 'aviso' if ttfb > 0.8 else 'ok', 'ttfb',
                 f'primeiro byte em {ttfb * 1000:.0f} ms', dica='acima de 800 ms: servidor lento, sem cache ou longe de quem acessa'))
    enc = pag['cabecalhos'].get('content-encoding', '')
    tam = len(pag['corpo'])
    P.append(ach('desempenho', 'ok' if enc or tam < 2048 else 'aviso', 'compressao',
                 f'HTML comprimido ({enc})' if enc else 'HTML sem compressão', [f'{humano(tam)} de HTML'],
                 'ligue gzip ou brotli no servidor'))
    versao = pag['http']
    P.append(ach('desempenho', 'ok' if versao in ('2', '3') else 'info', 'http2', f'HTTP/{versao}' if versao else 'versão do HTTP desconhecida',
                 dica='HTTP/2 baixa vários arquivos na mesma conexão'))
    bloqueando = [s for s in d.scripts if s['_head'] and s.get('src') and 'async' not in s and 'defer' not in s
                  and (s.get('type') or '').lower() != 'module']
    P.append(ach('desempenho', 'aviso' if bloqueando else 'ok', 'scripts-bloqueantes',
                 pl(len(bloqueando), 'script') + ' travando a renderização' if bloqueando else 'nenhum script travando a renderização',
                 [corta(s['src'], 50) for s in bloqueando[:3]], 'use defer (ou type="module") nos scripts do <head>'))
    sem_dim = [i for i in d.imgs if not (i.get('width') and i.get('height')) and 'aspect-ratio' not in (i.get('style') or '')]
    P.append(ach('desempenho', 'aviso' if len(sem_dim) > 1 else 'ok', 'img-dimensoes',
                 pl(len(sem_dim), 'imagem', 'imagens') + ' sem width/height' if sem_dim else 'imagens com dimensões',
                 [corta(i.get('src', ''), 50) for i in sem_dim[:3]], 'sem dimensões a página "pula" enquanto carrega (CLS)'))
    sem_lazy = [i for i in d.imgs[3:] if (i.get('loading') or '').lower() != 'lazy']
    if len(d.imgs) > 3:
        P.append(ach('desempenho', 'aviso' if len(sem_lazy) > 2 else 'ok', 'lazy',
                     pl(len(sem_lazy), 'imagem', 'imagens') + ' abaixo da dobra sem loading="lazy"' if sem_lazy else 'imagens com carregamento preguiçoso',
                     dica='loading="lazy" adia as imagens que ainda não estão na tela'))
    pesados = sorted([r for r in recursos if r.get('tamanho')], key=lambda r: -r['tamanho'])
    grandes = [r for r in pesados if r['tamanho'] > 300 * 1024]
    if pesados:
        P.append(ach('desempenho', 'aviso' if grandes else 'ok', 'pesados',
                     pl(len(grandes), 'arquivo') + ' acima de 300 KB' if grandes else 'nenhum arquivo acima de 300 KB',
                     [f'{humano(r["tamanho"])} {corta(r["url"].split("?")[0].rsplit("/", 1)[-1] or r["url"], 40)}' for r in (grandes or pesados)[:3]],
                     'converta imagens para WebP/AVIF e divida JavaScript grande'))
    legado = [r for r in recursos if re.search(r'\.(jpe?g|png|gif)(\?|$)', r['url'], re.I) and (r.get('tamanho') or 0) > 100 * 1024]
    if legado:
        P.append(ach('desempenho', 'aviso', 'formatos', pl(len(legado), 'imagem grande', 'imagens grandes') + ' em JPG/PNG/GIF',
                     [corta(r['url'].rsplit('/', 1)[-1], 50) for r in legado[:3]], 'WebP e AVIF costumam ter metade do tamanho'))
    estaticos = [r for r in recursos if r.get('cache') is not None and re.search(r'\.(js|css|woff2?|png|jpe?g|webp|avif|svg)(\?|$)', r['url'], re.I)]
    curtos = [r for r in estaticos if r['cache'] < 86400]
    if estaticos:
        P.append(ach('desempenho', 'aviso' if len(curtos) > len(estaticos) / 2 else 'ok', 'cache',
                     f'{len(curtos)} de {len(estaticos)} arquivos com cache curto' if curtos else 'arquivos com cache longo',
                     [corta(r['url'].rsplit('/', 1)[-1], 50) for r in curtos[:3]], 'arquivos com hash no nome podem ter cache de 1 ano'))
    return P


RASTREADORES = [(r'google-analytics\.com|googletagmanager\.com|gtag/js', 'Google Analytics'), (r'connect\.facebook\.net', 'Meta Pixel'),
                (r'hotjar\.com', 'Hotjar'), (r'clarity\.ms', 'Microsoft Clarity'), (r'doubleclick\.net|googlesyndication', 'Google Ads'),
                (r'snap\.licdn\.com', 'LinkedIn Insight'), (r'analytics\.tiktok\.com', 'TikTok Pixel')]


def checa_boas_praticas(d, html_bruto, final):
    from urllib.parse import urlparse
    B = []
    host = urlparse(final).netloc
    doctype = html_bruto.lstrip().lower().startswith('<!doctype html')
    B.append(ach('boas-praticas', 'ok' if doctype else 'falha', 'doctype', '<!doctype html> presente' if doctype else 'sem <!doctype html>',
                 dica='sem doctype o navegador entra no "modo quirks" e o CSS se comporta diferente'))
    charset = re.search(r'<meta[^>]+charset', html_bruto[:2048], re.I)
    B.append(ach('boas-praticas', 'ok' if charset else 'aviso', 'charset', 'codificação declarada no começo' if charset else 'sem <meta charset> no começo do HTML',
                 dica='<meta charset="utf-8"> logo no início evita acentos quebrados'))
    externos = [(s.get('src'), s) for s in d.scripts if s.get('src', '').startswith('http') and urlparse(s['src']).netloc != host]
    externos += [(l.get('href'), l) for l in d.links if 'stylesheet' in (l.get('rel') or '') and (l.get('href') or '').startswith('http')
                 and urlparse(l['href']).netloc != host]
    sem_sri = [u for u, a in externos if not a.get('integrity') and not re.search(r'googletagmanager|google-analytics|fonts\.googleapis', u)]
    if externos:
        B.append(ach('boas-praticas', 'aviso' if sem_sri else 'ok', 'sri', pl(len(sem_sri), 'arquivo de outro site', 'arquivos de outro site') + ' sem integrity'
                     if sem_sri else 'arquivos de CDN com integrity', [corta(u, 50) for u in sem_sri[:3]],
                     'integrity="sha384-…" garante que a CDN não trocou o arquivo (Subresource Integrity)'))
    for s in d.scripts:
        m = re.search(r'jquery[.-]?(\d+)\.(\d+)', s.get('src') or '', re.I)
        if m and (int(m.group(1)), int(m.group(2))) < (3, 5):
            B.append(ach('boas-praticas', 'aviso', 'jquery', f'jQuery {m.group(1)}.{m.group(2)} tem falhas de segurança conhecidas',
                         [corta(s['src'], 50)], 'atualize para o jQuery 3.5 ou mais novo (corrige falhas de XSS)'))
            break
    if d.elementos > 1500:
        B.append(ach('boas-praticas', 'aviso', 'dom', f'{d.elementos} elementos no HTML', dica='acima de ~1.500 elementos a página fica pesada para montar e rolar'))
    rastros = sorted({nome for rx, nome in RASTREADORES for s in d.scripts + d.iframes if re.search(rx, s.get('src') or '')}
                     | {nome for rx, nome in RASTREADORES if re.search(rx, html_bruto)})
    if rastros:
        B.append(ach('boas-praticas', 'aviso', 'rastreadores', 'rastreadores: ' + ', '.join(rastros), [],
                     'pela LGPD, avise sobre os cookies e peça consentimento antes de ativar esses scripts'))
    terceiros = sorted({urlparse(u).netloc for u in [s.get('src') or '' for s in d.scripts] + [i.get('src') or '' for i in d.iframes]
                        if u.startswith('http') and urlparse(u).netloc != host})
    if len(terceiros) > 4:
        B.append(ach('boas-praticas', 'aviso', 'terceiros', f'scripts de {len(terceiros)} domínios de terceiros', terceiros[:3],
                     'cada domínio externo é mais uma conexão e mais um ponto que pode cair ou vazar dados'))
    manifesto = d.link_rel('manifest')
    B.append(ach('boas-praticas', 'ok' if manifesto else 'info', 'manifesto', 'manifesto de app (PWA)' if manifesto else 'sem manifesto de app (PWA)',
                 dica='<link rel="manifest"> deixa instalar o site como app e define ícone e cor'))
    if not d.meta('theme-color'):
        B.append(ach('boas-praticas', 'info', 'theme-color', 'sem theme-color', dica='<meta name="theme-color" content="#303446"> pinta a barra do navegador no celular'))
    return B


def checa_seguranca(pag, d, url, tls):
    G = []
    https = url.startswith('https://')
    h = pag['cabecalhos']
    G.append(ach('seguranca', 'ok' if https else 'falha', 'https', 'HTTPS' if https else 'sem HTTPS', dica='todo site público deve usar HTTPS'))
    if tls:
        dias = tls.get('dias')
        if dias is not None:
            G.append(ach('seguranca', 'falha' if dias < 7 else 'aviso' if dias < 21 else 'ok', 'certificado',
                         f'certificado vence em {dias} dias' if dias >= 0 else 'certificado VENCIDO', [tls.get('emissor', '')],
                         'renove o certificado (Vercel, Netlify e GitHub Pages renovam sozinhos)'))
    cabecalhos = [('strict-transport-security', 'HSTS', 'força HTTPS nas próximas visitas', 'aviso'),
                  ('content-security-policy', 'CSP', 'limita de onde scripts podem vir (barra XSS)', 'aviso'),
                  ('x-content-type-options', 'X-Content-Type-Options', 'impede o navegador de "adivinhar" o tipo do arquivo', 'aviso'),
                  ('referrer-policy', 'Referrer-Policy', 'controla o que vaza no cabeçalho Referer', 'info'),
                  ('permissions-policy', 'Permissions-Policy', 'desliga câmera, microfone etc. que o site não usa', 'info')]
    for chave, nome, porque, nivel in cabecalhos:
        if chave == 'strict-transport-security' and not https:
            continue
        G.append(ach('seguranca', 'ok' if chave in h else nivel, 'h-' + chave, f'{nome}' if chave in h else f'sem {nome}', dica=porque))
    csp = h.get('content-security-policy', '')
    if csp and re.search(r"'unsafe-(inline|eval)'", csp):
        G.append(ach('seguranca', 'aviso', 'csp-fraca', "CSP com 'unsafe-inline' ou 'unsafe-eval'", [corta(csp, 50)],
                     'essas palavras desligam boa parte da proteção contra XSS; prefira nonce ou hash'))
    if h.get('access-control-allow-origin', '').strip() == '*':
        G.append(ach('seguranca', 'info', 'cors', 'CORS liberado para qualquer site (*)', dica='se a página não é uma API pública, restrinja o Access-Control-Allow-Origin'))
    anti_frame = 'x-frame-options' in h or 'frame-ancestors' in csp
    G.append(ach('seguranca', 'ok' if anti_frame else 'aviso', 'frame', 'proteção contra clickjacking' if anti_frame else 'sem proteção contra clickjacking',
                 dica='X-Frame-Options: DENY (ou frame-ancestors na CSP) impede que embutam o site num iframe'))
    if https:
        misto = [x for x in ([i.get('src', '') for i in d.imgs] + [s.get('src', '') for s in d.scripts] +
                             [l.get('href', '') for l in d.links if 'stylesheet' in (l.get('rel') or '')] + [f.get('src', '') for f in d.iframes])
                 if x.startswith('http://')]
        G.append(ach('seguranca', 'falha' if misto else 'ok', 'misto', pl(len(misto), 'recurso') + ' por HTTP numa página HTTPS' if misto else 'sem conteúdo misto',
                     [corta(x, 50) for x in misto[:3]], 'o navegador bloqueia ou avisa; troque por https://'))
        ruins = [c.split('=', 1)[0] for c in pag['cookies'] if 'secure' not in c.lower() or 'httponly' not in c.lower()]
        if pag['cookies']:
            G.append(ach('seguranca', 'aviso' if ruins else 'ok', 'cookies', pl(len(ruins), 'cookie') + ' sem Secure/HttpOnly' if ruins else 'cookies protegidos',
                         ruins[:3], 'Secure manda só por HTTPS; HttpOnly esconde do JavaScript (barra roubo de sessão)'))
    servidor = h.get('server', '') + ' ' + h.get('x-powered-by', '')
    if re.search(r'\d+\.\d+', servidor):
        G.append(ach('seguranca', 'info', 'versao', 'o servidor anuncia a versão', [servidor.strip()],
                     'esconder a versão dificulta quem procura falhas conhecidas'))
    abre = [a for a in d.ancoras if (a['target'] or '') == '_blank' and 'noopener' not in a['rel'] and 'noreferrer' not in a['rel']
            and (a['href'] or '').startswith('http')]
    if abre:
        G.append(ach('seguranca', 'info', 'noopener', pl(len(abre), 'link') + ' target="_blank" sem rel="noopener"',
                     dica='navegadores novos já protegem, mas rel="noopener" cobre os antigos'))
    return G


def info_tls(host):
    import socket
    import ssl
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                cert = ss.getpeercert()
        fim = ssl.cert_time_to_seconds(cert['notAfter'])
        emissor = dict(x[0] for x in cert.get('issuer', ())).get('organizationName', '')
        return {'dias': int((fim - time.time()) // 86400), 'emissor': emissor}
    except Exception:
        # Python sem certificados raiz (comum no macOS): tenta pelo curl, que usa os do sistema
        try:
            r = subprocess.run(['curl', '-sS', '-v', '-o', os.devnull, '--max-time', '15', f'https://{host}/'],
                               capture_output=True, timeout=25)
            m = re.search(r'expire date: (.+)', r.stderr.decode('utf-8', 'replace'))
            if m:
                fim = datetime.strptime(' '.join(m.group(1).split()), '%b %d %H:%M:%S %Y %Z').timestamp()
                return {'dias': int((fim - time.time()) // 86400), 'emissor': ''}
        except Exception:
            pass
    return None


def info_robots(origem):
    r = busca(origem + '/robots.txt', tempo=12)
    if r['status'] != 200 or b'<html' in r['corpo'][:500].lower():
        return {'existe': False, 'bloqueia': False, 'sitemaps': []}, []
    txt = r['corpo'].decode('utf-8', 'replace')
    bloqueia, agente = False, None
    for l in txt.splitlines():
        l = l.split('#')[0].strip()
        if l.lower().startswith('user-agent:'):
            agente = l.split(':', 1)[1].strip()
        elif l.lower().startswith('disallow:') and agente == '*' and l.split(':', 1)[1].strip() == '/':
            bloqueia = True
    sitemaps = [l.split(':', 1)[1].strip() for l in txt.splitlines() if l.lower().startswith('sitemap:')]
    return {'existe': True, 'bloqueia': bloqueia, 'sitemaps': sitemaps}, sitemaps


def le_sitemap(origem, sitemaps):
    for alvo in (sitemaps or []) + [origem + '/sitemap.xml']:
        r = busca(alvo, tempo=15)
        if r['status'] == 200 and b'<loc>' in r['corpo']:
            locs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', r['corpo'].decode('utf-8', 'replace'))
            if b'<sitemapindex' not in r['corpo']:
                return locs
            # índice de sitemaps: as <loc> são outros sitemaps, não páginas
            paginas = []
            for sub in locs[:5]:
                rs = busca(sub, tempo=15)
                if rs['status'] == 200:
                    paginas += re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', rs['corpo'].decode('utf-8', 'replace'))
            return paginas
    return []


def link_quebrado(l):
    # 401/403/429 e o 999 do LinkedIn são o site recusando robôs, não link quebrado
    return bool(l['erro']) or (l['status'] >= 400 and l['status'] not in (401, 403, 405, 429, 999))


def checa_recursos(urls, limite=60):
    # HEAD em cada link e arquivo da página: quebrados, tamanho e cache, em paralelo
    alvos = list(dict.fromkeys(urls))[:limite]

    def um(u):
        r = busca(u, metodo='HEAD', tempo=12, corpo=False)
        if r['status'] in (403, 405, 501) or (r['status'] == 0 and not r['erro']):
            r = busca(u, tempo=15)
            if r['corpo']:
                r['cabecalhos'].setdefault('content-length', str(len(r['corpo'])))
        cc = r['cabecalhos'].get('cache-control', '')
        m = re.search(r'max-age=(\d+)', cc)
        cache = int(m.group(1)) if m else (0 if 'no-cache' in cc or 'no-store' in cc else None)
        tam = r['cabecalhos'].get('content-length', '')
        return {'url': u, 'status': r['status'], 'erro': r['erro'], 'tamanho': int(tam) if tam.isdigit() else None, 'cache': cache}

    with ThreadPoolExecutor(10) as ex:
        return list(ex.map(um, alvos))


def absoluto(base, href):
    from urllib.parse import urljoin
    if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
        return None
    u = urljoin(base, href.strip())
    return u.split('#')[0] if u.startswith(('http://', 'https://')) else None


def detecta_stack(html, cab):
    tec = []
    sinais = [(r'/@vite/client|type="module"[^>]+src="/assets/index-[\w-]+\.js', 'Vite'), (r'__NEXT_DATA__|/_next/static', 'Next.js'),
              (r'__nuxt|/_nuxt/', 'Nuxt'), (r'ng-version=', 'Angular'), (r'data-reactroot|react-dom|id="root"', 'React'),
              (r'data-v-[0-9a-f]{8}|id="app"', 'Vue'), (r'svelte-[a-z0-9]{6}', 'Svelte'), (r'astro-island|data-astro', 'Astro'),
              (r'wp-content|wp-includes', 'WordPress'), (r'cdn\.tailwindcss|class="[^"]*\b(flex|grid) [^"]*\b(px|py|mt|mb)-\d', 'Tailwind'),
              (r'bootstrap(\.min)?\.(css|js)', 'Bootstrap')]
    for rx, nome in sinais:
        if re.search(rx, html, re.I) and nome not in tec:
            tec.append(nome)
    if 'Next.js' in tec and 'React' not in tec:
        tec.append('React')
    servidor = (cab.get('server', '') + ' ' + cab.get('x-powered-by', '')).lower()
    host = None
    if 'x-vercel-id' in cab or 'vercel' in servidor:
        host = 'Vercel'
    elif 'x-nf-request-id' in cab or 'netlify' in servidor:
        host = 'Netlify'
    elif 'github.com' in servidor or 'x-github-request-id' in cab:
        host = 'GitHub Pages'
    elif 'cf-ray' in cab or 'cloudflare' in servidor:
        host = 'Cloudflare'
    elif 'x-render-origin-server' in cab or 'render' in servidor:
        host = 'Render'
    return tec, host


def nota_de(achados):
    validos = [a for a in achados if a['nivel'] in PESO_NIVEL]
    if not validos:
        return None
    return round(100 * sum(PESO_NIVEL[a['nivel']] for a in validos) / (3 * len(validos)))


def analisa_pagina(t, url, args, nav, pr=None, completo=True):
    from urllib.parse import urlparse
    pag = busca(url)
    if pag['erro'] or not pag['status']:
        return {'url': url, 'erro': pag['erro'] or 'sem resposta'}
    final = pag['url_final']
    u = urlparse(final)
    origem = f'{u.scheme}://{u.netloc}'
    local = u.hostname in ('localhost', '127.0.0.1', '::1') or (u.hostname or '').endswith('.local')
    html_bruto = pag['corpo'].decode('utf-8', 'replace')
    bruto = LeitorHTML(html_bruto)
    modulos = any((s.get('type') or '').lower() == 'module' for s in bruto.scripts)
    raiz_vazia = re.search(r'<div[^>]+id=["\'](root|app|__next|__nuxt|svelte)["\'][^>]*>\s*</div>', html_bruto, re.I)
    spa = bool(raiz_vazia) or (len(bruto.texto) < 40 and modulos and not bruto.titulos)
    d, renderizado, dom = bruto, False, ''
    if spa and nav:
        if pr:
            pr.atual = 'renderizando com o navegador (site com JavaScript)'
        dom = dom_renderizado(nav, final)
        if dom:
            d, renderizado = LeitorHTML(dom), True
    achados = checa_acessibilidade(d)
    recursos_urls = ([absoluto(final, i.get('src')) for i in d.imgs] + [absoluto(final, s.get('src')) for s in d.scripts]
                     + [absoluto(final, l.get('href')) for l in d.links if (l.get('rel') or '').lower() in ('stylesheet', 'preload', 'icon')])
    links_urls = [absoluto(final, a['href']) for a in d.ancoras]
    robots = sitemap = None
    urls_sitemap = []
    if completo:
        if pr:
            pr.atual = 'robots.txt e sitemap'
        robots, sms = info_robots(origem)
        urls_sitemap = le_sitemap(origem, sms)
        sitemap = len(urls_sitemap)
    achados += checa_seo(d, bruto, final, robots, sitemap, renderizado)
    achados += checa_boas_praticas(d, html_bruto, final)
    recursos, links = [], []
    if completo:
        if pr:
            pr.atual = 'conferindo arquivos e links da página'
        verif = checa_recursos([x for x in recursos_urls + links_urls if x])
        por_url = {v['url']: v for v in verif}
        recursos = [por_url[x] for x in dict.fromkeys(recursos_urls) if x in por_url]
        links = [por_url[x] for x in dict.fromkeys(links_urls) if x in por_url]
    achados += checa_desempenho(pag, d, recursos)
    if not local:
        tls = info_tls(u.hostname) if final.startswith('https://') and completo else None
        achados += checa_seguranca(pag, d, final, tls)
        if completo:
            st = busca(origem + '/.well-known/security.txt', tempo=10, corpo=False)
            achados.append(ach('seguranca', 'ok' if st['status'] == 200 else 'info', 'security-txt',
                               'security.txt presente' if st['status'] == 200 else 'sem /.well-known/security.txt',
                               dica='diz para quem achar uma falha como avisar você (padrão RFC 9116)'))
        # quem chega por http:// precisa ser mandado para https://
        if completo and final.startswith('https://'):
            r = busca('http://' + u.netloc + (u.path or '/'), tempo=12, corpo=False)
            vai = r['url_final'].startswith('https://')
            achados.append(ach('seguranca', 'ok' if vai else 'falha', 'redireciona-https',
                               'http:// redireciona para https://' if vai else 'http:// não redireciona para https://',
                               dica='quem digita o endereço sem https fica na versão insegura'))
    if completo:
        quebrados = [l for l in links + recursos if link_quebrado(l)]
        achados.append(ach('links', 'falha' if quebrados else 'ok', 'quebrados',
                           pl(len(quebrados), 'link ou arquivo quebrado', 'links ou arquivos quebrados') if quebrados else f'{len(links) + len(recursos)} links e arquivos funcionando',
                           [f'{l["status"] or l["erro"]} {corta(l["url"], 46)}' for l in quebrados[:4]], 'corrija ou remova os links que levam a erro'))
        redir = len(pag['cadeia']) - 1
        if redir > 1:
            achados.append(ach('links', 'aviso', 'cadeia', f'{redir} redirecionamentos até a página',
                               [f'{s} → {corta(loc, 40)}' for s, loc in pag['cadeia'][:-1]], 'cada redirecionamento custa uma ida e volta ao servidor'))
    internos = [x for x in dict.fromkeys(links_urls + urls_sitemap) if x and urlparse(x).netloc == u.netloc
                and x.rstrip('/') != final.rstrip('/') and not re.search(r'\.(pdf|zip|png|jpe?g|svg|xml)(\?|$)', x, re.I)]
    tec, hospedagem = detecta_stack(html_bruto + (dom if renderizado else ''), pag['cabecalhos'])
    return {'url': url, 'final': final, 'status': pag['status'], 'ttfb': pag['ttfb'], 'total': pag['total'], 'http': pag['http'],
            'compressao': pag['cabecalhos'].get('content-encoding', ''), 'html': len(pag['corpo']), 'spa': spa,
            'renderizado': renderizado, 'local': local, 'achados': achados, 'internos': internos, 'tec': tec,
            'hospedagem': hospedagem, 'bytes': len(pag['corpo']) + sum(r.get('tamanho') or 0 for r in recursos)}


def le_lighthouse(dados):
    cats = {}
    for cid, c in dados.get('categories', {}).items():
        if c.get('score') is not None:
            cats[{'performance': 'desempenho', 'accessibility': 'acessibilidade', 'best-practices': 'boas-praticas', 'seo': 'seo'}.get(cid, cid)] = round(c['score'] * 100)
    audits = dados.get('audits', {})
    limites = {'first-contentful-paint': ('FCP', 1800, 3000), 'largest-contentful-paint': ('LCP', 2500, 4000),
               'total-blocking-time': ('TBT', 200, 600), 'cumulative-layout-shift': ('CLS', 0.1, 0.25), 'speed-index': ('SI', 3400, 5800)}
    metricas = []
    for chave, (sigla, bom, medio) in limites.items():
        a = audits.get(chave)
        if a and a.get('numericValue') is not None:
            v = a['numericValue']
            metricas.append({'sigla': sigla, 'titulo': a.get('title', sigla), 'valor': a.get('displayValue', ''),
                             'nivel': 'ok' if v <= bom else 'aviso' if v <= medio else 'falha'})
    oportunidades = []
    for a in audits.values():
        det = a.get('details') or {}
        if det.get('type') == 'opportunity' and (a.get('score') or 0) < 0.9 and (det.get('overallSavingsMs') or 0) > 50:
            oportunidades.append({'titulo': a.get('title', ''), 'ganho': det.get('overallSavingsMs', 0), 'valor': a.get('displayValue', '')})
    oportunidades.sort(key=lambda o: -o['ganho'])
    falhas = {}
    mapa = {'performance': 'desempenho', 'accessibility': 'acessibilidade', 'best-practices': 'boas-praticas', 'seo': 'seo'}
    for cid, c in dados.get('categories', {}).items():
        for ref in c.get('auditRefs', []):
            a = audits.get(ref.get('id'), {})
            if ref.get('weight', 0) > 0 and a.get('score') is not None and a['score'] < 0.9 and \
                    a.get('scoreDisplayMode') not in ('notApplicable', 'informative', 'manual') and cid != 'performance':
                itens = len(((a.get('details') or {}).get('items')) or [])
                falhas.setdefault(mapa.get(cid, cid), []).append({'titulo': a.get('title', ''), 'itens': itens})
    peso = (audits.get('total-byte-weight') or {}).get('numericValue')
    return {'notas': cats, 'metricas': metricas, 'oportunidades': oportunidades[:5], 'falhas': falhas, 'bytes': peso}


IDS_HEAD = {'lang', 'titulo', 'seo-titulo', 'descricao', 'canonical', 'viewport', 'open-graph', 'twitter', 'favicon', 'titulo-js',
            'jsonld', 'charset', 'doctype', 'manifesto', 'theme-color', 'zoom', 'noindex', 'scripts-bloqueantes'}
IDS_SERVIDOR = {'h-strict-transport-security', 'h-content-security-policy', 'h-x-content-type-options', 'h-referrer-policy',
                'h-permissions-policy', 'frame', 'csp-fraca', 'cors', 'compressao', 'http2', 'cache', 'versao', 'redireciona-https',
                'ttfb', 'cookies'}


def onde_mexer(a, res):
    tec, host = res.get('tec') or [], res.get('hospedagem')
    if a['id'] == 'doctype':
        return 'na primeira linha de cada HTML (index.html ou o template base)'
    if a['id'] == 'lang' and 'Next.js' not in tec:
        return 'na tag `<html>` do index.html (ou do layout/template base)'
    if a['id'] in IDS_HEAD:
        if 'Next.js' in tec:
            return 'no `export const metadata` (app/layout.tsx ou app/page.tsx), ou no next/head nas páginas antigas'
        if res.get('spa'):
            return 'no `index.html` da raiz do projeto: tem que estar no HTML estático, não ser injetado pelo JavaScript'
        return 'no `<head>` do HTML (index.html ou o layout/template comum das páginas)'
    if a['id'] in IDS_SERVIDOR:
        if host == 'Vercel':
            return 'no `vercel.json`, na chave `"headers"` (ou redirects/rewrites)'
        if host == 'Netlify':
            return 'no arquivo `_headers` (pasta pública) ou no `netlify.toml`'
        if host == 'GitHub Pages':
            return 'o GitHub Pages não deixa configurar cabeçalhos: só resolve com Cloudflare na frente ou mudando para Vercel/Netlify (não é correção de código)'
        return 'na configuração do servidor ou da hospedagem (cabeçalhos HTTP)'
    if a['id'] in ('robots', 'sitemap', 'security-txt'):
        return 'na pasta pública do projeto (`public/` em Vite/Next, ou a raiz do site)'
    if a['id'] == 'quebrados':
        return 'procure os endereços citados no código (busca no projeto pelo trecho do link)'
    if a['cat'] in ('acessibilidade', 'desempenho', 'boas-praticas'):
        return 'nos componentes/templates que renderizam os trechos citados (busque pelo src, class, name ou texto)'
    return 'procure pelos trechos citados no código do projeto'


def md(txt):
    # trecho de HTML no meio do texto vira código, senão o Markdown o trata como tag e ele some
    return re.sub(r'(<[^<>]+>)', r'`\1`', txt)


def gera_resumo_ia(res, notas, lh, extras, fontes):
    prio = {'falha': 'ALTA', 'aviso': 'MÉDIA', 'info': 'BAIXA (opcional)'}
    rotulos = dict(CATEGORIAS)
    L = [f'# Raio-x de {res["final"]}: correções', '',
         f'> Gerado pelo ferramentas em {datetime.now():%d/%m/%Y %H:%M}. Notas: '
         + ' · '.join(f'{rotulos[c]} {notas[c]}' for c, _ in CATEGORIAS if notas.get(c) is not None), '',
         '## Contexto', '', f'- Endereço analisado: {res["final"]}']
    if res.get('tec') or res.get('hospedagem'):
        L.append(f'- Tecnologia detectada: {", ".join(res.get("tec") or ["não identificada"])}'
                 + (f' · hospedagem: {res["hospedagem"]}' if res.get('hospedagem') else ''))
    if res.get('spa'):
        L.append('- O servidor manda um HTML quase vazio e o conteúdo é montado pelo JavaScript (SPA). '
                 'Título, descrição e tags og: precisam estar no `index.html`, senão robôs e redes sociais não veem.')
    L += ['', '## O que fazer', '',
          'Você está no código deste site. Corrija os problemas abaixo, na ordem (do mais grave para o menos grave):', '',
          '1. Para cada item, encontre no código os trechos citados em "Encontrado", aplique a correção e passe ao próximo.',
          '2. Não mude o visual nem o comportamento além do necessário para cada correção.',
          '3. Itens de prioridade BAIXA são opcionais: faça só se forem simples.',
          '4. Se um item depender de configuração fora do código (hospedagem, DNS), não invente: liste-o no fim como pendente.',
          '5. No final, resuma o que mudou, arquivo por arquivo.', '', '## Problemas', '']
    ordem = sorted([a for a in res['achados'] if a['nivel'] in prio and not (a['id'] == 'carbono' and a['nivel'] == 'info')], key=lambda a: (['falha', 'aviso', 'info'].index(a['nivel']),
                                                                                    [c for c, _ in CATEGORIAS].index(a['cat'])))
    if not ordem:
        L.append('Nenhum problema encontrado pela análise própria.')
    for i, a in enumerate(ordem, 1):
        L.append(f'### {i}. [{prio[a["nivel"]]}] {rotulos[a["cat"]]}: {md(a["titulo"])}' + (f' ({a["ref"]})' if a['ref'] else ''))
        if a['exemplos']:
            L.append('- **Encontrado:** ' + '; '.join(f'`{x}`' for x in a['exemplos']))
        L.append(f'- **Onde mexer:** {onde_mexer(a, res)}')
        if a['dica']:
            L.append(f'- **Correção:** {md(a["dica"])}')
        L.append('')
    if lh:
        L += ['## Lighthouse', '']
        if lh['oportunidades']:
            L.append('**O que mais acelera a página:**')
            L += [f'- {o["titulo"]} (economia estimada: {o["ganho"] / 1000:.1f} s)'.replace('.', ',') for o in lh['oportunidades']]
            L.append('')
        for cid, falhas in lh['falhas'].items():
            if falhas:
                L.append(f'**{rotulos.get(cid, cid)}, falhas apontadas pelo Lighthouse:**')
                L += [f'- {f["titulo"]}' + (f' ({pl(f["itens"], "elemento")})' if f['itens'] else '') for f in falhas]
                L.append('')
        ruins = [m for m in lh['metricas'] if m['nivel'] != 'ok']
        if ruins:
            L.append('**Core Web Vitals fora do ideal:** ' + ', '.join(f'{m["sigla"]} {m["valor"]}' for m in ruins))
            L.append('')
    paginas = [e for e in extras if not e.get('erro') and e.get('status', 200) < 400 and any(a['nivel'] == 'falha' for a in e['achados'])]
    fora = [e for e in extras if e.get('erro') or e.get('status', 200) >= 400]
    if fora:
        L += ['## Páginas internas com erro', ''] + [f'- {e.get("final") or e["url"]}: {e.get("erro") or "HTTP " + str(e["status"])}' for e in fora] + ['']
    if paginas:
        L += ['## Outras páginas com falhas', '']
        for e in paginas:
            L.append(f'- {e["final"]}: ' + '; '.join(a['titulo'] for a in e['achados'] if a['nivel'] == 'falha'))
        L.append('')
    L += ['## Como conferir', '', f'- [ ] Rodar de novo: `python ferramentas.py raiox {res["final"]}`',
          '- [ ] Nenhum item de prioridade ALTA restante', '- [ ] As notas não caíram em nenhuma categoria', '']
    return '\n'.join(L)


def copia_area_transferencia(texto):
    if os.name == 'nt':
        cmds = [(['clip'], texto.encode('utf-16le') if texto.startswith('\ufeff') else ('\ufeff' + texto).encode('utf-16le'))]
    elif sys.platform == 'darwin':
        cmds = [(['pbcopy'], texto.encode('utf-8'))]
    else:
        cmds = [(['wl-copy'], texto.encode()), (['xclip', '-selection', 'clipboard'], texto.encode()), (['xsel', '-b', '-i'], texto.encode())]
    for cmd, dados in cmds:
        if shutil.which(cmd[0]):
            try:
                if subprocess.run(cmd, input=dados, timeout=10).returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
    return False


def barra_nota(t, nota, larg):
    cor = 'verde' if nota >= 90 else 'amarelo' if nota >= 50 else 'vermelho'
    cheio = round(larg * nota / 100)
    vazio = '■' if t.cor else ('-' if t.nivel == 'ascii' else '·')
    return t.p(('#' if t.nivel == 'ascii' else '■') * cheio, cor) + t.p(vazio * (larg - cheio), 'fundo')


def _arquivo_historico(url):
    import hashlib
    chave = re.sub(r'^https?://', '', url.rstrip('/').lower())
    return CASA / 'raiox' / (hashlib.sha1(chave.encode()).hexdigest()[:16] + '.json')


def entrega_resumo_ia(t, args, resumo, nome):
    pasta = CASA / 'relatorios'
    pasta.mkdir(parents=True, exist_ok=True)
    arq_ia = pasta / f'{nome}-ia-{datetime.now():%Y-%m-%d_%H%M%S}.md'
    arq_ia.write_text(resumo, encoding='utf-8')
    t.escreve()
    t.titulo('resumo para a IA corrigir')
    t.relatorio(arq_ia, 'arquivo')
    copiar = args.copiar
    if not copiar and t.interativo and not args.sim:
        copiar = t.pergunta('copiar para a área de transferência? s = sim').strip().lower() in ('s', 'sim')
    if copiar:
        if copia_area_transferencia(resumo):
            t.ok('copiado: cole no Claude Code (ou outra IA) aberto na pasta do projeto.')
        else:
            t.aviso('não achei como copiar neste sistema; abra o arquivo acima.')
    else:
        t.paragrafo('No Claude Code aberto na pasta do projeto, peça: "leia esse arquivo e corrija os problemas".', 4, 'apagado')


def ferramenta_raiox(t, args):
    args.desktop = args.desktop or config('dispositivo') == 'computador'
    from urllib.parse import urlparse
    url = args.url.strip()
    if not re.match(r'https?://', url):
        url = ('http://' if re.match(r'(localhost|127\.0\.0\.1)', url) else 'https://') + url
    nav = acha_navegador()
    t.prompt('raiox', url, alvo=url)
    with Progresso(t, None, 'analisando') as pr:
        pr.atual = 'baixando a página'
        res = analisa_pagina(t, url, args, nav, pr)
        lh, lh_erro = None, None
        if not res.get('erro') and not args.rapido:
            pr.atual = 'rodando o Lighthouse (pode levar 1 minuto)'
            dados, lh_erro = roda_lighthouse(res['final'], nav, args.desktop)
            lh = le_lighthouse(dados) if dados else None
        extras = []
        if not res.get('erro') and args.paginas:
            for u in res['internos'][:args.paginas]:
                pr.atual = caminho_curto(u)
                extras.append(analisa_pagina(t, u, args, nav, completo=False))
    if res.get('erro'):
        t.erro(f'Não consegui abrir {url}: {res["erro"]}.')
        return 1

    achados = res['achados']
    peso = (lh or {}).get('bytes') or res['bytes']
    if peso:
        # modelo Sustainable Web Design (v3): 0,81 kWh por GB transferido, 442 g de CO2 por kWh (média mundial)
        co2 = peso / 1024 ** 3 * 0.81 * 442
        achados.append(ach('desempenho', 'info' if co2 < 0.8 else 'aviso', 'carbono',
                           (f'~{co2:.2f} g' if co2 >= 0.01 else 'menos de 0,01 g').replace('.', ',') + f' de CO₂ por visita ({humano(peso)})',
                           dica='estimativa pelo peso transferido (modelo Sustainable Web Design); a mediana da web é ~0,8 g'))
    estaticas = {cid: nota_de([a for a in achados if a['cat'] == cid]) for cid, _ in CATEGORIAS}
    notas, fontes = dict(estaticas), {c: 'propria' for c in estaticas}
    if lh:
        notas.update(lh['notas'])
        fontes.update({c: 'lighthouse' for c in lh['notas']})
    linha = [t.p(str(res['status']), 'verde' if res['status'] < 400 else 'vermelho'), t.p(f'{res["total"]:.1f} s'.replace('.', ','), 'texto'),
             t.p(f'HTTP/{res["http"]}', 'sub')]
    if res['compressao']:
        linha.append(t.p(res['compressao'], 'sub'))
    linha.append(t.p(f'{humano(res["html"])} de HTML', 'sub'))
    if res.get('tec') or res.get('hospedagem'):
        linha.append(t.p(' + '.join(res.get('tec') or []) + (f' na {res["hospedagem"]}' if res.get('hospedagem') else ''), 'roxo'))
    if res['spa']:
        linha.append(t.p('SPA' + (' (renderizada)' if res['renderizado'] else ''), 'roxo'))
    if res['final'].rstrip('/') != url.rstrip('/'):
        t.nota(f'  → {corta(res["final"], t.largura - 6)}', 2)
    t.partes(linha)
    if res['spa'] and not res['renderizado']:
        t.paragrafo('O HTML vem quase vazio (React/Vite?) e não achei Chrome, Edge ou Brave para renderizar: '
                    'a análise de acessibilidade e SEO vê só a casca.', 4, 'amarelo')

    # notas, com a comparação com a última vez
    hist_arq = _arquivo_historico(res['final'])
    anterior = None
    try:
        anterior = json.loads(hist_arq.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    t.escreve()
    t.titulo('notas' + (' (Lighthouse + análise própria)' if lh else ' (análise própria)'))
    larg = max(6, min(20, t.largura - 34))
    for cid, rotulo in CATEGORIAS:
        n = notas.get(cid)
        if n is None:
            continue
        cor = 'verde' if n >= 90 else 'amarelo' if n >= 50 else 'vermelho'
        delta = ''
        if anterior and cid in anterior.get('notas', {}) and anterior.get('fontes', {}).get(cid) == fontes.get(cid):
            dif = n - anterior['notas'][cid]
            if dif:
                delta = t.p(f' {"↑" if dif > 0 else "↓"}{abs(dif)}', 'verde' if dif > 0 else 'vermelho')
        fonte = '' if (lh and cid in lh['notas']) or not lh else t.p(' ·', 'apagado')
        t.escreve(f'    {t.p(f"{rotulo:<15}", "texto")}{barra_nota(t, n, larg)} {t.p(f"{n:>3}", cor, True)}{delta}{fonte}')
    if lh and any(fontes.get(c) == 'propria' and notas.get(c) is not None for c, _ in CATEGORIAS):
        t.paragrafo('· = nota só da análise própria (o Lighthouse não avalia)', 4, 'apagado')
    if lh_erro and not args.rapido:
        t.paragrafo(f'Lighthouse: {lh_erro}', 4, 'apagado')
    if anterior:
        quando = ha_quanto_iso(anterior.get('quando'))
        antes = set(anterior.get('problemas', []))
        agora = {a['id'] for a in achados if a['nivel'] in ('falha', 'aviso')}
        resolvidos, novos = antes - agora, agora - antes
        t.paragrafo(f'desde a última vez ({quando}): {pl(len(resolvidos), "problema resolvido", "problemas resolvidos")}, '
                    f'{pl(len(novos), "novo")}', 4, 'apagado')

    if lh and lh['metricas']:
        t.escreve()
        t.titulo('Core Web Vitals (celular)' if not args.desktop else 'Core Web Vitals (computador)')
        estilo = {'ok': ('●', 'verde'), 'aviso': ('●', 'amarelo'), 'falha': ('●', 'vermelho')}
        for m in lh['metricas']:
            ic, cor = estilo[m['nivel']]
            t.item(ic, cor, f'{m["sigla"]:<4} {m["titulo"]}', t.p(m['valor'], cor), recuo=4)
        if lh['oportunidades']:
            t.escreve()
            t.titulo('o que mais acelera')
            for o in lh['oportunidades']:
                t.item('↳', 'azul', o['titulo'], t.p(f'-{o["ganho"] / 1000:.1f} s'.replace('.', ','), 'verde'), recuo=4)

    # problemas por categoria
    estilo = {'falha': ('✗', 'vermelho'), 'aviso': ('!', 'amarelo'), 'info': ('·', 'azul'), 'ok': ('✓', 'verde')}
    rel = Relatorio('raiox')
    rel.add(f'URL: {res["final"]}', f'status {res["status"]} · {res["total"]:.2f} s · HTTP/{res["http"]}', '')
    rel.add('Notas: ' + ', '.join(f'{r} {notas[c]}' for c, r in CATEGORIAS if notas.get(c) is not None), '')
    for cid, rotulo in CATEGORIAS:
        da_cat = [a for a in achados if a['cat'] == cid]
        lh_falhas = (lh or {}).get('falhas', {}).get(cid, []) if lh else []
        if not da_cat and not lh_falhas:
            continue
        problemas = [a for a in da_cat if a['nivel'] in ('falha', 'aviso', 'info')]
        ordem = sorted(problemas, key=lambda a: ['falha', 'aviso', 'info'].index(a['nivel']))
        oks = [a for a in da_cat if a['nivel'] == 'ok']
        n_prob = sum(1 for a in problemas if a['nivel'] != 'info') or len(lh_falhas)
        t.escreve()
        t.titulo(f'{rotulo} · ' + (f'{n_prob} problema{"s" if n_prob != 1 else ""}' if n_prob else 'tudo certo'))
        for a in ordem:
            if a['nivel'] == 'info' and not args.tudo:
                continue
            ic, cor = estilo[a['nivel']]
            t.escreve('    ' + t.p(ic, cor, True) + ' ' + t.p(corta(a['titulo'], t.largura - 7), 'texto'))
            for ex in a['exemplos'][:3]:
                t.nota(corta(ex, t.largura - 9), 8)
            if a['dica'] and a['nivel'] != 'ok':
                for l in textwrap.wrap(a['dica'] + (f' ({a["ref"]})' if a['ref'] else ''), t.largura - 8):
                    t.escreve(' ' * 6 + t.p(l, 'apagado'))
        for f in lh_falhas[:6]:
            t.escreve('    ' + t.p('✗', 'vermelho', True) + ' ' + t.p(corta(f['titulo'], t.largura - 16), 'texto')
                      + (t.p(f' ({f["itens"]})', 'apagado') if f['itens'] else ''))
        infos = sum(1 for a in problemas if a['nivel'] == 'info')
        resto = []
        if oks:
            resto.append(f'{len(oks)} ok')
        if infos and not args.tudo:
            resto.append(f'{infos} sugest{"ões" if infos > 1 else "ão"}')
        if resto and not args.tudo:
            t.paragrafo(' · '.join(resto) + ' (veja tudo com --tudo)', 4, 'apagado')
        if args.tudo:
            for a in oks:
                t.escreve('    ' + t.p('✓', 'verde') + ' ' + t.p(corta(a['titulo'], t.largura - 7), 'sub'))
        for a in da_cat:
            rel.add(f'[{a["nivel"].upper()}] {rotulo}: {a["titulo"]}' + (f' — {"; ".join(a["exemplos"])}' if a['exemplos'] else '')
                    + (f' — {a["dica"]}' if a['dica'] and a['nivel'] != 'ok' else '') + (f' ({a["ref"]})' if a['ref'] else ''))
        for f in lh_falhas:
            rel.add(f'[LIGHTHOUSE] {rotulo}: {f["titulo"]}' + (f' ({f["itens"]} elementos)' if f['itens'] else ''))

    if extras:
        t.escreve()
        t.titulo(f'outras {pl(len(extras), "página")} (análise rápida)')
        for e in extras:
            caminho = urlparse(e.get('final') or e['url']).path or '/'
            if e.get('erro') or e.get('status', 200) >= 400:
                t.item('✗', 'vermelho', caminho, t.p(e.get('erro') or f'HTTP {e["status"]}', 'vermelho'), recuo=4)
                rel.add('', f'Página {e.get("final") or e["url"]}: {e.get("erro") or "HTTP " + str(e["status"])}')
                continue
            a11y = nota_de([a for a in e['achados'] if a['cat'] == 'acessibilidade'])
            seo = nota_de([a for a in e['achados'] if a['cat'] == 'seo'])
            prob = sum(1 for a in e['achados'] if a['nivel'] == 'falha')
            cor = 'verde' if prob == 0 else 'amarelo' if prob < 3 else 'vermelho'
            t.item('●', cor, caminho, t.p(f'a11y {a11y} · SEO {seo} · {prob} falha{"s" if prob != 1 else ""}', 'sub'), recuo=4)
            rel.add('', f'Página {e["final"]}: acessibilidade {a11y}, SEO {seo}')
            for a in e['achados']:
                if a['nivel'] in ('falha', 'aviso'):
                    rel.add(f'  [{a["nivel"].upper()}] {a["titulo"]}' + (f' — {"; ".join(a["exemplos"])}' if a['exemplos'] else ''))

    if lh is None and not args.rapido and lh_erro:
        t.escreve()
        t.paragrafo('Com Node e Chrome (ou Edge) instalados, o raio-x também roda o Lighthouse: notas oficiais, '
                    'Core Web Vitals e o teste de contraste de cores.', 4, 'apagado')
    CASA.joinpath('raiox').mkdir(parents=True, exist_ok=True)
    hist_arq.write_text(json.dumps({'url': res['final'], 'quando': datetime.now(timezone.utc).isoformat(),
                                    'notas': {k: v for k, v in notas.items() if v is not None}, 'fontes': fontes,
                                    'problemas': sorted({a['id'] for a in achados if a['nivel'] in ('falha', 'aviso')})}),
                        encoding='utf-8')
    if args.json:
        Path(args.json).write_text(json.dumps({'url': res['final'], 'notas': notas, 'achados': achados, 'lighthouse': lh,
                                               'paginas': extras}, ensure_ascii=False, indent=2), encoding='utf-8')
        t.nota(f'    JSON: {caminho_curto(args.json, t.largura - 12)}', 0)
    t.escreve()
    t.relatorio(rel.salva())
    entrega_resumo_ia(t, args, gera_resumo_ia(res, notas, lh, extras, fontes), 'raiox')
    return 0


# ═══════════════════════════════ 10. peso ═══════════════════════════════

TIPOS_PESO = [('script', 'JavaScript', 'amarelo'), ('stylesheet', 'CSS', 'azul'), ('image', 'imagens', 'verde'),
              ('font', 'fontes', 'roxo'), ('document', 'HTML', 'pessego'), ('media', 'vídeo e áudio', 'vermelho'),
              ('other', 'outros', 'sub')]
# metas para o celular, em KB transferidos: até o primeiro número é bom, até o segundo é aceitável
ORCAMENTO = {'total': (1600, 3000), 'script': (350, 700), 'stylesheet': (100, 200), 'image': (900, 2000),
             'font': (150, 300), 'document': (60, 150), 'media': (1000, 4000)}
ORCAMENTO_REQ = (50, 100)
MEDIANA_WEB = 2.3 * 1024 ** 2  # HTTP Archive (Web Almanac 2024): mediana das páginas no celular
TIPO_LH = {'Document': 'document', 'Script': 'script', 'Stylesheet': 'stylesheet', 'Image': 'image', 'Font': 'font',
           'Media': 'media'}
TERCEIROS = [(r'fonts\.(googleapis|gstatic)\.com', 'Google Fonts'), (r'maps\.(google|googleapis)\.com', 'Google Maps'),
             (r'googletagmanager\.com|google-analytics\.com', 'Google Analytics'), (r'recaptcha', 'reCAPTCHA'),
             (r'doubleclick\.net|googlesyndication\.com|adservice\.google', 'Google Ads'),
             (r'youtube(-nocookie)?\.com|ytimg\.com', 'YouTube'), (r'facebook\.(net|com)|fbcdn\.net', 'Meta'),
             (r'cdnjs\.cloudflare\.com', 'cdnjs'), (r'jsdelivr\.net', 'jsDelivr'), (r'unpkg\.com', 'unpkg'),
             (r'fontawesome', 'Font Awesome'), (r'hotjar', 'Hotjar'), (r'clarity\.ms', 'Microsoft Clarity'),
             (r'vercel-insights|vitals\.vercel|vercel\.live', 'Vercel Analytics'), (r'cloudflareinsights', 'Cloudflare Analytics'),
             (r'code\.jquery\.com', 'jQuery (CDN)'), (r'tailwindcss\.com', 'Tailwind (CDN)'), (r'tiktok', 'TikTok'),
             (r'linkedin|licdn', 'LinkedIn'), (r'gstatic\.com|googleapis\.com', 'Google')]
# o que o Lighthouse mede em bytes que dá para economizar
LH_ECONOMIAS = ['unused-javascript', 'unused-css-rules', 'modern-image-formats', 'uses-optimized-images',
                'uses-responsive-images', 'offscreen-images', 'uses-text-compression', 'unminified-javascript',
                'unminified-css', 'efficient-animated-content', 'duplicated-javascript', 'legacy-javascript']


def dominio_base(host):
    partes = (host or '').lower().split('.')
    # kessleru.com.br e kessleru.github.io contam como o mesmo site em qualquer subdomínio
    if len(partes) >= 3 and (partes[-2] in ('com', 'net', 'org', 'gov', 'edu', 'co') and len(partes[-1]) == 2
                             or '.'.join(partes[-2:]) in ('github.io', 'vercel.app', 'netlify.app', 'pages.dev')):
        return '.'.join(partes[-3:])
    return '.'.join(partes[-2:])


def nome_terceiro(host):
    return next((n for rx, n in TERCEIROS if re.search(rx, host or '', re.I)), host)


def tipo_do_arquivo(url, content_type=''):
    ct = (content_type or '').split(';')[0].strip().lower()
    caminho = urlparse(url).path.lower()
    ext = caminho.rsplit('.', 1)[-1] if '.' in caminho.rsplit('/', 1)[-1] else ''
    if 'javascript' in ct or ext in ('js', 'mjs', 'cjs'):
        return 'script'
    if 'css' in ct or ext == 'css':
        return 'stylesheet'
    if ct.startswith('image/') or ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'svg', 'ico', 'bmp'):
        return 'image'
    if 'font' in ct or ext in ('woff', 'woff2', 'ttf', 'otf', 'eot'):
        return 'font'
    if ct.startswith(('video/', 'audio/')) or ext in ('mp4', 'webm', 'mov', 'mp3', 'ogg', 'wav', 'm4a'):
        return 'media'
    if 'html' in ct:
        return 'document'
    return 'other'


def nome_arquivo(url, n=40):
    u = urlparse(url)
    nome = u.path.rstrip('/').rsplit('/', 1)[-1] or u.netloc
    return corta(nome, n)


def _max_age(cab):
    m = re.search(r'max-age=(\d+)', cab.get('cache-control', ''))
    if m:
        return int(m.group(1))
    return 0 if 'no-cache' in cab.get('cache-control', '') or 'no-store' in cab.get('cache-control', '') else None


def _fontes_do_css(css, base):
    """Fontes que o navegador baixaria: a primeira de cada @font-face, só nos subconjuntos latinos."""
    fontes = []
    for bloco in re.findall(r'@font-face\s*{([^}]*)}', css, re.I):
        faixa = re.search(r'unicode-range\s*:\s*([^;]+)', bloco, re.I)
        # o Google Fonts manda um bloco por alfabeto; quem lê português só baixa o latino
        if faixa and not re.search(r'U\+0{1,4}(-|,|\s|$)', faixa.group(1), re.I):
            continue
        src = re.search(r'src\s*:\s*([^;]+)', bloco, re.I)
        m = src and re.search(r'url\(\s*[\'"]?([^\'")]+)', src.group(1))
        if m:
            fontes.append(absoluto(base, m.group(1)))
    imports = [absoluto(base, u) for u in re.findall(r'@import\s+(?:url\()?\s*[\'"]?([^\'")\s;]+)', css)]
    return [f for f in fontes if f], [i for i in imports if i]


def _baixa_recurso(url):
    r = busca(url, tempo=25)
    cab = r['cabecalhos']
    tipo = tipo_do_arquivo(r['url_final'], cab.get('content-type'))
    return {'url': url, 'tipo': tipo, 'status': r['status'], 'erro': r['erro'], 'transferido': r['baixado'],
            'tamanho': len(r['corpo']), 'compressao': cab.get('content-encoding', ''), 'cache': _max_age(cab),
            'corpo': r['corpo'] if tipo in ('script', 'stylesheet', 'document') or url.lower().split('?')[0].endswith('.svg') else b''}


def mede_estatico(url, nav, pr=None):
    pag = busca(url)
    if pag['erro'] or not pag['status']:
        return {'url': url, 'erro': pag['erro'] or 'sem resposta'}
    final = pag['url_final']
    html_bruto = pag['corpo'].decode('utf-8', 'replace')
    bruto = LeitorHTML(html_bruto)
    modulos = any((s.get('type') or '').lower() == 'module' for s in bruto.scripts)
    raiz_vazia = re.search(r'<div[^>]+id=["\'](root|app|__next|__nuxt|svelte)["\'][^>]*>\s*</div>', html_bruto, re.I)
    spa = bool(raiz_vazia) or (len(bruto.texto) < 40 and modulos and not bruto.titulos)
    d, dom = bruto, ''
    if spa and nav:
        if pr:
            pr.atual = 'renderizando com o navegador (site com JavaScript)'
        dom = dom_renderizado(nav, final) or ''
        if dom:
            d = LeitorHTML(dom)
    agora, depois = [], []
    for s in bruto.scripts + d.scripts:
        agora.append(absoluto(final, s.get('src')))
    for l in bruto.links + d.links:
        rel = (l.get('rel') or '').lower().split()
        if {'stylesheet', 'modulepreload', 'preload', 'icon'} & set(rel) and (l.get('media') or '').lower() != 'print':
            agora.append(absoluto(final, l.get('href')))
    for i in d.imgs:
        src = i.get('src') or (i.get('srcset') or '').split(',')[0].strip().split(' ')[0]
        # imagem com loading="lazy" só desce quando a pessoa rola até ela
        (depois if (i.get('loading') or '').lower() == 'lazy' else agora).append(absoluto(final, src))
    for m in d.midias:
        agora.append(absoluto(final, m.get('poster')))
        depois.append(absoluto(final, m.get('src')))
    agora = [u for u in dict.fromkeys(agora) if u]
    depois = [u for u in dict.fromkeys(depois) if u and u not in agora]
    if pr:
        pr.atual = f'baixando {len(agora) + len(depois)} arquivos da página'
    with ThreadPoolExecutor(max_workers=8) as ex:
        recursos = list(ex.map(_baixa_recurso, agora))
        sob_demanda = list(ex.map(_baixa_recurso, depois))
        vistos = set(agora) | set(depois)
        # fontes e @import dentro dos CSS, até dois níveis
        for _ in range(2):
            novos = []
            for r in recursos:
                if r['tipo'] == 'stylesheet' and r['corpo'] and not r.get('_lido'):
                    r['_lido'] = True
                    fontes, imports = _fontes_do_css(r['corpo'].decode('utf-8', 'replace'), r['url'])
                    novos += [u for u in fontes + imports if u not in vistos]
                    vistos.update(fontes + imports)
            if not novos:
                break
            recursos += list(ex.map(_baixa_recurso, list(dict.fromkeys(novos))))
    doc = {'url': final, 'tipo': 'document', 'status': pag['status'], 'erro': None, 'transferido': pag['baixado'] or len(pag['corpo']),
           'tamanho': len(pag['corpo']), 'compressao': pag['cabecalhos'].get('content-encoding', ''),
           'cache': _max_age(pag['cabecalhos']), 'corpo': pag['corpo']}
    recursos = [doc] + [r for r in recursos if not r['erro'] and r['status'] < 400 and r['transferido']]
    sob_demanda = [r for r in sob_demanda if not r['erro'] and r['status'] < 400 and r['transferido']]
    host = urlparse(final).hostname
    for r in recursos + sob_demanda:
        h = urlparse(r['url']).hostname
        r['terceiro'] = nome_terceiro(h) if dominio_base(h) != dominio_base(host) else None
        r['sem_uso'] = None
    tec, hospedagem = detecta_stack(html_bruto + dom, pag['cabecalhos'])
    return {'url': url, 'final': final, 'status': pag['status'], 'fonte': 'propria', 'recursos': recursos,
            'sob_demanda': sob_demanda, 'economias': economias_estaticas(recursos, html_bruto, hospedagem),
            'tec': tec, 'hospedagem': hospedagem, 'spa': spa, 'renderizado': bool(dom), 'html': html_bruto,
            'ancoras': [absoluto(final, a['href']) for a in d.ancoras]}


def economias_estaticas(recursos, html_bruto, hospedagem):
    E = []
    texto_sem_gzip = [r for r in recursos if not r['compressao'] and r['tamanho'] > 1400 and
                      (r['tipo'] in ('script', 'stylesheet', 'document') or r['url'].lower().split('?')[0].endswith('.svg'))]
    if texto_sem_gzip:
        # gzip deixa HTML, CSS e JS com uns 30% do tamanho
        E.append({'id': 'uses-text-compression', 'titulo': 'Ligar compressão (gzip ou brotli) no servidor',
                  'arquivos': [(r['url'], int(r['tamanho'] * 0.7)) for r in texto_sem_gzip]})
    antigas = [r for r in recursos if r['tipo'] == 'image' and re.search(r'\.(jpe?g|png)(\?|$)', r['url'], re.I)
               and r['transferido'] > 50 * 1024]
    if antigas:
        # WebP fica em média 25–35% menor que JPG e bem menor que PNG de foto; a conta usa 30%, por baixo
        E.append({'id': 'modern-image-formats', 'titulo': 'Converter imagens JPG/PNG para WebP ou AVIF',
                  'arquivos': [(r['url'], int(r['transferido'] * 0.3)) for r in antigas]})
    gifs = [r for r in recursos if re.search(r'\.gif(\?|$)', r['url'], re.I) and r['transferido'] > 100 * 1024]
    if gifs:
        E.append({'id': 'efficient-animated-content', 'titulo': 'Trocar GIF animado por vídeo (MP4/WebM)',
                  'arquivos': [(r['url'], int(r['transferido'] * 0.8)) for r in gifs]})
    fontes_velhas = [r for r in recursos if r['tipo'] == 'font' and re.search(r'\.(ttf|otf|eot|woff)(\?|$)', r['url'], re.I)]
    if fontes_velhas:
        E.append({'id': 'fontes-woff2', 'titulo': 'Usar fontes em WOFF2',
                  'arquivos': [(r['url'], int(r['transferido'] * (0.3 if r['url'].lower().split('?')[0].endswith('.woff') else 0.5)))
                               for r in fontes_velhas]})
    sem_minificar = []
    for r in recursos:
        if r['tipo'] in ('script', 'stylesheet') and r['tamanho'] > 20 * 1024 and r['corpo']:
            txt = r['corpo']
            # código minificado quase não tem quebra de linha nem indentação
            if txt.count(b'\n') > len(txt) / 80 and txt.count(b'  ') > len(txt) / 50:
                sem_minificar.append(r)
    if sem_minificar:
        E.append({'id': 'unminified-javascript', 'titulo': 'Minificar JavaScript e CSS (build de produção)',
                  'arquivos': [(r['url'], int(r['transferido'] * 0.3)) for r in sem_minificar]})
    b64 = sum(len(m) for m in re.findall(r'data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+', html_bruto))
    for r in recursos:
        if r['tipo'] == 'stylesheet' and r['corpo']:
            b64 += sum(len(m) for m in re.findall(rb'data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+', r['corpo']))
    if b64 > 20 * 1024:
        E.append({'id': 'base64', 'titulo': 'Tirar imagens em base64 de dentro do HTML/CSS',
                  'arquivos': [('(embutidas no HTML/CSS)', int(b64 * 0.25))]})
    for e in E:
        e['bytes'] = sum(b for _, b in e['arquivos'])
    return sorted([e for e in E if e['bytes'] > 1024], key=lambda e: -e['bytes'])


def mede_lighthouse(dados, url):
    audits = dados.get('audits', {})
    final = dados.get('finalDisplayedUrl') or dados.get('finalUrl') or url
    host = urlparse(final).hostname
    proprios = set()
    for ent in dados.get('entities') or []:
        if ent.get('isFirstParty'):
            proprios.update(urlparse(o).hostname for o in ent.get('origins', []))
    sem_uso = {}
    for aid in ('unused-javascript', 'unused-css-rules'):
        for it in ((audits.get(aid) or {}).get('details') or {}).get('items') or []:
            if it.get('url') and it.get('totalBytes'):
                sem_uso[it['url']] = round(100 * (it.get('wastedBytes') or 0) / it['totalBytes'])
    recursos = []
    for it in ((audits.get('network-requests') or {}).get('details') or {}).get('items') or []:
        u = it.get('url') or ''
        if not u.startswith('http') or not it.get('transferSize'):
            continue
        h = urlparse(u).hostname
        terceiro = None
        if h not in proprios and dominio_base(h) != dominio_base(host):
            terceiro = it.get('entity') if isinstance(it.get('entity'), str) else nome_terceiro(h)
        tipo = TIPO_LH.get(it.get('resourceType')) or tipo_do_arquivo(u, it.get('mimeType'))
        recursos.append({'url': u, 'tipo': tipo, 'transferido': it['transferSize'], 'tamanho': it.get('resourceSize') or 0,
                         'terceiro': terceiro, 'sem_uso': sem_uso.get(u), 'cache': None})
    for it in ((audits.get('uses-long-cache-ttl') or {}).get('details') or {}).get('items') or []:
        for r in recursos:
            if r['url'] == it.get('url'):
                r['cache'] = int((it.get('cacheLifetimeMs') or 0) / 1000)
    economias = []
    for aid in LH_ECONOMIAS:
        a = audits.get(aid) or {}
        det = a.get('details') or {}
        itens = [(it.get('url'), it.get('wastedBytes') or 0) for it in det.get('items') or [] if it.get('url')]
        total = det.get('overallSavingsBytes') or sum(b for _, b in itens)
        if (a.get('score') is None or a['score'] < 1) and total > 2048:
            economias.append({'id': aid, 'titulo': a.get('title', aid), 'bytes': total,
                              'arquivos': sorted(itens, key=lambda x: -x[1])})
    economias.sort(key=lambda e: -e['bytes'])
    lcp = None
    det = (audits.get('largest-contentful-paint-element') or {}).get('details') or {}
    for bloco in det.get('items') or []:
        for it in (bloco.get('items') if isinstance(bloco, dict) and 'items' in bloco else [bloco]):
            node = (it or {}).get('node') or {}
            if node.get('snippet'):
                lcp = node['snippet']
                break
        if lcp:
            break
    return {'url': url, 'final': final, 'fonte': 'lighthouse', 'recursos': recursos, 'sob_demanda': [],
            'economias': economias, 'lcp': lcp,
            'lcp_tempo': (audits.get('largest-contentful-paint') or {}).get('displayValue')}


def resumo_por_tipo(recursos):
    tipos = {}
    for r in recursos:
        t_ = tipos.setdefault(r['tipo'], {'bytes': 0, 'n': 0})
        t_['bytes'] += r['transferido']
        t_['n'] += 1
    return tipos


def economia_total(economias):
    # o mesmo arquivo aparece em mais de uma sugestão (sem uso e sem minificar): conta o maior ganho de cada um
    por_arquivo = {}
    for e in economias:
        if e['id'] == 'offscreen-images':
            continue  # imagem fora da tela só é adiada, não some
        for u, b in e['arquivos'] or [(e['id'], e['bytes'])]:
            por_arquivo[u] = max(por_arquivo.get(u, 0), b)
    return sum(por_arquivo.values())


def meta_mb():
    return f'{ORCAMENTO["total"][0] / 1024:.1f} MB'.replace('.', ',')


def nivel_orcamento(chave, bytes_):
    bom, ok = ORCAMENTO[chave]
    kb = bytes_ / 1024
    return 'ok' if kb <= bom else 'aviso' if kb <= ok else 'falha'


def co2_por_visita(bytes_):
    # modelo Sustainable Web Design (v3): 0,81 kWh por GB transferido, 442 g de CO2 por kWh (média mundial)
    return bytes_ / 1024 ** 3 * 0.81 * 442


def onde_mexer_peso(eid, med):
    tec, host = med.get('tec') or [], med.get('hospedagem')
    vite, nxt = 'Vite' in tec, 'Next.js' in tec
    dicas = {
        'unused-javascript': 'Divida o código por rota com `import()` dinâmico (`React.lazy` + `Suspense`) e carregue '
                             'só o que a primeira tela usa. Veja o que entra no pacote com '
                             + ('`@next/bundle-analyzer`' if nxt else '`npx vite-bundle-visualizer`' if vite else 'um analisador de bundle')
                             + '. Troque bibliotecas grandes por menores (moment → dayjs, lodash → import por função).',
        'unused-css-rules': 'Importe só as partes usadas de bibliotecas de CSS (Bootstrap, animate.css, ícones). '
                            'Com Tailwind, confira se o `content`/`@source` cobre só os arquivos do projeto.',
        'modern-image-formats': ('Use `next/image`, que já serve WebP/AVIF. ' if nxt else '')
                                + 'Converta para WebP ou AVIF (squoosh.app, ou o pacote `sharp` num script) e troque o caminho no código; '
                                  'se precisar de navegador antigo, use `<picture>` com o JPG de reserva.',
        'uses-optimized-images': 'Comprima as imagens (qualidade 75–80 é suficiente para foto) antes de pôr no projeto.',
        'uses-responsive-images': 'A imagem é maior do que aparece na tela: gere tamanhos menores e use `srcset` + `sizes`'
                                  + (' (o `next/image` faz isso sozinho)' if nxt else '') + '.',
        'offscreen-images': 'Ponha `loading="lazy"` nas imagens abaixo da dobra (nunca na primeira imagem grande, que é o LCP).',
        'uses-text-compression': ('A ' + host + ' já comprime sozinha: confira se esses arquivos não vêm de outro servidor. '
                                  if host in ('Vercel', 'Netlify', 'GitHub Pages', 'Cloudflare') else
                                  'Ligue gzip/brotli no servidor (Express: pacote `compression`; nginx: `gzip on`). '),
        'unminified-javascript': 'Publique o resultado do `npm run build`, nunca os arquivos de desenvolvimento; '
                                 'para JS/CSS escritos à mão, minifique com `npx esbuild arquivo.js --minify`.',
        'unminified-css': 'Publique o CSS do build de produção, ou minifique com `npx esbuild estilo.css --minify`.',
        'efficient-animated-content': 'Troque o GIF por `<video autoplay muted loop playsinline>` com MP4/WebM.',
        'duplicated-javascript': 'A mesma biblioteca entra mais de uma vez: alinhe as versões no `package.json` e rode `npm dedupe`.',
        'legacy-javascript': 'O build inclui polyfills para navegadores antigos: ajuste o `browserslist`'
                             + (' ou o `build.target` do Vite' if vite else '') + '.',
        'fontes-woff2': 'Converta para WOFF2 e carregue só os pesos usados; `@fontsource/<fonte>` auto-hospeda já em WOFF2.',
        'base64': 'Imagem em base64 não entra em cache e atrasa o primeiro desenho: salve como arquivo e referencie pelo caminho.',
    }
    return dicas.get(eid, '').strip()


def gera_resumo_peso(med, total, tipos, n_req, economia, maiores, terceiros):
    fonte = 'Lighthouse, ' + ('computador' if med.get('desktop') else 'celular') if med['fonte'] == 'lighthouse' else 'medição própria'
    rotulos = {k: r for k, r, _ in TIPOS_PESO}
    L = [f'# Peso de {med["final"]}: o que reduzir', '',
         f'> Medido pelo ferramentas em {datetime.now():%d/%m/%Y %H:%M} ({fonte}). '
         f'Total: {humano(total)} em {n_req} requisições.', '', '## Contexto', '',
         f'- Meta para o celular: até {meta_mb()} por página; a mediana da web é ~2,3 MB.']
    if med.get('tec') or med.get('hospedagem'):
        L.append(f'- Tecnologia detectada: {", ".join(med.get("tec") or ["não identificada"])}'
                 + (f' · hospedagem: {med["hospedagem"]}' if med.get('hospedagem') else ''))
    L.append('- Por tipo: ' + ', '.join(f'{rotulos[k]} {humano(v["bytes"])}' for k, v in
                                        sorted(tipos.items(), key=lambda x: -x[1]['bytes'])))
    if med.get('lcp'):
        L.append(f'- Elemento do LCP ({med.get("lcp_tempo") or "?"}): `{corta(med["lcp"], 140)}` — não ponha `loading="lazy"` nele.')
    L += ['', '## O que fazer', '',
          'Você está no código deste site. Reduza o peso seguindo os itens abaixo, do maior ganho para o menor:', '',
          '1. Encontre no código onde cada arquivo listado é usado ou importado.',
          '2. Não mude o visual nem tire funcionalidade para ganhar peso; se um item exigir isso, pule e explique.',
          '3. Imagens: gere a versão nova ao lado da antiga e troque as referências; só apague a antiga se nada mais a usar.',
          '4. No final, liste o que mudou arquivo por arquivo e o ganho esperado.', '']
    if economia:
        L += [f'Ganho possível estimado: **{humano(economia)}** (de {humano(total)} para ~{humano(max(0, total - economia))}).', '']
    for i, e in enumerate(med['economias'], 1):
        L.append(f'### {i}. {md(e["titulo"])} (−{humano(e["bytes"])})')
        for u, b in e['arquivos'][:8]:
            L.append(f'- [ ] `{u}`' + (f' — {humano(b)} a menos' if b else ''))
        if len(e['arquivos']) > 8:
            L.append(f'- … e mais {len(e["arquivos"]) - 8}')
        dica = onde_mexer_peso(e['id'], med)
        if dica:
            L.append(f'- **Como:** {dica}')
        L.append('')
    if not med['economias']:
        L += ['Nenhuma economia grande apontada. Confira os arquivos mais pesados abaixo.', '']
    estourados = [(k, v) for k, v in tipos.items() if k in ORCAMENTO and nivel_orcamento(k, v['bytes']) != 'ok']
    if estourados:
        L += ['## Acima da meta', '']
        L += [f'- {rotulos[k]}: {humano(v["bytes"])} (meta: até {ORCAMENTO[k][0]} KB)' for k, v in estourados] + ['']
    L += ['## Arquivos mais pesados', '', '| arquivo | tipo | transferido | sem uso |', '| --- | --- | --- | --- |']
    for r in maiores:
        L.append(f'| `{corta(r["url"], 90)}` | {rotulos[r["tipo"]]} | {humano(r["transferido"])} | '
                 + (f'{r["sem_uso"]}%' if r.get('sem_uso') is not None else '—') + ' |')
    L.append('')
    if terceiros:
        L += ['## Terceiros', '', 'Scripts e arquivos de outros domínios. Avalie se cada um é necessário, se pode carregar '
              'depois da interação ou ser auto-hospedado (fontes, por exemplo):', '']
        L += [f'- {n}: {humano(v["bytes"])} em {pl(v["n"], "arquivo")}' for n, v in terceiros] + ['']
    L += ['## Como conferir', '', f'- [ ] Rodar de novo: `python ferramentas.py peso {med["final"]}`',
          f'- [ ] Total abaixo de {humano(total)} (meta: {meta_mb()})',
          '- [ ] O site continua igual na tela, no celular e no computador', '']
    return '\n'.join(L)


def barra_peso(t, fracao, larg, cor):
    cheio = max(1 if fracao > 0 else 0, round(larg * fracao))
    vazio = '■' if t.cor else ('-' if t.nivel == 'ascii' else '·')
    return t.p(('#' if t.nivel == 'ascii' else '■') * cheio, cor) + t.p(vazio * (larg - cheio), 'fundo')


def ferramenta_peso(t, args):
    args.desktop = args.desktop or config('dispositivo') == 'computador'
    url = args.url.strip()
    if not re.match(r'https?://', url):
        url = ('http://' if re.match(r'(localhost|127\.0\.0\.1)', url) else 'https://') + url
    nav = acha_navegador()
    t.prompt('peso', url, alvo=url)
    paginas = []
    with Progresso(t, None, 'medindo') as pr:
        pr.atual = 'baixando a página'
        est = mede_estatico(url, nav, pr)
        med, lh_erro = est, None
        if not est.get('erro') and not args.rapido:
            pr.atual = 'rodando o Lighthouse (pode levar 1 minuto)'
            dados, lh_erro = roda_lighthouse(est['final'], nav, args.desktop, 'performance')
            if dados:
                med = mede_lighthouse(dados, est['final'])
                if not med['recursos']:
                    med, lh_erro = est, 'o Lighthouse não devolveu a lista de arquivos'
                else:
                    med.update(tec=est['tec'], hospedagem=est['hospedagem'], desktop=args.desktop)
        if not est.get('erro') and args.paginas:
            host = urlparse(est['final']).netloc
            internos = [u for u in dict.fromkeys(est['ancoras']) if u and urlparse(u).netloc == host
                        and u.rstrip('/') != est['final'].rstrip('/')
                        and not re.search(r'\.(pdf|zip|png|jpe?g|svg|xml|webp)(\?|$)', u, re.I)]
            if len(internos) < args.paginas:
                _, sms = info_robots(f'{urlparse(est["final"]).scheme}://{host}')
                internos += [u for u in le_sitemap(f'{urlparse(est["final"]).scheme}://{host}', sms)
                             if u not in internos and u.rstrip('/') != est['final'].rstrip('/')]
            for u in internos[:args.paginas]:
                pr.atual = caminho_curto(u)
                paginas.append(mede_estatico(u, None))
    if est.get('erro'):
        t.erro(f'Não consegui abrir {url}: {est["erro"]}.')
        return 1

    recursos = med['recursos']
    total = sum(r['transferido'] for r in recursos)
    tipos = resumo_por_tipo(recursos)
    n_req = len(recursos)
    linha = [t.p(humano(total), 'verde' if nivel_orcamento('total', total) == 'ok' else 'amarelo'
                 if nivel_orcamento('total', total) == 'aviso' else 'vermelho', True),
             t.p(f'{n_req} requisições', 'texto')]
    descomp = sum(r['tamanho'] for r in recursos)
    if descomp > total * 1.15:
        linha.append(t.p(f'{humano(descomp)} descomprimidos', 'sub'))
    linha.append(t.p('Lighthouse · ' + ('computador' if args.desktop else 'celular') if med['fonte'] == 'lighthouse'
                     else 'medição própria', 'sub'))
    if med.get('tec') or med.get('hospedagem'):
        linha.append(t.p(' + '.join(med.get('tec') or []) + (f' na {med["hospedagem"]}' if med.get('hospedagem') else ''), 'roxo'))
    if med['final'].rstrip('/') != url.rstrip('/'):
        t.nota(f'  → {corta(med["final"], t.largura - 6)}', 2)
    t.partes(linha)
    vezes = total / MEDIANA_WEB
    t.paragrafo(f'{vezes:.1f}× a mediana da web no celular (~2,3 MB)'.replace('.', ',') if vezes >= 1.05 else
                f'{(1 - vezes) * 100:.0f}% mais leve que a mediana da web no celular (~2,3 MB)', 4, 'apagado')
    if lh_erro and not args.rapido:
        t.paragrafo(f'Lighthouse: {lh_erro} · usando a medição própria', 4, 'apagado')
    if est.get('spa') and not est.get('renderizado') and med['fonte'] == 'propria':
        t.paragrafo('Site montado por JavaScript e sem navegador para renderizar: os arquivos que o JavaScript '
                    'carrega depois ficam de fora da conta.', 4, 'amarelo')

    # histórico: a última medição da mesma URL, pela mesma fonte
    hist_arq = CASA / 'peso' / _arquivo_historico(med['final']).name
    anterior = None
    try:
        anterior = json.loads(hist_arq.read_text(encoding='utf-8'))
        if anterior.get('fonte') != med['fonte'] or anterior.get('desktop', False) != bool(args.desktop):
            anterior = None
    except (OSError, ValueError):
        pass

    def delta(atual, antes):
        if antes is None or abs(atual - antes) < 1024:
            return ''
        dif = atual - antes
        return t.p(f' {"↑" if dif > 0 else "↓"}{humano(abs(dif))}', 'vermelho' if dif > 0 else 'verde')

    rotulos = {k: r for k, r, _ in TIPOS_PESO}
    t.escreve()
    t.titulo('por tipo')
    com_arqs = t.largura >= 50
    larg = max(3, min(16, t.largura - (46 if com_arqs else 37)))
    for k, rotulo, cor in TIPOS_PESO:
        v = tipos.get(k)
        if not v:
            continue
        pct = 100 * v['bytes'] / max(total, 1)
        estouro = ''
        if k in ORCAMENTO and nivel_orcamento(k, v['bytes']) != 'ok':
            estouro = t.p(' !', 'amarelo' if nivel_orcamento(k, v['bytes']) == 'aviso' else 'vermelho', True)
        antes = (anterior or {}).get('tipos', {}).get(k)
        tam, arqs = humano(v['bytes']), f" {v['n']:>3} arq." if com_arqs else ''
        t.escreve(f'    {t.p(f"{rotulo:<13}", "texto")}{barra_peso(t, v["bytes"] / max(total, 1), larg, cor)} '
                  f'{t.p(f"{tam:>8}", "texto")} {t.p(f"{pct:>3.0f}%", "sub")}'
                  f'{t.p(arqs, "apagado")}{estouro}{delta(v["bytes"], antes)}')
    tam, rot = humano(total), 'total'
    t.escreve(f'    {t.p(f"{rot:<13}", "texto", True)}{" " * (larg + 1)}{t.p(f"{tam:>8}", "texto", True)}'
              + (f'      {t.p(f"{n_req:>3} arq.", "apagado")}' if com_arqs else '') + delta(total, (anterior or {}).get('total')))
    if med.get('sob_demanda'):
        extra = sum(r['transferido'] for r in med['sob_demanda'])
        t.paragrafo(f'+ {humano(extra)} em {pl(len(med["sob_demanda"]), "arquivo")} que só descem se a pessoa rolar '
                    'ou der play (loading="lazy", vídeo)', 4, 'apagado')
    if anterior:
        t.paragrafo(f'comparado com a última medição ({ha_quanto_iso(anterior.get("quando"))}): '
                    + ('mais pesado' if total > anterior.get('total', 0) + 1024 else
                       'mais leve' if total < anterior.get('total', 0) - 1024 else 'praticamente igual'), 4, 'apagado')

    # metas
    fora = [(k, v) for k, v in tipos.items() if k in ORCAMENTO and nivel_orcamento(k, v['bytes']) != 'ok']
    req_nivel = 'ok' if n_req <= ORCAMENTO_REQ[0] else 'aviso' if n_req <= ORCAMENTO_REQ[1] else 'falha'
    t.escreve()
    t.titulo('metas para o celular')
    estilo = {'ok': ('✓', 'verde'), 'aviso': ('!', 'amarelo'), 'falha': ('✗', 'vermelho')}
    nv = nivel_orcamento('total', total)
    t.item(estilo[nv][0], estilo[nv][1], 'página inteira', t.p(f'{humano(total)} / meta {meta_mb()}', estilo[nv][1]), recuo=4)
    t.item(estilo[req_nivel][0], estilo[req_nivel][1], 'requisições', t.p(f'{n_req} / meta {ORCAMENTO_REQ[0]}', estilo[req_nivel][1]), recuo=4)
    for k, v in sorted(fora, key=lambda x: -x[1]['bytes']):
        nv = nivel_orcamento(k, v['bytes'])
        t.item(estilo[nv][0], estilo[nv][1], rotulos[k], t.p(f'{humano(v["bytes"])} / meta {ORCAMENTO[k][0]} KB', estilo[nv][1]), recuo=4)
    if not fora:
        t.paragrafo('JavaScript, CSS, imagens e fontes dentro da meta', 4, 'apagado')

    # mais pesados
    maiores = sorted(recursos, key=lambda r: -r['transferido'])[:8]
    t.escreve()
    t.titulo('os mais pesados')
    for r in maiores:
        info = [rotulos[r['tipo']]]
        if r.get('sem_uso') is not None and r['sem_uso'] >= 20:
            info.append(f'{r["sem_uso"]}% sem uso')
        if r.get('terceiro'):
            info.append(r['terceiro'])
        cor = 'vermelho' if r['transferido'] > 300 * 1024 else 'amarelo' if r['transferido'] > 100 * 1024 else 'sub'
        det = ' · '.join(info)
        # 4 de recuo + 8 do tamanho + 2 + nome + espaço + pontos + espaço + detalhe
        nome = nome_arquivo(r['url'], max(8, t.largura - 17 - len(det)))
        pontos = max(1, t.largura - 16 - len(nome) - len(det))
        tam = humano(r['transferido'])
        t.escreve(f'    {t.p(f"{tam:>8}", cor, True)}  {t.p(nome, "texto")} '
                  f'{t.p("·" * pontos, "superficie")} {t.p(det, "apagado")}')

    # terceiros
    por_terceiro = {}
    for r in recursos:
        if r.get('terceiro'):
            v = por_terceiro.setdefault(r['terceiro'], {'bytes': 0, 'n': 0})
            v['bytes'] += r['transferido']
            v['n'] += 1
    terceiros = sorted(por_terceiro.items(), key=lambda x: -x[1]['bytes'])
    if terceiros:
        soma = sum(v['bytes'] for _, v in terceiros)
        t.escreve()
        t.titulo(f'terceiros · {humano(soma)} ({100 * soma / max(total, 1):.0f}%)')
        for nome, v in terceiros[:6]:
            t.item('●', 'roxo', nome, t.p(f'{humano(v["bytes"])} · {pl(v["n"], "arquivo")}', 'sub'), recuo=4)
        if len(terceiros) > 6:
            t.paragrafo(f'e mais {len(terceiros) - 6}', 4, 'apagado')

    # economias
    economia = economia_total(med['economias'])
    t.escreve()
    if med['economias']:
        t.titulo(f'onde economizar · até {humano(economia)}')
        for e in med['economias'][:7]:
            t.item('↳', 'azul', e['titulo'], t.p(f'-{humano(e["bytes"])}', 'verde'), recuo=4)
            for u, b in e['arquivos'][:2]:
                t.nota(corta(f'{nome_arquivo(u, 40)}' + (f'  -{humano(b)}' if b else ''), t.largura - 9), 8)
        if med['fonte'] == 'propria':
            t.paragrafo('ganhos estimados pela medição própria; o Lighthouse mede também o JavaScript e o CSS sem uso', 4, 'apagado')
    else:
        t.titulo('onde economizar')
        t.ok('nenhuma economia grande à vista.')
    curtos = [r for r in recursos if r.get('cache') is not None and r['cache'] < 86400 and r['tipo'] != 'document'
              and not r.get('terceiro')]
    if curtos and len(curtos) >= max(2, len([r for r in recursos if r['tipo'] != 'document']) // 3):
        t.paragrafo(f'{pl(len(curtos), "arquivo")} com cache de menos de um dia: quem volta ao site baixa tudo de novo. '
                    'Arquivo com hash no nome (index-a1b2c3.js) pode ter cache de um ano.', 4, 'amarelo')

    # carbono
    co2 = co2_por_visita(total)
    t.escreve()
    t.paragrafo(f'~{co2:.2f} g de CO₂ por visita · mil visitas por mês ≈ {co2 * 12:.1f} kg por ano'.replace('.', ',')
                if co2 >= 0.01 else 'menos de 0,01 g de CO₂ por visita', 4, 'apagado')

    if paginas:
        t.escreve()
        t.titulo(f'outras {pl(len(paginas), "página")} (medição rápida)')
        for p in paginas:
            caminho = urlparse(p.get('final') or p['url']).path or '/'
            if p.get('erro'):
                t.item('✗', 'vermelho', caminho, t.p(p['erro'], 'vermelho'), recuo=4)
                continue
            tot = sum(r['transferido'] for r in p['recursos'])
            nv = nivel_orcamento('total', tot)
            maior = max(p['recursos'], key=lambda r: r['transferido'])
            t.item('●', estilo[nv][1], caminho, t.p(f'{humano(tot)} · {len(p["recursos"])} arq. · maior: {nome_arquivo(maior["url"], 18)}', 'sub'), recuo=4)

    rel = Relatorio('peso')
    rel.add(f'URL: {med["final"]}', f'fonte: {med["fonte"]} · total {humano(total)} · {n_req} requisições', '')
    rel.add(*[f'{rotulos[k]}: {humano(v["bytes"])} em {v["n"]} arquivos' for k, v in tipos.items()], '')
    rel.add('Arquivos (do mais pesado ao mais leve):')
    rel.add(*[f'  {humano(r["transferido"]):>9}  {rotulos[r["tipo"]]:<12} {r["url"]}' + (f'  ({r["sem_uso"]}% sem uso)' if r.get('sem_uso') else '')
              for r in sorted(recursos, key=lambda r: -r['transferido'])], '')
    for e in med['economias']:
        rel.add(f'Economia: {e["titulo"]} — {humano(e["bytes"])}', *[f'  {humano(b):>9}  {u}' for u, b in e['arquivos']])
    for p in paginas:
        if not p.get('erro'):
            rel.add('', f'Página {p["final"]}: {humano(sum(r["transferido"] for r in p["recursos"]))} em {len(p["recursos"])} arquivos')

    CASA.joinpath('peso').mkdir(parents=True, exist_ok=True)
    hist_arq.write_text(json.dumps({'url': med['final'], 'quando': agora_iso(), 'fonte': med['fonte'], 'desktop': bool(args.desktop),
                                    'total': total, 'tipos': {k: v['bytes'] for k, v in tipos.items()}}), encoding='utf-8')
    t.escreve()
    t.relatorio(rel.salva())
    entrega_resumo_ia(t, args, gera_resumo_peso(med, total, tipos, n_req, economia, maiores, terceiros), 'peso')
    return 0


# ═══════════════════════════════ 11. atualizar ═══════════════════════════════

GRUPOS_ATUALIZAR = [('sistema', 'sistema e programas'), ('linguagens', 'linguagens'), ('pacotes', 'pacotes globais'),
                    ('editores', 'extensões dos editores')]
ENV_C = dict(os.environ, LC_ALL='C', LANG='C')  # saída em inglês: é ela que se sabe ler


def versao_tupla(v):
    return tuple(int(x) for x in re.findall(r'\d+', str(v or ''))[:4])


# pré-lançamento pelo nome: alpha, beta, rc, nightly… e o jeito do PEP 440 (1.0a1, 2.0b3, 3.1rc1, 1.2.dev0).
# "2.80.0-6ubuntu3" e "2.43.0.windows.1" não entram: o traço e o texto ali são revisão, não pré-lançamento
RE_INSTAVEL = re.compile(r'(?i)(alpha|beta|\brc|[._-]rc|\bpre\b|[._-]pre|preview|nightly|canary|insider|snapshot|'
                         r'experimental|unstable|\bnext\b|[._-]dev|\d(a|b|rc|c)\d+\b)')


def eh_estavel(v):
    return bool(v) and not RE_INSTAVEL.search(str(v))


def subiu_major(atual, novo):
    a, n = versao_tupla(atual), versao_tupla(novo)
    return bool(a and n and n[0] > a[0])


def _sai(cmd, tempo=180, env=None):
    r = roda(cmd, env=env, tempo=tempo)
    return r.returncode, texto(r.stdout), texto(r.stderr)


def _ultimo_quadro(linha):
    # winget e scoop desenham barras com \r: fica só o que sobrou por último na linha
    return linha.rsplit('\r', 1)[-1].rstrip()


def _tabela_por_cabecalho(saida, colunas):
    """Lê tabelas de texto (winget): acha a linha de traços e corta as linhas pelas posições do cabeçalho."""
    linhas = [_ultimo_quadro(l) for l in saida.splitlines()]
    for i in range(1, len(linhas)):
        if re.fullmatch(r'-{10,}', linhas[i].strip()):
            inicios = [m.start() for m in re.finditer(r'\S+', linhas[i - 1])]
            if len(inicios) < colunas:
                continue
            linhas_tab = []
            for l in linhas[i + 1:]:
                if not l.strip() or re.match(r'^\d+ ', l) or len(l) < inicios[colunas - 2]:
                    break
                linhas_tab.append([l[a:b].strip() for a, b in zip(inicios, inicios[1:] + [None])])
            return linhas_tab
    return []


def _tabela_por_tracos(saida):
    """Tabela do PowerShell (scoop): as colunas começam onde começa cada grupo de traços."""
    linhas = [_ultimo_quadro(l) for l in saida.splitlines()]
    for i, l in enumerate(linhas):
        if re.fullmatch(r'[- ]*-{3,}[- ]*', l) and l.count('-') > 6:
            inicios = [m.start() for m in re.finditer(r'-+', l)]
            return [[x[a:b].strip() for a, b in zip(inicios, inicios[1:] + [None])] for x in linhas[i + 1:] if x.strip()]
    return []


def _json_web(url):
    r = busca(url, tempo=20)
    if r['status'] != 200:
        return None
    try:
        return json.loads(r['corpo'])
    except ValueError:
        return None


def _pypi(nome):
    """Última versão ESTÁVEL no PyPI: tira pré-lançamento e versão retirada (yanked)."""
    dados = _json_web(f'https://pypi.org/pypi/{quote(nome)}/json') or {}
    estaveis = [v for v, arqs in (dados.get('releases') or {}).items()
                if eh_estavel(v) and arqs and not all(a.get('yanked') for a in arqs)]
    if estaveis:
        return max(estaveis, key=versao_tupla)
    v = (dados.get('info') or {}).get('version')
    return v if eh_estavel(v) else None


def _pypi_varios(pares):
    with ThreadPoolExecutor(max_workers=8) as ex:
        novos = list(ex.map(lambda p: _pypi(p[0]), pares))
    return [(n, a, v) for (n, a), v in zip(pares, novos) if v and versao_tupla(v) > versao_tupla(a)]


# ---- verificações: cada uma devolve [(nome, versão atual, versão nova)] ----

def checa_winget():
    _, out, _ = _sai(['winget', 'upgrade', '--accept-source-agreements', '--disable-interactivity'], 240)
    return [(c[0], c[2], c[3]) for c in _tabela_por_cabecalho(out, 5) if len(c) >= 4 and c[3]]


def checa_choco():
    _, out, _ = _sai(['choco', 'outdated', '-r', '--ignore-pinned', '--no-color'], 240)
    return [tuple(l.split('|')[:3]) for l in out.splitlines() if l.count('|') >= 3]


def checa_scoop():
    _, out, _ = _sai([shutil.which('scoop'), 'status'], 240)
    return [(c[0], c[1], c[2]) for c in _tabela_por_tracos(out) if len(c) >= 3 and c[2] and c[2] != c[1]]


def checa_brew():
    _sai(['brew', 'update', '--quiet'], 300)
    _, out, _ = _sai(['brew', 'outdated', '--json=v2'], 120, dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1'))
    dados = json.loads(out or '{}')
    return [(f['name'], (f.get('installed_versions') or ['?'])[-1], f.get('current_version', '?'))
            for f in dados.get('formulae', []) + dados.get('casks', [])]


def checa_mas():
    _, out, _ = _sai(['mas', 'outdated'])
    return [m.groups() for m in re.finditer(r'^\d+\s+(.+?)\s+\((\S+) -> (\S+)\)', out, re.M)]


def checa_softwareupdate():
    _, out, err = _sai(['softwareupdate', '-l'], 300, ENV_C)
    return [(m.group(1), '', m.group(2)) for m in re.finditer(r'Title: ([^,]+), Version: ([^,]+)', out + err)]


def checa_apt():
    _, out, _ = _sai(['apt', 'list', '--upgradable'], 120, ENV_C)
    itens = [(m.group(1), m.group(3), m.group(2)) for m in
             re.finditer(r'^([^/\s]+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from: ([^\]\s]+)\]', out, re.M)]
    # a lista só se renova com "apt update", que pede sudo; velha, ela pode dizer "em dia" sem estar
    try:
        dias = int((time.time() - os.path.getmtime('/var/lib/apt/lists')) // 86400)
    except OSError:
        dias = 0
    if dias >= 2:
        return (itens or None), f'lista de pacotes de {dias} dias atrás; a atualização baixa a nova antes'
    return itens


def checa_dnf():
    cod, out, _ = _sai(['dnf', '-q', 'check-update'], 300, ENV_C)
    if cod not in (0, 100):
        raise RuntimeError('o dnf não respondeu')
    itens = []
    for l in out.splitlines():
        p = l.split()
        if len(p) == 3 and '.' in p[0] and not l.startswith(' '):
            itens.append((p[0].rsplit('.', 1)[0], '', p[1]))
    return itens


def checa_pacman():
    cmd = ['checkupdates'] if shutil.which('checkupdates') else ['pacman', '-Qu']
    _, out, _ = _sai(cmd, 300, ENV_C)
    return [m.groups() for m in re.finditer(r'^(\S+) (\S+) -> (\S+)', out, re.M)]


def checa_aur(prog):
    _, out, _ = _sai([prog, '-Qua'], 300, ENV_C)
    return [m.groups() for m in re.finditer(r'^(\S+) (\S+) -> (\S+)', out, re.M)]


def checa_zypper():
    _, out, _ = _sai(['zypper', '-q', 'list-updates'], 300, ENV_C)
    linhas = [[c.strip() for c in l.split('|')] for l in out.splitlines() if l.startswith('v ')]
    return [(c[2], c[3], c[4]) for c in linhas if len(c) >= 5]


def checa_flatpak():
    _, out, _ = _sai(['flatpak', 'remote-ls', '--updates', '--columns=application,version'], 180, ENV_C)
    return [(p[0], '', p[1] if len(p) > 1 else '') for p in (l.split('\t') for l in out.splitlines()) if p[0].strip()]


def checa_snap():
    _, out, err = _sai(['snap', 'refresh', '--list'], 180, ENV_C)
    linhas = (out + err).splitlines()
    if not linhas or 'up to date' in (out + err):
        return []
    return [(p[0], '', p[1]) for p in (l.split() for l in linhas[1:]) if len(p) >= 2]


def checa_node():
    _, out, _ = _sai(['node', '--version'])
    atual = out.strip()
    indice = _json_web('https://nodejs.org/dist/index.json') or []
    lts = [v for v in indice if v.get('lts')]
    if not atual or not lts:
        raise RuntimeError('não consegui ver a versão do Node')
    mesma = [v['version'] for v in lts if versao_tupla(v['version'])[:1] == versao_tupla(atual)[:1]]
    alvo = mesma[0] if mesma else lts[0]['version']
    itens = [('Node.js', atual, alvo)] if versao_tupla(alvo) > versao_tupla(atual) else []
    nota = '' if versao_tupla(lts[0]['version'])[:1] == versao_tupla(atual)[:1] else f'LTS mais nova: {lts[0]["version"]}'
    return itens, nota


def dica_node():
    if shutil.which('fnm'):
        return 'fnm install --lts'
    if shutil.which('volta'):
        return 'volta install node@lts'
    if os.environ.get('NVM_DIR') or os.environ.get('NVM_HOME'):
        return 'nvm install --lts'
    if os.name == 'nt' and shutil.which('winget'):
        return 'winget upgrade OpenJS.NodeJS.LTS'
    if shutil.which('brew'):
        return 'brew upgrade node'
    return 'baixe a versão LTS em nodejs.org'


def checa_rustup():
    _, out, _ = _sai(['rustup', 'check'], 120)
    return [m.groups() for m in re.finditer(r'^(\S+) - Update available : (\S+).*?-> (\S+)', out, re.M)]


def checa_deno():
    _, out, _ = _sai(['deno', '--version'])
    atual = re.search(r'deno (\S+)', out)
    r = busca('https://dl.deno.land/release-latest.txt', tempo=15)
    novo = r['corpo'].decode('utf-8', 'replace').strip().lstrip('v') if r['status'] == 200 else ''
    if not atual or not novo:
        raise RuntimeError('não consegui ver a versão do Deno')
    return [('Deno', atual.group(1), novo)] if versao_tupla(novo) > versao_tupla(atual.group(1)) else []


def checa_bun():
    _, out, _ = _sai(['bun', '--version'])
    novo = (_json_web('https://registry.npmjs.org/bun/latest') or {}).get('version')
    if not out.strip() or not novo:
        raise RuntimeError('não consegui ver a versão do Bun')
    return [('Bun', out.strip(), novo)] if versao_tupla(novo) > versao_tupla(out.strip()) else []


def checa_npm():
    _, out, _ = _sai(['npm', 'outdated', '-g', '--json'], 180)  # sai com 1 quando há o que atualizar
    dados = json.loads(out or '{}')
    return [(n, v.get('current', '?'), v.get('latest', '?')) for n, v in dados.items()
            if v.get('latest') and v.get('current') != v.get('latest')]


def checa_pnpm():
    _, out, _ = _sai(['pnpm', 'outdated', '-g', '--format', 'json'], 180)
    try:
        dados = json.loads(out or '{}')
    except ValueError:
        return []
    return [(n, v.get('current', '?'), v.get('latest', '?')) for n, v in dados.items() if v.get('latest')]


def pip_gerenciado_pelo_sistema():
    import sysconfig
    if sys.prefix != getattr(sys, 'base_prefix', sys.prefix):
        return False  # num venv o pip é seu
    return Path(sysconfig.get_paths()['stdlib'], 'EXTERNALLY-MANAGED').exists()


def checa_pip():
    if pip_gerenciado_pelo_sistema():
        return [], 'Python do sistema: quem atualiza é o gerenciador de pacotes (use pipx para ferramentas)'
    # --not-required: só o que você instalou, não as dependências (atualizar dependência solta quebra quem depende dela)
    cod, out, err = _sai([sys.executable, '-m', 'pip', 'list', '--outdated', '--not-required', '--format=json',
                          '--disable-pip-version-check'], 240)
    if cod != 0 and 'No module named pip' in err:
        return [], 'este Python não tem pip'
    if cod != 0:
        raise RuntimeError('o pip não respondeu')
    return [(p['name'], p['version'], p['latest_version']) for p in json.loads(out or '[]')]


def checa_pipx():
    _, out, _ = _sai(['pipx', 'list', '--json'], 120)
    venvs = json.loads(out or '{}').get('venvs', {})
    pares = [(v['metadata']['main_package']['package'], v['metadata']['main_package']['package_version'])
             for v in venvs.values() if v.get('metadata', {}).get('main_package')]
    return _pypi_varios(pares)


def checa_uv():
    _, out, _ = _sai(['uv', 'tool', 'list'], 60)
    return _pypi_varios(re.findall(r'^(\S+) v(\S+)', out, re.M))


def checa_cargo():
    _, out, _ = _sai(['cargo', 'install-update', '-l'], 300)
    return [(p[0], p[1], p[2]) for p in (l.split() for l in out.splitlines()) if len(p) >= 4 and p[3] == 'Yes']


def checa_gh():
    _, out, _ = _sai(['gh', 'extension', 'list'], 60)
    n = len([l for l in out.splitlines() if l.strip()])
    if not n:
        return []
    return None, f'{pl(n, "extensão", "extensões")}; o gh só sabe se há versão nova ao atualizar'


def _extensoes(editor):
    _, out, _ = _sai([shutil.which(editor), '--list-extensions', '--show-versions'], 120)
    return [tuple(l.strip().rsplit('@', 1)) for l in out.splitlines() if '@' in l]


def _ultima_marketplace(ids):
    # a mesma consulta que o VS Code faz; flags 0x11 = versões + propriedades (para pular as pré-lançamento)
    plataforma = {'win32': 'win32', 'darwin': 'darwin', 'linux': 'linux'}.get(sys.platform, sys.platform)
    ultimas = {}
    for i in range(0, len(ids), 25):
        criterios = [{'filterType': 8, 'value': 'Microsoft.VisualStudio.Code'}] + [{'filterType': 7, 'value': x} for x in ids[i:i + 25]]
        corpo = json.dumps({'filters': [{'criteria': criterios,
                                         'pageSize': 25}], 'flags': 0x11})
        arq = _arquivo_tmp('.json')
        arq.write_text(corpo, encoding='utf-8')
        try:
            r = roda(['curl', '-sS', '--max-time', '40', '-H', 'Accept: application/json;api-version=3.0-preview.1',
                      '-H', 'Content-Type: application/json', '--data-binary', f'@{arq}',
                      'https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery'], tempo=60)
        finally:
            arq.unlink()
        try:
            exts = json.loads(r.stdout)['results'][0]['extensions']
        except (ValueError, KeyError, IndexError):
            continue
        for e in exts:
            ident = f'{e["publisher"]["publisherName"]}.{e["extensionName"]}'.lower()
            for v in e.get('versions', []):
                props = {p['key']: p['value'] for p in v.get('properties', [])}
                alvo = v.get('targetPlatform')
                if props.get('Microsoft.VisualStudio.Code.PreRelease') == 'true':
                    continue
                if alvo and not alvo.startswith(plataforma) and alvo not in ('universal', 'web'):
                    continue
                ultimas[ident] = v['version']
                break
    return ultimas


def _ultima_openvsx(ident):
    ns, _, nome = ident.partition('.')
    base = f'https://open-vsx.org/api/{quote(ns)}/{quote(nome)}'
    dados = _json_web(base) or {}
    if not dados.get('preRelease') and eh_estavel(dados.get('version')):
        return dados.get('version')
    # a última é pré-lançamento: desce pelas versões até achar uma estável (no máximo 6 consultas)
    for v in sorted((dados.get('allVersions') or {}), key=versao_tupla, reverse=True)[:6]:
        if v == 'latest' or not eh_estavel(v):
            continue
        info = _json_web(f'{base}/{quote(v)}') or {}
        if not info.get('preRelease'):
            return v
    return None


def checa_editor(editor, loja):
    exts = _extensoes(editor)
    if not exts:
        return []
    if loja == 'ms':
        ultimas = _ultima_marketplace([i for i, _ in exts])
    else:
        with ThreadPoolExecutor(max_workers=8) as ex:
            ultimas = dict(zip([i.lower() for i, _ in exts], ex.map(_ultima_openvsx, [i for i, _ in exts])))
    return [(i, v, ultimas[i.lower()]) for i, v in exts
            if ultimas.get(i.lower()) and versao_tupla(ultimas[i.lower()]) > versao_tupla(v)]


def _cmds_editor(editor):
    return lambda itens: [[shutil.which(editor), '--install-extension', i, '--force'] for i, _, _ in itens]


def fontes_do_pc():
    """O que existe nesta máquina, na ordem em que aparece."""
    win, mac, linux = os.name == 'nt', sys.platform == 'darwin', sys.platform.startswith('linux')
    tem = shutil.which
    F = []

    def f(id_, grupo, nome, checa, comandos, sudo=False, admin=False, so_lista=False, dica=''):
        F.append({'id': id_, 'grupo': grupo, 'nome': nome, 'checa': checa, 'comandos': comandos, 'sudo': sudo,
                  'admin': admin, 'so_lista': so_lista, 'dica': dica})

    if win and tem('winget'):
        f('winget', 'sistema', 'winget', checa_winget,
          [['winget', 'upgrade', '--all', '--silent', '--accept-package-agreements', '--accept-source-agreements',
            '--disable-interactivity']])
    if win and tem('choco'):
        f('choco', 'sistema', 'Chocolatey', checa_choco, [['choco', 'upgrade', 'all', '-y', '--no-progress']], admin=True)
    if win and tem('scoop'):
        f('scoop', 'sistema', 'Scoop', checa_scoop, [[tem('scoop'), 'update'], [tem('scoop'), 'update', '*']])
    if tem('brew'):
        f('brew', 'sistema', 'Homebrew', checa_brew, [['brew', 'upgrade']])
    if mac and tem('mas'):
        f('mas', 'sistema', 'App Store', checa_mas, [['mas', 'upgrade']])
    if mac and tem('softwareupdate'):
        f('softwareupdate', 'sistema', 'macOS', checa_softwareupdate, [], so_lista=True,
          dica='Ajustes do Sistema > Geral > Atualização de Software')
    if linux and tem('apt-get') and tem('apt'):
        f('apt', 'sistema', 'apt', checa_apt, [['apt-get', 'update'], ['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get',
                                                                        '-y', 'upgrade']], sudo=True)
    if linux and tem('dnf'):
        f('dnf', 'sistema', 'dnf', checa_dnf, [['dnf', '-y', 'upgrade']], sudo=True)
    if linux and tem('pacman'):
        f('pacman', 'sistema', 'pacman', checa_pacman, [['pacman', '-Syu', '--noconfirm']], sudo=True)
    for aur in ('paru', 'yay'):
        if linux and tem(aur):
            f(aur, 'sistema', f'AUR ({aur})', lambda a=aur: checa_aur(a), [[aur, '-Sua', '--noconfirm']])
            break
    if linux and tem('zypper'):
        f('zypper', 'sistema', 'zypper', checa_zypper, [['zypper', '-n', 'update']], sudo=True)
    if linux and tem('flatpak'):
        f('flatpak', 'sistema', 'Flatpak', checa_flatpak, [['flatpak', 'update', '-y', '--noninteractive']])
    if linux and tem('snap'):
        f('snap', 'sistema', 'Snap', checa_snap, [['snap', 'refresh']], sudo=True)

    if tem('node'):
        f('node', 'linguagens', 'Node.js', checa_node, [], so_lista=True, dica=dica_node())
    if tem('rustup'):
        f('rustup', 'linguagens', 'Rust', checa_rustup, [['rustup', 'update']])
    if tem('deno'):
        f('deno', 'linguagens', 'Deno', checa_deno, [['deno', 'upgrade']])
    if tem('bun'):
        f('bun', 'linguagens', 'Bun', checa_bun, [['bun', 'upgrade']])

    if tem('npm'):
        f('npm', 'pacotes', 'npm (globais)', checa_npm,
          lambda itens: [['npm', 'install', '-g'] + [f'{n}@latest' for n, _, _ in itens]])
    if tem('pnpm'):
        f('pnpm', 'pacotes', 'pnpm (globais)', checa_pnpm, [['pnpm', 'update', '-g', '--latest']])
    f('pip', 'pacotes', 'pip', checa_pip,
      lambda itens: [[sys.executable, '-m', 'pip', 'install', '-U', '--disable-pip-version-check'] + [n for n, _, _ in itens]])
    if tem('pipx'):
        f('pipx', 'pacotes', 'pipx', checa_pipx, [['pipx', 'upgrade-all']])
    if tem('uv'):
        f('uv', 'pacotes', 'uv (ferramentas)', checa_uv, [['uv', 'tool', 'upgrade', '--all']])
    if tem('cargo-install-update'):
        f('cargo', 'pacotes', 'cargo (binários)', checa_cargo, [['cargo', 'install-update', '-a']])
    if tem('gh'):
        f('gh', 'pacotes', 'extensões do gh', checa_gh, [['gh', 'extension', 'upgrade', '--all']])

    for editor, nome, loja in (('code', 'VS Code', 'ms'), ('code-insiders', 'VS Code Insiders', 'ms'),
                               ('codium', 'VSCodium', 'ovsx'), ('cursor', 'Cursor', 'ovsx')):
        if tem(editor):
            f(editor, 'editores', nome, lambda e=editor, l=loja: checa_editor(e, l), _cmds_editor(editor))
    return F


def eh_admin():
    if os.name == 'nt':
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def _verifica(fonte):
    try:
        res = fonte['checa']()
    except Exception as e:  # um gerenciador quebrado não pode derrubar os outros
        return {'itens': None, 'nota': '', 'erro': corta(str(e) or type(e).__name__, 70)}
    nota = ''
    if isinstance(res, tuple):
        res, nota = res
    if res:
        # só versão estável; quem já está num beta continua recebendo os betas daquele pacote
        res = [(n, a, v) for n, a, v in res if eh_estavel(v) or (a and not eh_estavel(a))]
    return {'itens': res, 'nota': nota, 'erro': None}


def dica_de_falha(ultima, fonte):
    """Traduz as falhas mais comuns em o que fazer."""
    txt = (ultima or '').lower()
    if 'eacces' in txt or ('permission denied' in txt and fonte['id'] in ('npm', 'pnpm')):
        return ('o npm global está numa pasta do sistema: use um gerenciador de versões do Node (fnm, nvm, volta) '
                'ou rode com sudo')
    if 'externally-managed' in txt:
        return 'esse Python é do sistema: instale ferramentas com pipx ou uv, e pacotes de projeto num venv'
    if 'access is denied' in txt or 'requires elevation' in txt or 'administrator' in txt or 'acesso negado' in txt:
        return 'precisa do terminal aberto como administrador'
    if 'could not resolve' in txt or 'network' in txt or 'timed out' in txt or 'temporary failure' in txt:
        return 'falha de rede: confira a internet e rode de novo'
    if 'lock' in txt and ('dpkg' in txt or 'apt' in txt or 'held by' in txt):
        return 'outro programa está instalando pacotes agora (atualização automática?); espere terminar e rode de novo'
    return ''


def executa_vivo(cmd, log, pr, env=None):
    """Roda mostrando a última linha no progresso e guardando tudo no log."""
    log.write(f'\n$ {" ".join(str(c) for c in cmd)}\n')
    log.flush()
    try:
        p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env)
    except OSError as e:
        log.write(f'{e}\n')
        return 127, str(e)
    ultima = ''
    try:
        while True:
            bloco = p.stdout.read1(4096)
            if not bloco:
                break
            txt = texto(bloco)
            log.write(txt.replace('\r\n', '\n'))
            ultimas = [l.strip() for l in re.split(r'[\r\n]', txt) if l.strip()]
            if ultimas:
                ultima = ultimas[-1]
                if pr:
                    pr.atual = ultima
        return p.wait(), ultima
    finally:
        if p.poll() is None:
            p.kill()


def ferramenta_atualizar(t, args):
    escolha = {x.strip().lower() for x in (args.so or '').split(',') if x.strip()}
    pular = {x.strip().lower() for x in (args.pular if args.pular is not None else config('atualizar_pular', '')).split(',')
             if x.strip()}
    fontes = [f for f in fontes_do_pc() if (not escolha or f['id'] in escolha or f['grupo'] in escolha)
              and f['id'] not in pular and f['grupo'] not in pular]
    if not fontes:
        t.aviso('nenhum gerenciador encontrado' + (' com esse filtro.' if escolha or pular else '.'))
        return 1
    t.prompt('atualizar', ' · '.join(f['id'] for f in fontes))
    with Progresso(t, len(fontes), 'verificando') as pr:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futuros = {ex.submit(_verifica, f): f for f in fontes}
            for fut in as_completed(futuros):
                futuros[fut].update(fut.result())
                pr.avanca(futuros[fut]['nome'])

    admin = eh_admin()
    rel = Relatorio('atualizar')
    candidatas = []
    for grupo, titulo in GRUPOS_ATUALIZAR:
        do_grupo = [f for f in fontes if f['grupo'] == grupo]
        if not do_grupo:
            continue
        t.escreve()
        t.titulo(titulo)
        for f in do_grupo:
            itens = f['itens']
            if f['erro']:
                t.item('✗', 'vermelho', f['nome'], t.p(f['erro'], 'vermelho'), recuo=4)
                rel.add(f'{f["nome"]}: erro — {f["erro"]}')
                continue
            if itens is None:
                t.item('·', 'azul', f['nome'], t.p('atualiza sem conferir antes', 'apagado'), recuo=4)
                if f['nota']:
                    t.nota(corta(f['nota'], t.largura - 9), 8)
                candidatas.append(f)
                rel.add(f'{f["nome"]}: {f["nota"]}')
                continue
            if not itens:
                t.item('✓', 'verde', f['nome'], t.p('em dia', 'apagado'), recuo=4)
                if f['nota']:
                    t.nota(corta(f['nota'], t.largura - 9), 8)
                rel.add(f'{f["nome"]}: em dia' + (f' ({f["nota"]})' if f['nota'] else ''))
                continue
            n = len(itens)
            t.item('●', 'amarelo', f['nome'], t.p(pl(n, 'atualização', 'atualizações'), 'amarelo'), recuo=4)
            mostrar = itens if args.tudo else itens[:4]
            for nome, atual, novo in mostrar:
                seta = f'{atual} → {novo}' if atual else f'→ {novo}'
                major = subiu_major(atual, novo)
                cabe = t.largura - 10 - (8 if major else 0)
                seta = corta(seta, max(12, cabe - 8))
                linha = f'{corta(nome, max(6, cabe - len(seta) - 2))}  {seta}'
                t.escreve(' ' * 8 + t.p(linha, 'sub') + (t.p(' (major)', 'amarelo') if major else ''))
            if len(itens) > len(mostrar):
                t.paragrafo(f'e mais {len(itens) - len(mostrar)} (veja todas com --tudo)', 8, 'apagado')
            if f['nota']:
                t.nota(corta(f['nota'], t.largura - 9), 8)
            rel.add(f'{f["nome"]}: {n} atualizações', *[f'  {a} {b} -> {c}' for a, b, c in itens])
            if f['so_lista']:
                t.nota(corta(f'atualize com: {f["dica"]}', t.largura - 9), 8)
            elif f['admin'] and not admin:
                t.nota('precisa do terminal aberto como administrador', 8)
            else:
                candidatas.append(f)
    if any(f['itens'] and subiu_major(*x[1:]) for f in candidatas for x in f['itens'] or []):
        t.escreve()
        t.paragrafo('(major) = versão nova principal: pode mudar comandos ou opções. Leia as notas da versão '
                    'se algo deixar de funcionar.', 4, 'apagado')
    t.escreve()
    arq_rel = rel.salva()
    t.relatorio(arq_rel)

    pendentes = [f for f in candidatas if f['itens'] or f['itens'] is None]
    com_algo = [f for f in pendentes if f['itens']]
    if not com_algo and not any(f['itens'] is None for f in pendentes):
        t.escreve()
        t.ok('tudo em dia.')
        return 0
    if args.teste or args.listar:
        t.escreve()
        t.nota('    modo teste: nada foi atualizado.', 0)
        return 0

    # escolha
    t.escreve()
    t.titulo('o que atualizar')
    for i, f in enumerate(pendentes, 1):
        extra = pl(len(f['itens']), 'atualização', 'atualizações') if f['itens'] else 'sem conferir antes'
        nome = corta(f['nome'], 18)
        t.escreve(f'    {t.p(f"{i:>2}", "verde", True)}  {t.p(f"{nome:<18}", "texto")} {t.p(extra, "sub")}'
                  + (t.p('  sudo', 'pessego') if f['sudo'] and not admin else ''))
    if not args.sim and not t.interativo:
        t.nota('    sem terminal para perguntar: rode de novo com --sim para atualizar tudo.', 0)
        return 0
    escolhidas = pendentes
    if not args.sim:
        t.escreve()
        t.paragrafo('Enter = todos · números separados por espaço · 0 = nenhum', 2, 'apagado')
        resp = t.pergunta('atualizar').strip().lower()
        if resp in ('0', 'n', 'nao', 'não', 'nenhum'):
            return 0
        nums = [int(x) for x in re.findall(r'\d+', resp) if 0 < int(x) <= len(pendentes)]
        if nums:
            escolhidas = [pendentes[n - 1] for n in dict.fromkeys(nums)]

    # sudo pede a senha uma vez, antes, com o terminal livre; depois os comandos rodam com sudo -n
    usa_sudo = os.name != 'nt' and not admin and any(f['sudo'] for f in escolhidas)
    if usa_sudo:
        t.escreve()
        t.paragrafo('o sudo vai pedir a sua senha uma vez (para ' + ', '.join(f['nome'] for f in escolhidas if f['sudo']) + ')', 2, 'apagado')
        if subprocess.run(['sudo', '-v']).returncode != 0:
            t.aviso('sem a senha, pulo os que precisam de sudo.')
            escolhidas = [f for f in escolhidas if not f['sudo']]
    pasta = CASA / 'atualizar'
    pasta.mkdir(parents=True, exist_ok=True)
    arq_log = pasta / f'log-{carimbo()}.txt'
    resultados = []
    t.escreve()
    with open(arq_log, 'w', encoding='utf-8') as log, Progresso(t, len(escolhidas), 'atualizando') as pr:
        for f in escolhidas:
            pr.atual = f['nome']
            cmds = f['comandos'](f['itens'] or []) if callable(f['comandos']) else f['comandos']
            inicio, cod, ultima = time.time(), 0, ''
            for cmd in cmds:
                if f['sudo'] and not admin:
                    cmd = ['sudo', '-n'] + cmd
                cod, ultima = executa_vivo(cmd, log, pr, env=ENV_C if f['grupo'] == 'sistema' and os.name != 'nt' else None)
                if cod != 0:
                    break
            resultados.append((f, cod, time.time() - inicio, ultima))
            pr.avanca(f['nome'])
    t.titulo('resultado')
    for f, cod, dur, ultima in resultados:
        if cod == 0:
            t.item('✓', 'verde', f['nome'], t.p(f'{pl(len(f["itens"]), "pacote") if f["itens"] else "feito"} · {dur:.0f} s', 'sub'), recuo=4)
        else:
            # winget devolve código de erro quando um pacote só falha e os outros vão
            t.item('✗', 'vermelho', f['nome'], t.p(f'saiu com código {cod}', 'vermelho'), recuo=4)
            if ultima:
                t.nota(corta(ultima, t.largura - 9), 8)
            dica = dica_de_falha(ultima, f)
            if dica:
                t.paragrafo(dica, 8, 'amarelo')
    t.escreve()
    t.relatorio(arq_log, 'log')
    if Path('/var/run/reboot-required').exists():
        t.aviso('o sistema pede para reiniciar o computador.')
    if any(r[1] != 0 for r in resultados):
        t.paragrafo('Rode de novo para ver o que ficou pendente; no log está a saída completa de cada um.', 4, 'apagado')
        return 1
    return 0


# ███████████████████████████████████████████████████████████████████████████
#
#   PARTE 3 · MENU E ENTRADA
#   as duas partes e o perfil num menu só, e os comandos de linha
#
# ███████████████████████████████████████████████████████████████████████████


GRUPOS = [
    ('seus repositórios no GitHub', 'repos', [
        ('segredos', 'segredos.sh', 'chaves e senhas vazadas', 'ferramenta_segredos'),
        ('branches', 'branches.sh', 'apaga as já mescladas', 'ferramenta_branches'),
        ('demos', 'demos.sh', 'os sites estão no ar?', 'ferramenta_demos'),
        ('backup', 'backup.sh', 'cópia da branch principal', 'ferramenta_backup'),
        ('deps', 'deps.sh', 'falhas e versões velhas', 'ferramenta_deps'),
        ('coautores', 'coautores.sh', 'tira a coautoria do Claude', 'ferramenta_coautores'),
    ]),
    ('seu computador e seus sites', 'dev', [
        ('faxina', 'faxina.sh', 'libera espaço em disco', 'ferramenta_faxina'),
        ('portas', 'portas.sh', 'quem usa cada porta', 'ferramenta_portas'),
        ('raiox', 'raiox.sh', 'acessibilidade, SEO e mais', 'ferramenta_raiox'),
        ('peso', 'peso.sh', 'o que a página carrega', 'ferramenta_peso'),
        ('atualizar', 'atualizar.sh', 'atualiza tudo do PC', 'ferramenta_atualizar'),
    ]),
    ('perfil e configuração', 'conta', [
        ('login', 'login.sh', 'seu perfil e o login do GitHub', 'ferramenta_login'),
        ('config', 'config.sh', 'preferências da ferramenta', 'ferramenta_config'),
    ]),
]
FERRAMENTAS = [(cmd, arq, desc, funcao, grupo) for _, grupo, itens in GRUPOS for cmd, arq, desc, funcao in itens
               if funcao in globals()]
PRECISA = {'login': ('curl',), 'segredos': ('git', 'curl'), 'branches': ('curl',), 'demos': ('curl',), 'backup': ('git', 'curl'),
           'deps': ('curl',), 'coautores': ('git', 'curl'), 'raiox': ('curl',), 'peso': ('curl',)}


def _limpa(self):
    if self.tty:
        sys.stdout.write('\033[2J\033[H')


def _espera(self, txt):
    try:
        input(self._adapta('  ' + self.p(txt, 'apagado') + ' '))
    except EOFError:
        raise KeyboardInterrupt  # sem entrada (fim do pipe): sai do menu em vez de repetir para sempre


Terminal.limpa = _limpa
Terminal.espera = _espera


def roda_ferramenta(ctx, args, mostra_descricao=True):
    cmd, arquivo, desc, funcao, grupo = next(f for f in FERRAMENTAS if f[0] == args.comando)
    t = ctx.t
    if mostra_descricao:
        t.aba(arquivo, desc)
    for prog in PRECISA.get(cmd, ()):
        if not shutil.which(prog):
            t.erro(f'Essa ferramenta precisa do {prog} instalado.')
            t.fim('não rodou', 'erro')
            return 1
    inicio = time.time()
    try:
        if grupo in ('repos', 'conta'):
            ctx.args = args
            cod = globals()[funcao](ctx)
        else:
            cod = globals()[funcao](t, args)
    except KeyboardInterrupt:
        t.fim('interrompido', 'erro')
        return 130
    if grupo != 'conta':
        ctx.estado[cmd] = agora_iso()
        salva_estado(ctx.estado)
    dur = time.time() - inicio
    t.fim(('concluído em ' if not cod else 'terminou com pendências · ') + _duracao(dur), 'ok' if not cod else 'aviso')
    return cod or 0


def monta_parser():
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument('--ascii', action='store_true', help='só caracteres simples (terminal que mostra quadradinhos)')
    comum.add_argument('--sem-cor', action='store_true', help='sem cores')
    comum.add_argument('--teste', action='store_true', help='só mostra, não altera nada')
    comum.add_argument('--sim', action='store_true', help='não pede confirmação')
    # as mesmas opções depois do comando; SUPPRESS para não apagarem as que vieram antes dele
    depois = argparse.ArgumentParser(add_help=False)
    for nome in ('--ascii', '--sem-cor', '--teste', '--sim'):
        depois.add_argument(nome, action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    de_repos = argparse.ArgumentParser(add_help=False)
    de_repos.add_argument('repos', nargs='*', help='só esses repositórios (padrão: todos os seus)')
    de_repos.add_argument('--forks', action='store_true', help='inclui forks')
    de_repos.add_argument('--sem-login', action='store_true', help='não usa token; só o acesso que o git já tem')

    p = argparse.ArgumentParser(prog='ferramentas', parents=[comum],
                                description='Ferramentas para os seus repositórios, o seu computador e os seus sites. '
                                            'Sem comando, abre o menu.')
    sub = p.add_subparsers(dest='comando', metavar='comando')
    sub.add_parser('segredos', parents=[depois, de_repos], help='[GitHub] caça chaves e senhas no histórico')
    b = sub.add_parser('branches', parents=[depois, de_repos], help='[GitHub] apaga branches já mescladas')
    b.add_argument('--restaurar', metavar='ARQUIVO', help='recria as branches apagadas numa rodada anterior')
    sub.add_parser('demos', parents=[depois, de_repos], help='[GitHub] confere se os sites das demos estão no ar')
    bk = sub.add_parser('backup', parents=[depois, de_repos], help='[GitHub] baixa/atualiza a branch principal de todos')
    bk.add_argument('--destino', help='pasta do backup (padrão ~/backup-github; ele lembra da última)')
    sub.add_parser('deps', parents=[depois, de_repos], help='[GitHub] vulnerabilidades e dependências velhas')
    sub.add_parser('coautores', parents=[depois, de_repos], help='[GitHub] tira a coautoria do Claude do histórico')
    lg = sub.add_parser('login', parents=[depois], help='[perfil] seu perfil e o login do GitHub (ver, trocar, sair)')
    lg.add_argument('--trocar', action='store_true', help='cola um token novo no lugar do atual')
    lg.add_argument('--sair', action='store_true', help='apaga o token guardado pela ferramenta')
    cf = sub.add_parser('config', parents=[depois], help='[perfil] preferências (sem nada: mostra e deixa mudar)')
    cf.add_argument('chave', nargs='?', help='usuario, backup, cores, simbolos, dispositivo, faxina-dias, atualizar-pular')
    cf.add_argument('valor', nargs='?', help='valor novo (vazio volta ao padrão)')

    f = sub.add_parser('faxina', parents=[depois], help='[PC] libera espaço de projetos parados')
    f.add_argument('pastas', nargs='*', help='onde procurar (padrão: sua pasta pessoal)')
    f.add_argument('--dias', type=int, default=None, help='dias sem mexer para contar como parado (padrão 30, ou o da config)')
    po = sub.add_parser('portas', parents=[depois], help='[PC] quem está usando cada porta')
    po.add_argument('porta', nargs='?', type=int, help='mostra só essa porta e oferece encerrar')
    po.add_argument('--matar', action='store_true', help='encerra o processo da porta (pede confirmação)')
    po.add_argument('--livre', type=int, nargs='?', const=3000, metavar='DESDE',
                    help='próxima porta livre a partir de DESDE (padrão 3000)')
    po.add_argument('--todas', action='store_true', help='inclui as portas altas do sistema')
    rx = sub.add_parser('raiox', parents=[depois], help='[site] acessibilidade, SEO, desempenho e segurança')
    rx.add_argument('url', help='endereço do site (ex.: meusite.com.br ou localhost:5173)')
    rx.add_argument('--desktop', action='store_true', help='Lighthouse como computador (padrão: celular)')
    rx.add_argument('--rapido', action='store_true', help='sem o Lighthouse (só a análise própria, em segundos)')
    rx.add_argument('--paginas', type=int, default=0, metavar='N', help='analisa também N páginas internas')
    rx.add_argument('--tudo', action='store_true', help='mostra também o que passou e as sugestões')
    rx.add_argument('--json', metavar='ARQUIVO', help='salva o resultado completo em JSON')
    rx.add_argument('--copiar', action='store_true', help='copia o resumo para a IA na área de transferência')
    if 'ferramenta_peso' in globals():
        pe = sub.add_parser('peso', parents=[depois], help='[site] o que cada página carrega e o que mais pesa')
        pe.add_argument('url', help='endereço do site')
        pe.add_argument('--desktop', action='store_true', help='mede como computador (padrão: celular)')
        pe.add_argument('--rapido', action='store_true', help='sem o Lighthouse (medição própria, em segundos)')
        pe.add_argument('--paginas', type=int, default=0, metavar='N', help='mede também N páginas internas')
        pe.add_argument('--copiar', action='store_true', help='copia o resumo para a IA na área de transferência')
    if 'ferramenta_atualizar' in globals():
        at = sub.add_parser('atualizar', parents=[depois], help='[PC] atualiza sistema, linguagens, pacotes e extensões')
        at.add_argument('--so', metavar='LISTA', help='só esses grupos ou ferramentas (ex.: npm,pip,winget)')
        at.add_argument('--pular', metavar='LISTA', help='menos esses grupos ou ferramentas (ex.: pip,editores)')
        at.add_argument('--listar', action='store_true', help='só lista o que tem atualização (igual a --teste)')
        at.add_argument('--tudo', action='store_true', help='mostra todos os pacotes, não só os quatro primeiros')
    return p


def menu(ctx, parser, args):
    t = ctx.t
    nomes = [f[0] for f in FERRAMENTAS]
    aviso = ''
    while True:
        t.limpa()
        t.logo()
        t.cabecalho('início', f'{len(FERRAMENTAS)} comandos')
        num, por_numero = 0, {}
        for titulo_grupo, grupo, _ in GRUPOS:
            itens = [f for f in FERRAMENTAS if f[4] == grupo]
            if not itens:
                continue
            t.titulo(titulo_grupo)
            for cmd, _, desc, _, _ in itens:
                num += 1
                por_numero[str(num)] = cmd
                quando = ha_quanto_iso(ctx.estado.get(cmd, '')) if grupo != 'conta' else ''
                esq = f'  {t.p(f"{num:>2}", "verde", True)}  {t.p(f"{cmd:<10}", "texto")} {t.p(corta(desc, t.largura - 17), "sub")}'
                if quando and vlen(esq) + len(quando) + 2 <= t.largura:
                    esq += ' ' * (t.largura - vlen(esq) - len(quando)) + t.p(quando, 'apagado')
                t.escreve(esq)
            t.escreve()
        t.escreve(f'  {t.p(" 0", "apagado", True)}  {t.p("sair", "apagado")}')
        t.escreve()
        if aviso:
            t.aviso(aviso)
            aviso = ''
        escolha = t.pergunta('número ou nome').strip().lower()
        if escolha in ('', '0', 'q', 'sair'):
            t.fim('até mais', 'nada')
            return 0
        cmd = por_numero.get(escolha) or (escolha if escolha in nomes else None)
        if not cmd:
            aviso = f'"{corta(escolha, 20)}" não é uma das opções.'
            continue
        _, arquivo, desc, _, grupo = next(f for f in FERRAMENTAS if f[0] == cmd)
        t.limpa()
        t.cabecalho(cmd)
        t.aba(arquivo, desc)
        extra = []
        if grupo == 'repos':
            t.paragrafo('Enter = todos os repositórios, ou digite os nomes separados por espaço', 2, 'apagado')
            extra = t.pergunta('repositórios').split()
            if cmd in ('branches', 'coautores'):
                t.paragrafo('só simular primeiro, sem alterar nada? s = sim, Enter = não', 2, 'apagado')
                if t.pergunta('simular').strip().lower() in ('s', 'sim'):
                    extra.append('--teste')
            t.escreve()
        elif cmd in ('raiox', 'peso'):
            t.paragrafo('endereço do site (ex.: meusite.com.br ou localhost:5173); Enter = voltar', 2, 'apagado')
            endereco = t.pergunta('endereço').strip()
            if not endereco:
                continue
            extra = [endereco]
            t.escreve()
        try:
            # nome com "-" na frente seria lido como opção, e o argparse encerraria o programa inteiro
            sub_args = parser.parse_args([cmd] + ['--'] + extra if extra and grupo == 'repos' else [cmd] + extra)
        except SystemExit:
            t.fim('não entendi o que foi digitado', 'aviso')
            t.espera('Enter para voltar ao menu')
            continue
        for k in ('ascii', 'sem_cor', 'teste', 'sim'):
            if getattr(args, k, False):
                setattr(sub_args, k, True)
        roda_ferramenta(ctx, sub_args, mostra_descricao=False)
        t.escreve(guia=False)
        try:
            t.espera('Enter para voltar ao menu')
        except KeyboardInterrupt:
            return 130


def main():
    parser = monta_parser()
    args = parser.parse_args()
    # preferências da config valem como se as opções tivessem sido digitadas
    args.ascii = args.ascii or config('simbolos') == 'simples'
    args.sem_cor = args.sem_cor or config('cores') == 'sem cor'
    t = Terminal(args.ascii, args.sem_cor)
    ctx = Ctx(args, t)
    try:
        if args.comando:
            t.cabecalho(args.comando)
            return roda_ferramenta(ctx, args)
        return menu(ctx, parser, args)
    except KeyboardInterrupt:
        t.fim('interrompido', 'erro')
        t.escreve(guia=False)
        return 130
    except BrokenPipeError:
        # saída num pipe que fechou antes (ex.: "| head"): sai quieto, sem rastro de erro
        try:
            sys.stdout = open(os.devnull, 'w')
        except OSError:
            pass
        return 0


if __name__ == '__main__':
    sys.exit(main())
