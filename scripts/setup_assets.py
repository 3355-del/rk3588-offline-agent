"""Download only pinned project assets, verify before promotion/extraction."""
import argparse,hashlib,json,os,time,urllib.request,zipfile,shutil,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def download(item):
    target=(ROOT/item['path']).resolve()
    if not target.is_relative_to(ROOT):raise ValueError('asset path outside project')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and target.stat().st_size==item['size'] and digest(target)==item['sha256']:
        print('已验证 '+item['path'],flush=True);return target
    if target.exists():raise RuntimeError('已有文件校验不匹配，请先核对并移走该文件：'+str(target))
    partial=target.with_name(target.name+'.part')
    for attempt in range(3):
        offset=partial.stat().st_size if partial.exists() else 0
        if offset==item['size']:
            if digest(partial)==item['sha256']:os.replace(partial,target);return target
            raise RuntimeError('下载文件校验失败：'+str(partial))
        if offset>item['size']:raise RuntimeError('下载临时文件大于清单大小：'+str(partial))
        headers=dict(item.get('headers',{}))
        if offset:headers['Range']=f'bytes={offset}-'
        try:
            print(f"下载 {item['path']}，起点 {offset} 字节",flush=True)
            with urllib.request.urlopen(urllib.request.Request(item['url'],headers=headers),timeout=45) as response:
                if response.status==206:
                    if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('invalid resume range')
                    mode='ab'
                elif response.status==200:mode='wb';offset=0
                else:raise ValueError('unexpected download status')
                with partial.open(mode) as out:
                    while data:=response.read(1024*1024):
                        offset+=len(data)
                        if offset>item['size']:raise ValueError('asset exceeds declared size')
                        out.write(data)
            if partial.stat().st_size!=item['size']:raise OSError('下载尚未完整')
            if digest(partial)!=item['sha256']:raise ValueError('SHA256校验失败')
            os.replace(partial,target);return target
        except OSError:
            if attempt==2:raise
            time.sleep(1)
    raise RuntimeError('download failed')

def extract_zip(archive,destination):
    destination=destination.resolve()
    if not destination.is_relative_to(ROOT):raise ValueError('extraction path outside project')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if sum(i.file_size for i in infos)>2*1024**3:raise ValueError('archive too large')
        for info in infos:
            target=(destination/info.filename).resolve()
            if not target.is_relative_to(destination) or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('unsafe zip entry')
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            data=z.read(info)
            if target.exists():
                if target.read_bytes()!=data:raise RuntimeError('已有解压文件与归档不同：'+str(target))
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as out:out.write(data)

def extract_tar(archive,destination):
    destination=destination.resolve()
    if not destination.is_relative_to(ROOT):raise ValueError('extraction path outside project')
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        if len({m.name.split('/')[0] for m in members})!=1 or sum(m.size for m in members)>2*1024**3:raise ValueError('unexpected source archive')
        for member in members:
            pieces=member.name.split('/',1)
            if len(pieces)<2 or not pieces[1]:continue
            target=(destination/pieces[1]).resolve()
            if not target.is_relative_to(destination) or not (member.isdir() or member.isfile()):raise ValueError('unsafe tar entry')
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            with tar.extractfile(member) as stream:data=stream.read()
            if target.exists():
                if target.read_bytes()!=data:raise RuntimeError('已有源码文件与归档不同：'+str(target))
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as out:out.write(data)

def main():
    p=argparse.ArgumentParser();p.add_argument('--desktop',action='store_true');p.add_argument('--sdk',action='store_true');p.add_argument('--source',action='store_true');p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    assets=json.loads((ROOT/'assets.lock.json').read_text(encoding='utf8'))['assets']
    groups={'voice'}|({'desktop'} if a.desktop else set())|({'sdk'} if a.sdk else set())|({'source'} if a.source else set())
    for item in assets:
        if item['group'] not in groups:continue
        if a.verify_only:
            target=ROOT/item['path']
            if not target.is_file() or target.stat().st_size!=item['size'] or digest(target)!=item['sha256']:raise RuntimeError('校验失败：'+str(target))
            print('已验证 '+item['path']);continue
        file=download(item)
        if item.get('extract'):extract_zip(file,ROOT/item['extract'])
        if item.get('extract_tar'):extract_tar(file,ROOT/item['extract_tar'])
    print('选定资源准备完成。')
if __name__=='__main__':main()
