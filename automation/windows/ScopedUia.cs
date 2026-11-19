using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

public static class ScopedUia {
    private delegate bool EnumWindow(IntPtr handle, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr handle, StringBuilder name, int count);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    public static AutomationElement[] ShellWindows() {
        var handles = new List<IntPtr>();
        EnumWindows((handle, parameter) => {
            uint pid;
            GetWindowThreadProcessId(handle, out pid);
            if (!IsWindowVisible(handle)) return true;
            try {
                using (var owner = Process.GetProcessById((int)pid)) {
                    var name = owner.ProcessName;
                    if (name == "explorer" || name == "ShellExperienceHost" || name == "ShellHost") handles.Add(handle);
                }
            } catch (ArgumentException) { /* Window closed during enumeration. */ }
            return handles.Count < 200;
        }, IntPtr.Zero);
        if (handles.Count >= 200) throw new InvalidOperationException("Shell window node budget exceeded");
        var windows = new List<AutomationElement>();
        foreach (var handle in handles) windows.Add(Call(() => AutomationElement.FromHandle(handle), "shell-window"));
        return windows.ToArray();
    }
    public static AutomationElement[] NativeMenus() {
        var handles = new List<IntPtr>();
        EnumWindows((handle, parameter) => {
            var name = new StringBuilder(256);
            GetClassName(handle, name, name.Capacity);
            if (IsWindowVisible(handle) && name.ToString() == "#32768") handles.Add(handle);
            return handles.Count < 200;
        }, IntPtr.Zero);
        if (handles.Count >= 200) throw new InvalidOperationException("Native menu node budget exceeded");
        var menus = new List<AutomationElement>();
        foreach (var handle in handles) {
            menus.Add(Call(() => AutomationElement.FromHandle(handle), "native-menu-window"));
        }
        return menus.ToArray();
    }
    public static T Call<T>(Func<T> operation, string name) {
        T result = default(T);
        Exception failure = null;
        var done = new ManualResetEventSlim(false);
        var worker = new Thread(() => {
            try { result = operation(); } catch (Exception e) { failure = e; }
            finally { done.Set(); }
        });
        worker.IsBackground = true;
        worker.SetApartmentState(ApartmentState.MTA);
        worker.Start();
        if (!done.Wait(750)) throw new TimeoutException("UIA per-call timeout (750ms): " + name);
        if (worker.Join(50)) done.Dispose();
        if (failure != null) throw new InvalidOperationException("UIA " + name + ": " + failure.GetType().Name + ": " + failure.Message, failure);
        return result;
    }
    public static AutomationElement[] Walk(AutomationElement root, int maxDepth, int maxNodes) {
        var nodes = new List<AutomationElement>();
        var pending = new Queue<Tuple<AutomationElement, int>>();
        pending.Enqueue(Tuple.Create(root, 0));
        var clock = Stopwatch.StartNew();
        while (pending.Count > 0) {
            if (clock.ElapsedMilliseconds > 5000) throw new TimeoutException("UIA scoped walk exceeded 5s");
            var item = pending.Dequeue();
            if (item.Item2 >= maxDepth) continue;
            var parent = item.Item1;
            var child = Call(() => TreeWalker.ControlViewWalker.GetFirstChild(parent), "first-child");
            while (child != null) {
                if (nodes.Count >= maxNodes) throw new InvalidOperationException("UIA scoped walk node budget exceeded");
                nodes.Add(child);
                pending.Enqueue(Tuple.Create(child, item.Item2 + 1));
                var current = child;
                child = Call(() => TreeWalker.ControlViewWalker.GetNextSibling(current), "next-sibling");
                if (clock.ElapsedMilliseconds > 5000) throw new TimeoutException("UIA scoped siblings exceeded 5s");
            }
        }
        return nodes.ToArray();
    }
    public static AutomationElement WindowForPid(int processId) {
        // Enumerating desktop UIA providers blocks on unrelated startup windows.
        // Resolve the owned HWND first, then contact only that provider.
        using (var process = Process.GetProcessById(processId)) {
            var handle = process.MainWindowHandle;
            if (handle == IntPtr.Zero) return null;
            return Call(() => AutomationElement.FromHandle(handle), "top-level-window");
        }
    }
    public static AutomationElement.AutomationElementInformation Info(AutomationElement node) {
        return Call(() => node.Current, "properties");
    }
    public static void Focus(AutomationElement node) {
        Call(() => { node.SetFocus(); return true; }, "focus");
    }
    public static string Name(AutomationElement node) { return Call(() => node.Current.Name, "name"); }
    public static string Help(AutomationElement node) { return Call(() => node.Current.HelpText, "help-text"); }
    public static AutomationElement FindName(AutomationElement root, string name) {
        // FindFirst stops at the requested control. Walking every sibling first
        // hit unresponsive provider nodes before reaching an already-ready input.
        return Call(() => root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.NameProperty, name)), "find-name: " + name);
    }
}
