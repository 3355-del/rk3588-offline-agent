"""Allowlisted read-only tools. Models cannot execute shell commands or pick paths."""
import json,platform,shutil,sqlite3
from pathlib import Path
from contextlib import closing
TOOLS=[{'type':'function','function':{'name':'device_status','description':'查询本地运行环境及配置；不启动传感器。','parameters':{'type':'object','properties':{},'additionalProperties':False}}}, {'type':'function','function':{'name':'recent_alarms','description':'读取项目一已落库的最近告警。','parameters':{'type':'object','properties':{'limit':{'type':'integer','minimum':1,'maximum':20}},'additionalProperties':False}}}]

def system_hardware():
    result={'board_model':None,'memory_total_mib':None}
    if platform.system()=='Linux':
        try:result['board_model']=Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode('utf8','replace') or None
        except OSError:pass
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                fields=line.split()
                if len(fields)==3 and fields[0]=='MemTotal:' and fields[2]=='kB':
                    result['memory_total_mib']=round(int(fields[1])/1024,1);break
        except (OSError,ValueError):pass
    return result
def execute(name,args,c):
    if not isinstance(args,dict):raise ValueError('tool arguments must be an object')
    if name=='device_status':
        if args:raise ValueError('device_status takes no arguments')
        from .devices import ffmpeg_path
        return {'os':platform.system(),'architecture':platform.machine(),'backend':c['backend'],'model':c['model'],'ffmpeg_available':bool(ffmpeg_path()),'camera_config':c['camera_linux'] if platform.system()=='Linux' else c['camera_windows'],'sensors_started':False,**system_hardware()}
    if name=='recent_alarms':
        if set(args)-{'limit'}:raise ValueError('unexpected alarm query argument')
        limit=args.get('limit',5)
        if type(limit)is not int or not 1<=limit<=20:raise ValueError('limit must be 1..20')
        path=Path(c['alarm_db'])
        if not path.is_file():return {'available':False,'reason':'项目一告警数据库尚未创建','alarms':[]}
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            rows=db.execute('SELECT event_id,payload,received_at FROM alarms ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return {'available':True,'alarms':[{'event_id':eid,'received_at':stamp,'event':{k:v for k,v in json.loads(payload).items() if k in ('timestamp_ms','stream_id','region_id','class_name','confidence','screenshot')}} for eid,payload,stamp in rows]}
    raise ValueError('tool not allowed: '+str(name))
