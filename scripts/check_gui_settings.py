"""Exercise Tk settings persistence with a disposable config, without sensor/model use."""
import json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tkinter as tk
from tkinter import ttk
from edge_agent.config import load
from edge_agent.gui import App

def main():
    path=ROOT/'config'/('gui-test-'+uuid.uuid4().hex+'.json')
    path.write_bytes((ROOT/'config/linux-cpu.json').read_bytes())
    root=None;app=None
    try:
        root=tk.Tk();root.withdraw();app=App(root,load(path));app.settings()
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        fields=[w for w in dialog.winfo_children() if isinstance(w,ttk.Entry)]
        assert len(fields)==6
        output=fields[2];output.delete(0,'end');output.insert(0,'plughw:CARD=rockchipes8388,DEV=0')
        save=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Button) and w.cget('text')=='保存')
        save.invoke();root.update_idletasks()
        value=json.loads(path.read_text(encoding='utf8'))['audio_output_linux']
        assert value=='plughw:CARD=rockchipes8388,DEV=0' and app.c['audio_output_linux']==value
        assert not dialog.winfo_exists()
        print(json.dumps({'passed':True,'settings_fields':len(fields),'audio_output_linux':value,
                          'real_config_changed':False,'sensors_started':False},ensure_ascii=False))
    finally:
        if app:app.agent.close();app.server.close()
        if root:root.destroy()
        path.unlink(missing_ok=True)

if __name__=='__main__':main()
