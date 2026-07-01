"""
管道管理页面。

展示所有管道（enabled 切换 + 删除），并支持新建管道（DAG 格式）。
新建界面：名称/ID 输入 + 入口模块选择 + 可增减的 routes 邻接表编辑器。
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
import uuid

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav
from gui.module_catalog import (
    MODULE_CATEGORY_ORDER,
    module_category_for_type,
)
from core.engine import PRODUCER_REGISTRY
from core.module_identity import module_display_name


def _build_route_graph_editor_html(
    *,
    editor_id: str,
    modules_cfg: dict,
    all_refs: list[str],
    producer_refs: list[str],
    entry_ref: str,
    routes: dict[str, list[str]],
) -> str:
    """Render the browser-side drag/drop route graph editor."""
    def _node_width_for_ref(ref_id: str) -> int:
        label = module_display_name(ref_id, modules_cfg.get(ref_id, {}))
        # Approximate browser select text width so long display names are visible.
        return min(420, max(172, len(label) * 13 + 56))

    module_options = {
        ref_id: {
            "label": module_display_name(ref_id, modules_cfg.get(ref_id, {})),
            "type": modules_cfg.get(ref_id, {}).get("type", "?"),
            "category": module_category_for_type(str(modules_cfg.get(ref_id, {}).get("type", ""))),
            "width": _node_width_for_ref(ref_id),
            "producer": ref_id in producer_refs,
        }
        for ref_id in all_refs
    }
    graph_refs: list[str] = []
    if entry_ref:
        graph_refs.append(entry_ref)
    for src, dsts in routes.items():
        if src in all_refs and src not in graph_refs:
            graph_refs.append(src)
        for dst in dsts:
            if dst in all_refs and dst not in graph_refs:
                graph_refs.append(dst)
    if not graph_refs and entry_ref:
        graph_refs.append(entry_ref)

    adjacency = {ref: [dst for dst in routes.get(ref, []) if dst in graph_refs] for ref in graph_refs}

    levels: dict[str, int] = {}
    queue = [entry_ref] if entry_ref in graph_refs else graph_refs[:1]
    if queue:
        levels[queue[0]] = 0
    while queue:
        current = queue.pop(0)
        for nxt in adjacency.get(current, []):
            next_level = levels.get(current, 0) + 1
            if next_level > levels.get(nxt, -1):
                levels[nxt] = next_level
                queue.append(nxt)
    for ref in graph_refs:
        levels.setdefault(ref, 0 if ref == entry_ref else 1)

    rows: dict[int, list[str]] = {}
    for ref in graph_refs:
        rows.setdefault(levels[ref], []).append(ref)
    nodes = []
    for level, refs in rows.items():
        x = 40
        for index, ref in enumerate(refs):
            nodes.append({
                "id": ref,
                "x": x,
                "y": 28 + level * 120,
                "width": _node_width_for_ref(ref),
                "entry": ref == entry_ref,
            })
            x += _node_width_for_ref(ref) + 48

    edges = [
        {"from": src, "to": dst}
        for src, dsts in routes.items()
        for dst in dsts
        if src in graph_refs and dst in graph_refs and src != dst
    ]
    data = {
        "entry": entry_ref,
        "nodes": nodes,
        "edges": edges,
        "modules": module_options,
        "categoryOrder": [
            {"key": category, "label": label}
            for category, label in MODULE_CATEGORY_ORDER
        ],
        "allRefs": all_refs,
        "producerRefs": producer_refs,
    }

    # The editor keeps config persistence deliberately simple: Python reads
    # window.__routeEditors[id].getGraph() and writes graph.entry/routes as before.
    return f"""
<div id="{editor_id}" class="route-editor">
  <div class="route-canvas-wrap">
    <svg class="route-lines"></svg>
    <div class="route-canvas"></div>
  </div>
  <div class="route-toolbar">
    <select class="route-add-select" aria-label="选择要添加的模块"></select>
    <button type="button" class="route-add-btn">添加</button>
  </div>
</div>
<style>
  #{editor_id}.route-editor {{
    width: 100%;
    border: 1px solid #d6d9de;
    border-radius: 8px;
    overflow: hidden;
    background: #f7f8fa;
  }}
  #{editor_id} .route-canvas-wrap {{
    position: relative;
    height: 460px;
    overflow: auto;
    background:
      linear-gradient(#edf0f3 1px, transparent 1px),
      linear-gradient(90deg, #edf0f3 1px, transparent 1px);
    background-size: 24px 24px;
  }}
  #{editor_id} .route-canvas {{
    position: relative;
    min-width: 1100px;
    min-height: 720px;
  }}
  #{editor_id} .route-lines {{
    position: absolute;
    inset: 0;
    min-width: 1100px;
    min-height: 720px;
    width: 1100px;
    height: 720px;
    pointer-events: auto;
    z-index: 3;
  }}
  #{editor_id} .route-node {{
    position: absolute;
    width: max-content;
    min-width: 172px;
    max-width: 420px;
    min-height: 74px;
    border: 1px solid #b9c0c9;
    border-radius: 8px;
    background: white;
    box-shadow: 0 2px 8px rgba(21, 30, 45, 0.11);
    z-index: 4;
    padding: 9px 26px 15px 12px;
    cursor: move;
    user-select: none;
  }}
  #{editor_id} .route-node.entry {{
    border-color: #1976d2;
    box-shadow: 0 2px 10px rgba(25, 118, 210, 0.20);
  }}
  #{editor_id} .route-node-title {{
    font-size: 12px;
    color: #5f6773;
    margin-bottom: 6px;
  }}
  #{editor_id} .route-node-select,
  #{editor_id} .route-add-select {{
    width: 100%;
    min-height: 30px;
    border: 1px solid #c5cbd3;
    border-radius: 6px;
    background: white;
    font-size: 13px;
  }}
  #{editor_id} .route-delete {{
    position: absolute;
    right: -11px;
    top: calc(50% - 11px);
    width: 22px;
    height: 22px;
    border: 0;
    border-radius: 50%;
    background: #d93025;
    color: white;
    cursor: pointer;
    line-height: 20px;
    font-weight: 700;
  }}
  #{editor_id} .route-port {{
    position: absolute;
    left: calc(50% - 6px);
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid white;
    background: #1976d2;
    box-shadow: 0 0 0 1px #1976d2;
  }}
  #{editor_id} .route-port.in {{ top: -7px; }}
  #{editor_id} .route-port.out {{ bottom: -7px; cursor: grab; }}
  #{editor_id} .route-port.out:active {{ cursor: grabbing; }}
  #{editor_id} .route-port.in.ready {{
    background: #2e7d32;
    box-shadow: 0 0 0 2px rgba(46, 125, 50, 0.25);
  }}
  #{editor_id} .route-toolbar {{
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px;
    border-top: 1px solid #d6d9de;
    background: white;
  }}
  #{editor_id} .route-add-select {{ max-width: 360px; }}
  #{editor_id} .route-add-btn {{
    min-height: 32px;
    padding: 0 14px;
    border: 0;
    border-radius: 6px;
    color: white;
    background: #1976d2;
    cursor: pointer;
  }}
  #{editor_id} .route-edge-hit {{
    pointer-events: stroke;
    cursor: pointer;
  }}
  #{editor_id} .route-edge-delete {{
    pointer-events: auto;
    cursor: pointer;
  }}
</style>
<script>
(function() {{
  const root = document.getElementById({json.dumps(editor_id)});
  const initial = {json.dumps(data, ensure_ascii=False)};
  const canvas = root.querySelector('.route-canvas');
  const svg = root.querySelector('.route-lines');
  const addSelect = root.querySelector('.route-add-select');
  const state = {{
    entry: initial.entry,
    modules: initial.modules,
    categoryOrder: initial.categoryOrder,
    allRefs: initial.allRefs,
    producerRefs: initial.producerRefs,
    nodes: initial.nodes.map(n => ({{...n}})),
    edges: initial.edges.map(e => ({{...e}})),
    drag: null,
    link: null,
    selectedEdge: null,
  }};

  function labelFor(ref) {{
    const m = state.modules[ref] || {{}};
    return m.label || ref;
  }}
  function widthFor(ref) {{
    const m = state.modules[ref] || {{}};
    const label = labelFor(ref);
    return Math.min(420, Math.max(172, Number(m.width) || (label.length * 13 + 56)));
  }}
  function categoryFor(ref) {{
    const m = state.modules[ref] || {{}};
    return m.category || 'other';
  }}
  function escapeHtml(text) {{
    return String(text).replace(/[&<>"']/g, ch => ({{
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }}[ch]));
  }}
  function optionsHtml(refs, selected) {{
    const groups = new Map();
    refs.forEach(ref => {{
      const category = categoryFor(ref);
      if (!groups.has(category)) groups.set(category, []);
      groups.get(category).push(ref);
    }});
    return state.categoryOrder
      .filter(group => groups.has(group.key))
      .map(group => {{
        const options = groups.get(group.key)
          .map(ref => `<option value="${{escapeHtml(ref)}}" ${{ref === selected ? 'selected' : ''}}>${{escapeHtml(labelFor(ref))}}</option>`)
          .join('');
        return `<optgroup label="${{escapeHtml(group.label)}}">${{options}}</optgroup>`;
      }})
      .join('');
  }}
  function nodeById(id) {{ return state.nodes.find(n => n.id === id); }}
  function uniqueEdges() {{
    const seen = new Set();
    state.edges = state.edges.filter(e => {{
      if (!nodeById(e.from) || !nodeById(e.to) || e.from === e.to) return false;
      const key = edgeKey(e);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }});
  }}
  function updateAddOptions() {{
    const used = new Set(state.nodes.map(n => n.id));
    const refs = state.allRefs.filter(ref => !used.has(ref));
    addSelect.innerHTML = refs.length
      ? optionsHtml(refs, refs[0])
      : '<option value="">没有可添加的模块</option>';
    addSelect.disabled = !refs.length;
    root.querySelector('.route-add-btn').disabled = !refs.length;
  }}
  function pointFor(ref, port) {{
    const node = nodeById(ref);
    const width = Number(node.width) || widthFor(ref);
    return {{
      x: node.x + width / 2,
      y: node.y + (port === 'in' ? 0 : 74),
    }};
  }}
  function canvasPoint(ev) {{
    const wrap = canvas.parentElement;
    const rect = wrap.getBoundingClientRect();
    return {{
      x: ev.clientX - rect.left + wrap.scrollLeft,
      y: ev.clientY - rect.top + wrap.scrollTop,
    }};
  }}
  function edgeKey(edge) {{
    return `${{encodeURIComponent(edge.from)}}→${{encodeURIComponent(edge.to)}}`;
  }}
  function curveFor(edge) {{
    const a = pointFor(edge.from, 'out');
    const b = pointFor(edge.to, 'in');
    const mid = Math.max(36, (b.y - a.y) / 2);
    const c1 = {{x: a.x, y: a.y + mid}};
    const c2 = {{x: b.x, y: b.y - mid}};
    const center = {{
      x: (a.x + 3 * c1.x + 3 * c2.x + b.x) / 8,
      y: (a.y + 3 * c1.y + 3 * c2.y + b.y) / 8,
    }};
    return {{
      key: edgeKey(edge),
      start: a,
      end: b,
      center,
      d: `M ${{a.x}} ${{a.y}} C ${{c1.x}} ${{c1.y}}, ${{c2.x}} ${{c2.y}}, ${{b.x}} ${{b.y}}`,
    }};
  }}
  function drawLines(tempLine) {{
    uniqueEdges();
    const paths = state.edges.map(e => {{
      const curve = curveFor(e);
      const selected = curve.key === state.selectedEdge;
      const halo = selected
        ? `<path d="${{curve.d}}" stroke="rgba(217, 48, 37, 0.24)" stroke-width="10" fill="none" />`
        : '';
      const visible = `<path d="${{curve.d}}" stroke="${{selected ? '#d93025' : '#1976d2'}}" stroke-width="${{selected ? 4 : 2.2}}" fill="none" marker-end="url(#arrow)" />`;
      const hit = `<path class="route-edge-hit" data-edge="${{escapeHtml(curve.key)}}" d="${{curve.d}}" stroke="#000" stroke-opacity="0.001" stroke-width="16" fill="none" />`;
      const del = selected
        ? `<g class="route-edge-delete" data-edge="${{escapeHtml(curve.key)}}" transform="translate(${{curve.center.x}} ${{curve.center.y}})">
             <circle r="12" fill="#d93025"></circle>
             <text x="0" y="4" text-anchor="middle" font-size="16" font-weight="700" fill="white">×</text>
           </g>`
        : '';
      return `${{halo}}${{visible}}${{hit}}${{del}}`;
    }});
    if (tempLine) {{
      paths.push(`<path d="M ${{tempLine.x1}} ${{tempLine.y1}} L ${{tempLine.x2}} ${{tempLine.y2}}" stroke="#7b8da3" stroke-width="2" fill="none" stroke-dasharray="5 5" />`);
    }}
    svg.innerHTML = `<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M 0 0 L 10 4 L 0 8 z" fill="#1976d2"></path></marker></defs>${{paths.join('')}}`;
    svg.querySelectorAll('.route-edge-hit').forEach(path => {{
      path.addEventListener('click', ev => {{
        ev.stopPropagation();
        state.selectedEdge = path.dataset.edge;
        drawLines();
      }});
    }});
    svg.querySelectorAll('.route-edge-delete').forEach(button => {{
      button.addEventListener('click', ev => {{
        ev.stopPropagation();
        const key = button.dataset.edge;
        state.edges = state.edges.filter(edge => edgeKey(edge) !== key);
        state.selectedEdge = null;
        render();
      }});
    }});
  }}
  function render() {{
    canvas.innerHTML = '';
    state.nodes.forEach(node => {{
      const el = document.createElement('div');
      el.className = `route-node ${{node.entry ? 'entry' : ''}}`;
      el.dataset.ref = node.id;
      node.width = widthFor(node.id);
      el.style.left = `${{node.x}}px`;
      el.style.top = `${{node.y}}px`;
      el.style.width = `${{node.width}}px`;
      el.innerHTML = `
        <div class="route-port in" data-port="in"></div>
        <div class="route-node-title">${{node.entry ? '入口模块' : '模块'}}</div>
        <select class="route-node-select">${{optionsHtml(node.entry ? state.producerRefs : state.allRefs, node.id)}}</select>
        ${{node.entry ? '' : '<button type="button" class="route-delete" title="删除">×</button>'}}
        <div class="route-port out" data-port="out"></div>
      `;
      const select = el.querySelector('.route-node-select');
      select.addEventListener('mousedown', ev => ev.stopPropagation());
      select.addEventListener('change', () => replaceNode(node.id, select.value));
      const del = el.querySelector('.route-delete');
      if (del) {{
        del.addEventListener('click', ev => {{
          ev.stopPropagation();
          state.nodes = state.nodes.filter(n => n.id !== node.id);
          state.edges = state.edges.filter(e => e.from !== node.id && e.to !== node.id);
          state.selectedEdge = null;
          render();
        }});
      }}
      el.addEventListener('mousedown', ev => {{
        if (ev.target.closest('select,button,.route-port')) return;
        const point = canvasPoint(ev);
        state.drag = {{
          id: node.id,
          dx: point.x - node.x,
          dy: point.y - node.y,
        }};
      }});
      el.querySelector('.route-port.out').addEventListener('mousedown', ev => {{
        ev.stopPropagation();
        const p = pointFor(node.id, 'out');
        state.selectedEdge = null;
        state.link = {{ from: node.id, x1: p.x, y1: p.y, x2: p.x, y2: p.y }};
      }});
      canvas.appendChild(el);
    }});
    updateAddOptions();
    drawLines();
  }}
  function replaceNode(oldRef, newRef) {{
    if (!newRef || oldRef === newRef) return;
    const oldNode = nodeById(oldRef);
    const existing = nodeById(newRef);
    if (existing) {{
      state.edges.forEach(e => {{
        if (e.from === oldRef) e.from = newRef;
        if (e.to === oldRef) e.to = newRef;
      }});
      if (oldNode.entry) {{
        existing.entry = true;
        state.entry = newRef;
      }}
      state.nodes = state.nodes.filter(n => n.id !== oldRef);
    }} else {{
      oldNode.id = newRef;
      oldNode.width = widthFor(newRef);
      if (oldNode.entry) state.entry = newRef;
      state.edges.forEach(e => {{
        if (e.from === oldRef) e.from = newRef;
        if (e.to === oldRef) e.to = newRef;
      }});
    }}
    render();
  }}
  root.querySelector('.route-add-btn').addEventListener('click', () => {{
    const ref = addSelect.value;
    if (!ref || nodeById(ref)) return;
    const wrap = canvas.parentElement;
    state.nodes.push({{
      id: ref,
      x: wrap.scrollLeft + 50 + (state.nodes.length % 4) * 42,
      y: wrap.scrollTop + 320 + (state.nodes.length % 3) * 24,
      width: widthFor(ref),
      entry: false,
    }});
    render();
  }});
  canvas.parentElement.addEventListener('click', ev => {{
    if (ev.target !== canvas && ev.target !== svg && ev.target !== canvas.parentElement) return;
    if (!state.selectedEdge) return;
    state.selectedEdge = null;
    drawLines();
  }});
  document.addEventListener('mousemove', ev => {{
    const point = canvasPoint(ev);
    const x = point.x;
    const y = point.y;
    if (state.drag) {{
      const node = nodeById(state.drag.id);
      if (node) {{
        node.x = Math.max(8, x - state.drag.dx);
        node.y = Math.max(8, y - state.drag.dy);
        const el = canvas.querySelector(`[data-ref="${{CSS.escape(node.id)}}"]`);
        if (el) {{
          el.style.left = `${{node.x}}px`;
          el.style.top = `${{node.y}}px`;
        }}
        drawLines();
      }}
    }}
    if (state.link) {{
      state.link.x2 = x;
      state.link.y2 = y;
      root.querySelectorAll('.route-port.in').forEach(p => p.classList.remove('ready'));
      const target = document.elementFromPoint(ev.clientX, ev.clientY);
      if (target && target.classList.contains('route-port') && target.dataset.port === 'in') {{
        target.classList.add('ready');
      }}
      drawLines(state.link);
    }}
  }});
  document.addEventListener('mouseup', ev => {{
    if (state.link) {{
      const target = document.elementFromPoint(ev.clientX, ev.clientY);
      if (target && target.classList.contains('route-port') && target.dataset.port === 'in') {{
        const to = target.closest('.route-node').dataset.ref;
        if (to && to !== state.link.from) {{
          state.edges.push({{from: state.link.from, to}});
          state.selectedEdge = null;
        }}
      }}
      state.link = null;
      root.querySelectorAll('.route-port.in').forEach(p => p.classList.remove('ready'));
      render();
    }}
    state.drag = null;
  }});
  window.__routeEditors = window.__routeEditors || {{}};
  window.__routeEditors[{json.dumps(editor_id)}] = {{
    getGraph() {{
      uniqueEdges();
      const reachable = new Set();
      const stack = [state.entry];
      while (stack.length) {{
        const current = stack.pop();
        if (!current || reachable.has(current)) continue;
        reachable.add(current);
        state.edges.filter(e => e.from === current).forEach(e => stack.push(e.to));
      }}
      const routes = {{}};
      state.edges.forEach(e => {{
        if (!reachable.has(e.from) || !reachable.has(e.to)) return;
        routes[e.from] = routes[e.from] || [];
        if (!routes[e.from].includes(e.to)) routes[e.from].push(e.to);
      }});
      return {{entry: state.entry, routes, reachable: Array.from(reachable)}};
    }}
  }};
  render();
}})();
</script>
"""


def _split_route_graph_editor_assets(content: str) -> tuple[str, str]:
    """Split editor markup from the init script so NiceGUI can run it explicitly."""
    match = re.search(r"<script>(.*)</script>\s*$", content, flags=re.DOTALL)
    if not match:
        return content, ""
    html = content[:match.start()]
    return html, match.group(1)


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

            def _module_options(raw: dict, ref_ids: list[str] | None = None) -> dict[str, str]:
                modules = raw.get("modules", {})
                ids = ref_ids if ref_ids is not None else _all_ref_ids(raw)
                return {
                    ref_id: module_display_name(ref_id, modules.get(ref_id, {}))
                    for ref_id in ids
                }

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
                module_options = _module_options(raw)
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
                        entry = graph.get("entry", "")
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
                                        ui.label(f"入口: {module_options.get(entry, '—')}").classes("text-caption")

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
                                            dst_str = ", ".join(
                                                module_options.get(dst, "未知模块") for dst in dsts
                                            ) if dsts else "(终点)"
                                            ui.label(f"  {module_options.get(src, '未知模块')}  →  {dst_str}").classes(
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
                entry_val = existing_entry if existing_entry in producer_refs else (producer_refs[0] if producer_refs else "")
                editor_id = f"route_editor_{uuid.uuid4().hex}"
                editor_html, editor_js = _split_route_graph_editor_assets(_build_route_graph_editor_html(
                    editor_id=editor_id,
                    modules_cfg=raw.get("modules", {}),
                    all_refs=all_refs,
                    producer_refs=producer_refs,
                    entry_ref=entry_val,
                    routes=existing_routes,
                ))

                with ui.dialog() as edit_dlg, ui.card().classes("w-full").style("min-width:780px; max-width:1120px"):
                    ui.label(f"编辑管道: {pipeline_id}").classes("text-h6")
                    ui.label(f"ID: {pipeline_id}（不可修改）").classes("text-caption text-grey")

                    name_input = ui.input(
                        label="显示名称",
                        value=pipeline_cfg.get("name", pipeline_id),
                    ).classes("w-full")

                    enabled_switch = ui.switch("启用", value=pipeline_cfg.get("enabled", False))

                    if producer_refs:
                        ui.label("入口模块在图中的蓝色入口节点上选择，只能选择 PacketProducerModule 类型模块。").classes(
                            "text-caption text-grey"
                        )
                    else:
                        ui.label("⚠ 尚无可用的入口模块（音频源），请先在「模块目录」页新增。").style("color:orange")

                    ui.separator().classes("q-my-sm")
                    ui.label("路由图编辑器").classes("text-subtitle2")
                    ui.html(editor_html, sanitize=False).classes("w-full")

                    ui.separator().classes("q-my-sm")

                    async def _confirm_edit() -> None:
                        if not producer_refs:
                            ui.notify("请选择入口模块", type="warning")
                            return
                        graph_data = await ui.run_javascript(
                            f"window.__routeEditors[{json.dumps(editor_id)}].getGraph()"
                        )
                        built_routes = graph_data.get("routes", {}) if isinstance(graph_data, dict) else {}
                        r = engine.get_raw_config()
                        for p in r.get("pipelines", []):
                            if isinstance(p, dict) and p.get("id") == pipeline_id:
                                p["name"] = name_input.value.strip() or pipeline_id
                                p["enabled"] = enabled_switch.value
                                p["graph"] = {
                                    "entry": graph_data.get("entry", entry_val) if isinstance(graph_data, dict) else entry_val,
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
                if editor_js:
                    ui.timer(0.1, lambda: ui.run_javascript(editor_js), once=True, immediate=False)

            draw_pipelines()

            ui.separator()

            # ──────────────────────────────────────────────────────────────
            # 新建管道按钮 → 打开 dialog
            # ──────────────────────────────────────────────────────────────
            def _open_create_dialog() -> None:
                raw = engine.get_raw_config()
                all_refs = _all_ref_ids(raw)
                producer_refs = _producer_ref_ids(raw)
                entry_val = producer_refs[0] if producer_refs else ""
                editor_id = f"route_editor_{uuid.uuid4().hex}"
                editor_html, editor_js = _split_route_graph_editor_assets(_build_route_graph_editor_html(
                    editor_id=editor_id,
                    modules_cfg=raw.get("modules", {}),
                    all_refs=all_refs,
                    producer_refs=producer_refs,
                    entry_ref=entry_val,
                    routes={},
                ))

                with ui.dialog() as dlg, ui.card().classes("w-full").style("min-width:780px; max-width:1120px"):
                    ui.label("新建管道").classes("text-h6")

                    with ui.grid(columns=2).classes("w-full gap-2"):
                        id_input = ui.input(label="* 管道 ID（唯一，不含空格）").classes("w-full")
                        name_input = ui.input(label="显示名称").classes("w-full")

                    enabled_switch = ui.switch("默认启用", value=False)

                    if producer_refs:
                        ui.label("入口模块在图中的蓝色入口节点上选择，只能选择 PacketProducerModule 类型模块。").classes(
                            "text-caption text-grey"
                        )
                    else:
                        ui.label("⚠ 尚无可用的入口模块（音频源），请先在「模块目录」页新增。").style("color:orange")

                    ui.separator().classes("q-my-sm")
                    ui.label("路由图编辑器").classes("text-subtitle2")
                    ui.html(editor_html, sanitize=False).classes("w-full")

                    ui.separator().classes("q-my-sm")

                    async def _confirm_create() -> None:
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
                        if not producer_refs:
                            ui.notify("请选择入口模块", type="warning")
                            return

                        graph_data = await ui.run_javascript(
                            f"window.__routeEditors[{json.dumps(editor_id)}].getGraph()"
                        )
                        built_routes = graph_data.get("routes", {}) if isinstance(graph_data, dict) else {}

                        new_pipeline = {
                            "id": pid,
                            "name": name_input.value.strip() or pid,
                            "enabled": enabled_switch.value,
                            "graph": {
                                "entry": graph_data.get("entry", entry_val) if isinstance(graph_data, dict) else entry_val,
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
                if editor_js:
                    ui.timer(0.1, lambda: ui.run_javascript(editor_js), once=True, immediate=False)

            ui.button(
                "＋ 新建管道", icon="add", color="primary",
                on_click=_open_create_dialog,
            )

