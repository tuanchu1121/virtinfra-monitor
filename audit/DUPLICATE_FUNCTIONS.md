# Duplicate function inventory (baseline)

File: `app/app.py`

Duplicate names: 123

Every duplicate implementation was retained. `Can remove` is `No` unless the old function object is proven unreachable across aliases, decorators, callbacks, dynamic lookup, and wrapper chains.

## `_abuse_flag_labels`

- Definition lines: `[12210, 12618, 13381, 15646, 16489, 22006]`
- Runtime-final definition: line `22006`
- Aliases/default captures: `11`
- Static load sites: `13`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12357: labels = _abuse_flag_labels(r[4], cfg)`
  - `12382: labels = _abuse_flag_labels(r[5], merged_cfg)`
  - `12807: labels = _abuse_flag_labels(r[4], cfg)`
  - `12835: labels = _abuse_flag_labels(r[5], merged_cfg)`
  - `12929: labels = _abuse_flag_labels(r[5], merged_cfg)`
  - `13715: labels = _abuse_flag_labels(r[4], cfg)`
  - `14577: labels = _abuse_flag_labels(r[4], cfg)`
  - `15903: labels = _abuse_flag_labels(r[4], cfg)`
  - `16388: labels = _abuse_flag_labels(r[4], cfg)`
  - `17310: labels = _abuse_flag_labels(r[4], cfg)`
  - `17502: labels = _abuse_flag_labels(r[4], cfg)`
- Caller/load evidence:
  - `12357 (vm_abuse_page_v480@12323)`
  - `12382 (vm_abuse_page_v480@12323)`
  - `12807 (vm_abuse_page_v483@12781)`
  - `12835 (vm_abuse_page_v483@12781)`
  - `12929 (admin_abuse_page_v483@12906)`
  - `13715 (vm_abuse_page_v484@13693)`
  - `14577 (_v490_abuse_current_page@14566)`
  - `15903 (_v4810_abuse_current_page@15893)`
  - `16388 (_v48102_current_abuse_page@16374)`
  - `17310 (_v48103_current_abuse_page@17302)`
  - `17502 (_v48103_current_abuse_page@17494)`
  - `22161 (_v48126_reason_badges@22160)`
  - `22371 (_v48126_api_abuse_vms_impl@22356)`

## `_abuse_state_map`

- Definition lines: `[12003, 13304]`
- Runtime-final definition: line `13304`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12069: before = _abuse_state_map(conn, node)`
  - `12092: after = _abuse_state_map(conn, node)`
  - `13404: before = _abuse_state_map(conn, node)`
  - `13484: after = _abuse_state_map(conn, node)`
- Caller/load evidence:
  - `12069 (refresh_fast_current_state@12066)`
  - `12092 (refresh_fast_current_state@12066)`
  - `13404 (refresh_fast_current_state@13401)`
  - `13484 (refresh_fast_current_state@13401)`

## `_api_authenticate`

- Definition lines: `[18259, 19153]`
- Runtime-final definition: line `19153`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `18312: _key, error = _api_authenticate(scopes)`
  - `19150: _v48120_api_authenticate_base = _api_authenticate`
- Caller/load evidence:
  - `18312 (wrapped@18311)`
  - `19150 (<module>)`

## `_apply_abuse_settings_to_runtime`

- Definition lines: `[11966, 12539, 13264, 15092, 21550]`
- Runtime-final definition: line `21550`
- Aliases/default captures: `1`
- Static load sites: `13`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `21506: _v48126_apply_settings_base = _apply_abuse_settings_to_runtime`
- Caller/load evidence:
  - `11998 (_v480_refresh_abuse_runtime_settings@11994)`
  - `12068 (refresh_fast_current_state@12066)`
  - `12459 (admin_abuse_settings@12432)`
  - `12739 (admin_abuse_settings_v483@12699)`
  - `13161 (<module>)`
  - `13403 (refresh_fast_current_state@13401)`
  - `13620 (admin_abuse_settings_v484@13575)`
  - `14298 (<module>)`
  - `15323 (refresh_fast_current_state@15315)`
  - `15570 (_v4810_save_policy@15537)`
  - `21506 (<module>)`
  - `21708 (refresh_fast_current_state@21706)`
  - `31330 (_v5050_refresh_fast_current_state@31328)`

## `_datetime_local_value`

- Definition lines: `[12150, 28996]`
- Runtime-final definition: line `28996`
- Aliases/default captures: `6`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12157: target_value = _datetime_local_value(target_ts)`
  - `13832: target_value = _datetime_local_value(target_ts)`
  - `14220: compact = f"""<form class="custom-time-form" style="display:flex;flex-basis:100%;margin-top:10px" method="get" action="{url_for('vm_page')}">\n      <input type="hidden" `
  - `14231: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Updated</div><div class="value">{fmt_full(end)}</div></div><div><div class="l`
  - `14253: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div`
  - `14399: compact = f"""<form class="custom-time-form" style="display:flex;flex-basis:100%;margin-top:10px" method="get" action="{url_for('vm_page')}">\n      <input type="hidden" `
- Caller/load evidence:
  - `12157 (dashboard_custom_time_card@12156)`
  - `13832 (_custom_snapshot_control@13824)`
  - `14222 (vm_period_links@14216)`
  - `14234 (top_node_page_v484@14226)`
  - `14256 (top_page_v484@14240)`
  - `14401 (vm_period_links@14387)`

## `_insert_abuse_event`

- Definition lines: `[12022, 12562, 13329]`
- Runtime-final definition: line `13329`
- Aliases/default captures: `0`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `12101 (refresh_fast_current_state@12066)`
  - `12103 (refresh_fast_current_state@12066)`
  - `12108 (refresh_fast_current_state@12066)`
  - `13493 (refresh_fast_current_state@13401)`
  - `13495 (refresh_fast_current_state@13401)`
  - `13500 (refresh_fast_current_state@13401)`

## `_maintenance_action_label`

- Definition lines: `[13018, 14516, 20150]`
- Runtime-final definition: line `20150`
- Aliases/default captures: `2`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14512: _maintenance_action_label_v484 = _maintenance_action_label`
  - `20145: _v48120_action_label_base = _maintenance_action_label`
- Caller/load evidence:
  - `13119 (database_maintenance_card@13096)`
  - `14512 (<module>)`
  - `19965 (database_maintenance_card@19930)`
  - `20145 (<module>)`

## `_maintenance_friendly_message`

- Definition lines: `[13068, 14522, 20206]`
- Runtime-final definition: line `20206`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13116: friendly = _maintenance_friendly_message(action, status, job_message)`
  - `14513: _maintenance_friendly_message_v484 = _maintenance_friendly_message`
  - `19960: friendly = _maintenance_friendly_message(action, status, job_message)`
  - `20147: _v48120_friendly_message_base = _maintenance_friendly_message`
- Caller/load evidence:
  - `13116 (database_maintenance_card@13096)`
  - `14513 (<module>)`
  - `19960 (database_maintenance_card@19930)`
  - `20147 (<module>)`

## `_maintenance_target_summary`

- Definition lines: `[13027, 20189]`
- Runtime-final definition: line `20189`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13117: target = _maintenance_target_summary(action, parameters)`
  - `19959: target = _maintenance_target_summary(action, parameters)`
  - `20146: _v48120_target_summary_base = _maintenance_target_summary`
- Caller/load evidence:
  - `13117 (database_maintenance_card@13096)`
  - `19959 (database_maintenance_card@19930)`
  - `20146 (<module>)`

## `_merge_event_abuse_cfg`

- Definition lines: `[12757, 15977]`
- Runtime-final definition: line `15977`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12834: merged_cfg = _merge_event_abuse_cfg(cfg, event_cfg)`
  - `12928: merged_cfg = _merge_event_abuse_cfg(cfg, event_cfg)`
- Caller/load evidence:
  - `12834 (vm_abuse_page_v483@12781)`
  - `12928 (admin_abuse_page_v483@12906)`

## `_parse_datetime_local`

- Definition lines: `[12136, 28972]`
- Runtime-final definition: line `28972`
- Aliases/default captures: `1`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12181: target_ts = _parse_datetime_local(request.args.get('at'))`
- Caller/load evidence:
  - `12181 (index_v480@12176)`
  - `13783 (_request_target_ts@13781)`

## `_public_abuse_policy`

- Definition lines: `[12771, 14305, 16005, 16459, 21986]`
- Runtime-final definition: line `21986`
- Aliases/default captures: `8`
- Static load sites: `12`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12851: content = f'{_abuse_page_style()}<div class="card top-card"><div class="overview-head"><h3>VM Abuse</h3><div class="overview-meta"><span>Current query <b>bounded state ta`
  - `13742: policy = _public_abuse_policy(cfg)`
  - `14633: policy = _public_abuse_policy(cfg)`
  - `22302: content = f"""<div class="card page-hero"><div><span class="eyebrow">ABUSE INTELLIGENCE</span><h2>VM Abuse</h2><p>Current state, paired incidents, weighted rankings and r`
  - `22962: content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse for live action, Abuse Events for repeat histor`
  - `23542: content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse uses a Top-VM-style sortable metric table. Abus`
  - `24284: content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse is a full operations table. Abuse Events groups`
  - `27690: content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse is a full operations table. Abuse Events groups`
- Caller/load evidence:
  - `12851 (vm_abuse_page_v483@12781)`
  - `13742 (vm_abuse_page_v484@13693)`
  - `14633 (_v490_abuse_current_page@14566)`
  - `15935 (_v4810_abuse_current_page@15893)`
  - `16442 (_v48102_current_abuse_page@16374)`
  - `17330 (_v48103_current_abuse_page@17302)`
  - `17518 (_v48103_current_abuse_page@17494)`
  - `22302 (vm_abuse_page_v48126@22297)`
  - `22964 (vm_abuse_page_v48127@22947)`
  - `23544 (vm_abuse_page_v48128@23525)`
  - `24286 (vm_abuse_page_v48129@24267)`
  - `27692 (vm_abuse_page_v48139@27668)`

## `_storage_io_params`

- Definition lines: `[24543, 26839]`
- Runtime-final definition: line `26839`
- Aliases/default captures: `6`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `24789: values = _storage_io_params()`
  - `25574: values = _storage_io_params()`
  - `26308: filter_href = _storage_io_url(_storage_io_params(), view='disks', node=node, mount=mount or '', q=vm_uuid, period=period, sort='writeiops', order='desc', page=1)`
  - `26836: _storage_io_params_v48137_base = _storage_io_params`
  - `27090: values = _storage_io_params()`
  - `27298: values = _storage_io_params()`
- Caller/load evidence:
  - `24789 (storage_io_page@24788)`
  - `25574 (storage_io_page_v48133@25573)`
  - `26309 (_v48136_disk_child_html@26301)`
  - `26836 (<module>)`
  - `27090 (storage_io_page_v48137@27089)`
  - `27298 (storage_io_page_v48138@27297)`

## `_storage_period_links`

- Definition lines: `[24574, 26891]`
- Runtime-final definition: line `26891`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `24809: content = STORAGE_IO_CSS + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Find the busy node storage, then identify `
  - `25590: content = STORAGE_IO_CSS + V48133_STORAGE_CSS + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>See node mount load, `
  - `27137: content = V48137_STORAGE_CSS + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Use snapshot age or an exact time, the`
  - `27341: toolbar = f'''\n    <div class="card top-card storage-top-card">\n      <div class="top-grid">\n        <div><div class="label">Latest Available</div><div class="value">{`
- Caller/load evidence:
  - `24814 (storage_io_page@24788)`
  - `25595 (storage_io_page_v48133@25573)`
  - `27143 (storage_io_page_v48137@27089)`
  - `27349 (storage_io_page_v48138@27297)`

## `_v48103_current_abuse_page`

- Definition lines: `[17302, 17494]`
- Runtime-final definition: line `17494`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `17337 (vm_abuse_page_v48103@17333)`

## `_v48103_latest_ram`

- Definition lines: `[17109, 33160]`
- Runtime-final definition: line `33160`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `17141: row = _v48103_latest_ram(node, vm_uuid)`
- Caller/load evidence:
  - `17141 (vm_page_v48103@17133)`

## `_v4810_policy_json`

- Definition lines: `[15129, 21556]`
- Runtime-final definition: line `21556`
- Aliases/default captures: `2`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `15278: thresholds = _v4810_policy_json(cfg)`
  - `21507: _v48126_policy_json_base = _v4810_policy_json`
- Caller/load evidence:
  - `15278 (_v4810_insert_abuse_event@15272)`
  - `15566 (_v4810_save_policy@15537)`
  - `21507 (<module>)`

## `_v4810_progress_bar`

- Definition lines: `[15717, 16512]`
- Runtime-final definition: line `16512`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `15738: cpu_prog = _v4810_progress_bar(r[6], cfg['cpu_required_cycles'])`
  - `15740: mbps_prog = _v4810_progress_bar(mbps_cycles, cfg['network_mbps_required_cycles'])`
  - `15741: disk_prog = _v4810_progress_bar(r[15], cfg['disk_required_cycles'])`
- Caller/load evidence:
  - `15738 (abuse_settings_admin_card@15724)`
  - `15740 (abuse_settings_admin_card@15724)`
  - `15741 (abuse_settings_admin_card@15724)`

## `_v4810_reset_current_state_for_policy`

- Definition lines: `[15520, 21571]`
- Runtime-final definition: line `21571`
- Aliases/default captures: `1`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `21508: _v48126_reset_state_base = _v4810_reset_current_state_for_policy`
- Caller/load evidence:
  - `15560 (_v4810_save_policy@15537)`
  - `21508 (<module>)`

## `_v4810_state_map`

- Definition lines: `[15155, 21587]`
- Runtime-final definition: line `21587`
- Aliases/default captures: `6`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `15324: before = _v4810_state_map(conn, node)`
  - `15486: after = _v4810_state_map(conn, node)`
  - `21709: before = _v4810_state_map(conn, node)`
  - `21863: after = _v4810_state_map(conn, node)`
  - `31331: before = _v4810_state_map(conn, node)`
  - `31484: after = _v4810_state_map(conn, node)`
- Caller/load evidence:
  - `15324 (refresh_fast_current_state@15315)`
  - `15486 (refresh_fast_current_state@15315)`
  - `21709 (refresh_fast_current_state@21706)`
  - `21863 (refresh_fast_current_state@21706)`
  - `31331 (_v5050_refresh_fast_current_state@31328)`
  - `31484 (_v5050_refresh_fast_current_state@31328)`

## `_v48120_api_key_table`

- Definition lines: `[19611, 20291]`
- Runtime-final definition: line `20291`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `19770: rows, key_count = _v48120_api_key_table()`
- Caller/load evidence:
  - `19770 (_v48120_admin_api_keys_page@19760)`

## `_v48120_api_scope_checkboxes`

- Definition lines: `[19562, 20287]`
- Runtime-final definition: line `20287`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `19771: content_tab = f'''\n        <div class="api-grid"><div class="card"><div class="table-title-row"><div><h3>Create API key</h3><div class="table-hint">Abuse permissions are pre`
- Caller/load evidence:
  - `19772 (_v48120_admin_api_keys_page@19760)`

## `_v48120_docs_tab`

- Definition lines: `[19744, 20582]`
- Runtime-final definition: line `20582`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `19776: content_tab = _v48120_docs_tab()`
- Caller/load evidence:
  - `19776 (_v48120_admin_api_keys_page@19760)`

## `_v48126_ram_hit`

- Definition lines: `[21688, 23056]`
- Runtime-final definition: line `23056`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `21796: ram_now, ram_ratios = _v48126_ram_hit(cfg, ram_metrics)`
  - `31401: ram_now, ram_ratios = _v48126_ram_hit(cfg, ram_metrics)`
- Caller/load evidence:
  - `21796 (refresh_fast_current_state@21706)`
  - `31401 (_v5050_refresh_fast_current_state@31328)`

## `_v48129_vm_detail_cpu_stat`

- Definition lines: `[23872, 33103]`
- Runtime-final definition: line `33103`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `8503 (vm_page@8398)`

## `_v48133_disk_totals_for_pairs`

- Definition lines: `[24833, 28401, 28886]`
- Runtime-final definition: line `28886`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `24884: totals = _v48133_disk_totals_for_pairs([(r[0], r[1]) for r in rows])`
  - `28883: _v48133_disk_totals_for_pairs_v48140_fast = _v48133_disk_totals_for_pairs`
- Caller/load evidence:
  - `24884 (get_top_vm_rows@24873)`
  - `28883 (<module>)`

## `_v48133_storage_disk_groups`

- Definition lines: `[25342, 28299, 28899]`
- Runtime-final definition: line `28899`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `26331: groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)`
  - `26941: groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)`
  - `27234: groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)`
  - `27727: groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)`
  - `28896: _v48133_storage_disk_groups_v48140_fast = _v48133_storage_disk_groups`
- Caller/load evidence:
  - `26331 (_v48136_storage_disk_group_table@26330)`
  - `26941 (_v48137_storage_disk_group_cards@26940)`
  - `27234 (_v48138_storage_disk_group_cards@27233)`
  - `27727 (_v48139_storage_disk_group_cards@27726)`
  - `28896 (<module>)`

## `_v48133_storage_disk_table`

- Definition lines: `[25411, 26369, 27047]`
- Runtime-final definition: line `27047`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `25584: table = _v48133_storage_node_table(conn, values, start_ts) if values['view'] == 'nodes' else _v48133_storage_disk_table(conn, values, start_ts)`
  - `26366: _v48136_storage_disk_filtered_base = _v48133_storage_disk_table`
  - `27111: table = _v48133_storage_disk_table(conn, values, start_ts)`
  - `27320: table = _v48133_storage_disk_table(conn, values, start_ts)`
- Caller/load evidence:
  - `25584 (storage_io_page_v48133@25573)`
  - `26366 (<module>)`
  - `27111 (storage_io_page_v48137@27089)`
  - `27320 (storage_io_page_v48138@27297)`

## `_v48133_storage_node_table`

- Definition lines: `[25502, 26500, 27059]`
- Runtime-final definition: line `27059`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `25584: table = _v48133_storage_node_table(conn, values, start_ts) if values['view'] == 'nodes' else _v48133_storage_disk_table(conn, values, start_ts)`
  - `26497: _v48136_storage_node_filtered_base = _v48133_storage_node_table`
  - `27109: table = _v48133_storage_node_table(conn, values, start_ts)`
  - `27318: table = _v48133_storage_node_table(conn, values, start_ts)`
- Caller/load evidence:
  - `25584 (storage_io_page_v48133@25573)`
  - `26497 (<module>)`
  - `27109 (storage_io_page_v48137@27089)`
  - `27318 (storage_io_page_v48138@27297)`

## `_v48133_vm_disk_io_card`

- Definition lines: `[25140, 33146]`
- Runtime-final definition: line `33146`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `25217: details = _v48133_vm_disk_io_card(rows)`
  - `26105: details = _v48133_vm_disk_io_card(rows)`
- Caller/load evidence:
  - `25217 (vm_page_v48133@25201)`
  - `26105 (vm_page_v48135@26091)`

## `_v48133_vm_disks`

- Definition lines: `[25053, 33114]`
- Runtime-final definition: line `33114`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `25210: rows = _v48133_vm_disks(node, vm_uuid)`
  - `26100: rows = _v48133_vm_disks(node, vm_uuid)`
  - `33111: _v5057_vm_disks_history_base = _v48133_vm_disks`
- Caller/load evidence:
  - `25210 (vm_page_v48133@25201)`
  - `26100 (vm_page_v48135@26091)`
  - `33111 (<module>)`

## `_v48135_vm_disk_total_overview`

- Definition lines: `[26058, 33135]`
- Runtime-final definition: line `33135`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `26104: total_card = _v48135_vm_disk_total_overview(rows)`
- Caller/load evidence:
  - `26104 (vm_page_v48135@26091)`

## `_v48137_create_snapshot_shadow_tables`

- Definition lines: `[26746, 28239]`
- Runtime-final definition: line `28239`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `27103: stats = _v48137_create_snapshot_shadow_tables(conn, payload_rows)`
  - `27312: stats = _v48137_create_snapshot_shadow_tables(conn, payload_rows)`
  - `28236: _v48137_create_snapshot_shadow_tables_v48140_base = _v48137_create_snapshot_shadow_tables`
- Caller/load evidence:
  - `27103 (storage_io_page_v48137@27089)`
  - `27312 (storage_io_page_v48138@27297)`
  - `28236 (<module>)`

## `_v48139_current_rows`

- Definition lines: `[27509, 28427, 28918]`
- Runtime-final definition: line `28918`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `27593: rows, total, counts = _v48139_current_rows(values)`
  - `28915: _v48139_current_rows_v48140_summary = _v48139_current_rows`
- Caller/load evidence:
  - `27593 (_v48139_current_page@27591)`
  - `28915 (<module>)`

## `_v48140_bump_cache_generation`

- Definition lines: `[28038, 29048]`
- Runtime-final definition: line `29048`
- Aliases/default captures: `0`
- Static load sites: `7`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `28515 (purge_vm_data@28505)`
  - `28526 (purge_all_vms_for_node@28522)`
  - `28537 (purge_node_data@28533)`
  - `29081 (wrapper@29078)`
  - `29855 (admin_bandwidth_consumption_action@29847)`
  - `29869 (admin_bandwidth_consumption_action@29847)`
  - `30623 (_v5049_save_theme_settings@30620)`

## `_v48140_cache_generation`

- Definition lines: `[28024, 29027]`
- Runtime-final definition: line `29027`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28555: generation = _v48140_cache_generation()`
  - `28786: generation = _v48140_cache_generation()`
- Caller/load evidence:
  - `28555 (wrapper@28551)`
  - `28786 (wrapper@28782)`

## `_v48140_node_group_cards_fast`

- Definition lines: `[28666, 28907]`
- Runtime-final definition: line `28907`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28773: _v48137_storage_node_group_cards = _v48140_node_group_cards_fast`
  - `28904: _v48140_node_group_cards_fast_base = _v48140_node_group_cards_fast`
  - `28912: _v48137_storage_node_group_cards = _v48140_node_group_cards_fast`
- Caller/load evidence:
  - `28773 (<module>)`
  - `28904 (<module>)`
  - `28912 (<module>)`

## `_v48140_refresh_node_summaries`

- Definition lines: `[28133, 31512]`
- Runtime-final definition: line `31512`
- Aliases/default captures: `0`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `28186 (_v48140_rebuild_all_summaries@28177)`
  - `28232 (ingest_disk_io_current@28230)`
  - `28514 (purge_vm_data@28505)`
  - `28525 (purge_all_vms_for_node@28522)`
  - `28879 (_v48140_reconcile_summaries_if_needed@28857)`
  - `32484 (_v5052_ingest_disk_io_current@32410)`

## `_v490_admin_nav`

- Definition lines: `[14673, 18982, 30906]`
- Runtime-final definition: line `30906`
- Aliases/default captures: `9`
- Static load sites: `9`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14846: content = f'''\n    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, policy, users and maintenance are se`
  - `18853: content = f'''\n    <style>\n    .api-grid{{display:grid;grid-template-columns:minmax(320px,.8fr) minmax(500px,1.2fr);gap:16px;align-items:start}}\n    .api-scope-grid{{d`
  - `18979: _v48110_admin_nav_base = _v490_admin_nav`
  - `19777: content = f"""\n    <style>\n    .api-hero{{display:flex;justify-content:space-between;gap:18px;align-items:center}}.api-stat-grid{{display:grid;grid-template-columns:rep`
  - `20450: content = f'''\n    <style>\n    .api-edit-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,.42fr);gap:16px;align-items:start}}.api-edit-form{{display:`
  - `25935: content = f'''\n    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, policy, users and maintenance are se`
  - `30887: shell = '<div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Professional preset visibility and one simple Custom the`
  - `30895: shell = f'''\n    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Professional VirtInfra presets and one optional`
  - `30903: _v5049_admin_nav_base = _v490_admin_nav`
- Caller/load evidence:
  - `14848 (admin_page_v490@14831)`
  - `18865 (admin_api_keys_page@18800)`
  - `18979 (<module>)`
  - `19782 (_v48120_admin_api_keys_page@19760)`
  - `20455 (admin_api_key_edit@20363)`
  - `25937 (admin_page_v48134@25913)`
  - `30887 (admin_theme_manager@30844)`
  - `30897 (admin_theme_manager@30844)`
  - `30903 (<module>)`

## `_v490_admin_overview`

- Definition lines: `[14759, 29021, 29815, 30918]`
- Runtime-final definition: line `30918`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14842: section_html = _v490_admin_overview(stats)`
  - `25928: section_html = _v490_admin_overview(stats)`
  - `29018: _v502_admin_overview_base = _v490_admin_overview`
  - `29812: _v5030_admin_overview_base = _v490_admin_overview`
  - `30915: _v5049_admin_overview_base = _v490_admin_overview`
- Caller/load evidence:
  - `14842 (admin_page_v490@14831)`
  - `25928 (admin_page_v48134@25913)`
  - `29018 (<module>)`
  - `29812 (<module>)`
  - `30915 (<module>)`

## `_v5049_runtime_theme_script`

- Definition lines: `[30765, 35813, 36128]`
- Runtime-final definition: line `36128`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30949: html = html.replace('</body>', _v5049_runtime_theme_script(settings) + '</body>', 1)`
- Caller/load evidence:
  - `30949 (page@30934)`

## `_v5049_theme_selector_html`

- Definition lines: `[30741, 35792, 36101]`
- Runtime-final definition: line `36101`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30944: html = html.replace(original_switch, _v5049_theme_selector_html(settings), 1)`
- Caller/load evidence:
  - `30944 (page@30934)`

## `_v5054_vm_snapshot_overview`

- Definition lines: `[14017, 33086]`
- Runtime-final definition: line `33086`
- Aliases/default captures: `3`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14196: snapshot = _v5054_vm_snapshot_overview(node, vm_uuid, period, bridge=(request.args.get('bridge') or '').strip(), iface=(request.args.get('iface') or '').strip())`
  - `32993: _v5057_vm_snapshot_history_base = _v5054_vm_snapshot_overview`
  - `8425: snapshot = _v5054_vm_snapshot_overview(node, vm_uuid, period, bridge=bridge, iface=iface)`
- Caller/load evidence:
  - `8425 (vm_page@8398)`
  - `14163 (_historical_vm_latest_metric@14161)`
  - `14196 (get_vm_latest_metric@14194)`
  - `32993 (<module>)`

## `_v5058c_node_ctes`

- Definition lines: `[33921, 35125]`
- Runtime-final definition: line `35125`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33985: ctes, params = _v5058c_node_ctes(start, end, selected_node)`
  - `34004: ctes, params = _v5058c_node_ctes(start, end)`
  - `35178: ctes, params = _v5058c_node_ctes(start, end, selected_node)`
  - `35201: ctes, params = _v5058c_node_ctes(start, end)`
- Caller/load evidence:
  - `33985 (_v5058c_node_totals@33984)`
  - `34004 (_v5058c_node_rows@34003)`
  - `35178 (_v5058r4_node_totals_uncached@35177)`
  - `35201 (_v5058c_node_rows@35200)`

## `_v5058c_node_rows`

- Definition lines: `[34003, 35200]`
- Runtime-final definition: line `35200`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `34301: rows, total, page_no, max_page = _v5058c_node_rows(start, end, q, coverage, sort_by, order, page_no, limit)`
- Caller/load evidence:
  - `34301 (bandwidth_consumption_page_v5058c@34275)`

## `_v5058c_node_source_sql`

- Definition lines: `[33872, 35102]`
- Runtime-final definition: line `35102`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33922: source_sql, source_params = _v5058c_node_source_sql(start, end, selected_node)`
  - `35126: source_sql, source_params = _v5058c_node_source_sql(start, end, selected_node)`
- Caller/load evidence:
  - `33922 (_v5058c_node_ctes@33921)`
  - `35126 (_v5058c_node_ctes@35125)`

## `_v5058c_node_table`

- Definition lines: `[34220, 36200]`
- Runtime-final definition: line `36200`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `34304: table_html = _v5058c_node_table(rows, common, sort_by, order)`
  - `36182: _v5059r3_node_consumption_table_base = _v5058c_node_table`
- Caller/load evidence:
  - `34304 (bandwidth_consumption_page_v5058c@34275)`
  - `36182 (<module>)`

## `_v5058c_node_totals`

- Definition lines: `[33984, 35196]`
- Runtime-final definition: line `35196`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `34294 (bandwidth_consumption_page_v5058c@34275)`

## `_v5058c_search_clause`

- Definition lines: `[33761, 34952]`
- Runtime-final definition: line `34952`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33819: search_sql, search_params = _v5058c_search_clause('vm', q)`
  - `34005: search_sql, search_params = _v5058c_search_clause('node', q)`
  - `35023: search_sql, search_params = _v5058c_search_clause('vm', q)`
  - `35202: search_sql, search_params = _v5058c_search_clause('node', q)`
- Caller/load evidence:
  - `33819 (_v5058c_vm_rows@33817)`
  - `34005 (_v5058c_node_rows@34003)`
  - `35023 (_v5058c_vm_rows@35021)`
  - `35202 (_v5058c_node_rows@35200)`

## `_v5058c_visible_nodes`

- Definition lines: `[34036, 35235]`
- Runtime-final definition: line `35235`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `34329 (bandwidth_consumption_page_v5058c@34275)`

## `_v5058c_visible_vm_cte`

- Definition lines: `[33672, 34866]`
- Runtime-final definition: line `34866`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33712: visible_sql, visible_params = _v5058c_visible_vm_cte(selected_node)`
  - `34906: visible_sql, visible_params = _v5058c_visible_vm_cte(selected_node)`
- Caller/load evidence:
  - `33712 (_v5058c_vm_ctes@33710)`
  - `34906 (_v5058c_vm_ctes@34904)`

## `_v5058c_vm_ctes`

- Definition lines: `[33710, 34904]`
- Runtime-final definition: line `34904`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33799: ctes, params = _v5058c_vm_ctes(start, end, selected_node)`
  - `33818: ctes, params = _v5058c_vm_ctes(start, end, selected_node)`
  - `34999: ctes, params = _v5058c_vm_ctes(start, end, selected_node)`
  - `35022: ctes, params = _v5058c_vm_ctes(start, end, selected_node)`
- Caller/load evidence:
  - `33799 (_v5058c_vm_totals@33798)`
  - `33818 (_v5058c_vm_rows@33817)`
  - `34999 (_v5058r4_vm_totals_uncached@34998)`
  - `35022 (_v5058c_vm_rows@35021)`

## `_v5058c_vm_rows`

- Definition lines: `[33817, 35021]`
- Runtime-final definition: line `35021`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `34306: rows, total, page_no, max_page = _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit)`
- Caller/load evidence:
  - `34306 (bandwidth_consumption_page_v5058c@34275)`

## `_v5058c_vm_source_sql`

- Definition lines: `[33633, 34827]`
- Runtime-final definition: line `34827`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33711: source_sql, source_params = _v5058c_vm_source_sql(start, end, selected_node)`
  - `34905: source_sql, source_params = _v5058c_vm_source_sql(start, end, selected_node)`
- Caller/load evidence:
  - `33711 (_v5058c_vm_ctes@33710)`
  - `34905 (_v5058c_vm_ctes@34904)`

## `_v5058c_vm_table`

- Definition lines: `[34161, 36185]`
- Runtime-final definition: line `36185`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `34309: table_html = _v5058c_vm_table(rows, common, sort_by, order)`
  - `36181: _v5059r3_vm_consumption_table_base = _v5058c_vm_table`
- Caller/load evidence:
  - `34309 (bandwidth_consumption_page_v5058c@34275)`
  - `36181 (<module>)`

## `_v5058c_vm_totals`

- Definition lines: `[33798, 35017]`
- Runtime-final definition: line `35017`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `34295 (bandwidth_consumption_page_v5058c@34275)`

## `abuse_settings_admin_card`

- Definition lines: `[12466, 12644, 13508, 15724, 21894]`
- Runtime-final definition: line `21894`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12945: content = f'''\n    {_abuse_page_style()}\n    <style>\n      .admin-abuse-head{{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap}}\n`
  - `21891: _v48126_abuse_settings_card_base = abuse_settings_admin_card`
  - `9305: content = f'''\n    <div class="card">\n        <h3>Admin</h3>\n        <a href="{url_for('index')}">Back to dashboard</a>\n        <a href="{url_for('admin_users_page')}`
- Caller/load evidence:
  - `9329 (admin_page@9243)`
  - `12955 (admin_abuse_page_v483@12906)`
  - `21891 (<module>)`

## `api_v1_performance_v48140`

- Definition lines: `[28632, 28820]`
- Runtime-final definition: line `28820`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `1`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Decorator evidence:
  - `28632: app.route('/api/v1/performance')`
- Caller/load evidence:
  - `28853 (<module>)`

## `clean_interface_sort`

- Definition lines: `[1728, 16957]`
- Runtime-final definition: line `16957`
- Aliases/default captures: `6`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11588: sort_by = clean_interface_sort(sort_by)`
  - `14276: current_sort = clean_interface_sort(current_sort)`
  - `16967: requested_sort = clean_interface_sort(sort_by)`
  - `3101: sort_by = clean_interface_sort(sort_by)`
  - `3469: current_sort = clean_interface_sort(current_sort)`
  - `8275: sort_by = clean_interface_sort(request.args.get('sort', 'total'))`
- Caller/load evidence:
  - `3101 (query_node_bridge@3092)`
  - `3469 (sort_header@3468)`
  - `8275 (node_page@8272)`
  - `11588 (query_node_bridge@11582)`
  - `14276 (sort_header@14275)`
  - `16967 (query_node_bridge@16966)`

## `clean_top_sort`

- Definition lines: `[5117, 16861, 26279]`
- Runtime-final definition: line `26279`
- Aliases/default captures: `8`
- Static load sites: `8`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11638: sort_by = clean_top_sort(sort_by)`
  - `14241: sort_by = clean_top_sort(request.args.get('sort', 'total'))`
  - `14283: current_sort = clean_top_sort(current_sort)`
  - `16872: requested_sort = clean_top_sort(sort_by)`
  - `26276: _clean_top_sort_v48136_base = clean_top_sort`
  - `5617: current_sort = clean_top_sort(current_sort)`
  - `5638: sort_by = clean_top_sort(sort_by)`
  - `7747: sort_by = clean_top_sort(request.args.get('sort', 'total'))`
- Caller/load evidence:
  - `5617 (top_sort_header@5616)`
  - `5638 (get_top_vm_rows@5637)`
  - `7747 (top_page@7744)`
  - `11638 (get_top_vm_rows@11633)`
  - `14241 (top_page_v484@14240)`
  - `14283 (top_sort_header@14282)`
  - `16872 (get_top_vm_rows@16871)`
  - `26276 (<module>)`

## `clear_all_monitoring_data`

- Definition lines: `[4859, 29926]`
- Runtime-final definition: line `29926`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `29923: _v5030_clear_all_monitoring_data_base = clear_all_monitoring_data`
- Caller/load evidence:
  - `29923 (<module>)`

## `dashboard_custom_time_card`

- Definition lines: `[12156, 13846]`
- Runtime-final definition: line `13846`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12191: content = f"\n    {range_card(period, start, end, q=q, endpoint='index')}\n    {dashboard_custom_time_card(target_ts, q=q, sort_by=sort_by, sort_order=sort_order)}\n    {`
  - `13775: _dashboard_custom_time_card_v483 = dashboard_custom_time_card`
- Caller/load evidence:
  - `12193 (index_v480@12176)`
  - `13775 (<module>)`

## `database_maintenance_card`

- Definition lines: `[4963, 13096, 19930, 32811]`
- Runtime-final definition: line `32811`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14845: section_html = _v490_live_cache_card() + database_maintenance_card(dbmsg, dberr)`
  - `19927: _v48120_maintenance_card_base = database_maintenance_card`
  - `25934: section_html = _v490_live_cache_card() + database_maintenance_card(dbmsg, dberr)`
  - `32808: _v5057_database_maintenance_card_base = database_maintenance_card`
  - `9305: content = f'''\n    <div class="card">\n        <h3>Admin</h3>\n        <a href="{url_for('index')}">Back to dashboard</a>\n        <a href="{url_for('admin_users_page')}`
- Caller/load evidence:
  - `9333 (admin_page@9243)`
  - `14845 (admin_page_v490@14831)`
  - `19927 (<module>)`
  - `25934 (admin_page_v48134@25913)`
  - `32808 (<module>)`

## `db`

- Definition lines: `[252, 16592, 17996, 27936, 34475]`
- Runtime-final definition: line `34475`
- Aliases/default captures: `236`
- Static load sites: `236`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `10005: conn = db()`
  - `10070: conn = db()`
  - `10305: conn = db()`
  - `10342: conn = db()`
  - `10673: conn = db()`
  - `1075: conn = db()`
  - `1127: conn = db()`
  - `11536: conn = db()`
  - `11565: conn = db()`
  - `11605: conn = db()`
  - `11668: conn = db()`
  - `11727: conn = db()`
  - `11786: conn = db()`
  - `11935: conn = db()`
  - `12122: conn = db()`
  - `1212: conn = db()`
  - `1221: conn = db()`
  - `12251: conn = db()`
  - `12292: conn = db()`
  - `12413: conn = db()`
  - `... 216 more`
- Caller/load evidence:
  - `1075 (rebuild_cache_if_empty@1074)`
  - `1127 (rebuild_inventory_from_usage@1125)`
  - `1212 (get_admin_setting@1211)`
  - `1221 (set_admin_setting@1220)`
  - `1276 (log_account_event@1275)`
  - `1300 (log_node_event@1299)`
  - `1350 (get_dashboard_user@1346)`
  - `1362 (dashboard_user_count@1361)`
  - `1370 (active_admin_count@1369)`
  - `1393 (get_dashboard_user_by_id@1392)`
  - `1436 (bootstrap_dashboard_admin_from_settings@1427)`
  - `1454 (upsert_dashboard_user@1447)`
  - `1472 (update_dashboard_user_login@1471)`
  - `1481 (get_dashboard_users@1480)`
  - `1493 (set_dashboard_user_status@1492)`
  - `1502 (delete_dashboard_user@1501)`
  - `1512 (reset_dashboard_user_password@1510)`
  - `1562 (account_log_rows@1557)`
  - `1582 (node_log_rows@1577)`
  - `1603 (delete_logs@1597)`
  - `2391 (auto_purge_migrated_vms@2388)`
  - `2438 (get_vm_current_location@2437)`
  - `2464 (get_recent_vm_migrations@2462)`
  - `2618 (get_node_live_last_seen@2617)`
  - `2654 (get_snapshot_tier@2651)`
  - `3064 (get_node_rows@2721)`
  - `3116 (query_node_bridge@3092)`
  - `3233 (get_node_overview@3229)`
  - `3584 (get_node_physical_nic_period@3581)`
  - `3803 (query_vm_chart@3794)`
  - `... 206 more`

## `delete_history_older_than`

- Definition lines: `[10297, 29898]`
- Runtime-final definition: line `29898`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `29895: _v5030_delete_history_base = delete_history_older_than`
- Caller/load evidence:
  - `29895 (<module>)`

## `enqueue_batched_purge_jobs`

- Definition lines: `[5084, 20790]`
- Runtime-final definition: line `20790`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `10060: jobs = enqueue_batched_purge_jobs('purge_vms', selected, actor)`
  - `9852: jobs = enqueue_batched_purge_jobs('purge_vms', [{'node': node, 'vm_uuid': vm_uuid}], actor)`
  - `9909: jobs = enqueue_batched_purge_jobs('purge_nodes', [node], actor)`
  - `9962: jobs = enqueue_batched_purge_jobs('purge_node_vms', [node], actor)`
  - `9995: jobs = enqueue_batched_purge_jobs(queue_action, nodes, actor)`
- Caller/load evidence:
  - `9852 (admin_delete_vm@9838)`
  - `9909 (admin_delete_node@9896)`
  - `9962 (admin_purge_node_vms@9952)`
  - `9995 (admin_bulk_nodes@9973)`
  - `10060 (admin_bulk_vms@10033)`

## `enqueue_maintenance_job`

- Definition lines: `[5015, 14451, 19872, 20689, 32651]`
- Runtime-final definition: line `32651`
- Aliases/default captures: `7`
- Static load sites: `7`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14448: _enqueue_maintenance_job_v484 = enqueue_maintenance_job`
  - `14542: job_id, _unit = enqueue_maintenance_job('clear_live_cache', {}, actor)`
  - `19869: _v48120_enqueue_maintenance_base = enqueue_maintenance_job`
  - `19917: job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)`
  - `20825: job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)`
  - `5093: job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)`
  - `9447: job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)`
- Caller/load evidence:
  - `5093 (enqueue_batched_purge_jobs@5084)`
  - `9447 (admin_database_maintenance@9415)`
  - `14448 (<module>)`
  - `14542 (admin_clear_live_cache@14534)`
  - `19869 (<module>)`
  - `19917 (_v48120_admin_database_maintenance@19903)`
  - `20825 (enqueue_batched_purge_jobs@20790)`

## `ensure_disk_io_schema`

- Definition lines: `[24342, 28113]`
- Runtime-final definition: line `28113`
- Aliases/default captures: `1`
- Static load sites: `13`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28106: _v48140_disk_schema_builder = ensure_disk_io_schema`
- Caller/load evidence:
  - `8025 (get_node_filesystems_snapshot@8018)`
  - `9708 (purge_vm_data@9636)`
  - `9777 (purge_all_vms_for_node@9719)`
  - `24398 (ingest_disk_io_current@24392)`
  - `24795 (storage_io_page@24788)`
  - `24845 (_v48133_disk_totals_for_pairs@24833)`
  - `25582 (storage_io_page_v48133@25573)`
  - `25621 (purge_vm_data@25610)`
  - `26532 (ensure_storage_snapshot_schema@26524)`
  - `27550 (_v48139_current_rows@27509)`
  - `28057 (ensure_v48140_performance_schema@28056)`
  - `28106 (<module>)`
  - `32411 (_v5052_ingest_disk_io_current@32410)`

## `ensure_v48140_performance_schema`

- Definition lines: `[28056, 28123]`
- Runtime-final definition: line `28123`
- Aliases/default captures: `1`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28107: _v48140_performance_schema_builder = ensure_v48140_performance_schema`
- Caller/load evidence:
  - `28107 (<module>)`
  - `28137 (_v48140_refresh_node_summaries@28133)`
  - `28178 (_v48140_rebuild_all_summaries@28177)`
  - `28203 (_v48140_bootstrap_performance@28195)`
  - `28858 (_v48140_reconcile_summaries_if_needed@28857)`
  - `31516 (_v48140_refresh_node_summaries@31512)`

## `fmt_chart_label`

- Definition lines: `[3769, 28963]`
- Runtime-final definition: line `28963`
- Aliases/default captures: `6`
- Static load sites: `15`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `17191: rows = [{'bucket': int(r[0]), 'label': fmt_chart_label(r[0], CACHE_BUCKET_SECONDS), 'total_cpu_percent': float(r[1] or 0), 'max_cpu_percent': float(r[2] or 0), 'ram_rs`
  - `30256: rows = [{'bucket': safe_int(r[0], 0), 'label': fmt_chart_label(r[0], CACHE_BUCKET_SECONDS), 'public': safe_int(r[1], 0), 'private': safe_int(r[2], 0), 'rx': safe_int(r`
  - `30323: rows = [{'bucket': safe_int(r[0], 0), 'label': fmt_chart_label(r[0], CACHE_BUCKET_SECONDS), 'total_cpu_percent': safe_float(r[1], 0), 'max_cpu_percent': safe_float(r[2`
  - `35585: label = row.get('label') or fmt_chart_label(bucket, _v5058r5_chart_cadence(ordered))`
  - `3948: rows = [{'bucket': int(r[0]), 'label': fmt_chart_label(r[0], CACHE_BUCKET_SECONDS), 'public': int(r[1] or 0), 'private': int(r[2] or 0), 'rx': int(r[3] or 0), 'tx': in`
  - `7857: rows = [{'bucket': int(r[0]), 'label': fmt_chart_label(r[0], CACHE_BUCKET_SECONDS), 'total_cpu_percent': float(r[1] or 0), 'max_cpu_percent': float(r[2] or 0), 'ram_rs`
- Caller/load evidence:
  - `3831 (query_vm_chart@3794)`
  - `3949 (query_node_chart@3910)`
  - `4507 (query_vm_perf_chart@4489)`
  - `7823 (query_node_network_health_chart@7791)`
  - `7857 (query_node_perf_chart@7828)`
  - `8079 (query_node_host_chart@8056)`
  - `17087 (query_vm_perf_chart@17064)`
  - `17192 (query_node_perf_chart@17160)`
  - `30124 (_v5040_network_row@30101)`
  - `30208 (query_vm_perf_chart@30184)`
  - `30257 (query_node_chart@30237)`
  - `30288 (query_node_network_health_chart@30265)`
  - `30324 (query_node_perf_chart@30295)`
  - `30356 (query_node_host_chart@30337)`
  - `35585 (_v5058r5_x_labels@35569)`

## `fmt_full`

- Definition lines: `[1867, 28945]`
- Runtime-final definition: line `28945`
- Aliases/default captures: `38`
- Static load sites: `112`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14231: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Updated</div><div class="value">{fmt_full(end)}</div></div><div><div class="l`
  - `14253: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div`
  - `14597: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push</small></div>"""`
  - `15730: version_rows = ''.join((f"""<tr><td class="num">v{safe_int(r[0], 0)}</td><td>{fmt_full(r[1])}</td><td>{escape(r[2] or '-')}</td><td>{escape(r[3] or 'save')}</td></tr>""" for r`
  - `15923: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `16416: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `17316: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `17509: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `18821: expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'`
  - `18822: used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'`
  - `19628: expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'`
  - `19629: used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'`
  - `20312: expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'`
  - `20313: used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'`
  - `20448: current_expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'`
  - `20449: last_used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'`
  - `23800: title = f'{title_prefix} {fmt_full(started)}'`
  - `24809: content = STORAGE_IO_CSS + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Find the busy node storage, then identify `
  - `25590: content = STORAGE_IO_CSS + V48133_STORAGE_CSS + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>See node mount load, `
  - `2689: time_cells = f'\n            <div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div>\n            <div><div class="label">Timezone</div>`
  - `... 18 more`
- Caller/load evidence:
  - `2267 (_old_node_missing_enough@2253)`
  - `2490 (vm_migration_table@2484)`
  - `2690 (range_card@2682)`
  - `2692 (range_card@2682)`
  - `2698 (range_card@2682)`
  - `2700 (range_card@2682)`
  - `3400 (node_table@3350)`
  - `3742 (overview_cards@3730)`
  - `4023 (node_chart_svg@3970)`
  - `4112 (node_chart_table@4084)`
  - `4315 (vm_chart_svg@4263)`
  - `4421 (vm_metric_chart_svg@4348)`
  - `4477 (vm_chart_table@4463)`
  - `4969 (database_maintenance_card@4963)`
  - `5531 (node_health_table@5506)`
  - `5532 (node_health_table@5506)`
  - `5549 (node_health_table@5506)`
  - `5826 (top_node_table@5794)`
  - `7270 (node_health_page@7257)`
  - `7306 (node_missed_detail_page@7295)`
  - `7307 (node_missed_detail_page@7295)`
  - `7322 (node_missed_detail_page@7295)`
  - `7323 (node_missed_detail_page@7295)`
  - `7324 (node_missed_detail_page@7295)`
  - `7360 (node_missed_detail_page@7295)`
  - `7361 (node_missed_detail_page@7295)`
  - `7402 (top_node_page@7389)`
  - `7410 (top_node_page@7389)`
  - `7758 (top_page@7744)`
  - `7766 (top_page@7744)`
  - `... 82 more`

## `fmt_push`

- Definition lines: `[1879, 28957]`
- Runtime-final definition: line `28957`
- Aliases/default captures: `9`
- Static load sites: `56`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14597: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push</small></div>"""`
  - `15923: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `16416: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `17146: replacement = f'<div class="stat vm-ram-detail-stat">VM RAM{block}<small>Updated {fmt_push(row[5])}</small></div>'`
  - `17316: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `17509: timeline = f"""<div class="timeline-cell"><b>{(fmt_full(r[3]) if r[3] else '-')}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int`
  - `27256: identity = f'\n          <div class="storage-vm-identity">\n            <span class="identity-kicker">VM UUID</span>\n            <div class="identity-uuid"><a href="{esca`
  - `3707: traffic = f"RX {float(r.get('rx_mbps') or 0):.2f} Mbps · TX {float(r.get('tx_mbps') or 0):.2f} Mbps · PPS {fmt_pps_value(total_pps)} · snapshot {fmt_push(r.get('last_seen`
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `2494 (vm_migration_table@2484)`
  - `2495 (vm_migration_table@2484)`
  - `3711 (badge@3699)`
  - `5722 (top_vm_table@5683)`
  - `7673 (vm_abuse_table@7639)`
  - `7955 (node_metric_cards@7944)`
  - `8186 (node_host_cards@8138)`
  - `8233 (node_filesystem_table@8203)`
  - `8495 (vm_page@8398)`
  - `11846 (vm_abuse_page_fast@11772)`
  - `12368 (vm_abuse_page_v480@12323)`
  - `12818 (vm_abuse_page_v483@12781)`
  - `13733 (vm_abuse_page_v484@13693)`
  - `14597 (_v490_abuse_current_page@14566)`
  - `14812 (_v490_admin_vms_section@14803)`
  - `15753 (abuse_settings_admin_card@15724)`
  - `15820 (abuse_settings_admin_card@15724)`
  - `15923 (_v4810_abuse_current_page@15893)`
  - `16329 (top_vm_table@16272)`
  - `16418 (_v48102_current_abuse_page@16374)`
  - `16926 (top_vm_table@16896)`
  - `17146 (vm_page_v48103@17133)`
  - `17253 (node_metric_cards@17246)`
  - `17316 (_v48103_current_abuse_page@17302)`
  - `17509 (_v48103_current_abuse_page@17494)`
  - `22179 (_v48126_current_page@22164)`
  - `22761 (_v48127_current_page@22741)`
  - `23314 (_v48128_current_page@23279)`
  - `24005 (_v48129_current_page@23966)`
  - `24688 (_storage_io_disk_table@24630)`
  - `... 26 more`

## `fmt_range`

- Definition lines: `[1873, 28951]`
- Runtime-final definition: line `28951`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `7397: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Updated</div>\n                <div`
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `7410 (top_node_page@7389)`
  - `8496 (vm_page@8398)`

## `get_abuse_settings`

- Definition lines: `[11932, 12503, 13225, 15031, 21511]`
- Runtime-final definition: line `21511`
- Aliases/default captures: `57`
- Static load sites: `61`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11985: cfg = get_abuse_settings()`
  - `12027: cfg = cfg or get_abuse_settings(conn)`
  - `12067: cfg = get_abuse_settings(conn)`
  - `12329: cfg = get_abuse_settings()`
  - `12459: cfg = get_abuse_settings(conn)`
  - `12467: cfg = get_abuse_settings()`
  - `12567: cfg = cfg or get_abuse_settings(conn)`
  - `12645: cfg = get_abuse_settings()`
  - `12738: cfg = get_abuse_settings(conn)`
  - `12787: cfg = get_abuse_settings()`
  - `12921: cfg = get_abuse_settings()`
  - `13296: cfg = get_abuse_settings()`
  - `13334: cfg = cfg or get_abuse_settings(conn)`
  - `13402: cfg = get_abuse_settings(conn)`
  - `13509: cfg = get_abuse_settings()`
  - `13619: cfg = get_abuse_settings(conn)`
  - `13704: cfg = get_abuse_settings()`
  - `14649: cfg = get_abuse_settings()`
  - `15119: cfg = get_abuse_settings()`
  - `15275: cfg = cfg or get_abuse_settings(conn)`
  - `... 37 more`
- Caller/load evidence:
  - `11985 (get_agent_runtime_config@11984)`
  - `11998 (_v480_refresh_abuse_runtime_settings@11994)`
  - `12027 (_insert_abuse_event@12022)`
  - `12067 (refresh_fast_current_state@12066)`
  - `12329 (vm_abuse_page_v480@12323)`
  - `12459 (admin_abuse_settings@12432)`
  - `12467 (abuse_settings_admin_card@12466)`
  - `12567 (_insert_abuse_event@12562)`
  - `12645 (abuse_settings_admin_card@12644)`
  - `12738 (admin_abuse_settings_v483@12699)`
  - `12787 (vm_abuse_page_v483@12781)`
  - `12921 (admin_abuse_page_v483@12906)`
  - `13161 (<module>)`
  - `13296 (get_agent_runtime_config@13292)`
  - `13334 (_insert_abuse_event@13329)`
  - `13402 (refresh_fast_current_state@13401)`
  - `13509 (abuse_settings_admin_card@13508)`
  - `13619 (admin_abuse_settings_v484@13575)`
  - `13704 (vm_abuse_page_v484@13693)`
  - `14298 (<module>)`
  - `14649 (vm_abuse_page_v490@14641)`
  - `15119 (get_agent_runtime_config@15118)`
  - `15275 (_v4810_insert_abuse_event@15272)`
  - `15322 (refresh_fast_current_state@15315)`
  - `15559 (_v4810_save_policy@15537)`
  - `15665 (_v4810_policy_status@15664)`
  - `15843 (_v4810_current_abuse_query@15833)`
  - `17272 (_v48103_current_abuse_query@17261)`
  - `21505 (<module>)`
  - `21629 (_v48126_insert_abuse_event@21628)`
  - `... 31 more`

## `get_agent_runtime_config`

- Definition lines: `[11984, 13292, 15118]`
- Runtime-final definition: line `15118`
- Aliases/default captures: `0`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `10689 (push@10571)`
  - `11213 (push@10571)`

## `get_node_filesystems_snapshot`

- Definition lines: `[8018, 25239, 25992, 33445]`
- Runtime-final definition: line `33445`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `25236: _get_node_filesystems_snapshot_v48133_base = get_node_filesystems_snapshot`
  - `25989: _get_node_filesystems_snapshot_v48135_base = get_node_filesystems_snapshot`
  - `33315: _v5057_get_node_filesystems_snapshot_history = get_node_filesystems_snapshot`
  - `8291: node_filesystems = get_node_filesystems_snapshot(node, period)`
- Caller/load evidence:
  - `8291 (node_page@8272)`
  - `25236 (<module>)`
  - `25989 (<module>)`
  - `33315 (<module>)`

## `get_node_host_period`

- Definition lines: `[7972, 33426]`
- Runtime-final definition: line `33426`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33314: _v5057_get_node_host_period_history = get_node_host_period`
  - `8290: node_host_period = get_node_host_period(node, period)`
- Caller/load evidence:
  - `8290 (node_page@8272)`
  - `33314 (<module>)`

## `get_node_metric_overview`

- Definition lines: `[7862, 17203, 33372]`
- Runtime-final definition: line `33372`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33313: _v5057_get_node_metric_overview_history = get_node_metric_overview`
  - `8289: node_metric_overview = get_node_metric_overview(node, period, q=q, vm_status=vm_status)`
- Caller/load evidence:
  - `8289 (node_page@8272)`
  - `33313 (<module>)`

## `get_node_overview`

- Definition lines: `[3229, 33322]`
- Runtime-final definition: line `33322`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33312: _v5057_get_node_overview_history = get_node_overview`
  - `8285: overview = get_node_overview(node, period, q=q, vm_status=vm_status)`
- Caller/load evidence:
  - `8285 (node_page@8272)`
  - `33312 (<module>)`

## `get_node_rows`

- Definition lines: `[2721, 11701, 13861]`
- Runtime-final definition: line `13861`
- Aliases/default captures: `6`
- Static load sites: `6`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11560: _get_node_rows_history = get_node_rows`
  - `11892: rows, start, end = get_node_rows(period, q)`
  - `12190: rows, start, end = get_node_rows(period, q, sort_by=sort_by, order=sort_order, target_ts=target_ts)`
  - `13769: _get_node_rows_v483 = get_node_rows`
  - `5788: rows, start, end = get_node_rows(period, q, sort_by=mapping.get(sort_by, 'cpu'), order=order)`
  - `7246: rows, start, end = get_node_rows(period, q, sort_by=sort_by, order=sort_order)`
- Caller/load evidence:
  - `5788 (get_top_node_rows@5776)`
  - `7246 (index@7227)`
  - `11560 (<module>)`
  - `11892 (summary@11890)`
  - `12190 (index_v480@12176)`
  - `13769 (<module>)`

## `get_top_vm_rows`

- Definition lines: `[5637, 11633, 14011, 16871, 22023, 24873]`
- Runtime-final definition: line `24873`
- Aliases/default captures: `7`
- Static load sites: `7`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11558: _get_top_vm_rows_history = get_top_vm_rows`
  - `13770: _get_top_vm_rows_v483 = get_top_vm_rows`
  - `14252: rows, start, end, limit = get_top_vm_rows(period, q=q, sort_by=sort_by, order=sort_order, scope=scope, limit=limit)`
  - `16858: _get_top_vm_rows_v48103_base = get_top_vm_rows`
  - `22020: _get_top_vm_rows_v48126_base = get_top_vm_rows`
  - `24870: _get_top_vm_rows_v48133_base = get_top_vm_rows`
  - `7751: rows, start, end, limit = get_top_vm_rows(period, q=q, sort_by=sort_by, order=sort_order, scope=scope, limit=limit)`
- Caller/load evidence:
  - `7751 (top_page@7744)`
  - `11558 (<module>)`
  - `13770 (<module>)`
  - `14252 (top_page_v484@14240)`
  - `16858 (<module>)`
  - `22020 (<module>)`
  - `24870 (<module>)`

## `get_vm_current_location`

- Definition lines: `[2437, 32967]`
- Runtime-final definition: line `32967`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `33197: current = get_vm_current_location(vm_uuid)`
  - `8482: current_location = get_vm_current_location(vm_uuid)`
- Caller/load evidence:
  - `8482 (vm_page@8398)`
  - `33197 (vm_page_v5057@33192)`

## `get_vm_directional_current`

- Definition lines: `[11535, 14210]`
- Runtime-final definition: line `14210`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13773: _get_vm_directional_current_v483 = get_vm_directional_current`
  - `8470: directional = get_vm_directional_current(node, vm_uuid)`
- Caller/load evidence:
  - `8470 (vm_page@8398)`
  - `13773 (<module>)`

## `get_vm_latest_metric`

- Definition lines: `[8376, 11564, 14194]`
- Runtime-final definition: line `14194`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11561: _get_vm_latest_metric_history = get_vm_latest_metric`
  - `13772: _get_vm_latest_metric_v483 = get_vm_latest_metric`
- Caller/load evidence:
  - `11561 (<module>)`
  - `13772 (<module>)`

## `ingest_disk_io_current`

- Definition lines: `[24392, 26650, 28230]`
- Runtime-final definition: line `28230`
- Aliases/default captures: `2`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `26647: _ingest_disk_io_current_v48137_base = ingest_disk_io_current`
  - `28227: _ingest_disk_io_current_v48140_base = ingest_disk_io_current`
- Caller/load evidence:
  - `11164 (push@10571)`
  - `26647 (<module>)`
  - `28227 (<module>)`

## `interface_table`

- Definition lines: `[3488, 16999, 17428, 35446]`
- Runtime-final definition: line `35446`
- Aliases/default captures: `1`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `35443: _v5058r5_interface_table_base = interface_table`
- Caller/load evidence:
  - `8300 (node_page@8272)`
  - `8302 (node_page@8272)`
  - `35443 (<module>)`

## `node_chart_svg`

- Definition lines: `[3970, 35621]`
- Runtime-final definition: line `35621`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
- Caller/load evidence:
  - `8350 (node_page@8272)`

## `node_chart_table`

- Definition lines: `[4084, 35761]`
- Runtime-final definition: line `35761`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `35753: _v5058r5_node_chart_table_base = node_chart_table`
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
- Caller/load evidence:
  - `8369 (node_page@8272)`
  - `35753 (<module>)`

## `node_filesystem_table`

- Definition lines: `[8203, 25996]`
- Runtime-final definition: line `25996`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
- Caller/load evidence:
  - `8316 (node_page@8272)`

## `node_health_table`

- Definition lines: `[5506, 36221]`
- Runtime-final definition: line `36221`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `36218: _v5059r3_node_health_table_base = node_health_table`
  - `7265: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Updated</div>\n                <div`
- Caller/load evidence:
  - `7289 (node_health_page@7257)`
  - `36218 (<module>)`

## `node_metric_cards`

- Definition lines: `[7944, 17246]`
- Runtime-final definition: line `17246`
- Aliases/default captures: `1`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
- Caller/load evidence:
  - `8319 (node_page@8272)`

## `node_sort_header`

- Definition lines: `[3281, 14267]`
- Runtime-final definition: line `14267`
- Aliases/default captures: `1`
- Static load sites: `18`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `3422: headers = {'node': node_sort_header('NODE', 'node', period, q, sort_by, order), 'status': node_sort_header('STATUS', 'last_push', period, q, sort_by, order), 'snapshot': `
- Caller/load evidence:
  - `3423 (node_table@3350)`
  - `3424 (node_table@3350)`
  - `3425 (node_table@3350)`
  - `3426 (node_table@3350)`
  - `3427 (node_table@3350)`
  - `3428 (node_table@3350)`
  - `3429 (node_table@3350)`
  - `3430 (node_table@3350)`
  - `3431 (node_table@3350)`
  - `3432 (node_table@3350)`
  - `3433 (node_table@3350)`
  - `3434 (node_table@3350)`
  - `3435 (node_table@3350)`
  - `3436 (node_table@3350)`
  - `3437 (node_table@3350)`
  - `3438 (node_table@3350)`
  - `3439 (node_table@3350)`
  - `3440 (node_table@3350)`

## `page`

- Definition lines: `[5879, 14870, 15966, 16129, 16549, 17352, 17387, 17582, 17712, 20651, 20936, 21201, 22562, 23015, 23565, 24320, 28593, 29122, 30934, 36078, 36425]`
- Runtime-final definition: line `36425`
- Aliases/default captures: `22`
- Static load sites: `72`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14858: _page_v484 = page`
  - `15963: _page_v4810_base = page`
  - `16126: _page_v48101_base = page`
  - `16546: _page_v48102_base = page`
  - `17349: _page_v48103_base = page`
  - `17384: _page_v48104_base = page`
  - `17579: _page_v48105_base = page`
  - `17710: _page_v48106_base = page`
  - `20648: _page_v48122_base = page`
  - `20933: _page_v48124_base = page`
  - `21198: _page_v48125_base = page`
  - `22194: prev = f'''<a class="btn {('disabled' if page <= 1 else '')}" href="{href(max(1, page - 1))}">Previous</a>'''`
  - `22195: nxt = f'''<a class="btn {('disabled' if page >= pages else '')}" href="{href(min(pages, page + 1))}">Next</a>'''`
  - `22559: _page_v48126_base = page`
  - `23012: _page_v48127_base = page`
  - `23562: _page_v48128_base = page`
  - `24317: _page_v48129_base = page`
  - `28590: _page_v48140_base = page`
  - `29119: _page_virtinfra_v502_base = page`
  - `30931: _page_v5049_theme_base = page`
  - `... 2 more`
- Caller/load evidence:
  - `7071 (dashboard_login@7010)`
  - `7252 (index@7227)`
  - `7291 (node_health_page@7257)`
  - `7384 (node_missed_detail_page@7295)`
  - `7427 (top_node_page@7389)`
  - `7734 (vm_abuse_page@7704)`
  - `7740 (vm_abuse_page@7704)`
  - `7786 (top_page@7744)`
  - `8373 (node_page@8272)`
  - `8516 (vm_page@8398)`
  - `8741 (admin_setup@8690)`
  - `8830 (admin_login@8745)`
  - `8879 (admin_change_password@8834)`
  - `8996 (admin_users_page@8892)`
  - `9200 (admin_logs_page@9069)`
  - `9239 (admin_system_health_page@9225)`
  - `9409 (admin_page@9243)`
  - `11882 (vm_abuse_page_fast@11772)`
  - `12196 (index_v480@12176)`
  - `12401 (vm_abuse_page_v480@12323)`
  - `12852 (vm_abuse_page_v483@12781)`
  - `12969 (admin_abuse_page_v483@12906)`
  - `13756 (vm_abuse_page_v484@13693)`
  - `14237 (top_node_page_v484@14226)`
  - `14259 (top_page_v484@14240)`
  - `14651 (vm_abuse_page_v490@14641)`
  - `14851 (admin_page_v490@14831)`
  - `14858 (<module>)`
  - `15946 (vm_abuse_page_v4810@15938)`
  - `15963 (<module>)`
  - `... 42 more`

## `period_links`

- Definition lines: `[2666, 14329]`
- Runtime-final definition: line `14329`
- Aliases/default captures: `3`
- Static load sites: `7`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `29738: content = '\n    <style id="v5030-bandwidth-consumption-css">\n      .bwcons-hero{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.bwcons-hero `
  - `30040: content = '\n    <style id="v5030-bandwidth-node-css">\n      .bwcons-periods{display:flex;gap:7px;flex-wrap:wrap}.bwcons-periods a{padding:7px 10px;border:1px solid var(`
  - `34378: content = '\n    <style id="v5058c-consumption-ui">\n      .v5058c-shell{padding:16px!important}.v5058c-head{display:flex;justify-content:space-between;gap:18px;align-ite`
- Caller/load evidence:
  - `2709 (range_card@2682)`
  - `29641 (bandwidth_consumption_page@29605)`
  - `29762 (bandwidth_consumption_page@29605)`
  - `30009 (bandwidth_consumption_node_page@29993)`
  - `30054 (bandwidth_consumption_node_page@29993)`
  - `34315 (bandwidth_consumption_page_v5058c@34275)`
  - `34403 (bandwidth_consumption_page_v5058c@34275)`

## `process_node_vm_presence`

- Definition lines: `[2370, 31008]`
- Runtime-final definition: line `31008`
- Aliases/default captures: `1`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `10932: presence_stats = process_node_vm_presence(conn, node, seen_vm_locations, data_time, inventory_complete=inventory_complete) or presence_stats`
- Caller/load evidence:
  - `2434 (update_vm_location@2433)`
  - `10932 (push@10571)`

## `purge_all_vms_for_node`

- Definition lines: `[9719, 28522]`
- Runtime-final definition: line `28522`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28519: _purge_all_vms_for_node_v48140_base = purge_all_vms_for_node`
  - `9800: deleted = purge_all_vms_for_node(conn, node)`
- Caller/load evidence:
  - `9800 (purge_node_data@9798)`
  - `28519 (<module>)`

## `purge_node_data`

- Definition lines: `[9798, 28533, 29912, 30385, 33491, 35254]`
- Runtime-final definition: line `35254`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `28530: _purge_node_data_v48140_base = purge_node_data`
  - `29909: _v5030_purge_node_data_base = purge_node_data`
  - `30382: _v5040_purge_node_data_base = purge_node_data`
  - `33489: _v5058_purge_node_data_base = purge_node_data`
  - `35252: _v5058r4_purge_node_data_base = purge_node_data`
- Caller/load evidence:
  - `28530 (<module>)`
  - `29909 (<module>)`
  - `30382 (<module>)`
  - `33489 (<module>)`
  - `35252 (<module>)`

## `purge_vm_data`

- Definition lines: `[9636, 25610, 27191, 28505, 30372, 33476]`
- Runtime-final definition: line `33476`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `27159: _purge_vm_data_v48137_base = purge_vm_data`
  - `28502: _purge_vm_data_v48140_base = purge_vm_data`
  - `30369: _v5040_purge_vm_data_base = purge_vm_data`
  - `33474: _v5058_purge_vm_data_base = purge_vm_data`
- Caller/load evidence:
  - `27159 (<module>)`
  - `28502 (<module>)`
  - `30369 (<module>)`
  - `33474 (<module>)`

## `query_node_bridge`

- Definition lines: `[3092, 11582, 14005, 16966]`
- Runtime-final definition: line `16966`
- Aliases/default captures: `5`
- Static load sites: `5`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `11559: _query_node_bridge_history = query_node_bridge`
  - `13771: _query_node_bridge_v483 = query_node_bridge`
  - `16954: _query_node_bridge_v48103_base = query_node_bridge`
  - `8283: public_rows, start, end = query_node_bridge(node, period, PUBLIC_BRIDGE, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status)`
  - `8284: private_rows, _, _ = query_node_bridge(node, period, PRIVATE_BRIDGE, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status)`
- Caller/load evidence:
  - `8283 (node_page@8272)`
  - `8284 (node_page@8272)`
  - `11559 (<module>)`
  - `13771 (<module>)`
  - `16954 (<module>)`

## `query_node_chart`

- Definition lines: `[3910, 30237]`
- Runtime-final definition: line `30237`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30072: _v5040_query_node_chart_legacy = query_node_chart`
  - `8286: chart_rows, _, _, step = query_node_chart(node, period, q=q, vm_status=vm_status)`
- Caller/load evidence:
  - `8286 (node_page@8272)`
  - `30072 (<module>)`

## `query_node_host_chart`

- Definition lines: `[8056, 30337]`
- Runtime-final definition: line `30337`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30076: _v5040_query_node_host_chart_legacy = query_node_host_chart`
  - `8292: node_host_rows, _, _, _ = query_node_host_chart(node, period)`
- Caller/load evidence:
  - `8292 (node_page@8272)`
  - `30076 (<module>)`

## `query_node_network_health_chart`

- Definition lines: `[7791, 30265]`
- Runtime-final definition: line `30265`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30074: _v5040_query_node_network_health_chart_legacy = query_node_network_health_chart`
  - `8287: node_net_rows, _, _, _ = query_node_network_health_chart(node, period, q=q)`
- Caller/load evidence:
  - `8287 (node_page@8272)`
  - `30074 (<module>)`

## `query_node_perf_chart`

- Definition lines: `[7828, 17160, 30295]`
- Runtime-final definition: line `30295`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30075: _v5040_query_node_perf_chart_legacy = query_node_perf_chart`
  - `8288: node_perf_rows, _, _, _ = query_node_perf_chart(node, period, q=q)`
- Caller/load evidence:
  - `8288 (node_page@8272)`
  - `30075 (<module>)`

## `query_vm_chart`

- Definition lines: `[3794, 30149]`
- Runtime-final definition: line `30149`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30071: _v5040_query_vm_chart_legacy = query_vm_chart`
  - `8409: rows, start, end, step = query_vm_chart(node, vm_uuid, period, bridge=bridge, iface=iface)`
  - `8528: rows, start, end, step = query_vm_chart(node, vm_uuid, period, bridge=bridge, iface=iface)`
- Caller/load evidence:
  - `8409 (vm_page@8398)`
  - `8528 (api_vm@8518)`
  - `30071 (<module>)`

## `query_vm_perf_chart`

- Definition lines: `[4489, 17064, 30184]`
- Runtime-final definition: line `30184`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `30073: _v5040_query_vm_perf_chart_legacy = query_vm_perf_chart`
  - `8410: perf_rows, _a, _b, _c = query_vm_perf_chart(node, vm_uuid, period)`
- Caller/load evidence:
  - `8410 (vm_page@8398)`
  - `30073 (<module>)`

## `range_card`

- Definition lines: `[2682, 13851]`
- Runtime-final definition: line `13851`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12191: content = f"\n    {range_card(period, start, end, q=q, endpoint='index')}\n    {dashboard_custom_time_card(target_ts, q=q, sort_by=sort_by, sort_order=sort_order)}\n    {`
  - `13774: _range_card_v483 = range_card`
  - `7248: content = f"\n    {range_card(period, start, end, q=q, endpoint='index')}\n    {node_table(rows, sort_by=sort_by, order=sort_order)}\n    "`
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
- Caller/load evidence:
  - `7249 (index@7227)`
  - `8313 (node_page@8272)`
  - `12192 (index_v480@12176)`
  - `13774 (<module>)`

## `range_for_period`

- Definition lines: `[1766, 13788]`
- Runtime-final definition: line `13788`
- Aliases/default captures: `18`
- Static load sites: `18`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13767: _range_for_period_v483 = range_for_period`
  - `17065: start, end = range_for_period(period)`
  - `17161: start, end = range_for_period(period)`
  - `24792: start_ts, end_ts = range_for_period(values['period'])`
  - `25579: start_ts, end_ts = range_for_period(values['period'])`
  - `30152: start, end = range_for_period(period)`
  - `30187: start, end = range_for_period(period)`
  - `30240: start, end = range_for_period(period)`
  - `30268: start, end = range_for_period(period)`
  - `30298: start, end = range_for_period(period)`
  - `30340: start, end = range_for_period(period)`
  - `3796: start, end = range_for_period(period)`
  - `3866: start, end = range_for_period(period)`
  - `3918: start, end = range_for_period(period)`
  - `4491: start, end = range_for_period(period)`
  - `7792: start, end = range_for_period(period)`
  - `7830: start, end = range_for_period(period)`
  - `8058: start, end = range_for_period(period)`
- Caller/load evidence:
  - `3796 (query_vm_chart@3794)`
  - `3866 (_node_retained_buckets@3860)`
  - `3918 (query_node_chart@3910)`
  - `4491 (query_vm_perf_chart@4489)`
  - `7792 (query_node_network_health_chart@7791)`
  - `7830 (query_node_perf_chart@7828)`
  - `8058 (query_node_host_chart@8056)`
  - `13767 (<module>)`
  - `17065 (query_vm_perf_chart@17064)`
  - `17161 (query_node_perf_chart@17160)`
  - `24792 (storage_io_page@24788)`
  - `25579 (storage_io_page_v48133@25573)`
  - `30152 (query_vm_chart@30149)`
  - `30187 (query_vm_perf_chart@30184)`
  - `30240 (query_node_chart@30237)`
  - `30268 (query_node_network_health_chart@30265)`
  - `30298 (query_node_perf_chart@30295)`
  - `30340 (query_node_host_chart@30337)`

## `refresh_fast_current_state`

- Definition lines: `[11271, 12066, 13401, 15315, 16613, 21706]`
- Runtime-final definition: line `21706`
- Aliases/default captures: `2`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12063: _refresh_fast_current_state_v470 = refresh_fast_current_state`
  - `16610: _refresh_fast_current_state_v48103_base = refresh_fast_current_state`
- Caller/load evidence:
  - `11167 (push@10571)`
  - `12063 (<module>)`
  - `16610 (<module>)`

## `reset_all_app_data`

- Definition lines: `[16185, 19297, 29936]`
- Runtime-final definition: line `29936`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `19294: _v48120_reset_all_app_data_base = reset_all_app_data`
  - `29933: _v5030_reset_all_app_data_base = reset_all_app_data`
- Caller/load evidence:
  - `19294 (<module>)`
  - `29933 (<module>)`

## `resolve_direct_vm_search`

- Definition lines: `[7085, 32891]`
- Runtime-final definition: line `32891`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12183: direct_vm = resolve_direct_vm_search(q)`
  - `14242: direct_vm = resolve_direct_vm_search(q) if q else None`
  - `7235: direct_vm = resolve_direct_vm_search(q)`
- Caller/load evidence:
  - `7235 (index@7227)`
  - `12183 (index_v480@12176)`
  - `14242 (top_page_v484@14240)`

## `resolve_snapshot_bucket`

- Definition lines: `[1791, 13796]`
- Runtime-final definition: line `13796`
- Aliases/default captures: `12`
- Static load sites: `12`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13768: _resolve_snapshot_bucket_v483 = resolve_snapshot_bucket`
  - `14034: selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `17207: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `26629: selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `3118: selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `3235: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `33172: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `3644: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `5641: selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=None)`
  - `7867: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `7977: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
  - `8026: selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)`
- Caller/load evidence:
  - `3118 (query_node_bridge@3092)`
  - `3235 (get_node_overview@3229)`
  - `3644 (get_node_physical_nic_period@3581)`
  - `5641 (get_top_vm_rows@5637)`
  - `7867 (get_node_metric_overview@7862)`
  - `7977 (get_node_host_period@7972)`
  - `8026 (get_node_filesystems_snapshot@8018)`
  - `13768 (<module>)`
  - `14034 (_v5054_vm_snapshot_overview@14017)`
  - `17207 (get_node_metric_overview@17203)`
  - `26629 (_v5054_selected_storage_payload@26621)`
  - `33172 (_v48103_latest_ram@33160)`

## `run_retention`

- Definition lines: `[10330, 12119, 21135, 22491, 29878]`
- Runtime-final definition: line `29878`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `12116: _run_retention_v470 = run_retention`
  - `21118: _run_retention_v48125_base = run_retention`
  - `22488: _v48126_run_retention_base = run_retention`
  - `29875: _v5030_run_retention_base = run_retention`
- Caller/load evidence:
  - `12116 (<module>)`
  - `21118 (<module>)`
  - `22488 (<module>)`
  - `29875 (<module>)`

## `sort_header`

- Definition lines: `[3468, 14275]`
- Runtime-final definition: line `14275`
- Aliases/default captures: `5`
- Static load sites: `53`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `17029: hs = {'rx': sort_header('RX', 'rx', node, period, q, sort_by, order, vm_status), 'tx': sort_header('TX', 'tx', node, period, q, sort_by, order, vm_status), 'total': `
  - `17045: ram_header = _v48104_ram_sort_header(sort_header('RAM', 'ram', node, period, q, sort_by, order, vm_status), [sort_header('Guest %', 'ram', node, period, q, sort_by, order, v`
  - `17459: hs = {'rx': sort_header('RX', 'rx', node, period, q, sort_by, order, vm_status), 'tx': sort_header('TX', 'tx', node, period, q, sort_by, order, vm_status), 'total': `
  - `17475: ram_header = _v48104_ram_sort_header(sort_header('RAM', 'ram', node, period, q, sort_by, order, vm_status), [sort_header('Guest %', 'ram', node, period, q, sort_by, order, v`
  - `3535: hs = {'rx': sort_header('RX', 'rx', node, period, q, sort_by, order, vm_status), 'tx': sort_header('TX', 'tx', node, period, q, sort_by, order, vm_status), 'total': `
- Caller/load evidence:
  - `3536 (interface_table@3488)`
  - `3537 (interface_table@3488)`
  - `3538 (interface_table@3488)`
  - `3539 (interface_table@3488)`
  - `3540 (interface_table@3488)`
  - `3541 (interface_table@3488)`
  - `3542 (interface_table@3488)`
  - `3543 (interface_table@3488)`
  - `3544 (interface_table@3488)`
  - `3545 (interface_table@3488)`
  - `3546 (interface_table@3488)`
  - `3547 (interface_table@3488)`
  - `3548 (interface_table@3488)`
  - `3549 (interface_table@3488)`
  - `3550 (interface_table@3488)`
  - `17030 (interface_table@16999)`
  - `17031 (interface_table@16999)`
  - `17032 (interface_table@16999)`
  - `17033 (interface_table@16999)`
  - `17034 (interface_table@16999)`
  - `17035 (interface_table@16999)`
  - `17036 (interface_table@16999)`
  - `17037 (interface_table@16999)`
  - `17038 (interface_table@16999)`
  - `17039 (interface_table@16999)`
  - `17040 (interface_table@16999)`
  - `17041 (interface_table@16999)`
  - `17042 (interface_table@16999)`
  - `17043 (interface_table@16999)`
  - `17046 (interface_table@16999)`
  - `... 23 more`

## `top_node_period_links`

- Definition lines: `[5162, 14348]`
- Runtime-final definition: line `14348`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14231: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Updated</div><div class="value">{fmt_full(end)}</div></div><div><div class="l`
  - `7397: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Updated</div>\n                <div`
- Caller/load evidence:
  - `7414 (top_node_page@7389)`
  - `14233 (top_node_page_v484@14226)`

## `top_node_sort_header`

- Definition lines: `[5757, 14289]`
- Runtime-final definition: line `14289`
- Aliases/default captures: `0`
- Static load sites: `1`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Caller/load evidence:
  - `5849 (h@5848)`

## `top_period_links`

- Definition lines: `[5178, 14361]`
- Runtime-final definition: line `14361`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14253: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div`
  - `7753: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Latest Available</div>\n           `
- Caller/load evidence:
  - `7770 (top_page@7744)`
  - `14255 (top_page_v484@14240)`

## `top_scope_links`

- Definition lines: `[5607, 14374]`
- Runtime-final definition: line `14374`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14253: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div`
  - `7753: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Latest Available</div>\n           `
- Caller/load evidence:
  - `7772 (top_page@7744)`
  - `14255 (top_page_v484@14240)`

## `top_sort_header`

- Definition lines: `[5616, 14282]`
- Runtime-final definition: line `14282`
- Aliases/default captures: `4`
- Static load sites: `4`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `16336: h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)`
  - `16930: h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)`
  - `25021: h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)`
  - `5729: h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)`
- Caller/load evidence:
  - `5729 (top_vm_table@5683)`
  - `16336 (top_vm_table@16272)`
  - `16930 (top_vm_table@16896)`
  - `25021 (top_vm_table@24984)`

## `top_vm_table`

- Definition lines: `[5683, 16272, 16896, 24984, 26054]`
- Runtime-final definition: line `26054`
- Aliases/default captures: `3`
- Static load sites: `3`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `14253: content = f'''\n    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div`
  - `26051: _top_vm_table_v48135_base = top_vm_table`
  - `7753: content = f"""\n    <div class="card top-card">\n        <div class="top-grid">\n            <div>\n                <div class="label">Latest Available</div>\n           `
- Caller/load evidence:
  - `7784 (top_page@7744)`
  - `14258 (top_page_v484@14240)`
  - `26051 (<module>)`

## `vm_chart_svg`

- Definition lines: `[4263, 35657]`
- Runtime-final definition: line `35657`
- Aliases/default captures: `0`
- Static load sites: `0`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.

## `vm_chart_table`

- Definition lines: `[4463, 35776]`
- Runtime-final definition: line `35776`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `35754: _v5058r5_vm_chart_table_base = vm_chart_table`
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `8515 (vm_page@8398)`
  - `35754 (<module>)`

## `vm_metric_chart_svg`

- Definition lines: `[4348, 35693]`
- Runtime-final definition: line `35693`
- Aliases/default captures: `2`
- Static load sites: `15`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `8305: content = f'''\n    <div class="card page-title-card">\n        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>\n     `
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `8335 (node_page@8272)`
  - `8341 (node_page@8272)`
  - `8346 (node_page@8272)`
  - `8351 (node_page@8272)`
  - `8355 (node_page@8272)`
  - `8359 (node_page@8272)`
  - `8364 (node_page@8272)`
  - `8506 (vm_page@8398)`
  - `8507 (vm_page@8398)`
  - `8508 (vm_page@8398)`
  - `8509 (vm_page@8398)`
  - `8510 (vm_page@8398)`
  - `8511 (vm_page@8398)`
  - `8512 (vm_page@8398)`
  - `8513 (vm_page@8398)`

## `vm_period_links`

- Definition lines: `[3778, 14216, 14387]`
- Runtime-final definition: line `14387`
- Aliases/default captures: `2`
- Static load sites: `2`
- Decorated definitions: `0`
- Can remove older implementation(s): **No**
- Decision: retained; static absence alone is not sufficient in this append-only wrapper architecture.
- Alias evidence:
  - `13776: _vm_period_links_v483 = vm_period_links`
  - `8493: content = f'''\n    {migration_notice}\n    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="marg`
- Caller/load evidence:
  - `8496 (vm_page@8398)`
  - `13776 (<module>)`

