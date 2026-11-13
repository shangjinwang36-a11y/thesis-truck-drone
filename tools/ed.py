import sys
def patch(path, old, new, count=1):
    raw=open(path,newline='').read()
    crlf='\r\n' in raw
    s=raw.replace('\r\n','\n')
    assert s.count(old)>=1, f'not found in {path}: {old[:60]!r}'
    if count==1: assert s.count(old)==1, f'ambiguous {s.count(old)}'
    s=s.replace(old,new)
    if crlf: s=s.replace('\n','\r\n')
    open(path,'w',newline='').write(s)
