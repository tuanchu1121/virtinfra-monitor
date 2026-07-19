# Manifest validator hotfix diff

```diff
--- /mnt/data/baseline-r5-original/virtinfra-monitor-50.5.9-prod-r5-node-groups-hotfix-additive-production-slim/install.sh	2026-07-18 20:17:55.000000000 +0000
+++ /mnt/data/fix-r5-manifest/virtinfra-monitor-50.5.9-prod-r5-node-groups-hotfix-additive-production-slim/install.sh	2026-07-19 01:42:48.914416642 +0000
@@ -83,16 +83,21 @@
     }
 
     listed="${listed#\*}"
-    [[ "$listed" == ./* ]] || {
-      printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
-      return 1
-    }
+    case "$listed" in
+      ./*) rel="${listed#./}" ;;
+      /*|'')
+        printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
+        return 1
+        ;;
+      *) rel="$listed" ;;
+    esac
 
-    rel="${listed#./}"
-    [[ -n "$rel" && "$rel" != /* && "$rel" != *'..'* ]] || {
-      printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
-      return 1
-    }
+    case "$rel" in
+      ''|.|..|../*|*/../*|*/..|./*|*/./*|*/.|*'//'* )
+        printf 'ERROR: Unsafe manifest path: %s\n' "$listed" >&2
+        return 1
+        ;;
+    esac
 
     source_file="$source_root/$rel"
     target_file="$clean_root/$rel"
```
