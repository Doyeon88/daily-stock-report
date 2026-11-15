"""
watchlist.json의 report_time(KST)·report_days를 GitHub Actions 스케줄(cron, UTC)로 바꿔 워크플로 파일에 반영합니다.

사용법:  python scripts/sync_schedule.py        (워크플로를 고쳐 쓰고 결과를 출력)
         python scripts/sync_schedule.py --check (고치지 않고 일치 여부만 확인, 불일치면 종료 코드 1)
시각을 바꾼 뒤 이 스크립트를 실행하고 커밋·푸시하면 됩니다. GitHub의 cron은 몇 분 늦게 시작될 수 있습니다.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, '.github', 'workflows', 'daily_report.yml')
WATCHLIST = os.path.join(ROOT, 'watchlist.json')
KST_OFFSET_HOURS = 9
DAY_NUMBERS = {'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6}


def parse_days(spec: str):
    """'tue-sat', 'mon,wed,fri' or 'daily' -> sorted list of weekday numbers (0=Sun, KST)"""
    spec = spec.strip().lower()
    if spec in ('daily', 'everyday', '*'):
        return list(range(7))
    days = set()
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            a, b = (DAY_NUMBERS[x.strip()] for x in part.split('-'))
            days.update((a + i) % 7 for i in range((b - a) % 7 + 1))
        else:
            days.add(DAY_NUMBERS[part])
    return sorted(days)


def kst_to_cron(time_text: str, days_spec: str) -> str:
    """KST 'HH:MM' + weekdays -> UTC cron expression (the weekday moves back a day when KST hour < 9)"""
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', time_text.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"report_time must look like '07:00', got {time_text!r}")
    hour, minute = int(match[1]), int(match[2])
    total = hour * 60 + minute - KST_OFFSET_HOURS * 60
    shift = 0
    if total < 0:
        total += 24 * 60
        shift = -1
    days = sorted((d + shift) % 7 for d in parse_days(days_spec))
    dow = '*' if len(days) == 7 else ','.join(str(d) for d in days)
    return f"{total % 60} {total // 60} * * {dow}"


def main(argv):
    with open(WATCHLIST, encoding='utf-8') as f:
        watchlist = json.load(f)
    time_text, days_spec = watchlist.get('report_time', '07:00'), watchlist.get('report_days', 'tue-sat')
    cron = kst_to_cron(time_text, days_spec)

    with open(WORKFLOW, encoding='utf-8') as f:
        text = f.read()
    comment = f"    # {days_spec} {time_text} KST (scripts/sync_schedule.py가 watchlist.json에서 만든 값)\n"
    pattern = re.compile(r"(    # [^\n]*\n)*    - cron: '[^']*'\n")
    new_text, count = pattern.subn(comment + f"    - cron: '{cron}'\n", text, count=1)
    if count != 1:
        print("워크플로에서 cron 줄을 찾지 못했습니다.", file=sys.stderr)
        return 2
    if '--check' in argv:
        print('일치' if new_text == text else f"불일치: 워크플로 cron을 '{cron}'으로 맞춰야 합니다")
        return 0 if new_text == text else 1
    with open(WORKFLOW, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"{days_spec} {time_text} KST -> cron '{cron}' (UTC)")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
