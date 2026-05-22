// ==UserScript==
// @name         LuxWork 诊断测试
// @match        https://luxwork.online/*
// @match        https://*.luxwork.online/*
// @grant        none
// @sandbox      DOM
// @run-at       document-end
// ==/UserScript==

console.log('[LWTEST] 脚本正在运行');

var d = document.createElement('div');
d.id = '_lwtest';
d.style.cssText = 'position:fixed;bottom:10px;left:10px;z-index:2147483647;background:#e53935;color:#fff;padding:12px 18px;border-radius:8px;font-size:14px;font-weight:bold;box-shadow:0 4px 12px rgba(0,0,0,.3)';
d.textContent = '✅ 脚本注入成功！';
document.body.appendChild(d);
setTimeout(function(){ d.remove(); }, 5000);
