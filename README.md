# SalesPilot — CRM e Retenção para Pequenos Restaurantes de Delivery

Piloto construído sobre **Odoo 18 Community (open source)**, a partir da transcrição da reunião
de 23/11 ("Plataforma de CRM e Retenção para Pequenos Restaurantes de Delivery").

A ideia central da conversa: um CRM de **relacionamento e retenção** (não de pipeline) para
pizzarias, hamburguerias e temakerias que vendem por delivery — matriz RFV, perfil de consumo,
disparos de WhatsApp/SMS por comportamento (aniversário, hábito, "red flag" de recorrência),
cardápio digital próprio com recomendações, e cobrança por sucesso (R$ 120/mês + 1% da receita
rastreada), bem mais barata que os 20–25% do marketplace.

> **Fora do escopo deste piloto (por decisão do briefing):** API oficial da Meta/WhatsApp,
> integrações com ERP / nota fiscal e gateway de pagamento. Tudo isso tem o ponto de encaixe
> pronto no código, mas no piloto os envios são **simulados** (caixa de saída) e o pagamento é
> **simulado** no cardápio.

---

## 1. Como subir o piloto

### Opção A — Docker (recomendado)

```bash
git clone <este repositório> salespilot && cd salespilot
docker compose up -d
# primeira execução: ~2 minutos (cria o banco em pt-BR, instala os módulos e gera os dados fictícios)
docker compose logs -f odoo   # aguarde "SalesPilot: banco pronto."
```

Acesse **http://localhost:8069**.

### Opção B — sem Docker (código-fonte do Odoo)

Requer PostgreSQL local (usuário `odoo` / senha `odoo`, com permissão de criar banco), Python 3.10–3.12 e git.

```bash
./scripts/run_local.sh            # clona o Odoo 18, cria o venv, o banco e sobe em :8069
./scripts/run_local.sh --reset    # recria o banco com os dados de demonstração do zero
```

### Logins

| Usuário | Senha | Perfil |
|---|---|---|
| `admin` | `admin` | Administrador SalesPilot (operadora) — vê os 3 restaurantes, prospecção e faturas |
| `diogo` | `diogo123` | Gestor do **Burger do Diogo** — só vê os dados do próprio restaurante |
| `lucia` | `lucia123` | Gestora da **Pizzaria Nonna Lúcia** |

### Cardápios digitais públicos (sem login)

- http://localhost:8069/cardapio/burger-do-diogo
- http://localhost:8069/cardapio/pizzaria-nonna-lucia
- http://localhost:8069/cardapio/temakeria-oishii

---

## 2. O que foi construído

Dois módulos em `addons/`:

| Módulo | Função |
|---|---|
| `salespilot_restaurant` | O produto: modelos, motor RFV, campanhas, réguas, alertas, insights, cardápio digital, dashboard, cobrança por sucesso, prospecção |
| `salespilot_demo` | Dados fictícios coerentes com o negócio (3 restaurantes, ~380 clientes, ~3.700 pedidos em 180 dias, campanhas já enviadas, réguas ativas, 15 prospects, faturas) |

### 2.1 Base de clientes + Matriz RFV
Cada cliente (`res.partner` estendido) ganha, calculado diariamente por cron ou pelo botão **Recalcular**:

- **R, F, V** (1–5) e segmento: *Campeões, Clientes fiéis, Potenciais fiéis, Novos, Promissores,
  Precisam de atenção, Prestes a dormir, Em risco, Não pode perder, Hibernando, Perdidos*.
  Recência em dias absolutos; Frequência e Valor em quintis relativos à base do restaurante.
- **Perfil de consumo**: produto favorito, dia da semana e hora habitual, intervalo típico entre
  pedidos (mediana), próximo pedido esperado, canal preferido, LTV, ticket médio.
- **Red flag de recorrência**: dias sem pedir ÷ intervalo típico. ≥ 1,5× = *Atenção*; ≥ 2,5× =
  *Crítico* (o "Diogo não comprou faz duas semanas" da transcrição).
- Resumo em texto no topo da ficha ("Pede a cada 7 dias, geralmente na quarta por volta das 18h. Favorito: Smash Burger").

Menus: **Clientes › Base de clientes / Matriz RFV (kanban por segmento + pivô R×F) / Red flags**.

### 2.2 Pedidos e cardápio
- `sp.order` com itens, canal (cardápio digital, WhatsApp, iFood, telefone, balcão), pagamento,
  status (confirmado → em preparo → saiu → entregue), cupom e **atribuição** (campanha/régua/mensagem).
- Cardápio por restaurante em `product.template` (categoria, tipo, destaque, "combina com", vendas 90 dias).

### 2.3 Cardápio digital público (`/cardapio/<slug>`)
- Mobile-first, sem login. O cliente informa o WhatsApp → **pop-up personalizado** com saudação
  por perfil ("Quarta é dia de Smash Burger, né?", "Que saudade, faz 23 dias…", "Você é VIP 🏆")
  e recomendações (favorito + itens que acompanham + mais pedidos).
- **Upsell/cross-sell na sacola**: coocorrência de itens ("44% de quem pede Smash leva Batata") e
  regra de upgrade (2+ principais sem bebida grande → sugere a 2L, "sai mais em conta que duas latas").
- Checkout cria o pedido, identifica/cadastra o cliente pelo telefone, aplica cupom de campanha e
  registra pagamento **simulado** (Pix copia-e-cola fictício, cartão online, Apple/Google Pay, na entrega).
- Página de acompanhamento do pedido.

### 2.4 Campanhas e caixa de saída (WhatsApp / SMS / e-mail)
- Tipos: avulsa, reativação, lembrete de hábito, aniversário, boas-vindas, pós-compra, lançamento, VIP.
- Público por segmentos RFV, risco, dias sem pedir, favorito, opt-in — com contagem ao vivo e "Ver público".
- Mensagem com variáveis `{nome} {produto_favorito} {cupom} {desconto} {link} {restaurante} {dia_semana} {dias_sem_pedir}`
  e botão **✨ Sugerir texto** (gerador local; opcionalmente um LLM via parâmetro `salespilot.llm_api_key`).
- Cada destinatário recebe um **link rastreado** `/c/<token>` → registra o clique, abre o cardápio e
  grava cookie de atribuição por 30 dias. Pedidos feitos depois contam para a campanha
  (**cliques, conversão, receita atribuída, custo e ROI**).
- Provedor de envio = `simulation` (parâmetro `salespilot.message_provider`). A integração com a
  WhatsApp Cloud API entra em `sp.message._provider_send_meta` quando for o momento.

### 2.5 Réguas automáticas (`sp.automation`)
Rodam por cron (hora em hora) respeitando janela de envio e intervalo mínimo entre mensagens:

| Gatilho | Exemplo na demo |
|---|---|
| Red flag de recorrência | 1,5× o intervalo típico → WhatsApp com cupom VOLTEI15 + alerta para a equipe |
| Lembrete de hábito | 2h antes do dia/horário habitual, só para fiéis/campeões |
| Aniversário | no dia, cupom NIVER20 |
| Boas-vindas | após o 1º pedido, cupom BEMVINDO10 |
| Pós-compra | pedido entregue → pesquisa NPS |
| Reativação 45–90 dias | cupom SAUDADE20 |

### 2.6 Alertas, insights e dashboard
- **Alertas**: cliente sumiu / campeão em risco / atraso de recorrência / aniversário / novo campeão,
  com botão **Enviar WhatsApp** (assistente pré-preenchido) e resolução automática quando o cliente volta a comprar.
- **Insights** gerados a cada recálculo: receita em risco, Pareto dos campeões, novos sem 2ª compra,
  pico de demanda, combos sugeridos por coocorrência, dependência de iFood (economia em comissão),
  aniversários da semana, melhor campanha — cada um com botão que abre a campanha pronta.
- **Dashboard** (OWL): KPIs de 30 dias com variação, matriz RFV 5×5 clicável, segmentos, receita por
  semana, mapa de calor dia × hora, canais, campanhas, alertas, aniversários, mais vendidos e o
  bloco **"Seu plano SalesPilot"** (receita rastreada, taxa de sucesso, economia vs. marketplace).

### 2.7 Lado da operadora (menu "SalesPilot (operadora)", só admin)
- **Restaurantes**: cadastro multi-restaurante com usuários vinculados; regras de registro isolam os dados.
- **Faturas (mensalidade + sucesso)**: por mês e restaurante — receita rastreada pela jornada
  SalesPilot, 1% de taxa, mensalidade R$ 120, custo efetivo e economia vs. ~23% de marketplace.
- **Prospecção de restaurantes**: pipeline no CRM do Odoo (Prospectado → Qualificado (IA) → Reunião →
  Proposta/piloto → Cliente ativo) com campos de Google/iFood/Instagram e **score de qualificação**
  + receita potencial, botão "✨ Qualificar prospect".

---

## 3. Roteiro sugerido de teste (15 min)

1. **Dashboard** (`admin`): troque de restaurante no seletor; clique em *Red flags* e nos segmentos da matriz.
2. **Clientes › Base de clientes**: abra **Diogo Martins** (aba SalesPilot): pede toda quarta ~18h, favorito Smash Burger.
   Abra **Ana Paula Ferreira**: era semanal e está há 20+ dias sem pedir → *Crítico* com alerta aberto.
3. **Clientes › Alertas**: em um alerta, clique **Enviar WhatsApp**, veja a prévia renderizada e envie.
   A mensagem aparece em **Relacionamento › Caixa de saída** (provedor simulação).
4. **Caixa de saída**: clique no ícone de link de uma mensagem — isso simula o cliente clicando no
   WhatsApp: abre o cardápio com o cupom aplicado. Faça um pedido. Volte à campanha/régua e veja
   *cliques, pedidos atribuídos e receita* atualizados.
5. **Cardápio** `/cardapio/burger-do-diogo` no celular: digite `(11) 99999-0001` (Diogo) ou
   `(11) 99999-0002` (Ana Paula) e veja o pop-up personalizado; adicione 2 burgers e veja a sugestão da 2L.
6. **Relacionamento › Campanhas**: *Nova* → tipo *Reativação* (público e cupom já vêm preenchidos) →
   *Ver público* → *✨ Sugerir texto* → *Enviar agora*.
7. **Réguas automáticas**: abra "Red flag" → *Ver elegíveis agora* / *Executar agora*.
8. **Insights**: clique em *Criar campanha de reativação* em um insight.
9. **SalesPilot (operadora) › Faturas**: abra a fatura do mês e confira o cálculo (R$ 120 + 1%).
10. **Prospecção de restaurantes**: kanban dos 15 prospects; abra um e clique *✨ Qualificar prospect*.
11. Entre como `diogo` / `diogo123`: só o Burger do Diogo aparece em todos os menus.

---

## 4. Decisões técnicas

- **Odoo 18 Community** puro; dependências apenas de módulos community (`base, web, mail, contacts, product, crm`).
- Sem serviços externos: RFV, hábitos, coocorrência e insights são estatística local sobre os pedidos.
  A camada de IA generativa (texto de campanha) é opcional e desligada por padrão.
- Multi-restaurante por modelo `sp.restaurant` + regras de registro (`ir.rule`) por usuário, em vez de
  multi-empresa, para manter o cardápio público e o onboarding simples.
- O cardápio digital é um controlador HTTP com template QWeb próprio (não usa o módulo `website`),
  leve o bastante para rodar bem no celular.
- Pontos de extensão para a próxima fase: `sp.message._provider_send_meta` (WhatsApp Cloud API),
  `payment_method`/`payment_status` no pedido (gateway Pix/cartão), `sp.order` como fonte para ERP/NF-e.

## 5. Estrutura

```
addons/salespilot_restaurant/   módulo principal (models, views, controllers, static/dashboard, wizards)
addons/salespilot_demo/         gerador de dados de demonstração (post_init_hook)
docker-compose.yml, odoo.conf, docker/entrypoint.sh   subida com Docker
scripts/run_local.sh            subida a partir do código-fonte
```
