from io import BytesIO
from PIL import Image,ImageOps
LAYOUTS={2:(2,1),3:(3,1),4:(2,2),5:(3,2),6:(3,2),7:(4,2),8:(4,2)}
def create_collage(raws,cell=(900,700),quality=85):
    n=len(raws)
    if n<2 or n>8:raise ValueError("2-8 images required")
    cols,rows=LAYOUTS[n];canvas=Image.new("RGB",(cols*cell[0],rows*cell[1]),"white");imgs=[]
    for raw in raws:
        im=ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB");imgs.append(ImageOps.fit(im,cell,method=Image.Resampling.LANCZOS))
    if n in (5,7):
        for i,im in enumerate(imgs[:cols]):canvas.paste(im,(i*cell[0],0))
        rest=imgs[cols:];off=int((cols-len(rest))*cell[0]/2)
        for i,im in enumerate(rest):canvas.paste(im,(off+i*cell[0],cell[1]))
    else:
        for i,im in enumerate(imgs):canvas.paste(im,((i%cols)*cell[0],(i//cols)*cell[1]))
    out=BytesIO();canvas.save(out,"JPEG",quality=quality,optimize=True,progressive=True);return out.getvalue()
