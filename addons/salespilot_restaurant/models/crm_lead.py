# -*- coding: utf-8 -*-
"""Prospecção de restaurantes (pipeline comercial do SalesPilot) com qualificação prévia."""
from odoo import api, fields, models, _

SEGMENTS = [
    ("hamburgueria", "Hamburgueria"), ("pizzaria", "Pizzaria"), ("temakeria", "Temakeria / Japonês"),
    ("acai", "Açaí / Sobremesas"), ("marmitaria", "Marmitaria"), ("outro", "Outro"),
]


class CrmLead(models.Model):
    _inherit = "crm.lead"

    sp_is_restaurant = fields.Boolean("Prospect de restaurante", default=False)
    sp_segment = fields.Selection(SEGMENTS, "Segmento")
    sp_google_rating = fields.Float("Nota no Google", digits=(2, 1))
    sp_google_reviews = fields.Integer("Avaliações no Google")
    sp_on_ifood = fields.Boolean("Está no iFood")
    sp_ifood_rating = fields.Float("Nota no iFood", digits=(2, 1))
    sp_instagram = fields.Char("Instagram")
    sp_instagram_followers = fields.Integer("Seguidores")
    sp_has_own_menu = fields.Boolean("Já tem cardápio próprio / site")
    sp_uses_whatsapp_orders = fields.Boolean("Recebe pedidos por WhatsApp", default=True)
    sp_monthly_orders_est = fields.Integer("Pedidos/mês (estimado)")
    sp_avg_ticket_est = fields.Float("Ticket médio estimado (R$)")
    sp_neighborhood = fields.Char("Bairro")
    sp_qualification_score = fields.Integer("Score de qualificação", compute="_compute_qualification", store=True)
    sp_qualification_notes = fields.Text("Qualificação prévia (IA)", compute="_compute_qualification", store=True)
    sp_potential_mrr = fields.Float("Receita potencial/mês (R$)", compute="_compute_qualification", store=True,
                                    help="Mensalidade + taxa de sucesso estimada sobre a receita de delivery.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get("sp_is_restaurant") or self.env.context.get("default_sp_is_restaurant"):
            team = self.env.ref("salespilot_restaurant.crm_team_salespilot", raise_if_not_found=False)
            if team and "team_id" in fields_list:
                res["team_id"] = team.id
        return res

    @api.depends("sp_segment", "sp_google_rating", "sp_google_reviews", "sp_on_ifood", "sp_ifood_rating",
                 "sp_has_own_menu", "sp_uses_whatsapp_orders", "sp_monthly_orders_est", "sp_avg_ticket_est",
                 "sp_instagram_followers", "sp_is_restaurant")
    def _compute_qualification(self):
        for lead in self:
            if not lead.sp_is_restaurant:
                lead.sp_qualification_score = 0
                lead.sp_qualification_notes = False
                lead.sp_potential_mrr = 0
                continue
            score = 0
            reasons = []
            if lead.sp_segment in ("hamburgueria", "pizzaria", "temakeria"):
                score += 20
                reasons.append("segmento-alvo (alta recorrência de delivery)")
            elif lead.sp_segment:
                score += 8
            if lead.sp_google_reviews >= 300:
                score += 20
                reasons.append(f"base grande de clientes ({lead.sp_google_reviews} avaliações)")
            elif lead.sp_google_reviews >= 100:
                score += 12
                reasons.append("base de clientes relevante")
            if 4.0 <= lead.sp_google_rating <= 4.7:
                score += 10
                reasons.append("boa reputação com espaço para fidelizar")
            elif lead.sp_google_rating > 4.7:
                score += 6
            if lead.sp_on_ifood:
                score += 15
                reasons.append("paga comissão de marketplace hoje (dor clara)")
            if lead.sp_uses_whatsapp_orders:
                score += 10
                reasons.append("já vende pelo WhatsApp")
            if not lead.sp_has_own_menu:
                score += 10
                reasons.append("não tem cardápio próprio")
            if lead.sp_monthly_orders_est >= 600:
                score += 15
                reasons.append("volume alto de pedidos")
            elif lead.sp_monthly_orders_est >= 250:
                score += 10
            if lead.sp_instagram_followers >= 3000:
                score += 5
            lead.sp_qualification_score = min(score, 100)
            rev = (lead.sp_monthly_orders_est or 0) * (lead.sp_avg_ticket_est or 0)
            lead.sp_potential_mrr = 120.0 + rev * 0.4 * 0.01  # premissa: 40% da receita migra para a jornada rastreada
            tier = "QUENTE" if score >= 70 else "MORNO" if score >= 45 else "FRIO"
            lead.sp_qualification_notes = (
                f"Lead {tier} ({min(score, 100)}/100). " + ("Motivos: " + "; ".join(reasons) + ". " if reasons else "")
                + f"Receita de delivery estimada: R$ {rev:,.0f}/mês. Pitch: substituir ~23% de comissão por R$120 + 1%."
            ).replace(",", ".")

    def action_sp_qualify(self):
        """Recalcula a qualificação e registra no chatter (ponto de extensão para IA externa)."""
        for lead in self:
            lead._compute_qualification()
            lead._message_log(body=lead.sp_qualification_notes or _("Sem dados suficientes para qualificar."))
            if lead.sp_qualification_score >= 70:
                lead.priority = "3"
            elif lead.sp_qualification_score >= 45:
                lead.priority = "2"
        return True
