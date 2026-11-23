# -*- coding: utf-8 -*-
"""Cobrança por sucesso: mensalidade + % sobre a receita rastreada pela jornada SalesPilot."""
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models, _

from .rfv_engine import ACTIVE_STATES


class SpBillingPeriod(models.Model):
    _name = "sp.billing.period"
    _description = "Fatura SalesPilot (mensalidade + sucesso)"
    _order = "date_from desc, restaurant_id"

    name = fields.Char("Fatura", compute="_compute_name", store=True)
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade")
    date_from = fields.Date("De", required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date("Até", required=True, default=lambda self: fields.Date.today())
    state = fields.Selection(string="Status", selection=[("draft", "Prévia"), ("issued", "Emitida"), ("paid", "Paga")], default="draft")
    currency_id = fields.Many2one(related="restaurant_id.currency_id")

    monthly_fee = fields.Float("Mensalidade")
    success_fee_pct = fields.Float("Taxa de sucesso (%)")
    marketplace_pct = fields.Float("Taxa de marketplace de referência (%)")
    orders_total = fields.Integer("Pedidos no período")
    revenue_total = fields.Float("Receita total do restaurante")
    orders_tracked = fields.Integer("Pedidos rastreados")
    tracked_revenue = fields.Float("Receita rastreada (cardápio + campanhas)")
    attributed_revenue = fields.Float("Receita atribuída a campanhas")
    recommendation_revenue = fields.Float("Receita com recomendação aceita")
    messages_sent = fields.Integer("Mensagens enviadas")
    success_fee = fields.Float("Taxa de sucesso (R$)")
    total_due = fields.Float("Total a pagar")
    marketplace_reference_cost = fields.Float("Custo equivalente em marketplace")
    savings = fields.Float("Economia vs. marketplace")
    effective_rate = fields.Float("Custo efetivo (% da receita rastreada)")
    notes = fields.Text("Observações")

    _sql_constraints = [("period_unique", "unique(restaurant_id, date_from, date_to)", "Já existe fatura para este período.")]

    @api.depends("restaurant_id", "date_from", "date_to")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.restaurant_id.name or ''} — {rec.date_from.strftime('%m/%Y') if rec.date_from else ''}"

    def action_compute(self):
        Order = self.env["sp.order"]
        for rec in self:
            r = rec.restaurant_id
            dt_from = datetime.combine(rec.date_from, time.min)
            dt_to = datetime.combine(rec.date_to, time.max)
            orders = Order.search([("restaurant_id", "=", r.id), ("state", "in", ACTIVE_STATES),
                                   ("date_order", ">=", dt_from), ("date_order", "<=", dt_to)])
            tracked = orders.filtered("tracked")
            attributed = orders.filtered("attributed")
            recom = orders.filtered("recommendation_accepted")
            msgs = self.env["sp.message"].search_count([("restaurant_id", "=", r.id), ("state", "in", ("sent", "delivered", "read")),
                                                        ("date_sent", ">=", dt_from), ("date_sent", "<=", dt_to)])
            tracked_rev = sum(tracked.mapped("amount_total"))
            fee = tracked_rev * (r.plan_success_fee_pct or 0) / 100.0
            mk = tracked_rev * (r.marketplace_fee_reference_pct or 0) / 100.0
            rec.write({
                "monthly_fee": r.plan_monthly_fee, "success_fee_pct": r.plan_success_fee_pct,
                "marketplace_pct": r.marketplace_fee_reference_pct,
                "orders_total": len(orders), "revenue_total": sum(orders.mapped("amount_total")),
                "orders_tracked": len(tracked), "tracked_revenue": tracked_rev,
                "attributed_revenue": sum(attributed.mapped("amount_total")),
                "recommendation_revenue": sum(recom.mapped("amount_total")),
                "messages_sent": msgs, "success_fee": fee, "total_due": fee + r.plan_monthly_fee,
                "marketplace_reference_cost": mk, "savings": mk - fee - r.plan_monthly_fee,
                "effective_rate": ((fee + r.plan_monthly_fee) / tracked_rev * 100.0) if tracked_rev else 0.0,
            })
        return True

    def action_issue(self):
        self.action_compute()
        self.write({"state": "issued"})

    def action_paid(self):
        self.write({"state": "paid"})

    @api.model
    def cron_generate_previous_month(self):
        today = fields.Date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        for r in self.env["sp.restaurant"].search([]):
            if not self.search_count([("restaurant_id", "=", r.id), ("date_from", "=", first_prev)]):
                self.create({"restaurant_id": r.id, "date_from": first_prev, "date_to": last_prev}).action_compute()
        return True

    @api.model
    def generate_for_month(self, restaurant, year, month):
        if isinstance(restaurant, int):
            restaurant = self.env["sp.restaurant"].browse(restaurant)
        first = date(year, month, 1)
        last = (first.replace(month=month % 12 + 1, year=year + (month // 12)) - timedelta(days=1))
        period = self.search([("restaurant_id", "=", restaurant.id), ("date_from", "=", first)], limit=1)
        if not period:
            period = self.create({"restaurant_id": restaurant.id, "date_from": first, "date_to": last})
        period.action_compute()
        return period
