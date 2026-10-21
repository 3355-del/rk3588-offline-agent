"""Read-only viewer for saved final-audit/soak reports; Ctrl+C stops only this viewer."""
import argparse,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('audit',type=Path);args=parser.parse_args()
    folder=args.audit.resolve()
    if not folder.is_relative_to(ROOT/'data'):raise ValueError('audit must be in project data')
    deadline=time.monotonic()+10800
    while time.monotonic()<deadline:
        summary=json.loads((folder/'summary.json').read_text())
        if summary.get('completed') or summary.get('error'):
            print(json.dumps(summary,ensure_ascii=False),flush=True);return
        joint_log=folder/'cpu-joint-hour.log'
        phase='cpu-joint-hour' if joint_log.exists() else 'npu-hour'
        output=None
        if joint_log.exists():
            with joint_log.open() as file:first=file.readline().strip()
            if first:output=Path(first)
        elif 'npu-hour' not in summary['steps']:output=Path(summary['npu_result']).parent
        else:phase='guard-native-acceptance'
        row={'phase':phase,'completed_steps':summary['steps']}
        if output and output.resolve().is_relative_to(ROOT/'data'):
            try:
                data=json.loads((output/'progress.json').read_text())
                for key in ('elapsed_seconds','rounds','vision_rounds','alarm_checks','min_rss_kib','max_rss_kib','max_temperature_c','errors'):
                    row[key]=data.get(key)
            except (OSError,ValueError):row['status']='starting'
        print(json.dumps(row,ensure_ascii=False),flush=True)
        time.sleep(45)
    raise TimeoutError('progress viewer exceeded three hours; inspect the audit result')

if __name__=='__main__':main()
