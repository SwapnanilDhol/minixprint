(function () {
  'use strict';
  // Relative URLs only, so the page works at / and under a proxy prefix like /print/.
  var BASE = location.pathname.endsWith('/') ? location.pathname : location.pathname + '/';
  var $ = function (id) { return document.getElementById(id); };
  var S = { settings: null, status: null, tz: 'UTC' };

  // ---- tiny DOM helper -----------------------------------------------------
  function h(tag, props) {
    var el = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v == null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(el, x); });
    else el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  function icon(id, cls) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('class', 'ico' + (cls ? ' ' + cls : ''));
    var u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    u.setAttribute('href', '#i-' + id); s.appendChild(u); return s;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

  // ---- api -------------------------------------------------------------------
  function api(path, opts) {
    return fetch(BASE + path, opts).then(function (r) {
      if (r.ok) return r;
      return r.text().then(function (t) {
        var d = t; try { d = JSON.parse(t).detail || t; } catch (e) {}
        var err = new Error(typeof d === 'string' ? d : JSON.stringify(d)); err.status = r.status; throw err;
      });
    });
  }
  function jreq(method, body) {
    return { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body == null ? {} : body) };
  }
  function getJSON(path) { return api(path).then(function (r) { return r.json(); }); }

  // ---- time ------------------------------------------------------------------
  function toDate(v) {
    if (v == null || v === '') return null;
    if (typeof v === 'number' || /^\d+(\.\d+)?$/.test(String(v))) { v = +v; return new Date(v < 1e12 ? v * 1000 : v); }
    var d = new Date(v); return isNaN(d) ? null : d;
  }
  function fmt(d, o) {
    try { return new Intl.DateTimeFormat([], Object.assign({ timeZone: S.tz }, o)).format(d); }
    catch (e) { return new Intl.DateTimeFormat([], o).format(d); }
  }
  function clock(v) { var d = toDate(v); return d ? fmt(d, { hour: '2-digit', minute: '2-digit', hour12: false }) : '—'; }
  function when(v) {
    var d = toDate(v); if (!d) return '';
    var day = fmt(d, { year: 'numeric', month: 'numeric', day: 'numeric' });
    var today = fmt(new Date(), { year: 'numeric', month: 'numeric', day: 'numeric' });
    return day === today ? clock(v) : fmt(d, { day: 'numeric', month: 'short' }) + ' ' + clock(v);
  }

  // ---- toasts ----------------------------------------------------------------
  var pendingCommit = null;
  function toast(o) {
    var box = $('toasts');
    Array.prototype.slice.call(box.children).forEach(dismissToast);
    var t = h('div', { class: 'toast enter' + (o.err ? ' err' : ''), role: o.err ? 'alert' : 'status' }, h('span', { class: 'msg', text: o.msg }));
    var timer;
    t._done = function () { clearTimeout(timer); t._done = null; leave(t); if (o.onExpire) o.onExpire(); };
    if (o.link) add(t, h('a', { href: o.link.href, target: '_blank', rel: 'noopener', text: o.link.text }));
    if (o.action) add(t, h('button', { text: o.action.label, onclick: function () { clearTimeout(timer); t._done = null; leave(t); o.action.fn(); } }));
    if (o.bar) { t.style.setProperty('--dur', o.ttl + 'ms'); add(t, h('i', { class: 'bar' })); }
    box.appendChild(t);
    requestAnimationFrame(function () { requestAnimationFrame(function () { t.classList.remove('enter'); }); });
    timer = setTimeout(function () { if (t._done) t._done(); }, o.ttl || 3800);
    return t;
  }
  function dismissToast(t) { if (t._done) t._done(); else leave(t); }
  function leave(t) { t.classList.add('leave'); setTimeout(function () { t.remove(); }, 180); }
  function fail(e) { toast({ msg: e && e.message ? e.message : String(e), err: true, ttl: 5000 }); }

  // ---- sheet -------------------------------------------------------------------
  var sheet = $('sheet'), sheetClose = null;
  function openSheet(title, body, onClose) {
    clear(sheet);
    sheetClose = onClose || null;
    var head = h('div', { class: 'sheet-head' }, h('h3', { id: 'sheet-title', text: title }),
      h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: closeSheet, text: '✕' }));
    sheet.appendChild(head);
    sheet.appendChild(h('div', { class: 'sheet-body' }, body));
    sheet.style.transform = '';
    if (!sheet.open) sheet.showModal();
    return sheet;
  }
  function closeSheet() { if (sheet.open) sheet.close(); }
  sheet.addEventListener('close', function () { if (sheetClose) { var f = sheetClose; sheetClose = null; f(); } });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) closeSheet(); });
  // Drag the header down to dismiss (phones). Flick velocity counts, not just distance.
  (function () {
    var y0 = 0, t0 = 0, dy = 0, on = false;
    sheet.addEventListener('pointerdown', function (e) {
      if (!e.target.closest('.sheet-head') || e.target.closest('button') || innerWidth >= 900) return;
      on = true; y0 = e.clientY; t0 = Date.now(); dy = 0; sheet.setPointerCapture(e.pointerId); sheet.style.transition = 'none';
    });
    sheet.addEventListener('pointermove', function (e) {
      if (!on) return;
      dy = Math.max(0, e.clientY - y0); sheet.style.transform = 'translateY(' + dy + 'px)';
    });
    function end() {
      if (!on) return; on = false; sheet.style.transition = '';
      var v = dy / Math.max(1, Date.now() - t0);
      if (dy > 110 || v > .5) closeSheet(); else sheet.style.transform = '';
    }
    sheet.addEventListener('pointerup', end); sheet.addEventListener('pointercancel', end);
  })();

  // ---- widgets -----------------------------------------------------------------
  // Segmented radio group wired to a getter/setter; used for static and built groups.
  function wireSeg(el, onchange) {
    var btns = Array.prototype.slice.call(el.querySelectorAll('button[role=radio]'));
    function sel(b, fire) {
      btns.forEach(function (x) { x.setAttribute('aria-checked', x === b ? 'true' : 'false'); x.tabIndex = x === b ? 0 : -1; });
      if (fire && onchange) onchange(b.dataset.v);
    }
    btns.forEach(function (b) {
      b.tabIndex = b.getAttribute('aria-checked') === 'true' ? 0 : -1;
      b.addEventListener('click', function () { sel(b, true); });
      b.addEventListener('keydown', function (e) {
        var i = btns.indexOf(b), n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : -1;
        if (n < 0 || n >= btns.length) return;
        e.preventDefault(); btns[n].focus(); sel(btns[n], true);
      });
    });
    return {
      get: function () { var b = btns.filter(function (x) { return x.getAttribute('aria-checked') === 'true'; })[0]; return b ? b.dataset.v : null; },
      set: function (v) { btns.forEach(function (b) { if (b.dataset.v === String(v)) sel(b, false); }); }
    };
  }
  function seg(options, value, onchange, extra) {
    var el = h('div', { class: 'seg ' + (extra || ''), role: 'radiogroup' });
    options.forEach(function (o) {
      el.appendChild(h('button', { type: 'button', role: 'radio', 'data-v': o[0], 'aria-checked': String(o[0]) === String(value) ? 'true' : 'false', text: o[1] }));
    });
    var w = wireSeg(el, onchange); el._w = w; return el;
  }
  function toggle(on, label, onchange) {
    var b = h('button', { class: 'sw', role: 'switch', 'aria-checked': on ? 'true' : 'false', 'aria-label': label });
    b.addEventListener('click', function () {
      var n = b.getAttribute('aria-checked') !== 'true'; b.setAttribute('aria-checked', n ? 'true' : 'false'); onchange(n, b);
    });
    return h('div', { class: 'swwrap' }, b);
  }
  function busy(btn, p) {
    btn.disabled = true;
    return p.then(function (r) { btn.disabled = false; return r; }, function (e) { btn.disabled = false; throw e; });
  }
  function field(label, input, id) { return h('div', { class: 'field' }, h('label', { class: 'lbl', for: id, text: label }), input); }

  // ---- submitting prints ---------------------------------------------------------
  function afterPrint(r, label) {
    if (r.status === 'skipped') {
      toast({ msg: 'Skipped — printed recently', link: r.skipped_of ? { href: BASE + 'api/history/' + r.skipped_of + '.png', text: 'View' } : null });
    } else {
      toast({ msg: (label || 'Sent') + ' · job #' + r.id, link: { href: BASE + 'api/history/' + r.id + '.png', text: 'View' } });
    }
    refreshStatus(); histStamp = '';
    return r;
  }
  function send(path, opts, label) {
    return api(path, opts).then(function (r) { return r.json(); }).then(function (r) { return afterPrint(r, label); });
  }
  function showPreview(title, path, opts) {
    var img = h('img', { alt: 'Preview', width: 384 });
    var paper = h('div', { class: 'paper', 'aria-busy': 'true' }, h('span', { class: 'lbl', text: 'Rendering…' }));
    openSheet(title, [paper, h('p', { class: 'vmeta', text: 'Exactly what will print (384 px wide).' })]);
    api(path, opts).then(function (r) { return r.blob(); }).then(function (b) {
      img.src = URL.createObjectURL(b); clear(paper).appendChild(img); paper.removeAttribute('aria-busy');
    }).catch(function (e) { closeSheet(); fail(e); });
  }

  // ---- header status ---------------------------------------------------------------
  function setChip(id, text, cls, extra) {
    var e = $(id); e.className = 'chip' + (cls ? ' ' + cls : ''); clear(e);
    if (extra) e.appendChild(extra);
    e.appendChild(document.createTextNode(text));
  }
  function battIcon(p) {
    var w = Math.max(1, Math.round(10 * p / 100));
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 18 11'); s.setAttribute('aria-hidden', 'true');
    s.innerHTML = '<rect x=".75" y=".75" width="14.5" height="9.5" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".6"/><rect x="2.5" y="2.5" width="' + w + '" height="6" rx="1" fill="currentColor"/><rect x="16" y="3.5" width="1.4" height="4" rx=".7" fill="currentColor" opacity=".6"/>';
    return s;
  }
  function refreshStatus() {
    return getJSON('api/status').then(function (s) {
      S.status = s;
      var name = (s.info && s.info.name) || 'MiniX';
      var n = $('h-name'); n.textContent = name; n.classList.remove('skel');
      var online = s.fake ? 'fake' : s.connected ? 'ok' : 'off';
      setChip('h-conn', online === 'fake' ? 'Fake' : online === 'ok' ? 'Connected' : 'Offline', online === 'ok' ? 'ok' : online === 'fake' ? 'warn' : 'bad', h('i', { class: 'dot' }));
      $('h-conn').title = s.fake ? 'Fake mode: jobs are archived, nothing prints' : (s.error || (s.transport || '').toUpperCase());
      var b = s.battery, be = $('h-batt');
      be.hidden = b == null;
      if (b != null) setChip('h-batt', b + '%', b < 20 ? 'bad' : b < 40 ? 'warn' : '', battIcon(b));
      setChip('h-queue', 'Queue ' + s.queue_depth, s.queue_depth ? 'warn' : '');
      if (s.timezone) S.tz = s.timezone;
    }).catch(function () {
      var n = $('h-name'); if (n.classList.contains('skel')) { n.textContent = 'MiniX'; n.classList.remove('skel'); }
      setChip('h-conn', 'Server offline', 'bad', h('i', { class: 'dot' }));
    });
  }

  // ---- PRINT -------------------------------------------------------------------------
  var tSize = wireSeg($('t-size')), tAlign = wireSeg($('t-align')), tBold = $('t-bold');
  tBold.addEventListener('click', function () { tBold.setAttribute('aria-pressed', tBold.getAttribute('aria-pressed') === 'true' ? 'false' : 'true'); });
  function textReq() {
    var t = $('t-text').value;
    if (!t.trim()) { $('t-text').focus(); throw new Error('Type something first'); }
    return jreq('POST', { text: t, size: +tSize.get(), align: tAlign.get(), bold: tBold.getAttribute('aria-pressed') === 'true' });
  }
  $('t-print').addEventListener('click', function () {
    var o; try { o = textReq(); } catch (e) { return toast({ msg: e.message, err: true }); }
    busy($('t-print'), send('api/print/text', o)).then(function () { $('t-text').value = ''; }).catch(fail);
  });
  $('t-preview').addEventListener('click', function () {
    try { showPreview('Preview', 'api/preview/text', textReq()); } catch (e) { toast({ msg: e.message, err: true }); }
  });

  // Photo: pick -> two dither previews -> choose -> print.
  var picker = h('input', { type: 'file', accept: 'image/*', class: 'sr', tabindex: '-1', 'aria-hidden': 'true' });
  document.body.appendChild(picker);
  $('go-photo').addEventListener('click', function () { picker.value = ''; picker.click(); });
  picker.addEventListener('change', function () { if (picker.files[0]) photoSheet(picker.files[0]); });
  function photoSheet(file) {
    var choice = 'fs', urls = [];
    function previewFor(d) {
      var fd = new FormData(); fd.append('file', file);
      return api('api/preview/image?dither=' + d, { method: 'POST', body: fd }).then(function (r) { return r.blob(); });
    }
    function opt(d, label) {
      var im = h('div', { class: 'im' });
      var b = h('button', { class: 'opt-thumb loading', role: 'radio', 'aria-checked': d === choice ? 'true' : 'false', 'data-v': d }, im, h('span', { text: label }));
      previewFor(d).then(function (blob) {
        var u = URL.createObjectURL(blob); urls.push(u);
        im.appendChild(h('img', { src: u, alt: label + ' dither preview' })); b.classList.remove('loading');
      }).catch(function (e) { b.classList.remove('loading'); im.textContent = '—'; fail(e); });
      return b;
    }
    var grid = h('div', { class: 'thumbs2', role: 'radiogroup', 'aria-label': 'Dither' }, opt('fs', 'Floyd–Steinberg'), opt('atkinson', 'Atkinson'));
    grid.addEventListener('click', function (e) {
      var b = e.target.closest('.opt-thumb'); if (!b) return;
      choice = b.dataset.v; Array.prototype.forEach.call(grid.children, function (c) { c.setAttribute('aria-checked', c === b ? 'true' : 'false'); });
    });
    var pb = h('button', { class: 'btn primary grow' }, icon('print'), 'Print photo');
    pb.addEventListener('click', function () {
      var fd = new FormData(); fd.append('file', file);
      busy(pb, send('api/print/image?dither=' + choice, { method: 'POST', body: fd }, 'Photo sent')).then(closeSheet).catch(fail);
    });
    var other = h('button', { class: 'btn ghost', text: 'Other photo', onclick: function () { closeSheet(); picker.value = ''; picker.click(); } });
    openSheet('Photo', [grid, h('p', { class: 'vmeta', text: 'Pick the look you like. Atkinson is crisper on faces; Floyd–Steinberg keeps more tone.' }),
      h('div', { class: 'row-actions' }, other, pb)], function () { urls.forEach(URL.revokeObjectURL); });
  }

  $('go-md').addEventListener('click', function () {
    var ta = h('textarea', { id: 'md-text', rows: 9, placeholder: '# Shopping\n- eggs\n- tea\n\n**bold**, _italic_, `code`', 'aria-label': 'Markdown' });
    var pb = h('button', { class: 'btn primary grow' }, icon('print'), 'Print');
    function body() { if (!ta.value.trim()) { ta.focus(); throw new Error('Write some Markdown first'); } return jreq('POST', { markdown: ta.value }); }
    pb.addEventListener('click', function () {
      var o; try { o = body(); } catch (e) { return toast({ msg: e.message, err: true }); }
      busy(pb, send('api/print/markdown', o)).then(closeSheet).catch(fail);
    });
    openSheet('Markdown', [ta, h('div', { class: 'row-actions' },
      h('button', { class: 'btn ghost', text: 'Preview', onclick: function () { try { var o = body(); closeSheet(); showPreview('Preview', 'api/preview/markdown', o); } catch (e) { toast({ msg: e.message, err: true }); } } }), pb)]);
    ta.focus();
  });

  $('go-qr').addEventListener('click', function () {
    var data = h('input', { type: 'text', id: 'qr-d', placeholder: 'https://… or any text', inputmode: 'url', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false' });
    var cap = h('input', { type: 'text', id: 'qr-c', placeholder: 'Caption (optional)' });
    var pb = h('button', { class: 'btn primary grow' }, icon('print'), 'Print QR');
    pb.addEventListener('click', function () {
      if (!data.value.trim()) { data.focus(); return toast({ msg: 'Enter something to encode', err: true }); }
      busy(pb, send('api/print/qr', jreq('POST', { data: data.value, caption: cap.value || null }))).then(closeSheet).catch(fail);
    });
    data.addEventListener('keydown', function (e) { if (e.key === 'Enter') pb.click(); });
    openSheet('QR code', [field('Text or link', data, 'qr-d'), field('Caption', cap, 'qr-c'), h('div', { class: 'row-actions' }, pb)]);
    data.focus();
  });

  // Advanced: density, feed, receipt.
  var density = wireSeg($('a-density'), function (v) {
    api('api/settings', jreq('PUT', { density: +v })).then(function () { if (S.settings) S.settings.density = +v; }).catch(fail);
  });
  Array.prototype.forEach.call($('a-feed').querySelectorAll('button'), function (b) {
    b.addEventListener('click', function () { busy(b, send('api/feed', jreq('POST', { dots: +b.dataset.v }), 'Feeding paper')).catch(fail); });
  });
  $('a-receipt').value = JSON.stringify({
    title: 'DOSA & CO.', subtitle_lines: ['12 Main Road'], currency: 'INR',
    items: [{ name: 'Masala Dosa', qty: 2, price: 180 }, { name: 'Filter Coffee', qty: 1, price: 60 }],
    taxes: [{ label: 'GST', rate: 5 }], footer_lines: ['Thank you!']
  }, null, 2);
  function receiptReq() {
    var d; try { d = JSON.parse($('a-receipt').value); } catch (e) { throw new Error('Receipt JSON: ' + e.message); }
    return jreq('POST', d);
  }
  $('a-rprint').addEventListener('click', function () {
    var o; try { o = receiptReq(); } catch (e) { return toast({ msg: e.message, err: true }); }
    busy($('a-rprint'), send('api/print/receipt', o)).catch(fail);
  });
  $('a-rpreview').addEventListener('click', function () {
    try { showPreview('Receipt preview', 'api/preview/receipt', receiptReq()); } catch (e) { toast({ msg: e.message, err: true }); }
  });

  // ---- shared job helpers ----------------------------------------------------------------
  var TITLES = {
    'aviation.metar': 'METAR & TAF', 'aviation.now': 'Departure board', 'aviation.overhead': 'Boarding passes',
    'aviation.runway': 'Runway in use', 'aviation.digest': 'Traffic digest', 'puzzle.sudoku': 'Sudoku', 'puzzle.maze': 'Maze',
    'puzzle.wordsearch': 'Word search', 'system.status': 'Pi status', morning: 'Morning docket', fortune: 'Fortune'
  };
  function jobTitle(n) {
    if (TITLES[n]) return TITLES[n];
    var s = n.split('.').pop().replace(/[_-]/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function jobDesc(d) { d = (d || '').replace(/^[\w.]+:\s*/, ''); return d.charAt(0).toUpperCase() + d.slice(1); }
  var GROUPS = [['Everyday', function (n) { return n.indexOf('.') < 0; }], ['Puzzles', function (n) { return /^puzzle\./.test(n); }],
    ['Aviation', function (n) { return /^aviation\./.test(n); }], ['System', function (n) { return /^system\./.test(n); }]];
  // The only jobs that take parameters worth showing. Each returns {node, value()}.
  var JOB_PARAMS = {
    morning: function () {
      var ta = h('textarea', { id: 'jp-todos', rows: 5, placeholder: 'One thing per line\nWater the plants\nCall the electrician' });
      return { node: field('Todos for today', ta, 'jp-todos'), value: function () {
        var l = ta.value.split('\n').map(function (x) { return x.trim(); }).filter(Boolean); return l.length ? { todos: l } : {}; } };
    },
    'puzzle.sudoku': function () {
      var s = seg([['easy', 'Easy'], ['medium', 'Medium'], ['hard', 'Hard']], 'medium', null, 'wide');
      return { node: h('div', { class: 'field' }, h('span', { class: 'lbl', text: 'Difficulty' }), s), value: function () { return { difficulty: s._w.get() }; } };
    }
  };
  function runJob(name, params, label) {
    return send('api/jobs/' + encodeURIComponent(name) + '/run', jreq('POST', params), label || jobTitle(name) + ' sent');
  }

  // ---- FUN ---------------------------------------------------------------------------------
  var funLoaded = false;
  function funSkeleton(p) {
    var g = h('div', { class: 'grid' });
    for (var i = 0; i < 6; i++) g.appendChild(h('div', { class: 'job', 'aria-hidden': 'true' }, h('div', { class: 'thumb skel' }), h('div', { class: 'meta' }, h('div', { class: 't skel', text: 'Loading job' }), h('div', { class: 's skel', text: 'description here' }))));
    p.appendChild(g);
  }
  function loadFun() {
    var p = $('p-fun');
    if (!funLoaded) funSkeleton(p);
    getJSON('api/jobs').then(function (jobs) {
      funLoaded = true; clear(p);
      var used = {};
      GROUPS.forEach(function (g) {
        var items = jobs.filter(function (j) { if (used[j.name] || !g[1](j.name)) return false; used[j.name] = 1; return true; });
        if (!items.length) return;
        p.appendChild(h('h2', { class: 'sec', text: g[0] }));
        p.appendChild(h('div', { class: 'grid' }, items.map(jobTile)));
      });
      var rest = jobs.filter(function (j) { return !used[j.name]; });
      if (rest.length) { p.appendChild(h('h2', { class: 'sec', text: 'Other' })); p.appendChild(h('div', { class: 'grid' }, rest.map(jobTile))); }
    }).catch(function (e) { clear(p).appendChild(h('div', { class: 'empty', text: 'Could not load jobs: ' + e.message })); });
  }
  function jobTile(j) {
    var hasParams = !!JOB_PARAMS[j.name];
    var thumb = h('div', { class: 'thumb' });
    var img = h('img', { src: 'thumbs/' + j.name + '.png', alt: '', loading: 'lazy' });
    img.addEventListener('error', function () { img.replaceWith(icon('fun', 'glyph')); });
    thumb.appendChild(img);
    if (hasParams) thumb.appendChild(h('span', { class: 'opt', title: 'Has options' }, icon('sliders')));
    var b = h('button', { class: 'job', 'aria-label': jobTitle(j.name) + '. ' + jobDesc(j.description) + (hasParams ? ' Opens options.' : ' Tap to print.') },
      thumb, h('div', { class: 'meta' }, h('div', { class: 't', text: jobTitle(j.name) }), h('div', { class: 's', text: jobDesc(j.description) })));
    b.addEventListener('click', function () { hasParams ? jobSheet(j) : undoPrint(j); });
    return b;
  }
  // One tap prints, after a 1 s window to cancel. A newer tap commits the previous one right away.
  function undoPrint(j) {
    if (pendingCommit) pendingCommit();
    var fired = false;
    function go() { if (fired) return; fired = true; pendingCommit = null; runJob(j.name, {}).catch(fail); }
    pendingCommit = function () { var t = $('toasts').firstChild; if (t && t._done) t._done(); else go(); };
    toast({ msg: 'Printing ' + jobTitle(j.name) + '…', bar: true, ttl: 1000, onExpire: go,
      action: { label: 'Undo', fn: function () { fired = true; pendingCommit = null; } } });
  }
  function jobSheet(j) {
    var pf = JOB_PARAMS[j.name]();
    var pb = h('button', { class: 'btn primary grow' }, icon('print'), 'Print');
    pb.addEventListener('click', function () { busy(pb, runJob(j.name, pf.value())).then(closeSheet).catch(fail); });
    var pv = h('button', { class: 'btn ghost', text: 'Preview', onclick: function () { closeSheet(); showPreview(jobTitle(j.name), 'api/preview/jobs/' + encodeURIComponent(j.name), jreq('POST', pf.value())); } });
    openSheet(jobTitle(j.name), [h('p', { class: 'vmeta', text: jobDesc(j.description) }), pf.node, h('div', { class: 'row-actions' }, pv, pb)]);
  }

  // ---- LIVE (feeds + schedules) ----------------------------------------------------------------
  var feedsApi = null; // null = unknown, true/false after first probe
  var MOCK = { on: false, nextId: 3,
    kinds: [
      { kind: 'metar', description: 'Print a METAR whenever a station issues a new one', default_interval_s: 300, params: { station: { type: 'str', required: true, default: 'VOMM' } } },
      { kind: 'acars', description: 'Print ACARS messages as they arrive', default_interval_s: 60, params: {} }],
    feeds: [
      { id: 1, kind: 'metar', params: { station: 'VOMM' }, interval_s: 300, enabled: true, last_poll: Date.now() / 1000 - 400, printed: 4, error: null },
      { id: 2, kind: 'acars', params: {}, interval_s: 60, enabled: false, last_poll: null, printed: 0, error: null }] };
  function feedsList() {
    if (feedsApi === false) return Promise.resolve(MOCK.feeds);
    return api('api/feeds').then(function (r) { feedsApi = true; return r.json(); }).catch(function (e) {
      if (e.status === 404 || e.status === 405) { feedsApi = false; MOCK.on = true; return MOCK.feeds; }
      throw e;
    });
  }
  function feedKinds() {
    if (feedsApi === false) return Promise.resolve(MOCK.kinds);
    return getJSON('api/feeds/kinds');
  }
  function feedCall(method, path, body) {
    if (feedsApi === false) {
      var m = path.match(/^api\/feeds(?:\/(\d+))?(?:\/(\w+))?/), id = m && +m[1], act = m && m[2];
      var f = MOCK.feeds.filter(function (x) { return x.id === id; })[0];
      if (method === 'POST' && !id) { MOCK.feeds.push({ id: MOCK.nextId++, kind: body.kind, params: body.params || {}, interval_s: body.interval_s || 300, enabled: true, last_poll: null, printed: 0, error: null }); }
      else if (method === 'DELETE') MOCK.feeds = MOCK.feeds.filter(function (x) { return x.id !== id; });
      else if (f && act === 'start') f.enabled = true;
      else if (f && act === 'stop') f.enabled = false;
      else if (f && act === 'poll') { f.last_poll = Date.now() / 1000; }
      return Promise.resolve({});
    }
    return api(path, method === 'DELETE' ? { method: 'DELETE' } : jreq(method, body)).then(function (r) { return r.status === 204 ? {} : r.json().catch(function () { return {}; }); });
  }
  function every(s) {
    s = +s;
    if (s % 3600 === 0) return s === 3600 ? 'every hour' : 'every ' + s / 3600 + ' h';
    if (s % 60 === 0) return 'every ' + s / 60 + ' min';
    return 'every ' + s + ' s';
  }
  var DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
  function cap(s) { return s.charAt(0) + s.slice(1).toLowerCase(); }
  function time12(hhmm) {
    var p = hhmm.split(':'), hr = +p[0], m = p[1] || '00';
    return (hr % 12 || 12) + ':' + m + ' ' + (hr < 12 ? 'AM' : 'PM');
  }
  function specWords(spec) {
    var s = (spec || '').trim(), m;
    if ((m = /^daily\s+(\d{1,2}:\d{2})$/i.exec(s))) return 'Every day at ' + time12(m[1]);
    if ((m = /^weekly\s+([A-Za-z,\s]+?)\s+(\d{1,2}:\d{2})$/i.exec(s))) {
      var d = m[1].split(',').map(function (x) { return cap(x.trim()); });
      return (d.length === 5 && !/Sat|Sun/.test(d.join()) ? 'Weekdays' : d.length === 7 ? 'Every day' : d.length > 1 ? d.slice(0, -1).join(', ') + ' & ' + d[d.length - 1] : d[0]) + ' at ' + time12(m[2]);
    }
    if ((m = /^every\s+(\d+)\s*([mh])$/i.exec(s))) {
      var n = +m[1], u = m[2].toLowerCase() === 'm' ? 'min' : (n === 1 ? 'hour' : 'hours');
      return n === 1 && u === 'hour' ? 'Every hour' : 'Every ' + n + ' ' + u;
    }
    return s;
  }
  function feedTitle(f) {
    var vals = Object.keys(f.params || {}).map(function (k) { return f.params[k]; }).filter(function (v) { return v !== '' && v != null && typeof v !== 'object'; });
    return f.kind.toUpperCase() + (vals.length ? ' ' + vals.join(' ') : '');
  }
  function skelRows(n) {
    var l = h('div', { class: 'list', 'aria-hidden': 'true' });
    for (var i = 0; i < n; i++) l.appendChild(h('div', { class: 'item' }, h('div', { class: 'body' }, h('div', { class: 't skel', text: 'METAR VOMM' }), h('div', { class: 's skel', text: 'every 5 min — last 13:30' }))));
    return l;
  }
  var liveLoaded = false;
  function loadLive() {
    var p = $('p-live');
    if (!liveLoaded) { clear(p).appendChild(h('h2', { class: 'sec', text: 'Feeds' })); p.appendChild(skelRows(2)); p.appendChild(h('h2', { class: 'sec', text: 'Schedules' })); p.appendChild(skelRows(2)); }
    Promise.all([feedsList(), getJSON('api/schedules')]).then(function (r) {
      if (sheet.open && liveLoaded) return;
      liveLoaded = true; clear(p);
      p.appendChild(h('div', { class: 'addbar' }, h('button', { class: 'btn small primary', onclick: addSheet }, icon('plus'), 'Add')));
      p.appendChild(h('h2', { class: 'sec', text: 'Feeds' }));
      var fl = h('div', { class: 'list' });
      if (!r[0].length) fl.appendChild(h('div', { class: 'empty', text: 'No feeds yet. Add one to print METARs or ACARS automatically.' }));
      r[0].forEach(function (f) { fl.appendChild(feedRow(f)); });
      p.appendChild(fl);
      if (MOCK.on) p.appendChild(h('p', { class: 'demo', text: 'Feeds API not found on this server — showing demo data.' }));
      p.appendChild(h('h2', { class: 'sec', text: 'Schedules' }));
      var sl = h('div', { class: 'list' });
      if (!r[1].length) sl.appendChild(h('div', { class: 'empty', text: 'Nothing scheduled. Print the morning docket every day at 7:30?' }));
      r[1].forEach(function (s) { sl.appendChild(schedRow(s)); });
      p.appendChild(sl);
    }).catch(function (e) { if (!liveLoaded) clear(p).appendChild(h('div', { class: 'empty', text: 'Could not load: ' + e.message })); });
  }
  function feedRow(f) {
    var sub = [every(f.interval_s), f.last_poll ? 'last ' + clock(f.last_poll) : 'not checked yet', (f.printed || 0) + ' printed'].join(' — ');
    var row = h('div', { class: 'item' }, h('div', { class: 'body' }, h('div', { class: 't', text: feedTitle(f) }),
      h('div', { class: 's', text: f.enabled ? sub : 'Paused — ' + sub }), f.error ? h('div', { class: 's err', text: f.error }) : null));
    row.appendChild(toggle(f.enabled, 'Feed ' + feedTitle(f), function (on, sw) {
      feedCall('POST', 'api/feeds/' + f.id + (on ? '/start' : '/stop')).then(function () { f.enabled = on; refreshLiveSoon(); }).catch(function (e) { sw.setAttribute('aria-checked', on ? 'false' : 'true'); fail(e); });
    }));
    row.appendChild(h('button', { class: 'more', 'aria-label': 'More for ' + feedTitle(f), onclick: function () { feedMenu(f); } }, icon('more')));
    return row;
  }
  function feedMenu(f) {
    openSheet(feedTitle(f), h('div', { class: 'menu' },
      h('button', { text: 'Check now', onclick: function () { feedCall('POST', 'api/feeds/' + f.id + '/poll').then(function () { closeSheet(); toast({ msg: 'Checked ' + feedTitle(f) }); refreshLiveSoon(); }).catch(fail); } }),
      h('button', { text: 'Preview latest', onclick: function () { closeSheet(); if (feedsApi === false) return toast({ msg: 'Preview needs the feeds API', err: true }); showPreview(feedTitle(f), 'api/feeds/' + f.id + '/preview'); } }),
      h('button', { class: 'danger', text: 'Delete feed', onclick: function () { feedCall('DELETE', 'api/feeds/' + f.id).then(function () { closeSheet(); refreshLiveSoon(); }).catch(fail); } })));
  }
  function schedRow(s) {
    var row = h('div', { class: 'item' }, h('div', { class: 'body' }, h('div', { class: 't', text: jobTitle(s.job || 'job') }),
      h('div', { class: 's', text: specWords(s.spec) + (s.last_run ? ' — last ' + when(s.last_run) : '') })));
    row.appendChild(toggle(!!s.enabled, 'Schedule ' + jobTitle(s.job || ''), function (on, sw) {
      api('api/schedules/' + s.id, jreq('PATCH', { enabled: on })).then(function () { s.enabled = on ? 1 : 0; }).catch(function (e) { sw.setAttribute('aria-checked', on ? 'false' : 'true'); fail(e); });
    }));
    row.appendChild(h('button', { class: 'more', 'aria-label': 'More for ' + jobTitle(s.job || ''), onclick: function () {
      openSheet(jobTitle(s.job || ''), [h('p', { class: 'vmeta', text: specWords(s.spec) + ' · ' + s.spec }), h('div', { class: 'menu' },
        h('button', { text: 'Print now', onclick: function () { closeSheet(); var pr = s.params; if (typeof pr === 'string') { try { pr = JSON.parse(pr); } catch (e) { pr = {}; } } runJob(s.job, pr || {}).catch(fail); } }),
        h('button', { class: 'danger', text: 'Delete schedule', onclick: function () { api('api/schedules/' + s.id, { method: 'DELETE' }).then(function () { closeSheet(); refreshLiveSoon(); }).catch(fail); } }))]);
    } }, icon('more')));
    return row;
  }
  function refreshLiveSoon() {
    if (!sheet.open) return loadLive();
    sheet.addEventListener('close', function f() { sheet.removeEventListener('close', f); loadLive(); });
  }

  function addSheet() {
    var mode = 'feed', box = h('div', { class: 'sheet-body-inner', style: 'display:grid;gap:14px' });
    var modes = seg([['feed', 'Feed'], ['schedule', 'Schedule']], 'feed', function (v) { mode = v; render(); }, 'wide');
    openSheet('Add', [modes, box]);
    function render() { clear(box); (mode === 'feed' ? feedForm : schedForm)(box); }
    render();
  }
  function feedForm(box) {
    var load = h('p', { class: 'vmeta', text: 'Loading…' }); box.appendChild(load);
    feedKinds().then(function (kinds) {
      clear(box);
      if (!kinds.length) return box.appendChild(h('p', { class: 'vmeta', text: 'This server has no feed kinds.' }));
      var sel = h('select', { id: 'f-kind' }, kinds.map(function (k) { return h('option', { value: k.kind, text: k.kind.toUpperCase() }); }));
      var desc = h('p', { class: 'vmeta' }), pbox = h('div', { style: 'display:grid;gap:14px' });
      var interval = h('input', { type: 'number', id: 'f-int', min: '1', inputmode: 'numeric' });
      var getters = {};
      function draw() {
        var k = kinds.filter(function (x) { return x.kind === sel.value; })[0];
        desc.textContent = k.description || ''; clear(pbox); getters = {};
        Object.keys(k.params || {}).forEach(function (name) {
          var d = k.params[name], isNum = /int|float|num/.test(d.type), isBool = /bool/.test(d.type), id = 'fp-' + name, inp;
          if (isBool) { inp = h('input', { type: 'checkbox', id: id }); inp.checked = !!d['default']; getters[name] = function () { return inp.checked; }; }
          else {
            inp = h('input', { type: isNum ? 'number' : 'text', id: id, autocapitalize: isNum ? 'off' : 'characters', autocorrect: 'off', spellcheck: 'false', placeholder: d.required ? 'Required' : 'Optional' });
            if (d['default'] != null) inp.value = d['default'];
            getters[name] = function () { var v = inp.value.trim(); if (!v) return undefined; return isNum ? +v : v; };
          }
          getters[name].req = d.required; getters[name].input = inp;
          pbox.appendChild(field(name.replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }) + (d.required ? ' *' : ''), inp, id));
        });
        interval.value = Math.max(1, Math.round((k.default_interval_s || 300) / 60));
      }
      sel.addEventListener('change', draw); draw();
      var ok = h('button', { class: 'btn primary grow', text: 'Add feed' });
      ok.addEventListener('click', function () {
        var params = {}, bad = null;
        Object.keys(getters).forEach(function (n) { var v = getters[n](); if (v === undefined) { if (getters[n].req && !bad) bad = n; } else params[n] = v; });
        if (bad) { getters[bad].input.focus(); return toast({ msg: bad.replace(/_/g, ' ') + ' is required', err: true }); }
        busy(ok, feedCall('POST', 'api/feeds', { kind: sel.value, params: params, interval_s: Math.max(1, +interval.value || 5) * 60 }))
          .then(function () { closeSheet(); toast({ msg: 'Feed added' }); refreshLiveSoon(); }).catch(fail);
      });
      box.appendChild(field('Kind', sel, 'f-kind')); box.appendChild(desc); box.appendChild(pbox);
      box.appendChild(field('Check every (minutes)', interval, 'f-int')); box.appendChild(h('div', { class: 'row-actions' }, ok));
    }).catch(function (e) { load.textContent = 'Could not load feed kinds: ' + e.message; });
  }
  function schedForm(box) {
    var jobSel = h('select', { id: 's-job' }), pbox = h('div'), pf = null;
    getJSON('api/jobs').then(function (jobs) {
      jobs.forEach(function (j) { jobSel.appendChild(h('option', { value: j.name, text: jobTitle(j.name) })); });
      jobSel.value = jobs.some(function (j) { return j.name === 'morning'; }) ? 'morning' : jobs[0].name; drawP();
    }).catch(fail);
    function drawP() { clear(pbox); pf = JOB_PARAMS[jobSel.value] ? JOB_PARAMS[jobSel.value]() : null; if (pf) pbox.appendChild(pf.node); }
    jobSel.addEventListener('change', drawP);
    var kind = 'daily', time = h('input', { type: 'time', id: 's-time', value: '07:30' });
    var days = ['MON', 'FRI'], dayBox = h('div', { class: 'daychips', role: 'group', 'aria-label': 'Days' });
    DAYS.forEach(function (d) {
      var b = h('button', { type: 'button', class: 'pill', 'aria-pressed': days.indexOf(d) >= 0 ? 'true' : 'false', text: cap(d) });
      b.addEventListener('click', function () { var i = days.indexOf(d); if (i >= 0) days.splice(i, 1); else days.push(d); b.setAttribute('aria-pressed', i >= 0 ? 'false' : 'true'); words(); });
      dayBox.appendChild(b);
    });
    var n = h('input', { type: 'number', id: 's-n', min: '1', value: '30', inputmode: 'numeric' });
    var unit = h('select', { 'aria-label': 'Unit' }, h('option', { value: 'm', text: 'minutes' }), h('option', { value: 'h', text: 'hours' }));
    var fTime = field('At', time, 's-time'), fDays = h('div', { class: 'field' }, h('span', { class: 'lbl', text: 'On' }), dayBox);
    var fEvery = h('div', { class: 'field' }, h('label', { class: 'lbl', for: 's-n', text: 'Every' }), h('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:8px' }, n, unit));
    var preview = h('p', { class: 'vmeta' });
    function spec() {
      if (kind === 'daily') return 'daily ' + time.value;
      if (kind === 'weekly') return 'weekly ' + DAYS.filter(function (d) { return days.indexOf(d) >= 0; }).join(',') + ' ' + time.value;
      return 'every ' + (+n.value || 1) + unit.value;
    }
    function words() {
      fTime.hidden = kind === 'every'; fDays.hidden = kind !== 'weekly'; fEvery.hidden = kind !== 'every';
      preview.textContent = (kind === 'weekly' && !days.length) ? 'Pick at least one day' : specWords(spec());
    }
    var when_ = seg([['daily', 'Daily'], ['weekly', 'Weekly'], ['every', 'Every…']], 'daily', function (v) { kind = v; words(); }, 'wide');
    [time, n, unit].forEach(function (e) { e.addEventListener('input', words); e.addEventListener('change', words); });
    var ok = h('button', { class: 'btn primary grow', text: 'Add schedule' });
    ok.addEventListener('click', function () {
      if (kind === 'weekly' && !days.length) return toast({ msg: 'Pick at least one day', err: true });
      if (kind !== 'every' && !time.value) return toast({ msg: 'Pick a time', err: true });
      busy(ok, api('api/schedules', jreq('POST', { spec: spec(), job: jobSel.value, params: pf ? pf.value() : {} })))
        .then(function () { closeSheet(); toast({ msg: 'Scheduled: ' + specWords(spec()) }); refreshLiveSoon(); }).catch(fail);
    });
    add(box, [field('Print', jobSel, 's-job'), pbox, h('div', { class: 'field' }, h('span', { class: 'lbl', text: 'When' }), when_), fTime, fDays, fEvery, preview, h('div', { class: 'row-actions' }, ok)]);
    words();
  }

  // ---- HISTORY -------------------------------------------------------------------------------------
  var histStamp = '', histLoaded = false;
  function loadHistory() {
    var p = $('p-history');
    if (!histLoaded) {
      var g = h('div', { class: 'hgrid', 'aria-hidden': 'true' });
      for (var i = 0; i < 6; i++) g.appendChild(h('div', { class: 'h' }, h('div', { class: 'thumb skel' }), h('div', { class: 'meta' }, h('div', { class: 't skel', text: 'text hello' }), h('div', { class: 's skel', text: 'local · 13:30' }))));
      clear(p).appendChild(g);
    }
    getJSON('api/history?limit=60').then(function (rows) {
      var stamp = rows.map(function (r) { return r.id + r.status; }).join();
      if (stamp === histStamp && histLoaded) return;
      histStamp = stamp; histLoaded = true; clear(p);
      if (!rows.length) return p.appendChild(h('div', { class: 'empty', text: 'Nothing printed yet. Prints show up here.' }));
      p.appendChild(h('div', { class: 'hgrid' }, rows.map(histCard)));
    }).catch(function (e) { if (!histLoaded) clear(p).appendChild(h('div', { class: 'empty', text: 'Could not load history: ' + e.message })); });
  }
  var STATUS = { done: ['Done', 'ok'], failed: ['Failed', 'bad'], skipped: ['Skipped', 'warn'], queued: ['Queued', 'warn'], printing: ['Printing', 'warn'] };
  function chipFor(st) { var s = STATUS[st] || [st, '']; return h('span', { class: 'chip ' + s[1], text: s[0] }); }
  function kindLabel(r) {
    return r.kind.indexOf('job:') === 0 ? jobTitle(r.kind.slice(4)) : r.kind === 'feed' ? 'Paper feed' : r.kind.charAt(0).toUpperCase() + r.kind.slice(1);
  }
  function histCard(r) {
    var b = h('button', { class: 'h', 'aria-label': kindLabel(r) + ', ' + r.status + ', ' + when(r.ts) },
      h('div', { class: 'thumb' + (r.status === 'failed' ? ' failed' : '') }, h('img', { src: 'api/history/' + r.id + '.png', alt: '', loading: 'lazy' })),
      h('div', { class: 'meta' }, h('div', { class: 't', text: r.summary && r.kind.indexOf('job:') !== 0 && r.kind !== 'feed' ? r.summary : kindLabel(r) }),
        h('div', { class: 's2' }, h('span', { class: 's', text: (r.user || 'local') + ' · ' + when(r.ts) }), chipFor(r.status))));
    b.querySelector('img').addEventListener('error', function (e) { e.target.style.visibility = 'hidden'; });
    b.addEventListener('click', function () { histSheet(r); });
    return b;
  }
  function histSheet(r) {
    var src = BASE + 'api/history/' + r.id + '.png';
    var again = h('button', { class: 'btn grow', text: 'Print again' });
    again.addEventListener('click', function () {
      busy(again, api(src).then(function (x) { return x.blob(); }).then(function (blob) {
        var fd = new FormData(); fd.append('file', blob, 'reprint.png');
        return send('api/print/raw', { method: 'POST', body: fd }, 'Reprinting');
      })).then(closeSheet).catch(fail);
    });
    openSheet(kindLabel(r) + ' · #' + r.id, [
      h('div', { class: 'paper' }, h('img', { src: src, alt: 'Printed output for job ' + r.id, width: 384 })),
      h('div', { class: 'vmeta' }, chipFor(r.status), (r.user || 'local') + ' · ' + when(r.ts) + ' · ' + r.height_px + ' px'),
      r.summary ? h('div', { class: 'vmeta', text: r.summary }) : null,
      r.error ? h('div', { class: 'vmeta' }, h('span', { class: 'chip bad', text: r.error })) : null,
      h('div', { class: 'row-actions' }, h('a', { class: 'btn ghost', href: src, target: '_blank', rel: 'noopener', text: 'Open image' }), again)]);
  }

  // ---- settings -----------------------------------------------------------------------------------------
  function loadSettings() { return getJSON('api/settings').then(function (s) { S.settings = s; if (s.timezone) S.tz = s.timezone; density.set(s.density); return s; }); }
  $('btn-settings').addEventListener('click', function () {
    loadSettings().then(function (s) {
      var home = h('input', { type: 'text', id: 'st-home', value: s.home_airport || '', autocapitalize: 'characters', autocorrect: 'off', spellcheck: 'false', maxlength: '4' });
      var aps = h('input', { type: 'text', id: 'st-aps', value: (s.airports || []).join(', '), autocapitalize: 'characters', autocorrect: 'off', spellcheck: 'false' });
      var tz = h('input', { type: 'text', id: 'st-tz', value: s.timezone || '', list: 'tzlist', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false' });
      var dl = h('datalist', { id: 'tzlist' });
      try { (Intl.supportedValuesOf('timeZone') || []).forEach(function (z) { dl.appendChild(h('option', { value: z })); }); } catch (e) {}
      var den = seg([['0', 'Light'], ['1', 'Medium'], ['2', 'Dark']], String(s.density), null, 'wide');
      var st = S.status || {};
      var tr = st.fake ? 'Fake (nothing prints)' : st.transport ? st.transport.toUpperCase() : 'None connected';
      var ok = h('button', { class: 'btn primary grow', text: 'Save' });
      ok.addEventListener('click', function () {
        var body = { home_airport: home.value.trim(), airports: aps.value.split(/[\s,]+/).filter(Boolean), timezone: tz.value.trim(), density: +den._w.get() };
        busy(ok, api('api/settings', jreq('PUT', body)).then(function (r) { return r.json(); })).then(function (n) {
          S.settings = n; S.tz = n.timezone; density.set(n.density); closeSheet(); toast({ msg: 'Settings saved' }); histStamp = '';
        }).catch(fail);
      });
      openSheet('Settings', [field('Home airport (ICAO)', home, 'st-home'), field('Other airports', aps, 'st-aps'),
        h('div', { class: 'field' }, h('span', { class: 'lbl', text: 'Print darkness' }), den),
        field('Timezone', tz, 'st-tz'), dl,
        h('div', { class: 'field' }, h('span', { class: 'lbl', text: 'Transport' }), h('div', { text: tr + (st.user && st.user !== 'local' ? ' · signed in as ' + st.user : '') })),
        h('div', { class: 'row-actions' }, ok)]);
    }).catch(fail);
  });

  // ---- tabs ---------------------------------------------------------------------------------------------------
  var tabs = Array.prototype.slice.call(document.querySelectorAll('#tabs button')), current = null;
  var LOADERS = { fun: loadFun, live: loadLive, history: loadHistory };
  function show(name, push) {
    if (!LOADERS[name] && name !== 'print') name = 'print';
    current = name;
    tabs.forEach(function (t) { var on = t.dataset.tab === name; t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
    Array.prototype.forEach.call(document.querySelectorAll('.panel'), function (p) { p.hidden = p.dataset.panel !== name; });
    if (push !== false && location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
    if (LOADERS[name]) LOADERS[name]();
    scrollTo(0, 0);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { show(t.dataset.tab); });
    t.addEventListener('keydown', function (e) {
      var n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : -1;
      if (n < 0 || n >= tabs.length) return;
      e.preventDefault(); tabs[n].focus(); show(tabs[n].dataset.tab);
    });
  });
  addEventListener('hashchange', function () { var n = location.hash.slice(1); if (n !== current) show(n, false); });

  // ---- boot / polling ---------------------------------------------------------------------------------------------
  show(location.hash.slice(1) || 'print', false);
  loadSettings().catch(function () {});
  refreshStatus();
  setInterval(function () {
    if (document.hidden) return;
    refreshStatus();
    if (sheet.open) return;
    if (current === 'history') loadHistory();
    if (current === 'live') loadLive();
  }, 5000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refreshStatus(); });
})();
