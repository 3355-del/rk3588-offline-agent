"""python -m edge_agent --help"""
import argparse,sys
from .config import load,DEFAULT
from .agent import Agent
from . import terminal
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
    args=parser.parse_args();config=load(args.config)
    from .runtime import LocalServer
    server=LocalServer(config)
    agent=Agent(config,prepare_model=server.start)
    try:
        return dispatch(args,config,agent)
    finally:
        try:
            agent.close()
        finally:
            server.close()

def dispatch(args,config,agent):
    if args.command=='console':
        terminal.console(config, agent)
    elif args.command=='ask':print(agent.ask(args.text,args.image))
    elif args.command=='doctor':
        terminal.print_doctor(config)
    elif args.command=='alarms':
        terminal.print_alarms(config, args.limit, args.stream_id, args.since_ms)
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
        terminal.voice_once(config, agent, confirm=getattr(args,'confirm',False))
    elif args.command=='chat':
        terminal.chat(config, agent)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\n已停止');sys.exit(130)
    except Exception as exc:print('错误：'+str(exc),file=sys.stderr);sys.exit(1)
