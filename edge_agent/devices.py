"""Explicit device actions: ordinary chat never acquires cameras or microphones."""
import json,platform,shutil,subprocess,uuid,wave,sys,tempfile,threading
from pathlib import Path
from .process import run,Cancelled

def ffmpeg_path():
    path=shutil.which('ffmpeg')
    if path:return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError):return None

def capture(config,kind,cancel=None):
    if kind not in ('image','audio'):raise ValueError('invalid capture kind')
    ffmpeg=ffmpeg_path()
    if not ffmpeg:raise RuntimeError('缺少FFmpeg；请先安装项目依赖')
    root=Path(config['input_dir']);root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<256*1024*1024:raise RuntimeError('输入目录剩余空间不足256MiB')
    out=root/(uuid.uuid4().hex+('.png' if kind=='image' else '.wav'))
    system=platform.system();linux=system=='Linux'
    if system not in ('Linux','Windows'):raise RuntimeError('采集仅支持Linux/Windows')
    camera=kind=='image';key=('camera_' if camera else 'audio_')+('linux' if linux else 'windows');device=config[key]
    if not device:raise ValueError(f'请先在配置文件填写 {key} 设备名')
    args=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-n']
    if linux:args+=['-f','v4l2' if camera else 'alsa']
    else:args+=['-f','dshow'];device=('video=' if camera else 'audio=')+device
    if camera:args+=['-video_size',f"{config['capture_width']}x{config['capture_height']}"]
    args+=['-i',device]
    args+=['-frames:v','1'] if camera else ['-t',str(config['audio_seconds']),'-ac','1','-ar','16000','-c:a','pcm_s16le']
    try:
        run(args+[str(out)],15 if camera else config['audio_seconds']+10,cancel)
        if not out.is_file() or out.stat().st_size==0:raise RuntimeError('采集未生成有效文件')
        return out
    except BaseException:
        out.unlink(missing_ok=True);raise

def transcribe(config,path,cancel=None):
    p=Path(path).resolve()
    if not p.is_relative_to(Path(config['input_dir']).resolve()) or not p.is_file():raise ValueError('音频必须位于inputs目录')
    if p.stat().st_size>2*1024*1024:raise ValueError('音频过大，请使用30秒以内单声道WAV')
    with wave.open(str(p),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('需要16kHz、16bit、单声道PCM WAV')
        if wav.getnframes()>30*16000:raise ValueError('音频超过30秒')
    from .asr import model_files
    backend=config.get('asr_backend','vosk')
    if not all((Path(config['asr_model'])/name).is_file() for name in model_files(backend)):
        raise RuntimeError(f'缺少完整的本地{backend}中文模型')
    with tempfile.TemporaryDirectory(prefix='edge-asr-') as folder:
        output=Path(folder)/'text.txt'
        run([sys.executable,'-X','utf8','-m','edge_agent.voice_worker'],120,cancel,json.dumps({'kind':'asr','path':str(p),'model':config['asr_model'],'backend':backend,'threads':config.get('asr_threads',2),'output':str(output)}))
        return output.read_text(encoding='utf8').strip()

def synthesize(config,text,cancel=None):
    if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('播报文本须为1~2000字')
    root=Path(config['input_dir']);root.mkdir(parents=True,exist_ok=True);out=root/(uuid.uuid4().hex+'.wav')
    try:
        if platform.system()=='Windows':
            run([sys.executable,'-X','utf8','-m','edge_agent.voice_worker'],120,cancel,json.dumps({'kind':'tts','text':text,'output':str(out)}))
        elif config.get('tts_linux','espeak')=='piper':
            model=Path(config['piper_model'])
            if not model.is_file() or not Path(str(model)+'.json').is_file():
                raise RuntimeError('缺少Piper离线中文模型及配套JSON配置')
            run([sys.executable,'-m','piper','-m',str(model),'-f',str(out)],120,cancel,text)
        else:
            engine=shutil.which('espeak-ng')
            if not engine:raise RuntimeError('请先安装espeak-ng及中文语音')
            run([engine,'-v','cmn','-w',str(out),'--stdin'],120,cancel,text)
        if not out.is_file() or out.stat().st_size<44:raise RuntimeError('语音合成未生成有效WAV')
        return out
    except BaseException:
        out.unlink(missing_ok=True);raise

def speak(text,config=None,cancel=None):
    if config is None:
        from .config import load
        config=load()
    cancel=cancel or threading.Event();audio=synthesize(config,text,cancel)
    try:
        if platform.system()=='Windows':
            import winsound
            with wave.open(str(audio),'rb') as wav:duration=wav.getnframes()/wav.getframerate()
            winsound.PlaySound(str(audio),winsound.SND_FILENAME|winsound.SND_ASYNC)
            try:
                if cancel.wait(duration+.2):raise Cancelled('已停止播报')
            finally:winsound.PlaySound(None,0)
        else:
            player=shutil.which('aplay')
            if not player:raise RuntimeError('缺少alsa-utils/aplay，已完成合成但无法播放')
            run([player,'-q','-D',config.get('audio_output_linux','default'),str(audio)],150,cancel)
    finally:audio.unlink(missing_ok=True)

def import_input(config,source,kind='image'):
    source=Path(source).resolve();allowed={'.png','.jpg','.jpeg'} if kind=='image' else {'.wav'}
    if not source.is_file() or source.suffix.lower() not in allowed:raise ValueError('不支持的输入文件格式')
    if source.stat().st_size>config['input_limit_mb']*1024*1024:raise ValueError('输入文件过大')
    root=Path(config['input_dir']);root.mkdir(parents=True,exist_ok=True)
    dest=root/(uuid.uuid4().hex+source.suffix.lower());shutil.copyfile(source,dest)
    return dest

def list_devices(cancel=None):
    if platform.system()=='Windows':
        ff=ffmpeg_path()
        if not ff:raise RuntimeError('缺少FFmpeg')
        return run([ff,'-hide_banner','-list_devices','true','-f','dshow','-i','dummy'],15,cancel,allow_failure=True)
    result=[]
    for entry in sorted(Path('/sys/class/video4linux').glob('video*')):
        try:name=(entry/'name').read_text().strip()
        except OSError:name='名称不可读'
        result.append(f'/dev/{entry.name}: {name}')
    for tool in ('arecord','aplay'):
        path=shutil.which(tool)
        result.append(run([path,'-L'],10,cancel,allow_failure=True) if path else tool+' 未安装')
    return '\n'.join(result) or '没有找到可列举的设备。'
