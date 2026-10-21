"""Actual alarm queries and screenshot import with a confined source directory."""
import json,sqlite3,uuid,shutil
from pathlib import Path
from contextlib import closing

def query(config,limit=10,stream_id=None,since_ms=None):
    if type(limit)is not int or not 1<=limit<=100:raise ValueError('limit must be 1..100')
    if stream_id is not None and (type(stream_id)is not int or stream_id<0):raise ValueError('invalid stream id')
    if since_ms is not None and (type(since_ms)is not int or since_ms<0):raise ValueError('invalid timestamp')
    p=Path(config['alarm_db'])
    if not p.is_file():return {'available':False,'alarms':[],'reason':'项目一告警数据库尚未创建'}
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        # JSON1 ships with supported Python SQLite. Filter at DB, not just last page.
        clauses=[];args=[]
        if stream_id is not None:clauses.append("json_extract(payload,'$.stream_id')=?");args.append(stream_id)
        if since_ms is not None:clauses.append("json_extract(payload,'$.timestamp_ms')>=?");args.append(since_ms)
        sql='SELECT event_id,payload,received_at FROM alarms'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY id DESC LIMIT ?'
        records=db.execute(sql,args+[limit]).fetchall()
    return {'available':True,'alarms':[{'event_id':eid,'event':json.loads(payload),'received_at':at} for eid,payload,at in records]}

def snapshot(config,event_id):
    if not isinstance(event_id,str) or not 1<=len(event_id)<=128:raise ValueError('invalid event_id')
    dbpath=Path(config['alarm_db'])
    if not dbpath.is_file():raise ValueError('告警库尚未创建')
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        row=db.execute('SELECT payload FROM alarms WHERE event_id=?',(event_id,)).fetchone()
    if not row:raise ValueError('未找到指定告警')
    event=json.loads(row[0]);name=event.get('screenshot','')
    if not isinstance(name,str) or not name or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('该告警没有可安全读取的截图文件名')
    root=Path(config['alarm_screenshot_dir']).resolve();source=(root/name).resolve()
    if not source.is_relative_to(root) or not source.is_file():raise ValueError('截图不存在或越出配置目录')
    if source.stat().st_size>config['input_limit_mb']*1024*1024:raise ValueError('告警截图超过输入大小限制')
    dest=Path(config['input_dir'])/(uuid.uuid4().hex+source.suffix.lower());dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,dest)
    return dest,event

def readable(result):
    if not result.get('available'):return result.get('reason','告警数据不可用')
    rows=result['alarms']
    if not rows:return '查询范围内没有已入库的告警。'
    return '\n'.join(f"{i}. 路号 {r['event'].get('stream_id','?')}，区域 {r['event'].get('region_id','?')}，类别 {r['event'].get('class_name','?')}，事件ID {r.get('event_id')}" for i,r in enumerate(rows,1))
