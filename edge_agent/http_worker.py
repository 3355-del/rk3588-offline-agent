"""One bounded localhost request. Parent can cancel by terminating this worker."""
import sys,json,urllib.request
from pathlib import Path
from .backend import NoRedirect
def main():
    job=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    try:
        body=json.dumps(job['payload'],ensure_ascii=False).encode()
        req=urllib.request.Request(job['url'],data=body,headers={'Content-Type':'application/json'},method='POST')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(req,timeout=job['timeout']) as response:raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('model response too large')
        result={'response':json.loads(raw)}
    except Exception as exc:result={'error':str(exc)[:2000],'value_error':isinstance(exc,ValueError)}
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
if __name__=='__main__':main()
