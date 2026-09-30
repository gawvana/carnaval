/**
 * pages/automation.js — Экран автоматизации Cardinal:
 * 4 подраздела через сегмент:
 *  - Автовыдача (лоты, привязка файлов, генерация тестовых ключей)
 *  - Склад (товарные файлы, пополнение, скачивание)
 *  - Автоответчик (команды, ответы, уведомления)
 *  - Шаблоны (быстрые ответы)
 */

import {
  getDeliveryLots, createDeliveryLot, updateDeliveryLot, deleteDeliveryLot, createDeliveryTest,
  getProductsFiles, createProductsFile, addGoodsToFile, deleteProductsFile,
  getAutoResponseCommands, createAutoResponseCommand, updateAutoResponseCommand, deleteAutoResponseCommand,
  getTemplates, createTemplate, updateTemplate, deleteTemplate,
  getFunPayLots
} from '../api.js';
import { tg } from '../tg.js';
import { renderHeader } from '../ui/header.js';
import { openSheet, closeSheet, openConfirmSheet } from '../ui/sheet.js';
import { showToast } from '../ui/toast.js';

let _activeTab = 'delivery'; // 'delivery' | 'files' | 'commands' | 'templates'

export async function renderAutomation(wrap) {
  wrap.innerHTML = '';

  const header = renderHeader({
    title: 'Автоматизация',
    subtitle: 'Настройки логики бота',
  });
  wrap.appendChild(header);

  const container = document.createElement('div');
  container.style.paddingTop = '68px';
  container.innerHTML = `
    <!-- Сегмент разделов автоматизации -->
    <div class="seg rv in" id="auto-seg" style="--seg-cols: 4; margin-bottom: 16px">
      <i></i>
      <button class="${_activeTab === 'delivery' ? 'on' : ''}" data-tab="delivery">Выдача</button>
      <button class="${_activeTab === 'files' ? 'on' : ''}" data-tab="files">Склад</button>
      <button class="${_activeTab === 'commands' ? 'on' : ''}" data-tab="commands">Ответы</button>
      <button class="${_activeTab === 'templates' ? 'on' : ''}" data-tab="templates">Шаблоны</button>
    </div>

    <!-- Контент активного подраздела -->
    <div id="auto-content">
      <div style="text-align:center; padding:32px 0"><div style="width:28px; height:28px; border-radius:50%; border:3px solid var(--track); border-top-color:var(--primary); animation:spin 1s linear infinite; margin:0 auto"></div></div>
    </div>
    <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
  `;
  wrap.appendChild(container);

  initSegControl(container);
  await loadActiveSubtab();
}

function initSegControl(root) {
  const seg = root.querySelector('#auto-seg');
  if (!seg) return;
  const buttons = seg.querySelectorAll('button');

  const idxMap = { delivery: 0, files: 1, commands: 2, templates: 3 };
  seg.style.setProperty('--k', String(idxMap[_activeTab] || 0));

  buttons.forEach((btn, idx) => {
    btn.addEventListener('click', async () => {
      tg.haptic.selection();
      buttons.forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      seg.style.setProperty('--k', String(idx));

      _activeTab = btn.dataset.tab;
      await loadActiveSubtab();
    });
  });
}

async function loadActiveSubtab() {
  const content = document.getElementById('auto-content');
  if (!content) return;

  if (_activeTab === 'delivery') {
    await renderDeliverySection(content);
  } else if (_activeTab === 'files') {
    await renderFilesSection(content);
  } else if (_activeTab === 'commands') {
    await renderCommandsSection(content);
  } else if (_activeTab === 'templates') {
    await renderTemplatesSection(content);
  }
}

// ─────────────────────────────────────────────────────────────
// 1. Секция автовыдачи
// ─────────────────────────────────────────────────────────────

async function renderDeliverySection(container) {
  try {
    const res = await getDeliveryLots();
    const lots = res.lots || [];

    container.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
        <h3 class="k" style="margin:0">Лоты с автовыдачей (${lots.length})</h3>
        <button class="btn press" id="add-delivery-lot-btn" style="height:36px; padding:0 14px; font-size:13px">
          + Добавить
        </button>
      </div>

      ${lots.length === 0 ? `
        <div class="empty rv in"><p>Лоты с автовыдачей пока не настроены</p></div>
      ` : `
        <div style="display:grid; gap:10px">
          ${lots.map((l) => `
            <div class="card n press delivery-lot-card rv in" data-index="${l.index}" style="height:auto; min-height:86px; padding:14px; width:100%">
              <div style="display:flex; justify-content:space-between; align-items:flex-start">
                <b style="font-size:15px; flex:1; margin-right:8px">${l.name}</b>
                <span style="font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; background:${l.disable ? 'var(--err-c)' : 'var(--ok-c)'}; color:${l.disable ? 'var(--on-err-c)' : 'var(--on-ok-c)'}">
                  ${l.disable ? 'Выключен' : 'Активен'}
                </span>
              </div>
              <div style="font-size:12px; color:var(--muted); margin:6px 0">
                ${l.productsFileName ? `Файл: <b>${l.productsFileName}</b> (остаток: <b>${l.goods_count}</b> шт.)` : 'Текстовая выдача (без файла)'}
              </div>
              <div style="display:flex; gap:8px; margin-top:8px">
                <button class="btn tn press test-lot-btn" data-index="${l.index}" style="height:32px; font-size:12px; padding:0 10px">Тест ключ</button>
                <button class="btn press edit-lot-btn" data-index="${l.index}" style="height:32px; font-size:12px; padding:0 10px">Настроить</button>
              </div>
            </div>
          `).join('')}
        </div>
      `}
    `;

    document.getElementById('add-delivery-lot-btn')?.addEventListener('click', openAddDeliveryLotModal);

    container.querySelectorAll('.test-lot-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index, 10);
        try {
          const testRes = await createDeliveryTest(idx);
          tg.haptic.notification('success');
          openSheet('Тестовый ключ автовыдачи', `
            <p class="tx">Отправьте этот ключ в чат с продавцом для проверки выдачи лота <b>${testRes.lot_name}</b>:</p>
            <div class="panel" style="background:var(--s); color:var(--on-s); font-family:monospace; padding:14px; word-break:break-all; font-size:13px; user-select:all">
              ${testRes.key}
            </div>
          `);
        } catch (err) {
          showToast(err.message, 'err');
        }
      });
    });

    container.querySelectorAll('.edit-lot-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index, 10);
        const lot = lots[idx];
        if (lot) openEditDeliveryLotModal(lot);
      });
    });
  } catch (err) {
    container.innerHTML = `<div class="empty"><p style="color:var(--err)">${err.message}</p></div>`;
  }
}

function openAddDeliveryLotModal() {
  openSheet('Новая автовыдача', `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Название лота (точно как на FunPay)</label>
        <input type="text" id="new-lot-name" placeholder="Пример: 1000 Золота (RU)" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Текст выдачи (используйте $product для файла)</label>
        <textarea id="new-lot-response" rows="4" placeholder="Привет, $username! Твой товар:\n$product" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px"></textarea>
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Товарный файл (необязательно)</label>
        <input type="text" id="new-lot-file" placeholder="goods.txt" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <button class="btn press" id="save-new-lot-btn" style="margin-top:8px">Создать правило</button>
    </div>
  `);

  document.getElementById('save-new-lot-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('new-lot-name')?.value.trim();
    const response = document.getElementById('new-lot-response')?.value.trim();
    const file = document.getElementById('new-lot-file')?.value.trim() || null;

    if (!name || !response) {
      showToast('Заполните название и текст ответа', 'err');
      return;
    }

    try {
      await createDeliveryLot({ name, response, productsFileName: file });
      showToast('Правило автовыдачи создано', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}

function openEditDeliveryLotModal(lot) {
  openSheet(`Лот: ${lot.name}`, `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Текст выдачи</label>
        <textarea id="edit-lot-response" rows="4" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">${lot.response || ''}</textarea>
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Имя товарного файла</label>
        <input type="text" id="edit-lot-file" value="${lot.productsFileName || ''}" placeholder="goods.txt (или оставьте пустым)" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <div class="row">
        <span>Отключить автовыдачу</span>
        <button class="sw" id="edit-lot-disable-sw" role="switch" aria-checked="${lot.disable}"><i></i></button>
      </div>
      <div style="display:flex; gap:10px; margin-top:12px">
        <button class="btn press" id="save-edit-lot-btn">Сохранить</button>
        <button class="btn err press" id="delete-lot-btn">Удалить</button>
      </div>
    </div>
  `);

  const sw = document.getElementById('edit-lot-disable-sw');
  sw?.addEventListener('click', () => {
    const cur = sw.getAttribute('aria-checked') === 'true';
    sw.setAttribute('aria-checked', String(!cur));
  });

  document.getElementById('save-edit-lot-btn')?.addEventListener('click', async () => {
    const response = document.getElementById('edit-lot-response')?.value.trim();
    const file = document.getElementById('edit-lot-file')?.value.trim();
    const disable = sw.getAttribute('aria-checked') === 'true';

    try {
      await updateDeliveryLot(lot.index, { response, productsFileName: file, disable });
      showToast('Настройки лота сохранены', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });

  document.getElementById('delete-lot-btn')?.addEventListener('click', () => {
    openConfirmSheet({
      title: 'Удаление правила',
      message: `Удалить автовыдачу для лота "${lot.name}"?`,
      danger: true,
      onConfirm: async () => {
        try {
          await deleteDeliveryLot(lot.index);
          showToast('Правило удалено', 'ok');
          loadActiveSubtab();
        } catch (e) {
          showToast(e.message, 'err');
        }
      },
    });
  });
}

// ─────────────────────────────────────────────────────────────
// 2. Секция склада (товарные файлы)
// ─────────────────────────────────────────────────────────────

async function renderFilesSection(container) {
  try {
    const res = await getProductsFiles();
    const files = res.files || [];

    container.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
        <h3 class="k" style="margin:0">Склад товаров (${files.length})</h3>
        <button class="btn press" id="add-file-btn" style="height:36px; padding:0 14px; font-size:13px">
          + Создать файл
        </button>
      </div>

      ${files.length === 0 ? `
        <div class="empty rv in"><p>В папке storage/products/ пока нет файлов</p></div>
      ` : `
        <div style="display:grid; gap:10px">
          ${files.map((f) => `
            <div class="card n press file-card rv in" data-name="${f.name}" style="height:auto; min-height:76px; padding:14px; width:100%; display:flex; justify-content:space-between; align-items:center">
              <div>
                <b style="font-size:15px; display:block">${f.name}</b>
                <span style="font-size:12px; color:var(--muted)">Товаров в наличии: <b style="color:var(--primary)">${f.count}</b> шт.</span>
              </div>
              <div style="display:flex; gap:6px">
                <button class="btn tn press add-goods-btn" data-name="${f.name}" style="height:32px; font-size:12px; padding:0 10px">+ Пополнить</button>
                <button class="btn press view-file-btn" data-name="${f.name}" style="height:32px; font-size:12px; padding:0 10px">Файл</button>
              </div>
            </div>
          `).join('')}
        </div>
      `}
    `;

    document.getElementById('add-file-btn')?.addEventListener('click', openCreateFileModal);

    container.querySelectorAll('.add-goods-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openAddGoodsModal(btn.dataset.name);
      });
    });

    container.querySelectorAll('.view-file-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openFileDetailsModal(btn.dataset.name);
      });
    });
  } catch (err) {
    container.innerHTML = `<div class="empty"><p style="color:var(--err)">${err.message}</p></div>`;
  }
}

function openCreateFileModal() {
  openSheet('Создать товарный файл', `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Имя файла (без спецсимволов)</label>
        <input type="text" id="new-filename" placeholder="keys.txt" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Начальные товары (по 1 строке на товар)</label>
        <textarea id="new-file-goods" rows="5" placeholder="Ключ 1\nКлюч 2\nКлюч 3" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px"></textarea>
      </div>
      <button class="btn press" id="confirm-create-file-btn" style="margin-top:8px">Создать файл</button>
    </div>
  `);

  document.getElementById('confirm-create-file-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('new-filename')?.value.trim();
    const raw = document.getElementById('new-file-goods')?.value || '';
    const goods = raw.split('\n').map((l) => l.trim()).filter(Boolean);

    if (!name) {
      showToast('Введите имя файла', 'err');
      return;
    }

    try {
      await createProductsFile(name, goods);
      showToast(`Файл ${name} создан`, 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}

function openAddGoodsModal(filename) {
  openSheet(`Пополнить ${filename}`, `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Вставьте товары (1 строка = 1 штука)</label>
        <textarea id="add-goods-textarea" rows="6" placeholder="Товар 1\nТовар 2" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px"></textarea>
      </div>
      <div class="row">
        <span>Добавить в начало очереди</span>
        <button class="sw" id="at-zero-sw" role="switch" aria-checked="false"><i></i></button>
      </div>
      <button class="btn press" id="confirm-add-goods-btn" style="margin-top:8px">Добавить товары</button>
    </div>
  `);

  const sw = document.getElementById('at-zero-sw');
  sw?.addEventListener('click', () => {
    const cur = sw.getAttribute('aria-checked') === 'true';
    sw.setAttribute('aria-checked', String(!cur));
  });

  document.getElementById('confirm-add-goods-btn')?.addEventListener('click', async () => {
    const raw = document.getElementById('add-goods-textarea')?.value || '';
    const goods = raw.split('\n').map((l) => l.trim()).filter(Boolean);
    const atZero = sw?.getAttribute('aria-checked') === 'true';

    if (goods.length === 0) {
      showToast('Введите хотя бы один товар', 'err');
      return;
    }

    try {
      const res = await addGoodsToFile(filename, goods, atZero);
      showToast(`Добавлено ${goods.length} шт. Всего: ${res.count}`, 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}

function openFileDetailsModal(filename) {
  openSheet(`Файл: ${filename}`, `
    <div style="display:flex; flex-direction:column; gap:10px">
      <a href="/api/delivery/files/${encodeURIComponent(filename)}/download" target="_blank" class="btn press" style="text-decoration:none">
        Скачать файл (.txt)
      </a>
      <button class="btn err press" id="delete-file-btn">
        Удалить файл со склада
      </button>
    </div>
  `);

  document.getElementById('delete-file-btn')?.addEventListener('click', () => {
    openConfirmSheet({
      title: 'Удаление файла',
      message: `Удалить товарный файл "${filename}"? Все товары внутри будут безвозвратно стёрты.`,
      danger: true,
      onConfirm: async () => {
        try {
          await deleteProductsFile(filename);
          showToast(`Файл ${filename} удалён`, 'ok');
          loadActiveSubtab();
        } catch (e) {
          showToast(e.message, 'err');
        }
      },
    });
  });
}

// ─────────────────────────────────────────────────────────────
// 3. Секция автоответчика
// ─────────────────────────────────────────────────────────────

async function renderCommandsSection(container) {
  try {
    const res = await getAutoResponseCommands();
    const cmds = res.commands || [];

    container.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
        <h3 class="k" style="margin:0">Команды автоответа (${cmds.length})</h3>
        <button class="btn press" id="add-command-btn" style="height:36px; padding:0 14px; font-size:13px">
          + Добавить
        </button>
      </div>

      ${cmds.length === 0 ? `
        <div class="empty rv in"><p>Команд автоответа пока нет</p></div>
      ` : `
        <div style="display:grid; gap:10px">
          ${cmds.map((c) => `
            <div class="card n press cmd-card rv in" data-index="${c.index}" style="height:auto; min-height:80px; padding:14px; width:100%">
              <div style="display:flex; justify-content:space-between; align-items:center">
                <b style="font-size:15px; color:var(--primary)">${c.command}</b>
                <span style="font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; background:${c.enabled ? 'var(--ok-c)' : 'var(--track)'}; color:${c.enabled ? 'var(--on-ok-c)' : 'var(--muted)'}">
                  ${c.enabled ? 'Включен' : 'Отключен'}
                </span>
              </div>
              <div style="font-size:13px; margin:6px 0; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical">
                ${c.response}
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--muted); margin-top:6px">
                <span>Уведомление в TG: <b>${c.telegramNotification ? 'Да' : 'Нет'}</b></span>
                <button class="btn tn press edit-cmd-btn" data-index="${c.index}" style="height:28px; font-size:11px; padding:0 8px">Настроить</button>
              </div>
            </div>
          `).join('')}
        </div>
      `}
    `;

    document.getElementById('add-command-btn')?.addEventListener('click', openAddCommandModal);

    container.querySelectorAll('.edit-cmd-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index, 10);
        const cmd = cmds[idx];
        if (cmd) openEditCommandModal(cmd);
      });
    });
  } catch (err) {
    container.innerHTML = `<div class="empty"><p style="color:var(--err)">${err.message}</p></div>`;
  }
}

function openAddCommandModal() {
  openSheet('Новая команда автоответа', `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Команда или фраза (можно через |)</label>
        <input type="text" id="new-cmd-name" placeholder="!хелп|помощь|help" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Текст ответа</label>
        <textarea id="new-cmd-response" rows="4" placeholder="Привет, $username! Чем могу помочь?" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px"></textarea>
      </div>
      <div class="row">
        <span>Уведомлять в Telegram</span>
        <button class="sw" id="new-cmd-tg-sw" role="switch" aria-checked="false"><i></i></button>
      </div>
      <button class="btn press" id="confirm-add-cmd-btn" style="margin-top:8px">Создать команду</button>
    </div>
  `);

  const tgSw = document.getElementById('new-cmd-tg-sw');
  tgSw?.addEventListener('click', () => {
    const cur = tgSw.getAttribute('aria-checked') === 'true';
    tgSw.setAttribute('aria-checked', String(!cur));
  });

  document.getElementById('confirm-add-cmd-btn')?.addEventListener('click', async () => {
    const command = document.getElementById('new-cmd-name')?.value.trim();
    const response = document.getElementById('new-cmd-response')?.value.trim();
    const telegramNotification = tgSw.getAttribute('aria-checked') === 'true';

    if (!command || !response) {
      showToast('Заполните команду и текст ответа', 'err');
      return;
    }

    try {
      await createAutoResponseCommand({ command, response, telegramNotification });
      showToast('Команда автоответа создана', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}

function openEditCommandModal(cmd) {
  openSheet(`Команда: ${cmd.command}`, `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Команда или набор (|)</label>
        <input type="text" id="edit-cmd-name" value="${cmd.command}" style="width:100%; height:44px; border-radius:14px; border:1px solid var(--outline); padding:0 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">
      </div>
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Текст ответа</label>
        <textarea id="edit-cmd-response" rows="4" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px">${cmd.response}</textarea>
      </div>
      <div class="row">
        <span>Включена</span>
        <button class="sw" id="edit-cmd-en-sw" role="switch" aria-checked="${cmd.enabled}"><i></i></button>
      </div>
      <div class="row">
        <span>Уведомлять в Telegram</span>
        <button class="sw" id="edit-cmd-tg-sw" role="switch" aria-checked="${cmd.telegramNotification}"><i></i></button>
      </div>
      <div style="display:flex; gap:10px; margin-top:12px">
        <button class="btn press" id="save-edit-cmd-btn">Сохранить</button>
        <button class="btn err press" id="delete-cmd-btn">Удалить</button>
      </div>
    </div>
  `);

  const enSw = document.getElementById('edit-cmd-en-sw');
  enSw?.addEventListener('click', () => {
    const cur = enSw.getAttribute('aria-checked') === 'true';
    enSw.setAttribute('aria-checked', String(!cur));
  });

  const tgSw = document.getElementById('edit-cmd-tg-sw');
  tgSw?.addEventListener('click', () => {
    const cur = tgSw.getAttribute('aria-checked') === 'true';
    tgSw.setAttribute('aria-checked', String(!cur));
  });

  document.getElementById('save-edit-cmd-btn')?.addEventListener('click', async () => {
    const command = document.getElementById('edit-cmd-name')?.value.trim();
    const response = document.getElementById('edit-cmd-response')?.value.trim();
    const enabled = enSw.getAttribute('aria-checked') === 'true';
    const telegramNotification = tgSw.getAttribute('aria-checked') === 'true';

    try {
      await updateAutoResponseCommand(cmd.index, { command, response, enabled, telegramNotification });
      showToast('Команда обновлена', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });

  document.getElementById('delete-cmd-btn')?.addEventListener('click', () => {
    openConfirmSheet({
      title: 'Удаление команды',
      message: `Удалить команду "${cmd.command}"?`,
      danger: true,
      onConfirm: async () => {
        try {
          await deleteAutoResponseCommand(cmd.index);
          showToast('Команда удалена', 'ok');
          loadActiveSubtab();
        } catch (e) {
          showToast(e.message, 'err');
        }
      },
    });
  });
}

// ─────────────────────────────────────────────────────────────
// 4. Секция шаблонов
// ─────────────────────────────────────────────────────────────

async function renderTemplatesSection(container) {
  try {
    const res = await getTemplates();
    const tmpls = res.templates || [];

    container.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
        <h3 class="k" style="margin:0">Шаблоны ответов (${tmpls.length})</h3>
        <button class="btn press" id="add-template-btn" style="height:36px; padding:0 14px; font-size:13px">
          + Добавить
        </button>
      </div>

      ${tmpls.length === 0 ? `
        <div class="empty rv in"><p>Заготовок ответов пока нет</p></div>
      ` : `
        <div style="display:grid; gap:8px">
          ${tmpls.map((t) => `
            <div class="card n press tmpl-card rv in" data-index="${t.index}" style="height:auto; min-height:64px; padding:12px 14px; width:100%; display:flex; justify-content:space-between; align-items:center">
              <div style="font-size:14px; flex:1; margin-right:12px">${t.text}</div>
              <div style="display:flex; gap:6px; flex:none">
                <button class="btn tn press edit-tmpl-btn" data-index="${t.index}" style="height:28px; font-size:11px; padding:0 8px">Изменить</button>
                <button class="btn err press del-tmpl-btn" data-index="${t.index}" style="height:28px; font-size:11px; padding:0 8px">✕</button>
              </div>
            </div>
          `).join('')}
        </div>
      `}
    `;

    document.getElementById('add-template-btn')?.addEventListener('click', openAddTemplateModal);

    container.querySelectorAll('.edit-tmpl-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index, 10);
        const tmpl = tmpls[idx];
        if (tmpl) openEditTemplateModal(tmpl);
      });
    });

    container.querySelectorAll('.del-tmpl-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index, 10);
        try {
          await deleteTemplate(idx);
          showToast('Шаблон удален', 'ok');
          loadActiveSubtab();
        } catch (err) {
          showToast(err.message, 'err');
        }
      });
    });
  } catch (err) {
    container.innerHTML = `<div class="empty"><p style="color:var(--err)">${err.message}</p></div>`;
  }
}

function openAddTemplateModal() {
  openSheet('Новый шаблон ответа', `
    <div style="display:grid; gap:12px">
      <div>
        <label style="font-size:12px; color:var(--muted); font-weight:600">Текст шаблона</label>
        <textarea id="new-tmpl-text" rows="3" placeholder="Здравствуйте, $username! Спасибо за покупку." style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on); margin-top:4px"></textarea>
      </div>
      <button class="btn press" id="confirm-add-tmpl-btn">Добавить шаблон</button>
    </div>
  `);

  document.getElementById('confirm-add-tmpl-btn')?.addEventListener('click', async () => {
    const text = document.getElementById('new-tmpl-text')?.value.trim();
    if (!text) {
      showToast('Введите текст шаблона', 'err');
      return;
    }
    try {
      await createTemplate(text);
      showToast('Шаблон сохранен', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}

function openEditTemplateModal(tmpl) {
  openSheet('Редактировать шаблон', `
    <div style="display:grid; gap:12px">
      <div>
        <textarea id="edit-tmpl-text" rows="3" style="width:100%; border-radius:14px; border:1px solid var(--outline); padding:10px 12px; font:inherit; background:var(--bg); color:var(--on)">${tmpl.text}</textarea>
      </div>
      <button class="btn press" id="save-edit-tmpl-btn">Сохранить</button>
    </div>
  `);

  document.getElementById('save-edit-tmpl-btn')?.addEventListener('click', async () => {
    const text = document.getElementById('edit-tmpl-text')?.value.trim();
    if (!text) {
      showToast('Текст не может быть пустым', 'err');
      return;
    }
    try {
      await updateTemplate(tmpl.index, text);
      showToast('Шаблон обновлен', 'ok');
      closeSheet();
      loadActiveSubtab();
    } catch (e) {
      showToast(e.message, 'err');
    }
  });
}
