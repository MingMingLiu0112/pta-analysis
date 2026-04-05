"""
PTA期货 MACD/KDJ 多周期指标扫描
用于各级别背驰判断
"""
import akshare as ak, pandas as pd, numpy as np, warnings, json, os
from datetime import datetime

warnings.filterwarnings('ignore')

def get_1min_data(symbol='TA0', bars=800):
    """获取1分钟原始数据"""
    df = ak.futures_zh_minute_sina(symbol=symbol, period='1')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').tail(bars).reset_index(drop=True)
    return df

def resample(df, period='5T'):
    """聚合周期转换"""
    df = df.set_index('datetime')
    resampled = df.resample(period).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    resampled = resampled.reset_index()
    return resampled

def calc_macd(close, fast=12, slow=26, signal=9):
    """MACD指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    """KDJ指标"""
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)
    K = rsv.ewm(com=m1-1, adjust=False).mean()
    D = K.ewm(com=m2-1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J

def get_period_indicators(df_1min, period_label, period_code):
    """获取指定周期的指标"""
    try:
        if period_code == '1T':
            df = df_1min.copy()
        else:
            df = resample(df_1min, period_code)
        
        if len(df) < 30:
            return {'period': period_label, 'error': f'数据不足({len(df)}根)'}
        
        close = df['close']
        dif, dea, macd = calc_macd(close)
        k, d, j = calc_kdj(df['high'], df['low'], close)
        
        last = df.iloc[-1]
        macd_last = macd.iloc[-1]
        
        # MACD状态
        macd_state = "多头" if macd_last > 0 else "空头" if macd_last < 0 else "中性"
        dif_change = "上升" if dif.iloc[-1] > dif.iloc[-2] else "下降"
        
        return {
            'period': period_label,
            'datetime': last['datetime'].strftime('%Y-%m-%d %H:%M'),
            'close': round(float(last['close']), 0),
            'bars': len(df),
            'macd': {
                'dif': round(float(dif.iloc[-1]), 4),
                'dea': round(float(dea.iloc[-1]), 4),
                'macd': round(float(macd_last), 4),
                'dif_change': dif_change,
                'state': macd_state,
            },
            'kdj': {
                'K': round(float(k.iloc[-1]), 2),
                'D': round(float(d.iloc[-1]), 2),
                'J': round(float(j.iloc[-1]), 2),
            }
        }
    except Exception as e:
        return {'period': period_label, 'error': str(e)}

def scan_all_periods(symbol='TA0'):
    """扫描所有周期"""
    df_1min = get_1min_data(symbol, bars=800)
    
    periods = [
        ('1分钟', '1T'),
        ('5分钟', '5T'),
        ('15分钟', '15T'),
        ('30分钟', '30T'),
        ('60分钟', '60T'),
    ]
    
    results = {}
    for label, code in periods:
        r = get_period_indicators(df_1min, label, code)
        results[label] = r
    
    return results, df_1min

def get_report(symbol='TA0'):
    """获取完整报告"""
    results, df_1min = scan_all_periods(symbol)
    
    lines = []
    lines.append("=" * 70)
    lines.append(f"PTA MACD/KDJ 多周期指标  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    lines.append("=" * 70)
    
    for period in ['1分钟', '5分钟', '15分钟', '30分钟', '60分钟']:
        if period not in results or 'error' in results[period]:
            continue
        r = results[period]
        m = r['macd']
        k = r['kdj']
        macd_arrow = "▲" if m['macd'] > 0 else "▼"
        lines.append(f"\n【{period}】{r['datetime']}  价格={r['close']:.0f}  ({r['bars']}根)")
        lines.append(f"  MACD: DIF={m['dif']:>8.4f}  DEA={m['dea']:>8.4f}  MACD={m['macd']:>8.4f} {macd_arrow} [{m['state']}] {m['dif_change']}")
        lines.append(f"  KDJ:  K={k['K']:>6.2f}    D={k['D']:>6.2f}    J={k['J']:>8.2f}")
    
    lines.append("\n" + "=" * 70)
    return "\n".join(lines), results, df_1min

if __name__ == '__main__':
    report, results, df_1min = get_report()
    print(report)
    
    # 保存
    with open('indicator_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    df_1min.to_csv('pta_1min_raw.csv', index=False, encoding='utf-8')
    print("\n已保存 indicator_results.json 和 pta_1min_raw.csv")
