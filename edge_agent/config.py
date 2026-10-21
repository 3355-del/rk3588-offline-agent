"""Validated config; all paths are relative to the config file, not the shell cwd."""
import json,ipaddress
from pathlib import Path
from urllib.parse import urlsplit
DEFAULT=Path(__file__).resolve().parents[1]/'config/default.json'
def load(path=DEFAULT):
    path=Path(path).resolve();c=json.loads(path.read_text(encoding='utf-8-sig'))
    c.setdefault('asr_backend','vosk');c.setdefault('asr_threads',2)
    if c['asr_backend'] not in ('vosk','sensevoice'):raise ValueError('invalid asr_backend')
    if type(c['asr_threads']) is not int or not 1<=c['asr_threads']<=4:raise ValueError('invalid asr_threads: expected integer 1..4')
    if c.get('backend') not in ('mock','rkllm_http','rkllm_native'):raise ValueError('invalid backend')
    for k,lo,hi in [('request_timeout',1,600),('max_tokens',1,2048),('history_turns',1,12),('max_context_chars',256,16000),('input_limit_mb',1,16),('capture_width',64,1920),('capture_height',64,1080),('audio_seconds',1,30)]:
        if type(c.get(k)) is not int or not lo<=c[k]<=hi:raise ValueError(f'invalid {k}: expected integer {lo}..{hi}')
    if type(c.get('supports_images')) is not bool:raise ValueError('supports_images must be boolean')
    u=urlsplit(c.get('server_url',''))
    try:ip=ipaddress.ip_address(u.hostname or '')
    except ValueError:raise ValueError('server_url must use a numeric loopback IP') from None
    if u.scheme!='http' or not ip.is_loopback or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
        raise ValueError('only a local loopback HTTP model service is allowed')
    _=u.port
    if not isinstance(c.get('model'),str) or not c['model']:raise ValueError('missing model')
    for k in ['alarm_db','input_dir','asr_model']:
        if not isinstance(c.get(k),str) or not c[k]:raise ValueError(f'missing {k}')
        c[k]=str((path.parent/c[k]).resolve())
    for k in ['camera_linux','camera_windows','audio_linux','audio_windows']:
        if not isinstance(c.get(k),str):raise ValueError(f'invalid {k}')
    c.setdefault('alarm_screenshot_dir','../../项目-基于 RK3588 的多路边缘目标检测告警系统/screenshots')
    c.setdefault('audio_output_linux','default')
    if not isinstance(c['audio_output_linux'],str) or not c['audio_output_linux'].strip():
        raise ValueError('invalid audio_output_linux')
    c.setdefault('tts_linux','espeak')
    if c['tts_linux'] not in ('espeak','piper'):raise ValueError('invalid tts_linux')
    if c['tts_linux']=='piper':
        if not isinstance(c.get('piper_model'),str) or not c['piper_model']:raise ValueError('missing piper_model')
        c['piper_model']=str((path.parent/c['piper_model']).resolve())
    for k in ['alarm_screenshot_dir','native_executable','rkllm_model','rknn_vision_model','llama_executable','gguf_model','gguf_projector']:
        if k in c:
            if not isinstance(c[k],str) or not c[k]:raise ValueError(f'invalid {k}')
            c[k]=str((path.parent/c[k]).resolve())
    for k,default,lo,hi in [('vision_width',448,28,2048),('vision_height',448,28,2048),('context_tokens',4096,512,8192),('cpu_threads',4,1,16)]:
        c.setdefault(k,default)
        if type(c[k])is not int or not lo<=c[k]<=hi:raise ValueError(f'invalid {k}')
    c.setdefault('enable_tools',True)
    c.setdefault('native_resident',True)
    if type(c['native_resident'])is not bool:raise ValueError('native_resident must be boolean')
    if type(c['enable_tools'])is not bool:raise ValueError('enable_tools must be boolean')
    if c['backend']=='rkllm_native':
        for k in ['native_executable','rkllm_model','rknn_vision_model']:
            if k not in c:raise ValueError(f'missing {k}')
    c['_config_path']=str(path)
    return c
