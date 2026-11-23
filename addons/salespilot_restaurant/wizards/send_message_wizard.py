# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.campaign import DEFAULT_TEMPLATES


class SpSendMessageWizard(models.TransientModel):
    _name = "sp.send.message.wizard"
    _description = "Enviar mensagem para clientes"

    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True,
                                    default=lambda self: self._default_restaurant())
    partner_ids = fields.Many2many("res.partner", string="Clientes", required=True)
    channel = fields.Selection([("whatsapp", "WhatsApp"), ("sms", "SMS"), ("email", "E-mail")], string="Canal", default="whatsapp", required=True)
    preset = fields.Selection(string="Modelo de mensagem", selection=[
        ("reactivation", "Reativação"), ("habit", "Lembrete de hábito"), ("birthday", "Aniversário"),
        ("vip", "VIP"), ("welcome", "Boas-vindas"), ("manual", "Livre"),
    ], default="manual")
    body = fields.Text("Mensagem", required=True, default=lambda self: DEFAULT_TEMPLATES["manual"])
    coupon_code = fields.Char("Cupom")
    discount_pct = fields.Float("Desconto (%)")
    alert_id = fields.Many2one("sp.alert", string="Alerta")
    campaign_id = fields.Many2one("sp.campaign", "Atribuir à campanha")
    preview = fields.Text("Prévia (1º cliente)", compute="_compute_preview")

    @api.model
    def _default_restaurant(self):
        partner_ids = self.env.context.get("default_partner_ids") or self.env.context.get("active_ids") or []
        if partner_ids and isinstance(partner_ids, list) and not isinstance(partner_ids[0], (list, tuple)):
            partners = self.env["res.partner"].browse(partner_ids)
            if partners.sp_restaurant_id:
                return partners.sp_restaurant_id[:1]
        return self.env["sp.restaurant"]._get_user_restaurants()[:1]

    @api.onchange("preset")
    def _onchange_preset(self):
        if self.preset:
            self.body = DEFAULT_TEMPLATES.get(self.preset, DEFAULT_TEMPLATES["manual"])
            presets = {"reactivation": ("VOLTEI15", 15), "birthday": ("NIVER20", 20), "vip": ("VIP10", 10), "welcome": ("BEMVINDO10", 10)}
            if self.preset in presets:
                self.coupon_code, self.discount_pct = presets[self.preset]

    @api.depends("body", "partner_ids", "coupon_code", "discount_pct")
    def _compute_preview(self):
        for wiz in self:
            partner = wiz.partner_ids[:1]
            if not partner:
                wiz.preview = ""
                continue
            extra = {"cupom": wiz.coupon_code or "", "desconto": f"{wiz.discount_pct:g}% de desconto" if wiz.discount_pct else "um mimo"}
            wiz.preview = self.env["sp.message"]._render_text(wiz.body, partner, extra=extra)

    def action_send(self):
        self.ensure_one()
        Message = self.env["sp.message"]
        msgs = Message
        for partner in self.partner_ids:
            if self.channel in ("whatsapp", "sms") and not partner.sp_whatsapp:
                continue
            token = Message._fields["tracking_token"].default(Message)
            extra = {"token": token, "cupom": self.coupon_code or "",
                     "desconto": f"{self.discount_pct:g}% de desconto" if self.discount_pct else "um mimo"}
            msgs |= Message.create({
                "restaurant_id": self.restaurant_id.id, "partner_id": partner.id, "channel": self.channel,
                "campaign_id": self.campaign_id.id,
                "to": partner.email if self.channel == "email" else partner.sp_whatsapp,
                "body": Message._render_text(self.body, partner, campaign=self.campaign_id, extra=extra),
                "tracking_token": token, "coupon_code": self.coupon_code,
            })
        if not msgs:
            raise UserError(_("Nenhum cliente com contato válido para o canal escolhido."))
        msgs.action_send()
        if self.alert_id:
            self.alert_id.write({"message_id": msgs[:1].id, "state": "done", "resolution": "Mensagem enviada",
                                 "date_resolved": fields.Datetime.now()})
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Mensagens enviadas"), "type": "success", "sticky": False,
                       "message": _("%s mensagem(ns) colocada(s) na fila (provedor: simulação).", len(msgs)),
                       "next": {"type": "ir.actions.act_window_close"}},
        }
