// ==UserScript==
// @name         LuxWork 批量图片上传
// @namespace    http://tampermonkey.net/
// @version      3.0.0
// @description  批量上传图片到 LuxWork 商品编辑页
// @match        https://luxwork.online/*
// @match        https://*.luxwork.online/*
// @require      https://cdn.bootcdn.net/ajax/libs/jszip/3.10.1/jszip.min.js
// @grant        none
// @sandbox      DOM
// @run-at       document-end
// ==/UserScript==

(function () {
    'use strict';

    // ── UI ──────────────────────────────────────────────────────────────────
    document.head.insertAdjacentHTML('beforeend', `<style>
        #_lw{position:fixed;bottom:70px;right:16px;z-index:2147483647;font:13px/1.4 sans-serif}
        #_lw_btn{width:48px;height:48px;border-radius:50%;background:#1a3c5e;color:#fff;
            font-size:22px;display:flex;align-items:center;justify-content:center;
            cursor:grab;box-shadow:0 3px 12px rgba(0,0,0,.3);margin-left:auto;user-select:none}
        #_lw_btn:active{cursor:grabbing}
        #_lw_box{display:none;position:absolute;bottom:56px;right:0;width:270px;background:#fff;
            border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.15);padding:14px;border:1px solid #ddd}
        ._lw_h{display:flex;justify-content:space-between;align-items:center;
            padding-bottom:10px;border-bottom:1px solid #f0f0f0;margin-bottom:10px}
        ._lw_h b{color:#1a3c5e;font-size:13px}
        ._lw_h span{cursor:pointer;color:#aaa;font-size:17px;line-height:1}
        ._lw_h span:hover{color:#555}
        ._lw_r{display:flex;flex-direction:column;gap:7px;margin-bottom:10px}
        ._lw_b{padding:9px;border:none;border-radius:7px;color:#fff;cursor:pointer;
            font-size:12px;font-weight:600;width:100%}
        ._lw_b1{background:#1a3c5e} ._lw_b2{background:#2d6a4f}
        ._lw_b:disabled{opacity:.45;cursor:not-allowed}
        #_lw_s{font-size:11px;color:#555;min-height:16px;margin-bottom:6px}
        #_lw_g{max-height:110px;overflow-y:auto;background:#f8f9fa;border-radius:5px;
            padding:6px 8px;font-size:11px;display:none}
        #_lw_g .ok{color:#2e7d32} #_lw_g .er{color:#c62828} #_lw_g .in{color:#1565c0}
        ._lw_row{display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:11px;color:#555}
        ._lw_row input{width:46px;border:1px solid #ddd;border-radius:4px;padding:3px 5px;font-size:11px}
    </style>`);

    document.body.insertAdjacentHTML('beforeend', `
        <div id="_lw">
            <div id="_lw_box">
                <div class="_lw_h"><b>📦 批量图片上传</b><span id="_lw_x">✕</span></div>
                <div class="_lw_r">
                    <button class="_lw_b _lw_b1" id="_lw_z">📦 选择 ZIP 压缩包</button>
                    <button class="_lw_b _lw_b2" id="_lw_d">📁 选择本地文件夹</button>
                </div>
                <div class="_lw_row">
                    每张间隔(秒): <input type="number" id="_lw_dl" value="2" min="0.5" max="30" step="0.5">
                </div>
                <div id="_lw_s">就绪，等待选择文件…</div>
                <div id="_lw_g"></div>
                <input type="file" id="_lw_zi" accept=".zip" style="display:none">
                <input type="file" id="_lw_di" webkitdirectory multiple style="display:none">
            </div>
            <div id="_lw_btn" title="批量图片上传">📦</div>
        </div>
    `);

    const btn  = document.getElementById('_lw_btn');
    const box  = document.getElementById('_lw_box');
    const bz   = document.getElementById('_lw_z');
    const bd   = document.getElementById('_lw_d');
    const zi   = document.getElementById('_lw_zi');
    const di   = document.getElementById('_lw_di');
    const stat = document.getElementById('_lw_s');
    const log  = document.getElementById('_lw_g');
    const dlIn = document.getElementById('_lw_dl');

    btn.onclick  = () => box.style.display = box.style.display === 'none' ? 'block' : 'none';
    document.getElementById('_lw_x').onclick = () => box.style.display = 'none';
    bz.onclick   = () => zi.click();
    bd.onclick   = () => di.click();

    // ── helpers ─────────────────────────────────────────────────────────────
    const IMG = /\.(jpe?g|png|gif|webp|bmp|tiff?|svg)$/i;
    const MIME = { jpg:'image/jpeg', jpeg:'image/jpeg', png:'image/png', gif:'image/gif',
                   webp:'image/webp', bmp:'image/bmp', svg:'image/svg+xml',
                   tiff:'image/tiff', tif:'image/tiff' };

    function addLog(msg, cls) {
        const d = document.createElement('div');
        if (cls) d.className = cls;
        d.textContent = msg;
        log.appendChild(d);
        log.scrollTop = log.scrollHeight;
        log.style.display = 'block';
    }
    function setStat(m) { stat.textContent = m; }
    function sleep(ms)  { return new Promise(r => setTimeout(r, ms)); }
    function nSort(a, b){ return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }); }

    // ── find the upload <input> ──────────────────────────────────────────────
    function findInput() {
        return document.querySelector('.img-selector input[type="file"]')
            || document.querySelector('#gallery input[type="file"]')
            || document.querySelector('.img-uploader input[type="file"]');
    }

    // ── inject ONE file into the page input ─────────────────────────────────
    function injectOne(file) {
        const inp = findInput();
        if (!inp) throw new Error('未找到上传框 (.img-selector input[type="file"])');
        const dt = new DataTransfer();
        dt.items.add(file);
        try {
            Object.defineProperty(inp, 'files', { value: dt.files, configurable: true, writable: true });
        } catch (e) { /* ignore */ }
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        inp.dispatchEvent(new Event('input',  { bubbles: true }));
    }

    // ── upload queue: one by one with delay ─────────────────────────────────
    let busy = false;
    async function upload(images) {
        if (busy) { addLog('上传中，请等待…', 'in'); return; }
        busy = true;
        bz.disabled = bd.disabled = true;
        log.innerHTML = '';
        log.style.display = 'block';

        const delay = Math.max(500, parseFloat(dlIn.value) * 1000 || 2000);
        addLog(`共 ${images.length} 张，间隔 ${dlIn.value}s`, 'in');

        let ok = 0;
        for (let i = 0; i < images.length; i++) {
            const { name, file } = images[i];
            setStat(`上传 ${i + 1}/${images.length}：${name}`);
            try {
                injectOne(file);
                addLog(`✓ ${name}`, 'ok');
                ok++;
            } catch (e) {
                addLog(`✗ ${name}：${e.message}`, 'er');
            }
            if (i < images.length - 1) await sleep(delay);
        }

        setStat(`完成！成功 ${ok}/${images.length} 张`);
        addLog('── 完成 ──', 'in');
        bz.disabled = bd.disabled = false;
        busy = false;
    }

    // ── ZIP handler ─────────────────────────────────────────────────────────
    zi.addEventListener('change', async (e) => {
        const f = e.target.files[0];
        zi.value = '';
        if (!f) return;
        if (typeof JSZip === 'undefined') { setStat('JSZip 未加载，请刷新页面重试'); return; }
        setStat('解析 ZIP…');
        log.innerHTML = '';
        try {
            const zip     = await new JSZip().loadAsync(f);
            const entries = Object.values(zip.files)
                .filter(x => !x.dir && IMG.test(x.name))
                .sort((a, b) => nSort(a.name, b.name));
            if (!entries.length) { setStat('ZIP 中无图片'); return; }
            const images = [];
            for (const entry of entries) {
                const blob = await entry.async('blob');
                const ext  = entry.name.split('.').pop().toLowerCase();
                const name = entry.name.split('/').pop();
                images.push({ name, file: new File([blob], name, { type: MIME[ext] || 'image/jpeg' }) });
            }
            await upload(images);
        } catch (e) {
            setStat('ZIP 错误：' + e.message);
        }
    });

    // ── Folder handler ───────────────────────────────────────────────────────
    di.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files)
            .filter(f => IMG.test(f.name))
            .sort((a, b) => nSort(a.name, b.name));
        di.value = '';
        if (!files.length) { setStat('文件夹中无图片'); return; }
        await upload(files.map(f => ({ name: f.name, file: f })));
    });

    // ── Drag support ─────────────────────────────────────────────────────────
    const lw = document.getElementById('_lw');
    let dragging = false, dragOX, dragOY;

    btn.addEventListener('mousedown', function (e) {
        if (e.button !== 0) return;
        const r = lw.getBoundingClientRect();
        lw.style.right  = 'auto';
        lw.style.bottom = 'auto';
        lw.style.left   = r.left + 'px';
        lw.style.top    = r.top  + 'px';
        dragOX = e.clientX - r.left;
        dragOY = e.clientY - r.top;
        dragging = true;
        e.preventDefault();
    });

    document.addEventListener('mousemove', function (e) {
        if (!dragging) return;
        var x = Math.max(0, Math.min(window.innerWidth  - lw.offsetWidth,  e.clientX - dragOX));
        var y = Math.max(0, Math.min(window.innerHeight - lw.offsetHeight, e.clientY - dragOY));
        lw.style.left = x + 'px';
        lw.style.top  = y + 'px';
    });

    document.addEventListener('mouseup', function () { dragging = false; });

})();
