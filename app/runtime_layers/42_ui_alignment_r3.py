# Presentation-only layer. It preserves routes, query parameters, payloads,
# database statements, sort/filter behavior, refresh cadence and Agent flow.
V5059R3_RELEASE = "50.5.9-prod-r4-dead-code-cleanup"

# One appearance selector contains the three core modes plus every configured
# saved theme. Existing localStorage keys stay compatible with older releases.
def _v5049_theme_selector_html(settings=None):
    theme_options = []
    for theme in _v5049_available_themes(settings):
        theme_options.append(
            '<option value="theme:%s">%s</option>' % (
                escape(theme["id"], quote=True), escape(theme["name"]),
            )
        )
    saved_group = (
        '<optgroup label="Themes">%s</optgroup>' % ''.join(theme_options)
        if theme_options else ''
    )
    return '''
    <div class="appearance-controls appearance-controls-r5 appearance-controls-r3" aria-label="Theme">
      <label class="appearance-select appearance-select-r3"><span>Theme</span>
        <select id="unified-theme-select" aria-label="Theme">
          <optgroup label="Display">
            <option value="mode:auto">Auto</option>
            <option value="mode:light">Light</option>
            <option value="mode:dark">Dark</option>
          </optgroup>
          %s
        </select>
      </label>
    </div>''' % saved_group

def _v5049_runtime_theme_script(settings=None):
    payload = json.dumps(_v5049_theme_client_payload(settings), separators=(",", ":"), sort_keys=True)
    return f'''
<script id="v5059r3-unified-theme-runtime">
(function(){{
  var themes={payload};
  var customKey="{V5049_THEME_SELECTION_KEY}";
  var coreApply=(typeof window.applyTheme==="function")?window.applyTheme:null;
  function currentSelect(){{return document.getElementById("unified-theme-select")}}
  function readCustom(){{try{{return localStorage.getItem(customKey)||""}}catch(e){{return""}}}}
  function writeCustom(id){{try{{if(id)localStorage.setItem(customKey,id);else localStorage.removeItem(customKey)}}catch(e){{}}}}
  function coreMode(){{try{{var mode=localStorage.getItem("bw-theme-mode")||"auto";return mode==="dark"||mode==="light"?mode:"auto"}}catch(e){{return"auto"}}}}
  function selectValue(value){{var select=currentSelect();if(select)select.value=value}}
  function useCore(mode,persist){{
    mode=(mode==="dark"||mode==="light")?mode:"auto";
    writeCustom("");
    document.documentElement.removeAttribute("data-custom-theme");
    if(coreApply)coreApply(mode,!!persist);
    else{{
      try{{if(persist)localStorage.setItem("bw-theme-mode",mode)}}catch(e){{}}
      document.documentElement.setAttribute("data-theme-mode",mode);
      var resolved=mode;
      if(mode==="auto"&&window.matchMedia)resolved=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
      document.documentElement.setAttribute("data-theme",resolved);
    }}
    selectValue("mode:"+mode);
  }}
  function useCustom(id,persist){{
    if(!themes[id]){{useCore(coreMode(),false);return}}
    if(persist)writeCustom(id);
    document.documentElement.setAttribute("data-custom-theme",id);
    document.documentElement.setAttribute("data-theme",themes[id]);
    document.documentElement.setAttribute("data-theme-mode","custom");
    selectValue("theme:"+id);
  }}
  function applySelection(value,persist){{
    if(value&&value.indexOf("theme:")===0)useCustom(value.slice(6),persist);
    else useCore(value&&value.indexOf("mode:")===0?value.slice(5):"auto",persist);
  }}
  function applyStored(){{var id=readCustom();if(id&&themes[id])useCustom(id,false);else useCore(coreMode(),false)}}
  window.virtinfraApplySelectedTheme=applyStored;
  window.applyTheme=function(mode,persist){{
    if(persist){{useCore(mode,true);return}}
    var id=readCustom();
    if(id&&themes[id])useCustom(id,false);else if(coreApply)coreApply(mode,false);else useCore(mode,false);
  }};
  document.addEventListener("change",function(ev){{
    var target=ev.target;
    if(target&&target.id==="unified-theme-select")applySelection(target.value,true);
  }});
  window.addEventListener("storage",function(ev){{
    if(ev.key===customKey||ev.key==="bw-theme-mode")applyStored();
  }});
  applyStored();
}})();
</script>
'''

# Add fixed column definitions to the already-rendered Consumption tables.
# The table body, links, sort keys and values are delegated byte-for-byte to
# the existing implementation.
_v5059r3_vm_consumption_table_base = _v5058c_vm_table
_v5059r3_node_consumption_table_base = _v5058c_node_table

def _v5058c_vm_table(rows, common, sort_by, order):
    html = _v5059r3_vm_consumption_table_base(rows, common, sort_by, order)
    return html.replace(
        '<table class="v5058c-table v5058c-vm-table">',
        '<table class="v5058c-table v5058c-vm-table">'
        '<colgroup>'
        '<col class="v5059r3-cons-vm"><col class="v5059r3-cons-node">'
        '<col class="v5059r3-cons-metric"><col class="v5059r3-cons-metric"><col class="v5059r3-cons-metric">'
        '<col class="v5059r3-cons-metric"><col class="v5059r3-cons-metric"><col class="v5059r3-cons-metric">'
        '<col class="v5059r3-cons-coverage"><col class="v5059r3-cons-latest">'
        '</colgroup>',
        1,
    )

def _v5058c_node_table(rows, common, sort_by, order):
    html = _v5059r3_node_consumption_table_base(rows, common, sort_by, order)
    return html.replace(
        '<table class="v5058c-table v5058c-node-table">',
        '<table class="v5058c-table v5058c-node-table">'
        '<colgroup>'
        '<col class="v5059r3-cons-node-only">'
        '<col class="v5059r3-cons-node-metric"><col class="v5059r3-cons-node-metric"><col class="v5059r3-cons-node-metric">'
        '<col class="v5059r3-cons-node-metric"><col class="v5059r3-cons-node-metric"><col class="v5059r3-cons-node-metric">'
        '<col class="v5059r3-cons-node-coverage"><col class="v5059r3-cons-node-latest">'
        '</colgroup>',
        1,
    )

# Node Health was the last operational list without an internal scroll frame.
# Only the returned markup is wrapped; the original renderer and its data are
# untouched.
_v5059r3_node_health_table_base = node_health_table

def node_health_table(rows, q="", sort_by="status", order="asc"):
    html = _v5059r3_node_health_table_base(rows, q=q, sort_by=sort_by, order=order)
    html = html.replace('<table>', '<div class="table-wrap node-health-table-wrap"><table class="node-health-table">', 1)
    html = html.replace('</table>', '</table></div>', 1)
    return html

V5059R3_UI_CSS = r'''
<style id="v5059r3-ui-alignment-overflow-hotfix">
/* Keep page chrome fixed while wide data tables scroll inside their cards. */
html,body{max-width:100%;overflow-x:hidden!important}
.wrap,main,.card,.table-wrap{min-width:0;box-sizing:border-box}
.table-wrap{
  width:100%;max-width:100%;overflow-x:auto!important;overflow-y:hidden!important;
  overscroll-behavior-inline:contain;scrollbar-gutter:stable;isolation:isolate;
  border-radius:9px;clip-path:inset(0 round 9px)
}
.table-wrap>table{max-width:none;margin:0}
.table-wrap th,.table-wrap td{box-sizing:border-box}
.table-wrap td>*{max-width:100%;box-sizing:border-box}
.table-wrap .uuid-cell,.table-wrap .node-name-cell,.table-wrap .dashboard-interface-wrap,
.table-wrap .vm-ram-block,.table-wrap .top-disk-capacity{min-width:0;max-width:100%}
.table-wrap .copy-btn{flex:0 0 auto}

/* One Theme control. There is no separate Style control in the rendered UI. */
.appearance-controls-r3{display:flex!important;justify-content:flex-end!important;gap:0!important}
.appearance-select-r3{grid-template-columns:auto minmax(124px,190px)!important;gap:7px!important}
.appearance-select-r3 select{width:100%;min-width:124px!important;max-width:190px!important}

/* Dashboard: align metric headers and values, and keep Interface inside the edge. */
body.endpoint-index .node-dashboard-table{min-width:1740px!important;table-layout:fixed!important}
body.endpoint-index .node-dashboard-table th,
body.endpoint-index .node-dashboard-table td{overflow:hidden;text-overflow:ellipsis;vertical-align:middle!important}
body.endpoint-index .node-dashboard-table th:nth-child(1),
body.endpoint-index .node-dashboard-table td:nth-child(1){text-align:left!important;padding-left:12px!important}
body.endpoint-index .node-dashboard-table th:nth-child(2),
body.endpoint-index .node-dashboard-table td:nth-child(2),
body.endpoint-index .node-dashboard-table th:nth-child(3),
body.endpoint-index .node-dashboard-table td:nth-child(3){text-align:center!important}
body.endpoint-index .node-dashboard-table th:nth-child(n+4),
body.endpoint-index .node-dashboard-table td:nth-child(n+4){text-align:center!important;font-variant-numeric:tabular-nums lining-nums}
body.endpoint-index .node-dashboard-table th:nth-child(18),
body.endpoint-index .node-dashboard-table td:nth-child(18){
  width:158px!important;min-width:158px!important;max-width:158px!important;
  padding-left:10px!important;padding-right:14px!important;text-align:center!important
}
body.endpoint-index .dashboard-interface-wrap{
  width:100%;display:flex!important;flex-direction:column;align-items:center;justify-content:center;
  gap:3px;overflow:hidden;text-align:center
}
body.endpoint-index .dashboard-interface-wrap .vm-state{max-width:100%;white-space:nowrap}
body.endpoint-index .dashboard-interface-wrap small{
  display:block;width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center
}
body.endpoint-index .dashboard-load-pill{margin-inline:auto!important}

/* Top VM: preserve the established Node/UUID cells and equalize all resource tracks. */
body.endpoint-top-page .table-top-vm{min-width:2010px!important;table-layout:fixed!important}
body.endpoint-top-page .table-top-vm col.top-rank{width:30px!important}
body.endpoint-top-page .table-top-vm col.top-node{width:135px!important}
body.endpoint-top-page .table-top-vm col.top-uuid{width:290px!important}
body.endpoint-top-page .table-top-vm col.top-cpu{width:164px!important}
body.endpoint-top-page .table-top-vm col.top-vcpu{width:48px!important}
body.endpoint-top-page .table-top-vm col.top-ram{width:190px!important}
body.endpoint-top-page .table-top-vm col.top-diskcap{width:190px!important}
body.endpoint-top-page .table-top-vm th:nth-child(13),body.endpoint-top-page .table-top-vm td:nth-child(13),
body.endpoint-top-page .table-top-vm th:nth-child(15),body.endpoint-top-page .table-top-vm td:nth-child(15),
body.endpoint-top-page .table-top-vm th:nth-child(16),body.endpoint-top-page .table-top-vm td:nth-child(16){text-align:center!important}
body.endpoint-top-page .cpu-dual-head>div,
body.endpoint-top-page .cpu-dual-head>small,
body.endpoint-top-page .ram-compact-head,
body.endpoint-top-page .disk-cap-compact-head,
body.endpoint-top-page .disk-cap-compact-head>small{
  width:100%!important;max-width:100%;margin-inline:auto;align-items:center!important;
  justify-content:center!important;justify-items:center!important;text-align:center!important
}
body.endpoint-top-page .disk-cap-compact-head>small{display:flex!important;flex-wrap:nowrap!important;gap:3px!important}
body.endpoint-top-page .cpu-dual-cell,
body.endpoint-top-page .ram-cell,
body.endpoint-top-page .disk-cap-cell{padding-left:8px!important;padding-right:8px!important;text-align:center!important}
body.endpoint-top-page .cpu-dual-cell .cpu-core-value,
body.endpoint-top-page .vm-ram-compact .ram-guest-value,
body.endpoint-top-page .top-disk-capacity>b{
  display:flex!important;align-items:center;justify-content:center;min-height:16px;margin:0!important;
  white-space:nowrap;text-align:center
}
body.endpoint-top-page .cpu-dual-cell .cpu-full-value,
body.endpoint-top-page .vm-ram-compact .ram-guest-label{display:block!important;min-height:12px;margin-top:2px!important;text-align:center!important}
body.endpoint-top-page .cpu-dual-cell .cpu-meter,
body.endpoint-top-page .vm-ram-compact .ram-meter,
body.endpoint-top-page .top-disk-capacity .disk-cap-meter{
  display:block!important;width:136px!important;min-width:136px!important;max-width:136px!important;
  height:5px!important;margin-left:auto!important;margin-right:auto!important
}
body.endpoint-top-page .cpu-dual-cell .cpu-meter{margin-top:5px!important}
body.endpoint-top-page .vm-ram-compact{width:164px!important;margin-inline:auto!important;text-align:center!important}
body.endpoint-top-page .vm-ram-compact .ram-meter{margin-top:4px!important}
body.endpoint-top-page .vm-ram-compact .ram-host-line{display:block!important;text-align:center!important;white-space:nowrap}
body.endpoint-top-page .top-disk-capacity{width:164px!important;margin-inline:auto!important;text-align:center!important}
body.endpoint-top-page .top-disk-capacity>b{margin-bottom:16px!important}
body.endpoint-top-page .top-disk-capacity .disk-cap-meter{margin-top:0!important}
body.endpoint-top-page .top-disk-capacity small{display:block!important;text-align:center!important;white-space:nowrap}

/* Consumption toolbar: search stays useful without swallowing the entire row. */
body.endpoint-bandwidth-consumption-page .v5058c-toolbar{
  justify-content:start!important;justify-items:stretch;align-items:center!important;column-gap:8px!important
}
body.endpoint-bandwidth-consumption-page .v5058c-toolbar:has(select[name="node"]){
  grid-template-columns:minmax(320px,520px) minmax(220px,360px) minmax(180px,240px) auto auto auto!important
}
body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])){ 
  grid-template-columns:minmax(300px,460px) minmax(180px,240px) auto auto auto!important
}
body.endpoint-bandwidth-consumption-page .v5058c-search{width:100%;max-width:520px}
body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])) .v5058c-search{max-width:460px}

/* Consumption: fixed columns make both header tiers share the body grid. */
body.endpoint-bandwidth-consumption-page .v5058c-table{
  width:100%!important;table-layout:fixed!important;border-collapse:separate;border-spacing:0
}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table{min-width:1320px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table{min-width:1180px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.v5059r3-cons-vm{width:17%}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.v5059r3-cons-node{width:14%}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.v5059r3-cons-metric{width:9%}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.v5059r3-cons-coverage{width:6%}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.v5059r3-cons-latest{width:9%}
body.endpoint-bandwidth-consumption-page .v5058c-node-table col.v5059r3-cons-node-only{width:18%}
body.endpoint-bandwidth-consumption-page .v5058c-node-table col.v5059r3-cons-node-metric{width:10.5%}
body.endpoint-bandwidth-consumption-page .v5058c-node-table col.v5059r3-cons-node-coverage{width:7%}
body.endpoint-bandwidth-consumption-page .v5058c-node-table col.v5059r3-cons-node-latest{width:12%}
body.endpoint-bandwidth-consumption-page .v5058c-table.v5058c-vm-table thead tr>th:nth-child(n),
body.endpoint-bandwidth-consumption-page .v5058c-table.v5058c-vm-table tbody tr>td:nth-child(n),
body.endpoint-bandwidth-consumption-page .v5058c-table.v5058c-node-table thead tr>th:nth-child(n),
body.endpoint-bandwidth-consumption-page .v5058c-table.v5058c-node-table tbody tr>td:nth-child(n){
  width:auto!important;min-width:0!important;max-width:none!important;box-sizing:border-box
}
body.endpoint-bandwidth-consumption-page .v5058c-table thead th{
  vertical-align:middle!important;overflow:hidden;padding-left:9px!important;padding-right:9px!important
}
body.endpoint-bandwidth-consumption-page .v5058c-table thead tr:first-child>th[colspan]{text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-table thead tr:nth-child(2)>th,
body.endpoint-bandwidth-consumption-page .v5058c-table thead tr:nth-child(2)>th .sort-link{
  text-align:right!important;justify-content:flex-end!important
}
body.endpoint-bandwidth-consumption-page .v5058c-table thead .sort-link{
  display:flex!important;width:100%;max-width:100%;align-items:center;box-sizing:border-box;white-space:nowrap
}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-child(1),
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-child(2),
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:nth-child(1){text-align:left!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-child(1) .sort-link,
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-child(2) .sort-link,
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:nth-child(1) .sort-link{justify-content:flex-start!important;text-align:left!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-last-child(2),
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:nth-last-child(2){text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:nth-last-child(2) .sort-link,
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:nth-last-child(2) .sort-link{justify-content:center!important;text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:last-child,
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:last-child{text-align:right!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child>th:last-child .sort-link,
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child>th:last-child .sort-link{justify-content:flex-end!important;text-align:right!important}
body.endpoint-bandwidth-consumption-page .v5058c-table tbody td{overflow:hidden;text-overflow:ellipsis}
body.endpoint-bandwidth-consumption-page .v5058c-table tbody td:nth-last-child(2){text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-latest{text-align:right!important;padding-right:12px!important}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-uuid .uuid-cell{width:100%;max-width:100%!important;overflow:hidden}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-uuid .uuid-cell>a{min-width:0;overflow:hidden;text-overflow:ellipsis}

/* Node Health: balanced first column and contained table scrolling. */
body.endpoint-node-health-page .node-health-table-wrap{margin:0;border-radius:0 0 9px 9px}
body.endpoint-node-health-page .node-health-table{width:100%;min-width:1040px;table-layout:fixed}
body.endpoint-node-health-page .node-health-table th,
body.endpoint-node-health-page .node-health-table td{vertical-align:middle!important;box-sizing:border-box}
body.endpoint-node-health-page .node-health-table th:nth-child(1),body.endpoint-node-health-page .node-health-table td:nth-child(1){width:22%!important;padding-left:18px!important;text-align:left!important}
body.endpoint-node-health-page .node-health-table th:nth-child(2),body.endpoint-node-health-page .node-health-table td:nth-child(2){width:12%!important;text-align:center!important}
body.endpoint-node-health-page .node-health-table th:nth-child(3),body.endpoint-node-health-page .node-health-table td:nth-child(3){width:17%!important;text-align:center!important;white-space:nowrap}
body.endpoint-node-health-page .node-health-table th:nth-child(4),body.endpoint-node-health-page .node-health-table td:nth-child(4){width:8%!important;text-align:center!important}
body.endpoint-node-health-page .node-health-table th:nth-child(5),body.endpoint-node-health-page .node-health-table td:nth-child(5){width:12%!important;text-align:center!important}
body.endpoint-node-health-page .node-health-table th:nth-child(6),body.endpoint-node-health-page .node-health-table td:nth-child(6){width:7%!important;text-align:center!important}
body.endpoint-node-health-page .node-health-table th:nth-child(7),body.endpoint-node-health-page .node-health-table td:nth-child(7){width:9%!important;text-align:center!important}
body.endpoint-node-health-page .node-health-table th:nth-child(8),body.endpoint-node-health-page .node-health-table td:nth-child(8){width:13%!important;text-align:right!important;padding-right:18px!important}

@media(max-width:1500px){
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:has(select[name="node"]){
    grid-template-columns:minmax(280px,440px) minmax(190px,300px) minmax(160px,210px) auto auto auto!important
  }
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])){ 
    grid-template-columns:minmax(280px,420px) minmax(160px,210px) auto auto auto!important
  }
}
@media(max-width:1050px){
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:has(select[name="node"]),
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])){display:flex!important;flex-wrap:wrap}
  body.endpoint-bandwidth-consumption-page .v5058c-search{flex:1 1 320px;max-width:none}
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar select[name="node"],
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar select[name="coverage"]{flex:1 1 190px}
}
</style>
'''

_page_v5059r3_base = page

def page(title, content):
    response = _page_v5059r3_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace('</head>', V5059R3_UI_CSS + '</head>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v50.5.9 r3 UI alignment layer")
    return response

