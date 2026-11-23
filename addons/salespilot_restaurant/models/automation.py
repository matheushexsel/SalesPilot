# -*- coding: utf-8 -*-
"""Réguas automáticas de relacionamento (aniversário, hábito, red flag, boas-vindas, pós-compra)."""
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

from .campaign import CHANNELS, DEFAULT_TEMPLATES
from .rfv_engine import TZ

TRIGGERS = [
    ("churn", "Red flag: queda de recorrência"),
    ("habit", "Lembrete de hábito (dia/horário habitual)"),
    ("birthday", "Aniversário"),
    ("welcome", "Boas-vindas (após o 1º pedido)"),
    ("post_purchase", "Pós-compra (pedido entregue)"),
    ("winback", "Reativação por dias sem pedir"),
    ("vip", "Virou Campeão (agradecimento VIP)"),
]


class SpAutomation(models.Model):
    _name = "sp.automation"
    _description = "Régua automática de relacionamento"
    _inherit = ["mail.thread"]
    _order = "sequence, id"

    name = fields.Char("Nome", required=True, tracking=True)
    sequence = fields.Integer("Sequência", default=10)
    active = fields.Boolean("Ativa", default=True, tracking=True)
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade",
                                    default=lambda self: self.env["sp.restaurant"]._get_user_restaurants()[:1])
    trigger = fields.Selection(TRIGGERS, string="Gatilho", required=True, default="churn")
    channel = fields.Selection(CHANNELS, string="Canal", required=True, default="whatsapp")
    message_template = fields.Text("Mensagem", required=True,
                                   help="Variáveis: {nome} {produto_favorito} {cupom} {desconto} {link} {restaurante} {dia_semana} {dias_sem_pedir}")
    coupon_code = fields.Char("Cupom")
    discount_pct = fields.Float("Desconto (%)")
    discount_value = fields.Float("Desconto (R$)")
    create_alert = fields.Boolean("Também gerar alerta para a equipe", default=True)
    send_message = fields.Boolean("Enviar mensagem automaticamente", default=True)

    # Parâmetros por gatilho
    churn_level = fields.Selection([("warning", "Atenção (1,5× o intervalo)"), ("critical", "Crítico (2,5× o intervalo)")],
                                   default="warning", string="Nível de risco")
    days_before = fields.Integer("Dias de antecedência", default=0, help="Aniversário: enviar N dias antes.")
    hours_before = fields.Integer("Horas antes do horário habitual", default=2)
    days_since_min = fields.Integer("Dias sem pedir (mín.)", default=30)
    days_since_max = fields.Integer("Dias sem pedir (máx.)", default=90)
    min_orders = fields.Integer("Mínimo de pedidos do cliente", default=1)
    segment_codes = fields.Char("Segmentos RFV", help="Códigos separados por vírgula. Vazio = todos.")
    send_hour_start = fields.Integer("Janela de envio: de (h)", default=10)
    send_hour_end = fields.Integer("Janela de envio: até (h)", default=21)
    cooldown_days = fields.Integer("Não repetir para o mesmo cliente por (dias)", default=14)
    last_run = fields.Datetime("Última execução", readonly=True)

    sp_message_ids = fields.One2many("sp.message", "automation_id")
    order_ids = fields.One2many("sp.order", "automation_id")
    sent_count = fields.Integer("Enviadas", compute="_compute_stats")
    order_count = fields.Integer("Pedidos atribuídos", compute="_compute_stats")
    attributed_revenue = fields.Float("Receita atribuída", compute="_compute_stats")

    def _compute_stats(self):
        for rec in self:
            rec.sent_count = len(rec.sp_message_ids.filtered(lambda m: m.state in ("sent", "delivered", "read")))
            orders = rec.order_ids.filtered(lambda o: o.state in ("confirmed", "preparing", "delivering", "delivered"))
            rec.order_count = len(orders)
            rec.attributed_revenue = sum(orders.mapped("amount_total"))

    @api.onchange("trigger")
    def _onchange_trigger(self):
        mapping = {"churn": "reactivation", "habit": "habit", "birthday": "birthday", "welcome": "welcome",
                   "post_purchase": "post_purchase", "winback": "reactivation", "vip": "vip"}
        if self.trigger and not self.message_template:
            self.message_template = DEFAULT_TEMPLATES.get(mapping.get(self.trigger, "manual"))

    # ------------------------------------------------------------------
    def _in_send_window(self, now_local):
        self.ensure_one()
        return self.send_hour_start <= now_local.hour < (self.send_hour_end or 24)

    def _recently_messaged(self, partner):
        """Respeita o cooldown da régua e o intervalo mínimo global do restaurante.

        Gatilhos por evento (boas-vindas, pós-compra) e aniversário ignoram o intervalo global:
        são mensagens esperadas pelo cliente e não devem ser engolidas por uma campanha recente."""
        self.ensure_one()
        now = fields.Datetime.now()
        global_days = self.restaurant_id.auto_message_cooldown_days or 0
        if global_days and self.trigger not in ("welcome", "post_purchase", "birthday") and \
                partner.sp_last_message_date and partner.sp_last_message_date > now - timedelta(days=global_days):
            return True
        if self.cooldown_days:
            since = now - timedelta(days=self.cooldown_days)
            if self.env["sp.message"].search_count([("automation_id", "=", self.id), ("partner_id", "=", partner.id),
                                                    ("create_date", ">=", since)]):
                return True
        return False

    def _base_domain(self):
        self.ensure_one()
        domain = [("sp_restaurant_id", "=", self.restaurant_id.id), ("sp_is_customer", "=", True),
                  ("sp_opt_in", "=", True), ("sp_total_orders", ">=", self.min_orders or 0)]
        codes = [c.strip() for c in (self.segment_codes or "").split(",") if c.strip()]
        if codes:
            domain.append(("sp_segment", "in", codes))
        return domain

    def _candidates(self, now_local):
        """Clientes elegíveis agora para gatilhos avaliados por cron."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        dom = self._base_domain()
        if self.trigger == "churn":
            levels = ("warning", "critical") if self.churn_level == "warning" else ("critical",)
            return Partner.search(dom + [("sp_churn_risk", "in", levels)])
        if self.trigger == "winback":
            dom += [("sp_recency_days", ">=", self.days_since_min or 0)]
            if self.days_since_max:
                dom += [("sp_recency_days", "<=", self.days_since_max)]
            return Partner.search(dom)
        if self.trigger == "habit":
            target = now_local + timedelta(hours=self.hours_before or 0)
            return Partner.search(dom + [("sp_favorite_weekday", "=", str(target.weekday())),
                                         ("sp_favorite_hour", "=", target.hour),
                                         ("sp_churn_risk", "!=", "critical")])
        if self.trigger == "birthday":
            partners = Partner.search(dom + [("sp_birthday", "!=", False)])
            return partners.filtered(lambda p: p._birthday_in_days(now_local.date()) == (self.days_before or 0))
        if self.trigger == "vip":
            recent = now_local.date() - timedelta(days=14)
            return Partner.search(dom + [("sp_segment", "=", "champions"), ("sp_segment_prev", "not in", ("champions", "none", False)),
                                         ("sp_segment_changed_date", ">=", recent)])
        return Partner

    def _fire(self, partner, extra=None, order=None):
        """Dispara a régua para um cliente: mensagem (fila de saída) e/ou alerta."""
        self.ensure_one()
        Message = self.env["sp.message"]
        created = Message
        if self.send_message and not self._recently_messaged(partner):
            created = Message.create(Message._prepare_from_automation(self, partner, extra))
            created.action_send()
        if self.create_alert:
            self.env["sp.alert"].create_from_automation(self, partner, created)
        return created

    @api.model
    def cron_run(self):
        now_local = datetime.now(TZ)
        for auto in self.search([("trigger", "in", ("churn", "winback", "habit", "birthday", "vip"))]):
            if not auto._in_send_window(now_local):
                continue
            # Gatilhos diários rodam uma vez por dia; o de hábito roda a cada hora
            if auto.trigger != "habit" and auto.last_run and \
                    fields.Datetime.context_timestamp(auto.with_context(tz="America/Sao_Paulo"), auto.last_run).date() == now_local.date():
                continue
            for partner in auto._candidates(now_local):
                try:
                    with self.env.cr.savepoint():
                        auto._fire(partner)
                except Exception:  # pragma: no cover - um cliente com problema não trava a régua
                    _logger.exception("Régua %s falhou para o cliente %s", auto.name, partner.id)
            auto.last_run = fields.Datetime.now()
        return True

    @api.model
    def _trigger_event(self, event, partner, order=None):
        """Eventos disparados pelo fluxo de pedidos (welcome, post_purchase)."""
        if self.env.context.get("sp_skip_automations") or not partner.sp_restaurant_id:
            return
        autos = self.search([("trigger", "=", event), ("restaurant_id", "=", partner.sp_restaurant_id.id)])
        for auto in autos:
            if partner.sp_opt_in:
                auto._fire(partner, extra={"pedido": order.name if order else ""}, order=order)

    def action_run_now(self):
        now_local = datetime.now(TZ)
        for auto in self:
            count = 0
            for partner in auto._candidates(now_local):
                auto._fire(partner)
                count += 1
            auto.last_run = fields.Datetime.now()
            auto._message_log(body=_("Régua executada manualmente: %s cliente(s) elegíveis.", count))
        return True

    def action_preview_candidates(self):
        self.ensure_one()
        now_local = datetime.now(TZ)
        return {"type": "ir.actions.act_window", "res_model": "res.partner", "name": _("Clientes elegíveis agora"),
                "view_mode": "list,form", "domain": [("id", "in", self._candidates(now_local).ids)]}

    def action_view_messages(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "sp.message", "name": _("Mensagens da régua"),
                "view_mode": "list,form", "domain": [("automation_id", "=", self.id)]}
