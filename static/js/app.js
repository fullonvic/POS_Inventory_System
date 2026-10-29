/* ---------- Modal helpers ---------- */
function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

/* ---------- POS logic ---------- */
document.addEventListener('DOMContentLoaded', () => {
  const grid = document.getElementById('productGrid');
  if (!grid) return; // not on POS page

  const searchInput = document.getElementById('searchInput');
  const cartEl = document.getElementById('cartItems');
  const totalEl = document.getElementById('cartTotal');
  const changeEl = document.getElementById('changeText');
  const paymentInput = document.getElementById('paymentInput');
  const checkoutBtn = document.getElementById('checkoutBtn');

  let products = [];

  async function loadProducts(q='') {
    const res = await fetch('/api/products?q=' + encodeURIComponent(q));
    products = await res.json();
    renderProducts();
  }

  function renderProducts() {
    if (!products.length) {
      grid.innerHTML = '<div class="empty">No products match your search.</div>';
      return;
    }
    grid.innerHTML = products.map(p => `
      <div class="product-card" data-id="${p.product_id}">
        <div class="pc-name">${escapeHtml(p.name)}</div>
        <div class="pc-code">${escapeHtml(p.product_code)}</div>
        <div class="pc-price">₱${p.price}</div>
        <div class="pc-stock">Stock: ${p.stock_quantity}</div>
      </div>
    `).join('');
    grid.querySelectorAll('.product-card').forEach(el => {
      el.addEventListener('click', () => addToCart(parseInt(el.dataset.id)));
    });
  }

  function addToCart(id) {
    const p = products.find(x => x.product_id === id);
    if (!p) return;
    const existing = window.CART[id];
    const qty = existing ? existing.quantity + 1 : 1;
    if (qty > p.stock_quantity) {
      alert(`Only ${p.stock_quantity} in stock for ${p.name}.`);
      return;
    }
    window.CART[id] = { ...p, quantity: qty };
    renderCart();
  }

  function removeFromCart(id) {
    delete window.CART[id];
    renderCart();
  }

  function updateQty(id, qty) {
    const p = window.CART[id];
    if (!p) return;
    qty = parseInt(qty);
    if (isNaN(qty) || qty < 1) qty = 1;
    if (qty > p.stock_quantity) qty = p.stock_quantity;
    p.quantity = qty;
    renderCart();
  }

  function renderCart() {
    const items = Object.values(window.CART);
    if (!items.length) {
      cartEl.innerHTML = '<div class="empty">Cart is empty. Add products to get started.</div>';
      totalEl.textContent = '₱0.00';
      changeEl.textContent = '₱0.00';
      checkoutBtn.disabled = true;
      return;
    }
    cartEl.innerHTML = items.map(it => `
      <div class="cart-item">
        <div class="ci-info">
          <div class="ci-name">${escapeHtml(it.name)}</div>
          <div class="ci-price">₱${it.price} × ${it.quantity} = ₱${(parseFloat(it.price) * it.quantity).toFixed(2)}</div>
        </div>
        <div class="ci-controls">
          <button class="qty-btn" onclick="updateQty(${it.product_id}, ${it.quantity - 1})">−</button>
          <input type="number" min="1" value="${it.quantity}" onchange="updateQty(${it.product_id}, this.value)" class="qty-input"/>
          <button class="qty-btn" onclick="updateQty(${it.product_id}, ${it.quantity + 1})">+</button>
          <button class="remove-btn" onclick="removeFromCart(${it.product_id})">✕</button>
        </div>
      </div>
    `).join('');
    updateTotals();
  }

  function cartTotal() {
    return Object.values(window.CART)
      .reduce((s, it) => s + parseFloat(it.price) * it.quantity, 0);
  }

  function updateTotals() {
    const total = cartTotal();
    totalEl.textContent = '₱' + total.toFixed(2);
    const pay = parseFloat(paymentInput.value) || 0;
    const change = pay - total;
    changeEl.textContent = '₱' + (change >= 0 ? change.toFixed(2) : '0.00');
    changeEl.style.color = change >= 0 ? 'var(--green)' : 'var(--red)';
    checkoutBtn.disabled = Object.keys(window.CART).length === 0 || pay < total;
  }

  window.updateQty = updateQty;
  window.removeFromCart = removeFromCart;

  paymentInput.addEventListener('input', updateTotals);

  checkoutBtn.addEventListener('click', async () => {
    const cart = Object.values(window.CART).map(it => ({
      product_id: it.product_id,
      quantity: it.quantity
    }));
    const payment = parseFloat(paymentInput.value) || 0;

    checkoutBtn.disabled = true;
    checkoutBtn.textContent = 'Processing...';
    try {
      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cart, payment })
      });
      const data = await res.json();
      if (!data.ok) {
        alert('Sale failed: ' + data.error);
        return;
      }
      showReceipt(data);
      window.CART = {};
      renderCart();
      paymentInput.value = '';
      loadProducts(searchInput.value);
    } catch (e) {
      alert('Network error: ' + e.message);
    } finally {
      checkoutBtn.textContent = 'Complete Sale';
      updateTotals();
    }
  });

  function showReceipt(data) {
    const rows = data.items.map(it => `
      <tr>
        <td>${escapeHtml(it.name)}</td>
        <td class="center">${it.quantity}</td>
        <td class="right">₱${parseFloat(it.unit_price).toFixed(2)}</td>
        <td class="right">₱${parseFloat(it.line_total).toFixed(2)}</td>
      </tr>
    `).join('');
    document.getElementById('receiptContent').innerHTML = `
      <div class="receipt">
        <div class="receipt-head">
          <div class="brand-logo small">POS</div>
          <h2>InventoPOS</h2>
          <p>Official Receipt</p>
        </div>
        <div class="receipt-meta">
          <div><b>Sale #:</b> ${data.sale_id}</div>
          <div><b>Date:</b> ${data.sale_date.replace('T',' ')}</div>
          <div><b>Cashier:</b> ${data.cashier}</div>
        </div>
        <table class="receipt-table">
          <thead><tr><th>Item</th><th class="center">Qty</th><th class="right">Price</th><th class="right">Total</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="receipt-totals">
          <div class="row"><span>Total:</span><strong>₱${parseFloat(data.total).toFixed(2)}</strong></div>
          <div class="row"><span>Paid:</span><strong>₱${parseFloat(data.payment).toFixed(2)}</strong></div>
          <div class="row"><span>Change:</span><strong>₱${parseFloat(data.change).toFixed(2)}</strong></div>
        </div>
        <div class="receipt-footer">Thank you for your purchase!</div>
      </div>
    `;
    openModal('receiptModal');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }

  searchInput.addEventListener('input', debounce(e => loadProducts(e.target.value), 250));
  loadProducts();
});

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}