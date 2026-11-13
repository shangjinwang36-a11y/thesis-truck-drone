import json,sys,urllib.request,urllib.parse
for q in sys.argv[1:]:
    url='https://api.crossref.org/works?rows=6&query.bibliographic='+urllib.parse.quote(q)
    req=urllib.request.Request(url, headers={'User-Agent':'thesis-ref-check (mailto:none@example.com)'})
    items=json.load(urllib.request.urlopen(req,timeout=40))['message']['items']
    print('==',q)
    for m in items:
        a=m.get('author',[]); yr=(m.get('issued') or {}).get('date-parts',[[None]])[0][0]
        print('  ',m['DOI'],'|',yr,'|',(a[0].get('family') if a else '-'),'|',(m.get('title') or [''])[0][:100],'|',(m.get('container-title') or [''])[0][:45])
