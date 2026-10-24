// Optional on-demand bridge. No app launches, global keys, coordinates or account APIs.
// Build with scripts/build-call-bridge.py. JSON requests travel over stdin, not argv.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Automation;

public static class CallControl {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 65536 };
    static string Hash(string text) {
        using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(Encoding.UTF8.GetBytes(text)));
    }
    static string Hex(byte[] data) { return BitConverter.ToString(data).Replace("-", "").ToLowerInvariant(); }
    static string FileHash(string path) {
        using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path)) return Hex(sha.ComputeHash(stream));
    }
    static string Text(Dictionary<string, object> value, string name) {
        if (!value.ContainsKey(name) || !(value[name] is string)) throw new InvalidOperationException();
        return (string)value[name];
    }
    static Process BoundProcess(Dictionary<string, object> profile) {
        var process = Process.GetProcessById(Convert.ToInt32(profile["pid"]));
        string channel = Text(profile, "channel");
        string expected = channel == "sim" ? "PhoneExperienceHost" : channel == "whatsapp_personal" ? "WhatsApp" : "";
        if (expected == "" || !String.Equals(process.ProcessName, expected, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException();
        if (process.HasExited || !String.Equals(process.MainModule.FileName, Text(profile, "executable"), StringComparison.OrdinalIgnoreCase)
            || process.StartTime.ToUniversalTime().Ticks.ToString() != Text(profile, "process_start")
            || FileHash(process.MainModule.FileName) != Text(profile, "sha256")) throw new InvalidOperationException();
        return process;
    }
    static List<AutomationElement> Roots(int pid) {
        var found = AutomationElement.RootElement.FindAll(TreeScope.Children,
            new PropertyCondition(AutomationElement.ProcessIdProperty, pid));
        if (found.Count > 32) throw new InvalidOperationException();
        var roots = new List<AutomationElement>();
        foreach (AutomationElement root in found) roots.Add(root);
        return roots;
    }
    static List<AutomationElement> Find(AutomationElement root, string id, bool button) {
        Condition condition = new PropertyCondition(AutomationElement.AutomationIdProperty, id);
        if (button) condition = new AndCondition(condition, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button));
        var elements = root.FindAll(TreeScope.Descendants, condition);
        if (elements.Count > 16) throw new InvalidOperationException();
        var result = new List<AutomationElement>();
        foreach (AutomationElement element in elements) {
            if (!element.Current.IsOffscreen && element.Current.IsEnabled) result.Add(element);
        }
        return result;
    }
    static string Runtime(AutomationElement element) { return String.Join(".", element.GetRuntimeId()); }
    sealed class Snapshot {
        public string State = "absent", Caller = Hash(""), Fingerprint = Hash("absent"), Start;
        public string View = Hash("absent");
        public AutomationElement Button;
        public object Public() { return new { state = State, fingerprint = Fingerprint, caller_hash = Caller, view_id = View, process_start = Start }; }
    }
    static Snapshot Observe(Dictionary<string, object> profile) {
        using (var process = BoundProcess(profile)) {
            var result = new Snapshot { Start = process.StartTime.ToUniversalTime().Ticks.ToString() };
            var candidates = new List<Snapshot>();
            foreach (var root in Roots(process.Id)) {
                if (root.Current.ClassName != Text(profile, "window_class")) continue;
                var caller = Find(root, Text(profile, "caller_id"), false);
                var answer = Find(root, Text(profile, "answer_id"), true);
                var decline = Find(root, Text(profile, "decline_id"), true);
                var end = Find(root, Text(profile, "hangup_id"), true);
                var ended = Find(root, Text(profile, "ended_id"), false);
                if (caller.Count != 1 || String.IsNullOrWhiteSpace(caller[0].Current.Name)) continue;
                string state = answer.Count == 1 && decline.Count == 1 && end.Count == 0 && ended.Count == 0 ? "ringing"
                    : answer.Count == 0 && decline.Count == 0 && end.Count == 1 && ended.Count == 0 ? "active"
                    : answer.Count == 0 && decline.Count == 0 && end.Count == 0 && ended.Count == 1 ? "ended" : "ambiguous";
                if (answer.Count == 0 && decline.Count == 0 && end.Count == 0 && ended.Count == 0) continue;
                var candidate = new Snapshot { State = state, Caller = Hash(caller[0].Current.Name), Start = result.Start };
                candidate.Button = state == "ringing" ? answer[0] : state == "active" ? end[0] : null;
                candidate.View = Hash(result.Start + "\n" + Runtime(root) + "\n" + Runtime(caller[0]) + "\n" + candidate.Caller);
                candidate.Fingerprint = Hash(candidate.View + "\n" + state + "\n" + (candidate.Button == null ? "" : Runtime(candidate.Button)));
                candidates.Add(candidate);
            }
            if (candidates.Count == 1) return candidates[0];
            if (candidates.Count > 1) result.State = "ambiguous";
            return result;
        }
    }
    static object Inventory() {
        var result = new List<object>();
        foreach (var process in Process.GetProcesses()) {
            using (process) try {
                string name = process.ProcessName;
                if (name.IndexOf("whatsapp", StringComparison.OrdinalIgnoreCase) < 0 && name != "PhoneExperienceHost") continue;
                result.Add(new { pid = process.Id, executable = process.MainModule.FileName,
                    sha256 = FileHash(process.MainModule.FileName), process_start = process.StartTime.ToUniversalTime().Ticks.ToString() });
            } catch (Exception) { /* Unreadable process is never enrolled. */ }
        }
        return new { ok = true, processes = result, readiness_proven = false };
    }
    static object Inspect(int pid) {
        using (var process = Process.GetProcessById(pid)) {
            if (!String.Equals(process.ProcessName, "PhoneExperienceHost", StringComparison.OrdinalIgnoreCase)
                && !String.Equals(process.ProcessName, "WhatsApp", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException();
        }
        var windows = new List<object>();
        foreach (var root in Roots(pid)) {
            var controls = new List<object>();
            var elements = root.FindAll(TreeScope.Descendants,
                new OrCondition(new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button),
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Text)));
            if (elements.Count > 256) {
                windows.Add(new { window_class = root.Current.ClassName, controls = controls, too_many_controls = true });
                continue;
            }
            foreach (AutomationElement element in elements) {
                string id = element.Current.AutomationId;
                if (id.Length == 0 || element.Current.IsOffscreen) continue;
                // Text values (contacts/caller/conversations) are deliberately omitted.
                object invoke;
                controls.Add(new { automation_id = id, control_type = element.Current.ControlType.ProgrammaticName,
                    label = element.Current.ControlType == ControlType.Button ? element.Current.Name : null,
                    invokable = element.TryGetCurrentPattern(InvokePattern.Pattern, out invoke) });
            }
            windows.Add(new { window_class = root.Current.ClassName, controls = controls });
        }
        return new { ok = true, windows = windows };
    }
    static object Execute(Dictionary<string, object> request) {
        string operation = Text(request, "operation");
        if (operation == "inventory") return Inventory();
        if (operation == "selftest") return new { ok = Hash("INARA").Length == 64, ui_activated = false };
        if (operation == "inspect") return Inspect(Convert.ToInt32(request["pid"]));
        if (operation != "observe" && operation != "answer" && operation != "hangup") throw new InvalidOperationException();
        var profile = (Dictionary<string, object>)request["profile"];
        var snapshot = Observe(profile);
        if (operation == "observe") return new { ok = true, observation = snapshot.Public() };
        if (!(bool)profile["controls_confirmed"] || !(bool)profile["route_confirmed"]) throw new InvalidOperationException();
        string required = operation == "answer" ? "ringing" : "active";
        if (snapshot.State != required || snapshot.Fingerprint != Text(request, "expected") || snapshot.Button == null)
            throw new InvalidOperationException();
        // Reobserve immediately before Invoke. No cached UIA element index is used.
        var fresh = Observe(profile);
        if (fresh.State != required || fresh.Fingerprint != snapshot.Fingerprint || fresh.Button == null)
            throw new InvalidOperationException();
        object pattern;
        if (!fresh.Button.TryGetCurrentPattern(InvokePattern.Pattern, out pattern)) throw new InvalidOperationException();
        ((InvokePattern)pattern).Invoke();
        return new { ok = true, invoked = true }; // Invocation is not evidence of connection.
    }
    [STAThread]
    public static int Main() {
        try {
            using (var reader = new StreamReader(Console.OpenStandardInput(), Encoding.UTF8)) {
                char[] data = new char[65537];
                int count = 0, read;
                while (count < data.Length && (read = reader.Read(data, count, data.Length - count)) > 0) count += read;
                if (count > 65536) throw new InvalidOperationException();
                var request = Json.Deserialize<Dictionary<string, object>>(new string(data, 0, count));
                Console.Write(Json.Serialize(Execute(request)));
            }
            return 0;
        } catch (Exception) {
            Console.Write("{\"ok\":false,\"code\":\"call_binding_unavailable\"}");
            return 2;
        }
    }
}
