# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rfv_engine import brl

ALERT_TYPES = [
    ("churn_warning", "Queda de recorrência"),
    ("churn_critical", "Red flag: cliente sumiu"),
    ("cant_lose", "Campeão em risco"),
    ("birthday", "Aniversário"),
    ("new_champion", "Novo campeão"),
    ("segment_drop", "Caiu de segmento"),
    ("automation", "Régua automática"),
]


class SpAlert(models.Model):
    _name = "sp.alert"
    _description = "Alerta de relacionamento"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "severity desc, create_date desc"

    name = fields.Char("Título", required=True)
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", "Cliente", required=True, index=True, ondelete="cascade")
    alert_type = fields.Selection(ALERT_TYPES, string="Tipo de alerta", required=True, index=True)
    severity = fields.Selection([("1", "Baixa"), ("2", "Média"), ("3", "Alta")], string="Prioridade", default="2", index=True)
    description = fields.Text("Detalhes")
    suggestion = fields.Text("Ação sugerida")
    state = fields.Selection(string="Status", selection=[("open", "Aberto"), ("done", "Resolvido"), ("dismissed", "Ignorado")],
                             default="open", index=True, tracking=True)
    resolution = fields.Char("Como foi resolvido")
    date_resolved = fields.Datetime("Resolvido em", readonly=True)
    automation_id = fields.Many2one("sp.automation", "Régua")
    message_id = fields.Many2one("sp.message", "Mensagem enviada")
    partner_segment = fields.Selection(related="partner_id.sp_segment", string="Segmento")
    partner_recency = fields.Integer(related="partner_id.sp_recency_days", string="Dias sem pedir")
    partner_ltv = fields.Float(related="partner_id.sp_ltv", string="LTV")
    partner_whatsapp = fields.Char(related="partner_id.sp_whatsapp", string="WhatsApp")

    # ------------------------------------------------------------------
    @api.model
    def _open_exists(self, partner, alert_type):
        return bool(self.search_count([("partner_id", "=", partner.id), ("alert_type", "=", alert_type),
                                       ("state", "=", "open")]))

    @api.model
    def scan(self, restaurants):
        """Gera alertas a partir do estado atual dos clientes (chamado após o RFV)."""
        Partner = self.env["res.partner"]
        today = fields.Date.context_today(self)
        for restaurant in restaurants:
            base = [("sp_restaurant_id", "=", restaurant.id), ("sp_is_customer", "=", True)]
            for p in Partner.search(base + [("sp_churn_risk", "=", "critical")]):
                kind = "cant_lose" if p.sp_segment_prev in ("champions", "loyal") or p.sp_segment in ("cant_lose", "at_risk") else "churn_critical"
                if not self._open_exists(p, kind):
                    fav = p.sp_favorite_product_id.name or "o pedido de sempre"
                    self.create({
                        "restaurant_id": restaurant.id, "partner_id": p.id, "alert_type": kind, "severity": "3",
                        "name": f"{p.name} sumiu: {p.sp_recency_days} dias sem pedir (ritmo: a cada {p.sp_typical_interval:.0f} dias)",
                        "description": p.sp_profile_summary,
                        "suggestion": f"Mandar WhatsApp pessoal oferecendo {fav} com cupom de reativação. "
                                      f"LTV em jogo: {brl(p.sp_ltv)}.",
                    })
            for p in Partner.search(base + [("sp_churn_risk", "=", "warning")]):
                if not self._open_exists(p, "churn_warning") and not self._open_exists(p, "churn_critical"):
                    self.create({
                        "restaurant_id": restaurant.id, "partner_id": p.id, "alert_type": "churn_warning", "severity": "2",
                        "name": f"{p.name} está atrasado: {p.sp_recency_days} dias sem pedir (costuma pedir a cada {p.sp_typical_interval:.0f})",
                        "description": p.sp_profile_summary,
                        "suggestion": "Lembrete leve do produto favorito, sem desconto ainda.",
                    })
            for p in Partner.search(base + [("sp_segment", "=", "champions"), ("sp_segment_prev", "not in", ("champions", "none", False))]):
                if not self._open_exists(p, "new_champion"):
                    self.create({
                        "restaurant_id": restaurant.id, "partner_id": p.id, "alert_type": "new_champion", "severity": "1",
                        "name": f"{p.name} virou Campeão 🏆",
                        "suggestion": "Agradecer e oferecer um mimo. Pedir avaliação no Google / indicação.",
                    })
            for p in Partner.search(base + [("sp_birthday", "!=", False), ("sp_opt_in", "=", True)]):
                days = p._birthday_in_days(today)
                if days is not None and 0 <= days <= 3 and not self._open_exists(p, "birthday"):
                    self.create({
                        "restaurant_id": restaurant.id, "partner_id": p.id, "alert_type": "birthday", "severity": "1",
                        "name": f"Aniversário de {p.name} {'hoje' if days == 0 else f'em {days} dia(s)'} 🎂",
                        "suggestion": "Enviar parabéns com cupom de aniversário.",
                    })
        return True

    @api.model
    def create_from_automation(self, automation, partner, message):
        if self._open_exists(partner, "automation") and automation.trigger not in ("welcome", "post_purchase"):
            return self.browse()
        return self.create({
            "restaurant_id": automation.restaurant_id.id, "partner_id": partner.id, "alert_type": "automation",
            "severity": "2" if automation.trigger in ("churn", "winback") else "1",
            "name": f"Régua '{automation.name}' disparada para {partner.name}",
            "description": message.body if message else "Mensagem não enviada (cooldown ou sem opt-in).",
            "suggestion": "Acompanhar se o cliente volta a pedir nos próximos dias.",
            "automation_id": automation.id, "message_id": message.id if message else False,
        })

    @api.model
    def resolve_for_partners(self, partners, reason):
        alerts = self.search([("partner_id", "in", partners.ids), ("state", "=", "open"),
                              ("alert_type", "in", ("churn_warning", "churn_critical", "cant_lose", "automation"))])
        alerts.write({"state": "done", "resolution": reason, "date_resolved": fields.Datetime.now()})
        return alerts

    def action_done(self):
        self.write({"state": "done", "date_resolved": fields.Datetime.now(), "resolution": self.resolution or "Tratado manualmente"})

    def action_dismiss(self):
        self.write({"state": "dismissed", "date_resolved": fields.Datetime.now()})

    def action_reopen(self):
        self.write({"state": "open", "date_resolved": False})

    def action_send_message(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "sp.send.message.wizard", "name": _("Enviar mensagem"),
            "view_mode": "form", "target": "new",
            "context": {"default_partner_ids": [(6, 0, self.partner_id.ids)], "default_restaurant_id": self.restaurant_id.id,
                        "default_alert_id": self.id, "default_preset": "reactivation" if "churn" in self.alert_type or self.alert_type == "cant_lose" else self.alert_type},
        }

    def action_open_partner(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "res.partner", "res_id": self.partner_id.id, "view_mode": "form"}
