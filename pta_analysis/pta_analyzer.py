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
from datetime import datetime, timedelta

PYTHON = "/home/admin/.pyenv/shims/python3.11"
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"

# 飞书Webhook（硬编码，从MEMORY.md同步）
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"

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

def get_macro_signal(brent_price, px_price, pta_spot, pta_cost_low, pta_cost_high):
    """
    宏观基本面信号
    return: score(-3~+3), label, detail
    """
    if not all([brent_price, px_price, pta_spot, pta_cost_low]):
        return 0, "数据不足", ""
    
    # 布伦特趋势
    if brent_price > 80:
        brent_signal = "强势(>80)"
        brent_score = 1
    elif brent_price < 65:
        brent_signal = "弱势(<65)"
        brent_score = -1
    else:
        brent_signal = "中性"
        brent_score = 0
    
    # PTA相对成本的偏离
    mid_cost = (pta_cost_low + pta_cost_high) / 2
    偏离 = (pta_spot - mid_cost) / mid_cost * 100
    
    if pta_spot < pta_cost_low:
        pta_signal = f"成本支撑区({偏离:.1f}%)"
        pta_score = 2
    elif pta_spot > pta_cost_high + 300:
        pta_signal = f"高估区({偏离:.1f}%)"
        pta_score = -2
    elif 偏离 < 2:
        pta_signal = f"合理偏低({偏离:.1f}%)"
        pta_score = 1
    elif 偏离 > 8:
        pta_signal = f"溢价偏高({偏离:.1f}%)"
        pta_score = -1
    else:
        pta_signal = f"合理区间({偏离:.1f}%)"
        pta_score = 0
    
    total = brent_score + pta_score
    if total >= 2:
        label, level = "利多", "+"
    elif total <= -2:
        label, level = "利空", "-"
    elif total == 1:
        label, level = "轻微利多", "+"
    elif total == -1:
        label, level = "轻微利空", "-"
    else:
        label, level = "中性", "~"
    
    detail = f"布伦特:{brent_signal}, PTA偏离成本:{pta_signal}"
    return total, label, detail


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
    
    # 认购 vs 认沽
    call = option_df[option_df['DELTA'] > 0.5].copy()
    put = option_df[option_df['DELTA'] < 0.5].copy()
    
    if call.empty or put.empty:
        return 0, "期权数据不足", ""
    
    # PCR
    call_oi = call['持仓量'].sum()
    put_oi = put['持仓量'].sum()
    call_vol = call['成交量(手)'].sum()
    put_vol = put['成交量(手)'].sum()
    
    pcr_oi = put_oi / call_oi if call_oi > 0 else None
    pcr_vol = put_vol / call_vol if call_vol > 0 else None
    
    # IV统计
    call_iv = call['隐含波动率'].dropna()
    put_iv = put['隐含波动率'].dropna()
    
    # 期权墙: 持仓量最大的行权价
    call_wall = call.nlargest(3, '持仓量')[['合约代码', '持仓量', '隐含波动率']].values.tolist()
    put_wall = put.nlargest(3, '持仓量')[['合约代码', '持仓量', '隐含波动率']].values.tolist()
    
    score = 0
    signals = []
    
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
        if put_iv.max() > 35:
            signals.append(f"极端高IV认沽({put_iv.max():.1f}%)")
            score -= 1
    
    # 期权墙梯度(行权价间距密度)
    # 简化: 认沽期权墙如果在虚值程度较深处,可能意味着支撑
    if put_wall:
        deep_otm_puts = [w for w in put_wall if w[2] and w[2] < 20]  # IV<20%的虚值认沽
        if deep_otm_puts:
            signals.append(f"深度虚值认沽期权墙({len(deep_otm_puts)}个)")
            score -= 0.5  # 虚值认沽堆叠可能是空头力量
    
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
        'pcr_oi': round(pcr_oi, 4) if pcr_oi else None,
        'pcr_vol': round(pcr_vol, 4) if pcr_vol else None,
        'call_iv_mean': round(call_iv.mean(), 2) if not call_iv.empty else None,
        'put_iv_mean': round(put_iv.mean(), 2) if not put_iv.empty else None,
        'call_wall': [[str(w[0]), int(w[1]), float(w[2]) if w[2] else None] for w in call_wall],
        'put_wall': [[str(w[0]), int(w[1]), float(w[2]) if w[2] else None] for w in put_wall],
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
    
    m_score, m_label, m_detail = get_macro_signal(brent_price, px_price, ta_spot, cost_low, cost_high)
    print(f"  宏观信号: {m_label}({m_score})")
    print(f"    {m_detail}")
    if cost_low:
        print(f"    PTA成本区间: {cost_low:.0f}~{cost_high:.0f} | 现货: {ta_spot:.0f}" if ta_spot else "")
    
    # 技术
    t_score, t_label, t_detail = get_tech_signal(ta_df, ta_spot_row)
    print(f"\n  技术信号: {t_label}({t_score})")
    print(f"    {t_detail}")
    
    # 期权
    o_result = get_option_signal(opt_df)
    if len(o_result) == 4:
        o_score, o_label, o_detail, o_extra = o_result
    else:
        o_score, o_label, o_detail = o_result
        o_extra = {}
    print(f"\n  期权信号: {o_label}({o_score})")
    print(f"    {o_detail}")
    if o_extra:
        print(f"    PCR(持仓): {o_extra.get('pcr_oi')}")
        print(f"    IV均值: 认购={o_extra.get('call_iv_mean')}% 认沽={o_extra.get('put_iv_mean')}%")
        print(f"    认购期权墙: {o_extra.get('call_wall', [])[:2]}")
        print(f"    认沽期权墙: {o_extra.get('put_wall', [])[:2]}")
    
    # 综合
    c_score, c_phase, c_desc = composite_signal(m_score, t_score, o_score)
    print(f"\n  → 综合判断: {c_phase}({c_score})")
    print(f"    {c_desc}")
    
    # ---- 飞书推送 ----
    report['macro'] = {'score': m_score, 'label': m_label, 'detail': m_detail}
    report['tech'] = {'score': t_score, 'label': t_label, 'detail': t_detail}
    report['option'] = {'score': o_score, 'label': o_label, 'detail': o_detail}
    report['composite'] = {'score': c_score, 'phase': c_phase, 'desc': c_desc}
    if o_extra:
        report['option_extra'] = o_extra
    
    # 推送内容
    emoji = {"偏多信号": "📈", "偏空信号": "📉", "观望": "➡️", "杀期权阶段": "🔪", "狂热顶共振": "🔥", "恐慌底共振": "🧊"}
    e = emoji.get(c_phase, "📊")
    
    push_text = f"""📊 PTA分析报告 {now.strftime('%m/%d %H:%M')}

🌍 宏观: {m_label}
   布伦特: ${brent_price} | PX: {px_price} | PTA现货: {ta_spot}
   成本区间: {cost_low:.0f}~{cost_high:.0f}元/吨
   {m_detail}

📈 技术: {t_label}({t_score})
   {t_detail}

🎯 期权: {o_label}({o_score})
   PCR持仓: {o_extra.get('pcr_oi', 'N/A')}
   IV: 认购{o_extra.get('call_iv_mean','?')}% / 认沽{o_extra.get('put_iv_mean','?')}%
   {o_detail}

{e} 综合: {c_phase}
   {c_desc}

#PTA #期权分析"""
    
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
