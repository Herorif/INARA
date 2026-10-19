"""Source/manifest guard and tool inventory. This is explicitly not an APK compile."""

import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
android = ROOT / "android"
namespace = "{http://schemas.android.com/apk/res/android}"
manifest = ET.parse(android / "app/src/main/AndroidManifest.xml").getroot()
permissions = [node.attrib[namespace + "name"] for node in manifest.findall("uses-permission")]
assert permissions == ["android.permission.INTERNET"]
application = manifest.find("application")
assert application.attrib[namespace + "allowBackup"] == "false"
assert application.attrib[namespace + "usesCleartextTraffic"] == "false"
services = application.findall("service")
assert len(services) == 1 and not application.findall("receiver")
assert services[0].attrib[namespace + "name"] == ".SelectedNotificationListener"
assert services[0].attrib[namespace + "exported"] == "false"
assert services[0].attrib[namespace + "permission"] == "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"
assert services[0].find("intent-filter/action").attrib[namespace + "name"] == "android.service.notification.NotificationListenerService"
assert '"NOTIFICATION_ACCEPTANCE_ENABLED", "false"' in (android / "app/build.gradle.kts").read_text()
assert application.find("activity").attrib[namespace + "resizeableActivity"] == "true"
ET.parse(android / "app/src/main/res/xml/data_extraction_rules.xml")
for name in ("MainActivity", "CompanionModel", "DeviceSecurity", "CompanionClient", "NotificationVault", "SelectedNotificationListener", "NotificationCard"):
    assert (android / f"app/src/main/java/com/inara/companion/{name}.kt").is_file()
sdk = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
tools = {name: shutil.which(name) for name in ("java", "javac", "gradle", "adb")}
print(json.dumps({"source_manifest_guards": "passed", "permissions": permissions,
    "tools": tools, "android_sdk": sdk, "apk_compiled": False,
    "note": "Source guards do not validate Kotlin compilation, Compose rendering, Keystore or phone behavior."}, indent=2))
