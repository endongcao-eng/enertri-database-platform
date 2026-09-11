"""Read-only HTTP load probe for an owned STAGING URL; no AI calls or credentials.
Example: python scripts/load_probe.py https://trial.example.org --users 20 --requests 400
This measures public read routes only, not authenticated or background-task capacity.
"""
import argparse, concurrent.futures, json, math, time, urllib.request
from urllib.parse import urlsplit
p=argparse.ArgumentParser();p.add_argument('base_url');p.add_argument('--users',type=int,default=20);p.add_argument('--requests',type=int,default=400)
a=p.parse_args()
if not 1<=a.users<=100 or not 1<=a.requests<=10000: p.error('users 1..100; requests 1..10000')
u=urlsplit(a.base_url)
if u.scheme not in {'http','https'} or not u.hostname or u.username or u.password: p.error('Supply an HTTP(S) URL without credentials')
paths=['/api/categories','/api/terms?status=approved&limit=50','/api/articles?status=approved&limit=20']
def one(i):
    start=time.monotonic()
    try:
        with urllib.request.urlopen(a.base_url.rstrip('/')+paths[i%len(paths)],timeout=20) as r:
            body=json.load(r)
            valid=r.status==200 and isinstance(body,list)
            return (time.monotonic()-start)*1000,valid
    except Exception: return (time.monotonic()-start)*1000,False
start=time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=a.users) as pool: results=list(pool.map(one,range(a.requests)))
duration=time.monotonic()-start
lat=sorted(x[0] for x in results);errors=sum(not x[1] for x in results)
print(json.dumps({'scope':'public-read-only','concurrency':a.users,'requests':len(results),'errors':errors,'error_rate':errors/len(results),'p95_ms':round(lat[math.ceil(.95*len(lat))-1],1),'p99_ms':round(lat[math.ceil(.99*len(lat))-1],1),'requests_per_second':round(len(results)/duration,1)},indent=2))
raise SystemExit(1 if errors or lat[math.ceil(.95*len(lat))-1]>1000 else 0)
