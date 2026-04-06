#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 缠论笔 - 修复版 v2
从 swing points 正确构建笔链

规则：
1. 找所有 swing points（顶底分型）→ 得到 (index, price, type) 序列
2. 笔：从一个点 → 下一个反向点（方向由起终点决定）
3. 最小笔幅度：10个点
4. 相邻同向笔合并
"""
import pandas as pd
import numpy as np
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import warnings
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'


def find_swing_points(bars):
    """找所有 swing points"""
    points = []
    for i in range(1, len(bars)-1):
        prev_h, curr_h, next_h = bars[i-1].high, bars[i].high, bars[i+1].high
        prev_l, curr_l, next_l = bars[i-1].low, bars[i].low, bars[i+1].low

        if curr_h > prev_h and curr_h > next_h:
            points.append((i, curr_h, 'H', bars[i].dt))
        if curr_l < prev_l and curr_l < next_l:
            points.append((i, curr_l, 'L', bars[i].dt))

    # 按 index 排序
    points.sort(key=lambda x: x[0])
    return points


def merge_consecutive_same_type(points):
    """合并相邻的同类型 swing points（保留最极值的那个）"""
    if not points:
        return []

    merged = [points[0]]
    for p in points[1:]:
        if p[2] == merged[-1][2]:  # 同类型
            # 保留更极值的
            if p[2] == 'H' and p[1] > merged[-1][1]:
                merged[-1] = p
            elif p[2] == 'L' and p[1] < merged[-1][1]:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def build_bi_chain(points, min_amplitude=10):
    """
    从 swing points 构建笔链
    points: [(index, price, type, datetime), ...]
    type: 'H' 或 'L'
    笔：从一个点到下一个反向点
    """
    if len(points) < 2:
        return []

    bis = []
    i = 0

    while i < len(points) - 1:
        p1 = points[i]
        # 找下一个反向点
        j = i + 1
        while j < len(points) - 1 and points[j][2] == p1[2]:
            j += 1

        if j >= len(points):
            break

        p2 = points[j]
        amp = abs(p2[1] - p1[1])

        if amp < min_amplitude:
            i = j
            continue

        direction = 'Up' if p2[1] > p1[1] else 'Down'
        bi_high = max(p1[1], p2[1])
        bi_low = min(p1[1], p2[1])

        bis.append({
            'direction': direction,
            'start_idx': p1[0],
            'end_idx': p2[0],
            'start_dt': p1[3],
            'end_dt': p2[3],
            'high': bi_high,
            'low': bi_low,
            'amplitude': amp,
        })
        i = j

    # 合并相邻同向小幅笔
    if not bis:
        return bis

    filtered = [bis[0]]
    for bi in bis[1:]:
        prev = filtered[-1]
        # 如果同向且当前笔幅度小于前一笔50%，合并
        if bi['direction'] == prev['direction']:
            if bi['amplitude'] < prev['amplitude'] * 0.5:
                # 合并
                prev['end_idx'] = bi['end_idx']
                prev['end_dt'] = bi['end_dt']
                prev['high'] = max(prev['high'], bi['high'])
                prev['low'] = min(prev['low'], bi['low'])
                prev['amplitude'] = abs(prev['high'] - prev['low'])
            else:
                filtered.append(bi)
        else:
            filtered.append(bi)

    return filtered


def main():
    # 加载4月3日数据
    df = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    april3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
    april3 = april3[april3['close'].notna() & (april3['close']>0)].sort_values('datetime').reset_index(drop=True)
    april3['real_time'] = april3['datetime'] + pd.Timedelta(hours=8)

    bars = []
    for i, (_, r) in enumerate(april3.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']),
            low=float(r['low']), close=float(r['close']),
            vol=float(r['volume']), amount=0, freq=Freq.F1))

    dt_to_idx = {b.dt: i for i, b in enumerate(bars)}

    # CZSC 严格笔
    c = CZSC(bars)
    czsc_bis = list(c.bi_list)

    # Swing 修复笔
    points = find_swing_points(bars)
    merged_pts = merge_consecutive_same_type(points)
    swing_bis = build_bi_chain(merged_pts, min_amplitude=10)

    print(f"CZSC笔: {len(czsc_bis)}笔")
    print(f"Swing笔: {len(swing_bis)}笔")
    print()

    # 对比
    print("=== 对比（CZSC vs Swing）===")
    max_len = max(len(czsc_bis), len(swing_bis))
    for i in range(max_len):
        cz = czsc_bis[i] if i < len(czsc_bis) else None
        sw = swing_bis[i] if i < len(swing_bis) else None

        cz_str = f"{str(cz.direction)[0]} {cz.edt.strftime('%H:%M')} | {cz.high:.0f}~{cz.low:.0f} | {cz.length}" if cz else "---"
        sw_str = f"{sw['direction'][0]} {sw['end_dt'].strftime('%H:%M')} | {sw['high']:.0f}~{sw['low']:.0f} | {sw['amplitude']:.0f}" if sw else "---"
        print(f"  [{i:2d}] CZSC: {cz_str}")
        print(f"  [{i:2d}] Swing: {sw_str}")
        print()

    # 关键区间对比
    print("=== 关键区间 10:35-10:55 ===")
    cz_key = [b for b in czsc_bis if hasattr(b, 'edt') and b.edt.strftime('%H:%M') >= '10:35']
    sw_key = [b for b in swing_bis if b['end_dt'].strftime('%H:%M') >= '10:35']

    print(f"CZSC 10:35后: {len(cz_key)}笔")
    print(f"Swing 10:35后: {len(sw_key)}笔")

    return bars, czsc_bis, swing_bis, dt_to_idx, april3


if __name__ == '__main__':
    bars, czsc_bis, swing_bis, dt_to_idx, april3 = main()
