# -*- coding: utf-8 -*-
import re
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

RFV_SEGMENTS = [
    ("champions", "Campeões"),
    ("loyal", "Clientes fiéis"),
    ("potential_loyal", "Potenciais fiéis"),
    ("new", "Novos clientes"),
    ("promising", "Promissores"),
    ("need_attention", "Precisam de atenção"),
    ("about_to_sleep", "Prestes a dormir"),
    ("at_risk", "Em risco"),
    ("cant_lose", "Não pode perder"),
    ("hibernating", "Hibernando"),
    ("lost", "Perdidos"),
    ("none", "Sem compras"),
]

WEEKDAYS = [
    ("0", "Segunda-feira"), ("1", "Terça-feira"), ("2", "Quarta-feira"), ("3", "Quinta-feira"),
    ("4", "Sexta-feira"), ("5", "Sábado"), ("6", "Domingo"),
]


def normalize_phone(phone):
    """Mantém só dígitos; adiciona DDI 55 quando faltar."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


class ResPartner(models.Model):
    _inherit = "res.partner"

    sp_restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", index=True, ondelete="cascade")
    sp_is_customer = fields.Boolean("Cliente de delivery", default=False, index=True)
    sp_whatsapp = fields.Char("WhatsApp", index=True, help="Número com DDD. Usado como identificador no cardápio digital.")
    sp_whatsapp_norm = fields.Char("WhatsApp (normalizado)", compute="_compute_whatsapp_norm", store=True, index=True)
    sp_birthday = fields.Date("Aniversário")
    sp_opt_in = fields.Boolean("Aceita mensagens (opt-in)", default=True)
    sp_source = fields.Selection([
        ("menu", "Cardápio digital"), ("whatsapp", "WhatsApp"), ("ifood", "iFood"),
        ("phone", "Telefone"), ("counter", "Balcão"), ("import", "Importação"), ("other", "Outro"),
    ], string="Origem do cadastro", default="menu")
    sp_delivery_notes = fields.Char("Referência / observações de entrega")
    sp_tags = fields.Char("Preferências (texto livre)", help="Ex.: sem cebola, gosta de picante, vegetariano")

    # ----- RFV e perfil de consumo (atualizados pelo motor sp.rfv.engine) -----
    sp_first_order_date = fields.Datetime("Primeiro pedido", readonly=True)
    sp_last_order_date = fields.Datetime("Último pedido", readonly=True)
    sp_recency_days = fields.Integer("Dias desde o último pedido", readonly=True)
    sp_frequency = fields.Integer("Pedidos na janela", readonly=True)
    sp_monetary = fields.Float("Valor na janela (R$)", readonly=True)
    sp_total_orders = fields.Integer("Total de pedidos", readonly=True)
    sp_ltv = fields.Float("LTV (R$)", readonly=True, help="Soma de tudo que o cliente já gastou.")
    sp_avg_ticket = fields.Float("Ticket médio (R$)", readonly=True)
    sp_r_score = fields.Integer("Score R", readonly=True)
    sp_f_score = fields.Integer("Score F", readonly=True)
    sp_v_score = fields.Integer("Score V", readonly=True)
    sp_fv_score = fields.Integer("Score FV", readonly=True, help="Média de frequência e valor (coluna da matriz RFV)")
    sp_rfv_score = fields.Char("RFV", readonly=True)
    sp_segment = fields.Selection(RFV_SEGMENTS, string="Segmento RFV", default="none", readonly=True, index=True)
    sp_segment_prev = fields.Selection(RFV_SEGMENTS, string="Segmento anterior", readonly=True)
    sp_segment_changed_date = fields.Date("Segmento alterado em", readonly=True)
    sp_typical_interval = fields.Float("Intervalo típico (dias)", readonly=True,
                                       help="Mediana dos dias entre pedidos consecutivos.")
    sp_next_order_expected = fields.Date("Próximo pedido esperado", readonly=True)
    sp_favorite_product_id = fields.Many2one("product.product", "Produto favorito", readonly=True)
    sp_favorite_weekday = fields.Selection(WEEKDAYS, "Dia habitual", readonly=True)
    sp_favorite_hour = fields.Integer("Hora habitual", readonly=True)
    sp_favorite_channel = fields.Selection([
        ("menu", "Cardápio digital"), ("whatsapp", "WhatsApp"), ("ifood", "iFood"),
        ("phone", "Telefone"), ("counter", "Balcão"),
    ], "Canal preferido", readonly=True)
    sp_churn_risk = fields.Selection([
        ("none", "Normal"), ("warning", "Atenção"), ("critical", "Crítico"),
    ], "Risco de perda", default="none", readonly=True, index=True)
    sp_recurrence_ratio = fields.Float("Atraso vs. intervalo típico", readonly=True,
                                       help="Dias sem comprar ÷ intervalo típico. >1,5 acende a red flag.")
    sp_profile_summary = fields.Text("Resumo do perfil", readonly=True)
    sp_last_message_date = fields.Datetime("Última mensagem enviada", readonly=True)

    sp_order_ids = fields.One2many("sp.order", "partner_id", string="Pedidos de delivery")
    sp_message_ids = fields.One2many("sp.message", "partner_id", string="Mensagens")
    sp_alert_ids = fields.One2many("sp.alert", "partner_id", string="Alertas")
    sp_order_count = fields.Integer("Nº de pedidos", compute="_compute_sp_counts")
    sp_message_count = fields.Integer("Nº de mensagens", compute="_compute_sp_counts")
    sp_birthday_soon = fields.Boolean("Aniversário nos próximos 7 dias", compute="_compute_birthday_soon",
                                      search="_search_birthday_soon")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if (res.get("sp_is_customer") or self.env.context.get("default_sp_is_customer")) and not res.get("sp_restaurant_id") \
                and "sp_restaurant_id" in fields_list:
            rest = self.env["sp.restaurant"]._get_user_restaurants()[:1]
            if rest:
                res["sp_restaurant_id"] = rest.id
        return res

    def _sp_is_restricted_user(self):
        """Usuário de restaurante (não admin SalesPilot, não superusuário)."""
        return not self.env.su and self.env.user.has_group("salespilot_restaurant.group_sp_user") and \
            not self.env.user.has_group("salespilot_restaurant.group_sp_admin")

    @api.model_create_multi
    def create(self, vals_list):
        if self._sp_is_restricted_user():
            allowed = set(self.env.user.sp_restaurant_ids.ids)
            for vals in vals_list:
                if vals.get("sp_restaurant_id") not in allowed:
                    raise AccessError(_("Usuários de restaurante só podem cadastrar clientes do próprio restaurante."))
        return super().create(vals_list)

    def write(self, vals):
        # Um usuário de restaurante só edita clientes do próprio restaurante e não pode "soltar"
        # ou transferir um cliente (perderia o isolamento). Reforço em Python além das regras de registro.
        if self._sp_is_restricted_user():
            allowed = set(self.env.user.sp_restaurant_ids.ids)
            for rec in self:
                if rec.sp_restaurant_id.id not in allowed:
                    raise AccessError(_("Você só pode editar clientes do seu restaurante."))
            if "sp_restaurant_id" in vals and vals["sp_restaurant_id"] not in allowed:
                raise AccessError(_("Somente o administrador SalesPilot pode mover um cliente de restaurante."))
        return super().write(vals)

    @api.depends("sp_whatsapp")
    def _compute_whatsapp_norm(self):
        for rec in self:
            rec.sp_whatsapp_norm = normalize_phone(rec.sp_whatsapp)

    def _compute_sp_counts(self):
        for rec in self:
            rec.sp_order_count = len(rec.sp_order_ids)
            rec.sp_message_count = len(rec.sp_message_ids)

    def _birthday_in_days(self, today=None):
        self.ensure_one()
        if not self.sp_birthday:
            return None
        today = today or fields.Date.context_today(self)
        try:
            nxt = self.sp_birthday.replace(year=today.year)
        except ValueError:  # 29/02
            nxt = date(today.year, 2, 28)
        if nxt < today:
            try:
                nxt = self.sp_birthday.replace(year=today.year + 1)
            except ValueError:
                nxt = date(today.year + 1, 2, 28)
        return (nxt - today).days

    def _compute_birthday_soon(self):
        for rec in self:
            days = rec._birthday_in_days()
            rec.sp_birthday_soon = days is not None and 0 <= days <= 7

    def _search_birthday_soon(self, operator, value):
        partners = self.search([("sp_is_customer", "=", True), ("sp_birthday", "!=", False)])
        ids = [p.id for p in partners if p.sp_birthday_soon]
        if (operator == "=" and value) or (operator == "!=" and not value):
            return [("id", "in", ids)]
        return [("id", "not in", ids)]

    # ------------------------------------------------------------------
    @api.model
    def sp_find_or_create_customer(self, restaurant, phone, name=None, extra=None):
        norm = normalize_phone(phone)
        partner = None
        if norm:
            # Trava por (restaurante, telefone) até o fim da transação: dois checkouts simultâneos
            # com o mesmo número novo não criam dois cadastros.
            self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"sp_customer:{restaurant.id}:{norm}",))
            partner = self.search([("sp_restaurant_id", "=", restaurant.id), ("sp_whatsapp_norm", "=", norm)], limit=1)
        if not partner:
            vals = {
                "name": name or f"Cliente {phone}",
                "sp_restaurant_id": restaurant.id,
                "sp_is_customer": True,
                "sp_whatsapp": phone,
                "phone": phone,
                "sp_source": "menu",
            }
            vals.update(extra or {})
            partner = self.create(vals)
        elif name and partner.name.startswith("Cliente "):
            partner.name = name
        return partner

    def action_view_sp_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "sp.order", "name": "Pedidos",
            "view_mode": "list,form", "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id, "default_restaurant_id": self.sp_restaurant_id.id},
        }

    def action_sp_send_message(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "sp.send.message.wizard", "name": "Enviar mensagem",
            "view_mode": "form", "views": [(False, "form")], "target": "new",
            "context": {"default_partner_ids": [(6, 0, self.ids)], "default_restaurant_id": self.sp_restaurant_id.id},
        }

    def action_sp_recompute(self):
        self.env["sp.rfv.engine"].sudo().recompute_partners(self.sudo())
        return True
