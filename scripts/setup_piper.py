"""Download the public Piper Chinese voice with upstream file verification."""
import hashlib,json,os,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/'
FILES=[('zh_CN-huayan-medium.onnx',63201294,'sha256','9929917bf8cabb26fd528ea44d3a6699c11e87317a14765312420be230be0f3d'),
       ('zh_CN-huayan-medium.onnx.json',4822,'git','f0e6e6ed1f91fdfa0bac50cb6f0538606fde254b'),
       ('MODEL_CARD',276,'git','02b4fba5ae8353637e93af3443ddddacf14c663e')]

def valid(path,size,kind,expected):
    if not path.is_file() or path.stat().st_size!=size:return False
    h=hashlib.sha256() if kind=='sha256' else hashlib.sha1(b'blob '+str(size).encode()+b'\0')
    with path.open('rb') as source:
        while block:=source.read(1024*1024):h.update(block)
    return h.hexdigest()==expected

def main():
    root=ROOT/'models/piper';root.mkdir(parents=True,exist_ok=True)
    for name,size,kind,digest in FILES:
        dest=root/name
        if valid(dest,size,kind,digest):print('Verified '+name,flush=True);continue
        if dest.exists():raise RuntimeError('Existing model differs; preserve and inspect '+str(dest))
        temp=dest.with_suffix(dest.suffix+'.part')
        print('Downloading '+name,flush=True)
        with urllib.request.urlopen(BASE+name,timeout=45) as response,temp.open('wb') as out:
            total=0
            while block:=response.read(1024*1024):
                total+=len(block)
                if total>size:raise ValueError('Downloaded file exceeds expected size')
                out.write(block)
        if not valid(temp,size,kind,digest):raise ValueError('Model verification failed')
        os.replace(temp,dest)
    (root/'source.json').write_text(json.dumps({'source':BASE,'engine':'piper-tts==1.8.0','files':FILES},indent=2))
    print('PASS: Chinese Piper voice files verified')

if __name__=='__main__':main()
