#!/usr/bin/env python3
# PTA期权微观分析 v5 - 三层防线（成本逻辑）
import re
import pandas as pd
import akshare as ak
import datetime


def _s(x):
    m = re.search(r'[CP](\d+)', str(x))
    return int(m.group(1)) if m else None


def _t(x):
    return 'C' if 'C' in str(x) else 'P'


def analyze(df, fp=7000):
    """
    三层防线按成本逻辑定义：
      地板L1 = 成本区间（6950~7354）—— 正常支撑
      地板L2 = 成本-300（6650~6950）—— 成本强化支撑
      地板L3 = 成本-500（6450~6650）—— 极端情况支撑
      天花板L1 = 成本+300（7250~7550）—— 利润锁定下沿
      天花板L2 = 成本+500（7450~7750）—— 利润锁点上沿
      天花板L3 = 成本+800（7750~8150）—— 极端目标
    """
    if df is None or df.empty:
        return {}

    df = df.copy()
    df['k'] = df['合约代码'].apply(_s)
    df['t'] = df['合约代码'].apply(_t)
    c = df[df['t'] == 'C'].copy()
    p = df[df['t'] == 'P'].copy()

    tcv = int(c['成交量(手)'].sum())
    tpv = int(p['成交量(手)'].sum())
    pcr = round(tpv / tcv, 4) if tcv > 0 else None

    # 成交量Top3（短期博弈焦点）
    t3c = [[str(r[0]), int(r[1]), int(r[2])] for r in c.nlargest(3, '成交量(手)')[['合约代码', 'k', '成交量(手)']].values.tolist()]
    t3p = [[str(r[0]), int(r[1]), int(r[2])] for r in p.nlargest(3, '成交量(手)')[['合约代码', 'k', '成交量(手)']].values.tolist()]

    cz = c[c['k'] > fp].copy()
    fz = p[p['k'] < fp].copy()

    # 地板三层防线（成本支撑逻辑）
    # L1: 6600~7000 = 成本支撑区（正常支撑）
    # L2: 5500~6600 = 成本缓冲带（大资金套保密集区）
    # L3: 4500~5500 = 深成本防线（极端成本支撑）
    def make_level(zd, lo, hi, label):
        z = zd[(zd['k'] >= lo) & (zd['k'] < hi)]
        if z.empty:
            return None
        oi = int(z['持仓量'].sum())
        top = z.nlargest(1, '持仓量').iloc[0]
        return {
            'label': label,
            'oi': oi,
            'code': str(top['合约代码']),
            'top_oi': int(top['持仓量']),
            'top_iv': float(top['隐含波动率']),
            'n': len(z)
        }

    fl1 = make_level(fz, 6600, 7000, 'L1成本6600~7000')
    fl2 = make_level(fz, 5500, 6600, 'L2缓冲5500~6600')
    fl3 = make_level(fz, 4500, 5500, 'L3深成本4500~5500')

    # 天花板三层防线（利润锁定逻辑）
    # L1: 7000~7400 = 近端压力（短期目标）
    # L2: 7400~8000 = 中端目标（正常利润区）
    # L3: 8000~8600 = 远端目标（极端目标）
    cl1 = make_level(cz, 7000, 7400, 'L1近端7000~7400')
    cl2 = make_level(cz, 7400, 8000, 'L2中端7400~8000')
    cl3 = make_level(cz, 8000, 8600, 'L3远端8000~8600')

    def sum_oi(lvlist):
        return sum(x['oi'] for x in lvlist if x)

    ft1 = sum_oi([fl1]); ft2 = sum_oi([fl2]); ft3 = sum_oi([fl3])
    ct1 = sum_oi([cl1]); ct2 = sum_oi([cl2]); ct3 = sum_oi([cl3])
    ftot = ft1 + ft2 + ft3
    ctot = ct1 + ct2 + ct3
    gr = round(ftot / ctot, 2) if ctot > 0 else None

    # IV曲面（ATM附近，正负3%）
    lo_iv, hi_iv = int(fp * 0.97), int(fp * 1.03)
    ac = c[(c['k'] >= lo_iv) & (c['k'] <= hi_iv)]
    ap = p[(p['k'] >= lo_iv) & (p['k'] <= hi_iv)]
    civ = round(ac['隐含波动率'].dropna().mean(), 1) if not ac['隐含波动率'].dropna().empty else None
    piv = round(ap['隐含波动率'].dropna().mean(), 1) if not ap['隐含波动率'].dropna().empty else None
    ivd = round(piv - civ, 1) if (civ and piv) else None

    # 评分
    sc = 0
    sg = []
    if pcr:
        if pcr < 0.5:
            sc += 1
            sg.append('PCR=%.2f认购主导' % pcr)
        elif pcr > 1.5:
            sc -= 1
            sg.append('PCR=%.2f认沽主导' % pcr)
        elif pcr > 1.0:
            sc -= 0.5
            sg.append('PCR=%.2f偏空' % pcr)
    if gr:
        if gr > 2.0:
            sc -= 2
            sg.append('地板%d>天花板%d防%.2fx极强' % (ftot, ctot, gr))
        elif gr > 1.5:
            sc -= 1
            sg.append('地板%d>天花板%d防%.2fx' % (ftot, ctot, gr))
    if ivd:
        if ivd > 5:
            sc -= 1
            sg.append('PutIV(%.1f)>CallIV(%.1f)下跌溢价' % (piv, civ))
        elif ivd < -5:
            sc += 1
            sg.append('CallIV(%.1f)>PutIV(%.1f)上涨溢价' % (civ, piv))

    ts = max(-4, min(4, sc))
    lb = '期权偏多' if ts >= 2 else ('期权偏空' if ts <= -2 else '期权中性')

    # 日间变化
    dc = []
    for i in range(1, 20):
        d = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%Y%m%d')
        try:
            pdf = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            if not pdf.empty and len(pdf) > 200:
                cur = df[df['合约代码'].str.startswith('TA605')].set_index('合约代码')
                prv = pdf[pdf['合约代码'].str.startswith('TA605')].set_index('合约代码')
                for co in cur.index:
                    if co in prv.index:
                        rc, rp = cur.loc[co], prv.loc[co]
                        dc.append({
                            'code': co,
                            'type': rc['t'],
                            'strike': int(rc['k']),
                            'oi_chg': int(rc['持仓量']) - int(rp['持仓量']),
                            'vol_chg': int(rc['成交量(手)']) - int(rp['成交量(手)']),
                            'iv_chg': round(float(rc['隐含波动率']) - float(rp['隐含波动率']), 2)
                        })
                break
        except:
            pass

    return {
        'pcr': pcr,
        'pcr_display': '%.2f' % pcr if pcr else 'N/A',
        't3c': t3c,
        't3p': t3p,
        'tcv': tcv,
        'tpv': tpv,
        'fl1': fl1, 'fl2': fl2, 'fl3': fl3,
        'ft1': ft1, 'ft2': ft2, 'ft3': ft3, 'ftot': ftot,
        'cl1': cl1, 'cl2': cl2, 'cl3': cl3,
        'ct1': ct1, 'ct2': ct2, 'ct3': ct3, 'ctot': ctot,
        'gr': gr,
        'civ': civ, 'piv': piv, 'ivd': ivd,
        'score': ts,
        'label': lb,
        'detail': ';'.join(sg) if sg else '信息不足',
        'dc': dc
    }


def report(r, fp=7000):
    if not r:
        return 'No data'

    lines = []
    lines.append('[期权] %s(%+d) PCR=%s' % (r['label'], r['score'], r.get('pcr_display', 'N/A')))
    lines.append('  短期博弈(成交量Top3):')
    for c in r.get('t3c', []):
        lines.append('    购 %s: %d手' % (c[0], c[2]))
    for p in r.get('t3p', []):
        lines.append('    沽 %s: %d手' % (p[0], p[2]))

    lines.append('  地板防线(OI=%d):' % r.get('ftot', 0))
    for lv in [r.get('fl1'), r.get('fl2'), r.get('fl3')]:
        if lv:
            lines.append('    %s: OI=%d | %s(%d IV=%.1f%%)' % (
                lv['label'], lv['oi'], lv['code'], lv['top_oi'], lv['top_iv']))

    lines.append('  天花板防线(OI=%d):' % r.get('ctot', 0))
    for lv in [r.get('cl1'), r.get('cl2'), r.get('cl3')]:
        if lv:
            lines.append('    %s: OI=%d | %s(%d IV=%.1f%%)' % (
                lv['label'], lv['oi'], lv['code'], lv['top_oi'], lv['top_iv']))

    lines.append('  梯度比(地板/天花板)=%s IV:Call=%s%% Put=%s%% Diff=%s%%' % (
        r.get('gr'), r.get('civ'), r.get('piv'), r.get('ivd')))
    lines.append('  %s' % r['detail'])
    lines.append('  日间变化(OI/Vol/IV):')

    if r.get('dc'):
        sig = sorted(r['dc'], key=lambda x: abs(x['oi_chg']), reverse=True)
        for c in sig[:10]:
            oi = c['oi_chg']
            vo = c['vol_chg']
            ivv = c['iv_chg']
            if abs(oi) >= 2000 or abs(vo) >= 8000 or abs(ivv) >= 0.5:
                lines.append('    %s(%s,行权价%d): OI%+d Vol%+d IV%+0.1f%%' % (
                    c['code'], c['type'], c['strike'], oi, vo, ivv))
    else:
        lines.append('    无历史数据')

    return '\n'.join(lines)


if __name__ == '__main__':
    now = datetime.datetime.now()
    for i in range(1, 8):
        d = (now - datetime.timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            ta = df[df['合约代码'].str.startswith('TA605')]
            if not ta.empty:
                print(report(analyze(df, fp=6988)))
                break
        except Exception as e:
            print('%s: %s' % (d, e))
