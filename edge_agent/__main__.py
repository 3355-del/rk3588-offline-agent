"""python -m edge_agent --help"""
import argparse,json,sys
from .config import load,DEFAULT
from .agent import Agent
from .tools import execute
from .devices import capture,transcribe,speak

def main():
    parser=argparse.ArgumentParser(description='离线端侧智能体：通过配置选择真实模型，不会自动启动传感器')
    parser.add_argument('--config',default=str(DEFAULT))
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('ask');p.add_argument('text');p.add_argument('--image')
    sub.add_parser('chat');sub.add_parser('doctor');sub.add_parser('demo');sub.add_parser('gui');sub.add_parser('serve');sub.add_parser('console')
    p=sub.add_parser('alarms');p.add_argument('--limit',type=int,default=5);p.add_argument('--stream-id',type=int);p.add_argument('--since-ms',type=int)
    sub.add_parser('capture');sub.add_parser('record')
    p=sub.add_parser('transcribe');p.add_argument('path')
    p=sub.add_parser('speak');p.add_argument('text')
    p=sub.add_parser('voice-once');p.add_argument('--confirm',action='store_true',help='识别后确认、改正或重录再回答')
    args=parser.parse_args();config=load(args.config);agent=Agent(config)
    from .runtime import LocalServer
    server=LocalServer(config)
    try:
        if args.command in ('ask','chat','demo','voice-once','console'):server.start()
        return dispatch(args,config,agent)
    finally:agent.close();server.close()

def dispatch(args,config,agent):
    if args.command=='console':
        from types import SimpleNamespace
        while True:
            print('\n项目二板卡测试；backend='+config['backend'])
            print('同一窗口复用模型；首次请求加载，退出释放。取消或超时后下一次重新加载。')
            print('1 中文对话\n2 语音问答\n3 拍照并描述\n4 查询最近告警\n5 播放测试短句\n6 环境自检\n7 清空会话\n0 退出')
            try:
                choice=input('请选择：').strip()
                if choice=='0':break
                if choice=='1':dispatch(SimpleNamespace(command='chat'),config,agent)
                elif choice=='2':dispatch(SimpleNamespace(command='voice-once',confirm=True),config,agent)
                elif choice=='3':
                    image=capture(config,'image')
                    print(agent.ask('请简短描述图片中的物品，不推测人物身份。',image))
                elif choice=='4':dispatch(SimpleNamespace(command='alarms',limit=5,stream_id=None,since_ms=None),config,agent)
                elif choice=='5':speak('你好，这是项目二的扬声器测试。',config)
                elif choice=='6':dispatch(SimpleNamespace(command='doctor'),config,agent)
                elif choice=='7':agent.reset();print('已清空会话，保留模型。')
                else:print('请输入0到7。')
            except EOFError:break
            except KeyboardInterrupt:agent.cancel();print('\n本次操作已取消。')
            except Exception as exc:print('本次操作失败：'+str(exc))
    elif args.command=='ask':print(agent.ask(args.text,args.image))
    elif args.command=='doctor':
        from .doctor import report
        print(json.dumps(report(config),ensure_ascii=False,indent=2))
    elif args.command=='alarms':
        from .alarms import query
        print(json.dumps(query(config,args.limit,args.stream_id,args.since_ms),ensure_ascii=False,indent=2))
    elif args.command=='gui':
        from .gui import main as gui_main
        gui_main(config)
    elif args.command=='serve':
        from .runtime import LocalServer
        import time
        server=LocalServer(config)
        try:
            server.start();print('模型服务已就绪：'+config['server_url'],flush=True)
            while True:time.sleep(1)
        finally:server.close()
    elif args.command=='demo':
        for text in ['你好','查看设备状态','查询最近告警']:print('用户：'+text+'\n助手：'+agent.ask(text)+'\n')
    elif args.command=='capture':print(capture(config,'image'))
    elif args.command=='record':print(capture(config,'audio'))
    elif args.command=='transcribe':print(transcribe(config,args.path))
    elif args.command=='speak':speak(args.text,config)
    elif args.command=='voice-once':
        while True:
            print('开始录音，最长'+str(config['audio_seconds'])+'秒',flush=True)
            text=transcribe(config,capture(config,'audio'))
            if not text:raise RuntimeError('未识别到语音，请重试')
            print('识别：'+text)
            if getattr(args,'confirm',False):
                try:choice=input('回车确认；输入 /r 重录、/q 取消，或直接输入正确的问题：').strip()
                except EOFError:return
                if choice=='/q':return
                if choice=='/r':continue
                if choice:text=choice
            break
        answer=agent.ask(text);print(answer);speak(answer[:2000],config)
    elif args.command=='chat':
        print('输入 /quit 退出，/reset 清空当前会话；backend='+config['backend'])
        while True:
            try:text=input('你：').strip()
            except EOFError:break
            if text.lower() in ('/quit','quit','exit','退出','结束'):break
            if text in ('/reset','清空会话'):agent.reset();print('已清空');continue
            if not text:continue
            try:print('助手：'+agent.ask(text))
            except Exception as exc:print('本次请求失败：'+str(exc))
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\n已停止');sys.exit(130)
    except Exception as exc:print('错误：'+str(exc),file=sys.stderr);sys.exit(1)
