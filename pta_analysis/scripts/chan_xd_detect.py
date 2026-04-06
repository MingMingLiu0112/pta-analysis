#!/usr/bin/env python3
"""
PTA 缠论线段检测 - 无未来函数版本

规则（根据缠论原文）：
1. 特征序列：反向笔当K线
2. 分型：顶分型（高高高）/ 底分型（低低低）
3. 线段破坏：笔终点跌破上升线段最低点
4. 常规情形：缺口封闭（回调低点 < 前一上行笔高点）→ 反弹不新高再回落成顶分型 → 立即确认
5. 非常规情形：缺口未封闭 → 需等下行段特征序列出底分型才能同时确认

无未来函数：确认必须两步走，先候选，再验证。
"""

import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq


def load_bars(date='2026-04-03'):
    """加载数据"""
    DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'
    df = pd.read_csv(f'{DATA}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    ap = df[df['datetime'].dt.date == pd.Timestamp(date).date()]
    ap = ap[(ap['close'].notna()) & (ap['close'] > 0)]
    ap = ap.sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)

    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars


class BiBar:
    """笔当K线"""
    def __init__(self, bi_idx, dt, direction, start_p, end_p, start_bar_idx, end_bar_idx):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction  # 'up' or 'down'
        self.open = start_p
        self.close = end_p
        self.high = max(start_p, end_p)
        self.low = min(start_p, end_p)


def get_bi_bars(c, d2i):
    """从CZSC获取笔当K线数据"""
    bi_bars = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        bi_bars.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down',
                            sp, ep, d2i[fb.dt], d2i[lb.dt]))
    return bi_bars


def find_fx_in_feature_seq(bi_bars, start, end, fx_type):
    """
    在特征序列中找分型（无未来函数）
    bi_bars: 笔K线列表
    start, end: 搜索范围索引
    fx_type: 'top' 找顶分型, 'bottom' 找底分型
    
    顶分型：三根相邻K线，中间high最高
    底分型：三根相邻K线，中间low最低
    
    返回第一个符合条件的分型索引，没有返回None
    """
    for i in range(start, min(end - 1, len(bi_bars) - 1)):
        prev = bi_bars[i - 1] if i > start else None
        curr = bi_bars[i]
        nxt = bi_bars[i + 1]
        if prev is None:
            continue
        if fx_type == 'top':
            if curr.high > prev.high and curr.high > nxt.high:
                return i
        else:  # bottom
            if curr.low < prev.low and curr.low < nxt.low:
                return i
    return None


def detect_xd(bi_bars):
    """
    线段检测 - 无未来函数版本
    两步确认：先候选，再验证
    
    返回：[(start_bi, end_bi, confirmed, direction), ...]
    """
    n = len(bi_bars)
    if n < 5:
        return []

    # pending_confirm: [(candidate_idx, xd_idx, reason), ...]
    # xd_segments: [{'start', 'end', 'confirmed', 'dir'}, ...]
    xd_segments = []
    pending_confirm = []  # 待确认的候选

    i = 0
    current_dir = bi_bars[0].direction
    seg_start = 0

    while i < n - 2:
        # 找下一个反向笔
        next_dir = 'down' if current_dir == 'up' else 'up'
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction == next_dir:
                next_idx = j
                break

        if next_idx is None:
            break

        next_bi = bi_bars[next_idx]

        if current_dir == 'up':
            # 上行段中，找回调笔
            if next_bi.low < bi_bars[seg_start].open:
                # 笔破坏：下行笔低点跌破上行段起点
                # 检查缺口封闭 vs 未封闭
                prev_up_high = bi_bars[i].high  # 上一上行笔的高点
                if next_bi.low < prev_up_high:
                    # 常规情形：缺口封闭
                    # 反弹不新高再回落 → 找顶分型确认
                    rebound_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'up':
                            rebound_idx = j
                            break
                    if rebound_idx is not None:
                        fx = find_fx_in_feature_seq(bi_bars, next_idx, rebound_idx + 2, 'top')
                        if fx is not None:
                            # 立即确认上行段结束
                            xd_segments.append({
                                'start': seg_start,
                                'end': next_idx,
                                'confirmed': True,
                                'dir': 'up',
                                'confirm_fx': fx
                            })
                            seg_start = rebound_idx
                            current_dir = 'down'
                            i = rebound_idx
                            continue
                else:
                    # 非常规情形：缺口未封闭
                    # 标记候选，等后续确认
                    # 找下行段中的上行笔（特征序列）
                    candidate_fx = next_idx
                    pending_confirm.append({
                        'candidate_fx': candidate_fx,
                        'xd_idx': len(xd_segments),
                        'up_seg_start': seg_start,
                        'down_seg_start': next_idx
                    })
                    seg_start = next_idx
                    current_dir = 'down'
                    i = next_idx
                    continue

        # 更新当前笔
        i = next_idx

        # 如果当前是反向笔还没确认，继续
        if bi_bars[i].direction != current_dir:
            current_dir = bi_bars[i].direction
            seg_start = i

    return xd_segments


def detect_xd_v2(bi_bars):
    """
    线段检测 v2 - 基于缺口封闭/未封闭的完整逻辑
    """
    n = len(bi_bars)
    if n < 3:
        return []

    # 找所有反向转折候选
    candidates = []  # (idx, type, related_bi)
    i = 0
    while i < n - 1:
        cur_dir = bi_bars[i].direction
        # 找下一个反向笔
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur_dir:
                candidates.append((j, 'reverse', i))
                break
        i = j if j < n else i + 1
        if j >= n:
            break

    print(f"找到{len(candidates)}个反向转折候选")

    # 分析每个候选的缺口情况
    results = []
    for idx, ctype, related in candidates:
        bi = bi_bars[idx]
        if bi.direction == 'down':
            # 下行笔，找前一个上行笔
            prev_up_idx = None
            for k in range(idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break
            if prev_up_idx is not None:
                gap_closed = bi.low < bi_bars[prev_up_idx].high
                print(f"  bi{idx+1}(down): low={bi.low:.0f} vs prev_up high={bi_bars[prev_up_idx].high:.0f} | gap_closed={gap_closed}")

    return results


def main():
    bars = load_bars('2026-04-03')
    d2i = {b.dt: i for i, b in enumerate(bars)}
    c = CZSC(bars)

    bi_bars = get_bi_bars(c, d2i)
    print(f"笔数量: {len(bi_bars)}")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1} {b.direction} [{b.dt.strftime('%H:%M')}] O={b.open:.0f} C={b.close:.0f} H={b.high:.0f} L={b.low:.0f}")

    print("\n线段检测:")
    results = detect_xd_v2(bi_bars)


if __name__ == '__main__':
    main()
