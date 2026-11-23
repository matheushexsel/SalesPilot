# -*- coding: utf-8 -*-
"""Insights gerados automaticamente a partir dos dados do restaurante ("IA de bolso")."""
from collections import Counter
from datetime import timedelta

from odoo import api, fields, models, _

from .rfv_engine import ACTIVE_STATES, SEGMENT_META, WEEKDAY_NAMES

KINDS = [("rfv", "Base de clientes"), ("habit", "Hábitos"), ("product", "Cardápio / combos"),
         ("campaign", "Campanhas"), ("revenue", "Receita"), ("channel", "Canais")]


def brl(v):
    return ("R$ {:,.0f}".format(v)).replace(",", ".")


class SpInsight(models.Model):
    _name = "sp.insight"
    _description = "Insight automático"
    _order = "priority desc, create_date desc"

    name = fields.Char("Insight", required=True)
    body = fields.Text("Explicação")
    kind = fields.Selection(KINDS, string="Tipo", default="rfv")
    priority = fields.Selection([("1", "Baixa"), ("2", "Média"), ("3", "Alta")], string="Prioridade", default="2")
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade")
    state = fields.Selection(string="Status", selection=[("new", "Novo"), ("done", "Aplicado"), ("dismissed", "Ignorado")], default="new", index=True)
    action_label = fields.Char("Ação sugerida")
    action_campaign_type = fields.Char("Tipo de campanha sugerida")
    action_segment_codes = fields.Char("Segmentos sugeridos")
    action_coupon = fields.Char("Cupom sugerido")
    action_discount = fields.Float("Desconto sugerido (%)")
    metric_value = fields.Float("Valor em jogo (R$)")

    def action_apply(self):
        """Abre uma campanha pré-preenchida com a sugestão."""
        self.ensure_one()
        self.state = "done"
        if not self.action_campaign_type:
            return True
        from .campaign import DEFAULT_TEMPLATES
        ctx = {
            "default_restaurant_id": self.restaurant_id.id,
            "default_name": self.action_label or self.name,
            "default_campaign_type": self.action_campaign_type,
            "default_segment_codes": self.action_segment_codes or "",
            "default_coupon_code": self.action_coupon or "",
            "default_discount_pct": self.action_discount or 0.0,
            "default_message_template": DEFAULT_TEMPLATES.get(self.action_campaign_type, DEFAULT_TEMPLATES["manual"]),
        }
        return {"type": "ir.actions.act_window", "res_model": "sp.campaign", "view_mode": "form", "views": [(False, "form")],
                "target": "current", "name": _("Nova campanha"), "context": ctx}

    def action_dismiss(self):
        self.write({"state": "dismissed"})

    @api.model
    def generate_for(self, restaurants):
        Partner = self.env["res.partner"]
        engine = self.env["sp.rfv.engine"]
        for r in restaurants:
            self.search([("restaurant_id", "=", r.id), ("state", "=", "new")]).unlink()
            base = [("sp_restaurant_id", "=", r.id), ("sp_is_customer", "=", True)]
            customers = Partner.search(base)
            if not customers:
                continue
            vals = []
            with_orders = customers.filtered(lambda p: p.sp_total_orders)
            total_rev = sum(with_orders.mapped("sp_monetary")) or 1.0

            # 1. Receita em risco
            risky = customers.filtered(lambda p: p.sp_churn_risk in ("warning", "critical"))
            if risky:
                at_stake = sum(risky.mapped("sp_monetary"))
                vals.append({
                    "name": f"{len(risky)} clientes reduziram a recorrência — {brl(at_stake)} em risco",
                    "body": f"{len(risky.filtered(lambda p: p.sp_churn_risk == 'critical'))} já estão em nível crítico. "
                            "Eles compravam em ritmo regular e pararam; provavelmente estão pedindo de outro lugar. "
                            "Uma campanha de reativação com cupom costuma recuperar 10–20% deles.",
                    "kind": "rfv", "priority": "3", "metric_value": at_stake,
                    "action_label": "Criar campanha de reativação", "action_campaign_type": "reactivation",
                    "action_segment_codes": "at_risk,cant_lose,need_attention,about_to_sleep",
                    "action_coupon": "VOLTEI15", "action_discount": 15,
                })

            # 2. Pareto dos campeões
            champs = customers.filtered(lambda p: p.sp_segment == "champions")
            if champs:
                share = sum(champs.mapped("sp_monetary")) / total_rev * 100
                vals.append({
                    "name": f"{len(champs)} Campeões ({len(champs) / len(with_orders) * 100:.0f}% da base) geram {share:.0f}% da receita",
                    "body": "Clientes que compram muito e recentemente. Recompensar esse grupo custa pouco e protege a maior "
                            "parte do faturamento. Ideias: cupom VIP, acesso antecipado a novidades, pedir avaliação no Google.",
                    "kind": "rfv", "priority": "2", "metric_value": sum(champs.mapped("sp_monetary")),
                    "action_label": "Agradecer os Campeões", "action_campaign_type": "vip",
                    "action_segment_codes": "champions", "action_coupon": "VIP10", "action_discount": 10,
                })

            # 3. Novos sem segunda compra
            d30 = fields.Datetime.now() - timedelta(days=30)
            new_one = customers.filtered(lambda p: p.sp_total_orders == 1 and p.sp_first_order_date and p.sp_first_order_date >= d30)
            if len(new_one) >= 3:
                vals.append({
                    "name": f"{len(new_one)} clientes novos ainda não fizeram o 2º pedido",
                    "body": "A segunda compra é o maior salto de retenção. Um cupom de boas-vindas válido por 7 dias "
                            "empurra esse grupo para o segmento de potenciais fiéis.",
                    "kind": "rfv", "priority": "2",
                    "action_label": "Cupom para a 2ª compra", "action_campaign_type": "welcome",
                    "action_segment_codes": "new", "action_coupon": "BEMVINDO10", "action_discount": 10,
                })

            # 4. Pico de demanda e lembretes de hábito
            self.env.cr.execute("""SELECT weekday, hour, COUNT(*) FROM sp_order
                                   WHERE restaurant_id=%s AND state IN %s AND date_order >= %s
                                   GROUP BY weekday, hour ORDER BY 3 DESC LIMIT 1""",
                                (r.id, ACTIVE_STATES, fields.Datetime.now() - timedelta(days=90)))
            row = self.env.cr.fetchone()
            habit_customers = customers.filtered(lambda p: p.sp_favorite_weekday)
            if row:
                wd, hr, cnt = row
                wd_counter = Counter(habit_customers.mapped("sp_favorite_weekday"))
                top_wd, top_wd_count = (wd_counter.most_common(1)[0] if wd_counter else (str(wd), 0))
                vals.append({
                    "name": f"Seu pico é {WEEKDAY_NAMES[wd]} às {hr}h; {len(habit_customers)} clientes têm dia fixo para pedir",
                    "body": f"{top_wd_count} clientes pedem sempre na {WEEKDAY_NAMES[int(top_wd)]}. Um lembrete 2h antes do horário "
                            "habitual (régua 'Lembrete de hábito') aumenta a chance de o pedido vir para você e não para o concorrente.",
                    "kind": "habit", "priority": "2",
                    "action_label": "Campanha de lembrete de hábito", "action_campaign_type": "habit",
                    "action_segment_codes": "champions,loyal,potential_loyal",
                })

            # 5. Combos a partir da coocorrência
            pair, single, n_orders = engine.cooccurrence(r)
            Template = self.env["product.template"]
            kinds = {t.id: t.sp_kind for t in Template.with_context(active_test=False).search([("sp_restaurant_id", "=", r.id)])}
            best = None
            for a, others in pair.items():
                if kinds.get(a) not in ("main", "combo") or single.get(a, 0) < 8:
                    continue
                for b, cnt in others.items():
                    if kinds.get(b) not in ("side", "drink", "dessert"):
                        continue
                    conf = cnt / single[a]
                    if conf >= 0.3 and (not best or conf * cnt > best[2] * best[3]):
                        best = (a, b, conf, cnt)
            if best:
                pa, pb = Template.browse(best[0]), Template.browse(best[1])
                has_combo = Template.search_count([("sp_restaurant_id", "=", r.id), ("sp_kind", "=", "combo"),
                                                   ("name", "ilike", pa.name.split(" ")[0])])
                vals.append({
                    "name": f"{int(best[2] * 100)}% de quem pede {pa.name} também leva {pb.name}",
                    "body": f"Combinação apareceu em {best[3]} pedidos nos últimos 120 dias. "
                            + ("Já existe um combo parecido; destaque-o no cardápio." if has_combo else
                               "Crie um combo com pequeno desconto: aumenta ticket médio e simplifica a escolha."),
                    "kind": "product", "priority": "2" if not has_combo else "1",
                    "action_label": "Divulgar combo", "action_campaign_type": "launch",
                    "action_segment_codes": "champions,loyal,potential_loyal,promising",
                })

            # 6. Canal: dependência de marketplace
            self.env.cr.execute("""SELECT channel, COUNT(*), SUM(amount_total) FROM sp_order
                                   WHERE restaurant_id=%s AND state IN %s AND date_order >= %s GROUP BY channel""",
                                (r.id, ACTIVE_STATES, fields.Datetime.now() - timedelta(days=90)))
            ch = {c: (n, v) for c, n, v in self.env.cr.fetchall()}
            total_ch = sum(v for _n, v in ch.values()) or 1.0
            ifood_rev = ch.get("ifood", (0, 0.0))[1]
            if ifood_rev / total_ch >= 0.25:
                saving = ifood_rev * (r.marketplace_fee_reference_pct - r.plan_success_fee_pct) / 100.0
                vals.append({
                    "name": f"{ifood_rev / total_ch * 100:.0f}% da receita vem do iFood — {brl(saving)}/trimestre em comissões",
                    "body": f"Clientes recorrentes do iFood podem ser migrados para o seu cardápio próprio "
                            f"(taxa de {r.plan_success_fee_pct:g}% em vez de ~{r.marketplace_fee_reference_pct:g}%). "
                            "Inclua um cartão com QR code do cardápio no pacote e um cupom de primeira compra direta.",
                    "kind": "channel", "priority": "2", "metric_value": saving,
                    "action_label": "Campanha de migração para o cardápio próprio", "action_campaign_type": "manual",
                })

            # 7. Aniversários da semana
            bdays = customers.filtered(lambda p: p.sp_birthday_soon)
            if bdays:
                vals.append({
                    "name": f"{len(bdays)} clientes fazem aniversário nos próximos 7 dias",
                    "body": "Mensagem de parabéns com cupom tem a maior taxa de conversão entre as réguas. "
                            "A régua 'Aniversário' cuida disso automaticamente; confira se está ativa.",
                    "kind": "campaign", "priority": "1",
                    "action_label": "Campanha de aniversário", "action_campaign_type": "birthday",
                    "action_coupon": "NIVER20", "action_discount": 20,
                })

            # 8. Melhor campanha
            best_camp = self.env["sp.campaign"].search([("restaurant_id", "=", r.id), ("sent_count", ">", 0)],
                                                       order="roi desc", limit=1)
            if best_camp and best_camp.roi:
                vals.append({
                    "name": f"Campanha '{best_camp.name}' teve ROI de {best_camp.roi:.0f}× e {best_camp.conversion_rate:.0f}% de conversão",
                    "body": f"{best_camp.sent_count} mensagens → {best_camp.order_count} pedidos ({brl(best_camp.attributed_revenue)}). "
                            "Repita o formato para o mesmo público em 3–4 semanas.",
                    "kind": "campaign", "priority": "1",
                    "action_label": "Repetir campanha", "action_campaign_type": best_camp.campaign_type,
                    "action_segment_codes": best_camp.segment_codes or "",
                    "action_coupon": best_camp.coupon_code or "", "action_discount": best_camp.discount_pct,
                })

            for v in vals:
                v["restaurant_id"] = r.id
            self.create(vals)
        return True
