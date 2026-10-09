from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageOps

p=Path(__file__).resolve().parent
files=['Hanui-Relay-4min.pdf','Hanui-Relay-10min.pdf']
docs=[fitz.open(p/f) for f in files]
rows=sum((len(d)+3)//4 for d in docs)
out=Image.new('RGB',(1600,rows*250),'#dce2de')
draw=ImageDraw.Draw(out)
row=0
for f,doc in zip(files,docs):
    for i,page in enumerate(doc):
        pix=page.get_pixmap(matrix=fitz.Matrix(.42,.42),alpha=False)
        im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        im=ImageOps.contain(im,(385,215))
        x=(i%4)*400; y=(row+i//4)*250
        out.paste(im,(x,y))
        draw.text((x+5,y+220),f'{f} · {i+1}',fill='#182a20')
    row+=(len(doc)+3)//4
out.save(p/'contact-sheet.png')
print([(f,len(d)) for f,d in zip(files,docs)])
