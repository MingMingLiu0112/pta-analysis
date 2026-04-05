#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权分析器 - 基于AKShare可用数据源
==========================
数据源:
  - futures_zh_realtime()  : PTA期货实时行情
  - option_hist_czce()     : 郑商所PTA期权日线(IV/DELTA/OI)
  - futures_spot_price()    : TA/PX现货价
  - futures_global_spot_em(): 布伦特原油
  - option_contract_info_ctp(): CTP合约信息

信号维度:
  1. 宏观基本面: 布伦特 + PX + PTA成本
  2. 技术面: 期货价格结构(升贴水) + 持仓量变化
  3. 期权面: PCR + IV曲面 + 期权墙梯度
  4. 综合信号: 三维共振判断
"""

import json
import os
import sys
import math
import re
from datetime import datetime, timedelta
import pandas as pd

PYTHON = "/home/admin/.pyenv/shims/python3.11"
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"

# 飞书Webhook（硬编码，从MEMORY.md同步）
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"

# 宏观新闻模块路径
import sys as _sys
_sys.path.insert(0, WORKSPACE)
import macro_news

# ===================== 成本计算 =====================
BRENT_TO_PX = 8.5   # 布伦特美元→PX美元的系数(简化估算)
PX_TO_PTA = 0.655   # PX→PTA加工系数(约655kg/吨)
TA_PROCESS_MARGIN = 800  # 加工利润+运费+杂费(元/吨)

def calc_pta_cost(brent_usd, px_cny):
    """
    布伦特→PTA成本估算
    路径: 布伦特(USD/桶) → PX(CNY/吨) → PTA成本(CNY/吨)
    """
    if not brent_usd or math.isnan(brent_usd):
        return None, None
    # 布伦特美元换算: 汇率假设7.25
    FX = 7.25
    brent_cny = brent_usd * FX
    # 简化路径: 布伦特 → PX → PTA
    # 实际公式: PTA成本 ≈ PX * 0.655 + 800
    pta_low = px_cny * PX_TO_PTA + TA_PROCESS_MARGIN - 200
    pta_high = px_cny * PX_TO_PTA + TA_PROCESS_MARGIN + 200
    return pta_low, pta_high

def generate_macro_qualitative(brent_price, px_price, pta_spot, pta_cost_low, pta_cost_high, news_summary):
    """
    基于充分信息的宏观定性分析
    返回: (score, label, detail_dict)
    detail_dict 包含各维度定性描述
    """
    result = {
        "cost": {},    # 成本端
        "supply": {},  # 供给端
        "demand": {},  # 需求端
        "funds": {},   # 资金行为
        "synthesis": {}, # 综合定性
    }

    # ---- 1. 成本端定性 ----
    if not all([brent_price, px_price, pta_spot, pta_cost_low]):
        result["cost"] = {"text": "数据不足，无法判断", "level": "未知"}
        return 0, "数据不足", result

    mid_cost = (pta_cost_low + pta_cost_high) / 2
    deviation_pct = (pta_spot - mid_cost) / mid_cost * 100

    if pta_spot < pta_cost_low:
        cost_text = f"PTA现货{pta_spot:.0f}元跌破成本区间下限({pta_cost_low:.0f})，加工费压缩至盈亏平衡以下"
        cost_level = "成本支撑强"
        cost_score = 2
    elif pta_spot > pta_cost_high + 300:
        cost_text = f"PTA现货{pta_spot:.0f}元明显高于成本区间上限({pta_cost_high:.0f})，利润良好"
        cost_level = "利润良好"
        cost_score = -2
    elif deviation_pct < 2:
        cost_text = f"PTA现货{pta_spot:.0f}元在成本区间({pta_cost_low:.0f}~{pta_cost_high:.0f})内，偏离中值{deviation_pct:.1f}%，成本支撑中性"
        cost_level = "成本支撑中性"
        cost_score = 0
    else:
        cost_text = f"PTA现货{pta_spot:.0f}元略高于成本区间({pta_cost_low:.0f}~{pta_cost_high:.0f})，偏离{deviation_pct:.1f}%"
        cost_level = "成本支撑弱"
        cost_score = -1

    # Brent定性地缘
    if brent_price > 80:
        brent_text = f"Brent原油期货(近月) ${brent_price}高位，地缘风险溢价显著"
        brent_score = 1
    elif brent_price > 70:
        brent_text = f"Brent原油期货(近月) ${brent_price}偏高，成本支撑偏强"
        brent_score = 0
    elif brent_price < 65:
        brent_text = f"Brent原油期货(近月) ${brent_price}低位，成本支撑弱"
        brent_score = -1
    else:
        brent_text = f"Brent原油期货(近月) ${brent_price}中性"
        brent_score = 0

    result["cost"] = {
        "text": f"【成本端】Brent ${brent_price}（{brent_text}）；PX {px_price}元/吨 → PTA成本区间 {pta_cost_low:.0f}~{pta_cost_high:.0f}元/吨；当前现货{pta_spot:.0f}元，{cost_text}。",
        "level": cost_level,
        "brent_text": brent_text,
    }

    # ---- 2. 供给端定性 ----
    supply_factors = []
    supply_score = 0
    if news_summary:
        supply_factors = news_summary.get("supply_factors", [])
        if "装置检修" in supply_factors or "降负减产" in supply_factors:
            supply_text = "4月大厂检修计划增多，供应收缩预期升温，PX供应偏紧"
            supply_score = 1
        elif "增产" in supply_factors or "重启" in supply_factors:
            supply_text = "装置重启或增产，供应压力上升"
            supply_score = -1
        else:
            supply_text = f"供给动态：{'、'.join(supply_factors) if supply_factors else '暂无明显变化'}"
            supply_score = 0

        wr_change = news_summary.get("wr_change")
        if wr_change is not None:
            if wr_change < 0:
                supply_text += f"；仓单减少{abs(wr_change)}张，现货端有支撑"
            else:
                supply_text += f"；仓单增加{wr_change}张，库存压力加大"
    else:
        supply_text = "供给数据暂缺，需结合检修计划综合判断"

    result["supply"] = {
        "text": f"【供给端】{supply_text}",
        "level": "收缩预期" if supply_score > 0 else ("宽松" if supply_score < 0 else "中性"),
    }

    # ---- 3. 需求端定性 ----
    demand_score = 0
    if news_summary:
        demand_factors = news_summary.get("demand_factors", [])
        neg_keywords = ["疲软", "羸弱", "负反馈", "开工率下降", "下降", "减少", "订单不足", "跟进慢"]
        pos_keywords = ["好转", "积极", "改善", "增加", "订单良好"]
        if demand_factors:
            demand_text = f"下游：{'、'.join(demand_factors[:3])}"
            if any(k in str(demand_factors) for k in neg_keywords):
                demand_score = -1
                demand_text += "——需求偏弱，对价格形成压制"
            elif any(k in str(demand_factors) for k in pos_keywords):
                demand_score = 1
                demand_text += "——需求改善，支撑价格"
            else:
                demand_text += "——需求端暂无明显改善"
        else:
            demand_text = "下游需求暂无明显变化"
    else:
        demand_text = "需求数据暂缺"
        demand_score = 0

    result["demand"] = {
        "text": f"【需求端】{demand_text}",
        "level": "偏弱" if demand_score < 0 else ("偏强" if demand_score > 0 else "中性"),
    }

    # ---- 4. 资金行为定性 ----
    funds_score = 0
    if news_summary and news_summary.get("net_position") is not None:
        net_pos = news_summary["net_position"]
        long_chg = news_summary.get("long_change")
        short_chg = news_summary.get("short_change")

        if net_pos < -30000:
            funds_text = f"前20席净空头{net_pos}手"
            if short_chg and long_chg:
                if abs(short_chg) > abs(long_chg):
                    funds_text += f"（空头加仓{short_chg}手>多头加仓{long_chg}手），空头主导；"
                else:
                    funds_text += f"（多头加仓{long_chg}手>空头加仓{short_chg}手），多头主导；"
            funds_text += f"本质：{'空头回补推动上涨，非真性做多' if net_pos < -20000 else '空头略占优势'}"
            funds_score = 0 if abs(net_pos) > 20000 else (1 if net_pos > 30000 else -1)
        elif net_pos > 30000:
            funds_text = f"前20席净多头{net_pos}手，多头主导"
            funds_score = 1
        else:
            funds_text = f"前20席净持仓{net_pos}手，多空力量接近"
            funds_score = 0

        result["funds"] = {
            "text": f"【资金行为】{funds_text}",
            "level": "空头回补" if net_pos < -20000 else ("多头主导" if net_pos > 20000 else "中性"),
        }
    else:
        result["funds"] = {"text": "【资金行为】持仓数据暂缺", "level": "未知"}
        funds_score = 0

    # ---- 5. 综合定性 ----
    all_scores = [cost_score, brent_score, supply_score, demand_score, funds_score]
    # 资金行为权重更高（基于真实持仓）
    weighted = cost_score * 0.2 + brent_score * 0.2 + supply_score * 0.15 + demand_score * 0.15 + funds_score * 0.3
    composite = round(weighted, 1)

    # 核心矛盾描述
    if funds_score == 0 and (cost_score > 0 or supply_score > 0) and demand_score < 0:
        core_矛盾 = "成本支撑+供给收缩 vs 需求疲软，空头回补推动上涨，持续性待观察"
        phase_label = "高位震荡"
    elif funds_score == 0 and net_pos and net_pos < -30000:
        core_矛盾 = "空头回补主导行情，本质非基本面驱动做多"
        phase_label = "空头回补"
    elif cost_score > 0 and demand_score < 0:
        core_矛盾 = "成本支撑 vs 需求压制，区间震荡为主"
        phase_label = "成本-需求博弈"
    elif demand_score < 0 and supply_score > 0:
        core_矛盾 = "供给收缩对冲需求疲软"
        phase_label = "弱平衡"
    else:
        core_矛盾 = "多空因素交织，方向不明"
        phase_label = "中性"

    if composite >= 1.5:
        final_label = "偏多"
        final_text = f"综合偏多({composite:+.1f})：{core_矛盾}"
    elif composite <= -1.5:
        final_label = "偏空"
        final_text = f"综合偏空({composite:+.1f})：{core_矛盾}"
    else:
        final_label = phase_label
        final_text = f"综合信号中性({composite:+.1f})：{core_矛盾}"

    result["synthesis"] = {
        "text": f"【综合定性】{final_text}",
        "label": final_label,
        "score": composite,
        "core_contradiction": core_矛盾,
    }

    return composite, final_label, result


# 兼容旧接口（保留给其他模块调用）
def get_macro_signal(brent_price, px_price, pta_spot, pta_cost_low, pta_cost_high):
    score, label, _ = generate_macro_qualitative(brent_price, px_price, pta_spot, pta_cost_low, pta_cost_high, None)
    return score, label, ""


def get_tech_signal(futures_df, spot_df_row):
    """
    技术面信号 - 基于期货持仓量/成交量 + 升贴水结构
    """
    if futures_df is None or futures_df.empty:
        return 0, "数据不足", ""
    
    # 取主力合约(成交量最大)
    main = futures_df.nlargest(1, 'volume')
    if main.empty:
        return 0, "数据不足", ""
    
    main_price = main.iloc[0]['trade']
    main_vol = main.iloc[0]['volume']
    main_pos = main.iloc[0]['position']
    
    # 现货价格
    spot_price = spot_df_row['spot_price'] if spot_df_row is not None else main_price
    
    # 升贴水
    basis = main_price - spot_price
    
    # 持仓量变化率(简化用持仓/成交比)
    pos_ratio = main_pos / main_vol if main_vol > 0 else 0
    
    # 分数
    score = 0
    signals = []
    
    # 升贴水判断
    if basis > 200:
        signals.append(f"强升水(+{basis:.0f})")
        score -= 1  # 升水过高可能预示回调
    elif basis < -100:
        signals.append(f"贴水({basis:.0f})")
        score += 1  # 贴水支撑
    else:
        signals.append(f"小幅升水({basis:.0f})")
    
    # 持仓/成交比(反映资金热度)
    if pos_ratio > 0.6:
        signals.append(f"高持仓比({pos_ratio:.2f})")
        score += 1  # 资金沉淀，看涨
    elif pos_ratio < 0.3:
        signals.append(f"低持仓比({pos_ratio:.2f})")
        score -= 1
    
    # 价格位置(多空判断)
    close_price = main_price
    preclose = main.iloc[0].get('prevsettlement', main_price)
    change_pct = (close_price - preclose) / preclose * 100 if preclose else 0
    
    if change_pct > 2:
        signals.append(f"大涨({change_pct:.2f}%)")
        score += 1
    elif change_pct < -2:
        signals.append(f"大跌({change_pct:.2f}%)")
        score -= 1
    else:
        signals.append(f"小幅波动({change_pct:+.2f}%)")
    
    total_score = max(-3, min(3, score))
    if total_score >= 2:
        label = "技术强势"
    elif total_score <= -2:
        label = "技术弱势"
    else:
        label = "技术中性"
    
    return total_score, label, "; ".join(signals)


def get_option_signal(option_df):
    """
    期权面信号 - PCR + IV + 期权墙梯度
    """
    if option_df is None or option_df.empty:
        return 0, "期权数据不足", ""
    
    # 认购 vs 认沽（用合约代码中的C/P标识，不用DELTA，因为深度虚值期权的DELTA可能不准确）
    call = option_df[option_df['合约代码'].str.contains('C')].copy()
    put = option_df[option_df['合约代码'].str.contains('P')].copy()
    
    if call.empty or put.empty:
        return 0, "期权数据不足", ""
    
    # PCR
    call_oi = call['持仓量'].sum()
    put_oi = put['持仓量'].sum()
    call_vol = call['成交量(手)'].sum()
    put_vol = put['成交量(手)'].sum()
    
    pcr_oi = put_oi / call_oi if call_oi > 0 else None
    pcr_vol = put_vol / call_vol if call_vol > 0 else None
    
    # IV统计（排除深度虚值合约的极端IV，保留DELTA在0.1~0.9之间）
    call_iv = call[(call['DELTA'] >= 0.1) & (call['DELTA'] <= 0.9)]['隐含波动率'].dropna()
    put_iv = put[(put['DELTA'] >= -0.9) & (put['DELTA'] <= -0.1)]['隐含波动率'].dropna()

    score = 0
    signals = []
    
    # 期权墙: 持仓量最大的行权价（原始）
    call_wall_raw = call.nlargest(5, '持仓量')[['合约代码', '持仓量', '隐含波动率']].values.tolist()
    put_wall_raw = put.nlargest(5, '持仓量')[['合约代码', '持仓量', '隐含波动率']].values.tolist()

    # 期权墙梯度分析（提取行权价）
    import re as _re
    def get_strike(code):
        m = _re.search(r'[CP](\d+)', str(code))
        return int(m.group(1)) if m else None

    call_walls = [(get_strike(w[0]), int(w[1]), float(w[2]) if w[2] else None) for w in call_wall_raw if get_strike(w[0])]
    put_walls = [(get_strike(w[0]), int(w[1]), float(w[2]) if w[2] else None) for w in put_wall_raw if get_strike(w[0])]

    # 天花板 = 认购侧OI最大的行权价（通常在当前价格上方）
    # 地板 = 认沽侧OI最大的行权价（通常在当前价格下方）
    best_call_wall = max(call_walls, key=lambda x: x[1]) if call_walls else None
    best_put_wall = max(put_walls, key=lambda x: x[1]) if put_walls else None

    # 梯度区间分析（天花板区间 >6800，地板区间 <6200）
    floor_zone_oi = sum(w[1] for w in put_walls if w[0] and 4000 <= w[0] <= 6200)
    ceiling_zone_oi = sum(w[1] for w in call_walls if w[0] and 6800 <= w[0] <= 9000)

    # 预设默认值
    floor_strike = ceiling_strike = floor_oi = ceiling_oi = ratio = None

    if best_put_wall and best_call_wall:
        floor_strike = best_put_wall[0]
        ceiling_strike = best_call_wall[0]
        floor_oi = best_put_wall[1]
        ceiling_oi = best_call_wall[1]
        ratio = floor_oi / ceiling_oi if ceiling_oi > 0 else None

        if ratio and ratio > 1.5:
            signals.append(f"期权墙梯度：地板P{floor_strike}({floor_oi}手)>天花板C{ceiling_strike}({ceiling_oi}手) → 防御偏重")
            score -= 0.5
        elif ratio and ratio < 0.7:
            signals.append(f"期权墙梯度：天花板C{ceiling_strike}({ceiling_oi}手)>地板P{floor_strike}({floor_oi}手) → 进攻偏重")
            score += 0.5

    # 地板区间 vs 天花板区间 OI 密度对比
    if floor_zone_oi and ceiling_zone_oi:
        if floor_zone_oi > ceiling_zone_oi * 1.3:
            signals.append(f"地板区间OI({floor_zone_oi}手)>天花板区间({ceiling_zone_oi}手) → 下方防线强")
            score -= 0.5
        elif ceiling_zone_oi > floor_zone_oi * 1.3:
            signals.append(f"天花板区间OI({ceiling_zone_oi}手)>地板区间({floor_zone_oi}手) → 上方压力强")
            score += 0.5

    # PCR判断(基于持仓PCR)
    if pcr_oi:
        if pcr_oi > 3.0:
            signals.append(f"PCR极高({pcr_oi:.2f})→机构对冲")
            score -= 1  # 高PCR可能是机构大量买入认沽对冲,意味着看跌
        elif pcr_oi > 1.5:
            signals.append(f"PCR偏高({pcr_oi:.2f})")
            score -= 0.5
        elif pcr_oi < 0.7:
            signals.append(f"PCR偏低({pcr_oi:.2f})→看涨情绪")
            score += 0.5
        else:
            signals.append(f"PCR正常({pcr_oi:.2f})")
    
    # IV曲面
    if not call_iv.empty and not put_iv.empty:
        iv_diff = put_iv.mean() - call_iv.mean()
        if iv_diff > 5:
            signals.append(f"认沽IV偏高(+{iv_diff:.1f})→下跌保护")
            score -= 1
        elif iv_diff < -5:
            signals.append(f"认购IV偏高({iv_diff:.1f})→上涨预期")
            score += 1
        
        # IV极端值
        if not put_iv.empty and put_iv.max() > 35:
            signals.append(f"极端高认沽IV({put_iv.max():.1f}%)→市场恐慌定价")
            score -= 1
    
    total_score = max(-3, min(3, score))
    # 分数为正 → 市场偏多/乐观 (认购强); 分数为负 → 机构对冲/偏空 (认沽强)
    if total_score >= 1.5:
        label = "期权偏多"
    elif total_score <= -1.5:
        label = "期权偏空"
    else:
        label = "期权中性"
    
    detail = "; ".join(signals)
    
    # 额外返回PCR和IV差供综合判断
    extra = {
        'pcr_vol': round(pcr_vol, 4) if pcr_vol else None,
        'call_iv_mean': round(call_iv.mean(), 2) if not call_iv.empty else None,
        'put_iv_mean': round(put_iv.mean(), 2) if not put_iv.empty else None,
        'call_wall': [[f"C{w[0]}", w[1], w[2]] for w in call_walls],
        'put_wall': [[f"P{w[0]}", w[1], w[2]] for w in put_walls],
        'best_floor': f"P{floor_strike}({floor_oi}手)" if floor_strike else None,
        'best_ceiling': f"C{ceiling_strike}({ceiling_oi}手)" if ceiling_strike else None,
        'floor_zone_oi': floor_zone_oi,
        'ceiling_zone_oi': ceiling_zone_oi,
        'floor_ceiling_ratio': round(ratio, 2) if ratio else None,
    }
    
    return total_score, label, detail, extra


def composite_signal(macro_score, tech_score, option_score):
    """
    三维共振综合信号
    杀期权阶段识别: 技术强势+期权偏空 → 杀期权概率大
    """
    total = macro_score + tech_score + option_score
    
    # 阶段识别
    if macro_score >= 1 and tech_score >= 1 and option_score <= -1:
        phase = "杀期权阶段"
        phase_desc = "基本面强势+技术强势,但期权偏空→机构被迫买入期货对冲,随后平仓导致双向收割"
        composite = -2
    elif macro_score <= -1 and tech_score <= -1 and option_score <= -1:
        phase = "恐慌底共振"
        phase_desc = "基本面弱+技术弱+期权弱→三重共振做空,但物极必反"
        composite = 2
    elif macro_score >= 1 and tech_score >= 1 and option_score >= 1:
        phase = "狂热顶共振"
        phase_desc = "基本面+技术+期权三多共振→极端风险区"
        composite = -2
    elif total >= 2:
        phase = "偏多信号"
        phase_desc = f"综合得分:{total}"
        composite = 2
    elif total <= -2:
        phase = "偏空信号"
        phase_desc = f"综合得分:{total}"
        composite = -2
    else:
        phase = "观望"
        phase_desc = f"综合得分:{total}"
        composite = 0
    
    return composite, phase, phase_desc

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




def main():
    import akshare as ak
    
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    print(f"\n{'='*60}")
    print(f"PTA分析报告  {today_str} {now.strftime('%H:%M')}")
    print(f"{'='*60}\n")
    
    report = {"timestamp": now.isoformat()}
    
    # ---- 数据采集 ----
    print("【1. 数据采集】")
    
    # 1.1 实时期货
    try:
        fut_df = ak.futures_zh_realtime()
        ta_df = fut_df[fut_df['exchange'] == 'czce'].copy()
        # 过滤主力+次主力
        ta_df = ta_df[ta_df['symbol'].str.match(r'^TA\d{4}$')]
        report['futures'] = "OK"
        print(f"  期货实时: OK ({len(ta_df)}个合约)")
    except Exception as e:
        ta_df = None
        report['futures'] = f"FAIL: {e}"
        print(f"  期货实时: FAIL {e}")
    
    # 1.2 现货
    try:
        # 找最近交易日
        spot_df = None
        for i in range(1, 8):
            d = (now - timedelta(days=i)).strftime('%Y%m%d')
            sdf = ak.futures_spot_price(date=d, vars_list=['TA', 'PX'])
            if not sdf.empty:
                spot_df = sdf
                report['spot_date'] = d
                break
        report['spot'] = "OK"
        print(f"  TA/PX现货: OK ({spot_df['date'].iloc[0] if spot_df is not None else 'N/A'})")
    except Exception as e:
        spot_df = None
        report['spot'] = f"FAIL: {e}"
        print(f"  TA/PX现货: FAIL {e}")
    
    # 1.3 布伦特
    try:
        brent_df = ak.futures_global_spot_em()
        brent = brent_df[brent_df['名称'].str.contains('布伦特| Brent', na=False)]
        brent_price = brent['最新价'].dropna().iloc[0] if not brent.empty else None
        report['brent'] = "OK"
        print(f"  布伦特原油: OK (${brent_price})" if brent_price else "  布伦特原油: 数据缺失")
    except Exception as e:
        brent_price = None
        report['brent'] = f"FAIL: {e}"
        print(f"  布伦特原油: FAIL {e}")
    
    # 1.4 期权历史
    try:
        opt_df = None
        for i in range(1, 8):
            d = (now - timedelta(days=i)).strftime('%Y%m%d')
            odf = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            if not odf.empty:
                opt_df = odf
                report['option_date'] = d
                break
        report['option'] = "OK"
        print(f"  PTA期权: OK ({opt_df.shape[0]}行 {report.get('option_date','')})" if opt_df is not None else "  PTA期权: 无数据")
    except Exception as e:
        opt_df = None
        report['option'] = f"FAIL: {e}"
        print(f"  PTA期权: FAIL {e}")
    
    # 1.5 宏观新闻（PTA产业相关）
    print("  宏观新闻采集中...")
    try:
        news_list = macro_news.fetch_pta_news(days=3)
        news_summary = macro_news.generate_macro_summary(news_list) if news_list else None
        report['news'] = {"count": len(news_list), "summary": news_summary}
        print(f"  宏观新闻: OK ({len(news_list)}篇)" if news_list else "  宏观新闻: 无相关资讯")
    except Exception as e:
        news_list = []
        news_summary = None
        report['news'] = f"FAIL: {e}"
        print(f"  宏观新闻: FAIL {e}")

    # 1.6 全球宏观大事件（地缘/央行/市场情绪）
    print("  全球宏观大事件采集中...")
    try:
        global_events, global_sentiment_score, global_summary = macro_news.fetch_and_analyze_global_macro()
        report['global_macro'] = {
            "event_count": len(global_events) if global_events else 0,
            "sentiment": global_summary.get("sentiment", "N/A") if global_summary else "N/A",
            "sentiment_score": global_sentiment_score,
            "summary": global_summary,
        }
        if global_events:
            print(f"  全球宏观: OK ({len(global_events)}个大事件) | {global_summary.get('sentiment','')}")
            print(f"    关键事件:")
            for ev in global_events[:4]:
                print(f"      [{ev['type']}] {ev['title'][:40]}")
        else:
            print("  全球宏观: 无数据")
    except Exception as e:
        global_events = None
        global_sentiment_score = None
        global_summary = None
        report['global_macro'] = f"FAIL: {e}"
        print(f"  全球宏观: FAIL {e}")
    
    print()
    
    # ---- 信号计算 ----
    print("【2. 信号分析】\n")
    
    # 宏观
    ta_spot_row = spot_df[spot_df['symbol'] == 'TA'].iloc[0] if spot_df is not None and not spot_df.empty else None
    px_spot_row = spot_df[spot_df['symbol'] == 'PX'].iloc[0] if spot_df is not None and not spot_df.empty else None
    ta_spot = ta_spot_row['spot_price'] if ta_spot_row is not None else None
    px_price = px_spot_row['spot_price'] if px_spot_row is not None else None
    
    if brent_price and px_price:
        cost_low, cost_high = calc_pta_cost(brent_price, px_price)
    else:
        cost_low = cost_high = None
    
    # 完整定性宏观分析（整合新闻）
    m_score, m_label, macro_qual = generate_macro_qualitative(
        brent_price, px_price, ta_spot, cost_low, cost_high, news_summary
    )

    print(f"  宏观信号: {m_label}({m_score:+.1f})")
    if cost_low and ta_spot:
        print(f"  宏观详情:")
        print(f"    {macro_qual['cost']['text']}")
        print(f"    {macro_qual['supply']['text']}")
        print(f"    {macro_qual['demand']['text']}")
        print(f"    {macro_qual['funds']['text']}")
        print(f"    {macro_qual['synthesis']['text']}")

    # 全球宏观大事件
    if global_events:
        sent = global_summary.get("sentiment", "N/A") if global_summary else "N/A"
        sent_score = global_sentiment_score or 0
        print(f"\n  全球宏观: {sent}({sent_score:+.1f})")
        for ev in global_events[:5]:
            print(f"    [{ev['type']}] {ev['title'][:50]}")
            print(f"      → {ev['impact_pta']}")
    
    # 技术
    t_score, t_label, t_detail = get_tech_signal(ta_df, ta_spot_row)
    print(f"\n  技术信号: {t_label}({t_score})")
    print(f"    {t_detail}")
    
    # 期权（微观分析：短期博弈 + 中期防线 + 绝对区间梯度）
    main_price = float(ta_df.nlargest(1, 'volume').iloc[0]['trade']) if ta_df is not None and not ta_df.empty else 7000
    o_result = analyze_option_wall(
        opt_df[opt_df['合约代码'].str.startswith('TA605')] if opt_df is not None else None,
        futures_price=main_price
    )
    o_score = o_result.get('score', 0)
    o_label = o_result.get('label', '期权数据不足')
    o_detail = o_result.get('detail', '')
    print(f"\n  期权信号: {o_label}({o_score})")
    print(f"    {o_detail}")
    if o_result:
        sg = o_result.get('short_gaming', {})
        mt = o_result.get('medium_term', {})
        ivs = o_result.get('iv_surface', {})
        print(f"    短期博弈（成交量Top3）:")
        print(f"      认购: {[(r[0], r[2]) for r in sg.get('top_vol_call', [])]}")
        print(f"      认沽: {[(r[0], r[2]) for r in sg.get('top_vol_put', [])]}")
        print(f"    中期防线（期权墙）:")
        print(f"      天花板Top3: {[(r[0], f'{r[2]:,}手') for r in mt.get('top5_ceiling', [])[:3]]}")
        print(f"      地板Top3: {[(r[0], f'{r[2]:,}手') for r in mt.get('top5_floor', [])[:3]]}")
        print(f"      天花板合计: {mt.get('ceil_zone_total_oi', 0):,}手 | 地板合计: {mt.get('floor_zone_total_oi', 0):,}手 | 梯度比: {mt.get('gradient_ratio', 'N/A')}")
        print(f"    IV曲面: 购IV={ivs.get('call_iv_near_atm', '?')}% 沽IV={ivs.get('put_iv_near_atm', '?')}% (差={ivs.get('iv_diff', '?')}%)")
    
    # 综合（加入全球风险情绪权重）
    global_w = 0.3
    m_score_adjusted = round(m_score + (global_sentiment_score or 0) * global_w, 1)
    c_score, c_phase, c_desc = composite_signal(m_score_adjusted, t_score, o_score)
    print(f"\n  → 综合判断: {c_phase}({c_score})")
    print(f"    {c_desc}")
    
    # ---- 飞书推送 ----
    report['macro'] = {'score': m_score, 'label': m_label, 'qualitative': macro_qual}
    report['tech'] = {'score': t_score, 'label': t_label, 'detail': t_detail}
    report['option'] = {'score': o_score, 'label': o_label, 'detail': o_detail}
    report['composite'] = {'score': c_score, 'phase': c_phase, 'desc': c_desc}
    if o_extra:
        report['option_extra'] = o_extra
    if news_summary:
        report['news_summary'] = news_summary
    
    # Push content - build as simple string concatenation
    # Build each block as simple string
    global_block_str = global_block or "(No data)"
    cost_str = cost_block[:120] if cost_block else f"Brent={brent_price} PX={px_price} TA_spot={ta_spot}"
    supply_str = supply_block[:100] + ".." if len(supply_block) > 100 else supply_block[:100]
    demand_str = demand_block[:100] + ".." if len(demand_block) > 100 else demand_block[:100]
    tech_str = f"Tech({t_label},{t_score:+d}): {t_detail}" if t_detail else f"Tech: {t_label}({t_score})"
    
    # Option block from result
    oi = o_result
    pcr_str = oi.get("pcr_vol_display", "N/A") if oi else "N/A"
    grad_str = str(mt.get("gradient_ratio", "N/A")) if mt.get("gradient_ratio") else "N/A"
    call_iv_str = str(ivs.get("call_iv_near_atm", "?"))
    put_iv_str = str(ivs.get("put_iv_near_atm", "?"))
    iv_diff_str = str(ivs.get("iv_diff", "?"))
    
    option_summary = f"Option({o_label},{o_score:+d}): PCR={pcr_str} Grad={grad_str} IV_Call={call_iv_str}% IV_Put={put_iv_str}% Diff={iv_diff_str}%"
    option_detail = o_detail if o_detail else ""
    
    summary_str = f"{e} Summary: {c_phase}({c_score:+d}): {c_desc}"
    
    lines = [
        f"PTA Analysis {now.strftime('%Y-%m-%d %H:%M')}",
        "=" * 40,
        f"[1] GLOBAL: {global_block_str}",
        f"[2] INDUSTRY: {cost_str}",
        f"  {supply_str}",
        f"  {demand_str}",
        f"  {funds_block[:100]}",
        f"[3] TECH: {tech_str}",
        f"[4] OPTION: {option_summary}",
        f"  {option_detail}",
        "=" * 40,
        f"[SUMMARY] {summary_str}",
        "#PTA #Options | Sources: 18qh.com + PhoenixFinance",
    ]
    push_text = "\n".join(lines)

    # 推送飞书
    webhook = FEISHU_WEBHOOK
    if webhook:
        try:
            import urllib.request
            payload = json.dumps({"msg_type": "text", "content": {"text": push_text}}).encode()
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            print(f"\n✅ 飞书推送成功")
            report['push'] = 'OK'
        except Exception as e:
            print(f"\n⚠️ 飞书推送失败: {e}")
            report['push'] = f'FAIL: {e}'
    else:
        print(f"\n⚠️ 未配置飞书Webhook")
        report['push'] = 'SKIP'
    
    # 保存报告
    report_file = f"{WORKSPACE}/report_{now.strftime('%Y%m%d_%H%M')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 报告已保存: {report_file}")
    
    return report


if __name__ == "__main__":
    main()
