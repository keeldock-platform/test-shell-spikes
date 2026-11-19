using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Windows.Automation;

public static class ScopedUia {
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
        if (failure != null) throw new InvalidOperationException("UIA " + name, failure);
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
        return Call(() => AutomationElement.RootElement.FindFirst(TreeScope.Children,
            new PropertyCondition(AutomationElement.ProcessIdProperty, processId)), "top-level-window");
    }
    public static AutomationElement.AutomationElementInformation Info(AutomationElement node) {
        return Call(() => node.Current, "properties");
    }
    public static void Focus(AutomationElement node) {
        Call(() => { node.SetFocus(); return true; }, "focus");
    }
    public static string Name(AutomationElement node) { return Call(() => node.Current.Name, "name"); }
    public static AutomationElement FindName(AutomationElement root, string name) {
        foreach (var node in Walk(root, 18, 2000)) if (Name(node) == name) return node;
        return null;
    }
}
