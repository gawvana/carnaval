"""
carnaval/services/search.py — сервис единого глобального поиска Carnaval.

Ищет по 8 категориям:
- chats (диалоги и переписки FunPay)
- orders (заказы и продажи)
- templates (шаблоны ответов)
- plugins (плагины Cardinal)
- automations (правила автовыдачи и команды автоответа)
- blacklist (пользователи в чёрном списке и причины)
- logs (журнал Cardinal)
- settings (настройки конфигурации)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from carnaval.deps import get_cardinal
from carnaval.services import automation as auto_svc
from carnaval.services import more as more_svc

logger = logging.getLogger("Carnaval.Search")


def _search_chats(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        chats_data = []
        acc = getattr(cardinal, "account", None)
        if acc:
            if hasattr(acc, "chats") and acc.chats:
                chats_data = list(acc.chats.values()) if isinstance(acc.chats, dict) else list(acc.chats)
            elif hasattr(acc, "get_chats"):
                try:
                    c_dict = acc.get_chats(update=False)
                    chats_data = list(c_dict.values()) if isinstance(c_dict, dict) else list(c_dict)
                except Exception:
                    pass
        elif hasattr(cardinal, "chats") and cardinal.chats:
            c_attr = cardinal.chats
            chats_data = list(c_attr.values()) if isinstance(c_attr, dict) else list(c_attr)

        for c in chats_data:
            c_id = getattr(c, "id", "")
            c_name = getattr(c, "name", "") or ""
            last_text = getattr(c, "last_message_text", "") or ""
            if not last_text and hasattr(c, "text"):
                last_text = getattr(c, "text", "") or ""

            if q in str(c_id).lower() or q in c_name.lower() or q in last_text.lower():
                results.append({
                    "id": str(c_id),
                    "title": c_name or f"Чат {c_id}",
                    "description": last_text or f"ID чата: {c_id}",
                    "category": "chats",
                    "route": f"/chats/{c_id}",
                    "action": f"open_chat:{c_id}",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search chats failed: {e}")
    return results


def _search_orders(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        orders_data = []
        if hasattr(cardinal, "orders") and cardinal.orders:
            orders_data = list(cardinal.orders.values()) if isinstance(cardinal.orders, dict) else list(cardinal.orders)
        elif hasattr(cardinal, "account") and cardinal.account and hasattr(cardinal.account, "get_sales"):
            try:
                _, s_list, _, _ = cardinal.account.get_sales(update=False)
                orders_data = s_list or []
            except Exception:
                pass

        for o in orders_data:
            o_id = getattr(o, "id", "")
            desc = getattr(o, "description", "") or ""
            buyer = getattr(o, "buyer_username", "") or ""
            subcat = getattr(o, "subcategory_name", "") or ""
            price = getattr(o, "price", "")
            currency = getattr(o, "currency", "")

            if (q in str(o_id).lower() or q in desc.lower() or q in buyer.lower() or q in subcat.lower()):
                price_str = f"{price} {currency}".strip()
                desc_str = f"{desc} | {price_str}" if price_str else desc
                results.append({
                    "id": str(o_id),
                    "title": f"Заказ #{o_id} — {buyer}" if buyer else f"Заказ #{o_id}",
                    "description": desc_str,
                    "category": "orders",
                    "route": f"/orders/{o_id}",
                    "action": f"view_order:{o_id}",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search orders failed: {e}")
    return results


def _search_templates(q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        templates = auto_svc.list_templates()
        for t in templates:
            text = t.get("text", "")
            idx = t.get("index", 0)
            if q in text.lower():
                short = text[:60] + ("..." if len(text) > 60 else "")
                results.append({
                    "id": f"template_{idx}",
                    "title": f"Шаблон #{idx + 1}",
                    "description": short,
                    "category": "templates",
                    "route": f"/automation#template-{idx}",
                    "action": f"use_template:{idx}",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search templates failed: {e}")
    return results


def _search_plugins(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        plugins = getattr(cardinal, "plugins", {})
        for p_uuid, pl in plugins.items():
            name = getattr(pl, "name", "") or ""
            desc = getattr(pl, "description", "") or ""
            credits_str = getattr(pl, "credits", "") or ""
            version = getattr(pl, "version", "") or ""
            enabled = getattr(pl, "enabled", True)

            if q in name.lower() or q in desc.lower() or q in credits_str.lower() or q in str(p_uuid).lower():
                status_str = "включен" if enabled else "выключен"
                results.append({
                    "id": str(p_uuid),
                    "title": f"Плагин: {name}",
                    "description": f"{desc} (v{version}) [{status_str}]",
                    "category": "plugins",
                    "route": f"/more#plugin-{p_uuid}",
                    "action": f"view_plugin:{p_uuid}",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search plugins failed: {e}")
    return results


def _search_automations(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        # 1. Автовыдача
        ad_cfg = getattr(cardinal, "AD_CFG", None)
        if ad_cfg and hasattr(ad_cfg, "sections"):
            for idx, sec in enumerate(ad_cfg.sections()):
                resp = ad_cfg[sec].get("response", "")
                fname = ad_cfg[sec].get("productsFileName", "")
                if q in sec.lower() or q in resp.lower() or q in fname.lower():
                    results.append({
                        "id": f"ad_{idx}",
                        "title": f"Автовыдача: {sec}",
                        "description": f"Ответ: {resp[:50]}... | Файл: {fname or 'нет'}",
                        "category": "automations",
                        "route": f"/automation#delivery-{idx}",
                        "action": f"edit_delivery:{idx}",
                    })
                    if len(results) >= limit:
                        return results

        # 2. Автоответчик
        raw_ar_cfg = getattr(cardinal, "RAW_AR_CFG", None)
        if raw_ar_cfg and hasattr(raw_ar_cfg, "sections"):
            for idx, cmd in enumerate(raw_ar_cfg.sections()):
                resp = raw_ar_cfg[cmd].get("response", "")
                if q in cmd.lower() or q in resp.lower():
                    results.append({
                        "id": f"ar_{idx}",
                        "title": f"Автоответ: {cmd}",
                        "description": f"Ответ: {resp[:50]}...",
                        "category": "automations",
                        "route": f"/automation#response-{idx}",
                        "action": f"edit_response:{idx}",
                    })
                    if len(results) >= limit:
                        return results
    except Exception as e:
        logger.debug(f"Search automations failed: {e}")
    return results


def _search_blacklist(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        bl = getattr(cardinal, "blacklist", [])
        reasons = more_svc._load_blacklist_reasons()
        for u in bl:
            reason = reasons.get(u, "")
            if q in u.lower() or q in reason.lower():
                results.append({
                    "id": f"bl_{u}",
                    "title": f"@{u}",
                    "description": f"Причина: {reason}" if reason else "В чёрном списке",
                    "category": "blacklist",
                    "route": "/more#blacklist",
                    "action": f"view_blacklist:{u}",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search blacklist failed: {e}")
    return results


def _search_logs(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        logs = list(more_svc.get_logs(200))
        extra_logs = getattr(cardinal, "logs", None) or []
        combined_logs = logs + [str(l) for l in extra_logs]
        for idx, line in enumerate(reversed(combined_logs)):
            if q in line.lower():
                short = line[:80] + ("..." if len(line) > 80 else "")
                results.append({
                    "id": f"log_{idx}",
                    "title": short,
                    "description": line,
                    "category": "logs",
                    "route": "/more#logs",
                    "action": "view_logs",
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Search logs failed: {e}")
    return results


def _search_settings(cardinal: Any, q: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        main_cfg = getattr(cardinal, "MAIN_CFG", None)
        if main_cfg and hasattr(main_cfg, "sections"):
            for sec in main_cfg.sections():
                if q in sec.lower():
                    results.append({
                        "id": f"setting_{sec}",
                        "title": f"Раздел настроек: [{sec}]",
                        "description": f"Конфигурационный блок [{sec}]",
                        "category": "settings",
                        "route": f"/settings#{sec.lower()}",
                        "action": f"open_section:{sec}",
                    })
                    if len(results) >= limit:
                        return results

                for opt in main_cfg[sec]:
                    val = main_cfg[sec][opt]
                    if q in opt.lower() or q in str(val).lower():
                        results.append({
                            "id": f"setting_{sec}_{opt}",
                            "title": f"{sec} -> {opt}",
                            "description": f"Значение: {val}",
                            "category": "settings",
                            "route": f"/settings#{sec.lower()}",
                            "action": f"open_setting:{sec}:{opt}",
                        })
                        if len(results) >= limit:
                            return results
    except Exception as e:
        logger.debug(f"Search settings failed: {e}")
    return results


def global_search(query: str, limit_per_category: int = 5) -> dict[str, Any]:
    """
    Выполняет сквозной глобальный поиск по 8 доменам Carnaval:
    chats, orders, templates, plugins, automations, blacklist, logs, settings.
    """
    cardinal = get_cardinal()
    q = (query or "").strip().lower()

    if not q:
        empty_cat = {
            "chats": [],
            "orders": [],
            "templates": [],
            "plugins": [],
            "automations": [],
            "blacklist": [],
            "logs": [],
            "settings": [],
        }
        return {
            "query": query or "",
            "total": 0,
            "results": empty_cat,
            "categories": empty_cat,
            "items": [],
            **empty_cat,
        }

    chats = _search_chats(cardinal, q, limit_per_category)
    orders = _search_orders(cardinal, q, limit_per_category)
    templates = _search_templates(q, limit_per_category)
    plugins = _search_plugins(cardinal, q, limit_per_category)
    automations = _search_automations(cardinal, q, limit_per_category)
    blacklist = _search_blacklist(cardinal, q, limit_per_category)
    logs = _search_logs(cardinal, q, limit_per_category)
    settings = _search_settings(cardinal, q, limit_per_category)

    categorized = {
        "chats": chats,
        "orders": orders,
        "templates": templates,
        "plugins": plugins,
        "automations": automations,
        "blacklist": blacklist,
        "logs": logs,
        "settings": settings,
    }

    all_items: list[dict[str, Any]] = []
    for cat_list in categorized.values():
        all_items.extend(cat_list)

    return {
        "query": query,
        "total": len(all_items),
        "results": categorized,
        "categories": categorized,
        "items": all_items,
        **categorized,
    }
