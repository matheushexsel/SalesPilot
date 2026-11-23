# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError

ORDER_CHANNELS = [
    ("menu", "Cardápio digital"),
    ("whatsapp", "WhatsApp"),
    ("ifood", "iFood"),
    ("phone", "Telefone"),
    ("counter", "Balcão"),
]

PAYMENT_METHODS = [
    ("pix", "Pix"),
    ("online_card", "Cartão online (simulado)"),
    ("apple_pay", "Apple Pay / Google Pay (simulado)"),
    ("card_delivery", "Cartão na entrega"),
    ("cash", "Dinheiro"),
    ("ifood", "Pago no iFood"),
]

ORDER_STATES = [
    ("draft", "Rascunho"),
    ("confirmed", "Confirmado"),
    ("preparing", "Em preparo"),
    ("delivering", "Saiu para entrega"),
    ("delivered", "Entregue"),
    ("cancelled", "Cancelado"),
]
ACTIVE_STATES = ("confirmed", "preparing", "delivering", "delivered")


class SpOrder(models.Model):
    _name = "sp.order"
    _description = "Pedido de delivery"
    _inherit = ["mail.thread"]
    _order = "date_order desc, id desc"

    name = fields.Char("Número", required=True, copy=False, readonly=True, default=lambda self: _("Novo"))
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, index=True, ondelete="restrict",
                                    default=lambda self: self.env["sp.restaurant"]._get_user_restaurants()[:1])
    partner_id = fields.Many2one("res.partner", "Cliente", required=True, index=True,
                                 domain="[('sp_restaurant_id', '=', restaurant_id)]")
    date_order = fields.Datetime("Data do pedido", required=True, default=fields.Datetime.now, index=True)
    channel = fields.Selection(ORDER_CHANNELS, string="Canal", required=True, default="whatsapp", index=True)
    from_menu = fields.Boolean("Feito pelo cardápio digital", default=False, readonly=True, index=True,
                               help="Marcado apenas pelo próprio cardápio digital; é o que conta como jornada rastreada.")
    state = fields.Selection(ORDER_STATES, string="Status", default="draft", required=True, tracking=True, index=True)
    payment_method = fields.Selection(PAYMENT_METHODS, "Pagamento", default="pix")
    payment_status = fields.Selection([("pending", "Pendente"), ("paid", "Pago"), ("refunded", "Estornado")], string="Pagamento (status)",
                                      default="pending", tracking=True)
    line_ids = fields.One2many("sp.order.line", "order_id", "Itens", copy=True)
    amount_subtotal = fields.Float("Subtotal", compute="_compute_amounts", store=True)
    delivery_fee = fields.Float("Taxa de entrega", default=0.0)
    discount_amount = fields.Float("Desconto", default=0.0)
    amount_total = fields.Float("Total", compute="_compute_amounts", store=True)
    currency_id = fields.Many2one(related="restaurant_id.currency_id")
    delivery_address = fields.Char("Endereço de entrega")
    customer_notes = fields.Text("Observações do cliente")
    coupon_code = fields.Char("Cupom")
    tracking_token = fields.Char("Token de rastreio", copy=False, default=lambda self: secrets.token_urlsafe(8))

    # Atribuição / jornada SalesPilot
    campaign_id = fields.Many2one("sp.campaign", "Campanha de origem", index=True)
    message_id = fields.Many2one("sp.message", "Mensagem de origem")
    automation_id = fields.Many2one("sp.automation", "Régua de origem")
    attributed = fields.Boolean("Atribuído a campanha", compute="_compute_attributed", store=True)
    tracked = fields.Boolean("Jornada rastreada", compute="_compute_attributed", store=True,
                             help="Pedido feito pelo cardápio digital SalesPilot (base da taxa de sucesso).")
    recommendation_accepted = fields.Boolean("Aceitou recomendação", default=False,
                                             help="O cliente adicionou um item sugerido pelo motor de recomendação.")
    weekday = fields.Integer("Dia da semana", compute="_compute_time_parts", store=True)
    hour = fields.Integer("Hora", compute="_compute_time_parts", store=True)
    item_summary = fields.Char("Resumo dos itens", compute="_compute_item_summary")

    @api.depends("line_ids.price_subtotal", "delivery_fee", "discount_amount")
    def _compute_amounts(self):
        for order in self:
            order.amount_subtotal = sum(order.line_ids.mapped("price_subtotal"))
            order.amount_total = max(order.amount_subtotal + order.delivery_fee - order.discount_amount, 0.0)

    @api.depends("campaign_id", "from_menu", "automation_id")
    def _compute_attributed(self):
        for order in self:
            order.attributed = bool(order.campaign_id or order.automation_id)
            order.tracked = order.from_menu or order.attributed

    @api.constrains("discount_amount", "delivery_fee")
    def _check_amounts(self):
        for order in self:
            if order.discount_amount < 0 or order.delivery_fee < 0:
                raise UserError(_("Desconto e taxa de entrega não podem ser negativos."))

    @api.depends("date_order")
    def _compute_time_parts(self):
        for order in self:
            if order.date_order:
                local = fields.Datetime.context_timestamp(order.with_context(tz="America/Sao_Paulo"), order.date_order)
                order.weekday = local.weekday()
                order.hour = local.hour
            else:
                order.weekday = 0
                order.hour = 0

    def _compute_item_summary(self):
        for order in self:
            order.item_summary = ", ".join(f"{int(l.qty)}x {l.product_id.name}" for l in order.line_ids[:4])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Novo")) == _("Novo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("sp.order") or _("Novo")
            if vals.get("partner_id") and not vals.get("delivery_address"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                vals["delivery_address"] = partner.contact_address_inline or partner.street
        orders = super().create(vals_list)
        orders.filtered(lambda o: o.state in ACTIVE_STATES)._on_confirmed()
        return orders

    def write(self, vals):
        before = {o.id: o.state for o in self}
        res = super().write(vals)
        if "state" in vals:
            newly = self.filtered(lambda o: o.state in ACTIVE_STATES and before.get(o.id) not in ACTIVE_STATES)
            newly._on_confirmed()
            if vals["state"] == "cancelled":
                self._refresh_partner_stats()
        return res

    def _on_confirmed(self):
        """Hook executado quando o pedido passa a contar para o RFV."""
        if not self:
            return
        first_timers = {}
        for order in self:
            if not order.partner_id.sp_is_customer:
                order.partner_id.sudo().sp_is_customer = True
            if not order.partner_id.sp_first_order_date and order.partner_id.id not in first_timers:
                first_timers[order.partner_id.id] = order
        self._refresh_partner_stats()
        self.env["sp.alert"].resolve_for_partners(self.mapped("partner_id"), reason="Cliente voltou a comprar")
        for order in first_timers.values():
            self.env["sp.automation"]._trigger_event("welcome", order.partner_id, order=order)

    def _refresh_partner_stats(self):
        if self.env.context.get("sp_skip_rfv"):
            return
        self.env["sp.rfv.engine"].sudo().recompute_partners(self.mapped("partner_id").sudo())

    # Transições
    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_prepare(self):
        self.write({"state": "preparing"})

    def action_deliver(self):
        self.write({"state": "delivering"})

    def action_delivered(self):
        self.write({"state": "delivered", "payment_status": "paid"})
        for order in self:
            self.env["sp.automation"]._trigger_event("post_purchase", order.partner_id, order=order)

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_set_paid(self):
        self.write({"payment_status": "paid"})

    def action_reset_draft(self):
        if any(o.state == "delivered" for o in self):
            raise UserError(_("Pedidos entregues não podem voltar para rascunho."))
        self.write({"state": "draft"})

    def unlink(self):
        partners = self.mapped("partner_id")
        res = super().unlink()
        self.env["sp.rfv.engine"].sudo().recompute_partners(partners.sudo())
        return res


class SpOrderLine(models.Model):
    _name = "sp.order.line"
    _description = "Item do pedido"
    _order = "order_id, id"

    order_id = fields.Many2one("sp.order", string="Pedido", required=True, ondelete="cascade", index=True)
    restaurant_id = fields.Many2one(related="order_id.restaurant_id", store=True, index=True)
    partner_id = fields.Many2one(related="order_id.partner_id", store=True, index=True)
    date_order = fields.Datetime(related="order_id.date_order", store=True)
    state = fields.Selection(related="order_id.state", store=True)
    product_id = fields.Many2one("product.product", "Produto", required=True,
                                 domain="[('product_tmpl_id.sp_restaurant_id', '=', parent.restaurant_id)]")
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True, index=True)
    qty = fields.Float("Qtd", default=1.0, required=True)
    price_unit = fields.Float("Preço unitário", required=True)
    price_subtotal = fields.Float("Subtotal", compute="_compute_subtotal", store=True)
    notes = fields.Char("Observação")
    recommended = fields.Boolean("Sugerido pelo SalesPilot", default=False)

    @api.constrains("qty", "price_unit")
    def _check_line(self):
        for line in self:
            if line.qty <= 0 or line.price_unit < 0:
                raise UserError(_("Quantidade deve ser positiva e o preço não pode ser negativo."))

    @api.depends("qty", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.qty * line.price_unit

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.lst_price
