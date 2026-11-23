# -*- coding: utf-8 -*-
"""Motor de RFV, perfil de consumo e recomendações do SalesPilot.

Tudo aqui é determinístico e roda localmente (sem serviços externos): estatística
simples sobre o histórico de pedidos do restaurante. O resultado alimenta a
segmentação, os alertas de red flag, as réguas automáticas e o cardápio digital.
"""
import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ACTIVE_STATES = ("confirmed", "preparing", "delivering", "delivered")
TZ = pytz.timezone("America/Sao_Paulo")

SEGMENT_META = {
    "champions": ("Campeões", "#1B998B", "Melhores clientes: compram muito e recentemente. Recompense e peça indicação."),
    "loyal": ("Clientes fiéis", "#2D6A4F", "Compram com frequência. Ofereça combos e programa de fidelidade."),
    "potential_loyal": ("Potenciais fiéis", "#52B788", "Recentes e já repetiram. Incentive o 3º/4º pedido."),
    "new": ("Novos clientes", "#4895EF", "Primeira compra recente. Boas-vindas e cupom para a 2ª compra."),
    "promising": ("Promissores", "#4CC9F0", "Compraram há pouco, ainda com pouca frequência."),
    "need_attention": ("Precisam de atenção", "#F4A261", "Frequência média, mas estão esfriando. Lembrete do favorito."),
    "about_to_sleep": ("Prestes a dormir", "#E9C46A", "Sumindo. Oferta de reativação leve."),
    "at_risk": ("Em risco", "#E76F51", "Eram bons clientes e pararam. Oferta forte de reativação."),
    "cant_lose": ("Não pode perder", "#D62828", "Eram campeões e sumiram. Contato pessoal do dono."),
    "hibernating": ("Hibernando", "#8D99AE", "Última compra há muito tempo e baixa frequência."),
    "lost": ("Perdidos", "#ADB5BD", "Sem compras há muito tempo. Campanha de baixo custo ou descarte."),
    "none": ("Sem compras", "#DEE2E6", "Cadastro sem pedidos."),
}

WEEKDAY_NAMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
WEEKDAY_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def brl(value):
    """Formata em reais no padrão brasileiro (R$ 1.234,56)."""
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def local_to_utc(local_dt):
    """datetime naive em horário de São Paulo -> datetime naive em UTC (formato do banco)."""
    return TZ.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)


def local_month_start(ref=None):
    ref = ref or datetime.now(TZ)
    return local_to_utc(datetime(ref.year, ref.month, 1))


def _median(values):
    return statistics.median(values) if values else 0.0


def _percentiles(values):
    """Devolve os limiares p20, p40, p60, p80 de uma lista."""
    if not values:
        return [0, 0, 0, 0]
    vals = sorted(values)
    n = len(vals)
    out = []
    for p in (0.2, 0.4, 0.6, 0.8):
        idx = min(int(round(p * (n - 1))), n - 1)
        out.append(vals[idx])
    return out


def _score_from_thresholds(value, thresholds):
    score = 1
    for t in thresholds:
        if value > t:
            score += 1
    return min(score, 5)


def recency_score(days):
    if days is None:
        return 0
    if days <= 7:
        return 5
    if days <= 14:
        return 4
    if days <= 30:
        return 3
    if days <= 60:
        return 2
    return 1


def frequency_score(freq, window_days):
    scale = max(window_days, 30) / 180.0
    if freq <= 0:
        return 1
    if freq <= 1 * scale + 0.01:
        return 1
    if freq <= 2 * scale + 0.01:
        return 2
    if freq <= 4 * scale + 0.01:
        return 3
    if freq <= 8 * scale + 0.01:
        return 4
    return 5


def segment_for(r, f, v, freq_window, total_orders):
    if total_orders == 0:
        return "none"
    fv = int((f + v) / 2.0 + 0.5)  # arredondamento "meio para cima"
    if total_orders == 1:
        return {5: "new", 4: "new", 3: "promising", 2: "about_to_sleep"}.get(r, "hibernating")
    if r >= 4 and fv >= 4:
        return "champions"
    if r <= 1 and fv >= 4:
        return "cant_lose"
    if r >= 2 and fv >= 3:
        return "loyal"
    if r >= 4 and fv <= 1 and total_orders == 1:
        return "new"
    if r >= 4 and fv == 2:
        return "potential_loyal"
    if r in (2, 3) and fv == 2:
        return "need_attention"
    if r <= 1 and fv >= 2:
        return "at_risk"
    if r >= 3 and fv <= 1:
        return "promising"
    if r == 2 and fv <= 1:
        return "about_to_sleep"
    if r == 1 and freq_window >= 1:
        return "hibernating"
    return "lost"


class SpRfvEngine(models.AbstractModel):
    _name = "sp.rfv.engine"
    _description = "Motor RFV e recomendações"

    # ------------------------------------------------------------------
    # Coleta
    # ------------------------------------------------------------------
    def _fetch_orders(self, restaurant, partner_ids=None):
        """Lista de dicts {partner_id, date, total, channel, products:[(product_id, qty)]}."""
        domain = [("restaurant_id", "=", restaurant.id), ("state", "in", ACTIVE_STATES)]
        if partner_ids is not None:
            domain.append(("partner_id", "in", list(partner_ids)))
        orders = self.env["sp.order"].search(domain, order="date_order asc")
        lines_by_order = defaultdict(list)
        for line in self.env["sp.order.line"].search([("order_id", "in", orders.ids)]):
            lines_by_order[line.order_id.id].append((line.product_id.id, line.qty, line.product_tmpl_id.sp_kind))
        out = defaultdict(list)
        for o in orders:
            out[o.partner_id.id].append({
                "date": o.date_order,
                "total": o.amount_total,
                "channel": o.channel,
                "products": lines_by_order.get(o.id, []),
            })
        return out

    def _partner_stats(self, orders, now, window_days):
        """Estatísticas brutas de um cliente a partir dos pedidos (ordenados por data)."""
        if not orders:
            return None
        window_start = now - timedelta(days=window_days)
        dates = [o["date"] for o in orders]
        totals = [o["total"] for o in orders]
        in_window = [o for o in orders if o["date"] >= window_start]
        gaps = [(dates[i] - dates[i - 1]).total_seconds() / 86400.0 for i in range(1, len(dates))]
        gaps = [g for g in gaps if g >= 0.25]  # ignora pedidos duplicados no mesmo momento
        local_dates = [d.replace(tzinfo=pytz.utc).astimezone(TZ) for d in dates]
        weekday_counter = Counter(d.weekday() for d in local_dates)
        hour_counter = Counter(d.hour for d in local_dates)
        # Favorito: o prato principal/combo mais recorrente (bebidas e acompanhamentos só como fallback)
        product_counter = Counter()
        main_counter = Counter()
        for o in orders:
            for pid, qty, kind in o["products"]:
                product_counter[pid] += 1
                if kind in ("main", "combo"):
                    main_counter[pid] += 1
        fav_counter = main_counter or product_counter
        channel_counter = Counter(o["channel"] for o in orders)

        n = len(orders)
        fav_weekday = fav_hour = None
        if n >= 3:
            wd, wd_cnt = weekday_counter.most_common(1)[0]
            if wd_cnt / n >= 0.4:
                fav_weekday = wd
            hr, hr_cnt = hour_counter.most_common(1)[0]
            if hr_cnt / n >= 0.3:
                fav_hour = hr
        typical = _median(gaps[-8:]) if len(gaps) >= 2 else 0.0
        return {
            "first": dates[0],
            "last": dates[-1],
            "recency": max((now - dates[-1]).days, 0),
            "frequency": len(in_window),
            "monetary": sum(o["total"] for o in in_window),
            "total_orders": n,
            "ltv": sum(totals),
            "avg_ticket": sum(totals) / n,
            "typical_interval": typical,
            "fav_weekday": fav_weekday,
            "fav_hour": fav_hour,
            "fav_product": fav_counter.most_common(1)[0][0] if fav_counter else False,
            "fav_channel": channel_counter.most_common(1)[0][0] if channel_counter else False,
        }

    # ------------------------------------------------------------------
    # Recalculo
    # ------------------------------------------------------------------
    @api.model
    def recompute(self, restaurants=None):
        restaurants = restaurants or self.env["sp.restaurant"].search([])
        for restaurant in restaurants:
            self._recompute_restaurant(restaurant)
        return True

    def _recompute_restaurant(self, restaurant, partners=None):
        now = fields.Datetime.now()
        window = restaurant.rfv_window_days or 180
        full = partners is None
        Partner = self.env["res.partner"].with_context(active_test=False)
        if full:
            partners = Partner.search([("sp_restaurant_id", "=", restaurant.id), ("sp_is_customer", "=", True)])
            orders_by_partner = self._fetch_orders(restaurant)
        else:
            orders_by_partner = self._fetch_orders(restaurant, partners.ids)

        stats = {p.id: self._partner_stats(orders_by_partner.get(p.id, []), now, window) for p in partners}

        # Limiares de Frequência e Valor: quintis da base do restaurante (recalculados só no cálculo completo).
        # Com base pequena (< 20 clientes ativos) usa a escala fixa.
        if full:
            active = [s for s in stats.values() if s and s["frequency"] > 0]
            thresholds = {
                "value": _percentiles([s["monetary"] for s in active]),
                "frequency": _percentiles([s["frequency"] for s in active]) if len(active) >= 20 else None,
            }
            restaurant.sudo().write({"rfv_value_thresholds": thresholds, "last_rfv_run": now})
        else:
            thresholds = restaurant.rfv_value_thresholds or {}
            if isinstance(thresholds, list):  # compat
                thresholds = {"value": thresholds, "frequency": None}
        value_thr = thresholds.get("value") or [0, 0, 0, 0]
        freq_thr = thresholds.get("frequency")

        product_names = {}
        for p in partners.sudo():
            s = stats[p.id]
            if not s:
                p.write({
                    "sp_segment_prev": p.sp_segment if p.sp_segment not in (False, "none") else False,
                    "sp_segment": "none", "sp_r_score": 0, "sp_f_score": 0,
                    "sp_v_score": 0, "sp_rfv_score": "---", "sp_churn_risk": "none", "sp_recurrence_ratio": 0,
                    "sp_total_orders": 0, "sp_frequency": 0, "sp_monetary": 0, "sp_ltv": 0, "sp_avg_ticket": 0,
                    "sp_recency_days": 0, "sp_first_order_date": False, "sp_last_order_date": False,
                    "sp_typical_interval": 0, "sp_next_order_expected": False, "sp_favorite_product_id": False,
                    "sp_favorite_weekday": False, "sp_favorite_hour": 0, "sp_favorite_channel": False,
                    "sp_profile_summary": "Cadastro sem pedidos registrados.",
                })
                continue
            r = recency_score(s["recency"])
            if freq_thr and s["frequency"] > 0:
                f = _score_from_thresholds(s["frequency"], freq_thr)
            else:
                f = frequency_score(s["frequency"], window)
            v = _score_from_thresholds(s["monetary"], value_thr) if s["monetary"] > 0 else 1
            segment = segment_for(r, f, v, s["frequency"], s["total_orders"])

            ratio = 0.0
            risk = "none"
            if s["typical_interval"] and s["total_orders"] >= 3:
                ratio = s["recency"] / s["typical_interval"]
                if s["recency"] <= 120:
                    if ratio >= (restaurant.churn_critical_factor or 2.5):
                        risk = "critical"
                    elif ratio >= (restaurant.churn_warning_factor or 1.5):
                        risk = "warning"
            next_expected = False
            if s["typical_interval"]:
                last_local = s["last"].replace(tzinfo=pytz.utc).astimezone(TZ)
                next_expected = (last_local + timedelta(days=s["typical_interval"])).date()

            fav_name = ""
            if s["fav_product"]:
                if s["fav_product"] not in product_names:
                    product_names[s["fav_product"]] = self.env["product.product"].browse(s["fav_product"]).display_name
                fav_name = product_names[s["fav_product"]]

            p.write({
                "sp_first_order_date": s["first"], "sp_last_order_date": s["last"],
                "sp_recency_days": s["recency"], "sp_frequency": s["frequency"], "sp_monetary": s["monetary"],
                "sp_total_orders": s["total_orders"], "sp_ltv": s["ltv"], "sp_avg_ticket": s["avg_ticket"],
                "sp_r_score": r, "sp_f_score": f, "sp_v_score": v, "sp_rfv_score": f"{r}{f}{v}",
                "sp_segment_prev": (p.sp_segment if p.sp_segment != segment else p.sp_segment_prev)
                if p.sp_segment not in (False, "none") else False,
                "sp_segment_changed_date": fields.Date.context_today(p) if p.sp_segment != segment else p.sp_segment_changed_date,
                "sp_segment": segment,
                "sp_typical_interval": s["typical_interval"], "sp_next_order_expected": next_expected,
                "sp_favorite_product_id": s["fav_product"],
                "sp_favorite_weekday": str(s["fav_weekday"]) if s["fav_weekday"] is not None else False,
                "sp_favorite_hour": s["fav_hour"] if s["fav_hour"] is not None else 0,
                "sp_favorite_channel": s["fav_channel"],
                "sp_churn_risk": risk, "sp_recurrence_ratio": ratio,
                "sp_profile_summary": self._profile_text(s, segment, risk, fav_name),
            })

        if full:
            self._update_product_stats(restaurant)
        return True

    def _profile_text(self, s, segment, risk, fav_name):
        parts = []
        label = SEGMENT_META.get(segment, ("", "", ""))[0]
        parts.append(f"Segmento {label} (RFV). {s['total_orders']} pedidos, LTV {brl(s['ltv'])}, "
                     f"ticket médio {brl(s['avg_ticket'])}.")
        if s["typical_interval"]:
            parts.append(f"Pede em média a cada {s['typical_interval']:.0f} dias.")
        habit = []
        if s["fav_weekday"] is not None:
            habit.append(f"geralmente na {WEEKDAY_NAMES[s['fav_weekday']]}")
        if s["fav_hour"] is not None:
            habit.append(f"por volta das {s['fav_hour']}h")
        if habit:
            parts.append("Compra " + " ".join(habit) + ".")
        if fav_name:
            parts.append(f"Favorito: {fav_name}.")
        if risk == "warning":
            parts.append(f"⚠ Atenção: está há {s['recency']} dias sem pedir, acima do ritmo habitual.")
        elif risk == "critical":
            parts.append(f"🚩 Red flag: {s['recency']} dias sem pedir — provavelmente comprando de outro lugar.")
        return " ".join(parts)

    def _update_product_stats(self, restaurant):
        since = fields.Datetime.now() - timedelta(days=90)
        self.env.cr.execute("""
            SELECT l.product_tmpl_id, SUM(l.qty), SUM(l.price_subtotal)
              FROM sp_order_line l JOIN sp_order o ON o.id = l.order_id
             WHERE o.restaurant_id = %s AND o.state IN %s AND o.date_order >= %s
             GROUP BY l.product_tmpl_id
        """, (restaurant.id, ACTIVE_STATES, since))
        rows = {r[0]: (r[1], r[2]) for r in self.env.cr.fetchall()}
        templates = self.env["product.template"].with_context(active_test=False).search(
            [("sp_restaurant_id", "=", restaurant.id)])
        for t in templates.sudo():
            qty, rev = rows.get(t.id, (0, 0.0))
            t.write({"sp_sold_qty_90d": int(qty), "sp_revenue_90d": rev})

    @api.model
    def recompute_partners(self, partners):
        partners = partners.filtered(lambda p: p.sp_restaurant_id)
        for restaurant, group in partners.grouped("sp_restaurant_id").items():
            self._recompute_restaurant(restaurant, group)
        return True

    @api.model
    def cron_recompute_all(self):
        restaurants = self.env["sp.restaurant"].search([])
        self.recompute(restaurants)
        self.env["sp.insight"].generate_for(restaurants)
        self.env["sp.alert"].scan(restaurants)
        return True

    # ------------------------------------------------------------------
    # Recomendações (cardápio digital / campanhas)
    # ------------------------------------------------------------------
    @api.model
    def cooccurrence(self, restaurant, days=120):
        """Matriz {produto_tmpl_id: Counter({outro_tmpl_id: pedidos_juntos})} + contagem por produto."""
        since = fields.Datetime.now() - timedelta(days=days)
        self.env.cr.execute("""
            SELECT o.id, l.product_tmpl_id
              FROM sp_order_line l JOIN sp_order o ON o.id = l.order_id
             WHERE o.restaurant_id = %s AND o.state IN %s AND o.date_order >= %s
        """, (restaurant.id, ACTIVE_STATES, since))
        baskets = defaultdict(set)
        for order_id, tmpl in self.env.cr.fetchall():
            baskets[order_id].add(tmpl)
        pair = defaultdict(Counter)
        single = Counter()
        for items in baskets.values():
            for a in items:
                single[a] += 1
                for b in items:
                    if a != b:
                        pair[a][b] += 1
        return pair, single, len(baskets)

    @api.model
    def cross_sell(self, restaurant, product_tmpl_ids, limit=3):
        """Sugere itens que costumam sair junto com os produtos do carrinho."""
        product_tmpl_ids = [int(x) for x in product_tmpl_ids if x]
        pair, single, _n = self.cooccurrence(restaurant)
        scores = Counter()
        for pid in product_tmpl_ids:
            base = single.get(pid) or 1
            for other, cnt in pair.get(pid, {}).items():
                if other in product_tmpl_ids:
                    continue
                scores[other] += cnt / base  # "confiança": % de pedidos de X que levaram Y
        Template = self.env["product.template"]
        suggestions = []
        for tmpl_id, score in scores.most_common(limit * 2):
            tmpl = Template.browse(tmpl_id)
            if tmpl.exists() and tmpl.sp_available and tmpl.active:
                suggestions.append({"product": tmpl, "confidence": min(score, 1.0),
                                    "reason": f"{int(min(score, 1.0) * 100)}% de quem pede isso também leva"})
            if len(suggestions) >= limit:
                break
        # Sugestões manuais do cardápio ("combina com")
        if len(suggestions) < limit:
            for tmpl in Template.browse(product_tmpl_ids):
                pair_prod = tmpl.sp_pair_product_id
                if pair_prod and pair_prod.id not in product_tmpl_ids and \
                        pair_prod.id not in [s["product"].id for s in suggestions] and pair_prod.sp_available:
                    suggestions.append({"product": pair_prod, "confidence": 0.5, "reason": "Combinação sugerida pela casa"})
                if len(suggestions) >= limit:
                    break
        # Upgrade: sugerir versão "família/2L" quando há 2+ principais e nenhuma bebida grande
        return suggestions[:limit]

    @api.model
    def recommend_for_partner(self, partner, limit=3):
        """Recomendações personalizadas com base no histórico do cliente."""
        restaurant = partner.sp_restaurant_id
        recs = []
        Template = self.env["product.template"]
        fav = partner.sp_favorite_product_id.product_tmpl_id
        if fav and fav.sp_available:
            recs.append({"product": fav, "reason": "Seu favorito", "kind": "favorite"})
        # Itens que acompanham o favorito
        if fav:
            for s in self.cross_sell(restaurant, [fav.id], limit=2):
                if s["product"].id not in [r["product"].id for r in recs]:
                    recs.append({"product": s["product"], "reason": s["reason"], "kind": "pair"})
        # Mais vendidos do restaurante para completar
        if len(recs) < limit:
            best = Template.search([("sp_restaurant_id", "=", restaurant.id), ("sp_available", "=", True),
                                    ("id", "not in", [r["product"].id for r in recs])],
                                   order="sp_sold_qty_90d desc, sp_highlight desc", limit=limit)
            for t in best:
                recs.append({"product": t, "reason": "Mais pedido da casa", "kind": "best"})
        return recs[:limit]

    @api.model
    def greeting_for_partner(self, partner):
        """Texto do pop-up personalizado do cardápio digital."""
        first = (partner.name or "").split(" ")[0]
        now_local = datetime.now(TZ)
        fav = partner.sp_favorite_product_id
        if partner.sp_segment == "none" or not partner.sp_total_orders:
            return f"Oi {first}! Bem-vindo(a). Separamos os mais pedidos da casa para você."
        if partner.sp_favorite_weekday and int(partner.sp_favorite_weekday) == now_local.weekday() and fav:
            return f"Oi {first}! {WEEKDAY_NAMES[now_local.weekday()].capitalize()} é dia de {fav.name}, né? Já deixamos separado 😉"
        if partner.sp_churn_risk in ("warning", "critical"):
            return f"Que saudade, {first}! Faz {partner.sp_recency_days} dias que você não pede. Preparamos uma sugestão especial."
        if partner.sp_segment == "champions":
            return f"Oi {first}! Você é um dos nossos clientes VIP 🏆. Seu pedido de sempre está a um toque."
        if fav:
            return f"Oi {first}! Repetir o {fav.name} de sempre ou experimentar algo novo?"
        return f"Oi {first}! Bom te ver de novo. Olha o que separamos para você."

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @api.model
    def dashboard_payload(self, restaurant):
        cr = self.env.cr
        now = fields.Datetime.now()
        d30 = now - timedelta(days=30)
        d60 = now - timedelta(days=60)
        d90 = now - timedelta(days=90)
        month_start = local_month_start()
        rid = restaurant.id

        def q(sql, params):
            cr.execute(sql, params)
            return cr.fetchall()

        base = "FROM sp_order o WHERE o.restaurant_id = %s AND o.state IN %s"
        rev30, orders30, ticket30, cust30 = q(f"SELECT COALESCE(SUM(amount_total),0), COUNT(*), COALESCE(AVG(amount_total),0), COUNT(DISTINCT partner_id) {base} AND date_order >= %s",
                                               (rid, ACTIVE_STATES, d30))[0]
        rev_prev, orders_prev, _tp, cust_prev = q(f"SELECT COALESCE(SUM(amount_total),0), COUNT(*), COALESCE(AVG(amount_total),0), COUNT(DISTINCT partner_id) {base} AND date_order >= %s AND date_order < %s",
                                                   (rid, ACTIVE_STATES, d60, d30))[0]
        retained = q(f"""SELECT COUNT(DISTINCT a.partner_id) FROM sp_order a
                         WHERE a.restaurant_id=%s AND a.state IN %s AND a.date_order >= %s
                           AND a.partner_id IN (SELECT b.partner_id FROM sp_order b WHERE b.restaurant_id=%s
                                                 AND b.state IN %s AND b.date_order >= %s AND b.date_order < %s)""",
                     (rid, ACTIVE_STATES, d30, rid, ACTIVE_STATES, d60, d30))[0][0]
        retention = (retained / cust_prev * 100.0) if cust_prev else 0.0
        tracked_month, attributed_month, recom_month = q(f"""SELECT
                COALESCE(SUM(CASE WHEN tracked THEN amount_total END),0),
                COALESCE(SUM(CASE WHEN attributed THEN amount_total END),0),
                COALESCE(SUM(CASE WHEN recommendation_accepted THEN amount_total END),0)
                {base} AND date_order >= %s""", (rid, ACTIVE_STATES, month_start))[0]
        rev_month = q(f"SELECT COALESCE(SUM(amount_total),0) {base} AND date_order >= %s", (rid, ACTIVE_STATES, month_start))[0][0]

        Partner = self.env["res.partner"]
        pdom = [("sp_restaurant_id", "=", rid), ("sp_is_customer", "=", True)]
        total_customers = Partner.search_count(pdom)
        new30 = Partner.search_count(pdom + [("sp_first_order_date", ">=", d30)])
        at_risk = Partner.search_count(pdom + [("sp_churn_risk", "in", ("warning", "critical"))])
        critical = Partner.search_count(pdom + [("sp_churn_risk", "=", "critical")])
        opt_in = Partner.search_count(pdom + [("sp_opt_in", "=", True)])

        # Segmentos
        seg_rows = Partner.read_group(pdom, ["sp_ltv:sum", "sp_monetary:sum"], ["sp_segment"])
        seg_map = {r["sp_segment"]: r for r in seg_rows}
        segments = []
        for code, (label, color, tip) in SEGMENT_META.items():
            row = seg_map.get(code)
            segments.append({"code": code, "label": label, "color": color, "tip": tip,
                             "count": row["sp_segment_count"] if row else 0,
                             "revenue": row["sp_monetary"] if row else 0.0})

        # Matriz R x FV
        matrix = [[0] * 5 for _ in range(5)]
        for p in Partner.search_read(pdom + [("sp_r_score", ">", 0)], ["sp_r_score", "sp_f_score", "sp_v_score"]):
            fv = int(round((p["sp_f_score"] + p["sp_v_score"]) / 2.0))
            fv = min(max(fv, 1), 5)
            matrix[5 - p["sp_r_score"]][fv - 1] += 1

        weeks = q(f"""SELECT date_trunc('week', date_order AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo')::date AS wk,
                             SUM(amount_total), COUNT(*)
                      {base} AND date_order >= %s GROUP BY wk ORDER BY wk""", (rid, ACTIVE_STATES, now - timedelta(weeks=12)))
        heat_rows = q(f"SELECT weekday, hour, COUNT(*) {base} AND date_order >= %s GROUP BY weekday, hour", (rid, ACTIVE_STATES, d90))
        heat = [[0] * 24 for _ in range(7)]
        for wd, hr, cnt in heat_rows:
            heat[wd][hr] = cnt
        channels = q(f"SELECT channel, COUNT(*), SUM(amount_total) {base} AND date_order >= %s GROUP BY channel", (rid, ACTIVE_STATES, d90))
        channel_labels = dict(self.env["sp.order"]._fields["channel"].selection)
        top_products = self.env["product.template"].search_read(
            [("sp_restaurant_id", "=", rid)], ["name", "sp_sold_qty_90d", "sp_revenue_90d"],
            order="sp_sold_qty_90d desc", limit=8)

        campaigns = self.env["sp.campaign"].search([("restaurant_id", "=", rid), ("state", "in", ("sent", "scheduled", "sending", "done"))],
                                                   order="date_scheduled desc", limit=6)
        alerts = self.env["sp.alert"].search([("restaurant_id", "=", rid), ("state", "=", "open")],
                                             order="severity desc, create_date desc", limit=8)
        insights = self.env["sp.insight"].search([("restaurant_id", "=", rid), ("state", "=", "new")],
                                                 order="priority desc, create_date desc", limit=6)
        birthdays = Partner.search(pdom + [("sp_birthday", "!=", False)]).filtered(lambda p: p.sp_birthday_soon)

        fee_pct = restaurant.plan_success_fee_pct or 0.0
        success_fee = tracked_month * fee_pct / 100.0
        marketplace_cost = tracked_month * (restaurant.marketplace_fee_reference_pct or 0.0) / 100.0
        return {
            "restaurant": {"id": rid, "name": restaurant.name, "slug": restaurant.slug, "segment": restaurant.segment,
                           "menu_url": restaurant.menu_url,
                           "last_rfv_run": restaurant.last_rfv_run.replace(tzinfo=pytz.utc).astimezone(TZ).strftime("%d/%m/%Y %H:%M")
                           if restaurant.last_rfv_run else None},
            "kpis": {
                "revenue_30d": rev30, "revenue_prev_30d": rev_prev, "orders_30d": orders30, "orders_prev_30d": orders_prev,
                "avg_ticket_30d": ticket30, "active_customers_30d": cust30, "active_customers_prev": cust_prev,
                "retention_rate": retention, "total_customers": total_customers, "new_customers_30d": new30,
                "at_risk": at_risk, "critical": critical, "opt_in": opt_in,
                "revenue_month": rev_month, "tracked_month": tracked_month, "attributed_month": attributed_month,
                "recommendation_month": recom_month, "success_fee": success_fee, "monthly_fee": restaurant.plan_monthly_fee,
                "marketplace_cost": marketplace_cost, "savings": marketplace_cost - success_fee - restaurant.plan_monthly_fee,
                "fee_pct": fee_pct, "marketplace_pct": restaurant.marketplace_fee_reference_pct,
            },
            "segments": segments,
            "matrix": matrix,
            "weeks": [{"week": w[0].strftime("%d/%m"), "revenue": w[1], "orders": w[2]} for w in weeks],
            "heat": heat, "weekday_short": WEEKDAY_SHORT,
            "channels": [{"code": c[0], "label": channel_labels.get(c[0], c[0]), "orders": c[1], "revenue": c[2]} for c in channels],
            "top_products": top_products,
            "campaigns": [{"id": c.id, "name": c.name, "channel": c.channel, "state": c.state, "sent": c.sent_count,
                           "clicks": c.click_count, "orders": c.order_count, "revenue": c.attributed_revenue,
                           "roi": c.roi, "conversion": c.conversion_rate} for c in campaigns],
            "alerts": [{"id": a.id, "partner_id": a.partner_id.id, "partner": a.partner_id.name, "type": a.alert_type,
                        "type_label": dict(a._fields["alert_type"].selection).get(a.alert_type),
                        "severity": a.severity, "title": a.name, "suggestion": a.suggestion} for a in alerts],
            "insights": [{"id": i.id, "title": i.name, "body": i.body, "kind": i.kind, "priority": i.priority,
                          "action_label": i.action_label} for i in insights],
            "birthdays": [{"id": p.id, "name": p.name, "in_days": p._birthday_in_days(), "segment": p.sp_segment} for p in birthdays[:8]],
        }
