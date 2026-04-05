#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权微观分析模块 v2
====================
三层分析：
  1. 短期博弈 -- 成交量分布（当日资金博弈焦点）
  2. 中期防线 -- 期权墙多层次梯度（地板 vs 天花板）
  3. 绝对区间 -- 全行权价区间OI密度分布

多层次梯度结构（核心）：
  天花板（认购，压力墙）：
    Level1(近端压力): 行权价7000~7400
    Level2(中端压力): 行权价7400~7800
    Level3(远端压力): 行权价7800以上
  地板（认沽，支撑墙）：
    Level1(近端支撑): 行权价6500~7000
    Level2(中端支撑): 行权价5500~6500
    Level3(深端支撑): 行权价4000~5500
"""

import re


def analyze_option_wall(option_df, futures_price=7000):
    """
    完整期权墙分析，含多层次梯度结构
    """
    if option_df is None or option_df.empty:
        return {}

    import pandas as pd

    # 区分C/P
    def get_strike(code):
        m = re.search(r'[CP](\d+)', str(code))
        return int(m.group(1)) if m else None

    def get_type(code):
        return 'C' if 'C' in str(code) else 'P'

    option_df = option_df.copy()
    option_df['行权价'] = option_df['合约代码'].apply(get_strike)
    option_df['类型'] = option_df['合约代码'].apply(get_type)

    call = option_df[option_df['类型'] == 'C'].copy()
    put = option_df[option_df['类型'] == 'P'].copy()

    # 基本PCR
    total_call_vol = int(call['成交量(手)'].sum())
    total_put_vol = int(put['成交量(手)'].sum())
    pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else None

    # ---- ① 短期博弈（成交量Top3）----
    top3_vol_call = call.nlargest(3, '成交量(手)')[['合约代码', '行权价', '成交量(手)']].values.tolist()
    top3_vol_put = put.nlargest(3, '成交量(手)')[['合约代码', '行权价', '成交量(手)']].values.tolist()

    # ---- ②③ 中期防线 + 多层次梯度 ----
    ceil_zone = call[call['行权价'] > futures_price].copy()
    floor_zone = put[put['行权价'] < futures_price].copy()

    # 多层梯度构建
    def build_levels(zone_df, level_defs):
        """
        按行权价区间分层，每层返回：
          - label: 层名称
          - oi_total: 该层总OI
          - top_contract: 最厚行权价合约
          - top_oi: 最厚OI
          - top_iv: 最厚IV
          - strike_count: 该层合约数
        """
        levels = []
        for label, lo, hi in level_defs:
            z = zone_df[(zone_df['行权价'] >= lo) & (zone_df['行权价'] < hi)]
            if z.empty:
                continue
            oi_total = int(z['持仓量'].sum())
            top_row = z.nlargest(1, '持仓量').iloc[0]
            levels.append({
                'label': label,
                'oi_total': oi_total,
                'top_contract': str(top_row['合约代码']),
                'top_oi': int(top_row['持仓量']),
                'top_iv': float(top_row['隐含波动率']),
                'strike_count': len(z),
            })
        return levels

    ceiling_levels = build_levels(ceil_zone, [
        ('近端压力(7000~7400)', 7000, 7400),
        ('中端压力(7400~7800)', 7400, 7800),
        ('远端压力(7800~)', 7800, 9999),
    ])
    floor_levels = build_levels(floor_zone, [
        ('近端支撑(6500~7000)', 6500, 7000),
        ('中端支撑(5500~6500)', 5500, 6500),
        ('深端支撑(4000~5500)', 4000, 5500),
    ])

    # 合计
    ceil_total_oi = int(ceil_zone['持仓量'].sum())
    floor_total_oi = int(floor_zone['持仓量'].sum())
    gradient_ratio = round(floor_total_oi / ceil_total_oi, 2) if ceil_total_oi > 0 else None

    # ---- IV曲面 ----
    atm_lo, atm_hi = futures_price * 0.95, futures_price * 1.05
    near_atm_call = call[(call['行权价'] >= atm_lo) & (call['行权价'] <= atm_hi)]
    near_atm_put = put[(put['行权价'] >= atm_lo) & (put['行权价'] <= atm_hi)]
    call_iv_near = near_atm_call['隐含波动率'].dropna()
    put_iv_near = near_atm_put['隐含波动率'].dropna()
    call_iv_mean = round(call_iv_near.mean(), 1) if not call_iv_near.empty else None
    put_iv_mean = round(put_iv_near.mean(), 1) if not put_iv_near.empty else None
    iv_diff = round(put_iv_mean - call_iv_mean, 1) if (call_iv_mean and put_iv_mean) else None

    # ---- 综合评分 ----
    score = 0
    signals = []

    if pcr_vol:
        if pcr_vol < 0.5:
            signals.append(f"成交量PCR={pcr_vol:.2f}，认购资金主导，短期情绪偏多")
            score += 1
        elif pcr_vol < 0.8:
            signals.append(f"成交量PCR={pcr_vol:.2f}，情绪偏多")
            score += 0.5
        elif pcr_vol > 1.5:
            signals.append(f"成交量PCR={pcr_vol:.2f}，认沽资金主导，短期情绪偏空")
            score -= 1
        elif pcr_vol > 1.0:
            signals.append(f"成交量PCR={pcr_vol:.2f}，情绪偏空")
            score -= 0.5

    if gradient_ratio:
        if gradient_ratio > 2.0:
            signals.append(f"地板合计OI({floor_total_oi:,}手)是天花板({ceil_total_oi:,}手)的{gradient_ratio}倍，防御力量极强")
            score -= 1.5
        elif gradient_ratio > 1.5:
            signals.append(f"地板({floor_total_oi:,}手)>天花板({ceil_total_oi:,}手)，梯度比{gradient_ratio}，防御偏重")
            score -= 1

    if iv_diff is not None:
        if iv_diff > 5:
            signals.append(f"认沽IV({put_iv_mean}%)>认购IV({call_iv_mean}%)，市场为下跌付更高溢价")
            score -= 1
        elif iv_diff < -5:
            signals.append(f"认购IV({call_iv_mean}%)>认沽IV({put_iv_mean}%)，市场为上涨付更高溢价")
            score += 1

    total_score = max(-4, min(4, score))
    label = "期权偏多" if total_score >= 2 else ("期权偏空" if total_score <= -2 else "期权中性")
    detail = "；".join(signals) if signals else "信息不足以判断"

    return {
        # 基础
        'pcr_vol': pcr_vol,
        'pcr_vol_display': f"{pcr_vol:.2f}" if pcr_vol else "N/A",

        # ① 短期博弈
        'short_gaming': {
            'top3_vol_call': [[str(r[0]), int(r[1]), int(r[2])] for r in top3_vol_call],
            'top3_vol_put': [[str(r[0]), int(r[1]), int(r[2])] for r in top3_vol_put],
            'total_call_vol': total_call_vol,
            'total_put_vol': total_put_vol,
        },

        # ②③ 中期防线 + 多层梯度
        'medium_term': {
            'ceiling_levels': ceiling_levels,
            'floor_levels': floor_levels,
            'ceil_total_oi': ceil_total_oi,
            'floor_total_oi': floor_total_oi,
            'gradient_ratio': gradient_ratio,
        },

        # IV曲面
        'iv_surface': {
            'call_iv_near_atm': call_iv_mean,
            'put_iv_near_atm': put_iv_mean,
            'iv_diff': iv_diff,
        },

        # 综合
        'score': total_score,
        'label': label,
        'detail': detail,
    }


def format_option_report(result, futures_price=7000):
    """
    将分析结果格式化为易读的期权墙报告
    返回字符串
    """
    if not result:
        return "期权数据不足"

    lines = []
    mt = result.get('medium_term', {})
    sg = result.get('short_gaming', {})
    ivs = result.get('iv_surface', {})

    # 标题
    lines.append(f"[Option] {result['label']}({result['score']:+d})")

    # ① 短期博弈
    lines.append("  [Short-term Gaming - Vol Top3]")
    for c in sg.get('top3_vol_call', []):
        lines.append(f"    Call: {c[0]} vol={c[2]:,} lots")
    for p in sg.get('top3_vol_put', []):
        lines.append(f"    Put:  {p[0]} vol={p[2]:,} lots")
    lines.append(f"  Vol PCR={result.get('pcr_vol_display', 'N/A')}")

    # ② 多层防线（天花板）
    lines.append("  [Ceiling Wall - Call Pressure]")
    for lv in mt.get('ceiling_levels', []):
        lines.append(f"    {lv['label']}: OI={lv['oi_total']:,} | thickest={lv['top_contract']}({lv['top_oi']:,} lots IV={lv['top_iv']:.1f}%)")

    # ③ 多层防线（地板）
    lines.append("  [Floor Wall - Put Support]")
    for lv in mt.get('floor_levels', []):
        lines.append(f"    {lv['label']}: OI={lv['oi_total']:,} | thickest={lv['top_contract']}({lv['top_oi']:,} lots IV={lv['top_iv']:.1f}%)")

    # 合计
    lines.append(f"  [Summary] Ceiling={mt.get('ceil_total_oi', 0):,} | Floor={mt.get('floor_total_oi', 0):,} | Gradient={mt.get('gradient_ratio', 'N/A')}")

    # IV曲面
    cv = ivs.get('call_iv_near_atm')
    pv = ivs.get('put_iv_near_atm')
    ivd = ivs.get('iv_diff')
    lines.append(f"  [IV Surface] Call={cv}% | Put={pv}% | Diff={ivd}%")

    # 信号
    lines.append(f"  {result['detail']}")

    return "\n".join(lines)


if __name__ == "__main__":
    import akshare as ak
    from datetime import datetime, timedelta

    now = datetime.now()
    for i in range(1, 5):
        d = (now - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            if not df.empty:
                result = analyze_option_wall(df, futures_price=6988)
                print(format_option_report(result))
                break
        except Exception as e:
            print(f"{d}: FAIL {e}")
