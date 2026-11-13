import sys
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
def setfont(st,ea,lat,size,bold=None):
    st.font.name=lat; st.font.size=Pt(size)
    if bold is not None: st.font.bold=bold
    rpr=st.element.get_or_add_rPr(); rf=rpr.find(qn('w:rFonts'))
    if rf is None: rf=rpr.makeelement(qn('w:rFonts'),{}); rpr.append(rf)
    for a in ('w:ascii','w:hAnsi','w:cs'): rf.set(qn(a),lat)
    rf.set(qn('w:eastAsia'),ea)
    for a in ('w:asciiTheme','w:hAnsiTheme','w:eastAsiaTheme','w:cstheme'):
        if rf.get(qn(a)) is not None: del rf.attrib[qn(a)]
    st.font.color.rgb=None
mode,src,dst=sys.argv[1:4]
d=Document(src)
S=d.styles
for n in ['Normal','Body Text','First Paragraph','Compact','Block Text','Table','Source Code']:
    try: st=S[n]
    except KeyError: continue
    setfont(st,'宋体','Times New Roman',12 if n!='Table' else 10.5)
    pf=st.paragraph_format; pf.line_spacing=1.5
    if n in ('Body Text','First Paragraph'): pf.first_line_indent=Pt(24); pf.space_before=Pt(0); pf.space_after=Pt(0)
for n,sz in [('Title',18),('Heading 1',16),('Heading 2',14),('Heading 3',12),('Heading 4',12)]:
    try: st=S[n]
    except KeyError: continue
    setfont(st,'黑体','Times New Roman',sz,True)
    st.paragraph_format.line_spacing=1.5; st.paragraph_format.space_before=Pt(12); st.paragraph_format.space_after=Pt(6)
    if n in ('Title','Heading 1'): st.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.CENTER
for n in ['Caption','Image Caption','Table Caption']:
    try: st=S[n]; setfont(st,'宋体','Times New Roman',10.5,False); st.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.CENTER; st.font.italic=False
    except KeyError: pass
if mode=='out':
    for p in d.paragraphs:
        if p.text.startswith('图') and p.style.name in ('Image Caption','Caption'): p.alignment=WD_ALIGN_PARAGRAPH.CENTER
d.save(dst)
if mode=='out':
    from docx.shared import Twips
    import re
    d=Document(dst)
    try:
        c=d.styles['Compact']; c.paragraph_format.line_spacing=1.15; c.paragraph_format.first_line_indent=Pt(0); c.font.size=Pt(10.5)
    except KeyError: pass
    total=9000
    for t in d.tables:
        tbl=t._tbl; pr=tbl.tblPr
        for e in pr.findall(qn('w:tblLayout')): pr.remove(e)
        ncol=len(t.columns)
        L=[0]*ncol
        for r in t.rows:
            for j,cell in enumerate(r.cells[:ncol]):
                for p in cell.paragraphs:
                    p.paragraph_format.first_line_indent=Pt(0)
                    for run in p.runs: run.font.size=Pt(10.5)
                n=sum(2 if ord(ch)>0x2e80 else 1 for ch in cell.text)
                L[j]=max(L[j],min(n,60))
        L=[max(x,6)**0.8 for x in L]; s=sum(L)
        ws=[int(total*x/s) for x in L]
        grid=tbl.tblGrid
        for gc,w in zip(grid.findall(qn('w:gridCol')),ws): gc.set(qn('w:w'),str(w))
        for r in t.rows:
            for j,cell in enumerate(r.cells[:ncol]): cell.width=Twips(ws[j])
        tw=pr.find(qn('w:tblW'))
        if tw is not None: tw.set(qn('w:type'),'dxa'); tw.set(qn('w:w'),str(total))
    d.save(dst)
