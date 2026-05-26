# {{ title }}

> 版本 v{{ version }} · 生成时间 {{ generated_at }}

---

## 概览

| 项目 | 内容 |
|------|------|
| 出发地 | {{ departure or "—" }} |
| 目的地 | {{ destination }} |
| 出行人数 | {{ people_num }} 人 |
| 行程天数 | {{ days_num }} 天 |
| 出行日期 | {{ start_date or "—" }} |
| 主题 | {{ travel_theme or "通用" }} |
| 预算档位 | {{ budget.level or "—" }} |
| 预算总计 | {{ budget.currency }} {{ '%.0f'|format(budget.total) }}（人均 {{ '%.0f'|format(budget.per_person) }} · 日均 {{ '%.0f'|format(budget.daily_avg or 0) }}）|
{% if review_feedback %}| 审稿建议 | {{ review_feedback }} |{% endif %}

{% if summary %}
{{ summary }}
{% endif %}

---

## 每日行程

{% for day in itinerary %}
### Day {{ day.day_index }}{% if day.date %} · {{ day.date }}{% endif %}{% if day.area %} · {{ day.area }}{% endif %}

{% if day.weather_summary %}☀️ **天气**：{{ day.weather_summary }}{% endif %}

| 时段 | 安排 | 类型 | 备注 |
|------|------|------|------|
{% for slot in day.slots -%}
| {{ slot.slot }} | {{ slot.poi }} | {{ slot.type }} | {{ slot.note or "—" }} |
{% endfor %}

{% if day.meals %}
**🍽 餐饮**
{% if day.meals.breakfast %}- 早餐：{{ day.meals.breakfast }}{% endif %}
{% if day.meals.lunch %}- 午餐：{{ day.meals.lunch }}{% endif %}
{% if day.meals.dinner %}- 晚餐：{{ day.meals.dinner }}{% endif %}
{% endif %}

{% if day.transport_hint %}🚇 **交通**：{{ day.transport_hint }}{% endif %}

{% if day.daily_cost_cny %}💰 **当日预估**：CNY {{ '%.0f'|format(day.daily_cost_cny) }}（不含机票/酒店）{% endif %}

{% if day.booking_notes %}
📌 **预订提醒**
{% for note in day.booking_notes %}- {{ note }}
{% endfor %}
{% endif %}

{% endfor %}

---

## 推荐机票

{% if flights %}
| 方向 | 航空 | 航班号 | 起飞 | 到达 | 时长(分) | 经停 | 价格 |
|------|------|--------|------|------|----------|------|------|
{% for f in flights[:6] -%}
| {{ f.direction }} | {{ f.airline }} | {{ f.flight_no }} | {{ f.depart_time }} | {{ f.arrive_time }} | {{ f.duration_minutes }} | {{ f.stops }} | {{ '%.0f'|format(f.price) }} |
{% endfor %}
{% else %}
> 暂未获取到候选航班。
{% endif %}

## 推荐酒店

{% if hotels %}
| 酒店 | 区域 | 单晚价格 | 评分 | 亲子友好 |
|------|------|----------|------|----------|
{% for h in hotels[:6] -%}
| {{ h.name }} | {{ h.area }} | {{ '%.0f'|format(h.price_per_night) }} | {{ h.rating }} | {% if h.kid_friendly %}是{% else %}否{% endif %} |
{% endfor %}
{% else %}
> 暂未获取到候选酒店。
{% endif %}

## 预算明细

| 项目 | 金额（{{ budget.currency }}）|
|------|------|
| 机票 | {{ '%.0f'|format(budget.flights) }} |
| 酒店 | {{ '%.0f'|format(budget.hotels) }} |
| 景点门票 | {{ '%.0f'|format(budget.pois) }} |
| 餐饮 | {{ '%.0f'|format(budget.meals) }} |
| 当地交通 | {{ '%.0f'|format(budget.transport) }} |
| **总计** | **{{ '%.0f'|format(budget.total) }}** |
| 人均 | {{ '%.0f'|format(budget.per_person) }} |

{% if daily_costs %}
**每日落地花销（不含机票/酒店）**

| Day | 金额 ({{ budget.currency }}) |
|-----|------|
{% for c in daily_costs -%}
| Day {{ loop.index }} | {{ '%.0f'|format(c) }} |
{% endfor %}
{% endif %}

---

## 打包清单

{% set pl = packing_list or {} %}
{% if pl.essentials or pl.clothing or pl.toiletries or pl.electronics or pl.health or pl.activities or pl.misc %}
{% if pl.essentials %}
**🛂 证件 / 必备**
{% for x in pl.essentials %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.clothing %}
**👕 衣物**
{% for x in pl.clothing %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.electronics %}
**🔌 电子设备**
{% for x in pl.electronics %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.toiletries %}
**🧴 洗漱**
{% for x in pl.toiletries %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.health %}
**💊 健康 / 药品**
{% for x in pl.health %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.activities %}
**🎒 活动专用**
{% for x in pl.activities %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% if pl.misc %}
**📦 其他**
{% for x in pl.misc %}- [ ] {{ x }}
{% endfor %}
{% endif %}
{% endif %}

---

## 当地文化与安全

{% set ct = cultural_tips or {} %}
{% if ct.dos %}
**✅ DO**
{% for x in ct.dos %}- {{ x }}
{% endfor %}
{% endif %}

{% if ct.donts %}
**❌ DON'T**
{% for x in ct.donts %}- {{ x }}
{% endfor %}
{% endif %}

{% if ct.dining %}
**🍴 用餐礼仪**
{% if ct.dining.meal_times %}- 用餐时段：{{ ct.dining.meal_times }}{% endif %}
{% if ct.dining.tipping %}- 小费：{{ ct.dining.tipping }}{% endif %}
{% if ct.dining.must_try %}- 必尝：{{ ct.dining.must_try | join('、') }}{% endif %}
{% if ct.dining.etiquette %}{% for e in ct.dining.etiquette %}- {{ e }}
{% endfor %}{% endif %}
{% endif %}

{% if ct.religious_sites %}
**🛕 宗教场所**
{% for x in ct.religious_sites %}- {{ x }}
{% endfor %}
{% endif %}

{% if ct.safety %}
**🛡 安全提示**
{% if ct.safety.common_scams %}- 常见骗局：{{ ct.safety.common_scams | join('；') }}{% endif %}
{% if ct.safety.areas_to_watch %}- 高发区域：{{ ct.safety.areas_to_watch | join('、') }}{% endif %}
{% if ct.safety.emergency_number %}- 紧急号码：{{ ct.safety.emergency_number }}{% endif %}
{% if ct.safety.transport_apps %}- 推荐出行 App：{{ ct.safety.transport_apps | join('、') }}{% endif %}
{% endif %}

{% if ct.useful_phrases %}
**💬 实用短句**

| 当地说法 | 中文 |
|----------|------|
{% for p in ct.useful_phrases -%}
| {{ p.local }} | {{ p.meaning }} |
{% endfor %}
{% endif %}

---

## 出行前准备 Timeline

{% if pre_trip_checklist %}
{% for bucket in pre_trip_checklist %}
**🗓 {{ bucket.timeline }}**
{% for task in bucket.tasks %}- [ ] {{ task }}
{% endfor %}

{% endfor %}
{% endif %}

---

## 实用 Tips

{% for tip in tips %}- {{ tip }}
{% endfor %}

{% if errors %}
## 信息暂缺
{% for err in errors %}- **{{ err.where }}**：{{ err.message }}
{% endfor %}
{% endif %}

---

> 本行程仅供参考，价格非实时；请自行核实签证、航班、入境政策等信息。
