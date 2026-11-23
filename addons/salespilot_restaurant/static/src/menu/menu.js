(function () {
    const CONFIG = JSON.parse(document.getElementById('sp-config').textContent);
    const SLUG = CONFIG.slug, TOKEN = CONFIG.token, DELIVERY = CONFIG.delivery_fee;
    const PRODUCTS = JSON.parse(document.getElementById('sp-products').textContent);
    const CATEGORIES = JSON.parse(document.getElementById('sp-categories').textContent);
    const byId = Object.fromEntries(PRODUCTS.map(p => [p.id, p]));
    const cart = {};           // id -> qty
    const recommended = new Set();
    let customer = null;
    const brl = v => 'R$ ' + (v || 0).toFixed(2).replace('.', ',');
    const $ = s => document.querySelector(s);

    async function rpc(path, params) {
        const r = await fetch('/cardapio/' + SLUG + '/api/' + path, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', id: Date.now(), params: params || {}}),
        });
        const data = await r.json();
        if (data.error) { throw new Error((data.error.data && data.error.data.message) || data.error.message); }
        return data.result;
    }

    function emoji(kind) { return {main: '🍽️', side: '🍟', drink: '🥤', dessert: '🍮', combo: '🎁'}[kind] || '🍽️'; }

    function renderMenu() {
        const cats = $('#cats'); const menu = $('#menu');
        cats.innerHTML = ''; menu.innerHTML = '';
        const groups = CATEGORIES.map(c => ({...c, items: PRODUCTS.filter(p => p.category_id === c.id)})).filter(g => g.items.length);
        const orphan = PRODUCTS.filter(p => !CATEGORIES.some(c => c.id === p.category_id));
        if (orphan.length) groups.push({id: 0, name: 'Outros', items: orphan});
        groups.forEach((g, i) => {
            const a = document.createElement('a'); a.href = '#cat-' + g.id; a.textContent = g.name; if (i === 0) a.classList.add('active');
            a.onclick = () => { cats.querySelectorAll('a').forEach(x => x.classList.remove('active')); a.classList.add('active'); };
            cats.appendChild(a);
            const h = document.createElement('h2'); h.className = 'cat'; h.id = 'cat-' + g.id; h.textContent = g.name; menu.appendChild(h);
            const grid = document.createElement('div'); grid.className = 'grid';
            g.items.forEach(p => grid.appendChild(card(p)));
            menu.appendChild(grid);
        });
    }

    function card(p) {
        const el = document.createElement('div'); el.className = 'card'; el.id = 'p-' + p.id;
        const img = p.has_image ? `<img src="/cardapio/${SLUG}/img/${p.id}" alt=""/>` : `<div class="ph">${emoji(p.kind)}</div>`;
        el.innerHTML = `${img}<div class="body">
            <div class="name">${p.name} ${p.highlight ? '<span class="badge">destaque</span>' : ''} ${customer && customer.favorite_id === p.id ? '<span class="badge rec">seu favorito</span>' : ''}</div>
            <div class="desc">${p.description || ''}</div>
            <div class="row"><span class="price">${brl(p.price)}</span>
                <div class="qty"><button data-d="-1">−</button><span id="q-${p.id}">${cart[p.id] || 0}</span><button class="add" data-d="1">+</button></div></div>
        </div>`;
        el.querySelectorAll('.qty button').forEach(b => b.onclick = () => change(p.id, parseInt(b.dataset.d)));
        return el;
    }

    function change(id, d, fromRec) {
        cart[id] = Math.max((cart[id] || 0) + d, 0);
        if (!cart[id]) { delete cart[id]; recommended.delete(id); }
        if (fromRec && cart[id]) recommended.add(id);
        const q = document.getElementById('q-' + id); if (q) q.textContent = cart[id] || 0;
        updateBar();
    }

    function items() { return Object.entries(cart).map(([id, qty]) => ({id: +id, qty, name: byId[id].name, kind: byId[id].kind})); }
    function subtotal() { return items().reduce((s, it) => s + it.qty * byId[it.id].price, 0); }

    function updateBar() {
        const n = items().reduce((s, it) => s + it.qty, 0);
        $('#cartbar').style.display = n ? 'block' : 'none';
        $('#cart-count').textContent = n; $('#cart-total').textContent = brl(subtotal());
    }

    let suggTimer = null;
    async function renderCart() {
        const box = $('#cart-lines'); box.innerHTML = '';
        items().forEach(it => {
            const d = document.createElement('div'); d.className = 'line';
            d.innerHTML = `<span>${it.qty}x ${it.name}</span><span class="qty"><button data-d="-1">−</button><button class="add" data-d="1">+</button><strong style="margin-left:8px">${brl(it.qty * byId[it.id].price)}</strong></span>`;
            d.querySelectorAll('button').forEach(b => b.onclick = () => { change(it.id, parseInt(b.dataset.d)); renderCart(); });
            box.appendChild(d);
        });
        $('#c-sub').textContent = brl(subtotal()); $('#c-total').textContent = brl(subtotal() + DELIVERY);
        clearTimeout(suggTimer);
        suggTimer = setTimeout(loadSuggestions, 250);
    }

    async function loadSuggestions() {
        const its = items(); const sb = $('#sugg-box'); const sl = $('#sugg-list');
        if (!its.length) { sb.style.display = 'none'; return; }
        try {
            const res = await rpc('suggest', {items: its});
            const sug = (res.suggestions || []).filter(s => !cart[s.id]);
            sl.innerHTML = '';
            sug.forEach(s => {
                const d = document.createElement('div'); d.className = 's';
                d.innerHTML = `<div><strong>${s.name}</strong> · ${brl(s.price)}<small>${s.reason}</small></div><button class="btn sm">+ Adicionar</button>`;
                d.querySelector('button').onclick = () => { change(s.id, 1, true); renderCart(); };
                sl.appendChild(d);
            });
            sb.style.display = sug.length ? 'block' : 'none';
        } catch (e) { sb.style.display = 'none'; }
    }

    async function identify(silent) {
        const phone = $('#phone').value.trim();
        if (phone.replace(/\D/g, '').length < 10) { if (!silent) alert('Digite o WhatsApp com DDD.'); return; }
        $('#f-phone').value = phone;
        const res = await rpc('identify', {phone});
        customer = res;
        if (res.known) {
            if (res.trusted) { $('#f-name').value = res.name || ''; $('#f-address').value = res.address || ''; }
            else { if (!$('#f-name').value) $('#f-name').value = res.first_name || ''; if (res.address_hint) $('#f-address').placeholder = 'Mesmo endereço de sempre? (' + res.address_hint + ')'; }
            $('#identify-hint').textContent = 'Olá, ' + res.first_name + '! Recomendações personalizadas ativadas.';
        } else {
            $('#identify-hint').textContent = 'Primeiro pedido? Bem-vindo(a)! Ganhe mimos nas próximas compras.';
        }
        renderMenu();
        $('#rec-title').textContent = res.greeting;
        const list = $('#rec-list'); list.innerHTML = '';
        (res.recommendations || []).forEach(r => {
            const d = document.createElement('div'); d.className = 'rec-card';
            d.innerHTML = `<div><strong>${r.name}</strong><div class="muted">${r.reason} · ${brl(r.price)}</div></div><button class="btn sm">+ Adicionar</button>`;
            d.querySelector('button').onclick = () => { change(r.id, 1, true); d.querySelector('button').textContent = '✓ Na sacola'; };
            list.appendChild(d);
        });
        $('#rec-modal').classList.add('open');
    }

    async function checkout() {
        $('#c-err').textContent = '';
        const pay = document.querySelector('input[name=pay]:checked').value;
        const btn = $('#btn-checkout'); btn.disabled = true; btn.textContent = 'Enviando...';
        try {
            const res = await rpc('checkout', {
                phone: $('#f-phone').value, name: $('#f-name').value, address: $('#f-address').value,
                birthday: $('#f-birthday').value || null, items: items(), payment_method: pay,
                notes: $('#f-notes').value, coupon: $('#f-coupon').value, token: TOKEN || null,
                recommended_ids: Array.from(recommended),
            });
            if (res.error) { $('#c-err').textContent = res.error; return; }
            $('#checkout-view').style.display = 'none';
            const sv = $('#success-view'); sv.style.display = 'block';
            let payHtml = '';
            if (res.payment.kind === 'pix') payHtml = `<div class="muted">Pix copia e cola (simulado):</div><div class="pixbox">${res.payment.code}</div>`;
            sv.innerHTML = `<div class="big">✅</div><h3>Pedido ${res.name} confirmado!</h3>
                <p>Previsão: ~${res.eta_minutes} min · Total <strong>${brl(res.total)}</strong>${res.discount ? ' (desconto de ' + brl(res.discount) + ')' : ''}</p>
                ${payHtml}<p class="muted">${res.payment.note}</p>
                <p><a href="${res.status_url}">Acompanhar pedido</a></p>
                <button class="btn" onclick="location.reload()">Fazer outro pedido</button>`;
            Object.keys(cart).forEach(k => delete cart[k]); updateBar();
        } catch (e) { $('#c-err').textContent = e.message || 'Erro ao enviar o pedido.'; }
        finally { btn.disabled = false; btn.textContent = 'Fazer pedido'; }
    }

    $('#btn-identify').onclick = () => identify(false);
    $('#phone').addEventListener('keydown', e => { if (e.key === 'Enter') identify(false); });
    $('#rec-close').onclick = () => $('#rec-modal').classList.remove('open');
    $('#btn-cart').onclick = () => { renderCart(); $('#cart-modal').classList.add('open'); };
    $('#cart-close').onclick = () => $('#cart-modal').classList.remove('open');
    $('#btn-checkout').onclick = checkout;
    renderMenu();
    if ($('#phone').value) identify(true);
})();
