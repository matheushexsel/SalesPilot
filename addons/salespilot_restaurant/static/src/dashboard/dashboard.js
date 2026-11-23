/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const HOURS = Array.from({ length: 13 }, (_, i) => i + 11); // 11h..23h

function brl(v) {
    return (v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}
function pct(v, digits = 0) {
    return (v || 0).toLocaleString("pt-BR", { maximumFractionDigits: digits }) + "%";
}
function delta(cur, prev) {
    if (!prev) return null;
    return ((cur - prev) / prev) * 100;
}

export class SpDashboard extends Component {
    static template = "salespilot_restaurant.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, data: null, restaurantId: null, tab: "overview" });
        this.weekRef = useRef("weekChart");
        this.channelRef = useRef("channelChart");
        this.charts = [];
        this.brl = brl;
        this.pct = pct;
        this.delta = delta;
        this.HOURS = HOURS;

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            const ctxId = this.props.action && this.props.action.context && this.props.action.context.default_restaurant_id;
            await this.load(ctxId || null);
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => this.destroyCharts());
    }

    async load(restaurantId) {
        this.state.loading = true;
        const data = await this.orm.call("sp.restaurant", "get_dashboard_data", [restaurantId]);
        this.state.data = data;
        this.state.restaurantId = data.restaurant ? data.restaurant.id : null;
        this.state.loading = false;
        // Charts need the DOM; defer to next tick
        setTimeout(() => this.renderCharts(), 0);
    }

    async onRestaurantChange(ev) {
        await this.load(parseInt(ev.target.value));
    }

    get k() {
        return this.state.data ? this.state.data.kpis : {};
    }

    matrixColor(count) {
        const max = Math.max(1, ...this.state.data.matrix.flat());
        const a = count ? 0.15 + 0.85 * (count / max) : 0.04;
        return `rgba(42, 120, 214, ${a.toFixed(2)})`;
    }
    heatColor(count) {
        const max = Math.max(1, ...this.state.data.heat.flat());
        const a = count ? 0.12 + 0.88 * (count / max) : 0.03;
        return `rgba(42, 120, 214, ${a.toFixed(2)})`;
    }
    heatValue(wd, hour) {
        return this.state.data.heat[wd][hour] || 0;
    }
    matrixLabel(rowIdx, colIdx) {
        return this.state.data.matrix[rowIdx][colIdx];
    }

    destroyCharts() {
        this.charts.forEach((c) => c.destroy());
        this.charts = [];
    }

    renderCharts() {
        this.destroyCharts();
        if (!this.state.data || !window.Chart) return;
        const d = this.state.data;
        if (this.weekRef.el) {
            this.charts.push(new Chart(this.weekRef.el, {
                type: "bar",
                data: {
                    labels: d.weeks.map((w) => w.week),
                    datasets: [{ label: "Receita", data: d.weeks.map((w) => Math.round(w.revenue)), backgroundColor: SERIES[0],
                                 borderRadius: 4, maxBarThickness: 28 }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${brl(c.raw)} · ${d.weeks[c.dataIndex].orders} pedidos` } } },
                    scales: { x: { grid: { display: false } }, y: { ticks: { callback: (v) => brl(v) }, grid: { color: "#eee" } } },
                },
            }));
        }
        if (this.channelRef.el) {
            this.charts.push(new Chart(this.channelRef.el, {
                type: "bar",
                data: {
                    labels: d.channels.map((c) => c.label),
                    datasets: [{ label: "Receita 90 dias", data: d.channels.map((c) => Math.round(c.revenue)),
                                 backgroundColor: d.channels.map((_, i) => SERIES[i % SERIES.length]), borderRadius: 4, maxBarThickness: 22 }],
                },
                options: {
                    indexAxis: "y", responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${brl(c.raw)} · ${d.channels[c.dataIndex].orders} pedidos` } } },
                    scales: { x: { ticks: { callback: (v) => brl(v) }, grid: { color: "#eee" } }, y: { grid: { display: false } } },
                },
            }));
        }
    }

    // ---------------- ações ----------------
    async openServerAction(xmlid, domain, name, context) {
        const action = await this.orm.call("sp.restaurant", "get_dashboard_action",
            [xmlid, this.state.restaurantId, domain || [], name || false, context || {}]);
        if (action) {
            await this.action.doAction(action);
        }
    }
    openCustomers(domain, name) {
        return this.openServerAction("action_sp_customers", domain, name || "Clientes");
    }
    openSegment(seg) {
        this.openCustomers([["sp_segment", "=", seg.code]], `Clientes: ${seg.label}`);
    }
    openRisk() {
        this.openCustomers([["sp_churn_risk", "in", ["warning", "critical"]]], "Red flags");
    }
    openNew() {
        this.openCustomers([["sp_first_order_date", ">=", this.state.data.since_30d]], "Novos clientes (30 dias)");
    }
    openAlerts() {
        return this.openServerAction("action_sp_alerts", [["state", "=", "open"]], "Alertas", {});
    }
    openAlert(alert) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "sp.alert", res_id: alert.id, views: [[false, "form"]] });
    }
    openPartner(id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "res.partner", res_id: id, views: [[false, "form"]] });
    }
    openCampaign(c) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "sp.campaign", res_id: c.id, views: [[false, "form"]] });
    }
    openOrders(domain, name) {
        return this.openServerAction("action_sp_orders", domain, name || "Pedidos");
    }
    openMenu() {
        window.open(`/cardapio/${this.state.data.restaurant.slug}`, "_blank");
    }
    _normalize(action) {
        // Ações devolvidas por métodos Python trazem só view_mode; o action manager exige "views".
        if (action && action.type === "ir.actions.act_window" && !action.views) {
            action.views = (action.view_mode || "list,form").split(",").map((m) => [false, m.trim()]);
        }
        return action;
    }
    async sendAlertMessage(alert) {
        const action = this._normalize(await this.orm.call("sp.alert", "action_send_message", [[alert.id]]));
        await this.action.doAction(action, { onClose: () => this.load(this.state.restaurantId) });
    }
    async applyInsight(ins) {
        const action = this._normalize(await this.orm.call("sp.insight", "action_apply", [[ins.id]]));
        if (action && action.type) {
            await this.action.doAction(action);
        } else {
            await this.load(this.state.restaurantId);
        }
    }
    async dismissInsight(ins) {
        await this.orm.call("sp.insight", "action_dismiss", [[ins.id]]);
        await this.load(this.state.restaurantId);
    }
    async recompute() {
        this.state.loading = true;
        await this.orm.call("sp.restaurant", "action_recompute_rfv", [[this.state.restaurantId]]);
        this.notification.add("RFV, insights e alertas recalculados.", { type: "success" });
        await this.load(this.state.restaurantId);
    }
    newCampaign(type) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "sp.campaign", views: [[false, "form"]], target: "current",
            context: { default_restaurant_id: this.state.restaurantId, default_campaign_type: type || "manual" } });
    }
    trendClass(v) {
        if (v === null || v === undefined) return "text-muted";
        return v >= 0 ? "text-success" : "text-danger";
    }
    trendText(v) {
        if (v === null || v === undefined) return "—";
        return (v >= 0 ? "▲ " : "▼ ") + Math.abs(v).toFixed(0) + "% vs. 30 dias anteriores";
    }
}

registry.category("actions").add("salespilot_dashboard", SpDashboard);
