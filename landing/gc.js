/* Caffe Steve — shared front-end helpers (vanilla, no framework).
   Safe to load on every page. Degrades gracefully without GSAP. */
(function () {
  'use strict';

  // --- nav shadow on scroll ---
  function initNav() {
    var nav = document.querySelector('.nav');
    if (!nav) return;
    var onScroll = function () {
      nav.classList.toggle('scrolled', window.scrollY > 8);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // --- scroll reveal (IntersectionObserver; fires once) ---
  // Elements with [data-rv] fade+rise once when they enter view.
  // Children of [data-rv-group] are staggered. Opacity stays visible if JS/IO absent.
  function initReveal() {
    var els = Array.prototype.slice.call(document.querySelectorAll('[data-rv]'));
    document.querySelectorAll('[data-rv-group]').forEach(function (grp) {
      Array.prototype.forEach.call(grp.children, function (c, i) {
        c.dataset.rvDelay = (i * 0.08).toFixed(2);
        els.push(c);
      });
    });
    if (!('IntersectionObserver' in window)) return; // leave visible
    // respect reduced-motion: skip the reveal animation, leave content visible
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    els.forEach(function (el) {
      var d = el.dataset.rvDelay || 0;
      el.style.opacity = '0';
      el.style.transform = 'translateY(28px)';
      el.style.transition = 'opacity .8s ease ' + d + 's, transform .8s cubic-bezier(.22,.61,.36,1) ' + d + 's';
      el.style.willChange = 'opacity, transform';
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.style.opacity = '1';
          e.target.style.transform = 'none';
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.08 });
    els.forEach(function (el) { io.observe(el); });
  }

  // --- stamp current year wherever [data-year] appears ---
  function initYear() {
    var y = new Date().getFullYear();
    document.querySelectorAll('[data-year]').forEach(function (el) { el.textContent = y; });
  }

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }
  ready(function () { initNav(); initReveal(); initYear(); });

  // --- backend / auth wiring -------------------------------------------------
  // The static landing site talks to the Caffe Steve hub (FastAPI on Railway).
  // Base URL precedence: ?backend= query  ->  localStorage  ->  window global
  //   ->  Railway default. The first two let the verification harness point the
  // pages at a throwaway local backend without editing source.
  var DEFAULT_BACKEND = 'https://golden-coffee-production.up.railway.app';
  var TOKEN_KEY = 'gc_token';
  var USER_KEY = 'gc_user';

  function resolveBackend() {
    try {
      var q = new URLSearchParams(window.location.search).get('backend');
      if (q) { localStorage.setItem('gc_backend', q); }
      var saved = localStorage.getItem('gc_backend');
      if (saved) return saved.replace(/\/+$/, '');
    } catch (e) { /* private mode / no storage */ }
    if (window.GC_BACKEND) return String(window.GC_BACKEND).replace(/\/+$/, '');
    return DEFAULT_BACKEND;
  }

  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function lsDel(k) { try { localStorage.removeItem(k); } catch (e) {} }

  // expose a tiny helper for pages that need GSAP-or-fallback
  window.GC = {
    fmtGBP: function (n) {
      return '£' + Math.round(n).toLocaleString('en-GB');
    },
    qs: function (k) {
      return new URLSearchParams(window.location.search).get(k);
    },

    backend: resolveBackend,

    // session helpers (token + cached user)
    token: function () { return lsGet(TOKEN_KEY); },
    setSession: function (token, user) {
      if (token) lsSet(TOKEN_KEY, token);
      if (user) lsSet(USER_KEY, JSON.stringify(user));
    },
    user: function () {
      try { return JSON.parse(lsGet(USER_KEY) || 'null'); } catch (e) { return null; }
    },
    clearSession: function () { lsDel(TOKEN_KEY); lsDel(USER_KEY); },

    // JSON fetch wrapper. Resolves to the parsed body on 2xx; rejects with
    // {status, detail} otherwise (network errors surface as status 0).
    api: function (path, opts) {
      opts = opts || {};
      var headers = { 'Content-Type': 'application/json' };
      if (opts.auth) {
        var t = lsGet(TOKEN_KEY);
        if (t) headers['Authorization'] = 'Bearer ' + t;
      }
      Object.keys(opts.headers || {}).forEach(function (k) { headers[k] = opts.headers[k]; });
      var cfg = { method: opts.method || 'GET', headers: headers };
      if (opts.body !== undefined) cfg.body = JSON.stringify(opts.body);
      return fetch(resolveBackend() + path, cfg).then(function (res) {
        return res.text().then(function (txt) {
          var data = {};
          try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = { detail: txt }; }
          if (res.ok) return data;
          var err = new Error(data.detail || ('Request failed (' + res.status + ')'));
          err.status = res.status; err.detail = data.detail || err.message;
          throw err;
        });
      }, function (netErr) {
        var err = new Error('Network error — could not reach Caffe Steve. Check your connection and try again.');
        err.status = 0; err.detail = err.message; err.cause = netErr;
        throw err;
      });
    }
  };
})();
