# Build ZJNU 2025 template-formatted thesis from the pandoc draft docx.
import zipfile, re, copy, sys
from lxml import etree
P='/workspace/thesis/paper'
SRC=f'{P}/thesis_draft_ch1-4.docx'
OUT=f'{P}/thesis_zjnu_v1.docx'
DISC=f'{P}/discrepancy_list.docx'
LOGO='/tmp/cv/x/word/media/image1.png'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'm':'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic':'http://schemas.openxmlformats.org/drawingml/2006/picture'}
W='{%s}'%NS['w']; Mq='{%s}'%NS['m']
DECL=' '.join(f'xmlns:{k}="{v}"' for k,v in NS.items())
def X(s):  # parse fragment(s)
    root=etree.fromstring(f'<root {DECL}>{s}</root>')
    return list(root)
def esc(t): return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
zin=zipfile.ZipFile(SRC); parts={n:zin.read(n) for n in zin.namelist()}
doc=etree.fromstring(parts['word/document.xml']); body=doc.find(W+'body')
def ptext(p): return ''.join(t.text or '' for t in p.iter(W+'t'))
def pstyle(p):
    s=p.find(f'{W}pPr/{W}pStyle'); return s.get(W+'val') if s is not None else None
kids=[k for k in body if k.tag!=W+'sectPr']
i1=next(i for i,k in enumerate(kids) if k.tag==W+'p' and pstyle(k)=='Heading1' and ptext(k).startswith('第1章'))
iD=next(i for i,k in enumerate(kids) if k.tag==W+'p' and pstyle(k)=='Heading1' and ptext(k).startswith('附：规范歧义'))
front_draft=kids[:i1]; main=kids[i1:iD]; disc=kids[iD:]
for k in kids: body.remove(k)
oldsect=body.find(W+'sectPr'); body.remove(oldsect)
HL='<w:highlight w:val="yellow"/>'
# ---------------------------------------------------------------- helpers
def run(t,rpr=''):
    return f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{esc(t)}</w:t></w:r>'
def para(content,style=None,ppr=''):
    st=f'<w:pStyle w:val="{style}"/>' if style else ''
    return f'<w:p><w:pPr>{st}{ppr}</w:pPr>{content}</w:p>'
def set_ppr(p,style=None,extra=None,keep=('numPr',)):
    ppr=p.find(W+'pPr')
    if ppr is None: ppr=etree.SubElement(p,W+'pPr'); p.remove(ppr); p.insert(0,ppr)
    for c in list(ppr):
        if c.tag.split('}')[1] not in keep: ppr.remove(c)
    if style:
        s=etree.Element(W+'pStyle'); s.set(W+'val',style); ppr.insert(0,s)
    if extra:
        for e in X(extra): ppr.append(e)
    return ppr
# ---------------------------------------------------------------- body transforms
report={'eq_numbered':0,'eq_unnumbered':0,'cites':0,'lists':0,'captions':[]}
FIGTAB=re.compile(r'(图|表|算法)\s?(\d+)-(\d+)')
def fix_text_nodes(el):
    for t in el.iter(W+'t'):
        if t.text:
            t.text=FIGTAB.sub(lambda m:f'{m.group(1)}{m.group(2)}.{m.group(3)}',t.text)
            t.text=t.text.replace('见文末“附：规范歧义与代码—规范差异清单”','见另附《规范歧义与代码—规范差异清单》（discrepancy_list.docx）')
    for d in el.iter('{%s}docPr'%NS['wp']):
        if d.get('descr'): d.set('descr',FIGTAB.sub(lambda m:f'{m.group(1)}{m.group(2)}.{m.group(3)}',d.get('descr')))
CITE=re.compile(r'\[\d+(?:[,，\-–]\d+)*\]')
def superscript_cites(p):
    for r in list(p.iter(W+'r')):
        if r.getparent().tag.startswith(Mq): continue
        ts=r.findall(W+'t')
        if len(ts)!=1 or not CITE.search(ts[0].text or ''): continue
        txt=ts[0].text; rpr=r.find(W+'rPr'); parent=r.getparent(); idx=parent.index(r)
        pieces=[]; pos=0
        for m in CITE.finditer(txt):
            if m.start()>pos: pieces.append((txt[pos:m.start()],False))
            pieces.append((m.group(0),True)); pos=m.end()
        if pos<len(txt): pieces.append((txt[pos:],False))
        parent.remove(r)
        for j,(s,sup) in enumerate(pieces):
            nr=etree.Element(W+'r'); np_=copy.deepcopy(rpr) if rpr is not None else etree.Element(W+'rPr')
            if sup:
                v=etree.SubElement(np_,W+'vertAlign'); v.set(W+'val','superscript'); report['cites']+=1
            nr.append(np_); t=etree.SubElement(nr,W+'t'); t.text=s; t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            parent.insert(idx+j,nr)
SPACE=re.compile(r'^[\s\u2000-\u200b\u3000]*$')
def strip_eqnum(omp):
    """remove trailing '(x.y)' from last oMath; return number string or None"""
    om=omp.findall(Mq+'oMath')[-1]; ch=list(om)
    def rt(e): return ''.join(t.text or '' for t in e.iter(Mq+'t')) if e.tag==Mq+'r' else None
    if len(ch)>=3 and rt(ch[-3])=='(' and rt(ch[-1])==')' and re.fullmatch(r'\d+\.\d+',rt(ch[-2]) or ''):
        num=rt(ch[-2])
        for e in ch[-3:]: om.remove(e)
        while len(om) and rt(om[-1]) is not None and SPACE.match(rt(om[-1])): om.remove(om[-1])
        return num
    return None
TXT_W=8787
def eq_table(omp,num):
    w1,w3=900,900; w2=TXT_W-w1-w3
    nb=''.join(f'<w:{b} w:val="nil"/>' for b in ['top','left','bottom','right','insideH','insideV'])
    t=X(f'''<w:tbl><w:tblPr><w:tblW w:w="{TXT_W}" w:type="dxa"/><w:jc w:val="center"/><w:tblBorders>{nb}</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="0000"/></w:tblPr>
<w:tblGrid><w:gridCol w:w="{w1}"/><w:gridCol w:w="{w2}"/><w:gridCol w:w="{w3}"/></w:tblGrid>
<w:tr><w:trPr><w:cantSplit/></w:trPr>
<w:tc><w:tcPr><w:tcW w:w="{w1}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr><w:p><w:pPr><w:pStyle w:val="Equation"/></w:pPr></w:p></w:tc>
<w:tc><w:tcPr><w:tcW w:w="{w2}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr><w:p><w:pPr><w:pStyle w:val="Equation"/></w:pPr></w:p></w:tc>
<w:tc><w:tcPr><w:tcW w:w="{w3}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr><w:p><w:pPr><w:pStyle w:val="EquationNo"/></w:pPr>{run(f"({num})")}</w:p></w:tc>
</w:tr></w:tbl>''')[0]
    t.findall(f'.//{W}tc')[1].find(W+'p').append(omp)
    return t
def split_display_math(p):
    """split a paragraph containing m:oMathPara into text/equation blocks"""
    segs=[]; cur=[]
    for c in list(p):
        if c.tag==W+'pPr': continue
        if c.tag==Mq+'oMathPara':
            segs.append(('t',cur)); segs.append(('m',c)); cur=[]
        else: cur.append(c)
    segs.append(('t',cur))
    out=[]; seen_eq=False
    for kind,v in segs:
        if kind=='t':
            txt=''.join(t.text or '' for e in v for t in e.iter(W+'t'))+''.join('x' for e in v for _ in e.iter(Mq+'oMath'))
            if not txt.strip(): continue
            np_=etree.Element(W+'p')
            if seen_eq: np_.append(X('<w:pPr><w:ind w:firstLine="0" w:firstLineChars="0"/></w:pPr>')[0])
            for e in v: np_.append(e)
            out.append(np_)
        else:
            seen_eq=True
            num=strip_eqnum(v)
            if num: out.append(eq_table(v,num)); report['eq_numbered']+=1
            else:
                q=etree.Element(W+'p'); q.append(X('<w:pPr><w:pStyle w:val="Equation"/></w:pPr>')[0]); q.append(v); out.append(q); report['eq_unnumbered']+=1
    return out
def format_table(t):
    tp=t.find(W+'tblPr')
    for c in list(tp): tp.remove(c)
    for e in X(f'<w:tblW w:w="{TXT_W}" w:type="dxa"/><w:jc w:val="center"/><w:tblBorders><w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/><w:left w:val="nil"/><w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders><w:tblLayout w:type="autofit"/><w:tblCellMar><w:left w:w="85" w:type="dxa"/><w:right w:w="85" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="04A0"/>'): tp.append(e)
    g=t.find(W+'tblGrid'); cols=g.findall(W+'gridCol'); tot=sum(int(c.get(W+'w')) for c in cols)
    ws=[int(int(c.get(W+'w'))*TXT_W/tot) for c in cols]
    for c,wv in zip(cols,ws): c.set(W+'w',str(wv))
    rows=t.findall(W+'tr')
    ncol=len(cols); maxlen=[0]*ncol
    for r in rows[1:]:
        for j,tc in enumerate(r.findall(W+'tc')[:ncol]):
            maxlen[j]=max(maxlen[j],len(''.join(x.text or '' for x in tc.iter(W+'t'))))
    for ri,r in enumerate(rows):
        trpr=r.find(W+'trPr')
        if ri==0:
            if trpr is None: trpr=etree.Element(W+'trPr'); r.insert(0,trpr)
            if trpr.find(W+'tblHeader') is None: etree.SubElement(trpr,W+'tblHeader')
        for j,tc in enumerate(r.findall(W+'tc')):
            tcpr=tc.find(W+'tcPr')
            if tcpr is None: tcpr=etree.Element(W+'tcPr'); tc.insert(0,tcpr)
            w_=tcpr.find(W+'tcW')
            if w_ is not None and j<len(ws): w_.set(W+'w',str(ws[j])); w_.set(W+'type','dxa')
            for b in tcpr.findall(W+'tcBorders'): tcpr.remove(b)
            if ri==0: tcpr.append(X('<w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>')[0])
            v=tcpr.find(W+'vAlign')
            if v is None: tcpr.append(X('<w:vAlign w:val="center"/>')[0])
            jc='center' if (ri==0 or (j<ncol and maxlen[j]<=14)) else 'both'
            for p in tc.findall(W+'p'):
                set_ppr(p,'TableText',f'<w:jc w:val="{jc}"/>',keep=())
                if ri==0:
                    for r_ in p.iter(W+'r'):
                        rp=r_.find(W+'rPr')
                        if rp is None: rp=etree.Element(W+'rPr'); r_.insert(0,rp)
                        if rp.find(W+'b') is None: rp.insert(0,etree.Element(W+'b'))
                superscript_cites(p)
STY_MAP={'BodyText':None,'FirstParagraph':None,'Compact':None,'BlockText':None}
def transform(elems, chapter_mode=True):
    out=[]; listcount={}; prev_num=None
    for k in elems:
        fix_text_nodes(k)
        if k.tag==W+'tbl':
            format_table(k); out.append(k); prev_num=None; continue
        if k.tag!=W+'p': out.append(k); continue
        st=pstyle(k); txt=ptext(k)
        if st and st.startswith('Heading'):
            lvl=int(st[-1])
            set_ppr(k,f'Heading{lvl}',keep=())
            if lvl==1:
                m=re.match(r'第(\d+)章\s*(.*)$',txt)
                if m:
                    for r_ in list(k.findall(W+'r')): k.remove(r_)
                    k.append(X(run(f'{m.group(1)} {m.group(2).strip()}'))[0])
            out.append(k); prev_num=None; continue
        if st=='CaptionedFigure':
            set_ppr(k,'Figure',keep=()); out.append(k); continue
        if st=='ImageCaption':
            set_ppr(k,'Caption',keep=()); report['captions'].append(ptext(k)); out.append(k); continue
        if st=='SourceCode':
            set_ppr(k,'CodeBlock',keep=())
            for r_ in k.iter(W+'r'):
                rp=r_.find(W+'rPr')
                if rp is not None:
                    for c in list(rp):
                        if c.tag==W+'rStyle': rp.remove(c)
            out.append(k); continue
        wruns=[r_ for r_ in k.iter(W+'r') if not r_.getparent().tag.startswith(Mq) and ''.join(t.text or '' for t in r_.iter(W+'t')).strip()]
        allbold=wruns and all(r_.find(f'{W}rPr/{W}b') is not None for r_ in wruns)
        if re.match(r'^(表|算法)\d+\.\d+',txt) and allbold and k.find(f'.//{Mq}oMathPara') is None and len(txt)<80:
            set_ppr(k,'Caption','<w:keepNext/>',keep=())
            for b in k.iter(W+'b',W+'bCs'): b.getparent().remove(b)
            report['captions'].append(ptext(k)); out.append(k); continue
        # body paragraph
        numpr=k.find(f'{W}pPr/{W}numPr')
        set_ppr(k,None,keep=())
        if numpr is not None:
            nid=numpr.find(W+'numId').get(W+'val')
            listcount[nid]=listcount.get(nid,0)+1
            k.insert(1,X(run(f'（{listcount[nid]}）'))[0]); report['lists']+=1
        if st=='BlockText':
            for r_ in k.iter(W+'r'):
                if r_.getparent().tag.startswith(Mq): continue
                rp=r_.find(W+'rPr')
                if rp is None: rp=etree.Element(W+'rPr'); r_.insert(0,rp)
                rp.append(X(HL)[0])
        superscript_cites(k)
        if k.find(f'.//{Mq}oMathPara') is not None:
            out.extend(split_display_math(k))
        else: out.append(k)
    return out
mainT=transform(main)
# ---------------------------------------------------------------- split into chapters
chapters=[]; cur=None
for e in mainT:
    if e.tag==W+'p' and pstyle(e)=='Heading1':
        cur={'title':ptext(e),'el':[]}; chapters.append(cur)
    cur['el'].append(e)
refs=[c for c in chapters if c['title'].strip()=='参考文献'][0]
for p in refs['el'][1:]:
    if p.tag==W+'p':
        # un-superscript reference numbers
        for v in list(p.iter(W+'vertAlign')): v.getparent().remove(v)
        set_ppr(p,'RefEntry',keep=())
chapters=[c for c in chapters if c is not refs]
# ---------------------------------------------------------------- header/footer parts
rels=etree.fromstring(parts['word/_rels/document.xml.rels']); RNS='{http://schemas.openxmlformats.org/package/2006/relationships}'
ct=etree.fromstring(parts['[Content_Types].xml'])
rid_n=[1000]
def add_part(name,data,rtype,ctype=None):
    rid_n[0]+=1; rid=f'rIdZ{rid_n[0]}'
    parts['word/'+name]=data
    r=etree.SubElement(rels,RNS+'Relationship'); r.set('Id',rid); r.set('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/'+rtype); r.set('Target',name)
    if ctype:
        o=etree.SubElement(ct,'{http://schemas.openxmlformats.org/package/2006/content-types}Override'); o.set('PartName','/word/'+name); o.set('ContentType',ctype)
    return rid
HCT='application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml'
FCT='application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml'
hf_n=[0]
def hdr(text):
    hf_n[0]+=1
    if text: c=f'<w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr>{run(text)}</w:p>'
    else: c='<w:p><w:pPr><w:pStyle w:val="HeaderBlank"/></w:pPr></w:p>'
    return add_part(f'header{hf_n[0]}.xml',f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {DECL}>{c}</w:hdr>'.encode(),'header',HCT)
def ftr(page):
    hf_n[0]+=1
    if page: c=('<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    else: c='<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr></w:p>'
    return add_part(f'footer{hf_n[0]}.xml',f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {DECL}>{c}</w:ftr>'.encode(),'footer',FCT)
H0=hdr(None); F0=ftr(False); FP=ftr(True)
COVER_MAR='<w:pgMar w:top="1440" w:right="1361" w:bottom="1440" w:left="1474" w:header="851" w:footer="992" w:gutter="0"/>'
BODY_MAR='<w:pgMar w:top="1985" w:right="1418" w:bottom="1418" w:left="1701" w:header="1418" w:footer="1134" w:gutter="0"/>'
def sect(hdef,hfirst,fdef,ffirst,mar=BODY_MAR,pg='',titlepg=False):
    return (f'<w:sectPr><w:headerReference w:type="default" r:id="{hdef}"/><w:headerReference w:type="first" r:id="{hfirst}"/>'
            f'<w:footerReference w:type="default" r:id="{fdef}"/><w:footerReference w:type="first" r:id="{ffirst}"/>'
            f'<w:type w:val="nextPage"/><w:pgSz w:w="11906" w:h="16838"/>{mar}{pg}{"<w:titlePg/>" if titlepg else ""}'
            '</w:sectPr>')
def end_section(elems,sectxml):
    last=elems[-1] if elems else None
    if last is not None and last.tag==W+'p' and last.find(f'.//{Mq}oMathPara') is None:
        ppr=last.find(W+'pPr')
        if ppr is None: ppr=etree.Element(W+'pPr'); last.insert(0,ppr)
        ppr.append(X(sectxml)[0])
    else:
        elems.append(X(f'<w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto"/>{sectxml}</w:pPr></w:p>')[0])
    return elems
# ---------------------------------------------------------------- front matter content
TITLE_CN='考虑空中交付随机失效的卡车—无人机协同配送事件触发恢复优化'
TITLE_EN='EVENT-TRIGGERED RECOVERY OPTIMIZATION FOR TRUCK–DRONE COLLABORATIVE DELIVERY UNDER RANDOM AERIAL DELIVERY FAILURES'
TITLE_EN_LINES=['EVENT-TRIGGERED RECOVERY OPTIMIZATION FOR','TRUCK–DRONE COLLABORATIVE DELIVERY UNDER','RANDOM AERIAL DELIVERY FAILURES']
PENDING='（题目待确认）'
AUTHOR_CN='姚天洋'; AUTHOR_EN='Yao Tianyang'; SUP_CN='毛程远'; SUP_EN='Mao Chengyuan'
# logo image
parts['word/media/zjnu_logo.png']=open(LOGO,'rb').read()
LOGO_RID=add_part('media/zjnu_logo.png',parts.pop('word/media/zjnu_logo.png'),'image')
KAI='<w:rFonts w:ascii="楷体_GB2312" w:hAnsi="楷体_GB2312" w:eastAsia="楷体_GB2312"/>'
def kr(t,size=32,b=True,u=False,extra=''):
    return run(t,KAI+('<w:b/><w:bCs/>' if b else '')+('<w:u w:val="single"/>' if u else '')+f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'+extra)
HEI='<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/>'
NOIND='<w:ind w:firstLine="0" w:firstLineChars="0"/>'
def cpara(content,ppr=''): return para(content,'CoverText',ppr)
cover=[]
cover.append(cpara(kr('学校代码 ')+kr(' 10345 ',u=True)+kr('                  研究类型 ')+kr('          ',u=True)))
cover+= [cpara('')]*2
cover.append(cpara(f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="5170805" cy="1292860"/><wp:docPr id="9001" name="ZJNU Logo"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="9001" name="zjnu_logo.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{LOGO_RID}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5170805" cy="1292860"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>','<w:jc w:val="center"/>'))
cover.append(cpara(''))
cover.append(cpara(kr('硕士专业学位论文',size=72,extra='<w:spacing w:val="60"/>'),'<w:jc w:val="center"/>'))
cover+= [cpara('')]*2
L600='<w:spacing w:line="600" w:lineRule="auto"/>'
cover.append(cpara(run('题  目：',HEI+'<w:b/><w:sz w:val="36"/><w:szCs w:val="36"/>')+run(TITLE_CN,HEI+'<w:b/><w:u w:val="single"/><w:sz w:val="36"/><w:szCs w:val="36"/>')+run(PENDING,HEI+'<w:sz w:val="24"/>'+HL),L600+'<w:ind w:left="630" w:hanging="1260"/>'.replace('w:left="630" w:hanging="1260"','w:left="1890" w:hanging="1260"')))
cover.append(cpara(''))
cover.append(cpara(kr('专业学位类别：')+kr('交通运输硕士',u=True,b=False)+run('（待确认）',KAI+HL+'<w:sz w:val="24"/>'),L600+'<w:ind w:left="630"/>'))
cover.append(cpara(kr('学 科 领 域 ：')+kr('交通运输          ',u=True,b=False),L600+'<w:ind w:left="630"/>'))
cover.append(cpara(kr('年      级：')+kr('            ',u=True,b=False)+kr('  学    号：')+kr('            ',u=True,b=False),L600+'<w:ind w:left="630"/>'))
cover.append(cpara(kr('研  究  生：')+kr(f'  {AUTHOR_CN}    ',u=True,b=False)+kr('  指导教师：')+kr(f'  {SUP_CN}    ',u=True,b=False),L600+'<w:ind w:left="630"/>'))
cover.append(cpara(kr('中图分类号：')+kr('         ',u=True,b=False)+kr(' 论文提交时间：')+kr('      ',u=True,b=False)+kr('年')+kr('    ',u=True,b=False)+kr('月')+kr('    ',u=True,b=False)+kr('日'),L600+'<w:ind w:left="630"/>'))
cover=X(''.join(cover))
end_section(cover,sect(H0,H0,F0,F0,COVER_MAR))
# 扉页
def fz(cn): return para(run(cn,HEI+'<w:sz w:val="32"/><w:szCs w:val="32"/>'),'TitlePage')
def fe(en): return para(run(en,'<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/><w:sz w:val="32"/><w:szCs w:val="32"/>'),'TitlePage')
fy=[para(run(TITLE_CN,HEI+'<w:sz w:val="32"/>')+run(PENDING,HEI+HL+'<w:sz w:val="24"/>'),'TitlePage')]
fy+=[fe(l) for l in TITLE_EN_LINES]
fy+=[para(run('(Title pending confirmation)','<w:sz w:val="24"/>'+HL),'TitlePage')]
fy+=[para('','TitlePage')]
fy+=[fz(f'作者：{AUTHOR_CN}'),fe(f'The Author: {AUTHOR_EN}'),
     para(run('学位类别：交通运输硕士（专业学位）',HEI+'<w:sz w:val="32"/>')+run('（待确认）',HEI+HL+'<w:sz w:val="24"/>'),'TitlePage'),
     para(run('Degree Category: Master of Transportation (Professional Degree)','<w:sz w:val="32"/>')+run(' (TBC)','<w:sz w:val="24"/>'+HL),'TitlePage'),
     para(run('年级：',HEI+'<w:sz w:val="32"/>')+run('        级',HEI+'<w:u w:val="single"/><w:sz w:val="32"/>'),'TitlePage'),
     para(run('Grade: ','<w:sz w:val="32"/>')+run('        ','<w:u w:val="single"/><w:sz w:val="32"/>'),'TitlePage'),
     fz('学科专业：交通运输'),fe('Major: Transportation'),
     fz('学位授予单位：浙江师范大学'),fe('The Degree-granting Unit: Zhejiang Normal University'),
     fz(f'指导教师：{SUP_CN}'),fe(f'Supervisor: {SUP_EN}'),
     para(run('提交日期：',HEI+'<w:sz w:val="32"/>')+run('      年    月    日',HEI+'<w:u w:val="single"/><w:sz w:val="32"/>'),'TitlePage'),
     para(run('Date of submission: ','<w:sz w:val="32"/>')+run('                    ','<w:u w:val="single"/><w:sz w:val="32"/>'),'TitlePage')]
fy=X(''.join(fy)); end_section(fy,sect(H0,H0,F0,F0,COVER_MAR))
# Chinese abstract
ABS_CN=[
'卡车—无人机协同配送能够兼顾卡车载量大、续航长与无人机速度快、不受路网约束的互补优势，是降低城市末端配送成本的重要途径。然而，现有车机协同模型大多假设每一次空中投递都能按计划完成，而投放点被占用、收件设施不可用等现场条件往往只有在无人机飞抵客户上空时才能确认。一旦空中交付失败，失败包裹仍留在机上，无人机须与卡车重新会合并改由卡车地面送达，进而可能引发滞空等待、电量不足、车辆绕行和班次超时等连锁后果。为此，本文研究随机空中交付失效下的多车多机协同配送恢复优化问题，目的是为失效发生后的回收与重调度提供一种可在有限计算预算内执行、且经独立核验可行的决策方法。',
'首先，本文建立了包含连续放飞位置、多票航次、载荷相关能耗、行驶充电、跨车回收与客户点重访的多车多机协同配送模型，以“到点揭示”的方式刻画空中交付失效，以及失败包裹在无人机与卡车之间的保管转移、回收交接和锁定地送过程，并在公开快照与隐藏环境严格隔离的信息结构下，将问题表述为事件触发的序贯决策过程。其次，设计了事件触发的自适应大邻域搜索（ALNS）数学启发式求解框架：以名义计划的未执行残段为基座生成恢复初解，由 ALNS 搜索离散结构，在结构与几何固定后以线性规划求解时序与充电量，并对全部候选方案进行独立的物理与成本重放核验。在此基础上，本文设计了两项方法改进：一是将失效后的回收卡车、回收客户点、插入位置、继续空送子集与失败包裹地送位置的联合决策构造为混合整数线性规划（MILP）恢复子问题，并与 ALNS 交替协调；二是以搜索停滞程度、退火温度阶段和失效类型构成离散状态，采用 Q-learning 替代传统 ALNS 的分段轮盘权重来选择“移除—修复”算子对，且学习过程不读取任何隐藏信息。最后，设计了仅允许原放飞卡车回收（S 政策）与允许任一合格卡车回收（X 政策）的配对比较方案，令两种政策共享名义计划、隐藏失效集合、物理参数与求解预算，并给出“同点/异点 × 原车/跨车”两层恢复分类，以便如实评估跨车回收的价值。',
]
ABS_CN_PENDING='【待实验完成后补充：数值实验的主要结果（包括 MILP 恢复子问题与 Q-learning 算子选择相对基线 ALNS 的效果，以及 S/X 两种回收政策的配对比较结果）与研究结论。】'
KW_CN='卡车—无人机协同配送；空中交付失效；事件触发恢复；自适应大邻域搜索；混合整数线性规划；强化学习'
absc=[para(run(TITLE_CN)+run(PENDING,HL+'<w:sz w:val="24"/>'),'ThesisTitle'),para('','AbsBody'),
      para(run('摘  要'),'AbsHeading'),para('','AbsBody')]
absc+=[para(run(t),'AbsBody') for t in ABS_CN]+[para(run(ABS_CN_PENDING,HL),'AbsBody'),para('','AbsBody')]
absc+=[para(run('关键词：',HEI+'<w:sz w:val="28"/><w:szCs w:val="28"/>')+run(KW_CN),'AbsBody',NOIND)]
absc=X(''.join(absc)); end_section(absc,sect(H0,H0,FP,FP,pg='<w:pgNumType w:fmt="upperRoman" w:start="1"/>'))
ABS_EN=[
'Truck–drone collaborative delivery combines the large capacity and long range of trucks with the speed and road-network independence of drones, and is a promising way to reduce the cost of urban last-mile delivery. Most existing truck–drone models, however, assume that every aerial delivery succeeds as planned, whereas on-site conditions such as an occupied drop point or an unavailable receiving facility can often be confirmed only when the drone arrives above the customer. When an aerial delivery fails, the parcel remains on board, the drone must rendezvous with a truck again, and the parcel must be delivered on the ground, which may trigger airborne waiting, energy shortage, truck detours and shift overruns. This thesis studies the recovery optimization problem of multi-truck multi-drone collaborative delivery under random aerial delivery failures, with the objective of providing a decision method that can be executed within a limited computational budget and whose solutions are independently verified to be feasible.',
'First, a multi-truck multi-drone delivery model is formulated that includes continuous launch positions, multi-parcel sorties, payload-dependent energy consumption, on-the-move charging, cross-truck retrieval and customer revisits. Aerial delivery failures are revealed only upon arrival, and the custody transfer, retrieval, handover and mandatory ground delivery of failed parcels are modeled explicitly. Under an information structure that strictly separates the public snapshot from the hidden environment, the problem is cast as an event-triggered sequential decision process. Second, an event-triggered matheuristic framework based on adaptive large neighborhood search (ALNS) is designed: recovery starts from the unexecuted residual of the nominal plan, ALNS searches the discrete structure, linear programming determines the timing and charging amounts once the structure and geometry are fixed, and every candidate solution is verified by an independent physical and cost replay. On this basis, two methodological enhancements are designed. The first formulates the joint decision on the retrieving truck, retrieval customer, insertion position, continued aerial-delivery subset and ground-delivery position of failed parcels as a mixed-integer linear programming (MILP) recovery subproblem that is coordinated with ALNS. The second replaces the segment-based roulette-wheel weights of classical ALNS with Q-learning, using search stagnation, annealing temperature phase and failure type as a discrete state to select destroy–repair operator pairs without accessing any hidden information. Finally, a paired comparison design is developed between a same-truck retrieval policy (S) and a cross-truck retrieval policy (X), in which both policies share the nominal plan, hidden failure set, physical parameters and solution budget, and recovery actions are classified by same/different location and original/other truck.',
]
ABS_EN_PENDING='[To be completed after the experiments: main numerical results (effects of the MILP recovery subproblem and Q-learning operator selection relative to the baseline ALNS, and the paired S/X policy comparison) and conclusions.]'
KW_EN='Truck–Drone Collaborative Delivery; Aerial Delivery Failure; Event-Triggered Recovery; Adaptive Large Neighborhood Search; Mixed-Integer Linear Programming; Reinforcement Learning'
abse=[para(''.join(run(l)+('<w:r><w:br/></w:r>' if j<len(TITLE_EN_LINES)-1 else '') for j,l in enumerate(TITLE_EN_LINES))+run(' (TBC)',HL+'<w:sz w:val="24"/>'),'ThesisTitle'),para('','AbsBody'),
      para(run('ABSTRACT'),'AbsHeading'),para('','AbsBody')]
abse+=[para(run(t),'AbsBodyEN') for t in ABS_EN]+[para(run(ABS_EN_PENDING,HL),'AbsBodyEN'),para('','AbsBody')]
abse+=[para(run('KEY WORDS: ','<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/>')+run(KW_EN),'AbsBodyEN',NOIND)]
abse=X(''.join(abse)); end_section(abse,sect(H0,H0,FP,FP,pg='<w:pgNumType w:fmt="upperRoman"/>'))
# TOC (field; entries pre-filled later)
toc=[para(run('目  录'),'TOCTitle'),
     '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>',
     '<!--TOCENTRIES-->',
     '<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>']
TOC_XML=''.join(toc)
# ---------------------------------------------------------------- back matter
def h1(t): return para(run(t),'Heading1')
ack=X(h1('致  谢')+para(run('【致谢内容待补充：对导师毛程远老师及给予指导或协助完成学位论文工作的组织和个人表示感谢；如有课题资助，请注明资助项目。本部分不可省略。】',HL)))
res=X(h1('攻读学位期间取得的研究成果')+para(run('【待补充：按类别（学术论文、著作、获奖、专利）列出攻读学位期间取得的研究成果，书写格式同参考文献。学术论文须注明作者、题目、刊物名称（含刊号）、卷期、页码、年月及署名次序与署名单位。如无，请按学院要求注明。】',HL)))
SIGN='<w:ind w:left="2520" w:firstLine="0" w:firstLineChars="0"/>'
integ=X(h1('浙江师范大学学位论文诚信承诺书')+para('')+
 para(run('我承诺自觉遵守《浙江师范大学研究生学术道德规范管理条例》。我的学位论文中凡引用他人已经发表或未发表的成果、数据、观点等，均已明确注明并详细列出有关文献的名称、作者、年份、刊物名称和出版文献的出版机构、出版地和版次等内容。论文中未注明的内容为本人的研究成果。'))+
 para(run('如有违反，本人接受处罚并承担一切责任。'))+para('')+para('')+
 para(run('承诺人（研究生）：'),None,SIGN)+para(run('指   导  教  师：'),None,SIGN))
decl=X(h1('浙江师范大学学位论文独创性声明')+para('')+
 para(run('本人声明所呈交的学位论文是我个人在导师指导下进行的研究工作及取得的研究成果。论文中除了特别加以标注和致谢的地方外，不包含其他人或其他机构已经发表或撰写过的研究成果。其他同志对本研究的启发和所做的贡献均已在论文中作了明确的声明并表示了谢意。本人完全意识到本声明的法律结果由本人承担。'))+para('')+
 para(run('作者签名：                日期：    年    月    日'),None,'<w:ind w:left="1260" w:firstLine="0" w:firstLineChars="0"/>')+para('')+para('')+
 para(run('学位论文使用授权声明'),'Heading1',)+para('')+
 para(run('本人完全了解浙江师范大学有关保留、使用学位论文的规定，即：学校有权保留并向国家有关机关或机构送交论文的复印件和电子文档，允许论文被查阅和借阅，可以采用影印、缩印或扫描等手段保存、汇编学位论文。同意浙江师范大学可以用不同方式在不同媒体上发表、传播论文的全部或部分内容。'))+
 para(run('保密的学位论文在解密后遵守此协议。'))+para('')+
 para(run('作者签名：            导师签名：            日期：    年    月    日'),None,'<w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>'))
# the second heading in decl page should not start new page: Heading1 has no pageBreakBefore, fine.
# ---------------------------------------------------------------- assemble
seq=cover+fy+absc+abse
toc_el=X(TOC_XML.replace('<!--TOCENTRIES-->',''))
end_section(toc_el,sect(H0,H0,FP,FP,pg='<w:pgNumType w:fmt="upperRoman"/>'))
toc_marker_index=len(seq)
seq+=toc_el
first=True
backs=[('参考文献',refs['el']),('致  谢',ack),('攻读学位期间取得的研究成果',res),('浙江师范大学学位论文诚信承诺书',integ),('学位论文独创性声明与使用授权声明',decl)]
for c in chapters:
    hd=hdr(c['title'])
    pg='<w:pgNumType w:fmt="decimal" w:start="1"/>' if first else '<w:pgNumType w:fmt="decimal"/>'
    first=False
    seq+=end_section(c['el'],sect(hd,H0,FP,FP,pg=pg,titlepg=True))
for name,els in backs[:-1]:
    hd=hdr(name)
    seq+=end_section(list(els),sect(hd,H0,FP,FP,pg='<w:pgNumType w:fmt="decimal"/>',titlepg=True))
hd=hdr(backs[-1][0])
for e in backs[-1][1]: seq.append(e)
for e in seq: body.append(e)
body.append(X(sect(hd,H0,FP,FP,pg='<w:pgNumType w:fmt="decimal"/>',titlepg=True))[0])
# ---------------------------------------------------------------- styles
sty=etree.fromstring(parts['word/styles.xml'])
TNR_SONG='<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" w:cs="Times New Roman"/>'
TNR_HEI='<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体" w:cs="Times New Roman"/>'
NEWSTY={
'Normal':('paragraph','Normal',None,'<w:widowControl/><w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLineChars="200" w:firstLine="480"/><w:jc w:val="both"/>',TNR_SONG+'<w:kern w:val="2"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/>'),
'Heading1':('paragraph','heading 1','Normal','<w:keepNext/><w:keepLines/><w:spacing w:before="312" w:beforeLines="100" w:after="312" w:afterLines="100" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/>',TNR_HEI+'<w:b/><w:bCs/><w:sz w:val="32"/><w:szCs w:val="32"/>'),
'Heading2':('paragraph','heading 2','Normal','<w:keepNext/><w:keepLines/><w:spacing w:before="0" w:after="120" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="left"/><w:outlineLvl w:val="1"/>',TNR_HEI+'<w:sz w:val="30"/><w:szCs w:val="30"/>'),
'Heading3':('paragraph','heading 3','Normal','<w:keepNext/><w:keepLines/><w:spacing w:before="0" w:after="120" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="left"/><w:outlineLvl w:val="2"/>',TNR_HEI+'<w:sz w:val="28"/><w:szCs w:val="28"/>'),
'Heading4':('paragraph','heading 4','Normal','<w:keepNext/><w:keepLines/><w:spacing w:before="290" w:after="280" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="left"/><w:outlineLvl w:val="3"/>',TNR_HEI+'<w:sz w:val="24"/><w:szCs w:val="24"/>'),
'Caption':('paragraph','图表题注','Normal','<w:keepLines/><w:spacing w:before="60" w:after="60" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>','<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="楷体" w:cs="Times New Roman"/><w:b w:val="0"/><w:i w:val="0"/><w:color w:val="000000"/><w:sz w:val="21"/><w:szCs w:val="21"/>'),
'Figure':('paragraph','图','Normal','<w:keepNext/><w:spacing w:before="120" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>',''),
'Equation':('paragraph','公式','Normal','<w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>',''),
'EquationNo':('paragraph','公式编号','Normal','<w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="right"/>',''),
'TableText':('paragraph','表格文字','Normal','<w:spacing w:before="0" w:after="0" w:line="264" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/>','<w:sz w:val="21"/><w:szCs w:val="21"/>'),
'CodeBlock':('paragraph','算法代码','Normal','<w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="000000"/><w:bottom w:val="single" w:sz="4" w:space="4" w:color="000000"/></w:pBdr><w:spacing w:before="0" w:after="120" w:line="264" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="left"/>','<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:eastAsia="宋体" w:cs="Courier New"/><w:sz w:val="18"/><w:szCs w:val="18"/>'),
'RefEntry':('paragraph','参考文献条目','Normal','<w:spacing w:before="0" w:after="0" w:line="300" w:lineRule="auto"/><w:ind w:left="420" w:hanging="420" w:firstLineChars="0"/><w:jc w:val="both"/>','<w:sz w:val="21"/><w:szCs w:val="21"/>'),
'ThesisTitle':('paragraph','论文题目','Normal','<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>',TNR_HEI+'<w:sz w:val="32"/><w:szCs w:val="32"/>'),
'AbsHeading':('paragraph','摘要','Normal','<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/><w:outlineLvl w:val="9"/>',TNR_HEI+'<w:sz w:val="30"/><w:szCs w:val="30"/>'),
'AbsBody':('paragraph','摘要正文','Normal','',''),
'AbsBodyEN':('paragraph','摘要正文（英文）','Normal','<w:ind w:firstLine="480" w:firstLineChars="0"/>',''),
'TOCTitle':('paragraph','目录标题','Normal','<w:spacing w:before="312" w:beforeLines="100" w:after="312" w:afterLines="100" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>',TNR_HEI+'<w:b/><w:bCs/><w:sz w:val="32"/><w:szCs w:val="32"/>'),
'TOC1':('paragraph','toc 1','Normal','<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="8777"/></w:tabs><w:spacing w:before="0" w:after="0" w:line="400" w:lineRule="exact"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="both"/>',''),
'TOC2':('paragraph','toc 2','Normal','<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="8777"/></w:tabs><w:spacing w:before="0" w:after="0" w:line="400" w:lineRule="exact"/><w:ind w:left="480" w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="both"/>',''),
'TOC3':('paragraph','toc 3','Normal','<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="8777"/></w:tabs><w:spacing w:before="0" w:after="0" w:line="400" w:lineRule="exact"/><w:ind w:left="960" w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="both"/>',''),
'Header':('paragraph','header','Normal','<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr><w:tabs><w:tab w:val="center" w:pos="4153"/><w:tab w:val="right" w:pos="8306"/></w:tabs><w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>','<w:sz w:val="21"/><w:szCs w:val="21"/>'),
'HeaderBlank':('paragraph','页眉（空）','Normal','<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>','<w:sz w:val="21"/><w:szCs w:val="21"/>'),
'Footer':('paragraph','footer','Normal','<w:tabs><w:tab w:val="center" w:pos="4153"/><w:tab w:val="right" w:pos="8306"/></w:tabs><w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>','<w:sz w:val="21"/><w:szCs w:val="21"/>'),
'CoverText':('paragraph','封面文字','Normal','<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="left"/>',''),
'TitlePage':('paragraph','扉页文字','Normal','<w:spacing w:line="360" w:lineRule="auto"/><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>','<w:sz w:val="32"/><w:szCs w:val="32"/>'),
'VerbatimChar':('character','Verbatim Char',None,None,'<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/><w:sz w:val="21"/>'),
}
for s in list(sty.findall(W+'style')):
    if s.get(W+'styleId') in NEWSTY or s.get(W+'styleId') in ('Heading1Char','Heading2Char','Heading3Char','Heading4Char'): sty.remove(s)
dd=sty.find(W+'docDefaults')
if dd is not None: sty.remove(dd)
sty.insert(0,X(f'<w:docDefaults><w:rPrDefault><w:rPr>{TNR_SONG}<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr/></w:pPrDefault></w:docDefaults>')[0])
for sid,(typ,name,based,ppr,rpr) in NEWSTY.items():
    q=f'<w:style w:type="{typ}" w:styleId="{sid}"'+(' w:default="1"' if sid=='Normal' else '')+f'><w:name w:val="{name}"/>'
    if based: q+=f'<w:basedOn w:val="{based}"/>'
    if sid.startswith('Heading'): q+='<w:next w:val="Normal"/>'
    q+='<w:qFormat/>'
    if ppr is not None: q+=f'<w:pPr>{ppr}</w:pPr>'
    q+=f'<w:rPr>{rpr}</w:rPr></w:style>'
    sty.append(X(q)[0])
# other pandoc paragraph styles based on Normal that carry their own spacing: neutralise BodyText etc. (not used anymore)
parts['word/styles.xml']=etree.tostring(sty,xml_declaration=True,encoding='UTF-8',standalone=True)
# settings: update fields on open, mirror none
st=etree.fromstring(parts['word/settings.xml'])
if st.find(W+'updateFields') is None:
    u=etree.Element(W+'updateFields'); u.set(W+'val','true'); st.insert(1,u)
parts['word/settings.xml']=etree.tostring(st,xml_declaration=True,encoding='UTF-8',standalone=True)
parts['word/_rels/document.xml.rels']=etree.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
parts['[Content_Types].xml']=etree.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
# core props title
if 'docProps/core.xml' in parts:
    c=parts['docProps/core.xml'].decode()
    c=re.sub(r'<dc:title>.*?</dc:title>',f'<dc:title>{TITLE_CN}</dc:title>',c)
    c=re.sub(r'<dc:creator>.*?</dc:creator>',f'<dc:creator>{AUTHOR_CN}</dc:creator>',c)
    parts['docProps/core.xml']=c.encode()
# ---------------------------------------------------------------- TOC entries prefill (from page map if available)
import json, os
pagemap=json.load(open('/tmp/zjnu_pagemap.json')) if os.path.exists('/tmp/zjnu_pagemap.json') else {}
entries=[]; bm=0
for p in body.iter(W+'p'):
    s=pstyle(p)
    if s in ('Heading1','Heading2','Heading3'):
        t=ptext(p).strip()
        if not t: continue
        bm+=1; name=f'_Toc_zj{bm:04d}'
        p.insert(1,X(f'<w:bookmarkStart w:id="{8000+bm}" w:name="{name}"/>')[0]); p.append(X(f'<w:bookmarkEnd w:id="{8000+bm}"/>')[0])
        lvl=int(s[-1]); pg=pagemap.get(t,'')
        entries.append(f'<w:p><w:pPr><w:pStyle w:val="TOC{lvl}"/></w:pPr><w:hyperlink w:anchor="{name}" w:history="1">{run(t)}<w:r><w:tab/></w:r>'
                       f'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGEREF {name} \\h </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>{run(str(pg))}<w:r><w:fldChar w:fldCharType="end"/></w:r></w:hyperlink></w:p>')
# insert entries after the field-begin paragraph
tocbegin=[p for p in body.iter(W+'p') if any((it.text or '').strip().startswith('TOC') for it in p.iter(W+'instrText'))][0]
idx=list(body).index(tocbegin)
for j,e in enumerate(X(''.join(entries))): body.insert(idx+1+j,e)
parts['word/document.xml']=etree.tostring(doc,xml_declaration=True,encoding='UTF-8',standalone=True)
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as z:
    for n,d in parts.items(): z.writestr(n,d)
print('wrote',OUT,report['eq_numbered'],report['eq_unnumbered'],report['cites'],report['lists'])
print('captions',report['captions'])
print('chapters',[c['title'] for c in chapters])
# ---------------------------------------------------------------- discrepancy list docx
d2=dict(zin.read(n) and (n,zin.read(n)) for n in zin.namelist())
d2=dict((n,zin.read(n)) for n in zin.namelist())
doc2=etree.fromstring(d2['word/document.xml']); b2=doc2.find(W+'body')
for k in list(b2): 
    if k.tag!=W+'sectPr': b2.remove(k)
s2=b2.find(W+'sectPr')
intro=X(para(run('规范歧义与代码—规范差异清单（供作者核对，非论文正文）','<w:b/><w:sz w:val="32"/>'),None,'<w:jc w:val="center"/>')+
        para(run('说明：本清单原附于论文初稿（thesis_draft_ch1-4.docx）文末，现按浙江师范大学 2025 模板排版时从论文文件中移出单独保存（2026-11-12）。论文正文中相应位置的“实现说明”已改为指向本文件。'))+
        para(run('原初稿草稿说明：','<w:b/>')))
for e in intro: b2.insert(len(b2)-1,e)
for e in [e for e in front_draft if pstyle(e)!='Heading1']+disc[1:]:
    b2.insert(len(b2)-1,copy.deepcopy(e))
s2.append(X('<w:pgSz w:w="11906" w:h="16838"/>')[0]); s2.append(X('<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="851" w:footer="992" w:gutter="0"/>')[0])
d2['word/document.xml']=etree.tostring(doc2,xml_declaration=True,encoding='UTF-8',standalone=True)
with zipfile.ZipFile(DISC,'w',zipfile.ZIP_DEFLATED) as z:
    for n,d in d2.items(): z.writestr(n,d)
print('wrote',DISC)
