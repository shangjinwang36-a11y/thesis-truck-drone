import json, sys, urllib.request, urllib.parse, time, concurrent.futures as cf
dois=[l.strip() for l in open('dois2.txt') if l.strip()]
def get(d):
    url='https://api.crossref.org/works/'+urllib.parse.quote(d, safe='/')
    for k in range(3):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'thesis-ref-check (mailto:none@example.com)'})
            m=json.load(urllib.request.urlopen(req, timeout=30))['message']
            au=[(a.get('family',''),a.get('given','')) for a in m.get('author',[])]
            ed=[(a.get('family',''),a.get('given','')) for a in m.get('editor',[])]
            iss=m.get('published-print') or m.get('issued') or {}
            yr=(m.get('issued') or {}).get('date-parts',[[None]])[0][0]
            pyr=(m.get('published-print') or {}).get('date-parts',[[None]])[0][0]
            oyr=(m.get('published-online') or {}).get('date-parts',[[None]])[0][0]
            return dict(doi=d, ok=True, title=(m.get('title') or [''])[0], authors=au, editors=ed,
              container=(m.get('container-title') or [''])[0], year=yr, print_year=pyr, online_year=oyr,
              volume=m.get('volume'), issue=m.get('issue'), page=m.get('page'), article=m.get('article-number'),
              type=m.get('type'), publisher=m.get('publisher'))
        except Exception as e:
            err=str(e); time.sleep(2)
    return dict(doi=d, ok=False, err=err)
with cf.ThreadPoolExecutor(6) as ex:
    res=list(ex.map(get,dois))
json.dump(res, open('crossref2.json','w'), ensure_ascii=False, indent=1)
for r in res:
    if r['ok']:
        a=r['authors']; 
        print(f"{r['doi']} | {r['year']}/{r['print_year']} | {a[0][0] if a else (r['editors'][0][0] if r['editors'] else '-')} +{max(0,len(a)-1)} | {r['title'][:90]} | {r['container'][:50]} | {r['volume']}:{r['page'] or r['article']}")
    else:
        print(r['doi'], 'FAIL', r['err'])
