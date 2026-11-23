# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SpMenuCategory(models.Model):
    _name = "sp.menu.category"
    _description = "Categoria do cardápio"
    _order = "sequence, name"

    name = fields.Char("Nome", required=True)
    sequence = fields.Integer("Sequência", default=10)
    restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", required=True, ondelete="cascade", index=True,
                                    default=lambda self: self.env["sp.restaurant"]._get_user_restaurants()[:1])
    product_ids = fields.One2many("product.template", "sp_menu_category_id", string="Itens")
    product_count = fields.Integer("Nº de itens", compute="_compute_product_count")

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    sp_restaurant_id = fields.Many2one("sp.restaurant", string="Restaurante", index=True, ondelete="cascade",
                                       default=lambda self: self.env["sp.restaurant"]._get_user_restaurants()[:1]
                                       if self.env.context.get("default_sp_is_menu_item") else False)
    sp_menu_category_id = fields.Many2one("sp.menu.category", string="Categoria do cardápio",
                                          domain="[('restaurant_id', '=', sp_restaurant_id)]")
    sp_available = fields.Boolean("Disponível no cardápio", default=True)
    sp_highlight = fields.Boolean("Destaque", default=False)
    sp_kind = fields.Selection([
        ("main", "Prato principal"), ("side", "Acompanhamento"), ("drink", "Bebida"),
        ("dessert", "Sobremesa"), ("combo", "Combo"),
    ], string="Tipo no cardápio", default="main")
    sp_serves = fields.Integer("Serve (pessoas)", default=1)
    sp_tags = fields.Char("Tags do cardápio", help="Ex.: picante, vegetariano, mais vendido")
    sp_sold_qty_90d = fields.Integer("Vendidos (90 dias)", readonly=True)
    sp_revenue_90d = fields.Float("Receita (90 dias)", readonly=True)
    sp_pair_product_id = fields.Many2one("product.template", "Combina com",
                                         domain="[('sp_restaurant_id', '=', sp_restaurant_id)]",
                                         help="Sugestão manual de acompanhamento (o motor também calcula automaticamente).")

    @api.onchange("sp_restaurant_id")
    def _onchange_sp_restaurant_id(self):
        if self.sp_restaurant_id:
            self.type = "consu"
            self.sale_ok = True
            self.purchase_ok = False
