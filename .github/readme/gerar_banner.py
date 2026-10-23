#!/usr/bin/env python3
# Gera .github/readme/banner.svg: uma janela de terminal com a saída no estilo neofetch.
#   python .github/readme/gerar_banner.py
from html import escape
from pathlib import Path

MONO = "ui-monospace,'Cascadia Code','JetBrains Mono',Menlo,Consolas,'DejaVu Sans Mono',monospace"
C = {  # Catppuccin Mocha
    'crust': '#11111b', 'mantle': '#181825', 'base': '#1e1e2e', 'surface0': '#313244', 'surface1': '#45475a',
    'overlay0': '#6c7086', 'overlay1': '#7f849c', 'subtext0': '#a6adc8', 'text': '#cdd6f4',
    'green': '#a6e3a1', 'mauve': '#cba6f7', 'blue': '#89b4fa', 'red': '#f38ba8', 'yellow': '#f9e2af',
    'peach': '#fab387', 'teal': '#94e2d5', 'pink': '#f5c2e7', 'sky': '#89dceb', 'lavender': '#b4befe',
}

# fonte de 3x5 "pixels", a mesma do logo que aparece no terminal
LETRAS = {
    '<': ['..#', '.#.', '#..', '.#.', '..#'], '/': ['..#', '..#', '.#.', '#..', '#..'],
    '>': ['#..', '.#.', '..#', '.#.', '#..'], 'K': ['#.#', '#.#', '##.', '#.#', '#.#'],
    'E': ['###', '#..', '##.', '#..', '###'], 'S': ['###', '#..', '###', '..#', '###'],
    'L': ['#..', '#..', '#..', '#..', '###'], 'R': ['##.', '#.#', '##.', '#.#', '#.#'],
    'U': ['#.#', '#.#', '#.#', '#.#', '###'],
}


def pixels(texto, x, y, px, cores):
    rects, cx = [], x
    for i, ch in enumerate(texto):
        for linha, bits in enumerate(LETRAS[ch]):
            for col, b in enumerate(bits):
                if b == '#':
                    rects.append(f'<rect x="{cx + col * px}" y="{y + linha * px}" width="{px - 1}" height="{px - 1}" '
                                 f'rx="1" fill="{cores[i % len(cores)]}"/>')
        cx += px * 4
    return ''.join(rects)


def linha(x, y, partes, tamanho=17, peso=None):
    spans = ''.join(f'<tspan fill="{C[c]}"{" font-weight=" + chr(34) + "700" + chr(34) if b else ""}>{escape(t)}</tspan>'
                    for c, t, b in partes)
    return f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{tamanho}" xml:space="preserve">{spans}</text>'


def banner():
    W, H = 1200, 380
    partes = []

    # moldura, barra de abas e controles
    partes.append(f'<rect width="{W}" height="{H}" rx="14" fill="{C["crust"]}"/>')
    partes.append(f'<path d="M0 14a14 14 0 0 1 14-14h{W - 28}a14 14 0 0 1 14 14v26H0z" fill="{C["mantle"]}"/>')
    partes.append(f'<path d="M14 40v-28a6 6 0 0 1 6-6h214a6 6 0 0 1 6 6v28z" fill="{C["base"]}"/>')
    partes.append(f'<rect x="20" y="38" width="214" height="2" fill="{C["green"]}"/>')
    partes.append(linha(34, 28, [('green', '▸ ', False), ('text', 'ferramentas-git', False)], 14))
    partes.append(linha(258, 28, [('overlay0', 'zsh', False)], 14))
    partes.append(linha(304, 28, [('overlay0', '+', False)], 15))
    partes.append(linha(W - 104, 28, [('overlay1', '─   □   ✕', False)], 14))
    partes.append(f'<rect x="0" y="40" width="{W}" height="{H - 76}" fill="{C["base"]}"/>')

    # comando
    partes.append(linha(48, 84, [('green', 'kessleru@github', True), ('overlay1', ':', False), ('blue', '~', True),
                                 ('overlay1', '$ ', False), ('text', 'python ferramentas-git.py', False)]))

    # "logo" do neofetch: </> grande e o nome embaixo
    partes.append(pixels('</>', 56, 118, 17, [C['mauve'], C['green'], C['mauve']]))
    partes.append(pixels('KESSLERU', 56, 222, 6, [C['green']]))

    # informações do neofetch
    x = 300
    partes.append(linha(x, 130, [('green', 'ferramentas-git', True), ('overlay1', '@', False), ('mauve', 'kessleru', True)], 30))
    partes.append(f'<rect x="{x}" y="144" width="432" height="2" fill="{C["surface1"]}"/>')
    infos = [
        ('mauve', 'comandos  ', 'segredos · branches · demos · backup · deps · coautores'),
        ('blue', 'requisitos', 'Python 3.8+ · git · curl'),
        ('peach', 'instalação', 'nenhuma, é um arquivo só'),
        ('teal', 'terminais ', 'Windows · macOS · Linux · 16, 256 ou 24 bits'),
        ('red', 'segurança ', 'nada é apagado sem você digitar SIM'),
    ]
    for i, (cor, chave, valor) in enumerate(infos):
        partes.append(linha(x, 178 + i * 27, [(cor, chave, True), ('overlay0', ' ', False), ('text', valor, False)]))

    # os quadradinhos de cor que o neofetch imprime no fim
    for i, cor in enumerate(['surface1', 'red', 'green', 'yellow', 'blue', 'pink', 'teal', 'subtext0']):
        partes.append(f'<rect x="{x + i * 30}" y="318" width="30" height="18" fill="{C[cor]}"/>')

    # prompt de novo, com cursor piscando
    partes.append(linha(56, 300, [('green', '$ ', True)]))
    partes.append(f'<rect x="76" y="286" width="10" height="18" fill="{C["text"]}">'
                  '<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>')

    # barra de status no estilo tmux
    y = H - 36
    partes.append(f'<path d="M0 {y}h{W}v22a14 14 0 0 1-14 14H14A14 14 0 0 1 0 {H - 14}z" fill="{C["mantle"]}"/>')
    partes.append(f'<path d="M0 {y}h176l12 18-12 18H14A14 14 0 0 1 0 {H - 14}z" fill="{C["green"]}"/>')
    partes.append(linha(18, y + 23, [('crust', ' ferramentas-git', True)], 14))
    partes.append(linha(206, y + 23, [('subtext0', '0:zsh*  1:segredos  2:backup', False)], 14))
    partes.append(f'<path d="M{W - 320} {y}h320v22a14 14 0 0 1-14 14H{W - 320}l-12-18z" fill="{C["surface0"]}"/>')
    partes.append(linha(W - 306, y + 23, [('mauve', ' git:main ', False), ('overlay1', '│', False),
                                          ('text', ' utf-8 ', False), ('overlay1', '│', False), ('green', ' 6 ferramentas', False)], 14))

    # linhas de varredura de monitor antigo, bem fracas
    fundo = (f'<defs><pattern id="crt" width="4" height="4" patternUnits="userSpaceOnUse">'
             f'<rect width="4" height="1" fill="#ffffff" opacity=".022"/></pattern>'
             f'<radialGradient id="brilho" cx=".18" cy=".45" r=".6"><stop offset="0" stop-color="{C["green"]}" stop-opacity=".07"/>'
             f'<stop offset="1" stop-color="{C["green"]}" stop-opacity="0"/></radialGradient>'
             f'<clipPath id="moldura"><rect width="{W}" height="{H}" rx="14"/></clipPath></defs>')
    sobre = (f'<rect x="0" y="40" width="{W}" height="{H - 76}" fill="url(#brilho)"/>'
             f'<rect x="0" y="40" width="{W}" height="{H - 76}" fill="url(#crt)"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="ferramentas-git: janela de terminal com o logo e a lista das seis ferramentas">'
            f'{fundo}<g clip-path="url(#moldura)">{"".join(partes[:9])}{sobre}{"".join(partes[9:])}'
            f'<rect width="{W}" height="{H}" rx="14" fill="none" stroke="{C["surface0"]}" stroke-width="2"/></g></svg>\n')


if __name__ == '__main__':
    destino = Path(__file__).with_name('banner.svg')
    destino.write_text(banner(), encoding='utf-8')
    print(f'gerado: {destino}')
