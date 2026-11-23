# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    sp_restaurant_ids = fields.Many2many("sp.restaurant", "sp_restaurant_users_rel", "user_id", "restaurant_id",
                                         string="Restaurantes (SalesPilot)")
