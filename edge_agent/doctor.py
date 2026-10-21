"""Read-only deployment preflight, without starting sensors or loading NPU models."""
import importlib.util,platform,shutil,sys,os
from pathlib import Path
from .devices import ffmpeg_path

def report(c):
    checks=[]
    def add(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':str(detail)})
    add('Python',sys.version_info>=(3,10),sys.version.split()[0])
    add('真实模型后端',c['backend']!='mock',c['backend'])
    from .asr import model_files
    asr=c.get('asr_backend','vosk')
    modules=('PIL','sherpa_onnx','numpy') if asr=='sensevoice' else ('PIL','vosk')
    for module in modules:add(module,importlib.util.find_spec(module) is not None,'已安装' if importlib.util.find_spec(module) else '缺少依赖')
    ff=ffmpeg_path();add('FFmpeg',ff is not None,ff or '缺少')
    add('中文ASR模型',all((Path(c['asr_model'])/name).is_file() for name in model_files(asr)),asr+': '+c['asr_model'])
    if platform.system()=='Linux':
        add('ALSA播放',shutil.which('aplay') is not None,c.get('audio_output_linux','default'))
        if c.get('tts_linux','espeak')=='piper':
            add('Piper',importlib.util.find_spec('piper') is not None,'离线中文神经语音')
            model=Path(c['piper_model'])
            add('Piper模型',model.is_file() and Path(str(model)+'.json').is_file(),model)
        else:add('中文TTS',shutil.which('espeak-ng') is not None,'espeak-ng')
    keys=('native_executable','rkllm_model','rknn_vision_model') if c['backend']=='rkllm_native' else ('llama_executable','gguf_model','gguf_projector') if 'llama_executable' in c else ()
    for key in keys:add(key,Path(c[key]).is_file(),c[key])
    if c['backend']=='rkllm_native':
        add('ARM64 Linux',platform.system()=='Linux' and platform.machine() in ('aarch64','arm64'),platform.platform())
        device=Path('/proc/device-tree/model')
        add('板卡型号可读',device.is_file(),device.read_bytes().rstrip(b'\0').decode(errors='replace') if device.is_file() else '当前不是已确认的目标板')
        driver=Path('/sys/kernel/debug/rknpu/version')
        try:version=driver.read_text().strip()
        except OSError:version='未读取到；到板后核对厂商驱动，不自动提权'
        add('NPU驱动版本',version!= '未读取到；到板后核对厂商驱动，不自动提权',version)
    root=Path(c['input_dir']);existing=root
    while not existing.exists():existing=existing.parent
    free=shutil.disk_usage(existing).free;add('可用磁盘',free>=1024**3,f'{free/1024**3:.1f} GiB')
    gui={'tkinter_available':importlib.util.find_spec('tkinter') is not None,
         'display_configured':platform.system()!='Linux' or bool(os.environ.get('DISPLAY')),
         'window_verified':False}
    return {'ready_for_software_run':all(x['ok'] for x in checks),'checks':checks,'gui':gui,'hardware_validated':False,'note':'此自检不验证摄像头、麦克风、扬声器或NPU推理；GUI字段不代表已成功创建窗口。须在目标板完成硬件验收。'}
