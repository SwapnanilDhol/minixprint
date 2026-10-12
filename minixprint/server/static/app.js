(function () {
  'use strict';
  // Relative URLs only, so the page works at / and under a proxy prefix like /print/.
  var BASE = location.pathname.endsWith('/') ? location.pathname : location.pathname + '/';
  var $ = function (id) { return document.getElementById(id); };
  var tab = 'text';

  function toast(msg, err) {
    var t = $('toast');
    t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
    clearTimeout(toast.h); toast.h = setTimeout(function () { t.className = ''; }, 3200);
  }

  function api(path, opts) {
    return fetch(BASE + path, opts).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          var d = t; try { d = JSON.parse(t).detail || t; } catch (e) {}
          throw new Error(typeof d === 'string' ? d : JSON.stringify(d));
        });
      }
      return r;
    });
  }
  function jsonReq(method, body) {
    return { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  }

  // ---- status bar -------------------------------------------------------
  function setChip(id, text, cls) { var e = $(id); e.textContent = text; e.className = 'chip' + (cls ? ' ' + cls : ''); }
  function refreshStatus() {
    api('api/status').then(function (r) { return r.json(); }).then(function (s) {
      var b = s.battery;
      setChip('c-batt', '🔋 ' + (b == null ? '—' : b + '%'), b == null ? '' : b < 20 ? 'bad' : b < 50 ? 'warn' : 'ok');
      var f = s.flags || [];
      var nopaper = f.some(function (x) { return /paper/i.test(x); });
      setChip('c-paper', s.flags ? (nopaper ? 'out of paper' : 'paper ok') : 'paper —', s.flags ? (nopaper ? 'bad' : 'ok') : '');
      var busy = f.some(function (x) { return /busy|print/i.test(x); });
      setChip('c-busy', busy ? 'busy' : 'idle', busy ? 'warn' : '');
      setChip('c-transport', s.transport ? s.transport.toUpperCase() : (s.fake ? 'fake' : 'no printer'), s.transport ? '' : (s.fake ? 'warn' : 'bad'));
      setChip('c-queue', 'queue ' + s.queue_depth, s.queue_depth ? 'warn' : '');
      $('c-user').textContent = s.user && s.user !== 'local' ? '👤 ' + s.user : '';
      $('fake').hidden = !s.fake;
    }).catch(function () { setChip('c-transport', 'offline', 'bad'); });
  }

  // ---- composer ---------------------------------------------------------
  document.querySelectorAll('#tabs button').forEach(function (b) {
    b.onclick = function () {
      tab = b.dataset.tab;
      document.querySelectorAll('#tabs button').forEach(function (x) { x.classList.toggle('on', x === b); });
      document.querySelectorAll('.pane').forEach(function (p) { p.hidden = p.dataset.pane !== tab; });
      $('preview').hidden = true;
    };
  });

  function addItem(name, qty, price) {
    var d = document.createElement('div'); d.className = 'item';
    d.innerHTML = '<input placeholder="Item" class="n"><input class="q" type="number" min="1" placeholder="Qty"><input class="p" type="number" step="0.01" placeholder="Price">';
    d.querySelector('.n').value = name || ''; d.querySelector('.q').value = qty || 1; d.querySelector('.p').value = price || '';
    $('r-items').appendChild(d);
  }
  addItem('Masala Dosa', 2, 180); addItem('Filter Coffee', 1, 60);
  $('r-add').onclick = function () { addItem(); };

  function receiptFromForm() {
    var r = { title: $('r-title').value, items: [], currency: $('r-cur').value };
    if ($('r-sub').value) r.subtitle_lines = [$('r-sub').value];
    document.querySelectorAll('#r-items .item').forEach(function (d) {
      var n = d.querySelector('.n').value.trim();
      if (n) r.items.push({ name: n, qty: +d.querySelector('.q').value || 1, price: +d.querySelector('.p').value || 0 });
    });
    if ($('r-taxr').value) r.taxes = [{ label: $('r-taxl').value || 'Tax', rate: +$('r-taxr').value }];
    if ($('r-foot').value) r.footer_lines = [$('r-foot').value];
    return r;
  }
  $('r-json').onchange = function () {
    var on = $('r-json').checked;
    if (on) $('r-raw').value = JSON.stringify(receiptFromForm(), null, 2);
    $('r-raw').hidden = !on; $('r-form').hidden = on;
  };
  $('i-gamma').oninput = function () { $('i-gout').textContent = (+$('i-gamma').value).toFixed(1); };

  // Returns [path-suffix, fetch options] for the current tab.
  function request() {
    switch (tab) {
      case 'text':
        if (!$('t-text').value.trim()) throw new Error('Type something first');
        return ['text', jsonReq('POST', { text: $('t-text').value, size: +$('t-size').value || 28, align: $('t-align').value,
                                           bold: $('t-bold').checked, mono: $('t-mono').checked })];
      case 'markdown':
        if (!$('m-text').value.trim()) throw new Error('Type some Markdown first');
        return ['markdown', jsonReq('POST', { markdown: $('m-text').value })];
      case 'receipt':
        var data;
        try { data = $('r-json').checked ? JSON.parse($('r-raw').value) : receiptFromForm(); }
        catch (e) { throw new Error('Receipt JSON: ' + e.message); }
        return ['receipt', jsonReq('POST', data)];
      case 'image':
        var f = $('i-file').files[0];
        if (!f) throw new Error('Choose an image first');
        var fd = new FormData(); fd.append('file', f);
        var q = '?dither=' + $('i-dither').value + '&gamma=' + $('i-gamma').value + '&invert=' + $('i-invert').checked;
        return ['image' + q, { method: 'POST', body: fd }];
      case 'qr':
        if (!$('q-data').value.trim()) throw new Error('Enter QR data');
        return ['qr', jsonReq('POST', { data: $('q-data').value, caption: $('q-cap').value || null })];
    }
  }

  function showBlob(r, box) {
    return r.blob().then(function (b) {
      var img = box.querySelector('img');
      if (img.src) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(b); box.hidden = false;
    });
  }
  function busy(btns, on) { btns.forEach(function (b) { b.disabled = on; }); }

  $('btn-preview').onclick = function () {
    var req; try { req = request(); } catch (e) { return toast(e.message, true); }
    busy([$('btn-preview'), $('btn-print')], true);
    api('api/preview/' + req[0], req[1]).then(function (r) { return showBlob(r, $('preview')); })
      .catch(function (e) { toast(e.message, true); })
      .then(function () { busy([$('btn-preview'), $('btn-print')], false); });
  };
  $('btn-print').onclick = function () {
    var req; try { req = request(); } catch (e) { return toast(e.message, true); }
    busy([$('btn-preview'), $('btn-print')], true);
    api('api/print/' + req[0], req[1]).then(function (r) { return r.json(); })
      .then(function (j) { toast('Queued job #' + j.id); refreshStatus(); refreshHistory(); })
      .catch(function (e) { toast(e.message, true); })
      .then(function () { busy([$('btn-preview'), $('btn-print')], false); });
  };

  // ---- fun jobs ---------------------------------------------------------
  var job = null;
  function jobReq() {
    var p = {};
    var raw = $('jobparams').value.trim();
    if (raw) { try { p = JSON.parse(raw); } catch (e) { throw new Error('Params must be JSON'); } }
    return jsonReq('POST', p);
  }
  function loadJobs() {
    api('api/jobs').then(function (r) { return r.json(); }).then(function (list) {
      var box = $('jobs'); box.innerHTML = '';
      $('s-job').innerHTML = '';
      list.forEach(function (j) {
        var b = document.createElement('button'); b.textContent = j.name; b.title = j.description;
        b.onclick = function () {
          job = j; $('jobpanel').hidden = false; $('jobprev').hidden = true;
          $('jobname').innerHTML = ''; $('jobname').appendChild(document.createTextNode(j.name));
          var sm = document.createElement('small'); sm.textContent = j.description; $('jobname').appendChild(sm);
          box.querySelectorAll('button').forEach(function (x) { x.classList.toggle('on', x === b); });
        };
        box.appendChild(b);
        var o = document.createElement('option'); o.value = o.textContent = j.name; $('s-job').appendChild(o);
      });
    }).catch(function (e) { toast(e.message, true); });
  }
  $('job-preview').onclick = function () {
    try { var r = jobReq(); } catch (e) { return toast(e.message, true); }
    api('api/preview/jobs/' + encodeURIComponent(job.name), r).then(function (x) { return showBlob(x, $('jobprev')); })
      .catch(function (e) { toast(e.message, true); });
  };
  $('job-print').onclick = function () {
    try { var r = jobReq(); } catch (e) { return toast(e.message, true); }
    api('api/jobs/' + encodeURIComponent(job.name) + '/run', r).then(function (x) { return x.json(); })
      .then(function (j) { toast('Queued job #' + j.id); refreshStatus(); refreshHistory(); })
      .catch(function (e) { toast(e.message, true); });
  };

  // ---- schedules --------------------------------------------------------
  function el(tag, text, cls) { var e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
  function loadSchedules() {
    api('api/schedules').then(function (r) { return r.json(); }).then(function (list) {
      var ul = $('sched'); ul.innerHTML = '';
      if (!list.length) { ul.appendChild(el('li', 'No schedules yet.')); return; }
      list.forEach(function (s) {
        var li = el('li');
        var cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = s.enabled; cb.style.width = 'auto';
        cb.onchange = function () { api('api/schedules/' + s.id, jsonReq('PATCH', { enabled: cb.checked })).catch(function (e) { toast(e.message, true); }); };
        var t = el('div', null, 't'); t.appendChild(document.createTextNode(s.job + ' · ' + s.spec));
        var last = s.last_run ? 'last ' + new Date(s.last_run * 1000).toLocaleString() : 'never run';
        var extra = Object.keys(s.params || {}).length ? ' · ' + JSON.stringify(s.params) : '';
        t.appendChild(el('small', last + extra));
        var del = el('button', 'Delete');
        del.onclick = function () { api('api/schedules/' + s.id, { method: 'DELETE' }).then(loadSchedules).catch(function (e) { toast(e.message, true); }); };
        li.appendChild(cb); li.appendChild(t); li.appendChild(del); ul.appendChild(li);
      });
    });
  }
  $('sched-form').onsubmit = function (ev) {
    ev.preventDefault();
    var p = {};
    if ($('s-params').value.trim()) { try { p = JSON.parse($('s-params').value); } catch (e) { return toast('Params must be JSON', true); } }
    api('api/schedules', jsonReq('POST', { spec: $('s-spec').value, job: $('s-job').value, params: p }))
      .then(function () { $('s-spec').value = ''; $('s-params').value = ''; loadSchedules(); toast('Schedule added'); })
      .catch(function (e) { toast(e.message, true); });
  };

  // ---- live feeds ---------------------------------------------------------
  var feedKinds = {};
  function feedKind() { return feedKinds[$('f-kind').value]; }
  function renderFeedParams() {
    var k = feedKind(), box = $('f-params'); box.innerHTML = '';
    if (!k) return;
    $('f-int').value = k.default_interval_s;
    Object.keys(k.params).forEach(function (name) {
      var spec = k.params[name], lab = el('label', (spec.label || name) + ' '), inp;
      if (spec.type === 'enum') {
        inp = document.createElement('select');
        spec.options.forEach(function (o) { var op = el('option', o); op.value = o; inp.appendChild(op); });
        inp.value = spec.default || spec.options[0];
      } else {
        inp = document.createElement('input');
        inp.type = spec.type === 'int' ? 'number' : 'text';
        var d = spec.default;
        inp.value = d == null ? '' : Array.isArray(d) ? d.join(', ') : d;
        if (spec.type === 'icao') { inp.maxLength = 4; inp.placeholder = 'VOMM'; }
        if (spec.required) inp.required = true;
      }
      inp.dataset.param = name; inp.dataset.type = spec.type;
      lab.appendChild(inp); box.appendChild(lab);
    });
  }
  function feedParams() {
    var p = {};
    document.querySelectorAll('#f-params [data-param]').forEach(function (i) {
      var v = i.value.trim();
      if (v === '') return;
      p[i.dataset.param] = i.dataset.type === 'int' ? +v : i.dataset.type === 'list' ? v.split(/[\s,]+/).filter(Boolean) : v;
    });
    return p;
  }
  function loadFeeds() {
    api('api/feeds').then(function (r) { return r.json(); }).then(function (list) {
      var ul = $('feeds'); ul.innerHTML = '';
      if (!list.length) { ul.appendChild(el('li', 'No live feeds yet.')); return; }
      list.forEach(function (f) {
        var li = el('li'), t = el('div', null, 't');
        var what = f.kind + (f.params.station ? ' ' + f.params.station : '');
        t.appendChild(document.createTextNode(what + ' · every ' + f.interval_s + 's'));
        var last = f.last_item_ts ? 'last item ' + new Date(f.last_item_ts * 1000).toLocaleString() : 'no items yet';
        t.appendChild(el('small', last + ' · printed ' + f.printed));
        if (f.error) t.appendChild(el('small', f.error, 'bad'));
        var tog = el('button', f.enabled ? 'Stop' : 'Start');
        tog.onclick = function () {
          api('api/feeds/' + f.id + (f.enabled ? '/stop' : '/start'), { method: 'POST' }).then(loadFeeds)
            .catch(function (e) { toast(e.message, true); });
        };
        var del = el('button', 'Delete');
        del.onclick = function () { api('api/feeds/' + f.id, { method: 'DELETE' }).then(loadFeeds).catch(function (e) { toast(e.message, true); }); };
        li.appendChild(el('span', f.enabled ? '●' : '○')); li.appendChild(t); li.appendChild(tog); li.appendChild(del); ul.appendChild(li);
      });
    }).catch(function () {});
  }
  function loadFeedKinds() {
    api('api/feeds/kinds').then(function (r) { return r.json(); }).then(function (list) {
      list.forEach(function (k) {
        feedKinds[k.kind] = k;
        var o = el('option', k.kind); o.value = k.kind; o.title = k.description; $('f-kind').appendChild(o);
      });
      renderFeedParams();
    }).catch(function (e) { toast(e.message, true); });
  }
  $('f-kind').onchange = renderFeedParams;
  $('feed-form').onsubmit = function (ev) {
    ev.preventDefault();
    api('api/feeds', jsonReq('POST', { kind: $('f-kind').value, params: feedParams(), interval_s: +$('f-int').value || null, enabled: true }))
      .then(function () { loadFeeds(); toast('Feed started'); })
      .catch(function (e) { toast(e.message, true); });
  };

  // ---- history ----------------------------------------------------------
  function refreshHistory() {
    api('api/history?limit=30').then(function (r) { return r.json(); }).then(function (list) {
      var box = $('hist'); box.innerHTML = '';
      if (!list.length) { box.appendChild(el('div', 'Nothing printed yet.')); return; }
      list.forEach(function (h) {
        var a = el('a', null, 'thumb' + (h.status === 'failed' ? ' failed' : ''));
        a.title = [h.kind, h.summary, h.user, h.status, h.error].filter(Boolean).join(' · ');
        if (h.height_px) { a.href = BASE + 'api/history/' + h.id + '.png'; a.target = '_blank'; }
        var im = el('div', null, 'im' + (h.height_px ? '' : ' none'));
        if (h.height_px) { var i = document.createElement('img'); i.loading = 'lazy'; i.src = BASE + 'api/history/' + h.id + '.png'; im.appendChild(i); }
        else im.textContent = h.status === 'failed' ? '⚠︎' : '↧';
        a.appendChild(im);
        a.appendChild(el('div', h.status === 'queued' || h.status === 'printing' ? h.status + '…' : h.summary || h.kind, 'cap'));
        box.appendChild(a);
      });
    });
  }
  $('feed').onclick = function () {
    api('api/feed', jsonReq('POST', { dots: 120 })).then(function () { toast('Feeding paper'); refreshHistory(); })
      .catch(function (e) { toast(e.message, true); });
  };

  // ---- settings ---------------------------------------------------------
  function loadSettings() {
    api('api/settings').then(function (r) { return r.json(); }).then(function (s) {
      $('st-home').value = s.home_airport; $('st-air').value = s.airports.join(', ');
      $('st-tz').value = s.timezone; $('st-den').value = s.density; $('st-max').value = s.max_height_px;
    });
  }
  $('st-save').onclick = function () {
    api('api/settings', jsonReq('PUT', {
      home_airport: $('st-home').value, airports: $('st-air').value.split(/[\s,]+/).filter(Boolean),
      timezone: $('st-tz').value, density: +$('st-den').value, max_height_px: +$('st-max').value
    })).then(function () { toast('Settings saved'); }).catch(function (e) { toast(e.message, true); });
  };

  refreshStatus(); refreshHistory(); loadJobs(); loadSchedules(); loadSettings(); loadFeedKinds(); loadFeeds();
  setInterval(refreshStatus, 5000);
  setInterval(refreshHistory, 15000);
  setInterval(loadFeeds, 10000);
})();
