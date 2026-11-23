# -*- coding: utf-8 -*-
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)
from odoo.exceptions import UserError

from .res_partner import RFV_SEGMENTS

CHANNELS = [("whatsapp", "WhatsApp"), ("sms", "SMS"), ("email", "E-mail")]

CAMPAIGN_TYPES = [
    ("manual", "Campanha avulsa"),
    ("reactivation", "Reativação"),
    ("habit", "Lembrete de hábito"),
    ("birthday", "Aniversário"),
    ("welcome", "Boas-vindas"),
    ("post_purchase", "Pós-compra"),
    ("launch", "Lançamento / novidade"),
    ("vip", "VIP / fidelidade"),
]

DEFAULT_TEMPLATES = {
    "reactivation": "Oi {nome}! Sentimos sua falta por aqui 🥲 Faz um tempinho que você não pede seu {produto_favorito}. "
                    "Pra te trazer de volta, use o cupom {cupom} e ganhe {desconto} hoje: {link}",
    "habit": "Oi {nome}! {dia_semana} é dia de {produto_favorito}, né? 😋 Já deixamos tudo pronto pra você pedir em 1 toque: {link}",
    "birthday": "Parabéns, {nome}! 🎂 Hoje é seu dia e a gente quer comemorar junto: use o cupom {cupom} e ganhe {desconto} no seu pedido. {link}",
    "welcome": "Oi {nome}, obrigado pelo primeiro pedido no {restaurante}! 🙌 Na próxima, use {cupom} e ganhe {desconto}: {link}",
    "post_purchase": "Oi {nome}! Tudo certo com o seu pedido de hoje? Responda de 0 a 10 o quanto você recomendaria o {restaurante} 🙏",
    "launch": "Oi {nome}! Novidade no cardápio do {restaurante} 🔥 Dá uma olhada: {link}",
    "vip": "Oi {nome}! Você é um dos nossos clientes VIP 🏆. Como agradecimento, {desconto} no próximo pedido com o cupom {cupom}: {link}",
    "manual": "Oi {nome}! {restaurante} com uma oferta especial pra você: {link}",
}


class SpCampaign(models.Model):
    _name = "sp.campaign"
    _description = "Campanha de relacionamento"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_scheduled desc, id desc"

    name = fields.Char("Nome da campanha", required=True, tracking=True)
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade",
                                    default=lambda self: self.env["sp.restaurant"]._get_user_restaurants()[:1])
    campaign_type = fields.Selection(CAMPAIGN_TYPES, "Tipo", default="manual", required=True)
    channel = fields.Selection(CHANNELS, string="Canal", required=True, default="whatsapp")
    state = fields.Selection(string="Status", selection=[
        ("draft", "Rascunho"), ("scheduled", "Agendada"), ("sending", "Enviando"),
        ("sent", "Enviada"), ("done", "Encerrada"), ("cancelled", "Cancelada"),
    ], default="draft", tracking=True, index=True)
    automation_id = fields.Many2one("sp.automation", "Gerada pela régua", readonly=True)
    date_scheduled = fields.Datetime("Agendar para", default=fields.Datetime.now)
    date_sent = fields.Datetime("Enviada em", readonly=True)

    # Público
    segment_codes = fields.Char("Segmentos RFV", help="Códigos separados por vírgula. Vazio = todos.")
    segment_ids_display = fields.Char(compute="_compute_segment_display", string="Público (segmentos)")
    target_churn_risk = fields.Selection([("any", "Qualquer"), ("risk", "Só em risco (atenção/crítico)"),
                                          ("none", "Só sem risco")], default="any", string="Risco de perda")
    target_min_orders = fields.Integer("Mínimo de pedidos", default=0)
    target_days_since_min = fields.Integer("Dias sem pedir (mín.)", default=0)
    target_days_since_max = fields.Integer("Dias sem pedir (máx.)", default=0, help="0 = sem limite")
    target_favorite_product_id = fields.Many2one("product.template", "Favorito é", domain="[('sp_restaurant_id','=',restaurant_id)]")
    only_opt_in = fields.Boolean("Só clientes com opt-in", default=True)
    partner_ids = fields.Many2many("res.partner", "sp_campaign_partner_rel", "campaign_id", "partner_id",
                                   string="Destinatários (fixos)",
                                   help="Se preenchido, substitui os filtros de segmento.")
    audience_count = fields.Integer("Tamanho do público", compute="_compute_audience")

    # Conteúdo
    message_template = fields.Text("Mensagem", required=True,
                                   help="Variáveis: {nome} {produto_favorito} {cupom} {desconto} {link} {restaurante} {dia_semana}")
    coupon_code = fields.Char("Cupom")
    discount_pct = fields.Float("Desconto (%)", default=0.0)
    discount_value = fields.Float("Desconto (R$)", default=0.0)
    coupon_valid_days = fields.Integer("Validade do cupom (dias)", default=7)
    utm_token = fields.Char("Token de rastreio", default=lambda self: secrets.token_urlsafe(6), copy=False)
    cost_per_message = fields.Float("Custo por mensagem (R$)", default=0.08,
                                    help="Estimativa (WhatsApp API ~R$0,08 marketing; SMS ~R$0,10).")

    # Resultados
    sp_message_ids = fields.One2many("sp.message", "campaign_id", "Mensagens")
    order_ids = fields.One2many("sp.order", "campaign_id", "Pedidos atribuídos")
    sent_count = fields.Integer("Enviadas", compute="_compute_stats", store=True)
    delivered_count = fields.Integer("Entregues", compute="_compute_stats", store=True)
    click_count = fields.Integer("Cliques no cardápio", compute="_compute_stats", store=True)
    order_count = fields.Integer("Nº de pedidos atribuídos", compute="_compute_stats", store=True)
    attributed_revenue = fields.Float("Receita atribuída", compute="_compute_stats", store=True)
    cost_total = fields.Float("Custo estimado", compute="_compute_stats", store=True)
    roi = fields.Float("ROI (x)", compute="_compute_stats", store=True)
    conversion_rate = fields.Float("Conversão (%)", compute="_compute_stats", store=True)
    click_rate = fields.Float("Taxa de clique (%)", compute="_compute_stats", store=True)

    @api.depends("segment_codes")
    def _compute_segment_display(self):
        labels = dict(RFV_SEGMENTS)
        for rec in self:
            codes = [c.strip() for c in (rec.segment_codes or "").split(",") if c.strip()]
            rec.segment_ids_display = ", ".join(labels.get(c, c) for c in codes) or "Todos os clientes"

    @api.onchange("campaign_type")
    def _onchange_campaign_type(self):
        if self.campaign_type and (not self.message_template or self.message_template in DEFAULT_TEMPLATES.values()):
            self.message_template = DEFAULT_TEMPLATES.get(self.campaign_type)
        presets = {
            "reactivation": {"segment_codes": "at_risk,cant_lose,about_to_sleep,need_attention", "target_churn_risk": "any",
                             "discount_pct": 15, "coupon_code": "VOLTEI15"},
            "habit": {"segment_codes": "champions,loyal", "target_churn_risk": "any"},
            "birthday": {"segment_codes": "", "discount_pct": 20, "coupon_code": "NIVER20"},
            "welcome": {"segment_codes": "new", "discount_pct": 10, "coupon_code": "BEMVINDO10"},
            "vip": {"segment_codes": "champions", "discount_pct": 10, "coupon_code": "VIP10"},
            "launch": {"segment_codes": "champions,loyal,potential_loyal,promising"},
        }
        defaults = {"segment_codes": "", "target_churn_risk": "any", "discount_pct": 0.0, "discount_value": 0.0,
                    "coupon_code": False}
        defaults.update(presets.get(self.campaign_type or "", {}))
        for k, v in defaults.items():
            setattr(self, k, v)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        insight_id = self.env.context.get("sp_insight_id")
        if insight_id:
            self.env["sp.insight"].browse(insight_id).sudo().write({"state": "done"})
        return records

    # ------------------------------------------------------------------
    def _audience_domain(self):
        self.ensure_one()
        domain = [("sp_restaurant_id", "=", self.restaurant_id.id), ("sp_is_customer", "=", True)]
        if self.only_opt_in:
            domain.append(("sp_opt_in", "=", True))
        if self.channel in ("whatsapp", "sms"):
            domain.append(("sp_whatsapp_norm", "!=", False))
        elif self.channel == "email":
            domain.append(("email", "!=", False))
        codes = [c.strip() for c in (self.segment_codes or "").split(",") if c.strip()]
        if codes:
            domain.append(("sp_segment", "in", codes))
        if self.target_churn_risk == "risk":
            domain.append(("sp_churn_risk", "in", ("warning", "critical")))
        elif self.target_churn_risk == "none":
            domain.append(("sp_churn_risk", "=", "none"))
        if self.target_min_orders:
            domain.append(("sp_total_orders", ">=", self.target_min_orders))
        if self.target_days_since_min:
            domain.append(("sp_recency_days", ">=", self.target_days_since_min))
        if self.target_days_since_max:
            domain.append(("sp_recency_days", "<=", self.target_days_since_max))
        if self.target_favorite_product_id:
            domain.append(("sp_favorite_product_id.product_tmpl_id", "=", self.target_favorite_product_id.id))
        return domain

    def _audience(self):
        self.ensure_one()
        if self.partner_ids:
            return self.partner_ids
        return self.env["res.partner"].search(self._audience_domain())

    @api.depends("segment_codes", "target_churn_risk", "target_min_orders", "target_days_since_min",
                 "target_days_since_max", "only_opt_in", "partner_ids", "channel", "restaurant_id",
                 "target_favorite_product_id")
    def _compute_audience(self):
        for rec in self:
            rec.audience_count = len(rec._audience()) if rec.restaurant_id else 0

    @api.depends("sp_message_ids.state", "sp_message_ids.clicked", "order_ids.amount_total", "order_ids.state",
                 "cost_per_message")
    def _compute_stats(self):
        for rec in self:
            msgs = rec.sp_message_ids
            sent = msgs.filtered(lambda m: m.state in ("sent", "delivered", "read"))
            rec.sent_count = len(sent)
            rec.delivered_count = len(msgs.filtered(lambda m: m.state in ("delivered", "read")))
            rec.click_count = len(msgs.filtered("clicked"))
            orders = rec.order_ids.filtered(lambda o: o.state in ("confirmed", "preparing", "delivering", "delivered"))
            rec.order_count = len(orders)
            rec.attributed_revenue = sum(orders.mapped("amount_total"))
            rec.cost_total = rec.sent_count * rec.cost_per_message
            rec.roi = (rec.attributed_revenue / rec.cost_total) if rec.cost_total else 0.0
            rec.conversion_rate = (rec.order_count / rec.sent_count * 100.0) if rec.sent_count else 0.0
            rec.click_rate = (rec.click_count / rec.sent_count * 100.0) if rec.sent_count else 0.0

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------
    def action_schedule(self):
        for rec in self:
            if not rec.message_template:
                raise UserError(_("Escreva a mensagem antes de agendar."))
            if not rec.date_scheduled:
                rec.date_scheduled = fields.Datetime.now()
            rec.state = "scheduled"

    def action_send_now(self):
        for rec in self:
            rec.date_scheduled = fields.Datetime.now()
            rec._send()

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_done(self):
        self.write({"state": "done"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_preview_audience(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "res.partner", "name": _("Público da campanha"),
            "view_mode": "list,kanban,form", "domain": [("id", "in", self._audience().ids)],
            "context": {"search_default_sp_customers": 1},
        }

    def action_view_messages(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "sp.message", "name": _("Mensagens"),
                "view_mode": "list,form", "domain": [("campaign_id", "=", self.id)]}

    def action_view_orders(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "sp.order", "name": _("Pedidos atribuídos"),
                "view_mode": "list,form", "domain": [("campaign_id", "=", self.id)]}

    def action_generate_copy(self):
        """Gera o texto com o assistente de IA (ou modelo local) conforme o tipo e o público."""
        for rec in self:
            rec.message_template = self.env["sp.ai.copy"].campaign_copy(rec)
        return True

    def _send(self):
        Message = self.env["sp.message"]
        for rec in self:
            if rec.state in ("sent", "done", "cancelled"):
                continue
            rec.state = "sending"
            audience = rec._audience()
            already = set(rec.sp_message_ids.mapped("partner_id").ids)
            to_create = []
            for partner in audience:
                if partner.id in already:
                    continue
                to_create.append(Message._prepare_from_campaign(rec, partner))
            msgs = Message.create(to_create)
            msgs.action_send()
            rec.write({"state": "sent", "date_sent": fields.Datetime.now()})
            rec._message_log(body=_("Campanha enviada para %s cliente(s) pelo canal %s.", len(msgs), rec.channel))
        return True

    @api.model
    def cron_send_scheduled(self):
        now = fields.Datetime.now()
        for camp in self.search([("state", "=", "scheduled"), ("date_scheduled", "<=", now)]):
            try:
                with self.env.cr.savepoint():
                    camp._send()
            except Exception:  # pragma: no cover - não travar a fila por uma campanha
                _logger.exception("Falha ao enviar a campanha %s", camp.id)
                camp._message_log(body=_("Falha ao enviar automaticamente; verifique a campanha."))
        # Encerra campanhas enviadas há mais de 14 dias
        old = now - timedelta(days=14)
        self.search([("state", "=", "sent"), ("date_sent", "<", old)]).write({"state": "done"})
        return True

    def render_message(self, partner, template=None):
        """Substitui as variáveis do template para um cliente."""
        self.ensure_one()
        return self.env["sp.message"]._render_text(template or self.message_template, partner, self)
