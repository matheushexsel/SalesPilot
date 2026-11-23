# -*- coding: utf-8 -*-
import re
import unicodedata
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def slugify(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "restaurante"


class SpRestaurant(models.Model):
    _name = "sp.restaurant"
    _description = "Restaurante (cliente SalesPilot)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char("Nome do restaurante", required=True, tracking=True)
    slug = fields.Char("Slug do cardápio", required=True, copy=False,
                       help="Identificador usado na URL pública do cardápio: /cardapio/<slug>")
    active = fields.Boolean("Ativo", default=True)
    segment = fields.Selection([
        ("hamburgueria", "Hamburgueria"),
        ("pizzaria", "Pizzaria"),
        ("temakeria", "Temakeria / Japonês"),
        ("acai", "Açaí / Sobremesas"),
        ("marmitaria", "Marmitaria"),
        ("outro", "Outro"),
    ], string="Segmento", default="hamburgueria", required=True)
    tagline = fields.Char("Frase de apresentação", help="Aparece no topo do cardápio digital.")
    logo = fields.Image("Logo", max_width=512, max_height=512)
    color_primary = fields.Char("Cor principal", default="#E63946")
    whatsapp = fields.Char("WhatsApp do restaurante")
    phone = fields.Char("Telefone")
    email = fields.Char("E-mail")
    street = fields.Char("Endereço")
    city = fields.Char("Cidade", default="São Paulo")
    state_code = fields.Char("UF", default="SP", size=2)
    opening_hours = fields.Char("Horário de funcionamento", default="Ter a Dom, 18h às 23h30")
    delivery_fee = fields.Float("Taxa de entrega padrão (R$)", default=6.0)
    min_order = fields.Float("Pedido mínimo (R$)", default=25.0)
    avg_prep_minutes = fields.Integer("Tempo médio de preparo (min)", default=40)
    currency_id = fields.Many2one("res.currency", string="Moeda", default=lambda self: self.env.ref("base.BRL", raise_if_not_found=False)
                                  or self.env.company.currency_id)
    company_id = fields.Many2one("res.company", string="Empresa", default=lambda self: self.env.company)

    # Parâmetros do motor RFV / churn
    rfv_window_days = fields.Integer("Janela RFV (dias)", default=180,
                                     help="Período considerado para Frequência e Valor.")
    churn_warning_factor = fields.Float("Fator de alerta de recorrência", default=1.5,
                                        help="Alerta quando dias sem comprar > fator × intervalo típico do cliente.")
    churn_critical_factor = fields.Float("Fator crítico de recorrência", default=2.5)
    auto_message_cooldown_days = fields.Integer("Intervalo mínimo entre mensagens automáticas (dias)", default=5)

    # Plano SalesPilot
    plan_monthly_fee = fields.Float("Mensalidade (R$)", default=120.0)
    plan_success_fee_pct = fields.Float("Taxa de sucesso (%)", default=1.0,
                                        help="Percentual cobrado sobre a receita rastreada pela jornada SalesPilot.")
    marketplace_fee_reference_pct = fields.Float("Taxa de marketplace de referência (%)", default=23.0,
                                                 help="Usado só para comparar a economia com marketplaces (iFood etc.).")

    # Relacionamentos / contadores
    user_ids = fields.Many2many("res.users", "sp_restaurant_users_rel", "restaurant_id", "user_id",
                                string="Usuários com acesso")
    customer_count = fields.Integer("Clientes", compute="_compute_counts")
    order_count = fields.Integer("Pedidos", compute="_compute_counts")
    product_count = fields.Integer("Itens do cardápio", compute="_compute_counts")
    campaign_count = fields.Integer("Campanhas", compute="_compute_counts")
    open_alert_count = fields.Integer("Alertas abertos", compute="_compute_counts")
    revenue_30d = fields.Float("Receita 30 dias", compute="_compute_counts")
    menu_url = fields.Char("URL do cardápio", compute="_compute_menu_url")
    last_rfv_run = fields.Datetime("Último cálculo RFV", readonly=True)
    rfv_value_thresholds = fields.Json("Limiares de Valor (quintis)", readonly=True)

    _sql_constraints = [
        ("slug_unique", "unique(slug)", "Já existe um restaurante com este slug."),
    ]

    @api.constrains("slug")
    def _check_slug(self):
        for rec in self:
            if not re.match(r"^[a-z0-9-]+$", rec.slug or ""):
                raise ValidationError(_("O slug deve conter apenas letras minúsculas, números e hífens."))

    @api.onchange("name")
    def _onchange_name_slug(self):
        for rec in self:
            if rec.name and not rec.slug:
                rec.slug = slugify(rec.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") and not vals.get("slug"):
                vals["slug"] = slugify(vals["name"])
        return super().create(vals_list)

    def _compute_menu_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            rec.menu_url = f"{base}/cardapio/{rec.slug}"

    def _compute_counts(self):
        since = fields.Datetime.now() - timedelta(days=30)
        for rec in self:
            rec.customer_count = self.env["res.partner"].search_count([("sp_restaurant_id", "=", rec.id)])
            rec.order_count = self.env["sp.order"].search_count([("restaurant_id", "=", rec.id)])
            rec.product_count = self.env["product.template"].search_count([("sp_restaurant_id", "=", rec.id)])
            rec.campaign_count = self.env["sp.campaign"].search_count([("restaurant_id", "=", rec.id)])
            rec.open_alert_count = self.env["sp.alert"].search_count(
                [("restaurant_id", "=", rec.id), ("state", "=", "open")])
            orders = self.env["sp.order"].search([("restaurant_id", "=", rec.id),
                                                  ("state", "in", ("confirmed", "preparing", "delivering", "delivered")),
                                                  ("date_order", ">=", since)])
            rec.revenue_30d = sum(orders.mapped("amount_total"))

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------
    def action_recompute_rfv(self):
        # Roda como superusuário: o cálculo grava em clientes, produtos, insights e alertas,
        # e operadores do restaurante só têm leitura em parte desses modelos.
        env = self.env(su=True)
        env["sp.rfv.engine"].recompute(self.sudo())
        env["sp.insight"].generate_for(self.sudo())
        env["sp.alert"].scan(self.sudo())
        return True

    def action_open_menu(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"/cardapio/{self.slug}", "target": "new"}

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "salespilot_dashboard",
            "name": _("Dashboard - %s", self.name),
            "context": {"default_restaurant_id": self.id},
        }

    def _open_records(self, model, name, domain=None, views=None):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": model,
            "name": name,
            "view_mode": "list,form",
            "domain": [("restaurant_id" if model != "res.partner" and model != "product.template"
                        else ("sp_restaurant_id"), "=", self.id)] + (domain or []),
            "context": {"default_restaurant_id": self.id, "default_sp_restaurant_id": self.id,
                        "search_default_restaurant_id": self.id},
        }

    def action_view_customers(self):
        return self._open_records("res.partner", _("Clientes"), [("sp_is_customer", "=", True)])

    def action_view_orders(self):
        return self._open_records("sp.order", _("Pedidos"))

    def action_view_products(self):
        return self._open_records("product.template", _("Cardápio"))

    def action_view_campaigns(self):
        return self._open_records("sp.campaign", _("Campanhas"))

    def action_view_alerts(self):
        return self._open_records("sp.alert", _("Alertas"), [("state", "=", "open")])

    # ------------------------------------------------------------------
    # Helpers usados pelo dashboard / controller
    # ------------------------------------------------------------------
    @api.model
    def _get_user_restaurants(self):
        """Restaurantes visíveis para o usuário atual (admin vê todos)."""
        if self.env.user.has_group("salespilot_restaurant.group_sp_admin"):
            return self.search([])
        return self.env.user.sp_restaurant_ids

    @api.model
    def get_dashboard_data(self, restaurant_id=None):
        restaurants = self._get_user_restaurants()
        restaurant = restaurants.filtered(lambda r: r.id == restaurant_id) if restaurant_id else restaurants[:1]
        if not restaurant:
            restaurant = restaurants[:1]  # id inválido ou sem acesso: cai no primeiro restaurante do usuário
        if not restaurant:
            return {"restaurants": [], "restaurant": None}
        restaurant = restaurant[:1]
        data = self.env["sp.rfv.engine"].dashboard_payload(restaurant)
        data["restaurants"] = [{"id": r.id, "name": r.name} for r in restaurants]
        return data
