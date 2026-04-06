#!/usr/bin/env python3
"""
PTA 缠论线段检测 - 修复XD3版

关键：反向新段形成后，还必须被破坏，才能确认原段结束
"""

import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'


def load_bars(date='2026-04-03'):
    df = pd.read_csv(f'{DATA}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    ap = df[df['datetime'].dt.date == pd.Timestamp(date).date()]
    good = ap['close'].notna() & (ap['close'] > 0)
    ap = ap[good].sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)
    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars


class BiBar:
    def __init__(self, bi_idx, dt, direction, start_p, end_p):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.start = start_p
        self.end = end_p


def get_bi_bars(c):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        result.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down', sp, ep))
    return result


def detect_xd(bi_bars):
    n = len(bi_bars)
    results = []
    i = 0

    while i < n - 2:
        b0, b1, b2 = bi_bars[i], bi_bars[i+1], bi_bars[i+2]
        if not (b0.direction != b1.direction and b1.direction != b2.direction):
            i += 1
            continue

        seg_start = i
        seg_dir = b0.direction
        seg_len = 3
        last_idx = i + 2
        j = i + 3
        destroyed = False

        while j < n:
            cur = bi_bars[j]
            if cur.direction != seg_dir:
                # 反向笔出现
                if j + 2 < n:
                    c0, c1, c2 = bi_bars[j], bi_bars[j+1], bi_bars[j+2]
                    if (c0.direction != c1.direction and c1.direction != c2.direction):
                        # 可以形成新段，检查是否被破坏
                        # 需要j+3存在，且下一笔与seg_dir同向（破坏新段）
                        if j + 3 < n and bi_bars[j+3].direction == seg_dir:
                            # 新段被破坏，原段结束
                            results.append((seg_start, last_idx, seg_dir))
                            i = j
                            destroyed = True
                            break
                        else:
                            # 新段未被破坏，原段继续
                            last_idx = j
                            seg_len += 1
                            j += 1
                    else:
                        last_idx = j
                        seg_len += 1
                        j += 1
                else:
                    last_idx = j
                    seg_len += 1
                    j += 1
            else:
                last_idx = j
                seg_len += 1
                j += 1

        if not destroyed:
            remaining = n - seg_start
            if remaining >= 3:
                results.append((seg_start, n - 1, seg_dir))
            break

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测")
    print("=" * 60)
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] {b.start:.0f} → {b.end:.0f}")

    print()
    results = detect_xd(bi_bars)

    print(f"检测结果: {len(results)}条线段")
    for r in results:
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  {r[2]:4s}  bi{r[0]+1}~bi{r[1]+1}  ({n_bi}笔)  "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}]  "
              f"{s.start:.0f} → {e.end:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()
