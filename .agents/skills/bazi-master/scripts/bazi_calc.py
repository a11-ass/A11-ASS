# -*- coding: utf-8 -*-
"""
bazi_calc.py — 八字排盘引擎（确定性算法，自包含，不依赖第三方库）
口径依据：年以立春为界；月以交节（节气）为界；日用儒略日；时以23:00为次日；
          大运阳男阴女顺、阴男阳女逆，起运岁数=出生到交节实足天数/3。
日柱常数经双锚校准：1965-12-16=甲辰(40)，2000-01-01=戊午(54)。
"""
import math
from datetime import datetime, timedelta

# ---------------- 基础数据 ----------------
TIANGAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DIZHI  = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
GZ = [(TIANGAN[i % 10], DIZHI[i % 12]) for i in range(60)]  # 标准60甲子循环
GAN_WUXING = ["木", "木", "火", "火", "土", "土", "金", "金", "水", "水"]
GAN_YINYANG = ["阳", "阴", "阳", "阴", "阳", "阴", "阳", "阴", "阳", "阴"]
ZHI_WUXING = ["水", "土", "木", "木", "土", "火", "火", "土", "金", "金", "土", "水"]
ZHI_HIDE = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"],
    "卯": ["乙"], "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"],
    "午": ["丁", "己"], "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"],
    "酉": ["辛"], "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"],
}
NAYIN = [
    "海中金","海中金","炉中火","炉中火","大林木","大林木","路旁土","路旁土","剑锋金","剑锋金",
    "山头火","山头火","涧下水","涧下水","城头土","城头土","白蜡金","白蜡金","杨柳木","杨柳木",
    "泉中水","泉中水","屋上土","屋上土","霹雳火","霹雳火","松柏木","松柏木","长流水","长流水",
    "沙中金","沙中金","山下火","山下火","平地木","平地木","壁上土","壁上土","金箔金","金箔金",
    "覆灯火","覆灯火","天河水","天河水","大驿土","大驿土","钗钏金","钗钏金","桑松木","桑松木",
    "大溪水","大溪水","沙中土","沙中土","天上火","天上火","石榴木","石榴木","大海水","大海水",
]
CHANGSHENG = ["长生","沐浴","冠带","临官","帝旺","衰","病","死","墓","绝","胎","养"]
CHANGSHENG_ZHI = {"甲":"亥","丙":"寅","戊":"寅","庚":"巳","壬":"申"}
YANGREN = {"甲":"卯","乙":"辰","丙":"午","丁":"未","戊":"午","己":"未","庚":"酉","辛":"戌","壬":"子","癸":"丑"}
LUSHEN = {"甲":"寅","乙":"卯","丙":"巳","丁":"午","戊":"巳","己":"午","庚":"申","辛":"酉","壬":"亥","癸":"子"}
WENCHANG = {"甲":"巳","乙":"午","丙":"申","丁":"酉","戊":"申","己":"酉","庚":"亥","辛":"子","壬":"寅","癸":"卯"}
TIANYI = {"甲":["丑","未"],"戊":["丑","未"],"庚":["丑","未"],
          "乙":["子","申"],"己":["子","申"],
          "丙":["亥","酉"],"丁":["亥","酉"],
          "壬":["卯","巳"],"癸":["卯","巳"],"辛":["寅","午"]}
TAOHUA = {"寅":"卯","午":"卯","戌":"卯","申":"酉","子":"酉","辰":"酉","巳":"午","酉":"午","丑":"午","亥":"子","卯":"子","未":"子"}
YIMA = {"寅":"申","午":"申","戌":"申","申":"寅","子":"寅","辰":"寅","巳":"亥","酉":"亥","丑":"亥","亥":"巳","卯":"巳","未":"巳"}
HUAGAI = {"寅":"戌","午":"戌","戌":"戌","申":"辰","子":"辰","辰":"辰","巳":"丑","酉":"丑","丑":"丑","亥":"未","卯":"未","未":"未"}

def gz_index(g, z):
    """干支在60甲子中的0基序号（甲子=0）。用同余反解，保证 GZ[gz_index(g,z)]==(g,z)"""
    gi = TIANGAN.index(g); zi = DIZHI.index(z)
    k = ((gi - zi) // 2) % 6          # 解 i≡gi(mod10), i≡zi(mod12)
    return (gi + 10 * k) % 60

# ---------------- 儒略日（Fliegel 公式，返回"真太阳时"标准JD，自0h起算）----------------
def cal_to_jd(y, mo, d, hh=12, mm=0, ss=0):
    if mo <= 2:
        y -= 1; mo += 12
    A = (14 - mo) // 12
    yy = y + 4800 - A
    mm2 = mo + 12 * A - 3
    JDN = d + (153 * mm2 + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    frac = (hh * 3600 + mm * 60 + ss) / 86400.0
    return JDN - 0.5 + frac   # 标准JD：整数部分为当日0h之JD

def jd_to_cal(jd):
    Z = int(jd + 0.5)
    F = (jd + 0.5) - Z
    if Z < 2299161:
        A = Z
    else:
        alpha = int((Z - 1867216.25) / 36524.25)
        A = Z + 1 + alpha - int(alpha / 4)
    B = A + 1524
    C = int((B - 122.1) / 365.25)
    D = int(365.25 * C)
    E = int((B - D) / 30.6001)
    day = B - D - int(30.6001 * E) + F
    if E < 14:
        month = E - 1
    else:
        month = E - 13
    if month > 2:
        year = C - 4716
    else:
        year = C - 4715
    d_int = int(day); frac = day - d_int
    hour = frac * 24; h = int(hour); m = int((hour - h) * 60); s = int(((hour - h) * 60 - m) * 60)
    return year, month, d_int, h, m, s

# ---------------- 节气（Meeus 低精度太阳黄经 + 牛顿迭代）----------------
def solar_app_longitude(jd_ut):
    T = (jd_ut - 2451545.0) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
    Mr = math.radians(M)
    C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(Mr) \
        + (0.019993 - 0.000101 * T) * math.sin(2 * Mr) \
        + 0.000289 * math.sin(3 * Mr)
    L = L0 + C
    omega = 125.04 - 1934.136 * T
    return (L - 0.00569 - 0.00478 * math.sin(math.radians(omega))) % 360.0

def find_solar_term(year, target_lon):
    """求某年太阳视黄经达 target_lon 的 UT 儒略日（二分法，正确处理黄经环绕）"""
    j0 = cal_to_jd(year, 1, 1, 0, 0, 0)
    l0 = solar_app_longitude(j0)
    delta = (target_lon - l0) % 360.0          # 立春后需要前进的黄经度数（0~360）
    approx = delta / 0.985647                  # 太阳日均行约 0.9856°
    a = j0 + approx - 30.0
    b = j0 + approx + 30.0
    for _ in range(60):
        m = (a + b) / 2.0
        # 带符号的"距目标黄经差"，范围 (-180,180]，黄经递增故单调
        diff = (solar_app_longitude(m) - target_lon + 540.0) % 360.0 - 180.0
        if diff < 0:
            a = m
        else:
            b = m
    return (a + b) / 2.0

# 12 节（换月令节点，即"交节"）黄经、月支、名称
# 黄经：立春315 惊蛰345 清明15 立夏45 芒种75 小暑105 立秋135 白露165 寒露195 立冬225 大雪255 小寒285
MONTH_SOLAR = [(315,"寅","立春"),(345,"卯","惊蛰"),(15,"辰","清明"),(45,"巳","立夏"),
               (75,"午","芒种"),(105,"未","小暑"),(135,"申","立秋"),(165,"酉","白露"),
               (195,"戌","寒露"),(225,"亥","立冬"),(255,"子","大雪"),(285,"丑","小寒")]

def get_terms_around(dt_beijing):
    # 统一以"北京时间JD"为基准：出生当地时间直接当UT代入，节气(+8h)同为北京时间JD
    jd_bj = cal_to_jd(dt_beijing.year, dt_beijing.month, dt_beijing.day,
                      dt_beijing.hour, dt_beijing.minute, dt_beijing.second)
    terms = []
    for yr in (dt_beijing.year - 1, dt_beijing.year, dt_beijing.year + 1):
        for lon, zhi, name in MONTH_SOLAR:
            terms.append((find_solar_term(yr, lon) + 8.0/24.0, zhi, name, lon, yr))
    terms.sort()
    cur = None; nxt = None
    for i, t in enumerate(terms):
        if t[0] <= jd_bj:
            cur = t
            if i + 1 < len(terms):
                nxt = terms[i + 1]
        else:
            if nxt is None:
                nxt = t
            break
    if nxt is None:
        nxt = (find_solar_term(dt_beijing.year + 1, 315) + 8.0/24.0, "寅", "立春", 315, dt_beijing.year + 1)
    return cur, nxt

# ---------------- 排四柱 ----------------
def year_pillar(dt_beijing):
    jd_bj = cal_to_jd(dt_beijing.year, dt_beijing.month, dt_beijing.day,
                      dt_beijing.hour, dt_beijing.minute, dt_beijing.second)
    lichun = find_solar_term(dt_beijing.year, 315) + 8.0/24.0
    lichun_prev = find_solar_term(dt_beijing.year - 1, 315) + 8.0/24.0
    y = dt_beijing.year - 1 if jd_bj < lichun else dt_beijing.year
    idx = (y - 4) % 60
    return TIANGAN[idx % 10], DIZHI[idx % 12], y

def month_pillar(dt_beijing, yg):
    cur, nxt = get_terms_around(dt_beijing)
    mz = cur[1]
    start_map = {"甲":"丙","己":"丙","乙":"戊","庚":"戊","丙":"庚","辛":"庚","丁":"壬","壬":"壬","戊":"甲","癸":"甲"}
    first = start_map[yg]
    zhi_order = ["寅","卯","辰","巳","午","未","申","酉","戌","亥","子","丑"]
    pos = zhi_order.index(mz)
    mg = TIANGAN[(TIANGAN.index(first) + pos) % 10]
    return mg, mz, {"cur": cur, "next": nxt}

def day_pillar(dt_beijing):
    y, mo, d, hh, mm, ss = (dt_beijing.year, dt_beijing.month, dt_beijing.day,
                            dt_beijing.hour, dt_beijing.minute, dt_beijing.second)
    if hh >= 23:
        nb = datetime(y, mo, d) + timedelta(days=1)
        y, mo, d = nb.year, nb.month, nb.day
    JDN = int(cal_to_jd(y, mo, d, 0, 0, 0))
    idx = (JDN + 50) % 60   # 甲子=0，双锚校准：1965-12-16=甲辰(40)，2000-01-01=戊午(54)
    return TIANGAN[idx % 10], DIZHI[idx % 12]

def hour_pillar(day_gan, dt_beijing):
    hh = dt_beijing.hour
    # 23:00–23:59 为晚子时，归次日，且按"子时"取支（日干已由 day_pillar 顺延到次日）
    if hh == 23:
        zhi_h = "子"
    else:
        zhi_h = DIZHI[(hh // 2) % 12]
    start_map = {"甲":"甲","己":"甲","乙":"丙","庚":"丙","丙":"戊","辛":"戊","丁":"庚","壬":"庚","戊":"壬","癸":"壬"}
    first = start_map[day_gan]
    pos = DIZHI.index(zhi_h)
    return TIANGAN[(TIANGAN.index(first) + pos) % 10], zhi_h

# ---------------- 十神 ----------------
def shishen(day_gan, other_gan):
    if other_gan is None:
        return None
    dw = GAN_WUXING[TIANGAN.index(day_gan)]
    ow = GAN_WUXING[TIANGAN.index(other_gan)]
    ds = GAN_YINYANG[TIANGAN.index(day_gan)]
    os = GAN_YINYANG[TIANGAN.index(other_gan)]
    if dw == ow:
        return "比肩" if ds == os else "劫财"
    if (dw == "木" and ow == "水") or (dw == "火" and ow == "木") or \
       (dw == "土" and ow == "火") or (dw == "金" and ow == "土") or \
       (dw == "水" and ow == "金"):
        return "正印" if ds != os else "偏印"
    if (ow == "木" and dw == "水") or (ow == "火" and dw == "木") or \
       (ow == "土" and dw == "火") or (ow == "金" and dw == "土") or \
       (ow == "水" and dw == "金"):
        return "伤官" if ds != os else "食神"
    if (dw == "木" and ow == "金") or (dw == "火" and ow == "水") or \
       (dw == "土" and ow == "木") or (dw == "金" and ow == "火") or \
       (dw == "水" and ow == "土"):
        return "正官" if ds != os else "七杀"
    if (ow == "木" and dw == "金") or (ow == "火" and dw == "水") or \
       (ow == "土" and dw == "木") or (ow == "金" and dw == "火") or \
       (ow == "水" and dw == "土"):
        return "正财" if ds != os else "偏财"
    return "?"

def changsheng_of(day_gan, zhi):
    yinyang = GAN_YINYANG[TIANGAN.index(day_gan)]
    if day_gan in CHANGSHENG_ZHI:
        start_zhi = CHANGSHENG_ZHI[day_gan]
    else:
        yang_gan = {"乙":"甲","丁":"丙","己":"戊","辛":"庚","癸":"壬"}[day_gan]
        start_zhi = CHANGSHENG_ZHI[yang_gan]
    if yinyang == "阳":
        start = DIZHI.index(start_zhi)
        return CHANGSHENG[(DIZHI.index(zhi) - start) % 12]
    else:
        chong = {"亥":"巳","寅":"申","巳":"亥","申":"寅"}[start_zhi]
        start = DIZHI.index(chong)
        return CHANGSHENG[(start - DIZHI.index(zhi)) % 12]

def xunkong(day_g, day_z):
    idx = gz_index(day_g, day_z)
    xun_start = (idx // 10) * 10
    present = set()
    for k in range(10):
        present.add(GZ[(xun_start + k) % 60][1])
    return [z for z in DIZHI if z not in present]

def find_shensha(day_g, day_z):
    return {
        "天乙贵人": TIANYI.get(day_g, []),
        "文昌": WENCHANG.get(day_g, ""),
        "羊刃": YANGREN.get(day_g, ""),
        "禄神": LUSHEN.get(day_g, ""),
        "桃花": TAOHUA.get(day_z, ""),
        "驿马": YIMA.get(day_z, ""),
        "华盖": HUAGAI.get(day_z, ""),
    }

def dayun(birth_dt, year_g, month_g, month_z, gender, cur, nxt):
    yyang = GAN_YINYANG[TIANGAN.index(year_g)]
    male = (gender == "男")
    if (yyang == "阳" and male) or (yyang == "阴" and not male):
        direction = "顺"; tgt = nxt
    else:
        direction = "逆"; tgt = cur
    bjd = cal_to_jd(birth_dt.year, birth_dt.month, birth_dt.day,
                    birth_dt.hour, birth_dt.minute, birth_dt.second)
    d_days = (tgt[0] - bjd) if direction == "顺" else (bjd - tgt[0])
    if d_days < 0:
        d_days = 0
    start_age = d_days / 3.0
    jiaoyun = birth_dt + timedelta(days=start_age * 365.2425)
    m_idx = gz_index(month_g, month_z)
    seq = []
    for i in range(1, 11):
        sidx = (m_idx + i) % 60 if direction == "顺" else (m_idx - i) % 60
        seq.append(GZ[sidx])
    return start_age, jiaoyun, direction, seq, d_days

def bazi_chart(year, month, day, hour, minute, gender):
    dt = datetime(year, month, day, hour, minute, 0)
    yg, yz, yreal = year_pillar(dt)
    mg, mz, terminfo = month_pillar(dt, yg)
    dg, dz = day_pillar(dt)
    hg, hz = hour_pillar(dg, dt)
    pillars = {"年": (yg, yz), "月": (mg, mz), "日": (dg, dz), "时": (hg, hz)}
    shis = {k: shishen(dg, pillars[k][0]) for k in pillars}
    wuxing_count = {"木":0,"火":0,"土":0,"金":0,"水":0}
    for k in pillars:
        g, z = pillars[k]
        wuxing_count[GAN_WUXING[TIANGAN.index(g)]] += 1
        for h in ZHI_HIDE[z]:
            wuxing_count[GAN_WUXING[TIANGAN.index(h)]] += 1
    nayin = {k: NAYIN[gz_index(*pillars[k])] for k in pillars}
    canggan = {k: ZHI_HIDE[pillars[k][1]] for k in pillars}
    cs = {k: changsheng_of(dg, pillars[k][1]) for k in pillars}
    xk = xunkong(dg, dz)
    sh = find_shensha(dg, dz)
    start_age, jiaoyun, direction, seq, d_days = dayun(dt, yg, mg, mz, gender, terminfo["cur"], terminfo["next"])
    return {"birth": dt, "gender": gender, "pillars": pillars, "shishen": shis,
            "wuxing_count": wuxing_count, "nayin": nayin, "canggan": canggan,
            "changsheng": cs, "xunkong": xk, "shensha": sh,
            "dayun": {"start_age": start_age, "jiaoyun": jiaoyun, "direction": direction,
                      "seq": seq, "to_jie_days": d_days}, "year_real": yreal}

def format_chart(r):
    p = r["pillars"]; s = r["shishen"]
    L = []
    L.append(f"性别：{r['gender']}  出生：{r['birth']}（北京时间，23:00起为次日）")
    L.append("四柱：  年      月      日      时")
    L.append("      " + "  ".join(f"{p[k][0]}{p[k][1]}" for k in ["年","月","日","时"]))
    L.append("十神： " + "  ".join(f"{s[k] or '　':<2}" for k in ["年","月","日","时"]))
    L.append(f"纳音： " + "  ".join(r["nayin"][k] for k in ["年","月","日","时"]))
    L.append(f"五行（含藏干）：" + " ".join(f"{k}{v}" for k,v in r["wuxing_count"].items()))
    L.append(f"日干：{p['日'][0]}  旬空：{' '.join(r['xunkong'])}")
    L.append(f"长生（日干）：年{r['changsheng']['年']} 月{r['changsheng']['月']} 日{r['changsheng']['日']} 时{r['changsheng']['时']}")
    sh = r["shensha"]
    L.append(f"神煞：天乙[{','.join(sh['天乙贵人'])}] 文昌{sh['文昌']} 羊刃{sh['羊刃']} 禄{sh['禄神']} 桃花{sh['桃花']} 驿马{sh['驿马']} 华盖{sh['华盖']}")
    du = r["dayun"]
    L.append(f"大运：{du['direction']}行  起运{du['start_age']:.2f}岁（约{du['jiaoyun']:%Y-%m-%d}交运，到交节{du['to_jie_days']:.1f}天）")
    L.append(f"大运序列（每步10年）：" + "  ".join(f"{g}{z}" for g,z in du["seq"]))
    return "\n".join(L)

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        dtstr = sys.argv[1].replace("/", "-"); gender = sys.argv[2]
        parts = dtstr.split(" ")
        ymd = parts[0].split("-"); y, mo, d = int(ymd[0]), int(ymd[1]), int(ymd[2])
        h, mi = 0, 0
        if len(parts) > 1:
            hm = parts[1].split(":"); h, mi = int(hm[0]), (int(hm[1]) if len(hm) > 1 else 0)
        print(format_chart(bazi_chart(y, mo, d, h, mi, gender)))
    else:
        print('用法：python bazi_calc.py "1965-12-16 06:06" 男')
