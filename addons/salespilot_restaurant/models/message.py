# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .rfv_engine import WEEKDAY_NAMES

MESSAGE_STATES = [
    ("queued", "Na fila"), ("sent", "Enviada"), ("delivered", "Entregue"), ("read", "Lida"),
    ("failed", "Falhou"), ("skipped", "Ignorada"),
]


class SpMessage(models.Model):
    """Caixa de saída. Cada registro é uma mensagem individual (WhatsApp/SMS/E-mail).

    No piloto o provedor é "Simulação": a mensagem é marcada como enviada/entregue sem
    sair do sistema. A integração oficial com a API do WhatsApp (Meta Cloud API) entra
    aqui depois, implementando `_provider_send_meta`.
    """
    _name = "sp.message"
    _description = "Mensagem enviada ao cliente"
    _order = "create_date desc, id desc"

    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", "Cliente", required=True, index=True, ondelete="cascade")
    campaign_id = fields.Many2one("sp.campaign", "Campanha", index=True, ondelete="set null")
    automation_id = fields.Many2one("sp.automation", "Régua", index=True, ondelete="set null")
    channel = fields.Selection([("whatsapp", "WhatsApp"), ("sms", "SMS"), ("email", "E-mail")], string="Canal", required=True,
                               default="whatsapp")
    to = fields.Char("Destino", help="Número de WhatsApp/SMS ou e-mail")
    body = fields.Text("Conteúdo", required=True)
    state = fields.Selection(MESSAGE_STATES, string="Status", default="queued", index=True)
    provider = fields.Selection(string="Provedor", selection=[("simulation", "Simulação (piloto)"), ("meta", "WhatsApp Cloud API"),
                                 ("sms_gateway", "Gateway SMS"), ("mail", "E-mail Odoo")], default="simulation")
    provider_ref = fields.Char("Ref. do provedor")
    error = fields.Char("Erro")
    date_sent = fields.Datetime("Enviada em")
    date_clicked = fields.Datetime("Clique em")
    clicked = fields.Boolean("Clicou no link", default=False, index=True)
    tracking_token = fields.Char("Token de rastreio", index=True, copy=False, default=lambda self: secrets.token_urlsafe(9))
    tracking_url = fields.Char("Link rastreado", compute="_compute_tracking_url")
    coupon_code = fields.Char("Cupom")
    order_ids = fields.One2many("sp.order", "message_id", "Pedidos gerados")
    order_count = fields.Integer("Pedidos", compute="_compute_order_count")
    direction = fields.Selection([("out", "Enviada"), ("in", "Recebida")], string="Direção", default="out")

    _sql_constraints = [("tracking_token_unique", "unique(tracking_token)", "Token duplicado.")]

    @api.depends("partner_id", "channel", "create_date")
    def _compute_display_name(self):
        labels = dict(self._fields["channel"].selection)
        for rec in self:
            when = fields.Datetime.context_timestamp(rec, rec.create_date).strftime("%d/%m %H:%M") if rec.create_date else ""
            rec.display_name = f"{labels.get(rec.channel, rec.channel)} → {rec.partner_id.name or ''} ({when})"

    def _compute_tracking_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            rec.tracking_url = f"{base}/c/{rec.tracking_token}"

    def _compute_order_count(self):
        for rec in self:
            rec.order_count = len(rec.order_ids)

    # ------------------------------------------------------------------
    @api.model
    def _render_text(self, template, partner, campaign=None, automation=None, extra=None):
        restaurant = partner.sp_restaurant_id or (campaign and campaign.restaurant_id) or (automation and automation.restaurant_id)
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        token = (extra or {}).get("token", "")
        link = f"{base}/c/{token}" if token else (f"{base}/cardapio/{restaurant.slug}" if restaurant else "")
        discount = ""
        coupon = ""
        src = campaign or automation
        if src:
            coupon = src.coupon_code or ""
            if src.discount_pct:
                discount = f"{src.discount_pct:g}% de desconto"
            elif src.discount_value:
                discount = f"R$ {src.discount_value:,.2f} de desconto".replace(",", "v").replace(".", ",").replace("v", ".")
        fav = partner.sp_favorite_product_id.name or "pedido de sempre"
        weekday = WEEKDAY_NAMES[int(partner.sp_favorite_weekday)].capitalize() if partner.sp_favorite_weekday else "Hoje"
        values = {
            "nome": (partner.name or "").split(" ")[0],
            "nome_completo": partner.name or "",
            "produto_favorito": fav,
            "cupom": coupon,
            "desconto": discount or "um mimo",
            "link": link,
            "restaurante": restaurant.name if restaurant else "",
            "dia_semana": weekday,
            "dias_sem_pedir": str(partner.sp_recency_days or 0),
        }
        values.update(extra or {})
        text = template or ""
        for key, val in values.items():
            text = text.replace("{" + key + "}", str(val))
        return text

    @api.model
    def _prepare_from_campaign(self, campaign, partner):
        token = secrets.token_urlsafe(9)
        return {
            "restaurant_id": campaign.restaurant_id.id,
            "partner_id": partner.id,
            "campaign_id": campaign.id,
            "channel": campaign.channel,
            "to": partner.email if campaign.channel == "email" else partner.sp_whatsapp,
            "body": self._render_text(campaign.message_template, partner, campaign=campaign, extra={"token": token}),
            "tracking_token": token,
            "coupon_code": campaign.coupon_code,
        }

    @api.model
    def _prepare_from_automation(self, automation, partner, extra=None):
        token = secrets.token_urlsafe(9)
        ctx = dict(extra or {}, token=token)
        return {
            "restaurant_id": automation.restaurant_id.id,
            "partner_id": partner.id,
            "automation_id": automation.id,
            "channel": automation.channel,
            "to": partner.email if automation.channel == "email" else partner.sp_whatsapp,
            "body": self._render_text(automation.message_template, partner, automation=automation, extra=ctx),
            "tracking_token": token,
            "coupon_code": automation.coupon_code,
        }

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------
    def action_send(self):
        provider = self.env["ir.config_parameter"].sudo().get_param("salespilot.message_provider", "simulation")
        for msg in self.filtered(lambda m: m.state in ("queued", "failed")):
            if not msg.to:
                msg.write({"state": "skipped", "error": "Cliente sem número/e-mail"})
                continue
            if not msg.partner_id.sp_opt_in and msg.direction == "out":
                msg.write({"state": "skipped", "error": "Cliente sem opt-in"})
                continue
            handler = getattr(msg, f"_provider_send_{provider}", None)
            if not handler:
                msg.write({"state": "failed", "error": f"Provedor '{provider}' não configurado"})
                continue
            try:
                handler()
                msg.partner_id.sp_last_message_date = fields.Datetime.now()
            except Exception as exc:  # pragma: no cover
                msg.write({"state": "failed", "error": str(exc)[:200]})
        return True

    def _provider_send_simulation(self):
        """Piloto: não envia nada de verdade. Marca como entregue para alimentar os relatórios."""
        self.write({"state": "delivered", "provider": "simulation", "date_sent": fields.Datetime.now(),
                    "provider_ref": f"SIM-{self.id}"})

    def _provider_send_meta(self):
        raise UserError(_("A integração com a WhatsApp Cloud API (Meta) não faz parte deste piloto. "
                          "Mantenha o provedor em 'simulation' em Configurações > Parâmetros do sistema."))

    def _provider_send_sms_gateway(self):
        raise UserError(_("Gateway de SMS não configurado neste piloto."))

    def _provider_send_mail(self):
        self.ensure_one()
        if not self.partner_id.email:
            raise UserError(_("Cliente sem e-mail."))
        self.env["mail.mail"].sudo().create({
            "subject": f"{self.restaurant_id.name}",
            "body_html": f"<p>{self.body}</p>",
            "email_to": self.partner_id.email,
        }).send(raise_exception=False)
        self.write({"state": "sent", "provider": "mail", "date_sent": fields.Datetime.now()})

    def register_click(self):
        for msg in self:
            if not msg.clicked:
                msg.write({"clicked": True, "date_clicked": fields.Datetime.now(), "state": "read"})
        return True

    def action_open_tracking(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.tracking_url, "target": "new"}

    def action_retry(self):
        self.filtered(lambda m: m.state in ("failed", "skipped")).write({"state": "queued", "error": False})
        return self.action_send()
