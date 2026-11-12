"""Actual alarm queries and screenshot import with a confined source directory."""
import json,sqlite3,uuid,shutil
from datetime import datetime, time, timedelta
from pathlib import Path
from contextlib import closing

def query(config,limit=10,stream_id=None,since_ms=None,until_ms=None):
    if type(limit)is not int or not 1<=limit<=100:raise ValueError('limit must be 1..100')
    if stream_id is not None and (type(stream_id)is not int or stream_id<0):raise ValueError('invalid stream id')
    if since_ms is not None and (type(since_ms)is not int or since_ms<0):raise ValueError('invalid timestamp')
    if until_ms is not None and (type(until_ms)is not int or until_ms<0):raise ValueError('invalid timestamp')
    p=Path(config['alarm_db']).resolve()
    if not p.is_file():return {'available':False,'alarms':[],'reason':'项目一告警数据库尚未创建'}
    clauses, args = [], []
    for field, operator, value in (
        ('stream_id', '=', stream_id),
        ('timestamp_ms', '>=', since_ms),
        ('timestamp_ms', '<', until_ms),
    ):
        if value is not None:
            clauses.append(f"json_extract(payload,'$.{field}'){operator}?")
            args.append(value)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    try:
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            records = db.execute(
                'SELECT event_id,payload,received_at FROM alarms'+where+' ORDER BY id DESC LIMIT ?',
                args+[limit],
            ).fetchall()
        rows = []
        for event_id, payload, received_at in records:
            event = json.loads(payload)
            if not isinstance(event, dict):
                raise ValueError('invalid alarm payload')
            rows.append({'event_id':event_id, 'event':event, 'received_at':received_at})
        return {'available':True, 'alarms':rows}
    except (sqlite3.Error, ValueError):
        return {'available':False, 'alarms':[], 'reason':'项目一告警数据库暂时无法读取'}

def today(config, limit=10):
    day = datetime.now().date()
    start = datetime.combine(day, time.min)
    end = datetime.combine(day + timedelta(days=1), time.min)
    return query(config, limit, since_ms=int(start.timestamp()*1000),
                 until_ms=int(end.timestamp()*1000))

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
    lines=[]
    for i,row in enumerate(rows,1):
        event=row['event']
        text=(f"{i}. 路号 {event.get('stream_id','?')}，区域 {event.get('region_id','?')}，"
              f"类别 {event.get('class_name','?')}")
        track=event.get('track_id')
        if type(track) is int and track>0:
            text+=f"，目标 #{track}"
        lines.append(f"{text}，事件ID {row.get('event_id')}")
    return '\n'.join(lines)
