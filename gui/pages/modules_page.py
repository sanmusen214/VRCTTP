"""
模块目录页面。

区块 A：已有模块实例（config["modules"]）— 展示 + 删除
区块 B：新增模块实例 — 类型选择 + 动态 config 表单
区块 C：类型参考（只读 catalog）— 折叠显示
"""
from __future__ import annotations

from copy import deepcopy

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav
from gui.components.module_form import create_module_form, read_form_values
from core.module_identity import module_display_name, module_ref_id


def register(app) -> None:  # noqa: ARG001

    @ui.page("/modules")
    def modules_page() -> None:
        ui.page_title("模块目录")
        create_nav()
        engine = state.get_engine()

        with ui.column().classes("w-full max-w-5xl mx-auto q-pa-md gap-4"):
            ui.label("模块目录").classes("text-h5")

            # ──────────────────────────────────────────────────────────────
            # 区块 A：已有模块实例
            # ──────────────────────────────────────────────────────────────
            ui.label("模块实例").classes("text-subtitle1 text-bold")
            ui.label("以下为 config.json 中 modules 节已定义的实例。").classes("text-caption text-grey")

            instances_container = ui.column().classes("w-full gap-1")

            def _pipelines_using(ref_id: str, pipelines: list) -> list[str]:
                """返回所有引用了 ref_id 的 pipeline id 列表。"""
                using = []
                for p in pipelines:
                    if not isinstance(p, dict):
                        continue
                    graph = p.get("graph", {})
                    entry = graph.get("entry", "")
                    routes = graph.get("routes", {})
                    all_refs = {entry}
                    for from_r, to_list in routes.items():
                        all_refs.add(from_r)
                        all_refs.update(to_list)
                    if ref_id in all_refs:
                        using.append(p.get("id", "?"))
                return using

            def _copy_module(ref_id: str) -> None:
                raw = engine.get_raw_config()
                modules = raw.get("modules", {})
                source = modules.get(ref_id)
                if not isinstance(source, dict):
                    ui.notify("找不到要复制的模块实例", type="warning")
                    return

                source_name = module_display_name(ref_id, source)
                existing_names = {
                    module_display_name(rid, cfg)
                    for rid, cfg in modules.items()
                    if not rid.startswith("_") and isinstance(cfg, dict)
                }
                base_name = f"{source_name}（副本）"
                new_name = base_name
                suffix = 2
                while new_name in existing_names:
                    new_name = f"{base_name} {suffix}"
                    suffix += 1

                new_ref_id = module_ref_id(new_name)
                if new_ref_id in modules:
                    ui.notify("模块 ID 哈希冲突，请调整显示名称后重试", type="negative")
                    return
                copied = deepcopy(source)
                copied["display_name"] = new_name
                modules[new_ref_id] = copied
                engine.save_config(raw)
                ui.notify(
                    f"已复制模块为 {new_name!r}（需在首页重载生效）",
                    type="positive",
                )
                draw_instances()

            def draw_instances() -> None:
                instances_container.clear()
                raw = engine.get_raw_config()
                modules_cfg: dict = raw.get("modules", {})
                pipelines_list: list = raw.get("pipelines", [])

                with instances_container:
                    real_items = [(k, v) for k, v in modules_cfg.items()
                                  if not k.startswith("_") and isinstance(v, dict)]
                    if not real_items:
                        ui.label("尚无模块实例。").classes("text-grey")
                        return

                    for ref_id, mod_def in real_items:
                        mod_type = mod_def.get("type", "?")
                        display_name = module_display_name(ref_id, mod_def)
                        params = mod_def.get("params", {})
                        display_params = {k: v for k, v in params.items()
                                          if not k.startswith("_")}

                        with ui.expansion(
                            f"{display_name}  [{mod_type}]", icon="extension"
                        ).classes("w-full"):
                            with ui.card().classes("w-full q-pa-sm"):
                                ui.label("params:").classes("text-caption text-grey")
                                for pk, pv in display_params.items():
                                    ui.label(f"  {pk}: {pv}").classes(
                                        "text-caption font-mono"
                                    )

                                ui.separator().classes("q-my-sm")

                                def _make_delete(rid: str, current_name: str):
                                    def _do_delete() -> None:
                                        using = _pipelines_using(rid, pipelines_list)
                                        with ui.dialog() as dlg, ui.card():
                                            ui.label(f"确认删除模块实例 {current_name!r}？").classes(
                                                "text-bold"
                                            )
                                            if using:
                                                ui.label(
                                                    f"⚠ 该实例正在被以下管道引用：{', '.join(using)}"
                                                ).style("color:orange")
                                            with ui.row():
                                                ui.button(
                                                    "删除", color="negative",
                                                    on_click=lambda: _confirm_delete(rid, dlg),
                                                )
                                                ui.button("取消", on_click=dlg.close)
                                        dlg.open()
                                    return _do_delete

                                def _make_edit(rid: str, current_name: str, mtype: str, cur_params: dict):
                                    def _open_edit() -> None:
                                        cls = module_classes.get(mtype)
                                        if cls is None:
                                            ui.notify(f"未知模块类型 {mtype!r}", type="warning")
                                            return
                                        config_attrs = cls.get_config_attributes()
                                        edit_elements: dict = {}
                                        with ui.dialog() as edit_dlg, ui.card().classes("w-full").style("min-width:480px"):
                                            ui.label(f"编辑模块: {current_name}  [{mtype}]").classes("text-h6")
                                            name_input = ui.input(
                                                label="* 显示名称", value=current_name,
                                            ).classes("w-full")
                                            if config_attrs:
                                                edit_elements.update(
                                                    create_module_form(config_attrs, cur_params)
                                                )
                                            else:
                                                ui.label("该模块无自定义配置参数。").classes("text-caption text-grey")
                                            def _save_edit() -> None:
                                                new_name = (name_input.value or "").strip()
                                                if not new_name:
                                                    ui.notify("显示名称不能为空", type="warning")
                                                    return
                                                r = engine.get_raw_config()
                                                duplicate = any(
                                                    other_id != rid
                                                    and isinstance(cfg, dict)
                                                    and module_display_name(other_id, cfg) == new_name
                                                    for other_id, cfg in r.get("modules", {}).items()
                                                )
                                                if duplicate:
                                                    ui.notify(f"显示名称 {new_name!r} 已存在", type="warning")
                                                    return
                                                new_params = read_form_values(edit_elements)
                                                new_params = {k: v for k, v in new_params.items() if v is not None}
                                                if rid in r.get("modules", {}):
                                                    r["modules"][rid]["display_name"] = new_name
                                                    r["modules"][rid]["params"] = new_params
                                                    engine.save_config(r)
                                                    ui.notify(f"已保存 {new_name!r}（需点击「重载所有配置」生效）", type="positive")
                                                edit_dlg.close()
                                                draw_instances()
                                            with ui.row():
                                                ui.button("保存", icon="save", color="primary", on_click=_save_edit)
                                                ui.button("取消", on_click=edit_dlg.close)
                                        edit_dlg.open()
                                    return _open_edit

                                with ui.row().classes("gap-2"):
                                    ui.button(
                                        "编辑", icon="edit", color="primary",
                                        on_click=_make_edit(ref_id, display_name, mod_type, display_params),
                                    ).props("flat")
                                    ui.button(
                                        "复制", icon="content_copy", color="primary",
                                        on_click=lambda _, rid=ref_id: _copy_module(rid),
                                    ).props("flat")
                                    ui.button(
                                        "删除此实例", icon="delete", color="negative",
                                        on_click=_make_delete(ref_id, display_name),
                                    ).props("flat")

            def _confirm_delete(ref_id: str, dlg) -> None:
                dlg.close()
                raw = engine.get_raw_config()
                raw.get("modules", {}).pop(ref_id, None)
                engine.save_config(raw)
                ui.notify("已删除模块实例（需点击「重载所有配置」生效）", type="positive")
                draw_instances()

            draw_instances()

            ui.separator()

            # ──────────────────────────────────────────────────────────────
            # 区块 B：新增模块实例
            # ──────────────────────────────────────────────────────────────
            ui.label("新增模块实例").classes("text-subtitle1 text-bold")

            module_classes = engine.get_module_classes()
            type_names = sorted(module_classes.keys())

            with ui.card().classes("w-full q-pa-md"):
                with ui.row().classes("items-start gap-4 w-full flex-wrap"):
                    name_input = ui.input(
                        label="* 显示名称（如：翻译到日文）"
                    ).style("min-width:220px")
                    type_select = ui.select(
                        type_names,
                        label="* 模块类型",
                        value=type_names[0] if type_names else None,
                        on_change=lambda e: _rebuild_form(e.value),
                    ).style("min-width:200px")

                form_container = ui.column().classes("w-full gap-1")
                form_elements: dict = {}

                def _rebuild_form(selected_type: str | None = None) -> None:
                    form_container.clear()
                    form_elements.clear()
                    t = selected_type or type_select.value
                    if not t or t not in module_classes:
                        return
                    cls = module_classes[t]
                    config_attrs = cls.get_config_attributes()
                    if not config_attrs:
                        with form_container:
                            ui.label("该模块无自定义配置参数。").classes("text-caption text-grey")
                        return
                    with form_container:
                        ui.label(f"配置参数 ({t})").classes("text-caption text-grey")
                        new_elements = create_module_form(config_attrs, {})
                    form_elements.update(new_elements)

                _rebuild_form()

                def _create_instance() -> None:
                    display_name = (name_input.value or "").strip()
                    mod_type = type_select.value
                    if not display_name:
                        ui.notify("显示名称不能为空", type="warning")
                        return
                    raw = engine.get_raw_config()
                    modules = raw.get("modules", {})
                    if any(
                        isinstance(cfg, dict)
                        and module_display_name(rid, cfg) == display_name
                        for rid, cfg in modules.items()
                    ):
                        ui.notify(f"显示名称 {display_name!r} 已存在", type="warning")
                        return
                    ref_id = module_ref_id(display_name)
                    if ref_id in modules:
                        ui.notify("模块 ID 哈希冲突，请调整显示名称后重试", type="negative")
                        return
                    params = read_form_values(form_elements)
                    # Remove None values to keep JSON clean
                    params = {k: v for k, v in params.items() if v is not None}
                    raw.setdefault("modules", {})[ref_id] = {
                        "display_name": display_name,
                        "type": mod_type,
                        "params": params,
                    }
                    engine.save_config(raw)
                    ui.notify(f"已新增模块实例 {display_name!r}（类型: {mod_type}）", type="positive")
                    name_input.value = ""
                    draw_instances()

                ui.button(
                    "确认创建", icon="add_circle", color="primary",
                    on_click=_create_instance,
                ).classes("q-mt-sm")

            ui.separator()

            # ──────────────────────────────────────────────────────────────
            # 区块 C：类型参考（只读 catalog）
            # ──────────────────────────────────────────────────────────────
            with ui.expansion("模块类型参考（只读）", icon="menu_book", value=False).classes("w-full"):
                with ui.column().classes("w-full gap-2 q-pa-sm"):
                    for type_name, cls in module_classes.items():
                        require_attrs = cls.require_attributes_in_packages()
                        add_attrs = cls.add_attributes_in_packages()
                        config_attrs = cls.get_config_attributes()

                        with ui.expansion(
                            f"{type_name}  ({cls.__name__})", icon="extension"
                        ).classes("w-full q-mb-xs"):
                            with ui.column().classes("w-full q-pa-sm gap-3"):
                                if require_attrs:
                                    ui.label("需要的包字段 (require)").classes("text-subtitle2")
                                    ui.table(
                                        columns=[
                                            {"name": "name", "label": "字段名", "field": "name", "align": "left"},
                                            {"name": "must", "label": "必须",   "field": "must", "align": "center"},
                                            {"name": "desc", "label": "说明",   "field": "desc", "align": "left"},
                                        ],
                                        rows=[
                                            {"name": r["name"], "must": "✓" if r["must_have"] else "?", "desc": r["description"]}
                                            for r in require_attrs
                                        ],
                                    ).classes("w-full dense flat")

                                if add_attrs:
                                    ui.label("写入的包字段 (add)").classes("text-subtitle2 q-mt-sm")
                                    ui.table(
                                        columns=[
                                            {"name": "name", "label": "字段名", "field": "name", "align": "left"},
                                            {"name": "must", "label": "必写",   "field": "must", "align": "center"},
                                            {"name": "desc", "label": "说明",   "field": "desc", "align": "left"},
                                        ],
                                        rows=[
                                            {"name": r["name"], "must": "✓" if r["must_have"] else "?", "desc": r["description"]}
                                            for r in add_attrs
                                        ],
                                    ).classes("w-full dense flat")

                                if config_attrs:
                                    ui.label("配置参数 (params)").classes("text-subtitle2 q-mt-sm")
                                    ui.table(
                                        columns=[
                                            {"name": "name",     "label": "参数名", "field": "name",     "align": "left"},
                                            {"name": "type",     "label": "类型",   "field": "type",     "align": "left"},
                                            {"name": "default",  "label": "默认值", "field": "default",  "align": "left"},
                                            {"name": "required", "label": "必填",   "field": "required", "align": "center"},
                                            {"name": "desc",     "label": "说明",   "field": "desc",     "align": "left"},
                                        ],
                                        rows=[
                                            {
                                                "name":     a["name"],
                                                "type":     a["type"].value,
                                                "default":  str(a.get("default", "")),
                                                "required": "✓" if a.get("required") else "",
                                                "desc":     a.get("description", ""),
                                            }
                                            for a in config_attrs
                                        ],
                                    ).classes("w-full dense flat")

