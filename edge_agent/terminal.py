"""Terminal workflows for the board menu and one-shot commands."""

import json

from .alarms import query
from .devices import capture, speak, transcribe
from .doctor import report


def print_alarms(config, limit=5, stream_id=None, since_ms=None):
    print(json.dumps(query(config, limit, stream_id, since_ms), ensure_ascii=False, indent=2))


def print_doctor(config):
    print(json.dumps(report(config), ensure_ascii=False, indent=2))


def console(config, agent):
    while True:
        print('\n项目二板卡测试；backend='+config['backend'])
        print('同一窗口复用模型；首次请求加载，退出释放。取消或超时后下一次重新加载。')
        print('1 中文对话\n2 语音问答\n3 拍照并描述\n4 查询最近告警\n5 播放测试短句\n6 环境自检\n7 清空会话\n0 退出')
        try:
            choice=input('请选择：').strip()
            if choice=='0':break
            if choice=='1':chat(config, agent)
            elif choice=='2':voice_once(config, agent, confirm=True)
            elif choice=='3':
                image=capture(config,'image')
                print(agent.ask('请简短描述图片中的物品，不推测人物身份。',image))
            elif choice=='4':print_alarms(config)
            elif choice=='5':speak('你好，这是项目二的扬声器测试。',config)
            elif choice=='6':print_doctor(config)
            elif choice=='7':agent.reset();print('已清空会话，保留模型。')
            else:print('请输入0到7。')
        except EOFError:
            break
        except KeyboardInterrupt:
            agent.cancel()
            print('\n本次操作已取消。')
        except Exception as exc:
            print('本次操作失败：'+str(exc))


def voice_once(config, agent, *, confirm=False):
    while True:
        print('开始录音，最长'+str(config['audio_seconds'])+'秒',flush=True)
        text=transcribe(config,capture(config,'audio'))
        if not text:raise RuntimeError('未识别到语音，请重试')
        print('识别：'+text)
        if confirm:
            try:choice=input('回车确认；输入 /r 重录、/q 取消，或直接输入正确的问题：').strip()
            except EOFError:return
            if choice=='/q':return
            if choice=='/r':continue
            if choice:text=choice
        break
    answer=agent.ask(text);print(answer);speak(answer[:2000],config)


def chat(config, agent):
    print('输入 /quit 退出，/reset 清空当前会话；backend='+config['backend'])
    while True:
        try:text=input('你：').strip()
        except EOFError:break
        if text.lower() in ('/quit','quit','exit','退出','结束'):break
        if text in ('/reset','清空会话'):agent.reset();print('已清空');continue
        if not text:continue
        try:
            print('助手：'+agent.ask(text))
        except KeyboardInterrupt:
            agent.cancel()
            print('\n本次请求已取消。')
        except Exception as exc:
            print('本次请求失败：'+str(exc))

