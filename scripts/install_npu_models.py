"""Install explicitly selected local NPU model pair, preserving existing files."""
import argparse,hashlib,json,os,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def copy_model(source,dest,suffix):
    source=Path(source).resolve()
    if source.suffix.lower()!=suffix or not source.is_file():raise ValueError('不是有效的模型文件路径：'+str(source))
    if not 1024*1024<=source.stat().st_size<=8*1024**3:raise ValueError('模型文件大小异常')
    h=hashlib.sha256()
    with source.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    sha=h.hexdigest()
    if dest.exists():
        other=hashlib.sha256()
        with dest.open('rb') as f:
            for data in iter(lambda:f.read(1024*1024),b''):other.update(data)
        if sha!=other.hexdigest():raise RuntimeError('已有不同模型，拒绝覆盖：'+str(dest))
    else:
        temp=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.tmp')
        try:shutil.copyfile(source,temp);os.replace(temp,dest)
        finally:temp.unlink(missing_ok=True)
    return {'file':dest.name,'sha256':sha,'bytes':source.stat().st_size}

def main():
    p=argparse.ArgumentParser(description='安装本地 Qwen3-VL-2B RK3588 配套模型；不下载、不执行模型')
    p.add_argument('--llm',required=True);p.add_argument('--vision',required=True)
    p.add_argument('--width',type=int,required=True);p.add_argument('--height',type=int,required=True)
    p.add_argument('--source',required=True,help='模型来源与导出工具版本说明，用于后续核对')
    a=p.parse_args()
    if not 28<=a.width<=2048 or not 28<=a.height<=2048:raise ValueError('图像尺寸超出范围')
    folder=ROOT/'models/rk3588';folder.mkdir(parents=True,exist_ok=True)
    size=sum(Path(s).stat().st_size for s in (a.llm,a.vision))
    if shutil.disk_usage(folder).free<size+256*1024**2:raise RuntimeError('剩余空间不足')
    models=[copy_model(a.llm,folder/'llm.rkllm','.rkllm'),copy_model(a.vision,folder/'vision.rknn','.rknn')]
    config=ROOT/'config/rk3588-native.json';c=json.loads(config.read_text(encoding='utf8'));c.update(vision_width=a.width,vision_height=a.height)
    temp=config.with_suffix('.json.tmp');temp.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,config)
    (folder/'model-pair.json').write_text(json.dumps({'source':a.source,'model_family':'Qwen3-VL-2B','target':'rk3588','width':a.width,'height':a.height,'models':models,'hardware_validated':False},ensure_ascii=False,indent=2),encoding='utf8')
    print('本地模型已安装并记录SHA256。文件存在不等于版本兼容，仍须在板端运行验收。')
if __name__=='__main__':main()
