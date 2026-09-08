import cairosvg, os

ROXO = "#6B4EE6"
AMBAR = "#FFC94D"
BRANCO = "#FFFFFF"

def conteudo(escala=1.0):
    cx, cy = 256, 256
    barras = [(110, 112), (158, 176), (206, 84), (254, 144)]
    linha = (302, 100)
    p = []
    for x, h in barras:
        nx = cx + (x - cx) * escala
        nh = h * escala
        nw = 26 * escala
        p.append(f'<rect x="{nx:.1f}" y="{cy - nh/2:.1f}" width="{nw:.1f}" height="{nh:.1f}" rx="{nw/2:.1f}" fill="{BRANCO}"/>')
    lx = cx + (linha[0] - cx) * escala
    lw = linha[1] * escala
    lh = 26 * escala
    p.append(f'<rect x="{lx:.1f}" y="{cy - lh/2:.1f}" width="{lw:.1f}" height="{lh:.1f}" rx="{lh/2:.1f}" fill="{AMBAR}"/>')
    return "\n  ".join(p)

def svg(rx=112, escala=1.0, fundo=ROXO):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img">
  <title>Decifra Pro</title>
  <desc>Onda sonora que se transforma em uma linha de texto.</desc>
  <rect width="512" height="512" rx="{rx}" fill="{fundo}"/>
  {conteudo(escala)}
</svg>'''

open("icon.svg", "w").write(svg())
open("icon-maskable.svg", "w").write(svg(rx=0, escala=0.78))
open("apple-touch.svg", "w").write(svg(rx=0))

alvos = [
    ("icon.svg", "icon-192.png", 192),
    ("icon.svg", "icon-512.png", 512),
    ("icon.svg", "favicon-32.png", 32),
    ("icon-maskable.svg", "maskable-512.png", 512),
    ("apple-touch.svg", "apple-touch-icon.png", 180),
]
for src, dst, tam in alvos:
    cairosvg.svg2png(url=src, write_to=dst, output_width=tam, output_height=tam)

from PIL import Image
img = Image.open("favicon-32.png")
img.save("favicon.ico", sizes=[(16,16),(32,32),(48,48)])
os.remove("favicon-32.png")
os.remove("apple-touch.svg")
print("\n".join(sorted(os.listdir("."))))
