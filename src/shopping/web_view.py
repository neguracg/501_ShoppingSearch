# @owns 公開Webの画面（HTML テンプレートと表示用の整形）。業務判断・通信は持たない
"""外部 CSS/JS/CDN を使わない 1 カラムの画面。リンクは楽天の商品URLとクレジットだけ。"""
from __future__ import annotations

from jinja2 import DictLoader, Environment

from .adapters.rakuten import is_item_url
from .credit import CREDIT_HTML, FRESHNESS_TEXT, OPERATOR_TEXT
from .inputs import MAX_KEYWORDS, WIDTH_TEXT
from .pricing import OUTLIER_NOTE, PRICE_VARIES_NOTE, format_unit_price
from .quantity import basis_choices, format_amount

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#5a5a5a;--line:#d9d9d9;--card:#f6f6f6;--accent:#b00020;--warn:#7a4b00;--warnbg:#fff4e0}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--muted:#aaa;--line:#3a3a3a;--card:#222;--accent:#ff8a9a;--warn:#ffd48a;--warnbg:#3a2c10}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Hiragino Sans","Yu Gothic UI",sans-serif}
main,footer{max-width:42rem;margin:0 auto;padding:0 16px}
h1{font-size:1.3rem;margin:1rem 0 .25rem}h2{font-size:1.05rem;margin:1.5rem 0 .5rem}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 1rem}
label{display:block;font-weight:600;margin:.8rem 0 .2rem}
textarea,input{width:100%;font:inherit;padding:.5rem;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.row{display:flex;gap:8px}.row>div{flex:1}
.hint{color:var(--muted);font-size:.85rem}
.btns{display:flex;gap:8px;margin:1rem 0}
button{flex:1;font:inherit;padding:.7rem;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.card{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:10px 12px;margin:.6rem 0}
.card .name{font-weight:600;word-break:break-word}
.card .meta{color:var(--muted);font-size:.88rem}
.price{font-size:1.1rem;font-weight:700}
.warn{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 12px;margin:.6rem 0;font-size:.92rem}
.warn ul,.notes ul{margin:.2rem 0;padding-left:1.2rem}
.notes{color:var(--muted);font-size:.88rem}
.best{border-left:4px solid var(--accent)}
details summary{cursor:pointer;font-weight:600;margin:.5rem 0}
a{color:var(--accent)}
footer{border-top:1px solid var(--line);margin-top:2rem;padding-top:1rem;padding-bottom:2rem;color:var(--muted);font-size:.85rem}
footer p{margin:.4rem 0}
"""

_TEMPLATES = {
    "base.html": """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}買い物リサーチ{% endblock %}</title>
<style>{{ css|safe }}</style></head>
<body><main>
<h1><a href="{{ base }}/" style="text-decoration:none;color:inherit">買い物リサーチ</a></h1>
<p class="sub">楽天市場の商品を検索し、個数・内容量・単価・送料に注意して比べます。購入操作はしません。</p>
{% block body %}{% endblock %}
</main>
<footer>
<p>{{ credit|safe }}</p>
<p>{{ operator }}</p>
<p>{{ freshness }}</p>
</footer></body></html>""",

    "index.html": """{% extends "base.html" %}
{% block body %}
<form method="get" action="{{ base }}/search">
<label for="q">探したいもの（1〜5語）</label>
<textarea id="q" name="q" rows="3" required placeholder="例: 洗濯洗剤 詰め替え 900g">{{ form.q }}</textarea>
<div class="hint">改行またはカンマで区切ると、語ごとに検索して統合します（{{ max_terms }}語まで・1語は{{ width_text }}まで）。</div>
<label for="include">含む語（任意。商品名に全部含むものだけ残す）</label>
<input id="include" name="include" value="{{ form.include }}" placeholder="例: 詰め替え 濃縮">
<label for="exclude">除く語（任意。商品名に含むものは外す）</label>
<input id="exclude" name="exclude" value="{{ form.exclude }}" placeholder="例: 本体 訳あり">
<div class="hint">語は空白かカンマで区切ります（{{ max_terms }}語まで・1語は{{ width_text }}まで。楽天側の除外語も同じ）。仕様の違い（濃縮・型番・色など）は自動では判定しないので、ここで絞るか結果の商品名で確認してください。</div>
<label for="ng">楽天側の除外語（任意）</label>
<input id="ng" name="ng" value="{{ form.ng }}">
<label for="basis">比べる単位</label>
<select id="basis" name="basis">
<option value="">自動（商品名から読み取れる量で決める）</option>
{% for b in bases %}<option value="{{ b }}"{% if form.basis == b %} selected{% endif %}>{{ b }}あたり</option>
{% endfor %}</select>
<div class="hint">比べる単位は「比較する」でだけ使います（「一覧で見る」では使いません）。含む語・除く語は、どちらでも使います。</div>
<div class="row">
<div><label for="min_price">価格の下限（円）</label><input id="min_price" name="min_price" inputmode="numeric" value="{{ form.min_price }}"></div>
<div><label for="max_price">価格の上限（円）</label><input id="max_price" name="max_price" inputmode="numeric" value="{{ form.max_price }}"></div>
</div>
<div class="btns">
<button type="submit" formaction="{{ base }}/search" formmethod="get">一覧で見る</button>
<button type="submit" class="primary" formaction="{{ base }}/compare" formmethod="get">比較する</button>
</div>
</form>
<p class="hint">「比較する」は商品名から個数と内容量（例: 900g×6、2L×9本、100W×2）を読み取り、選んだ単位あたりの単価などを出します。読み取れない商品は順位付けから外し、その理由を表示します。</p>
{% endblock %}""",

    "message.html": """{% extends "base.html" %}
{% block title %}{{ heading }} - 買い物リサーチ{% endblock %}
{% block body %}
<h2>{{ heading }}</h2>
{% for p in paragraphs %}<p>{{ p }}</p>{% endfor %}
<p><a href="{{ base }}/">検索画面に戻る</a></p>
{% endblock %}""",

    "results.html": """{% extends "base.html" %}
{% block title %}{{ '比較' if mode == 'compare' else '検索' }}結果 - 買い物リサーチ{% endblock %}
{% macro offer_card(o, best=False) %}
<div class="card{% if best %} best{% endif %}">
<div class="name">{{ o.name }}</div>
<div><span class="price">{{ yen(o.price) }}</span>
 <span class="meta">／ {{ ship(o) }}{% if o.total_price is not none and o.shipping_status == 'separate' %}（総額 {{ yen(o.total_price) }}）{% endif %}</span></div>
<div class="meta">{{ o.shop_name or '店舗不明' }} ／ {{ qty(o) }}</div>
{% if o.review_count %}<div class="meta">レビュー {{ o.review_average }}（{{ o.review_count }}件）</div>{% endif %}
{% if o.unit_price_outlier %}<div class="warn">要確認: {{ outlier_note }}</div>{% endif %}
{% if o.price_varies %}<div class="warn">要確認: {{ price_varies_note }}（価格幅 {{ yen(o.price_min) }}〜{{ yen(o.price_max) }}）</div>{% endif %}
{% if o.shipping_title_conflict %}<div class="warn">{{ o.shipping_title_conflict }}</div>{% endif %}
<div class="meta">取得 {{ o.fetched_at or '不明' }}</div>
{% if safe_url(o) %}<div><a href="{{ o.url }}" target="_blank" rel="noopener">楽天市場の商品ページを開く</a></div>
{% else %}<div class="meta">商品URLの形式を確認できなかったためリンクを出していません。</div>{% endif %}
</div>
{% endmacro %}
{% block body %}
<p class="sub">検索語: {{ keywords|join(' / ') }}{% if mock %}（架空のモックデータ）{% endif %}</p>
{% if mode == 'compare' %}
{% if caveats %}<div class="warn"><strong>断定できない理由・注意</strong><ul>{% for c in caveats %}<li>{{ c }}</li>{% endfor %}</ul></div>{% endif %}
<h2>最安の候補</h2>
{% for label, o in cheapest %}
<h3 style="font-size:.95rem;margin:.8rem 0 0">{{ label }}</h3>
{% if o %}{{ offer_card(o, True) }}{% else %}<div class="card meta">断定できない、または該当なし（上の理由を確認してください）</div>{% endif %}
{% endfor %}
<h2>{{ basis_label }}の比較（単位価格の安い順）</h2>
{% for g in groups %}
<details {% if loop.first %}open{% endif %}><summary>{{ g.title }}（{{ g.count }}件）</summary>
{% for o in g.offers %}{{ offer_card(o) }}{% endfor %}
{% if g.count > g.offers|length %}<p class="meta">ほか {{ g.count - g.offers|length }} 件は省略しています。</p>{% endif %}
</details>
{% else %}<p>単位価格を出せる候補がありませんでした。</p>{% endfor %}
{% if unknown_count %}<details><summary>単価不明（量を読み取れない）{{ unknown_count }}件</summary>
{% for o in unknown_offers %}{{ offer_card(o) }}{% endfor %}
{% if unknown_count > unknown_offers|length %}<p class="meta">ほか {{ unknown_count - unknown_offers|length }} 件は省略しています。</p>{% endif %}
</details>{% endif %}
{% else %}
<h2>候補 {{ offers|length }} 件</h2>
{% for o in offers %}{{ offer_card(o) }}{% else %}<p>条件に合う商品が見つかりませんでした。</p>{% endfor %}
{% endif %}
<div class="notes"><h2>注意・出典</h2><ul>{% for n in notes %}<li>{{ n }}</li>{% endfor %}</ul></div>
<p><a href="{{ base }}/">条件を変えて検索する</a></p>
{% endblock %}""",
}

BASIS_UNUSED_NOTE = "比べる単位は一覧では使っていません。単位あたりの単価で比べるには「比較する」を使ってください。"

_env = Environment(loader=DictLoader(_TEMPLATES), autoescape=True)


def _yen(v) -> str:
    return "価格不明" if v is None else f"{v:,}円"


def _ship(o: dict) -> str:
    return {"included": "送料込み", "separate": "送料別", "unknown": "送料不明"}.get(
        o.get("shipping_status"), "送料不明")


def _qty(o: dict) -> str:
    q = o.get("quantity") or {}
    if q.get("confidence") != "high":
        return "数量不明" if q.get("confidence") == "none" else "数量要確認"
    text = f"{format_amount(q['count_total'])}{q['count_unit']}"
    if q.get("content_amount") is not None:
        text += (f" × {format_amount(q['content_amount'])}{q['content_unit']}"
                 f"（計 {format_amount(q['measure_total'])}{q['content_unit']}）")
    up = o.get("unit_price")
    return text + (f"／{o['unit_price_label']} {format_unit_price(up)}円" if up is not None else "")


def _safe_url(o: dict) -> bool:
    return o.get("url_status") == "ok" and is_item_url(o.get("url"))


def render(name: str, base: str, **ctx) -> str:
    return _env.get_template(name).render(
        base=base, css=_CSS, credit=CREDIT_HTML, operator=OPERATOR_TEXT, freshness=FRESHNESS_TEXT,
        outlier_note=OUTLIER_NOTE, price_varies_note=PRICE_VARIES_NOTE, yen=_yen, ship=_ship, qty=_qty, safe_url=_safe_url, bases=basis_choices(),
        max_terms=MAX_KEYWORDS, width_text=WIDTH_TEXT, **ctx)


_DIMENSION_LABELS = {"count": "個数", "volume": "容量", "mass": "重さ", "length": "長さ",
                     "power": "電力", "charge": "電池容量", "energy": "電力量"}


def group_title(g: dict, basis_label: str) -> str:
    unit = f"［{g['count_unit']}］" if g.get("count_unit") else ""     # 数え語ごとのグループ（WP14 W3）
    return f"{basis_label}{unit}で比較（{_DIMENSION_LABELS.get(g.get('dimension'), g.get('dimension'))}）"
