# -*- coding: utf-8 -*-
{
    "name": "SalesPilot - CRM e Retenção para Restaurantes de Delivery",
    "summary": "CRM de relacionamento, matriz RFV, réguas de WhatsApp/SMS, cardápio digital "
               "com recomendações e cobrança por sucesso para pequenos restaurantes de delivery.",
    "description": """
Plataforma de CRM e retenção para pizzarias, hamburguerias, temakerias e outros
pequenos restaurantes de delivery, construída sobre o Odoo Community.

- Base de clientes com matriz RFV (Recência, Frequência, Valor) e segmentação automática
- Perfil de consumo: produto favorito, dia e horário habitual, intervalo típico entre pedidos
- Alertas de "red flag" quando um cliente ativo reduz a recorrência
- Campanhas e réguas automáticas (aniversário, lembrete de hábito, reativação, pós-compra)
- Cardápio digital público com identificação por telefone, recomendações e upsell
- Atribuição de pedidos às campanhas (jornada WhatsApp -> cardápio -> pedido)
- Cobrança por sucesso: mensalidade + % sobre a receita rastreada
- Pipeline de prospecção de restaurantes (CRM) com qualificação prévia
""",
    "version": "18.0.1.0.0",
    "category": "Sales/CRM",
    "author": "SalesPilot",
    "license": "LGPL-3",
    "website": "https://salespilot.com.br",
    "depends": ["base", "web", "mail", "contacts", "product", "crm"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence_data.xml",
        "data/cron_data.xml",
        "data/crm_data.xml",
        "views/restaurant_views.xml",
        "views/partner_views.xml",
        "views/product_views.xml",
        "views/order_views.xml",
        "views/campaign_views.xml",
        "views/message_views.xml",
        "views/automation_views.xml",
        "views/alert_views.xml",
        "views/insight_views.xml",
        "views/billing_views.xml",
        "views/crm_lead_views.xml",
        "views/dashboard_views.xml",
        "wizards/send_message_wizard_views.xml",
        "views/menu_templates.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "salespilot_restaurant/static/src/dashboard/**/*",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
}
