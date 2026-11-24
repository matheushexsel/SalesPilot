"""Modelo de coorte simples para projetar receita do SalesPilot em 12 meses.

Hipóteses (todas parametrizadas abaixo):
- Novos restaurantes por mês por cenário.
- Churn mensal (benchmark SMB SaaS 3%/mês; conservador 4%, otimista 2%).
- Receita do canal próprio por restaurante cresce com a idade da conta (rampa).
- Primeiros 20 contratos: plano Fundador (R$ 120 + 1%); depois: Essencial (R$ 149 + 2%, teto R$ 499).
- Parte variável zerada nos 2 primeiros meses de cada conta (60 dias de carência).
- Nenhum custo da Meta (cobrado à parte do restaurante).
"""

FOUNDER_LIMIT = 20
FOUNDER = dict(fee=120.0, pct=0.01, cap=None)
ESSENCIAL = dict(fee=149.0, pct=0.02, cap=499.0)
GRACE_MONTHS = 2

# Receita mensal do canal próprio por idade da conta (meses desde a ativação), em R$.
# Restaurante típico com ~R$ 60 mil/mês de delivery migrando gradualmente ~1/3 para o canal próprio.
RAMP_BASE = {1: 1500, 2: 3000, 3: 5000, 4: 7000, 5: 9000, 6: 11000, 7: 12500, 8: 14000, 9: 15500, 10: 17000, 11: 18000, 12: 19000}

SCENARIOS = {
    "conservador": dict(new=[3, 3, 4, 4, 5, 5, 6, 6, 6, 7, 7, 7], churn=0.04, ramp_mult=0.6),
    "base":        dict(new=[4, 5, 6, 8, 8, 10, 10, 12, 12, 12, 14, 14], churn=0.03, ramp_mult=1.0),
    "otimista":    dict(new=[5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26], churn=0.02, ramp_mult=1.3),
}

# Custos fixos mensais (R$), sem Meta. Dois níveis de estrutura.
COSTS = {
    "enxuto": {  # fundadores vendem e fazem onboarding; 1 dev pleno PJ meio período + infra
        "infra": 600, "ferramentas": 400, "dev": 6000, "cs_onboarding": 0, "vendas": 0, "marketing": 1500, "contabilidade": 700,
    },
    "time": {    # 1 dev pleno, 1 CS/onboarding, 1 SDR com variável, mídia paga
        "infra": 1200, "ferramentas": 900, "dev": 12000, "cs_onboarding": 6000, "vendas": 5000, "marketing": 3000, "contabilidade": 800,
    },
}
TAX_RATE = 0.06        # Simples Nacional, faixa inicial (sobe para ~11% acima de R$ 180 mil/ano de receita)
BILLING_COST = 2.5     # R$ por cobrança (boleto/Pix via Asaas e similares)
ONBOARDING_HOURS = 5   # horas de pessoa por restaurante novo
ONBOARDING_HOUR_COST = 60.0


def plan_for(index):
    return FOUNDER if index < FOUNDER_LIMIT else ESSENCIAL


def revenue_for(plan, age, own_channel):
    var = 0.0
    if age > GRACE_MONTHS:
        var = own_channel * plan["pct"]
        if plan["cap"]:
            var = min(var, plan["cap"])
    return plan["fee"] + var


def run(name, sc, cost_level):
    accounts = []  # dicts: idx, start_month, alive
    idx = 0
    rows = []
    cum_rev = cum_result = 0.0
    for m in range(1, 13):
        # churn no início do mês (contas com pelo menos 1 mês)
        for a in accounts:
            if a["alive"] and a["start"] < m:
                a["alive_frac"] *= (1 - sc["churn"])
        # novas contas
        new = sc["new"][m - 1]
        for _ in range(new):
            accounts.append({"idx": idx, "start": m, "alive": True, "alive_frac": 1.0}); idx += 1
        mrr = 0.0; var_total = 0.0; active = 0.0; own_total = 0.0
        for a in accounts:
            age = m - a["start"] + 1
            own = RAMP_BASE[min(age, 12)] * sc["ramp_mult"]
            plan = plan_for(a["idx"])
            rev = revenue_for(plan, age, own)
            mrr += rev * a["alive_frac"]; active += a["alive_frac"]; own_total += own * a["alive_frac"]
            var_total += (rev - plan["fee"]) * a["alive_frac"]
        costs = COSTS[cost_level]
        fixed = sum(costs.values())
        variable_costs = new * ONBOARDING_HOURS * ONBOARDING_HOUR_COST + active * BILLING_COST + mrr * TAX_RATE
        total_cost = fixed + variable_costs
        result = mrr - total_cost
        cum_rev += mrr; cum_result += result
        rows.append(dict(m=m, new=new, active=active, mrr=mrr, var=var_total, own=own_total, cost=total_cost, result=result, cum_rev=cum_rev, cum_result=cum_result))
    return rows


if __name__ == "__main__":
    for level in ("enxuto", "time"):
        print(f"\n===== Estrutura: {level} (custo fixo R$ {sum(COSTS[level].values()):,.0f}/mês)")
        for name, sc in SCENARIOS.items():
            rows = run(name, sc, level)
            print(f"\n--- Cenário {name} (churn {sc['churn']:.0%}/mês)")
            print(f"{'mês':>3} {'novos':>5} {'ativos':>7} {'MRR':>10} {'variável':>9} {'canal próprio':>14} {'custo':>9} {'resultado':>10} {'acum.rec':>10} {'acum.res':>10}")
            for r in rows:
                if r["m"] in (1, 2, 3, 6, 9, 12):
                    print(f"{r['m']:>3} {r['new']:>5} {r['active']:>7.1f} {r['mrr']:>10,.0f} {r['var']:>9,.0f} {r['own']:>14,.0f} {r['cost']:>9,.0f} {r['result']:>10,.0f} {r['cum_rev']:>10,.0f} {r['cum_result']:>10,.0f}")
            r12 = rows[-1]
            print(f"ARR saída (MRR mês 12 x 12): R$ {r12['mrr']*12:,.0f} | ARPU mês 12: R$ {r12['mrr']/r12['active']:,.0f}")
