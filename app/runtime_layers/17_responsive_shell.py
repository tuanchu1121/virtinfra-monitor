#
# The previous visual layer capped the main shell and centered it. On large
# dashboards that left a large unused gutter and forced wide operational
# tables into a small viewport. This final layer is intentionally injected
# last so every route uses the available browser width while tables retain
# their own horizontal scroller when the viewport is genuinely too narrow.
V48101_VERSION = "48.10.1"
V48101_WIDE_UI_CSS = r"""
<style id="v48101-wide-ui">
html,body{width:100%;max-width:none}
body.app-v490{overflow-x:hidden}
body.app-v490 #bw-content.wrap{
  width:100%!important;
  max-width:none!important;
  min-width:0!important;
  margin:0!important;
  padding:14px 12px 28px!important;
}
body.app-v490 #bw-content.wrap>.card,
body.app-v490 #bw-content.wrap>form,
body.app-v490 #bw-content.wrap>details{
  width:100%!important;
  max-width:none!important;
}
body.app-v490 .card{max-width:none!important}
body.app-v490 .table-wrap{
  width:100%!important;
  max-width:100%!important;
  min-width:0!important;
  overflow-x:auto!important;
  overflow-y:visible;
  overscroll-behavior-x:contain;
  scrollbar-gutter:stable;
  -webkit-overflow-scrolling:touch;
}
body.app-v490 .table-wrap>table{
  min-width:100%;
}
/* Dashboard is an operations screen, so use almost edge-to-edge space. */
body.app-v490.endpoint-index #bw-content.wrap{
  padding-left:8px!important;
  padding-right:8px!important;
}
body.app-v490.endpoint-index .card{
  padding:14px!important;
  margin-bottom:12px!important;
}
body.app-v490.endpoint-index .table-wrap th{
  padding:8px 7px!important;
  font-size:10px!important;
  white-space:nowrap;
}
body.app-v490.endpoint-index .table-wrap td{
  padding:8px 7px!important;
  font-size:11px!important;
  white-space:nowrap;
}
body.app-v490.endpoint-index .top-grid{gap:10px!important}
/* Keep the other heavy data pages wide as well. */
body.app-v490.endpoint-top-page #bw-content.wrap,
body.app-v490.endpoint-top-node-page #bw-content.wrap,
body.app-v490.endpoint-node-page #bw-content.wrap,
body.app-v490.endpoint-vm-page #bw-content.wrap,
body.app-v490.endpoint-vm-abuse-page #bw-content.wrap,
body.app-v490.endpoint-admin-page #bw-content.wrap,
body.app-v490.endpoint-admin-abuse-page #bw-content.wrap{
  padding-left:10px!important;
  padding-right:10px!important;
}
body.app-v490.endpoint-vm-abuse-page .abuse-v490-table{
  min-width:1420px!important;
}
body.app-v490.endpoint-vm-abuse-page .abuse-current-card{
  padding-left:12px!important;
  padding-right:12px!important;
}
/* Prevent long metadata from widening the whole page outside its table. */
body.app-v490 .mono,
body.app-v490 .uuid-line,
body.app-v490 .identity-cell,
body.app-v490 td,
body.app-v490 th{min-width:0}
/* At very large resolutions keep readable spacing without reintroducing a cap. */
@media(min-width:2200px){
  body.app-v490 #bw-content.wrap{padding-left:18px!important;padding-right:18px!important}
  body.app-v490.endpoint-index #bw-content.wrap{padding-left:12px!important;padding-right:12px!important}
}
@media(max-width:900px){
  body.app-v490 #bw-content.wrap{padding:10px 7px 20px!important}
  body.app-v490 .card{border-radius:11px!important;padding:12px!important}
}
</style>
"""
_page_v48101_base = page

def page(title, content):
    response = _page_v48101_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48101_WIDE_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.1 wide UI layer")
    return response

