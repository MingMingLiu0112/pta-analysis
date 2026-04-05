# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## 天勤量化TqSdk账户

### TqKq快期模拟账户
```python
from tqsdk import TqApi, TqAuth, TqKq

api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))
```

### 获取数据示例
```python
# 获取K线
klines = api.get_kline_serial('KQ.m@CZCE.TA', 86400, data_length=8000)

# 获取行情
quote = api.get_quote('KQ.m@CZCE.TA')

# 等待数据更新
while True:
    api.wait_update()
    print(quote.last_price)
```
