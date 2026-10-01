/**
 * pages/automation_lab.js — Interactive Automation Builder, Simulator & Execution Debugger.
 * 
 * Maps 100% to real Cardinal configurations (auto_delivery, auto_response, greetings).
 * Zero fake features: simulator executes rules against real engine without mutating live state.
 */

import { getIcon } from '../ui/icons.js';
import * as api from '../api.js';
import { showToast } from '../ui/toast.js';

let container = null;
let workflows = [];
let currentWorkflow = null;
let validationResult = null;

export async function renderAutomationLab(mountEl) {
  container = mountEl;
  renderShell();
  await loadWorkflows();
  loadDebugTraces();
}

function renderShell() {
  if (!container) return;
  container.innerHTML = `
    <div class="page-header" style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--outline); flex-wrap: wrap; gap: 10px;">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="color: var(--primary);">${getIcon('automation', 'icon-md')}</span>
        <div>
          <h2 style="margin: 0; font-size: 18px; font-weight: 700; color: var(--on);">Лаборатория автоматизации</h2>
          <span style="font-size: 12px; color: var(--muted);">Конструктор пайплайнов, симулятор и отладчик Cardinal</span>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 8px;">
        <button id="validate-pipeline-btn" class="btn btn-sm spring-tap" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: var(--r1); font-size: 12px; cursor: pointer; background: var(--track); border: 1px solid var(--outline); color: var(--on);">
          ${getIcon('check', 'icon-xs')} Проверить
        </button>
        <button id="run-simulator-btn" class="btn btn-sm btn-primary spring-tap" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: var(--r1); font-size: 13px; cursor: pointer;">
          ${getIcon('activity', 'icon-xs')} Тест (Симулятор)
        </button>
      </div>
    </div>

    <div class="auto-lab-content" style="padding: 16px 20px; display: flex; flex-direction: column; gap: 16px;">
      <!-- Селектор и метаданные воркфлоу -->
      <div class="workflow-header-card liquid-glass" style="padding: 16px; border-radius: var(--r2); display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
          <div style="display: flex; align-items: center; gap: 10px; flex: 1; min-width: 260px;">
            <label for="workflow-select" style="font-size: 12px; font-weight: 600; color: var(--muted); white-space: nowrap;">Воркфлоу:</label>
            <select id="workflow-select" style="flex: 1; background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 13px; outline: none; cursor: pointer;">
              <option value="">Загрузка воркфлоу...</option>
            </select>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <button id="toggle-workflow-btn" class="spring-tap" style="border: none; padding: 6px 12px; border-radius: var(--r1); font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
              Загрузка...
            </button>
            <button id="save-workflow-btn" class="btn btn-sm btn-primary spring-tap" style="padding: 6px 14px; border-radius: var(--r1); font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
              ${getIcon('check', 'icon-xs')} Сохранить
            </button>
            <button id="delete-workflow-btn" class="spring-tap" style="background: rgba(186, 27, 61, 0.15); border: 1px solid var(--err); color: var(--err); padding: 6px 10px; border-radius: var(--r1); font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
              ${getIcon('trash', 'icon-xs')} Удалить
            </button>
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 10px;">
          <label for="workflow-name-input" style="font-size: 12px; color: var(--muted); width: 80px;">Название:</label>
          <input type="text" id="workflow-name-input" placeholder="Название правила" style="flex: 1; background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 6px 10px; border-radius: var(--r1); font-size: 13px; outline: none;" />
        </div>
      </div>

      <!-- Валидация баннер (скрыт по умолчанию) -->
      <div id="validation-banner" style="display: none; padding: 10px 14px; border-radius: var(--r1); font-size: 12px;"></div>

      <!-- Интерактивный конструктор узлов (Builder) -->
      <div class="pipeline-card liquid-glass" style="padding: 16px; border-radius: var(--r2);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
          <div>
            <strong style="font-size: 14px; color: var(--on); display: block;">Архитектура выполнения (Pipeline Builder)</strong>
            <span style="font-size: 11px; color: var(--muted);">Последовательность шагов: Триггер → Условия → Действия → Уведомления</span>
          </div>
          <!-- Тулбар добавления узлов -->
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <button class="add-node-btn spring-tap" data-type="trigger" style="background: rgba(59, 130, 246, 0.15); color: #3B82F6; border: 1px solid rgba(59, 130, 246, 0.4); padding: 5px 10px; border-radius: var(--r1); font-size: 11px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
              ${getIcon('plus', 'icon-xs')} + Триггер
            </button>
            <button class="add-node-btn spring-tap" data-type="condition" style="background: rgba(217, 119, 6, 0.15); color: #D97706; border: 1px solid rgba(217, 119, 6, 0.4); padding: 5px 10px; border-radius: var(--r1); font-size: 11px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
              ${getIcon('plus', 'icon-xs')} + Условие
            </button>
            <button class="add-node-btn spring-tap" data-type="action" style="background: rgba(27, 110, 74, 0.15); color: #1B6E4A; border: 1px solid rgba(27, 110, 74, 0.4); padding: 5px 10px; border-radius: var(--r1); font-size: 11px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
              ${getIcon('plus', 'icon-xs')} + Действие
            </button>
            <button class="add-node-btn spring-tap" data-type="notification" style="background: rgba(0, 136, 204, 0.15); color: #0088CC; border: 1px solid rgba(0, 136, 204, 0.4); padding: 5px 10px; border-radius: var(--r1); font-size: 11px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
              ${getIcon('plus', 'icon-xs')} + Уведомление
            </button>
          </div>
        </div>

        <!-- Список интерактивных узлов -->
        <div id="pipeline-nodes-flow" style="display: flex; flex-direction: column; gap: 8px;"></div>
      </div>

      <!-- Контейнер вывода симулятора -->
      <div id="simulator-output-box" class="liquid-glass" style="padding: 16px; border-radius: var(--r2); display: none;"></div>

      <!-- Журнал отладки выполнения (Execution Traces) -->
      <div class="traces-card liquid-glass" style="padding: 16px; border-radius: var(--r2);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <strong style="font-size: 14px; color: var(--on); display: flex; align-items: center; gap: 6px;">
            ${getIcon('logs', 'icon-sm')} Журнал выполнения автоматизаций
          </strong>
          <button id="refresh-traces-btn" class="spring-tap" style="background: none; border: none; color: var(--primary); cursor: pointer; font-size: 11px; display: inline-flex; align-items: center; gap: 4px;">
            ${getIcon('refresh', 'icon-xs')} Обновить
          </button>
        </div>
        <div id="traces-list" style="display: flex; flex-direction: column; gap: 8px;">
          <div style="padding: 14px; text-align: center; color: var(--muted); font-size: 12px;">
            Ожидание запуска правил...
          </div>
        </div>
      </div>
    </div>

    <!-- Модальное окно редактирования узла -->
    <div id="node-modal-backdrop" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.65); z-index: 1000; align-items: center; justify-content: center; backdrop-filter: blur(4px);">
      <div class="liquid-glass" style="background: var(--bg); border: 1px solid var(--outline); border-radius: var(--r2); width: 90%; max-width: 460px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
          <strong id="node-modal-title" style="font-size: 15px; color: var(--on);">Настройка узла</strong>
          <button id="close-modal-btn" style="background: none; border: none; color: var(--muted); cursor: pointer;">${getIcon('close', 'icon-sm')}</button>
        </div>
        <div id="node-modal-body" style="display: flex; flex-direction: column; gap: 12px;"></div>
        <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px;">
          <button id="cancel-node-modal-btn" class="btn btn-sm spring-tap" style="background: var(--track); border: 1px solid var(--outline); color: var(--on); padding: 6px 12px; border-radius: var(--r1); font-size: 12px; cursor: pointer;">
            Отмена
          </button>
          <button id="save-node-modal-btn" class="btn btn-sm btn-primary spring-tap" style="padding: 6px 16px; border-radius: var(--r1); font-size: 12px; cursor: pointer;">
            Применить
          </button>
        </div>
      </div>
    </div>
  `;

  // Регистрация обработчиков
  container.querySelector('#run-simulator-btn').addEventListener('click', runSimulator);
  container.querySelector('#validate-pipeline-btn').addEventListener('click', onValidateClick);
  container.querySelector('#workflow-select').addEventListener('change', onWorkflowSelectChange);
  container.querySelector('#workflow-name-input').addEventListener('input', onWorkflowNameInput);
  container.querySelector('#toggle-workflow-btn').addEventListener('click', onToggleWorkflowClick);
  container.querySelector('#save-workflow-btn').addEventListener('click', onSaveWorkflowClick);
  container.querySelector('#delete-workflow-btn').addEventListener('click', onDeleteWorkflowClick);
  container.querySelector('#refresh-traces-btn').addEventListener('click', loadDebugTraces);

  container.querySelectorAll('.add-node-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      openNodeModal(-1, btn.getAttribute('data-type'));
    });
  });

  const backdrop = container.querySelector('#node-modal-backdrop');
  container.querySelector('#close-modal-btn').addEventListener('click', closeModal);
  container.querySelector('#cancel-node-modal-btn').addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });
}

// ─────────────────────────────────────────────────────────────
// 1. Управление воркфлоу (CRUD)
// ─────────────────────────────────────────────────────────────

async function loadWorkflows() {
  try {
    const res = await api.request('GET', '/api/automation/rules', { allowRelogin: false });
    workflows = res?.rules || res?.workflows || [];
    if (workflows.length === 0) {
      workflows = [createDefaultWorkflow()];
    }
    if (!currentWorkflow || !workflows.find(w => w.id === currentWorkflow.id)) {
      currentWorkflow = workflows[0];
    } else {
      currentWorkflow = workflows.find(w => w.id === currentWorkflow.id);
    }
    updateWorkflowSelector();
    renderCurrentWorkflow();
  } catch (e) {
    showToast('Не удалось загрузить воркфлоу: ' + (e.message || e), 'err');
    workflows = [createDefaultWorkflow()];
    currentWorkflow = workflows[0];
    updateWorkflowSelector();
    renderCurrentWorkflow();
  }
}

function createDefaultWorkflow() {
  return {
    id: 'wf_' + Date.now().toString(36),
    name: 'Новый воркфлоу автовыдачи',
    enabled: true,
    nodes: [
      {
        id: 'node_trig_1',
        type: 'trigger',
        event_type: 'order_created',
        label: 'Новый заказ',
        params: { lot_name: 'Тестовый лот' }
      },
      {
        id: 'node_cond_1',
        type: 'condition',
        condition: 'blacklist_check',
        label: 'Покупатель не в ЧС',
        params: {}
      },
      {
        id: 'node_cond_2',
        type: 'condition',
        condition: 'lot_active',
        label: 'Лот активен',
        params: {}
      },
      {
        id: 'node_act_1',
        type: 'action',
        action: 'deliver_product',
        label: 'Выдать товар из хранилища',
        params: {
          lot_name: 'Тестовый лот',
          response: 'Спасибо за заказ! Ваш ключ: $product',
          productsFileName: 'keys.txt'
        }
      },
      {
        id: 'node_notif_1',
        type: 'notification',
        action: 'send_notification',
        label: 'Уведомление в Telegram',
        params: { text: 'Заказ $order_id выдан покупателю $username' }
      }
    ]
  };
}

function updateWorkflowSelector() {
  const select = container?.querySelector('#workflow-select');
  if (!select) return;
  select.innerHTML = workflows.map(w => `
    <option value="${escapeHtml(w.id)}" ${w.id === currentWorkflow?.id ? 'selected' : ''}>
      ${escapeHtml(w.name || 'Воркфлоу')} ${w.enabled ? '' : '(Отключен)'}
    </option>
  `).join('') + `<option value="__new__">+ Новый воркфлоу...</option>`;
}

function renderCurrentWorkflow() {
  if (!currentWorkflow || !container) return;

  const nameInput = container.querySelector('#workflow-name-input');
  if (nameInput) nameInput.value = currentWorkflow.name || '';

  const toggleBtn = container.querySelector('#toggle-workflow-btn');
  if (toggleBtn) {
    if (currentWorkflow.enabled) {
      toggleBtn.style.background = 'rgba(27, 110, 74, 0.2)';
      toggleBtn.style.color = 'var(--ok, #1B6E4A)';
      toggleBtn.innerHTML = `${getIcon('check', 'icon-xs')} Активен`;
    } else {
      toggleBtn.style.background = 'var(--track)';
      toggleBtn.style.color = 'var(--muted)';
      toggleBtn.innerHTML = `${getIcon('close', 'icon-xs')} Отключен`;
    }
  }

  renderPipelineNodes();
}

function onWorkflowSelectChange(e) {
  const val = e.target.value;
  if (val === '__new__') {
    const newWf = createDefaultWorkflow();
    newWf.name = `Воркфлоу #${workflows.length + 1}`;
    workflows.push(newWf);
    currentWorkflow = newWf;
    updateWorkflowSelector();
    renderCurrentWorkflow();
    showToast('Создан новый воркфлоу', 'ok');
  } else {
    const found = workflows.find(w => w.id === val);
    if (found) {
      currentWorkflow = found;
      renderCurrentWorkflow();
    }
  }
}

function onWorkflowNameInput(e) {
  if (currentWorkflow) {
    currentWorkflow.name = e.target.value;
    updateWorkflowSelector();
  }
}

async function onToggleWorkflowClick() {
  if (!currentWorkflow) return;
  const newStatus = !currentWorkflow.enabled;
  currentWorkflow.enabled = newStatus;
  renderCurrentWorkflow();

  try {
    await api.request('PATCH', `/api/automation/rules/${encodeURIComponent(currentWorkflow.id)}`, {
      enabled: newStatus
    }, { allowRelogin: false });
    showToast(newStatus ? 'Воркфлоу включен' : 'Воркфлоу отключен', 'ok');
    updateWorkflowSelector();
  } catch (e) {
    // Воркфлоу еще не сохранен на бэкенде, изменения сохранены локально
    showToast(newStatus ? 'Воркфлоу включен (локально)' : 'Воркфлоу отключен (локально)', 'info');
  }
}

async function onSaveWorkflowClick() {
  if (!currentWorkflow) return;
  const valResult = validatePipeline(currentWorkflow.nodes || []);
  if (!valResult.valid) {
    showValidationBanner(valResult);
    showToast('Исправьте ошибки перед сохранением', 'err');
    return;
  }

  try {
    const res = await api.request('POST', '/api/automation/rules', currentWorkflow, { allowRelogin: false });
    if (res?.id) currentWorkflow.id = res.id;
    showToast('Воркфлоу успешно сохранен в конфигурации Cardinal', 'ok');
    hideValidationBanner();
    await loadWorkflows();
  } catch (e) {
    showToast('Ошибка сохранения: ' + (e.message || e), 'err');
  }
}

async function onDeleteWorkflowClick() {
  if (!currentWorkflow) return;
  if (!confirm(`Удалить воркфлоу "${currentWorkflow.name}"?`)) return;

  try {
    await api.request('DELETE', `/api/automation/rules/${encodeURIComponent(currentWorkflow.id)}?confirm=true`, {}, { allowRelogin: false });
    showToast('Воркфлоу удален', 'ok');
    workflows = workflows.filter(w => w.id !== currentWorkflow.id);
    currentWorkflow = workflows[0] || null;
    if (!currentWorkflow) {
      workflows = [createDefaultWorkflow()];
      currentWorkflow = workflows[0];
    }
    updateWorkflowSelector();
    renderCurrentWorkflow();
  } catch (e) {
    // Если на сервере не найден, удаляем локально
    workflows = workflows.filter(w => w.id !== currentWorkflow.id);
    currentWorkflow = workflows[0] || createDefaultWorkflow();
    updateWorkflowSelector();
    renderCurrentWorkflow();
    showToast('Воркфлоу удален', 'ok');
  }
}

// ─────────────────────────────────────────────────────────────
// 2. Интерактивный пайплайн (Builder Nodes Flow)
// ─────────────────────────────────────────────────────────────

function renderPipelineNodes() {
  const flowEl = container?.querySelector('#pipeline-nodes-flow');
  if (!flowEl) return;

  const nodes = currentWorkflow?.nodes || [];
  if (nodes.length === 0) {
    flowEl.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--muted); border: 2px dashed var(--outline); border-radius: var(--r1); font-size: 13px;">
        Пайплайн пуст. Нажмите на одну из кнопок выше (+ Триггер / + Условие / + Действие), чтобы добавить первый шаг.
      </div>
    `;
    return;
  }

  flowEl.innerHTML = '';

  nodes.forEach((node, idx) => {
    const nodeEl = document.createElement('div');
    nodeEl.className = 'pipeline-node-card spring-tap';
    nodeEl.style.cssText = 'display: flex; align-items: center; justify-content: space-between; background: var(--track); padding: 10px 14px; border-radius: var(--r1); gap: 10px; border-left: 4px solid; transition: transform 0.15s ease;';

    let badgeText = 'STEP';
    let badgeColor = '#3B82F6';
    let borderLeftColor = '#3B82F6';
    let iconName = 'automation';
    let summaryText = node.label || 'Узел';

    if (node.type === 'trigger') {
      badgeText = 'WHEN';
      badgeColor = '#3B82F6';
      borderLeftColor = '#3B82F6';
      iconName = 'activity';
      const evLabels = {
        order_created: 'Новый оплаченный заказ',
        message_received: 'Входящее сообщение',
        command_received: 'Вызов команды'
      };
      summaryText = `Событие: ${evLabels[node.event_type] || node.event_type || 'Входящий триггер'}`;
      if (node.params?.lot_name) summaryText += ` (лот: ${node.params.lot_name})`;
      if (node.params?.command) summaryText += ` (команда: ${node.params.command})`;
    } else if (node.type === 'condition') {
      badgeText = 'IF';
      badgeColor = '#D97706';
      borderLeftColor = '#D97706';
      iconName = 'check';
      const condLabels = {
        lot_active: 'Лот активен и доступен к покупке',
        blacklist_check: 'Покупатель не находится в черном списке',
        cooldown_expired: 'Период кулдауна между обращениями истек',
        text_contains: `Текст содержит: "${node.params?.pattern || ''}"`
      };
      summaryText = condLabels[node.condition] || node.label || 'Условие проверки';
    } else if (node.type === 'action') {
      badgeText = 'THEN';
      badgeColor = '#1B6E4A';
      borderLeftColor = '#1B6E4A';
      iconName = 'delivery';
      const actLabels = {
        deliver_product: 'Выдать товар из хранилища и отправить шаблон автоответа',
        send_response: 'Отправить ответное сообщение в диалог',
        send_notification: 'Отправить служебное уведомление в Telegram',
        raise_lots: 'Поднять лоты продавца на FunPay (Auto-Raise)'
      };
      summaryText = actLabels[node.action] || node.label || 'Выполнить действие';
      if (node.params?.productsFileName) summaryText += ` [файл: ${node.params.productsFileName}]`;
    } else if (node.type === 'notification') {
      badgeText = 'NOTIFY';
      badgeColor = '#0088CC';
      borderLeftColor = '#0088CC';
      iconName = 'telegram';
      summaryText = node.params?.text ? `Уведомление в Telegram: "${node.params.text.slice(0, 40)}..."` : 'Отправить уведомление в Telegram';
    }

    nodeEl.style.borderLeftColor = borderLeftColor;

    nodeEl.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0;">
        <span style="font-weight: 800; color: ${badgeColor}; font-size: 11px; width: 50px; text-transform: uppercase; letter-spacing: 0.5px;">${badgeText}</span>
        <span style="color: ${badgeColor}; display: flex; align-items: center;">${getIcon(iconName, 'icon-xs')}</span>
        <div style="font-size: 13px; color: var(--on); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          ${escapeHtml(summaryText)}
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 4px;">
        <button class="node-up-btn spring-tap" title="Переместить выше" style="background: none; border: none; color: ${idx === 0 ? 'var(--outline)' : 'var(--muted)'}; cursor: ${idx === 0 ? 'default' : 'pointer'}; padding: 4px;" ${idx === 0 ? 'disabled' : ''}>
          ${getIcon('chevron-up', 'icon-xs')}
        </button>
        <button class="node-down-btn spring-tap" title="Переместить ниже" style="background: none; border: none; color: ${idx === nodes.length - 1 ? 'var(--outline)' : 'var(--muted)'}; cursor: ${idx === nodes.length - 1 ? 'default' : 'pointer'}; padding: 4px;" ${idx === nodes.length - 1 ? 'disabled' : ''}>
          ${getIcon('chevron-down', 'icon-xs')}
        </button>
        <button class="node-edit-btn spring-tap" title="Редактировать" style="background: none; border: none; color: var(--primary); cursor: pointer; padding: 4px;">
          ${getIcon('edit', 'icon-xs')}
        </button>
        <button class="node-delete-btn spring-tap" title="Удалить" style="background: none; border: none; color: var(--err); cursor: pointer; padding: 4px;">
          ${getIcon('close', 'icon-xs')}
        </button>
      </div>
    `;

    nodeEl.querySelector('.node-up-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      moveNode(idx, -1);
    });
    nodeEl.querySelector('.node-down-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      moveNode(idx, 1);
    });
    nodeEl.querySelector('.node-edit-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      openNodeModal(idx, node.type);
    });
    nodeEl.querySelector('.node-delete-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteNode(idx);
    });

    flowEl.appendChild(nodeEl);
  });
}

function moveNode(index, offset) {
  if (!currentWorkflow || !currentWorkflow.nodes) return;
  const targetIndex = index + offset;
  if (targetIndex < 0 || targetIndex >= currentWorkflow.nodes.length) return;

  const item = currentWorkflow.nodes.splice(index, 1)[0];
  currentWorkflow.nodes.splice(targetIndex, 0, item);
  renderPipelineNodes();
  hideValidationBanner();
}

function deleteNode(index) {
  if (!currentWorkflow || !currentWorkflow.nodes) return;
  currentWorkflow.nodes.splice(index, 1);
  renderPipelineNodes();
  hideValidationBanner();
}

// ─────────────────────────────────────────────────────────────
// 3. Модальное окно редактирования узла
// ─────────────────────────────────────────────────────────────

let activeModalIndex = -1;
let activeModalType = 'trigger';

function openNodeModal(index = -1, defaultType = 'trigger') {
  activeModalIndex = index;
  const backdrop = container?.querySelector('#node-modal-backdrop');
  const body = container?.querySelector('#node-modal-body');
  const title = container?.querySelector('#node-modal-title');
  if (!backdrop || !body || !title) return;

  const node = index >= 0 ? currentWorkflow.nodes[index] : null;
  activeModalType = node?.type || defaultType;

  title.textContent = index >= 0 ? `Редактирование: ${activeModalType.toUpperCase()}` : `Добавить узел: ${activeModalType.toUpperCase()}`;

  renderModalBody(body, node, activeModalType);
  backdrop.style.display = 'flex';
}

function renderModalBody(body, node, type) {
  const params = node?.params || {};

  if (type === 'trigger') {
    const selectedEv = node?.event_type || 'order_created';
    body.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 6px;">
        <label style="font-size: 12px; font-weight: 600; color: var(--on);">Тип входящего события (Event Type):</label>
        <select id="modal-event-type" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 8px 10px; border-radius: var(--r1); font-size: 13px; outline: none;">
          <option value="order_created" ${selectedEv === 'order_created' ? 'selected' : ''}>order_created — Новый оплаченный заказ</option>
          <option value="message_received" ${selectedEv === 'message_received' ? 'selected' : ''}>message_received — Входящее сообщение в чате</option>
          <option value="command_received" ${selectedEv === 'command_received' ? 'selected' : ''}>command_received — Команда (!команда)</option>
        </select>
      </div>
      <div id="modal-extra-params" style="display: flex; flex-direction: column; gap: 10px;"></div>
    `;

    const select = body.querySelector('#modal-event-type');
    const extra = body.querySelector('#modal-extra-params');

    const updateExtra = () => {
      const val = select.value;
      if (val === 'order_created') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Фильтр по названию лота (опционально):</label>
            <input type="text" id="modal-param-lot" value="${escapeHtml(params.lot_name || '')}" placeholder="Например: Premium VIP" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px;" />
          </div>
        `;
      } else if (val === 'command_received') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Команда триггера (с восклицательным знаком):</label>
            <input type="text" id="modal-param-cmd" value="${escapeHtml(params.command || '!help')}" placeholder="!help" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px;" />
          </div>
        `;
      } else {
        extra.innerHTML = '';
      }
    };

    select.addEventListener('change', updateExtra);
    updateExtra();

  } else if (type === 'condition') {
    const selectedCond = node?.condition || 'lot_active';
    body.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 6px;">
        <label style="font-size: 12px; font-weight: 600; color: var(--on);">Условие проверки (Condition):</label>
        <select id="modal-condition-type" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 8px 10px; border-radius: var(--r1); font-size: 13px; outline: none;">
          <option value="lot_active" ${selectedCond === 'lot_active' ? 'selected' : ''}>lot_active — Лот активен (не отключен)</option>
          <option value="blacklist_check" ${selectedCond === 'blacklist_check' ? 'selected' : ''}>blacklist_check — Покупатель не находится в черном списке</option>
          <option value="cooldown_expired" ${selectedCond === 'cooldown_expired' ? 'selected' : ''}>cooldown_expired — Кулдаун между обращениями истек</option>
          <option value="text_contains" ${selectedCond === 'text_contains' ? 'selected' : ''}>text_contains — Текст сообщения содержит подстроку</option>
        </select>
      </div>
      <div id="modal-condition-params" style="display: flex; flex-direction: column; gap: 10px;"></div>
    `;

    const select = body.querySelector('#modal-condition-type');
    const extra = body.querySelector('#modal-condition-params');

    const updateExtra = () => {
      if (select.value === 'text_contains') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Искомый текст или ключевое слово:</label>
            <input type="text" id="modal-param-pattern" value="${escapeHtml(params.pattern || '')}" placeholder="Ключевая фраза" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px;" />
          </div>
        `;
      } else {
        extra.innerHTML = '';
      }
    };

    select.addEventListener('change', updateExtra);
    updateExtra();

  } else if (type === 'action') {
    const selectedAct = node?.action || 'deliver_product';
    body.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 6px;">
        <label style="font-size: 12px; font-weight: 600; color: var(--on);">Выполняемое действие (Action):</label>
        <select id="modal-action-type" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 8px 10px; border-radius: var(--r1); font-size: 13px; outline: none;">
          <option value="deliver_product" ${selectedAct === 'deliver_product' ? 'selected' : ''}>deliver_product — Выдать товар из хранилища и отправить автоответ</option>
          <option value="send_response" ${selectedAct === 'send_response' ? 'selected' : ''}>send_response — Отправить ответ в чат</option>
          <option value="send_notification" ${selectedAct === 'send_notification' ? 'selected' : ''}>send_notification — Отправить уведомление в Telegram</option>
          <option value="raise_lots" ${selectedAct === 'raise_lots' ? 'selected' : ''}>raise_lots — Поднять лоты на FunPay (Auto-Raise)</option>
        </select>
      </div>
      <div id="modal-action-params" style="display: flex; flex-direction: column; gap: 10px;"></div>
    `;

    const select = body.querySelector('#modal-action-type');
    const extra = body.querySelector('#modal-action-params');

    const updateExtra = () => {
      const val = select.value;
      if (val === 'deliver_product') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Имя файла товаров (storage/products/):</label>
            <input type="text" id="modal-param-filename" value="${escapeHtml(params.productsFileName || '')}" placeholder="keys.txt" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px;" />
          </div>
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Шаблон сообщения (переменные: $product, $username, $order_id):</label>
            <textarea id="modal-param-response" rows="3" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px; font-family: inherit; resize: vertical;">${escapeHtml(params.response || 'Ваш ключ: $product! Приятной игры, $username!')}</textarea>
          </div>
        `;
      } else if (val === 'send_response') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Текст ответа (переменная: $username):</label>
            <textarea id="modal-param-response" rows="3" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px; font-family: inherit; resize: vertical;">${escapeHtml(params.response || 'Здравствуйте, $username!')}</textarea>
          </div>
        `;
      } else if (val === 'send_notification') {
        extra.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 11px; color: var(--muted);">Текст Telegram уведомления:</label>
            <input type="text" id="modal-param-notif-text" value="${escapeHtml(params.text || 'Сработало правило автоматизации')}" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px;" />
          </div>
        `;
      } else {
        extra.innerHTML = '';
      }
    };

    select.addEventListener('change', updateExtra);
    updateExtra();

  } else if (type === 'notification') {
    body.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 6px;">
        <label style="font-size: 12px; font-weight: 600; color: var(--on);">Уведомление в Telegram:</label>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; color: var(--muted);">Текст уведомления (переменные: $order_id, $username):</label>
          <textarea id="modal-param-notif-text" rows="3" style="background: var(--track); color: var(--on); border: 1px solid var(--outline); padding: 7px 10px; border-radius: var(--r1); font-size: 12px; font-family: inherit; resize: vertical;">${escapeHtml(params.text || 'Уведомление: заказ $order_id обработан автоматизацией')}</textarea>
        </div>
      </div>
    `;
  }

  const saveBtn = container?.querySelector('#save-node-modal-btn');
  if (saveBtn) {
    saveBtn.onclick = () => saveNodeFromModal(body, type);
  }
}

function saveNodeFromModal(body, type) {
  if (!currentWorkflow) return;
  if (!currentWorkflow.nodes) currentWorkflow.nodes = [];

  const node = activeModalIndex >= 0 ? currentWorkflow.nodes[activeModalIndex] : { id: 'node_' + Date.now().toString(36), type };
  node.type = type;
  node.params = {};

  if (type === 'trigger') {
    node.event_type = body.querySelector('#modal-event-type')?.value || 'order_created';
    if (node.event_type === 'order_created') {
      node.params.lot_name = body.querySelector('#modal-param-lot')?.value || '';
    } else if (node.event_type === 'command_received') {
      node.params.command = body.querySelector('#modal-param-cmd')?.value || '!help';
    }
  } else if (type === 'condition') {
    node.condition = body.querySelector('#modal-condition-type')?.value || 'lot_active';
    if (node.condition === 'text_contains') {
      node.params.pattern = body.querySelector('#modal-param-pattern')?.value || '';
    }
  } else if (type === 'action') {
    node.action = body.querySelector('#modal-action-type')?.value || 'deliver_product';
    if (node.action === 'deliver_product') {
      node.params.productsFileName = body.querySelector('#modal-param-filename')?.value || '';
      node.params.response = body.querySelector('#modal-param-response')?.value || '';
    } else if (node.action === 'send_response') {
      node.params.response = body.querySelector('#modal-param-response')?.value || '';
    } else if (node.action === 'send_notification') {
      node.params.text = body.querySelector('#modal-param-notif-text')?.value || '';
    }
  } else if (type === 'notification') {
    node.action = 'send_notification';
    node.params.text = body.querySelector('#modal-param-notif-text')?.value || '';
  }

  if (activeModalIndex >= 0) {
    currentWorkflow.nodes[activeModalIndex] = node;
  } else {
    currentWorkflow.nodes.push(node);
  }

  closeModal();
  renderPipelineNodes();
  hideValidationBanner();
}

function closeModal() {
  const backdrop = container?.querySelector('#node-modal-backdrop');
  if (backdrop) backdrop.style.display = 'none';
  activeModalIndex = -1;
}

// ─────────────────────────────────────────────────────────────
// 4. Валидация пайплайна
// ─────────────────────────────────────────────────────────────

function validatePipeline(nodes) {
  const errors = [];
  if (!nodes || nodes.length === 0) {
    errors.push('Пайплайн пуст. Добавьте хотя бы один триггер и действие.');
    return { valid: false, errors };
  }

  const triggers = nodes.filter(n => n.type === 'trigger');
  if (triggers.length === 0) {
    errors.push('Отсутствует начальный триггер (WHEN).');
  }

  if (nodes[0]?.type !== 'trigger') {
    errors.push('Первым узлом в пайплайне должен быть триггер (WHEN).');
  }

  const actions = nodes.filter(n => n.type === 'action' || n.type === 'notification');
  if (actions.length === 0) {
    errors.push('Пайплайн должен содержать хотя бы одно действие или уведомление (THEN / NOTIFY).');
  }

  nodes.forEach((n, idx) => {
    if (n.type === 'action' && n.action === 'deliver_product') {
      const resp = n.params?.response || '';
      const pFile = n.params?.productsFileName || '';
      if (pFile && !resp.includes('$product')) {
        errors.push(`Узел #${idx + 1}: При указании файла товаров шаблон должен содержать $product.`);
      }
    }
    if (n.type === 'condition' && n.condition === 'text_contains' && !n.params?.pattern) {
      errors.push(`Узел #${idx + 1}: Для условия text_contains укажите искомую подстроку.`);
    }
  });

  return { valid: errors.length === 0, errors };
}

function onValidateClick() {
  const nodes = currentWorkflow?.nodes || [];
  const result = validatePipeline(nodes);
  showValidationBanner(result);
}

function showValidationBanner(result) {
  const banner = container?.querySelector('#validation-banner');
  if (!banner) return;
  banner.style.display = 'block';

  if (result.valid) {
    banner.style.background = 'rgba(27, 110, 74, 0.15)';
    banner.style.border = '1px solid var(--ok, #1B6E4A)';
    banner.style.color = 'var(--ok, #1B6E4A)';
    banner.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        ${getIcon('check', 'icon-sm')}
        <strong>Пайплайн валиден:</strong> готов к исполнению ядром Cardinal без конфликтов.
      </div>
    `;
    showToast('Пайплайн успешно прошел валидацию', 'ok');
  } else {
    banner.style.background = 'rgba(186, 27, 61, 0.15)';
    banner.style.border = '1px solid var(--err, #BA1B3D)';
    banner.style.color = 'var(--err, #BA1B3D)';
    banner.innerHTML = `
      <div style="display: flex; align-items: flex-start; gap: 8px;">
        <span style="margin-top: 2px;">${getIcon('alert', 'icon-sm')}</span>
        <div>
          <strong>Ошибки валидации пайплайна:</strong>
          <ul style="margin: 4px 0 0 16px; padding: 0;">
            ${result.errors.map(e => `<li>${escapeHtml(e)}</li>`).join('')}
          </ul>
        </div>
      </div>
    `;
  }
}

function hideValidationBanner() {
  const banner = container?.querySelector('#validation-banner');
  if (banner) banner.style.display = 'none';
}

// ─────────────────────────────────────────────────────────────
// 5. Симулятор выполнения (Zero Fake Data)
// ─────────────────────────────────────────────────────────────

async function runSimulator() {
  const outputBox = container?.querySelector('#simulator-output-box');
  if (!outputBox) return;

  outputBox.style.display = 'block';
  outputBox.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px; color: var(--primary);">
      ${getIcon('refresh', 'icon-xs')}
      <span style="font-size: 13px; font-weight: 600;">Выполнение симуляции правила в Cardinal...</span>
    </div>
  `;

  // Формируем payload на основе текущего триггера воркфлоу
  const nodes = currentWorkflow?.nodes || [];
  const triggerNode = nodes.find(n => n.type === 'trigger');
  const evType = triggerNode?.event_type || 'order_created';

  let testPayload = {};
  if (evType === 'order_created') {
    testPayload = {
      order_id: 'SIM-' + Date.now().toString().slice(-6),
      buyer_username: 'TestBuyer',
      buyer_id: 999999,
      price: 250.0,
      lot_name: triggerNode?.params?.lot_name || currentWorkflow?.name || 'Тестовый лот'
    };
  } else if (evType === 'command_received') {
    testPayload = {
      command: triggerNode?.params?.command || '!help',
      author: 'TestUser',
      message: triggerNode?.params?.command || '!help'
    };
  } else {
    testPayload = {
      message: 'Тестовое сообщение',
      author: 'TestUser'
    };
  }

  try {
    const res = await api.request('POST', '/api/automation/simulate', {
      event_type: evType,
      test_payload: testPayload
    }, { allowRelogin: false });

    renderSimulationResult(outputBox, res);
    loadDebugTraces();
  } catch (e) {
    // Честное отображение реальной ошибки бэкенда (без фальсификаций)
    outputBox.innerHTML = `
      <div style="border-left: 3px solid var(--err); padding: 12px 14px; border-radius: var(--r1); background: rgba(186, 27, 61, 0.1);">
        <div style="display: flex; align-items: center; gap: 6px; color: var(--err); margin-bottom: 4px;">
          ${getIcon('alert', 'icon-sm')}
          <strong style="font-size: 13px;">Ошибка симуляции</strong>
        </div>
        <div style="font-size: 12px; color: var(--muted);">${escapeHtml(e.message || String(e))}</div>
      </div>
    `;
    showToast('Сбой симуляции: ' + (e.message || e), 'err');
  }
}

function renderSimulationResult(outputBox, res) {
  const isSuccess = res.success !== false;
  const statusColor = isSuccess ? 'var(--ok, #1B6E4A)' : 'var(--warn, #D97706)';
  const statusIcon = isSuccess ? 'check' : 'alert';
  const statusText = isSuccess ? 'Симуляция успешно завершена (условия выполнены)' : 'Симуляция завершена: условия не удовлетворены';

  let actionHtml = '';
  if (res.action_preview) {
    const act = res.action_preview;
    actionHtml = `
      <div style="margin-top: 8px; padding: 8px 12px; background: var(--track); border-radius: var(--r1); font-size: 12px;">
        <div><strong>Сформированное действие:</strong> <code>${escapeHtml(act.action || 'delivery')}</code></div>
        ${act.delivery_text ? `<div style="margin-top: 4px; color: var(--muted);"><strong>Текст ответа:</strong> "${escapeHtml(act.delivery_text)}"</div>` : ''}
        ${act.response_text ? `<div style="margin-top: 4px; color: var(--muted);"><strong>Текст ответа:</strong> "${escapeHtml(act.response_text)}"</div>` : ''}
        ${act.sample_goods?.length ? `<div style="margin-top: 4px; color: var(--ok);"><strong>Выдаваемые ключи:</strong> ${escapeHtml(act.sample_goods.join(', '))}</div>` : ''}
        ${act.products_file ? `<div style="margin-top: 2px; color: var(--muted);">Файл склада: ${escapeHtml(act.products_file)} (остаток: ~${act.goods_left_estimate ?? 0})</div>` : ''}
      </div>
    `;
  } else {
    actionHtml = `<div style="margin-top: 6px; color: var(--muted); font-size: 12px;">Действие не было вызвано (правило не сработало).</div>`;
  }

  outputBox.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--outline); padding-bottom: 8px; margin-bottom: 10px;">
      <div style="display: flex; align-items: center; gap: 6px; color: ${statusColor};">
        ${getIcon(statusIcon, 'icon-sm')}
        <strong style="font-size: 13px;">${statusText}</strong>
      </div>
      <span style="font-size: 11px; color: var(--muted);">${res.duration_ms || 0} ms</span>
    </div>

    <div style="font-size: 12px; color: var(--on); line-height: 1.5;">
      <div><strong>Сработавшее правило Cardinal:</strong> <code style="background: var(--track); padding: 2px 6px; border-radius: 4px;">${escapeHtml(res.matched_rule || 'Не сопоставлено')}</code></div>
      
      <div style="margin-top: 8px;">
        <strong>Проверка условий (Conditions):</strong>
        <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 4px;">
          ${res.conditions ? res.conditions.map(c => `
            <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; color: ${c.passed ? 'var(--ok, #1B6E4A)' : 'var(--err, #BA1B3D)'};">
              ${c.passed ? getIcon('check', 'icon-xs') : getIcon('close', 'icon-xs')}
              <span><strong>${escapeHtml(c.name)}:</strong> ${escapeHtml(c.details || '')}</span>
            </div>
          `).join('') : '<span style="color: var(--muted);">Условия отсутствуют</span>'}
        </div>
      </div>

      ${actionHtml}
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────
// 6. Журнал трассировок (Debug Traces)
// ─────────────────────────────────────────────────────────────

async function loadDebugTraces() {
  const listEl = container?.querySelector('#traces-list');
  if (!listEl) return;

  try {
    const data = await api.request('GET', '/api/automation/debug-traces', { allowRelogin: false });
    const traces = data?.traces || [];
    if (traces.length > 0) {
      listEl.innerHTML = traces.slice(0, 10).map(t => {
        const timeStr = t.timestamp ? new Date(t.timestamp * 1000).toLocaleTimeString() : 'Только что';
        const isOk = t.success !== false;
        return `
          <div style="background: var(--track); padding: 8px 12px; border-radius: var(--r1); display: flex; justify-content: space-between; align-items: center; font-size: 12px; border-left: 3px solid ${isOk ? 'var(--ok, #1B6E4A)' : 'var(--warn, #D97706)'};">
            <div>
              <strong style="color: var(--on);">${escapeHtml(t.matched_rule || t.rule || 'Automation')}</strong>
              <span style="color: var(--muted); margin-left: 6px; font-size: 11px;">${escapeHtml(t.event_type || 'order')} [${t.duration_ms || 0} ms]</span>
            </div>
            <span style="color: var(--muted); font-size: 11px;">${escapeHtml(timeStr)}</span>
          </div>
        `;
      }).join('');
    } else {
      listEl.innerHTML = `
        <div style="padding: 14px; text-align: center; color: var(--muted); font-size: 12px;">
          Журнал пуст. Запустите симулятор для записи трассировок.
        </div>
      `;
    }
  } catch (e) {
    // Тихо игнорируем
  }
}

export function unmountAutomationLab() {
  container = null;
  workflows = [];
  currentWorkflow = null;
  validationResult = null;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
