#!/usr/bin/env python3
"""
PTA 缠论线段检测 - 正确版
核心规则：
- 反向笔出现时，gap封闭(reversal signal) → 不立即确认
- 需等下一个反向走势确认：若下一走势不创新高/低，则反转确认，线段结束
- 若下一走势创新高/低，则反转被拒绝，线段延续

上行段被下行笔破坏：
  1. gap封闭：下行笔.low < 前一上行笔.high → reversal signal
  2. 确认：下一个上行笔是否创新高？
     - 不新高(≤前高) → 反转确认 → 线段结束于该下行笔的起点
     - 创新高(>前高) → 反转被拒 → 线段延续

下行段被上行笔破坏：
  1. gap封闭：上行笔.high > 前一下行笔.low
  2. 确认：下一个下行笔是否新低？
     - 不新低(≥前低) → 反转确认
     - 新低(<前低) → 反转被拒
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
    n = len(bi_bars)
    results = []

    i = 0
    while i < n:
        cur = bi_bars[i]
        xd_start = i

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
        if next_idx is None:
            results.append((xd_start, n - 1, cur.direction))
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # ===== 上行段末尾出现下行笔 =====
            # 找前一上行笔（用于gap判断）
            prev_up_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break

            if prev_up_idx is not None:
                prev_up_high = bi_bars[prev_up_idx].high
                gap_closed = next_bi.low < prev_up_high  # reversal signal

                print(f"\n候选 bi{next_idx+1}(dn): gap={gap_closed}")

                if gap_closed:
                    # 找下一个上行笔（确认走势）
                    confirm_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'up':
                            confirm_idx = j
                            break

                    if confirm_idx is not None:
                        confirm = bi_bars[confirm_idx]
                        # 确认：下一个上行笔是否创新高？
                        if confirm.end <= prev_up_high:
                            # 不新高 → 反转确认！
                            results.append((xd_start, next_idx, 'up'))
                            print(f"  ✓ 反转确认! bi{xd_start+1}~bi{next_idx+1} "
                                  f"(bi{confirm_idx+1}不新高{confirm.end:.0f}≤{prev_up_high:.0f})")
                            i = next_idx
                            continue
                        else:
                            # 创新高 → 反转被拒，线段延续
                            print(f"  ✗ 反转被拒(bi{confirm_idx+1}新高{confirm.end:.0f}>{prev_up_high:.0f})，延续")
                    else:
                        # 没有下一个上行笔 → 反转自动确认！
                        results.append((xd_start, next_idx, 'up'))
                        print(f"  ✓ 反转确认(无确认走势)! bi{xd_start+1}~bi{next_idx+1}")
                        i = next_idx
                        continue

        elif cur.direction == 'down' and next_bi.direction == 'up':
            # ===== 下行段末尾出现上行笔 =====
            prev_dn_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'down':
                    prev_dn_idx = k
                    break

            if prev_dn_idx is not None:
                prev_dn_low = bi_bars[prev_dn_idx].low
                gap_closed = next_bi.high > prev_dn_low

                print(f"\n候选 bi{next_idx+1}(up): gap={gap_closed}")

                if gap_closed:
                    confirm_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'down':
                            confirm_idx = j
                            break

                    if confirm_idx is not None:
                        confirm = bi_bars[confirm_idx]
                        if confirm.end >= prev_dn_low:
                            # 不新低 → 反转确认！
                            results.append((xd_start, next_idx, 'down'))
                            print(f"  ✓ 反转确认! bi{xd_start+1}~bi{next_idx+1} "
                                  f"(bi{confirm_idx+1}不新低{confirm.end:.0f}≥{prev_dn_low:.0f})")
                            i = next_idx
                            continue
                        else:
                            print(f"  ✗ 反转被拒(bi{confirm_idx+1}新低{confirm.end:.0f}<{prev_dn_low:.0f})，延续")
                    else:
                        results.append((xd_start, next_idx, 'down'))
                        print(f"  ✓ 反转确认(无确认走势)! bi{xd_start+1}~bi{next_idx+1}")
                        i = next_idx
                        continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f}")

    print("\n" + "=" * 60