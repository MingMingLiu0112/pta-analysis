#!/usr/bin/env python3
"""
PTA 缠论线段检测 v8 - 最终版
核心条件：上行段被下行笔破坏 = 下行笔终点 < 上行段最后上行笔的低点
参考：用户确认的正确标准（2026-04-06）
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
        self.high = max(start_p, end_p)
        self.low = min(start_p, end_p)


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
    """
    笔破坏条件（用户确认版）：
    - 上行段：下行笔终点 < 上行段最后上行笔的低点 → 线段破坏
    - 下行段：上行笔终点 > 下行段最后下行笔的高点 → 线段破坏
    
    线段终点 = 反向笔的起点（破坏点）
    """
    n = len(bi_bars)
    results = []

    i = 0
    while i < n:
        cur = bi_bars[i]

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
        if next_idx is None:
            # 没有更多反向笔，当前段延续到结尾
            results.append((i, n - 1, cur.direction))
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # ===== 上行段检测 =====
            # 条件：下行笔终点 < 上行段最后上行笔的低点
            last_up_low = cur.low  # 最后上行笔自身的低点
            broken = next_bi.end < last_up_low

            print(f"\n上行段 bi{i+1}~bi{next_idx+1}: "
                  f"最后up笔低点={last_up_low:.0f}  "
                  f"反向dn笔终点={next_bi.end:.0f}  "
                  f"{'✓笔破坏' if broken else '✗未破坏'}")

            if broken:
                # 线段终点 = 反向笔的起点
                results.append((i, next_idx, 'up'))
                print(f"  → 上行段 bi{i+1}~bi{next_idx+1} 终点={next_bi.start:.0f}")
                i = next_idx
                continue

        elif cur.direction == 'down' and next_bi.direction == 'up':
            # ===== 下行段检测 =====
            last_dn_high = cur.high  # 最后下行笔自身的高点
            broken = next_bi.end > last_dn_high

            print(f"\n下行段 bi{i+1}~bi{next_idx+1}: "
                  f"最后dn笔高点={last_dn_high:.0f}  "
                  f"反向up笔终点={next_bi.end:.0f}  "
                  f"{'✓笔破坏' if broken else '✗未破坏'}")

            if broken:
                results.append((i, next_idx, 'down'))
                print(f"  → 下行段 bi{i+1}~bi{next_idx+1} 终点={next_bi.start:.0f}")
                i = next_idx
                continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测 v8")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f}")

    print("\n" + "=" * 60)
    results = detect_xd(bi_bars)
    print(f"\n检测结果: {len(results)}条线段")
    print("-" * 60)
    for r in results:
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  {r[2]:4s} bi{r[0]+1}~bi{r[1]+1} ({n_bi}笔) "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}] "
              f"{s.start:.0f} → {s.start:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()
