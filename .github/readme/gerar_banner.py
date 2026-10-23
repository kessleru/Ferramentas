#!/usr/bin/env python3
# Gera .github/readme/banner.svg no mesmo molde do banner do Portfolio-kessleru.
#   python .github/readme/gerar_banner.py
from pathlib import Path

MONO = "ui-monospace,'Cascadia Code',Consolas,monospace"
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
PALETA = ['#f5e0dc', '#f2cdcd', '#f5c2e7', '#cba6f7', '#f38ba8', '#eba0ac', '#fab387',
          '#f9e2af', '#a6e3a1', '#94e2d5', '#89dceb', '#74c7ec', '#89b4fa', '#b4befe']

# a mesma fonte de 3x5 "pixels" do logo do terminal
LETRAS = {
    '<': ['..#', '.#.', '#..', '.#.', '..#'], '/': ['..#', '..#', '.#.', '#..', '#..'],
    '>': ['#..', '.#.', '..#', '.#.', '#..'], 'K': ['#.#', '#.#', '##.', '#.#', '#.#'],
    'E': ['###', '#..', '##.', '#..', '###'], 'S': ['###', '#..', '###', '..#', '###'],
    'L': ['#..', '#..', '#..', '#..', '###'], 'R': ['##.', '#.#', '##.', '#.#', '#.#'],
    'U': ['#.#', '#.#', '#.#', '#.#', '###'],
}


def logo(x, y, px):
    rects, cx = [], x
    for i, ch in enumerate('</> KESSLERU'):
        if ch == ' ':
            cx += px * 2
            continue
        cor = '#c6d0f5' if i < 3 else '#a6d189'
        for linha, bits in enumerate(LETRAS[ch]):
            for col, b in enumerate(bits):
                if b == '#':
                    rects.append(f'<rect x="{cx + col * px}" y="{y + linha * px}" width="{px}" height="{px}" fill="{cor}"/>')
        cx += px * 4
    return ''.join(rects)


def janela(x, y, fundo, barra, borda, apagado, destaque, texto, titulo, pasta, linhas, extra=''):
    corpo = []
    for dy, partes in linhas:
        spans = ''.join(f'<tspan fill="{c}">{t}</tspan>' for c, t in partes)
        corpo.append(f'<text x="14" y="{dy}">{spans}</text>')
    return f'''
  <g transform="translate({x},{y})" filter="url(#sombra)">
    <rect width="320" height="178" rx="12" fill="{fundo}" stroke="{borda}" stroke-opacity=".35"/>
    <path d="M0 12a12 12 0 0 1 12-12h296a12 12 0 0 1 12 12v16H0z" fill="{barra}"/>
    <circle cx="16" cy="14" r="4" fill="#f38ba8"/><circle cx="30" cy="14" r="4" fill="#f9e2af"/><circle cx="44" cy="14" r="4" fill="#a6e3a1"/>
    <text x="160" y="18" text-anchor="middle" font-family="{MONO}" font-size="9" fill="{apagado}">{titulo}</text>
    <text x="14" y="46" font-family="{MONO}" font-size="13" fill="{destaque}">~/{pasta}/<tspan fill="{destaque}">▌</tspan></text>
    {extra}
    <g font-family="{MONO}" font-size="11.5" fill="{texto}">{''.join(corpo)}</g>
  </g>'''


def banner():
    atras1 = janela(690, 26, '#232634', '#1e2030', '#626880', '#737994', '#e78284', '#c6d0f5',
                    'segredos.sh', 'segredos', [
                        (78, [('#e78284', '✗ CRÍTICO '), ('#c6d0f5', 'Token do GitHub')]),
                        (96, [('#a5adce', '  config.js:12 · ghp_…a9')]),
                        (120, [('#e5c890', '! MÉDIO   '), ('#c6d0f5', 'Token JWT')]),
                        (138, [('#a5adce', '  api/auth.ts:8 · eyJh…Kc')])])
    atras2 = janela(732, 70, '#292c3c', '#232634', '#626880', '#737994', '#ca9ee6', '#c6d0f5',
                    'branches.sh', 'branches', [
                        (78, [('#a6d189', '✓ '), ('#c6d0f5', 'feat/login  '), ('#838ba7', 'PR #12 mesclado')]),
                        (96, [('#a6d189', '✓ '), ('#c6d0f5', 'fix/menu    '), ('#838ba7', 'já está na main')]),
                        (114, [('#838ba7', '· '), ('#a5adce', 'wip/ideias  '), ('#838ba7', '3 commits fora')]),
                        (138, [('#ca9ee6', '> '), ('#c6d0f5', '2 podem ser apagadas')])])
    atras3 = janela(774, 114, '#2c2f40', '#262938', '#626880', '#737994', '#8caaee', '#c6d0f5',
                    'backup.sh', 'backup', [
                        (78, [('#a6d189', '+ '), ('#c6d0f5', 'Animais-Web  '), ('#838ba7', 'baixado')]),
                        (96, [('#a6d189', '↑ '), ('#c6d0f5', 'Forest-Web   '), ('#838ba7', '+2 commits')]),
                        (114, [('#838ba7', '✓ '), ('#a5adce', 'Portfolio    '), ('#838ba7', 'em dia')]),
                        (138, [('#8caaee', '> '), ('#c6d0f5', '113 MB em ~/backup-github')])])
    frente = janela(816, 158, '#303446', '#292c3c', '#737994', '#838ba7', '#a6d189', '#c6d0f5',
                    'ferramentas-git', 'início', [
                        (126, [('#a6d189', '> '), ('#c6d0f5', 'Olá! O que vamos fazer hoje?')]),
                        (148, [('#a6d189', '1 '), ('#c6d0f5', 'segredos  '), ('#a6d189', '2 '), ('#c6d0f5', 'branches')]),
                        (166, [('#a6d189', '3 '), ('#c6d0f5', 'demos     '), ('#a6d189', '4 '), ('#c6d0f5', 'backup  '),
                               ('#838ba7', '…')])],
                    extra=logo(14, 66, 4))
    bolinhas = ''.join(f'<circle cx="{i * 22}" cy="0" r="7" fill="{c}"/>' for i, c in enumerate(PALETA))
    etiquetas = [('6 ferramentas', '#a6e3a1', 'rgba(166,227,161,.14)'),
                 ('qualquer terminal', '#cba6f7', 'rgba(203,166,247,.16)'),
                 ('nada muda sem SIM', '#89b4fa', 'rgba(137,180,250,.16)')]
    pilulas, x = [], 74
    for txt, cor, fundo in etiquetas:
        larg = 40 + int(len(txt) * 7.9)
        pilulas.append(f'<rect x="{x}" y="262" width="{larg}" height="32" rx="16" fill="{fundo}"/>'
                       f'<circle cx="{x + 20}" cy="278" r="4" fill="{cor}"/><text x="{x + 32}" y="283" fill="{cor}">{txt}</text>')
        x += larg + 10
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="380" viewBox="0 0 1200 380" role="img" aria-label="ferramentas-git — seis ferramentas para todos os seus repositórios do GitHub">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#11111b"/>
      <stop offset="100%" stop-color="#313244"/>
    </linearGradient>
    <filter id="sombra" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#000000" flood-opacity=".28"/>
    </filter>
    <clipPath id="moldura"><rect width="1200" height="380" rx="24"/></clipPath>
  </defs>

  <rect width="1200" height="380" rx="24" fill="url(#bg)"/>
  <circle cx="1105" cy="60" r="190" fill="#a6e3a1" opacity="0.06"/>
  <circle cx="110" cy="360" r="150" fill="#a6e3a1" opacity="0.048"/>
  <g clip-path="url(#moldura)">{atras1}{atras2}{atras3}{frente}
  <g transform="translate(74,330)">{bolinhas}</g>
  </g>

  <text x="72" y="148" font-family="{SANS}" font-size="44" font-weight="800" letter-spacing="-1" fill="#cdd6f4">ferramentas-git</text>
  <text x="74" y="196" font-family="{SANS}" font-size="24" font-weight="600" fill="#cdd6f4">Seis ferramentas para todos os seus repos</text>
  <text x="74" y="232" font-family="{SANS}" font-size="17" fill="#a6adc8">Python · git · curl · zero dependências</text>

  <g font-family="{SANS}" font-size="14" font-weight="600">{''.join(pilulas)}</g>
</svg>
'''


if __name__ == '__main__':
    destino = Path(__file__).with_name('banner.svg')
    destino.write_text(banner(), encoding='utf-8')
    print(f'gerado: {destino}')
