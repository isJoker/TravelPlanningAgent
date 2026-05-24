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
| 预算总计 | {{ budget.currency }} {{ '%.0f'|format(budget.total) }}（人均 {{ '%.0f'|format(budget.per_person) }}）|
{% if review_feedback %}| 审稿建议 | {{ review_feedback }} |{% endif %}

{% if summary %}
{{ summary }}
{% endif %}

---

## 每日行程

{% for day in itinerary %}
### Day {{ day.day_index }}{% if day.date %} · {{ day.date }}{% endif %}{% if day.area %} · {{ day.area }}{% endif %}

{% if day.weather_summary %} ☀️**天气**：{{ day.weather_summary }}{% endif %}

| 时段 | 安排 | 类型 | 备注 |
|------|------|------|------|
{% for slot in day.slots -%}
| {{ slot.slot }} | {{ slot.poi }} | {{ slot.type }} | {{ slot.note or "—" }} |
{% endfor %}

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
