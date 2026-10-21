"""Isolated speech worker; cancellation releases model and SAPI resources."""
import sys,json,wave,os
from pathlib import Path
def main():
    job=json.loads(sys.stdin.read(65536))
    if job['kind']=='asr':
        from .asr import recognize
        text=recognize(job['path'],job['model'],job.get('backend','vosk'),job.get('threads',2))
        Path(job['output']).write_text(text,encoding='utf8')
    elif job['kind']=='tts':
        import pyttsx3
        engine=pyttsx3.init()
        try:
            selected=None
            for voice in engine.getProperty('voices'):
                fields=(voice.id+' '+voice.name+' '+str(voice.languages)).lower()
                if any(tag in fields for tag in ('chinese','zh-cn','zh_cn','huihui','mandarin','cmn')):selected=voice.id;break
            if selected is None:raise RuntimeError('本机未安装中文语音包')
            engine.setProperty('voice',selected);engine.setProperty('rate',165)
            engine.save_to_file(job['text'],job['output']);engine.runAndWait()
        finally:engine.stop()
        p=Path(job['output'])
        if not p.is_file() or p.stat().st_size<44:raise RuntimeError('语音合成未生成音频')
    else:raise ValueError('unsupported speech action')
if __name__=='__main__':main()
