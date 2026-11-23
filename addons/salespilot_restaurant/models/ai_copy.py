# -*- coding: utf-8 -*-
"""Assistente de texto para campanhas.

Funciona offline com um gerador de modelos por tipo de campanha e segmento. Se o parâmetro
de sistema `salespilot.llm_api_key` estiver preenchido, usa a API de um LLM para gerar
copy mais criativa (opcional; não faz parte do escopo testado do piloto).
"""
import json
import logging
import random

import requests

from odoo import api, models

from .campaign import DEFAULT_TEMPLATES
from .rfv_engine import SEGMENT_META

_logger = logging.getLogger(__name__)

TONE = {
    "hamburgueria": ("🍔", "aquele smash suculento"),
    "pizzaria": ("🍕", "aquela pizza quentinha"),
    "temakeria": ("🍣", "aquele temaki fresquinho"),
    "acai": ("🍧", "aquele açaí caprichado"),
    "marmitaria": ("🍱", "aquela marmita caseira"),
    "outro": ("😋", "aquele pedido de sempre"),
}

VARIANTS = {
    "reactivation": [
        "Oi {nome}! A gente notou que faz {dias_sem_pedir} dias que você não pede {emoji} Sentimos falta! "
        "Use {cupom} e ganhe {desconto} no seu {produto_favorito}: {link}",
        "{nome}, {prato} tá com saudade de você {emoji} Volta com {desconto} usando o cupom {cupom}: {link}",
    ],
    "habit": [
        "{nome}, {dia_semana} chegou {emoji} Seu {produto_favorito} já pode sair em 1 toque: {link}",
        "Oi {nome}! Hoje é {dia_semana}: dia de {produto_favorito}? Já deixamos tudo separado 😉 {link}",
    ],
    "birthday": [
        "Feliz aniversário, {nome}! 🎂 Presente da casa: {desconto} com o cupom {cupom}. Comemora com a gente: {link}",
    ],
    "welcome": [
        "{nome}, valeu pelo primeiro pedido no {restaurante} {emoji} Na próxima tem {desconto} com {cupom}: {link}",
    ],
    "vip": [
        "{nome}, você é top 10% dos nossos clientes 🏆 Como agradecimento: {desconto} com {cupom} no próximo pedido. {link}",
    ],
    "launch": [
        "{nome}, novidade no {restaurante} {emoji} Olha o que acabou de entrar no cardápio: {link}",
    ],
    "post_purchase": [
        "{nome}, chegou tudo certinho? De 0 a 10, quanto você indicaria o {restaurante}? Sua resposta ajuda muito 🙏",
    ],
    "manual": [
        "Oi {nome}! {restaurante} com uma oferta especial pra você {emoji} {link}",
    ],
}


class SpAiCopy(models.AbstractModel):
    _name = "sp.ai.copy"
    _description = "Gerador de texto de campanhas"

    @api.model
    def campaign_copy(self, campaign):
        key = self.env["ir.config_parameter"].sudo().get_param("salespilot.llm_api_key")
        if key:
            try:
                text = self._llm_copy(campaign, key)
                if text:
                    return text
            except Exception as exc:  # pragma: no cover - fallback silencioso
                _logger.warning("Falha ao gerar copy via LLM: %s", exc)
        return self._local_copy(campaign)

    @api.model
    def _local_copy(self, campaign):
        emoji, prato = TONE.get(campaign.restaurant_id.segment or "outro", TONE["outro"])
        options = VARIANTS.get(campaign.campaign_type) or [DEFAULT_TEMPLATES.get(campaign.campaign_type, DEFAULT_TEMPLATES["manual"])]
        rnd = random.Random(campaign.id or 0)
        text = rnd.choice(options)
        return text.replace("{emoji}", emoji).replace("{prato}", prato)

    @api.model
    def _llm_copy(self, campaign, key):
        model = self.env["ir.config_parameter"].sudo().get_param("salespilot.llm_model", "claude-sonnet-5-5")
        segs = [c.strip() for c in (campaign.segment_codes or "").split(",") if c.strip()]
        seg_desc = "; ".join(f"{SEGMENT_META[s][0]}: {SEGMENT_META[s][2]}" for s in segs if s in SEGMENT_META) or "todos os clientes"
        prompt = (
            "Você escreve mensagens curtas de WhatsApp (máx. 300 caracteres) para um pequeno restaurante de delivery "
            f"brasileiro ({campaign.restaurant_id.segment}, '{campaign.restaurant_id.name}'). "
            f"Tipo de campanha: {campaign.campaign_type}. Público: {seg_desc}. "
            "Use obrigatoriamente as variáveis {nome}, {link} e, quando houver cupom, {cupom} e {desconto}. "
            "Pode usar {produto_favorito} e {dia_semana}. Tom informal, 1 emoji, sem hashtags. Responda só com a mensagem."
        )
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            data=json.dumps({"model": model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}),
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json().get("content") or []
        return "".join(block.get("text", "") for block in content if block.get("type") == "text").strip()
