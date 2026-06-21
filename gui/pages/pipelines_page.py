"""
管道管理页面。

展示所有管道（enabled 切换 + 删除），并支持新建管道（DAG 格式）。
新建界面：名称/ID 输入 + 入口模块选择 + 可增减的 routes 邻接表编辑器。
"""
from __future__ import annotations

from copy import deepcopy

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav
from core.engine import PRODUCER_REGISTRY


def register(app) -> None:  # noqa: ARG001

    @ui.page("/pipelines")
    def pipelines_page() -> None:
        ui.page_title("管道管理")
        create_nav()
        engine = state.get_engine()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):
            ui.label("管道管理").classes("text-h5")

            pipelines_container = ui.column().classes("w-full gap-2")

            def _all_ref_ids(raw: dict) -> list[str]:
                return [k for k in raw.get("modules", {}).keys()
                        if not k.startswith("_")]

            def _producer_ref_ids(raw: dict) -> list[str]:
                modules = raw.get("modules", {})
                return [
                    k for k, v in modules.items()
                    if not k.startswith("_")
                    and isinstance(v, dict)
                    and v.get("type") in PRODUCER_REGISTRY
                ]

            def _copy_pipeline(pipeline_id: str) -> None:
                raw = engine.get_raw_config()
                pipelines = raw.get("pipelines", [])
                source = next(
                    (p for p in pipelines
                     if isinstance(p, dict) and p.get("id") == pipeline_id),
                    None,
                )
                if source is None:
                    ui.notify(f"找不到管道 {pipeline_id!r}", type="warning")
                    return

                existing_ids = {
                    p.get("id") for p in pipelines if isinstance(p, dict)
                }
                base_id = f"{pipeline_id}_copy"
                new_id = base_id
                suffix = 2
                while new_id in existing_ids:
                    new_id = f"{base_id}_{suffix}"
                    suffix += 1

                copied = deepcopy(source)
                copied["id"] = new_id
                source_name = source.get("name") or pipeline_id
                existing_names = {
                    p.get("name") for p in pipelines if isinstance(p, dict)
                }
                base_name = f"{source_name}（副本）"
                new_name = base_name
                suffix = 2
                while new_name in existing_names:
                    new_name = f"{base_name} {suffix}"
                    suffix += 1
                copied["name"] = new_name
                pipelines.append(copied)
                engine.save_config(raw)
                ui.notify(
                    f"已复制为 [{new_id}] {new_name}（需在首页重载生效）",
                    type="positive",
                )
                draw_pipelines()

            def draw_pipelines() -> None:
                pipelines_container.clear()
                raw = engine.get_raw_config()
                pipelines = [
                    p for p in raw.get("pipelines", [])
                    if isinstance(p, dict) and "id" in p
                ]

                with pipelines_container:
                    if not pipelines:
                        ui.label("配置中没有任何管道。").classes("text-grey")
                        return

                    for pipeline in pipelines:
                        pid = pipeline.get("id", "")
                        name = pipeline.get("name", pid)
                        enabled = pipeline.get("enabled", False)
                        graph = pipeline.get("graph", {})
                        entry = graph.get("entry", "—")
                        routes = {
                            k: v for k, v in graph.get("routes", {}).items()
                            if not k.startswith("_")
                        }

                        with ui.expansion(
                            f"[{pid}] {name}", icon="account_tree", value=False
                        ).classes("w-full"):
                            with ui.card().classes("w-full q-pa-sm"):
                                with ui.row().classes("items-center justify-between w-full"):
                                    with ui.column().classes("gap-0"):
                                        ui.label(f"ID: {pid}").classes("text-caption")
                                        ui.label(f"入口: {entry}").classes("text-caption")

                                    with ui.row().classes("items-center gap-2"):
                                        def _make_toggle(pipeline_id: str):
                                            def _toggle(e) -> None:
                                                r = engine.get_raw_config()
                                                for p in r.get("pipelines", []):
                                                    if isinstance(p, dict) and p.get("id") == pipeline_id:
                                                        p["enabled"] = e.value
                                                engine.save_config(r)
                                                ui.notify(
                                                    f"{'启用' if e.value else '禁用'} {pipeline_id}，已保存（需在首页重载生效）",
                                                    type="positive",
                                                )
                                                draw_pipelines()
                                            return _toggle

                                        ui.switch("启用", value=enabled, on_change=_make_toggle(pid))

                                        def _make_delete_btn(pipeline_id: str):
                                            def _open_delete() -> None:
                                                with ui.dialog() as dlg, ui.card():
                                                    ui.label(f"确认删除管道 {pipeline_id!r}？").classes("text-bold")
                                                    ui.label("操作不可撤销，管道将从配置文件中移除。").classes("text-caption text-grey")
                                                    with ui.row():
                                                        ui.button(
                                                            "删除", color="negative",
                                                            on_click=lambda: _confirm_delete_pipeline(pipeline_id, dlg),
                                                        )
                                                        ui.button("取消", on_click=dlg.close)
                                                dlg.open()
                                            return _open_delete

                                        def _make_edit_btn(pipeline_id: str, pcfg: dict):
                                            def _open_edit() -> None:
                                                _open_edit_dialog(pipeline_id, pcfg)
                                            return _open_edit

                                        ui.button(
                                            icon="edit", color="primary",
                                            on_click=_make_edit_btn(pid, pipeline),
                                        ).props("flat round dense")

                                        ui.button(
                                            icon="content_copy", color="primary",
                                            on_click=lambda _, pipeline_id=pid: _copy_pipeline(pipeline_id),
                                        ).props("flat round dense").tooltip("复制管道")

                                        ui.button(
                                            icon="delete", color="negative",
                                            on_click=_make_delete_btn(pid),
                                        ).props("flat round dense")

                                if routes:
                                    ui.separator().classes("q-my-sm")
                                    ui.label("路由图 (routes)").classes("text-caption text-bold")
                                    with ui.column().classes("gap-0"):
                                        for src, dsts in routes.items():
                                            dst_str = ", ".join(dsts) if dsts else "(终点)"
                                            ui.label(f"  {src}  →  {dst_str}").classes(
                                                "text-caption font-mono"
                                            )

            def _confirm_delete_pipeline(pipeline_id: str, dlg) -> None:
                dlg.close()
                raw = engine.get_raw_config()
                raw["pipelines"] = [
                    p for p in raw.get("pipelines", [])
                    if not (isinstance(p, dict) and p.get("id") == pipeline_id)
                ]
                engine.save_config(raw)
                ui.notify(f"已删除管道 {pipeline_id!r}，配置已保存（需在首页重载生效）", type="positive")
                draw_pipelines()

            # ──────────────────────────────────────────────────────────────
            # 编辑现有管道 dialog
            # ──────────────────────────────────────────────────────────────
            def _open_edit_dialog(pipeline_id: str, pipeline_cfg: dict) -> None:
                raw = engine.get_raw_config()
                all_refs = _all_ref_ids(raw)
                producer_refs = _producer_ref_ids(raw)

                graph = pipeline_cfg.get("graph", {})
                existing_entry = graph.get("entry", "")
                existing_routes: dict = {
                    k: v for k, v in graph.get("routes", {}).items()
                    if not k.startswith("_")
                }
                edit_routes_rows: list[dict] = [
                    {"from_ref": fr, "to_refs": list(to)}
                    for fr, to in existing_routes.items()
                ]

                with ui.dialog() as edit_dlg, ui.card().classes("w-full").style("min-width:600px; max-width:800px"):
                    ui.label(f"编辑管道: {pipeline_id}").classes("text-h6")
                    ui.label(f"ID: {pipeline_id}（不可修改）").classes("text-caption text-grey")

                    name_input = ui.input(
                        label="显示名称",
                        value=pipeline_cfg.get("name", pipeline_id),
                    ).classes("w-full")

                    enabled_switch = ui.switch("启用", value=pipeline_cfg.get("enabled", False))

                    if producer_refs:
                        entry_val = existing_entry if existing_entry in producer_refs else (producer_refs[0] if producer_refs else None)
                        entry_select = ui.select(
                            producer_refs, label="* 入口模块（PacketProducerModule 类型）",
                            value=entry_val,
                        ).classes("w-full q-mt-sm")
                    else:
                        ui.label("⚠ 尚无可用的入口模块（音频源），请先在「模块目录」页新增。").style("color:orange")
                        entry_select = None

                    ui.separator().classes("q-my-sm")
                    ui.label("路由邻接表 (routes)").classes("text-subtitle2")
                    ui.label("每行描述一条 from → to 路由。to 可多选。").classes("text-caption text-grey")

                    edit_routes_container = ui.column().classes("w-full gap-1")

                    @ui.refreshable
                    def edit_routes_editor() -> None:
                        edit_routes_container.clear()
                        with edit_routes_container:
                            if not edit_routes_rows:
                                ui.label("暂无路由行，点击「添加路由行」。").classes("text-caption text-grey")
                                return
                            for i, row in enumerate(edit_routes_rows):
                                with ui.row().classes("items-center gap-2 w-full"):
                                    def _make_from_change(idx: int):
                                        def _ch(e) -> None:
                                            edit_routes_rows[idx]["from_ref"] = e.value
                                        return _ch

                                    ui.select(
                                        all_refs,
                                        label="from",
                                        value=row["from_ref"] if row["from_ref"] in all_refs else (all_refs[0] if all_refs else None),
                                        on_change=_make_from_change(i),
                                    ).style("min-width:160px")

                                    ui.label("→").classes("text-bold")

                                    def _make_to_change(idx: int):
                                        def _ch(e) -> None:
                                            edit_routes_rows[idx]["to_refs"] = list(e.value) if e.value else []
                                        return _ch

                                    ui.select(
                                        all_refs,
                                        label="to（可多选）",
                                        value=[r for r in row["to_refs"] if r in all_refs],
                                        multiple=True,
                                        on_change=_make_to_change(i),
                                    ).classes("flex-grow").style("min-width:200px")

                                    def _make_del_row(idx: int):
                                        def _del() -> None:
                                            edit_routes_rows.pop(idx)
                                            edit_routes_editor.refresh()
                                        return _del

                                    ui.button(
                                        icon="remove_circle", color="negative",
                                        on_click=_make_del_row(i),
                                    ).props("flat round dense")

                    edit_routes_editor()

                    def _add_edit_route_row() -> None:
                        default_from = all_refs[0] if all_refs else ""
                        edit_routes_rows.append({"from_ref": default_from, "to_refs": []})
                        edit_routes_editor.refresh()

                    ui.button("＋ 添加路由行", icon="add", on_click=_add_edit_route_row).props("flat")

                    ui.separator().classes("q-my-sm")

                    def _confirm_edit() -> None:
                        if entry_select is None or not entry_select.value:
                            ui.notify("请选择入口模块", type="warning")
                            return
                        built_routes: dict[str, list[str]] = {}
                        for row in edit_routes_rows:
                            fr = row["from_ref"]
                            to = row["to_refs"]
                            if fr:
                                built_routes.setdefault(fr, [])
                                built_routes[fr].extend(
                                    [t for t in to if t not in built_routes[fr]]
                                )
                        r = engine.get_raw_config()
                        for p in r.get("pipelines", []):
                            if isinstance(p, dict) and p.get("id") == pipeline_id:
                                p["name"] = name_input.value.strip() or pipeline_id
                                p["enabled"] = enabled_switch.value
                                p["graph"] = {
                                    "entry": entry_select.value,
                                    "routes": built_routes,
                                }
                                break
                        engine.save_config(r)
                        edit_dlg.close()
                        ui.notify(f"已更新管道 {pipeline_id!r}，配置已保存（需在首页重载生效）", type="positive")
                        draw_pipelines()

                    with ui.row():
                        ui.button("保存更改", icon="save", color="primary", on_click=_confirm_edit)
                        ui.button("取消", on_click=edit_dlg.close)

                edit_dlg.open()

            draw_pipelines()

            ui.separator()

            # ──────────────────────────────────────────────────────────────
            # 新建管道按钮 → 打开 dialog
            # ──────────────────────────────────────────────────────────────
            def _open_create_dialog() -> None:
                raw = engine.get_raw_config()
                all_refs = _all_ref_ids(raw)
                producer_refs = _producer_ref_ids(raw)

                # routes 邻接表数据，每项：{"from_ref": str, "to_refs": list[str]}
                routes_rows: list[dict] = []

                with ui.dialog() as dlg, ui.card().classes("w-full").style("min-width:600px; max-width:800px"):
                    ui.label("新建管道").classes("text-h6")

                    with ui.grid(columns=2).classes("w-full gap-2"):
                        id_input = ui.input(label="* 管道 ID（唯一，不含空格）").classes("w-full")
                        name_input = ui.input(label="显示名称").classes("w-full")

                    enabled_switch = ui.switch("默认启用", value=False)

                    if producer_refs:
                        entry_select = ui.select(
                            producer_refs, label="* 入口模块（PacketProducerModule 类型）",
                            value=producer_refs[0],
                        ).classes("w-full q-mt-sm")
                    else:
                        ui.label("⚠ 尚无可用的入口模块（音频源），请先在「模块目录」页新增。").style("color:orange")
                        entry_select = None

                    ui.separator().classes("q-my-sm")
                    ui.label("路由邻接表 (routes)").classes("text-subtitle2")
                    ui.label(
                        "每行描述一条 from → to 路由。to 可多选。"
                    ).classes("text-caption text-grey")

                    routes_container = ui.column().classes("w-full gap-1")

                    @ui.refreshable
                    def routes_editor() -> None:
                        routes_container.clear()
                        with routes_container:
                            if not routes_rows:
                                ui.label("暂无路由行，点击「添加路由行」。").classes("text-caption text-grey")
                                return
                            for i, row in enumerate(routes_rows):
                                with ui.row().classes("items-center gap-2 w-full"):
                                    def _make_from_change(idx: int):
                                        def _ch(e) -> None:
                                            routes_rows[idx]["from_ref"] = e.value
                                        return _ch

                                    ui.select(
                                        all_refs,
                                        label="from",
                                        value=row["from_ref"] if row["from_ref"] in all_refs else (all_refs[0] if all_refs else None),
                                        on_change=_make_from_change(i),
                                    ).style("min-width:160px")

                                    ui.label("→").classes("text-bold")

                                    def _make_to_change(idx: int):
                                        def _ch(e) -> None:
                                            routes_rows[idx]["to_refs"] = list(e.value) if e.value else []
                                        return _ch

                                    ui.select(
                                        all_refs,
                                        label="to（可多选）",
                                        value=[r for r in row["to_refs"] if r in all_refs],
                                        multiple=True,
                                        on_change=_make_to_change(i),
                                    ).classes("flex-grow").style("min-width:200px")

                                    def _make_del_row(idx: int):
                                        def _del() -> None:
                                            routes_rows.pop(idx)
                                            routes_editor.refresh()
                                        return _del

                                    ui.button(
                                        icon="remove_circle", color="negative",
                                        on_click=_make_del_row(i),
                                    ).props("flat round dense")

                    routes_editor()

                    def _add_route_row() -> None:
                        default_from = all_refs[0] if all_refs else ""
                        routes_rows.append({"from_ref": default_from, "to_refs": []})
                        routes_editor.refresh()

                    ui.button("＋ 添加路由行", icon="add", on_click=_add_route_row).props("flat")

                    ui.separator().classes("q-my-sm")

                    def _confirm_create() -> None:
                        pid = id_input.value.strip()
                        if not pid:
                            ui.notify("管道 ID 不能为空", type="warning")
                            return
                        if " " in pid:
                            ui.notify("管道 ID 不能含空格", type="warning")
                            return
                        r = engine.get_raw_config()
                        existing_ids = [
                            p.get("id") for p in r.get("pipelines", [])
                            if isinstance(p, dict)
                        ]
                        if pid in existing_ids:
                            ui.notify(f"管道 ID {pid!r} 已存在", type="warning")
                            return
                        if entry_select is None or not entry_select.value:
                            ui.notify("请选择入口模块", type="warning")
                            return

                        built_routes: dict[str, list[str]] = {}
                        for row in routes_rows:
                            fr = row["from_ref"]
                            to = row["to_refs"]
                            if fr:
                                built_routes.setdefault(fr, [])
                                built_routes[fr].extend(
                                    [t for t in to if t not in built_routes[fr]]
                                )

                        new_pipeline = {
                            "id": pid,
                            "name": name_input.value.strip() or pid,
                            "enabled": enabled_switch.value,
                            "graph": {
                                "entry": entry_select.value,
                                "routes": built_routes,
                            },
                        }
                        r.setdefault("pipelines", []).append(new_pipeline)
                        engine.save_config(r)
                        dlg.close()
                        ui.notify(f"已创建管道 {pid!r}，配置已保存（需在首页重载生效）", type="positive")
                        draw_pipelines()

                    with ui.row():
                        ui.button("确认创建", icon="check", color="primary", on_click=_confirm_create)
                        ui.button("取消", on_click=dlg.close)

                dlg.open()

            ui.button(
                "＋ 新建管道", icon="add", color="primary",
                on_click=_open_create_dialog,
            )

