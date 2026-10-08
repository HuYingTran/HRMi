/* Trợ lý HRMi: khung chat góc phải dưới.
   Hội thoại giữ trong sessionStorage (sang trang khác vẫn còn, đóng tab thì mất), không lưu trên server.
   HTML câu trả lời do server dựng từ kho hướng dẫn và đã escape; chữ người dùng gõ chỉ gán qua textContent. */
(function () {
  const root = document.getElementById('asst');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const fab = $('asst-fab'), panel = $('asst-panel'), log = $('asst-log'),
        form = $('asst-form'), input = $('asst-q'), sugg = $('asst-sugg');
  const KEY = root.dataset.key, MAX_ITEMS = 40;

  const store = {
    get(k, d) { try { return JSON.parse(sessionStorage.getItem(KEY + k)) ?? d; } catch (e) { return d; } },
    set(k, v) { try { sessionStorage.setItem(KEY + k, JSON.stringify(v)); } catch (e) { /* chế độ riêng tư */ } },
  };
  let items = store.get('.log', []);

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function renderUser(text) {
    log.appendChild(el('div', 'asst-msg me', text));
  }

  function renderBot(d) {
    const box = el('div', 'asst-msg bot');
    if (d.title) box.appendChild(el('b', 'asst-title', d.title));
    const body = el('div', 'asst-body');
    body.innerHTML = d.html || '';
    box.appendChild(body);
    if (d.links && d.links.length) {
      const row = el('div', 'asst-links');
      d.links.forEach(l => {
        const a = el('a', 'btn small', l.label);
        a.href = l.url;
        a.addEventListener('click', () => store.set('.open', true));  // trang mới mở sẵn khung chat
        row.appendChild(a);
      });
      box.appendChild(row);
    }
    if (d.more_url) {
      const more = el('a', 'asst-more', 'Xem hướng dẫn đầy đủ →');
      more.href = d.more_url;
      box.appendChild(more);
    }
    if (d.related && d.related.length) {
      const rel = el('div', 'asst-related');
      rel.appendChild(el('small', 'hint', 'Liên quan:'));
      d.related.forEach(r => {
        const b = el('button', null, r.title);
        b.type = 'button';
        b.addEventListener('click', () => ask(r.q));
        rel.appendChild(b);
      });
      box.appendChild(rel);
    }
    log.appendChild(box);
    if (d.suggestions && d.suggestions.length) setSuggestions(d.suggestions);
  }

  function renderAll() {
    log.innerHTML = '';
    if (!items.length) {
      renderBot({ html: '<p>Chào bạn! Mình hướng dẫn cách dùng HRMi và đưa bạn tới đúng trang. ' +
                        'Hãy hỏi bằng tiếng Việt, có dấu hay không dấu đều được.</p>' });
    }
    items.forEach(it => it.role === 'me' ? renderUser(it.text) : renderBot(it.data));
    log.scrollTop = log.scrollHeight;
  }

  function setSuggestions(list) {
    sugg.innerHTML = '';
    list.forEach(s => {
      const b = el('button', null, s);
      b.type = 'button';
      sugg.appendChild(b);
    });
  }

  function remember(it) {
    items.push(it);
    items = items.slice(-MAX_ITEMS);
    store.set('.log', items);
  }

  async function ask(text) {
    text = (text || '').trim();
    if (!text) return;
    remember({ role: 'me', text });
    renderUser(text);
    const typing = el('div', 'asst-msg bot typing');
    typing.append(el('i'), el('i'), el('i'));
    log.appendChild(typing);
    log.scrollTop = log.scrollHeight;
    let data;
    try {
      const res = await fetch(root.dataset.api, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: text, page: root.dataset.page }),
      });
      if (res.status === 401) data = { html: '<p>Phiên đăng nhập đã hết, hãy tải lại trang.</p>' };
      else data = await res.json();
      if (data.error) data = { html: '<p>' + data.error.replace(/</g, '&lt;') + '</p>' };
    } catch (e) {
      data = { html: '<p>Không kết nối được máy chủ HRMi. Kiểm tra mạng rồi thử lại.</p>' };
    }
    typing.remove();
    remember({ role: 'bot', data });
    renderBot(data);
    log.scrollTop = log.scrollHeight;
  }

  function open(focus = true) {
    panel.hidden = false;
    root.classList.add('open');
    fab.setAttribute('aria-expanded', 'true');
    store.set('.open', true);
    renderAll();
    if (focus) input.focus();
  }

  function close() {
    panel.hidden = true;
    root.classList.remove('open');
    fab.setAttribute('aria-expanded', 'false');
    store.set('.open', false);
    fab.focus();
  }

  fab.addEventListener('click', () => (panel.hidden ? open() : close()));
  $('asst-close').addEventListener('click', close);
  $('asst-clear').addEventListener('click', () => { items = []; store.set('.log', items); renderAll(); input.focus(); });
  form.addEventListener('submit', ev => { ev.preventDefault(); const q = input.value; input.value = ''; ask(q); });
  sugg.addEventListener('click', ev => { if (ev.target.tagName === 'BUTTON') ask(ev.target.textContent); });

  document.addEventListener('keydown', ev => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if (ev.key === '?' && !typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      ev.preventDefault();
      panel.hidden ? open() : input.focus();
    } else if (ev.key === 'Escape' && !panel.hidden) {
      close();
    }
  });

  if (store.get('.open', false)) open(false);
})();
