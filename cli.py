# @owns コマンドライン入口（引数解釈と人間向け表示だけ。処理は service に委譲）
"""買い物リサーチ CLI。

  python cli.py search "kw1" "kw2" [--include 語 ...] [--exclude 語 ...] [--min-price N] [--max-price N] [--ng 語] [--pages N] [--start-page N] [--mock] [--json]
  python cli.py compare "kw1" ... [--include 語 ...] [--exclude 語 ...] [--basis 個|ml|g|m|W|...] [--desired-quantity N] [...]
  python cli.py regular <id> [--regulars PATH] [--mock] [--json]

既定は架空データ（モック。API を呼ばない）。実 API を呼ぶのは --live（または環境変数 SHOPPING_LIVE=1）を
明示した時だけ（SPEC §11: ローカルの CLI は運営者の開発・試験用。普段使いは公開Web / {BASE}/mcp）。
表示に認証情報・接続元 IP は出さない。商品固有 URL は出す。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from shopping import service  # noqa: E402
from shopping.inputs import DEFAULT_PAGES, MAX_HITS, MAX_PAGES  # noqa: E402
from shopping.pricing import OUTLIER_NOTE, PRICE_VARIES_NOTE, format_unit_price  # noqa: E402
from shopping.quantity import format_amount  # noqa: E402


def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("keywords", nargs="+", help="検索語（1〜5個）")
    p.add_argument("--min-price", type=int)
    p.add_argument("--max-price", type=int)
    p.add_argument("--ng", dest="ng_keyword", help="楽天側の除外語")
    p.add_argument("--include", nargs="+", metavar="語", help="商品名に全て含む語（例: 詰め替え 単3）")
    p.add_argument("--exclude", nargs="+", metavar="語", help="商品名に含んだら外す語")
    p.add_argument("--sort", default="standard")
    _add_paging_args(p)
    _add_common(p)


def _add_paging_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                   help=f"語ごとに取るページ数（1〜{MAX_PAGES}。既定 {DEFAULT_PAGES}＝{DEFAULT_PAGES * MAX_HITS} 件。1 ページ約 1 秒）")
    p.add_argument("--start-page", type=int, default=1, dest="start_page",
                   help=f"取り始めるページ（1〜{MAX_PAGES}。既定 1。続きは表示される『続き』のページ番号を指定）。"
                        f"楽天は {MAX_PAGES} ページ目（3000 件）までしか返さない")


def _add_common(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--mock", action="store_true", help="架空データを使う（既定。API を呼ばない）")
    g.add_argument("--live", action="store_true", help="実 API を呼ぶ（認証情報が要る。運営者の開発・試験用）")
    p.add_argument("--json", action="store_true", help="JSON で出力")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cli.py", description="楽天の商品を検索・比較する")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="候補を検索して一覧表示")
    _add_search_args(s)
    s.add_argument("--max-results", type=int, default=None, help="表示件数の上限（省略＝取得した全件）")
    c = sub.add_parser("compare", help="同じ仕様どうしで比較して最安を出す")
    _add_search_args(c)
    c.add_argument("--basis", help="比べる単位: 個 / ml / g / m / W / mAh / Wh（L・kg 等の別名も可）。省略で自動")
    c.add_argument("--desired-quantity", type=float, help="必要な量の下限（basis の単位）。同じ商品を n 個注文する組み合わせで比べる")
    c.add_argument("--desired-quantity-max", type=float, dest="desired_quantity_max",
                   help="必要な量の上限（任意。--desired-quantity とあわせて指定。注文量がこれを超える組み合わせは除く）")
    r = sub.add_parser("regular", help="定番品マスタの id で今の最安を調べる")
    r.add_argument("regular_id")
    r.add_argument("--regulars", help="定番品マスタのパス（既定 data/regulars.json）")
    _add_paging_args(r)
    _add_common(r)
    return ap


def _yen(v) -> str:
    return "不明" if v is None else f"{v:,}円"


def _ship(o: dict) -> str:
    return {"included": "送料込み", "separate": "送料別", "unknown": "送料不明"}.get(
        o["shipping_status"], "送料不明")


def _qty(o: dict) -> str:
    q = o.get("quantity") or {}
    if q.get("confidence") != "high":
        hint = f"（説明欄に「{q['caption_evidence']}」・単価には使っていない）" if q.get("caption_candidate") else ""
        return ("数量不明" if q.get("confidence") == "none" else "数量要確認") + hint
    text = f"{format_amount(q['count_total'])}{q['count_unit']}"
    if q.get("content_amount") is not None:
        text += (f" × {format_amount(q['content_amount'])}{q['content_unit']}"
                 f"（計 {format_amount(q['measure_total'])}{q['content_unit']}）")
    if q.get("source") == "caption":
        text += "【説明欄の記述から補完・確認済みではない: " + str(q.get("caption_evidence")) + "】"
    elif q.get("caption_conflict"):
        text += "【説明欄の「" + str(q.get("caption_evidence")) + "」と食い違い・要確認】"
    up = o.get("unit_price")
    return text + (f"（{o['unit_price_label']} {format_unit_price(up)}円）" if up is not None else "")


def _offer_line(o: dict) -> str:
    mark = "" if o["url_status"] == "ok" else " [URL要確認]"
    warn = f"\n      ※要確認: {OUTLIER_NOTE}" if o.get("unit_price_outlier") else ""
    if o.get("price_varies"):
        warn += (f"\n      ※要確認: {PRICE_VARIES_NOTE}"
                 f"（価格幅 {_yen(o.get('price_min'))}〜{_yen(o.get('price_max'))}）")
    return (f"{_yen(o['price'])} | {o['shop_name'] or '店舗不明'} | {_qty(o)} | "
            f"{_ship(o)}{mark}\n      {o['name']}\n      {o['url']}{warn}")


def _print_stats(stats: dict) -> None:
    print(f"取得 {stats['total_received']} 件 / 重複除去 {stats['duplicates_removed']} 件 / "
          f"候補 {stats['unique_offers']} 件 / 取得時刻 {stats['fetched_at']}"
          + (f" / 打ち切り: {stats['stopped_reason']}" if stats.get("stopped_reason") else ""))
    for k in stats["per_keyword"]:
        err = f" エラー={k['error']}" if k["error"] else ""
        span = f"（{k['start_page']}〜{k['last_page']}ページ目）" if k.get("last_page") else ""
        more = (f" / 続き: --start-page {k['next_page']}（残り約 {k['remaining']} 件）"
                if k.get("next_page") and k.get("remaining") is not None
                else f" / 続き: --start-page {k['next_page']}" if k.get("next_page") else "")
        print(f"  - {k['keyword']}: API件数 {k['api_count']} / 取得 {k['received']}{span}{err}{more}")


def _print_notes(result: dict) -> None:
    for n in result.get("notes", []):
        print(f"※ {n}")


def render_search(r: dict) -> None:
    _print_stats(r["stats"])
    print()
    for i, o in enumerate(r["offers"], 1):
        print(f"[{i}] {_offer_line(o)}")
    print()
    _print_notes(r)


def _plan_line(p: dict) -> str:
    mark = "確認済み" if p["confirmed"] else "未確認"
    return (f"{p['n']}個 = {format_amount(p['order_quantity'])} / 注文額 {_yen(p['order_total'])}"
            f"（単価 {format_unit_price(p['order_unit_price'])}円）/ {_ship(p)} / {mark} | {p['shop_name'] or '店舗不明'}\n"
            f"        {p['name']}\n        {p['url']}")


def _print_orders(sec: dict, indent: str = "", by_unit: bool = False) -> None:
    """order_plans / cheapest_order / to_check（最上位、または groups[] の中）の表示。"""
    co = sec.get("cheapest_order")
    print(f"{indent}★ 注文の最安（確認済み・" + ("注文の単価が最小" if by_unit else "注文額が最小") + "）: " + ("（該当なし）" if co is None else _plan_line(co)))
    for t in sec.get("to_check") or []:
        print(f"{indent}  ? 逆転し得る: {_plan_line(t)}")
        for cond in t["conditions"]:
            print(f"{indent}      条件: {cond['text']}")


def render_compare(r: dict) -> None:
    _print_stats(r["stats"])
    c = r["comparison"]
    print()
    print(f"比べる単位: {c['basis_label']}（{c['basis']}）")
    for g in c["groups"]:
        cu = f"［{g['count_unit']}］" if g.get("count_unit") else ""
        print(f"■ {g['basis']}{cu} で比較できる候補（{g['count']} 件・単位価格の安い順）")
        for i, o in enumerate(g["offers"], 1):
            print(f"  [{i}] {_offer_line(o)}")
    if c["unknown_count"]:
        print(f"■ 単価不明（{c['basis']} の量を読めない）{c['unknown_count']} 件")
        for i, o in enumerate(c["unknown_offers"], 1):
            print(f"  [{i}] {_offer_line(o)}")
    print()
    labels = [("cheapest_price", "商品価格が最安"), ("cheapest_unit_price", "単位価格が最安"),
              ("cheapest_total", "支払総額が最安"), ("cheapest_for_quantity", "必要数量を満たす最安")]
    multi = len(c["groups"]) > 1 and c.get("main_count_unit")
    for key, label in labels:
        if multi and key in ("cheapest_unit_price", "cheapest_for_quantity"):
            label = f"{label}［主グループ {c['main_count_unit']}］"
        o = c[key]
        print(f"★ {label}: " + ("（断定できない／該当なし）" if o is None else _offer_line(o)))
    if r.get("desired_quantity") is not None:
        print()
        rng = f"{format_amount(r['desired_quantity'])}" + (
            f"〜{format_amount(r['desired_quantity_max'])}" if r.get("desired_quantity_max") is not None else " 以上")
        print(f"希望量 {rng}（{c['basis']}）を同じ商品の n 個注文で満たす組み合わせ:")
        if len(c["groups"]) > 1:                       # 主グループの結果。他の数え語のグループは JSON の groups[] にある
            print(f"  （数え語の主グループ［{c['main_count_unit']}］。他の数え方の候補は比べていない）")
        _print_orders(c, "  ", r.get("desired_quantity_max") is not None)
    if c["caveats"]:
        print()
        print("断定できない理由・注意:")
        for cv in c["caveats"]:
            print(f"  - {cv}")
    print()
    _print_notes(r)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adapter = service.make_adapter(mock=True if args.mock else (False if args.live else None),
                                   local_tool=True)
    if args.command == "search":
        result = service.search_products(
            args.keywords, ng_keyword=args.ng_keyword, min_price=args.min_price,
            max_price=args.max_price, sort=args.sort, pages=args.pages, start_page=args.start_page,
            max_results=args.max_results, include_terms=args.include, exclude_terms=args.exclude,
            adapter=adapter)
        render = render_search
    elif args.command == "compare":
        result = service.compare_offers(
            args.keywords, args.include, args.exclude, args.desired_quantity, args.basis,
            desired_quantity_max=args.desired_quantity_max, ng_keyword=args.ng_keyword, min_price=args.min_price, max_price=args.max_price,
            sort=args.sort, pages=args.pages, start_page=args.start_page, adapter=adapter)
        render = render_compare
    else:
        result = service.find_regular_item(args.regular_id, regulars_path=args.regulars,
                                           pages=args.pages, start_page=args.start_page,
                                           adapter=adapter)
        render = render_compare
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result["ok"]:
        print(f"エラー: {result['error']['kind']} - {result['error']['message']}", file=sys.stderr)
    else:
        if args.command == "regular":
            reg = result["regular"]
            print(f"定番品: {reg['name']} (id={reg['id']}) 含む語={reg['include_terms']} "
                  f"除く語={reg['exclude_terms']} 単位={reg['basis'] or '自動'} 希望数量={reg['desired_quantity']}")
        render(result)
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
