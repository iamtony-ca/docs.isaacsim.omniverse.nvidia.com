(function () {
    'use strict';

    var ICON_MAX_PX = 40;
    var SWIPE_MIN_PX = 50;

    function init() {
        var root = document.querySelector('[role="main"]')
            || document.querySelector('.rst-content')
            || document.querySelector('.document')
            || document.querySelector('.body')
            || document.body;

        var candidates = root.querySelectorAll('img');
        var pending = [];

        for (var i = 0; i < candidates.length; i++) {
            var img = candidates[i];
            if (img.classList.contains('logo') || img.classList.contains('no-lightbox')) continue;
            if (isIconSync(img)) continue;
            pending.push(img);
        }

        if (!pending.length) return;

        var overlay = buildOverlay();
        document.body.appendChild(overlay);

        var state = {
            idx: -1,
            imgs: [],
            el: overlay,
            display: overlay.querySelector('.lb-img'),
            caption: overlay.querySelector('.lb-caption'),
            counter: overlay.querySelector('.lb-counter'),
            prev: overlay.querySelector('.lb-prev'),
            next: overlay.querySelector('.lb-next'),
            tx: 0
        };

        attachGlobal(state);

        for (var j = 0; j < pending.length; j++) {
            enrollImage(state, pending[j]);
        }
    }

    function px(v) {
        if (!v) return 0;
        var n = parseInt(v, 10);
        return isNaN(n) ? 0 : n;
    }

    function isIconSync(img) {
        var w = px(img.getAttribute('width')) || px(img.style.width);
        if (w > 0 && w <= ICON_MAX_PX) return true;
        var h = px(img.getAttribute('height')) || px(img.style.height);
        if (h > 0 && h <= ICON_MAX_PX) return true;
        return false;
    }

    function isIconLoaded(img) {
        return img.naturalWidth > 0 && img.naturalWidth <= ICON_MAX_PX
            && img.naturalHeight > 0 && img.naturalHeight <= ICON_MAX_PX;
    }

    function enrollImage(state, img) {
        function activate() {
            if (isIconLoaded(img)) return;
            var idx = state.imgs.length;
            state.imgs.push(img);
            img.style.cursor = 'zoom-in';
            if (img.alt && !img.title && !isPathLike(img.alt)) img.title = img.alt;
            bindClick(state, img, idx);
        }

        if (img.complete) {
            activate();
        } else {
            img.addEventListener('load', activate, { once: true });
        }
    }

    function isPathLike(s) {
        return /\.(?:png|jpe?g|gif|svg|webp|bmp|tiff?|ico|avif)$/i.test(s);
    }

    function isSelfLink(a, img) {
        if (!a || !a.href) return false;
        var href = a.href;
        return href === img.src || href === img.currentSrc;
    }

    function buildOverlay() {
        var d = document.createElement('div');
        d.className = 'lb-overlay';
        d.innerHTML =
            '<button class="lb-close" aria-label="Close lightbox">&times;</button>' +
            '<button class="lb-prev" aria-label="Previous image">&#8249;</button>' +
            '<button class="lb-next" aria-label="Next image">&#8250;</button>' +
            '<div class="lb-stage"><img class="lb-img" alt=""><span class="lb-caption"></span></div>' +
            '<span class="lb-counter"></span>';
        return d;
    }

    function show(s, i) {
        s.idx = i;
        render(s);
        s.el.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function hide(s) {
        s.el.classList.remove('active');
        document.body.style.overflow = '';
        s.idx = -1;
    }

    function render(s) {
        var src = s.imgs[s.idx];
        s.display.src = src.src;
        s.display.alt = src.alt || '';
        var label = src.title || '';
        if (!label && src.alt && !isPathLike(src.alt)) label = src.alt;
        s.display.title = label;
        s.caption.textContent = label;
        s.caption.style.display = label ? '' : 'none';
        var multi = s.imgs.length > 1;
        s.counter.textContent = (s.idx + 1) + ' / ' + s.imgs.length;
        s.prev.style.display = multi ? '' : 'none';
        s.next.style.display = multi ? '' : 'none';
        s.counter.style.display = multi ? '' : 'none';
    }

    function go(s, delta) {
        s.idx = (s.idx + delta + s.imgs.length) % s.imgs.length;
        render(s);
    }

    function bindClick(s, img, idx) {
        var a = img.closest('a');
        var hasExternalLink = a && !isSelfLink(a, img);
        if (hasExternalLink) return;
        img.addEventListener('click', function (e) { e.preventDefault(); show(s, idx); });
        if (a) {
            a.addEventListener('click', function (e) { e.preventDefault(); show(s, idx); });
        }
    }

    function attachGlobal(s) {
        s.el.querySelector('.lb-close').addEventListener('click', function () { hide(s); });
        s.prev.addEventListener('click', function (e) { e.stopPropagation(); go(s, -1); });
        s.next.addEventListener('click', function (e) { e.stopPropagation(); go(s, 1); });

        s.el.addEventListener('click', function (e) {
            if (e.target === s.el || e.target.classList.contains('lb-stage')) hide(s);
        });

        document.addEventListener('keydown', function (e) {
            if (s.idx < 0) return;
            if (e.key === 'Escape') { e.preventDefault(); hide(s); }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); go(s, -1); }
            else if (e.key === 'ArrowRight') { e.preventDefault(); go(s, 1); }
        });

        s.el.addEventListener('touchstart', function (e) {
            s.tx = e.changedTouches[0].screenX;
        }, { passive: true });

        s.el.addEventListener('touchend', function (e) {
            var dx = s.tx - e.changedTouches[0].screenX;
            if (Math.abs(dx) > SWIPE_MIN_PX) go(s, dx > 0 ? 1 : -1);
        }, { passive: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
