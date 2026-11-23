# -*- coding: utf-8 -*-
"""Gerador de dados fictícios coerentes com o negócio (hamburgueria, pizzaria, temakeria).

Tudo é determinístico (seed fixa) e relativo à data de instalação, para que os alertas de
red flag, aniversários e próximos pedidos estejam "frescos" no momento do teste.
"""
import logging
import random
from datetime import date, datetime, timedelta, timezone

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)
TZ_OFFSET = timedelta(hours=3)  # America/Sao_Paulo (sem horário de verão) -> UTC

FIRST_NAMES = [
    "Ana", "Bruno", "Camila", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela", "João",
    "Karina", "Lucas", "Mariana", "Nicolas", "Olívia", "Pedro", "Rafaela", "Samuel", "Tatiane", "Vinícius",
    "Amanda", "Caio", "Daniela", "Fábio", "Giovanna", "Igor", "Juliana", "Leonardo", "Larissa", "Marcelo",
    "Natália", "Otávio", "Patrícia", "Renato", "Sabrina", "Thiago", "Vanessa", "Wesley", "Beatriz", "Rodrigo",
    "Carla", "André", "Letícia", "Gustavo", "Fernanda", "Matheus", "Bianca", "Ricardo", "Priscila", "Alexandre",
]
LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira", "Lima", "Gomes",
    "Costa", "Ribeiro", "Martins", "Carvalho", "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa",
    "Rocha", "Dias", "Nascimento", "Andrade", "Moreira", "Nunes", "Marques", "Machado", "Mendes", "Freitas",
    "Cardoso", "Ramos", "Gonçalves", "Santana", "Teixeira", "Araújo", "Pinto", "Correia", "Cavalcanti", "Monteiro",
]
STREETS = ["Rua dos Pinheiros", "Rua Fradique Coutinho", "Rua Teodoro Sampaio", "Av. Rebouças", "Rua Cardeal Arcoverde",
           "Rua Harmonia", "Rua Wisard", "Rua Domingos de Morais", "Rua Vergueiro", "Av. Ibirapuera", "Alameda dos Anapurus",
           "Rua Pamplona", "Rua Augusta", "Rua Joaquim Floriano", "Rua Aspicuelta"]

RESTAURANTS = [
    {
        "name": "Burger do Diogo", "slug": "burger-do-diogo", "segment": "hamburgueria",
        "tagline": "Smash burgers artesanais em Pinheiros, direto da chapa pra sua casa.",
        "color_primary": "#E63946", "whatsapp": "(11) 98877-1010", "street": "Rua dos Pinheiros, 742 - Pinheiros",
        "opening_hours": "Ter a Dom, 18h às 23h30", "delivery_fee": 6.0, "min_order": 25.0, "avg_prep_minutes": 40,
        "customers": 150, "lunch_share": 0.08,
        "categories": ["Burgers", "Combos", "Acompanhamentos", "Bebidas", "Sobremesas"],
        "products": [
            # (nome, categoria, tipo, preço, destaque, descrição, combina_com)
            ("Smash Burger", "Burgers", "main", 29.90, True, "Dois smash de 80g, queijo prato, cebola na chapa e molho da casa no pão brioche.", "Batata Frita"),
            ("Smash Duplo Bacon", "Burgers", "main", 38.90, True, "Dois smash, cheddar inglês, bacon crocante e maionese defumada.", "Batata com Cheddar e Bacon"),
            ("Cheddar Bacon Clássico", "Burgers", "main", 36.90, False, "Blend 160g, cheddar cremoso, bacon e cebola caramelizada.", "Onion Rings"),
            ("Chicken Crispy", "Burgers", "main", 32.90, False, "Frango empanado crocante, alface americana, picles e maionese de ervas.", "Batata Frita"),
            ("Veggie Burger", "Burgers", "main", 34.90, False, "Burger de grão-de-bico e cogumelos, queijo coalho e rúcula.", "Suco Natural 500ml"),
            ("Combo Smash", "Combos", "combo", 44.90, True, "Smash Burger + batata frita média + refrigerante lata.", None),
            ("Combo Família", "Combos", "combo", 89.90, False, "2 burgers à escolha + batata grande + Coca-Cola 2L.", None),
            ("Batata Frita", "Acompanhamentos", "side", 16.90, False, "Porção média, crocante, com sal de alecrim.", None),
            ("Batata com Cheddar e Bacon", "Acompanhamentos", "side", 24.90, True, "Porção grande coberta com cheddar e bacon.", None),
            ("Onion Rings", "Acompanhamentos", "side", 18.90, False, "Anéis de cebola empanados, 10 unidades.", None),
            ("Coca-Cola Lata", "Bebidas", "drink", 7.00, False, "350ml gelada.", None),
            ("Guaraná Antarctica Lata", "Bebidas", "drink", 6.50, False, "350ml gelado.", None),
            ("Coca-Cola 2L", "Bebidas", "drink", 14.90, False, "Pra dividir.", None),
            ("Suco Natural 500ml", "Bebidas", "drink", 9.90, False, "Laranja, limão ou abacaxi com hortelã.", None),
            ("Milkshake Ovomaltine", "Sobremesas", "dessert", 19.90, False, "400ml, bem cremoso.", None),
            ("Brownie com Sorvete", "Sobremesas", "dessert", 14.90, False, "Brownie de chocolate meio amargo com bola de creme.", None),
        ],
        "cross": {"side": 0.62, "drink": 0.58, "dessert": 0.14},
    },
    {
        "name": "Pizzaria Nonna Lúcia", "slug": "pizzaria-nonna-lucia", "segment": "pizzaria",
        "tagline": "Massa de fermentação natural e forno a lenha, na Vila Mariana desde 2009.",
        "color_primary": "#B5451B", "whatsapp": "(11) 97766-2020", "street": "Rua Domingos de Morais, 1580 - Vila Mariana",
        "opening_hours": "Todos os dias, 18h às 23h", "delivery_fee": 8.0, "min_order": 40.0, "avg_prep_minutes": 50,
        "customers": 120, "lunch_share": 0.03,
        "categories": ["Pizzas Grandes", "Brotos", "Doces", "Extras", "Bebidas"],
        "products": [
            ("Margherita", "Pizzas Grandes", "main", 54.90, True, "Molho de tomate San Marzano, mussarela de búfala e manjericão.", "Coca-Cola 2L"),
            ("Calabresa Especial", "Pizzas Grandes", "main", 52.90, True, "Calabresa artesanal, cebola roxa e azeitonas pretas.", "Coca-Cola 2L"),
            ("Portuguesa", "Pizzas Grandes", "main", 58.90, False, "Presunto, ovos, cebola, ervilha, azeitona e mussarela.", "Guaraná 2L"),
            ("Quatro Queijos", "Pizzas Grandes", "main", 62.90, False, "Mussarela, gorgonzola, parmesão e catupiry.", "Coca-Cola 2L"),
            ("Frango com Catupiry", "Pizzas Grandes", "main", 59.90, False, "Frango desfiado temperado e catupiry original.", "Coca-Cola 2L"),
            ("Pepperoni", "Pizzas Grandes", "main", 64.90, False, "Pepperoni importado e mussarela, bordas crocantes.", "Coca-Cola 2L"),
            ("Broto Margherita", "Brotos", "main", 32.90, False, "Pizza individual de 25cm.", "Coca-Cola Lata"),
            ("Broto Calabresa", "Brotos", "main", 31.90, False, "Pizza individual de 25cm.", "Coca-Cola Lata"),
            ("Pizza de Chocolate com Morango (broto)", "Doces", "dessert", 34.90, False, "Chocolate ao leite, morangos frescos e leite condensado.", None),
            ("Borda Recheada de Catupiry", "Extras", "side", 8.00, False, "Adicional por pizza.", None),
            ("Esfiha de Carne (3 un)", "Extras", "side", 15.90, False, "Abertas, massa fininha.", None),
            ("Coca-Cola 2L", "Bebidas", "drink", 14.90, False, "Gelada.", None),
            ("Guaraná 2L", "Bebidas", "drink", 12.90, False, "Gelado.", None),
            ("Coca-Cola Lata", "Bebidas", "drink", 7.00, False, "350ml.", None),
            ("Água Mineral 500ml", "Bebidas", "drink", 4.00, False, "Com ou sem gás.", None),
        ],
        "cross": {"side": 0.35, "drink": 0.66, "dessert": 0.12},
    },
    {
        "name": "Temakeria Oishii", "slug": "temakeria-oishii", "segment": "temakeria",
        "tagline": "Temakis e combinados frescos em Moema. Peixe do dia, arroz na hora.",
        "color_primary": "#2A9D8F", "whatsapp": "(11) 96655-3030", "street": "Alameda dos Anapurus, 1130 - Moema",
        "opening_hours": "Ter a Dom, 11h30 às 15h e 18h às 23h", "delivery_fee": 7.0, "min_order": 30.0, "avg_prep_minutes": 35,
        "customers": 100, "lunch_share": 0.3,
        "categories": ["Temakis", "Combinados", "Entradas", "Bebidas", "Sobremesas"],
        "products": [
            ("Temaki Salmão", "Temakis", "main", 32.90, True, "Salmão fresco em cubos, cream cheese e cebolinha.", "Sunomono"),
            ("Temaki Salmão Grelhado", "Temakis", "main", 34.90, False, "Salmão grelhado no maçarico com tarê.", "Guioza (6 un)"),
            ("Temaki Hot Philadelphia", "Temakis", "main", 36.90, True, "Salmão, cream cheese, empanado e frito.", "Chá Gelado 500ml"),
            ("Temaki Atum", "Temakis", "main", 31.90, False, "Atum fresco, cebolinha e gergelim.", "Sunomono"),
            ("Temaki Camarão Empanado", "Temakis", "main", 38.90, False, "Camarão crocante, cream cheese e molho especial.", "Chá Gelado 500ml"),
            ("Temaki Vegetariano", "Temakis", "main", 26.90, False, "Pepino, manga, cenoura e cream cheese.", "Chá Gelado 500ml"),
            ("Combinado 20 peças", "Combinados", "main", 69.90, True, "8 sashimis, 6 uramakis, 4 niguiris e 2 hossomakis.", "Shimeji na Manteiga"),
            ("Combinado 40 peças", "Combinados", "main", 129.90, False, "Para 2–3 pessoas. Salmão, atum e peixe branco.", "Coca-Cola 2L"),
            ("Hot Roll (10 un)", "Entradas", "side", 29.90, False, "Enrolado de salmão empanado com tarê.", None),
            ("Sunomono", "Entradas", "side", 12.90, False, "Salada de pepino agridoce com gergelim.", None),
            ("Guioza (6 un)", "Entradas", "side", 24.90, False, "Recheio de porco e legumes, grelhado.", None),
            ("Shimeji na Manteiga", "Entradas", "side", 22.90, False, "Com shoyu e cebolinha.", None),
            ("Coca-Cola Lata", "Bebidas", "drink", 7.00, False, "350ml.", None),
            ("Chá Gelado 500ml", "Bebidas", "drink", 8.90, False, "Chá verde ou pêssego, feito na casa.", None),
            ("Coca-Cola 2L", "Bebidas", "drink", 14.90, False, "Gelada.", None),
            ("Harumaki de Banana com Doce de Leite", "Sobremesas", "dessert", 14.90, False, "2 unidades, crocantes.", None),
        ],
        "cross": {"side": 0.48, "drink": 0.45, "dessert": 0.10},
    },
]

# Personas de comportamento: (nome, peso, intervalo mín, intervalo máx, parado há (min,max) ou None, nº máx de pedidos)
PERSONAS = [
    ("champion", 0.08, 5, 8, None, 40),
    ("loyal", 0.16, 10, 16, None, 20),
    ("regular", 0.22, 20, 35, None, 10),
    ("occasional", 0.16, 40, 75, None, 5),
    ("new", 0.11, 7, 20, None, 2),
    ("at_risk", 0.12, 7, 14, (18, 40), 20),
    ("lost", 0.15, 10, 30, (95, 170), 8),
]

PROSPECTS = [
    ("Hamburgueria Garage 66", "hamburgueria", "Vila Madalena", 4.6, 812, True, 4.5, "@garage66burgers", 5400, False, 700, 52.0),
    ("Pizzaria Dom Bosco", "pizzaria", "Perdizes", 4.4, 1240, True, 4.3, "@pizzariadombosco", 2100, False, 950, 68.0),
    ("Temakeria Kaizen", "temakeria", "Itaim Bibi", 4.7, 430, True, 4.6, "@kaizentemakeria", 3900, True, 420, 58.0),
    ("Bendito Smash", "hamburgueria", "Santana", 4.3, 290, True, 4.2, "@benditosmash", 1800, False, 380, 45.0),
    ("La Famiglia Pizza", "pizzaria", "Mooca", 4.5, 2100, False, 0.0, "@lafamigliapizzasp", 7200, True, 1100, 72.0),
    ("Açaí da Praça", "acai", "Butantã", 4.2, 150, True, 4.1, "@acaidapraca", 900, False, 260, 28.0),
    ("Marmitaria Sabor Caseiro", "marmitaria", "Lapa", 4.5, 210, False, 0.0, "", 300, False, 520, 24.0),
    ("Sushi Nakamura Delivery", "temakeria", "Pinheiros", 4.8, 980, True, 4.7, "@sushinakamura", 11000, True, 640, 85.0),
    ("Burger Station", "hamburgueria", "Tatuapé", 4.1, 620, True, 4.0, "@burgerstationsp", 4100, False, 560, 48.0),
    ("Pizza na Brasa", "pizzaria", "Saúde", 4.6, 480, True, 4.5, "@pizzanabrasa", 2600, False, 430, 61.0),
    ("Temaki Express Moema", "temakeria", "Moema", 4.0, 95, True, 3.9, "", 450, False, 180, 40.0),
    ("Cantina do Enzo", "pizzaria", "Bela Vista", 4.7, 1560, True, 4.6, "@cantinadoenzo", 8800, True, 880, 75.0),
    ("Smash Lab", "hamburgueria", "Pinheiros", 4.5, 340, True, 4.4, "@smashlab.sp", 6700, False, 490, 50.0),
    ("Oriental House", "temakeria", "Vila Olímpia", 4.3, 260, True, 4.2, "@orientalhousesp", 1500, False, 300, 62.0),
    ("Rei do Açaí", "acai", "Ipiranga", 4.4, 710, True, 4.3, "@reidoacai", 3200, False, 800, 26.0),
]


def _to_utc(local_dt):
    return local_dt + TZ_OFFSET


def post_init_hook(env):
    if hasattr(env, "cr") and not isinstance(env, api.Environment):  # compat (cr, registry)
        env = api.Environment(env, SUPERUSER_ID, {})
    Seeder(env).run()


class Seeder:
    def __init__(self, env):
        self.env = env
        self.rnd = random.Random(2024)
        self.now_local = datetime.now(timezone.utc).replace(tzinfo=None) - TZ_OFFSET
        self.today = self.now_local.date()

    # ------------------------------------------------------------------
    def run(self):
        env = self.env
        if env["sp.restaurant"].search_count([("slug", "in", [r["slug"] for r in RESTAURANTS])]):
            _logger.warning("SalesPilot demo: dados já existem neste banco; geração ignorada.")
            return
        _logger.info("SalesPilot demo: gerando dados...")
        self._setup_company()
        restaurants = []
        for spec in RESTAURANTS:
            rest = self._create_restaurant(spec)
            products = self._create_menu(rest, spec)
            customers = self._create_customers(rest, spec)
            self._create_orders(rest, spec, products, customers)
            restaurants.append((rest, spec, products, customers))
        env["sp.rfv.engine"].recompute(env["sp.restaurant"].browse([r[0].id for r in restaurants]))
        for rest, spec, products, customers in restaurants:
            self._create_automations(rest)
            self._create_campaigns(rest, spec, products)
        self._create_users(restaurants)
        self._create_prospects()
        rests = env["sp.restaurant"].browse([r[0].id for r in restaurants])
        env["sp.rfv.engine"].recompute(rests)
        env["sp.insight"].generate_for(rests)
        env["sp.alert"].scan(rests)
        self._create_billing(rests)
        _logger.info("SalesPilot demo: concluído.")

    # ------------------------------------------------------------------
    def _setup_company(self):
        env = self.env
        brl = env.ref("base.BRL")
        brl.active = True
        company = env.company
        company.write({"name": "SalesPilot Piloto", "currency_id": brl.id, "country_id": env.ref("base.br").id,
                       "city": "São Paulo", "state_id": env.ref("base.state_br_sp").id,
                       "email": "contato@salespilot.com.br"})
        env["res.lang"]._activate_lang("pt_BR")
        admin = env.ref("base.user_admin")
        admin.write({"lang": "pt_BR", "tz": "America/Sao_Paulo", "name": "Matheus (SalesPilot)"})
        if not admin.email:
            admin.email = "admin@salespilot.com.br"
        env["ir.config_parameter"].sudo().set_param("salespilot.message_provider", "simulation")
        # Desliga serviços pagos/externos do Odoo que não fazem parte do piloto (enriquecimento IAP de leads)
        crons = env["ir.cron"].sudo().with_context(active_test=False).search([("cron_name", "ilike", "enrich")])
        crons.write({"active": False})
        env["ir.config_parameter"].sudo().set_param("crm.iap.lead.enrich.setting", "manual")

    def _create_restaurant(self, spec):
        vals = {k: v for k, v in spec.items() if k in (
            "name", "slug", "segment", "tagline", "color_primary", "whatsapp", "street", "opening_hours",
            "delivery_fee", "min_order", "avg_prep_minutes")}
        vals.update({"city": "São Paulo", "state_code": "SP", "email": f"contato@{spec['slug'].replace('-', '')}.com.br",
                     "phone": spec["whatsapp"]})
        return self.env["sp.restaurant"].create(vals)

    def _create_menu(self, rest, spec):
        Cat = self.env["sp.menu.category"]
        Tmpl = self.env["product.template"]
        cats = {name: Cat.create({"name": name, "restaurant_id": rest.id, "sequence": i * 10})
                for i, name in enumerate(spec["categories"])}
        products = {}
        for name, cat, kind, price, highlight, desc, _pair in spec["products"]:
            products[name] = Tmpl.create({
                "name": name, "type": "consu", "sale_ok": True, "purchase_ok": False, "list_price": price,
                "description_sale": desc, "sp_restaurant_id": rest.id, "sp_menu_category_id": cats[cat].id,
                "sp_kind": kind, "sp_highlight": highlight, "sp_available": True,
                "sp_serves": 2 if ("2L" in name or "Família" in name or "40" in name or "Grandes" == cat) else 1,
            })
        for name, _cat, _kind, _price, _hl, _desc, pair in spec["products"]:
            if pair and pair in products:
                products[name].sp_pair_product_id = products[pair].id
        return products

    def _birthday_in(self, days_ahead, age):
        """Data de nascimento de quem faz `age` anos daqui a `days_ahead` dias (sem deriva de bissexto)."""
        target = self.today + timedelta(days=days_ahead)
        try:
            return target.replace(year=target.year - age)
        except ValueError:  # 29/02
            return target.replace(year=target.year - age, day=28)

    def _phone(self):
        return f"(11) 9{self.rnd.randint(6000, 9999)}-{self.rnd.randint(1000, 9999)}"

    def _create_customers(self, rest, spec):
        Partner = self.env["res.partner"]
        customers = []
        used = set()
        personas = [p for p in PERSONAS]
        weights = [p[1] for p in personas]
        vals_list = []
        metas = []
        for i in range(spec["customers"]):
            while True:
                name = f"{self.rnd.choice(FIRST_NAMES)} {self.rnd.choice(LAST_NAMES)}"
                if name not in used:
                    used.add(name)
                    break
            persona = self.rnd.choices(personas, weights)[0]
            birthday = None
            if self.rnd.random() < 0.7:
                birthday = date(self.rnd.randint(1970, 2003), self.rnd.randint(1, 12), self.rnd.randint(1, 28))
            phone = self._phone()
            vals_list.append({
                "name": name, "sp_restaurant_id": rest.id, "sp_is_customer": True,
                "sp_whatsapp": phone, "phone": phone, "sp_birthday": birthday,
                "sp_opt_in": self.rnd.random() < 0.9,
                "sp_source": self.rnd.choices(["menu", "whatsapp", "ifood", "phone"], [0.45, 0.3, 0.2, 0.05])[0],
                "street": f"{self.rnd.choice(STREETS)}, {self.rnd.randint(20, 1900)}", "city": "São Paulo",
                "sp_tags": self.rnd.choice(["", "", "", "sem cebola", "gosta de picante", "vegetariano", "pede pra família", "sem lactose"]),
            })
            metas.append(persona)
        # Clientes "nomeados" para o roteiro de teste
        named = []
        if spec["segment"] == "hamburgueria":
            named = [
                ({"name": "Diogo Martins", "sp_whatsapp": "(11) 99999-0001", "sp_birthday": date(1988, 11, 29),
                  "sp_tags": "quarta-feira é dia de smash", "street": "Rua Harmonia, 310 - Vila Madalena"},
                 ("habit_wed", 0, 7, 7, None, 24)),
                ({"name": "Ana Paula Ferreira", "sp_whatsapp": "(11) 99999-0002", "sp_birthday": date(1992, 5, 14),
                  "street": "Rua Fradique Coutinho, 1200"},
                 ("at_risk", 0, 6, 8, (24, 24), 22)),
                ({"name": "Carlos Eduardo Nunes", "sp_whatsapp": "(11) 99999-0003",
                  "sp_birthday": self._birthday_in(2, 35),
                  "street": "Rua Cardeal Arcoverde, 88"},
                 ("loyal", 0, 10, 14, None, 15)),
                ({"name": "Juliana Rocha", "sp_whatsapp": "(11) 99999-0004",
                  "sp_birthday": self._birthday_in(0, 29), "street": "Rua Wisard, 45"},
                 ("champion", 0, 5, 7, None, 30)),
                ({"name": "Marcos Vinícius Lima", "sp_whatsapp": "(11) 99999-0005", "street": "Rua Aspicuelta, 500"},
                 ("new", 0, 7, 10, None, 1)),
            ]
        elif spec["segment"] == "pizzaria":
            named = [
                ({"name": "Família Bertolini", "sp_whatsapp": "(11) 99999-0101", "sp_tags": "sexta à noite, 2 grandes",
                  "street": "Rua Vergueiro, 2300"}, ("habit_fri", 0, 7, 7, None, 22)),
                ({"name": "Roberto Takahashi", "sp_whatsapp": "(11) 99999-0102", "street": "Rua Domingos de Morais, 900"},
                 ("at_risk", 0, 7, 10, (30, 30), 18)),
            ]
        else:
            named = [
                ({"name": "Fernanda Yamamoto", "sp_whatsapp": "(11) 99999-0201", "sp_tags": "almoço de terça, temaki salmão",
                  "street": "Av. Ibirapuera, 2000"}, ("habit_tue_lunch", 0, 7, 7, None, 20)),
                ({"name": "Paulo Sérgio Andrade", "sp_whatsapp": "(11) 99999-0202", "street": "Alameda dos Anapurus, 300"},
                 ("at_risk", 0, 10, 12, (28, 28), 14)),
            ]
        for vals, persona in named:
            base = {"sp_restaurant_id": rest.id, "sp_is_customer": True, "sp_opt_in": True,
                    "sp_source": "menu", "city": "São Paulo"}
            base.update(vals)
            base.setdefault("phone", base.get("sp_whatsapp"))
            vals_list.append(base)
            metas.append(persona)
        partners = Partner.create(vals_list)
        for partner, persona in zip(partners, metas):
            customers.append((partner, persona))
        return customers

    # ------------------------------------------------------------------
    def _pick_products(self, spec, products, persona_name, fav, n_people=1):
        """Monta os itens de um pedido com base no favorito e nas probabilidades de cross-sell."""
        rnd = self.rnd
        by_kind = {}
        for name, _cat, kind, _price, _hl, _desc, _pair in spec["products"]:
            by_kind.setdefault(kind, []).append(name)
        items = []
        if rnd.random() < 0.72:
            main = fav
        else:
            main = rnd.choice(by_kind["main"] + by_kind.get("combo", []))
        qty_main = 1 if n_people == 1 else rnd.choice([1, 2, 2])
        items.append((main, qty_main))
        is_combo = main in by_kind.get("combo", [])
        cross = spec["cross"]
        if not is_combo and rnd.random() < cross["side"]:
            side = products[fav].sp_pair_product_id.name if products[fav].sp_pair_product_id and \
                products[fav].sp_pair_product_id.sp_kind == "side" and rnd.random() < 0.7 else rnd.choice(by_kind["side"])
            items.append((side, 1))
        if not is_combo and rnd.random() < cross["drink"]:
            big = [d for d in by_kind["drink"] if "2L" in d]
            small = [d for d in by_kind["drink"] if "2L" not in d]
            if qty_main >= 2 and big and rnd.random() < 0.75:
                items.append((rnd.choice(big), 1))
            else:
                items.append((rnd.choice(small), qty_main))
        if rnd.random() < cross["dessert"] and by_kind.get("dessert"):
            items.append((rnd.choice(by_kind["dessert"]), 1))
        return items

    def _order_datetime(self, day, weekday_pref, hour_pref, spec):
        rnd = self.rnd
        if hour_pref is not None and rnd.random() < 0.75:
            hour = hour_pref
        elif rnd.random() < spec["lunch_share"]:
            hour = rnd.choice([11, 12, 12, 13, 13, 14])
        else:
            hour = rnd.choices([18, 19, 20, 21, 22, 23], [0.12, 0.26, 0.3, 0.2, 0.09, 0.03])[0]
        minute = rnd.randint(0, 59)
        return datetime(day.year, day.month, day.day, hour, minute)

    def _create_orders(self, rest, spec, products, customers):
        rnd = self.rnd
        Order = self.env["sp.order"].with_context(sp_skip_rfv=True, sp_skip_automations=True)
        mains = [name for name, _c, kind, _p, _h, _d, _pair in spec["products"] if kind == "main"]
        combos = [name for name, _c, kind, _p, _h, _d, _pair in spec["products"] if kind == "combo"]
        # pesos: destaques vendem mais
        weights = [3 if products[m].sp_highlight else 1 for m in mains]
        channels = ["menu", "whatsapp", "ifood", "phone", "counter"]
        channel_w = [0.42, 0.25, 0.25, 0.05, 0.03]
        pay_by_channel = {"menu": ["pix", "online_card", "apple_pay", "card_delivery"], "whatsapp": ["pix", "card_delivery", "cash"],
                          "ifood": ["ifood"], "phone": ["card_delivery", "cash"], "counter": ["pix", "card_delivery", "cash"]}
        vals_list = []
        horizon = 180
        for partner, persona in customers:
            pname, _w, imin, imax, stopped, max_orders = persona
            fav = rnd.choices(mains, weights)[0]
            if pname == "habit_wed":
                fav = "Smash Burger"
            elif pname == "habit_fri":
                fav = "Calabresa Especial"
            elif pname == "habit_tue_lunch":
                fav = "Temaki Salmão"
            if spec["segment"] == "hamburgueria" and rnd.random() < 0.12:
                fav = rnd.choice(combos) if combos else fav
            n_people = 2 if (rnd.random() < 0.35 or spec["segment"] == "pizzaria" and rnd.random() < 0.6) else 1
            weekday_pref = rnd.randint(0, 6) if rnd.random() < 0.5 else None
            hour_pref = rnd.choice([19, 20, 20, 21]) if rnd.random() < 0.5 else None
            channel_pref = rnd.choices(channels, channel_w)[0]
            if pname == "habit_wed":
                weekday_pref, hour_pref, channel_pref = 2, 18, "menu"
            elif pname == "habit_fri":
                weekday_pref, hour_pref, channel_pref = 4, 20, "whatsapp"
            elif pname == "habit_tue_lunch":
                weekday_pref, hour_pref, channel_pref = 1, 12, "menu"

            # Linha do tempo de pedidos
            if stopped:
                last_gap = rnd.randint(*stopped)
            else:
                last_gap = rnd.randint(0, max(1, int((imin + imax) / 2 * 0.9)))
                if pname == "new":
                    last_gap = rnd.randint(1, 20)
            dates = []
            cursor = self.today - timedelta(days=last_gap)
            start_limit = self.today - timedelta(days=horizon)
            if pname == "new":
                first = cursor - timedelta(days=rnd.randint(0, 12)) if max_orders > 1 and rnd.random() < 0.5 else None
                dates = [cursor] + ([first] if first else [])
            else:
                count = 0
                while cursor >= start_limit and count < max_orders:
                    dates.append(cursor)
                    gap = rnd.randint(imin, imax)
                    cursor = cursor - timedelta(days=gap)
                    count += 1
            if pname in ("habit_wed", "habit_fri", "habit_tue_lunch"):
                target_wd = weekday_pref
                dates = []
                d = self.today
                while d.weekday() != target_wd:
                    d -= timedelta(days=1)
                # se hoje é o dia habitual e ainda é cedo, o último pedido foi na semana passada
                if d == self.today and self.now_local.hour < (hour_pref or 19):
                    d -= timedelta(days=7)
                for i in range(max_orders):
                    if i < 4 or rnd.random() < 0.9:  # últimas 4 semanas sempre presentes (hábito consistente)
                        dates.append(d)
                    d -= timedelta(days=7)
            for day in dates:
                if day > self.today:
                    continue
                dt_local = self._order_datetime(day, weekday_pref, hour_pref, spec)
                if dt_local > self.now_local:
                    dt_local = self.now_local - timedelta(minutes=rnd.randint(5, 120))
                channel = channel_pref if rnd.random() < 0.7 else rnd.choices(channels, channel_w)[0]
                items = self._pick_products(spec, products, pname, fav, n_people)
                lines = [(0, 0, {"product_id": products[n].product_variant_id.id, "qty": q, "price_unit": products[n].list_price})
                         for n, q in items]
                age_minutes = (self.now_local - dt_local).total_seconds() / 60
                if age_minutes < 20:
                    state = "confirmed"
                elif age_minutes < 45:
                    state = "preparing"
                elif age_minutes < 75:
                    state = "delivering"
                else:
                    state = "delivered"
                if rnd.random() < 0.025:
                    state = "cancelled"
                pay = rnd.choice(pay_by_channel[channel])
                vals_list.append({
                    "restaurant_id": rest.id, "partner_id": partner.id, "date_order": _to_utc(dt_local),
                    "channel": channel, "from_menu": channel == "menu", "state": state, "payment_method": pay,
                    "payment_status": "paid" if state == "delivered" or pay in ("pix", "online_card", "apple_pay", "ifood") else "pending",
                    "delivery_fee": 0.0 if channel == "counter" else rest.delivery_fee,
                    "line_ids": lines,
                })
        # cria em lotes
        for i in range(0, len(vals_list), 300):
            Order.create(vals_list[i:i + 300])
        _logger.info("SalesPilot demo: %s pedidos criados para %s", len(vals_list), rest.name)

    # ------------------------------------------------------------------
    def _create_automations(self, rest):
        Auto = self.env["sp.automation"]
        from odoo.addons.salespilot_restaurant.models.campaign import DEFAULT_TEMPLATES as T
        Auto.create([
            {"name": "Red flag: cliente reduziu a recorrência", "restaurant_id": rest.id, "trigger": "churn", "churn_level": "warning",
             "channel": "whatsapp", "message_template": T["reactivation"], "coupon_code": "VOLTEI15", "discount_pct": 15,
             "min_orders": 3, "cooldown_days": 14, "sequence": 1},
            {"name": "Lembrete de hábito (2h antes do horário de sempre)", "restaurant_id": rest.id, "trigger": "habit", "hours_before": 2,
             "channel": "whatsapp", "message_template": T["habit"], "min_orders": 4, "cooldown_days": 6, "sequence": 2,
             "segment_codes": "champions,loyal,potential_loyal", "create_alert": False},
            {"name": "Aniversário com cupom", "restaurant_id": rest.id, "trigger": "birthday", "days_before": 0,
             "channel": "whatsapp", "message_template": T["birthday"], "coupon_code": "NIVER20", "discount_pct": 20,
             "min_orders": 1, "cooldown_days": 300, "sequence": 3},
            {"name": "Boas-vindas após o 1º pedido", "restaurant_id": rest.id, "trigger": "welcome",
             "channel": "whatsapp", "message_template": T["welcome"], "coupon_code": "BEMVINDO10", "discount_pct": 10,
             "min_orders": 0, "cooldown_days": 90, "sequence": 4, "create_alert": False},
            {"name": "Pesquisa pós-compra (NPS)", "restaurant_id": rest.id, "trigger": "post_purchase",
             "channel": "whatsapp", "message_template": T["post_purchase"], "min_orders": 0, "cooldown_days": 20,
             "sequence": 5, "create_alert": False},
            {"name": "Reativação 45–90 dias sem pedir", "restaurant_id": rest.id, "trigger": "winback", "days_since_min": 45,
             "days_since_max": 90, "channel": "whatsapp", "message_template": T["reactivation"], "coupon_code": "SAUDADE20",
             "discount_pct": 20, "min_orders": 2, "cooldown_days": 30, "sequence": 6, "active": rest.segment == "hamburgueria"},
        ])

    def _create_campaigns(self, rest, spec, products):
        """Campanhas já enviadas (com resultados) + uma agendada."""
        rnd = self.rnd
        env = self.env
        from odoo.addons.salespilot_restaurant.models.campaign import DEFAULT_TEMPLATES as T
        Campaign = env["sp.campaign"]
        Message = env["sp.message"]
        Order = env["sp.order"].with_context(sp_skip_rfv=True, sp_skip_automations=True)
        mains = [name for name, _c, kind, _p, _h, _d, _pair in spec["products"] if kind == "main"]
        plans = [
            ("Reativação de clientes sumidos - outubro", "reactivation", "whatsapp", "at_risk,cant_lose,about_to_sleep,hibernating",
             "VOLTEI15", 15, 38, 0.11),
            ("Lembrete de sexta: {produto} de sempre", "habit", "whatsapp", "champions,loyal", "", 0, 17, 0.22),
            ("Lançamento de novidade no cardápio", "launch", "whatsapp", "champions,loyal,potential_loyal,promising", "", 0, 9, 0.08),
        ]
        if spec["segment"] == "hamburgueria":
            plans.append(("Cupom VIP para Campeões", "vip", "whatsapp", "champions", "VIP10", 10, 26, 0.3))
        for name, ctype, channel, segs, coupon, disc, days_ago, conv in plans:
            fav_name = products[rnd.choice(mains)].name
            camp = Campaign.create({
                "name": name.replace("{produto}", fav_name), "restaurant_id": rest.id, "campaign_type": ctype,
                "channel": channel, "segment_codes": segs, "coupon_code": coupon or False, "discount_pct": disc,
                "message_template": T[ctype], "date_scheduled": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago),
                "state": "draft",
            })
            audience = camp._audience().filtered(lambda p: not (p.sp_whatsapp or "").startswith("(11) 99999-"))
            if not audience:
                audience = env["res.partner"].search([("sp_restaurant_id", "=", rest.id), ("sp_opt_in", "=", True)], limit=25)
            audience = audience[: rnd.randint(25, 60)]
            msgs = Message.create([Message._prepare_from_campaign(camp, p) for p in audience])
            sent_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago, hours=rnd.randint(1, 5))
            msgs.write({"state": "delivered", "provider": "simulation", "date_sent": sent_dt})
            camp.write({"state": "sent" if days_ago < 14 else "done", "date_sent": sent_dt})
            # cliques e pedidos atribuídos
            for msg in msgs:
                r = rnd.random()
                if r < conv * 2.2:
                    msg.write({"clicked": True, "date_clicked": sent_dt + timedelta(hours=rnd.randint(1, 30)), "state": "read"})
                if r < conv:
                    day_dt = sent_dt + timedelta(hours=rnd.randint(2, 70))
                    if day_dt > datetime.now(timezone.utc).replace(tzinfo=None):
                        continue
                    fav = msg.partner_id.sp_favorite_product_id.product_tmpl_id
                    fav_n = fav.name if fav and fav.name in products else rnd.choice(mains)
                    items = self._pick_products(spec, products, "camp", fav_n, 1 if rnd.random() < 0.6 else 2)
                    subtotal = sum(products[n].list_price * q for n, q in items)
                    Order.create({
                        "restaurant_id": rest.id, "partner_id": msg.partner_id.id, "date_order": day_dt, "channel": "menu", "from_menu": True,
                        "state": "delivered", "payment_method": rnd.choice(["pix", "online_card", "card_delivery"]),
                        "payment_status": "paid", "delivery_fee": rest.delivery_fee, "coupon_code": coupon or False,
                        "discount_amount": subtotal * disc / 100.0, "campaign_id": camp.id, "message_id": msg.id,
                        "recommendation_accepted": rnd.random() < 0.3,
                        "line_ids": [(0, 0, {"product_id": products[n].product_variant_id.id, "qty": q,
                                             "price_unit": products[n].list_price, "recommended": i > 0 and rnd.random() < 0.3})
                                     for i, (n, q) in enumerate(items)],
                    })
            camp._compute_stats()
        # Uma campanha agendada para amanhã
        Campaign.create({
            "name": "Fim de semana: combo pra família", "restaurant_id": rest.id, "campaign_type": "launch", "channel": "whatsapp",
            "segment_codes": "champions,loyal,potential_loyal,need_attention", "message_template":
                "Oi {nome}! Fim de semana chegando 🙌 No {restaurante} tem combo pra família com entrega grátis até domingo. Garanta o seu: {link}",
            "date_scheduled": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1), "state": "scheduled",
        })

    # ------------------------------------------------------------------
    def _create_users(self, restaurants):
        env = self.env
        admin = env.ref("base.user_admin")
        rests = env["sp.restaurant"].browse([r[0].id for r in restaurants])
        admin.write({"sp_restaurant_ids": [(6, 0, rests.ids)],
                     "groups_id": [(4, env.ref("salespilot_restaurant.group_sp_admin").id)]})
        burger = rests.filtered(lambda r: r.segment == "hamburgueria")
        Users = env["res.users"]
        if Users.with_context(active_test=False).search_count([("login", "in", ("diogo", "lucia"))]):
            return
        Users.create({
            "name": "Diogo (Burger do Diogo)", "login": "diogo", "password": "diogo123", "lang": "pt_BR", "tz": "America/Sao_Paulo",
            "email": "diogo@burgerdodiogo.com.br",
            "groups_id": [(6, 0, [env.ref("base.group_user").id, env.ref("salespilot_restaurant.group_sp_manager").id])],
            "sp_restaurant_ids": [(6, 0, burger.ids)],
        })
        pizza = rests.filtered(lambda r: r.segment == "pizzaria")
        Users.create({
            "name": "Lúcia (Pizzaria Nonna Lúcia)", "login": "lucia", "password": "lucia123", "lang": "pt_BR", "tz": "America/Sao_Paulo",
            "email": "lucia@nonnalucia.com.br",
            "groups_id": [(6, 0, [env.ref("base.group_user").id, env.ref("salespilot_restaurant.group_sp_manager").id])],
            "sp_restaurant_ids": [(6, 0, pizza.ids)],
        })

    def _create_prospects(self):
        env = self.env
        rnd = self.rnd
        team = env.ref("salespilot_restaurant.crm_team_salespilot")
        stages = [env.ref(f"salespilot_restaurant.stage_prospect_{s}") for s in ("new", "qualified", "meeting", "proposal", "won")]
        stage_weights = [0.35, 0.3, 0.15, 0.12, 0.08]
        leads = []
        for i, (name, seg, hood, g_rating, g_rev, on_ifood, i_rating, insta, followers, own_menu, orders, ticket) in enumerate(PROSPECTS):
            stage = rnd.choices(stages, stage_weights)[0]
            leads.append({
                "name": f"{name} — piloto SalesPilot", "partner_name": name, "type": "opportunity", "team_id": team.id,
                "stage_id": stage.id, "sp_is_restaurant": True, "sp_segment": seg, "sp_neighborhood": hood, "city": "São Paulo",
                "sp_google_rating": g_rating, "sp_google_reviews": g_rev, "sp_on_ifood": on_ifood, "sp_ifood_rating": i_rating,
                "sp_instagram": insta, "sp_instagram_followers": followers, "sp_has_own_menu": own_menu,
                "sp_uses_whatsapp_orders": True, "sp_monthly_orders_est": orders, "sp_avg_ticket_est": ticket,
                "expected_revenue": round((120 + orders * ticket * 0.4 * 0.01) * 12, 2),
                "phone": self._phone(), "email_from": f"contato@{name.lower().split()[0]}.com.br",
                "description": f"<p>Prospect encontrado via análise de Google Maps / iFood ({hood}). "
                               f"{g_rev} avaliações no Google, nota {g_rating}. "
                               f"{'Opera no iFood' if on_ifood else 'Não está no iFood'}; "
                               f"{'já tem cardápio próprio' if own_menu else 'sem cardápio próprio'}.</p>",
                "user_id": env.ref("base.user_admin").id,
            })
        created = env["crm.lead"].create(leads)
        created.action_sp_qualify()

    def _create_billing(self, rests):
        Billing = self.env["sp.billing.period"]
        today = self.today
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        for r in rests:
            prev = Billing.generate_for_month(r, last_prev.year, last_prev.month)
            prev.write({"state": "issued"})
            Billing.generate_for_month(r, today.year, today.month)
