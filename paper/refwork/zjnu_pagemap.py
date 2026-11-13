import subprocess,json,re,zipfile
from lxml import etree
pdf='/tmp/pdfout/thesis_zjnu_v1.pdf'; docx='/workspace/thesis/paper/thesis_zjnu_v1.docx'
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
n=int(re.search(r'Pages:\s+(\d+)',subprocess.run(['pdfinfo',pdf],capture_output=True,text=True).stdout).group(1))
pages=[subprocess.run(['pdftotext','-f',str(i),'-l',str(i),pdf,'-'],capture_output=True,text=True).stdout for i in range(1,n+1)]
norm=lambda s:re.sub(r'\s+','',s)
plines=[[norm(l) for l in p.splitlines()] for p in pages]
d=etree.fromstring(zipfile.ZipFile(docx).read('word/document.xml'))
heads=[]
for p in d.iter(W+'p'):
    s=p.find(f'{W}pPr/{W}pStyle')
    if s is not None and s.get(W+'val') in ('Heading1','Heading2','Heading3'):
        heads.append(''.join(t.text or '' for t in p.iter(W+'t')).strip())
start=next(i for i,pl in enumerate(plines) if '1绪论' in pl and not any('.....' in l for l in pl))
mp={}; cur=start
for h in heads:
    for i in range(cur,n):
        if norm(h) in plines[i]: mp[h]=str(i-start+1); cur=i; break
    else: mp[h]=''
json.dump(mp,open('/tmp/zjnu_pagemap.json','w'),ensure_ascii=False)
print('body starts at physical page',start+1,'missing',[h for h,v in mp.items() if not v])
