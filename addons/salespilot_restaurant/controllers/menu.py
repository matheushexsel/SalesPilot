# -*- coding: utf-8 -*-
"""Cardápio digital público e rastreamento da jornada (link -> cardápio -> pedido)."""
import json
import logging
import math
import secrets
from datetime import timedelta

from markupsafe import Markup

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request

from ..models.res_partner import normalize_phone

_logger = logging.getLogger(__name__)
ATTR_COOKIE = "sp_attr"
PHONE_COOKIE = "sp_phone"
COOKIE_AGE = 60 * 60 * 24 * 30


def _restaurant(slug):
    rest = request.env["sp.restaurant"].sudo().search([("slug", "=", slug)], limit=1)
    if not rest:
        raise NotFound()
    return rest


def _product_payload(tmpl):
    return {
        "id": tmpl.id,
        "product_id": tmpl.product_variant_id.id,
        "name": tmpl.name,
        "description": tmpl.description_sale or "",
        "price": tmpl.list_price,
        "category_id": tmpl.sp_menu_category_id.id,
        "kind": tmpl.sp_kind,
        "highlight": tmpl.sp_highlight,
        "tags": tmpl.sp_tags or "",
        "serves": tmpl.sp_serves,
        "has_image": bool(tmpl.image_128),
    }


PUBLIC_PAYMENT_METHODS = ("pix", "online_card", "apple_pay", "card_delivery", "cash")


def _text(value, limit=200):
    """Converte qualquer JSON em texto curto e sem espaços nas pontas (nunca levanta exceção)."""
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    return str(value).strip()[:limit]


def _find_coupon_source(env, rest, coupon, campaign=None, automation=None):
    """Devolve (origem, erro). Prefere a campanha/régua do link; depois qualquer campanha válida do
    restaurante com esse cupom; depois uma régua. Um cupom antigo expirado não bloqueia o da régua."""
    now = fields.Datetime.now()

    def campaign_valid(c):
        if not c.coupon_valid_days or not c.date_sent:
            return True
        return now <= c.date_sent + timedelta(days=c.coupon_valid_days)

    if campaign and (campaign.coupon_code or "").upper() == coupon:
        return (campaign, None) if campaign_valid(campaign) else (None, "Este cupom expirou.")
    if automation and (automation.coupon_code or "").upper() == coupon:
        return automation, None
    campaigns = env["sp.campaign"].search([("restaurant_id", "=", rest.id), ("coupon_code", "=ilike", coupon),
                                           ("state", "in", ("sending", "sent", "done"))], order="date_sent desc")
    valid = campaigns.filtered(campaign_valid)
    if valid:
        return valid[0], None
    auto = env["sp.automation"].search([("restaurant_id", "=", rest.id), ("coupon_code", "=ilike", coupon)], limit=1)
    if auto:
        return auto, None
    if campaigns:
        return None, "Este cupom expirou."
    return None, "Cupom inválido ou expirado."


class _CheckoutError(Exception):
    """Erro de negócio no checkout: desfaz o savepoint e devolve a mensagem ao cliente."""


class SalesPilotMenu(http.Controller):

    # ------------------------------------------------------------------
    # Link rastreado das mensagens
    # ------------------------------------------------------------------
    @http.route("/c/<string:token>", type="http", auth="public", website=False, sitemap=False)
    def tracked_link(self, token, **kw):
        msg = request.env["sp.message"].sudo().search([("tracking_token", "=", token)], limit=1)
        if not msg:
            raise NotFound()
        msg.register_click()
        response = request.redirect(f"/cardapio/{msg.restaurant_id.slug}?c={token}")
        response.set_cookie(ATTR_COOKIE, token, max_age=COOKIE_AGE, samesite="Lax")
        return response

    # ------------------------------------------------------------------
    # Página do cardápio
    # ------------------------------------------------------------------
    @http.route("/cardapio/<string:slug>", type="http", auth="public", website=False, sitemap=False)
    def menu_page(self, slug, c=None, **kw):
        rest = _restaurant(slug)
        categories = request.env["sp.menu.category"].sudo().search([("restaurant_id", "=", rest.id)])
        products = request.env["product.template"].sudo().search(
            [("sp_restaurant_id", "=", rest.id), ("sp_available", "=", True), ("sale_ok", "=", True)],
            order="sp_highlight desc, sp_sold_qty_90d desc, name")
        token = c or request.httprequest.cookies.get(ATTR_COOKIE)
        msg = None
        if token:
            msg = request.env["sp.message"].sudo().search([("tracking_token", "=", token),
                                                            ("restaurant_id", "=", rest.id)], limit=1) or None
            if not msg:
                token = None
        coupon = msg.coupon_code if msg else ""
        discount_pct = 0.0
        discount_value = 0.0
        if msg:
            src = msg.campaign_id or msg.automation_id
            if src:
                discount_pct = src.discount_pct
                discount_value = src.discount_value
        known_phone = request.httprequest.cookies.get(PHONE_COOKIE) or ""
        values = {
            "rest": rest,
            "categories": categories,
            "products": products,
            "products_json": Markup(json.dumps([_product_payload(p) for p in products]).replace("<", "\\u003c")),
            "categories_json": Markup(json.dumps([{"id": c.id, "name": c.name} for c in categories]).replace("<", "\\u003c")),
            "config_json": Markup(json.dumps({"slug": rest.slug, "token": token or "", "delivery_fee": rest.delivery_fee}).replace("<", "\\u003c")),
            "token": token or "",
            "coupon": coupon or "",
            "token_first_name": (msg.partner_id.name or "").split(" ")[0] if msg and msg.partner_id else "",
            "discount_pct": discount_pct,
            "discount_value": discount_value,
            "known_phone": known_phone,
            "payment_methods": [("pix", "Pix (QR code simulado)"), ("online_card", "Cartão online (simulado)"),
                                ("apple_pay", "Apple Pay / Google Pay (simulado)"), ("card_delivery", "Cartão na entrega"),
                                ("cash", "Dinheiro")],
        }
        response = request.render("salespilot_restaurant.menu_page", values)
        if c and token:
            response.set_cookie(ATTR_COOKIE, c, max_age=COOKIE_AGE, samesite="Lax")
        return response

    @http.route("/cardapio/<string:slug>/img/<int:tmpl_id>", type="http", auth="public", website=False, sitemap=False)
    def menu_image(self, slug, tmpl_id, **kw):
        rest = _restaurant(slug)
        tmpl = request.env["product.template"].sudo().browse(tmpl_id)
        if not tmpl.exists() or tmpl.sp_restaurant_id != rest:
            raise NotFound()
        return request.env["ir.binary"]._get_image_stream_from(tmpl, "image_512").get_response()

    # ------------------------------------------------------------------
    # APIs JSON usadas pela página
    # ------------------------------------------------------------------
    @http.route("/cardapio/<string:slug>/api/identify", type="json", auth="public", methods=["POST"], csrf=False)
    def api_identify(self, slug, phone=None, **kw):
        rest = _restaurant(slug)
        env = request.env(su=True)
        digits = normalize_phone(_text(phone, 40))
        partner = env["res.partner"].search([("sp_restaurant_id", "=", rest.id), ("sp_whatsapp_norm", "=", digits)], limit=1) if digits else None
        engine = env["sp.rfv.engine"]
        if not partner:
            best = env["product.template"].search([("sp_restaurant_id", "=", rest.id), ("sp_available", "=", True)],
                                                  order="sp_sold_qty_90d desc", limit=3)
            return {"known": False, "greeting": "Bem-vindo(a)! Olha os mais pedidos da casa:",
                    "recommendations": [{"id": t.id, "name": t.name, "price": t.list_price, "reason": "Mais pedido da casa"} for t in best]}
        recs = engine.recommend_for_partner(partner)
        # Privacidade: nome completo e endereço só voltam para quem chegou pelo próprio link rastreado
        # (cookie com o telefone). Para um número digitado, devolvemos só o primeiro nome e uma dica
        # do endereço, suficiente para a experiência e inútil para quem tenta enumerar números.
        # "Confiável" = o navegador tem o link rastreado deste cliente E digitou o número dele,
        # ou já fez um pedido com esse número neste navegador (cookie gravado no checkout).
        token = request.httprequest.cookies.get(ATTR_COOKIE)
        token_partner = env["sp.message"].search([("tracking_token", "=", token or ""), ("restaurant_id", "=", rest.id)], limit=1).partner_id
        trusted = (token_partner and token_partner.id == partner.id) or \
            normalize_phone(request.httprequest.cookies.get(PHONE_COOKIE)) == digits
        street = partner.street or ""
        address_hint = " ".join(street.split(",")[0].split(" ")[:3]) + " ..." if street else ""
        return {
            "known": True,
            "name": partner.name if trusted else (partner.name or "").split(" ")[0],
            "first_name": (partner.name or "").split(" ")[0],
            "address": (partner.contact_address_inline or street) if trusted else "",
            "address_hint": address_hint,
            "trusted": trusted,
            "greeting": engine.greeting_for_partner(partner),
            "favorite_id": partner.sp_favorite_product_id.product_tmpl_id.id if partner.sp_favorite_product_id else None,
            "recommendations": [{"id": r["product"].id, "name": r["product"].name, "price": r["product"].list_price,
                                 "reason": r["reason"], "kind": r["kind"]} for r in recs],
        }

    @http.route("/cardapio/<string:slug>/api/suggest", type="json", auth="public", methods=["POST"], csrf=False)
    def api_suggest(self, slug, items=None, **kw):
        rest = _restaurant(slug)
        env = request.env(su=True)
        items = [i for i in (items if isinstance(items, list) else []) if isinstance(i, dict)]
        tmpl_ids = []
        for i in items:
            try:
                tmpl_ids.append(int(i.get("id")))
            except (TypeError, ValueError):
                continue
        if not tmpl_ids:
            return {"suggestions": []}
        suggestions = env["sp.rfv.engine"].cross_sell(rest, tmpl_ids, limit=3)
        out = [{"id": s["product"].id, "name": s["product"].name, "price": s["product"].list_price, "reason": s["reason"]}
               for s in suggestions]
        # Regra de upgrade: 2+ principais sem bebida grande -> sugerir bebida 2L / família
        kinds = {t.id: (t.sp_kind, t.name or "") for t in env["product.template"].browse(tmpl_ids).exists()}
        mains = 0
        has_big_drink = False
        for i in items:
            try:
                tid, qty = int(i.get("id")), max(int(float(i.get("qty", 1))), 0)
            except (TypeError, ValueError):
                continue
            kind, name = kinds.get(tid, (None, ""))
            if kind in ("main", "combo"):
                mains += qty
            if kind == "drink" and ("2l" in name.lower() or "1,5" in name.lower()):
                has_big_drink = True
        if mains >= 2 and not has_big_drink:
            big = env["product.template"].search([("sp_restaurant_id", "=", rest.id), ("sp_kind", "=", "drink"),
                                                  ("sp_available", "=", True), ("name", "ilike", "2L")], limit=1)
            if big and big.id not in [o["id"] for o in out] and big.id not in tmpl_ids:
                out.insert(0, {"id": big.id, "name": big.name, "price": big.list_price,
                               "reason": f"Para {mains} pessoas sai mais em conta que duas latas"})
        return {"suggestions": out[:3]}

    @http.route("/cardapio/<string:slug>/api/checkout", type="json", auth="public", methods=["POST"], csrf=False)
    def api_checkout(self, slug, phone=None, name=None, address=None, items=None, payment_method="pix",
                     notes=None, coupon=None, token=None, recommended_ids=None, birthday=None, **kw):
        rest = _restaurant(slug)
        env = request.env(su=True)
        items = [i for i in (items if isinstance(items, list) else []) if isinstance(i, dict)]
        if not items:
            return {"error": "Carrinho vazio."}
        phone = _text(phone, 40)
        if len(normalize_phone(phone)) < 12:  # 55 + DDD + número
            return {"error": "Informe seu WhatsApp com DDD para continuar."}
        name = _text(name, 80) or None
        address = _text(address, 200) or None
        notes = _text(notes, 500) or None
        coupon = _text(coupon, 30)
        token = _text(token, 40) or None
        if payment_method not in PUBLIC_PAYMENT_METHODS:
            payment_method = "pix"
        if birthday:
            try:
                birthday = fields.Date.to_date(_text(birthday, 10))
            except (ValueError, TypeError):
                birthday = None
        Template = env["product.template"]
        lines = []
        subtotal = 0.0
        try:
            recommended_ids = set(int(x) for x in (recommended_ids if isinstance(recommended_ids, list) else []))
        except (TypeError, ValueError, OverflowError):
            recommended_ids = set()
        for it in items:
            try:
                tmpl = Template.browse(int(it.get("id")))
                qty = float(it.get("qty", 1))
                if not math.isfinite(qty):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                return {"error": "Itens inválidos no carrinho."}
            if not tmpl.exists() or tmpl.sp_restaurant_id != rest or not tmpl.sp_available:
                return {"error": "Um dos itens não está mais disponível. Atualize o cardápio."}
            qty = min(max(round(qty), 1), 50)
            subtotal += qty * tmpl.list_price
            lines.append((0, 0, {"product_id": tmpl.product_variant_id.id, "qty": qty, "price_unit": tmpl.list_price,
                                 "notes": _text(it.get("notes"), 200) or False, "recommended": tmpl.id in recommended_ids}))
        if not lines:
            return {"error": "Itens inválidos."}
        if subtotal < (rest.min_order or 0):
            return {"error": f"Pedido mínimo de R$ {rest.min_order:.2f}".replace(".", ",")}

        # A partir daqui há escrita no banco: tudo dentro de um savepoint, para que um cupom
        # inválido não deixe um cadastro de cliente para trás.
        try:
            with env.cr.savepoint():
                return self._checkout_commit(env, rest, phone, name, address, birthday, lines, subtotal, payment_method,
                                             notes, coupon, token, recommended_ids)
        except _CheckoutError as exc:
            return {"error": str(exc)}

    def _checkout_commit(self, env, rest, phone, name, address, birthday, lines, subtotal, payment_method,
                         notes, coupon, token, recommended_ids):
        extra = {}
        if address:
            extra["street"] = address
        if birthday:
            extra["sp_birthday"] = birthday
        partner = env["res.partner"].sp_find_or_create_customer(rest, phone, name=name, extra=extra)
        if address and not partner.street:
            partner.street = address
        if birthday and not partner.sp_birthday:
            partner.sp_birthday = birthday

        token = token or request.httprequest.cookies.get(ATTR_COOKIE)
        msg = env["sp.message"].search([("tracking_token", "=", token), ("restaurant_id", "=", rest.id)], limit=1) \
            if token else env["sp.message"]
        discount = 0.0
        campaign = msg.campaign_id if msg else env["sp.campaign"]
        automation = msg.automation_id if msg else env["sp.automation"]
        coupon = (coupon or "").strip().upper()
        if coupon:
            src, error = _find_coupon_source(env, rest, coupon, campaign, automation)
            if error:
                raise _CheckoutError(error)
            if src._name == "sp.campaign" and not campaign:
                campaign = src
            elif src._name == "sp.automation" and not automation:
                automation = src
            # Uso único por cliente
            already = env["sp.order"].search_count([("partner_id", "=", partner.id), ("coupon_code", "=ilike", coupon),
                                                    ("state", "in", ("confirmed", "preparing", "delivering", "delivered"))])
            if already:
                raise _CheckoutError("Você já usou este cupom.")
            discount = round(subtotal * (src.discount_pct or 0) / 100.0 + (src.discount_value or 0.0), 2)

        order = env["sp.order"].create({
            "restaurant_id": rest.id,
            "partner_id": partner.id,
            "channel": "menu",
            "from_menu": True,
            "state": "confirmed",
            "payment_method": payment_method if payment_method in dict(env["sp.order"]._fields["payment_method"].selection) else "pix",
            "payment_status": "pending",  # piloto: nenhum pagamento é cobrado de verdade
            "delivery_fee": rest.delivery_fee,
            "discount_amount": min(discount, subtotal),
            "delivery_address": address or partner.street or "",
            "customer_notes": notes or False,
            "coupon_code": coupon or False,
            "campaign_id": campaign.id if campaign else False,
            "automation_id": automation.id if automation else False,
            "message_id": msg.id if msg else False,
            "recommendation_accepted": bool(recommended_ids),
            "line_ids": lines,
        })
        payment_info = {}
        if payment_method == "pix":
            payment_info = {"kind": "pix", "code": "00020126580014BR.GOV.BCB.PIX0136" + secrets.token_hex(16) + "5204000053039865802BR",
                            "note": "Pix simulado no piloto: nenhuma cobrança é feita e o pedido fica como 'pagamento pendente'."}
        elif payment_method in ("online_card", "apple_pay"):
            payment_info = {"kind": payment_method, "note": "Pagamento simulado no piloto (gateway não integrado)."}
        else:
            payment_info = {"kind": payment_method, "note": "Pague na entrega."}
        request.future_response.set_cookie(PHONE_COOKIE, phone, max_age=COOKIE_AGE, samesite="Lax")
        response_vals = {
            "order_id": order.id, "name": order.name, "total": order.amount_total, "subtotal": order.amount_subtotal,
            "discount": order.discount_amount, "delivery_fee": order.delivery_fee,
            "eta_minutes": rest.avg_prep_minutes, "payment": payment_info, "attributed": order.attributed,
            "status_url": f"/cardapio/{rest.slug}/pedido/{order.id}/{order.tracking_token}",
        }
        return response_vals

    @http.route("/cardapio/<string:slug>/pedido/<int:order_id>/<string:token>", type="http", auth="public", website=False, sitemap=False)
    def order_status(self, slug, order_id, token, **kw):
        rest = _restaurant(slug)
        order = request.env["sp.order"].sudo().browse(order_id)
        if not order.exists() or order.restaurant_id != rest or order.tracking_token != token:
            raise NotFound()
        return request.render("salespilot_restaurant.order_status_page", {"rest": rest, "order": order})
