using ElementBlocks.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace ElementBlocks.Desktop.Views;

/// <summary>第二页：轮换间隔 + 常驻方块行为设置。</summary>
public sealed partial class RotationPage : Page
{
    private bool _loading;
    private bool _loaded;
    private readonly Action<Models.Element?> _onElementChanged;
    private readonly Action _onStateChanged;

    public RotationPage()
    {
        Diag.Log("RotationPage ctor begin");
        _onElementChanged = _ => Refresh();
        _onStateChanged = Refresh;
        InitializeComponent();
        Diag.Log("InitializeComponent done");
        BuildIntervalCombo();
        Refresh();
        Diag.Log("ctor Refresh done");

        // 页面加载完成后再允许处理用户交互事件，避免构造期异步触发的
        // SelectionChanged / ValueChanged 误调用 Set* 造成不必要的副作用或异常。
        Loaded += (_, _) => { _loaded = true; Diag.Log("RotationPage Loaded"); };

        App.State.ElementChanged += _onElementChanged;
        App.State.EnabledChanged += _onStateChanged;
        App.State.SettingsChanged += _onStateChanged;
        if (App.Rotation is not null) App.Rotation.Polled += _onStateChanged;
        Unloaded += (_, _) =>
        {
            _loaded = false;
            App.State.ElementChanged -= _onElementChanged;
            App.State.EnabledChanged -= _onStateChanged;
            App.State.SettingsChanged -= _onStateChanged;
            if (App.Rotation is not null) App.Rotation.Polled -= _onStateChanged;
        };
    }

    private void BuildIntervalCombo()
    {
        foreach (var option in App.State.Assets.Intervals)
        {
            IntervalCombo.Items.Add(new ComboBoxItem
            {
                Content = option.Label,
                Tag = option.Id,
            });
        }
    }

    private void Refresh()
    {
        _loading = true;
        var state = App.State;
        var cfg = state.Config;
        var cur = state.Current;

        CurrentText.Text = cur is null ? "未启用任何元素" : $"{cur.Number} {cur.NameZh} {cur.Symbol}";
        EnabledText.Text = $"{cfg.EnabledSymbols.Count} / {state.Assets.Elements.Elements.Count}";

        var interval = state.Assets.Interval(cfg.Rotation);
        bool inactive = interval.Minutes <= 0 || cfg.Paused || cfg.EnabledSymbols.Count < 2;
        if (inactive)
        {
            NextText.Text = cfg.Paused ? "已暂停" : (cfg.EnabledSymbols.Count < 2 ? "已启用元素不足 2 个" : "从不");
            HintText.Text = "";
        }
        else if (cfg.NextFireUtc is { } next)
        {
            var local = next.ToLocalTime();
            var remain = next - DateTimeOffset.UtcNow;
            NextText.Text = $"{local:MM-dd HH:mm}（{(remain.TotalSeconds > 0 ? FormatRemain(remain) : "即将")}）";
            HintText.Text = "下一次切换时刻会写入配置，重启 / 休眠恢复后继续按该时刻执行。";
        }
        else
        {
            NextText.Text = "排程中…";
        }

        foreach (ComboBoxItem item in IntervalCombo.Items)
            if ((item.Tag as string) == cfg.Rotation) { IntervalCombo.SelectedItem = item; break; }

        OpacitySlider.Value = cfg.Opacity;
        OpacityLabel.Text = $"不透明度：{Math.Round(cfg.Opacity * 100)}%";

        PauseSwitch.IsOn = cfg.Paused;
        ClickThroughSwitch.IsOn = cfg.ClickThrough;
        AutoStartSwitch.IsOn = cfg.AutoStart;
        SizeSlider.Value = cfg.BlockSize;
        SizeLabel.Text = $"方块大小：{cfg.BlockSize} px";

        foreach (ComboBoxItem item in AnchorBox.Items)
            if ((item.Tag as string) == cfg.Position.Anchor) { AnchorBox.SelectedItem = item; break; }

        _loading = false;
    }

    private static string FormatRemain(TimeSpan t) =>
        t.TotalHours >= 1 ? $"{(int)t.TotalHours} 小时 {t.Minutes} 分后"
                          : $"{Math.Max(0, (int)t.TotalMinutes)} 分钟后";

    private void IntervalCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: IntervalCombo_SelectionChanged");
            return;
        }
        if (_loading) return;
        if (IntervalCombo.SelectedItem is ComboBoxItem { Tag: string id }) App.State.SetRotation(id);
    }

    private void OpacitySlider_ValueChanged(object sender,
                                           Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: OpacitySlider_ValueChanged");
            return;
        }
        if (_loading) return;
        double v = Math.Clamp(e.NewValue, 0.1, 1.0);
        App.State.SetOpacity(v);
        OpacityLabel.Text = $"不透明度：{Math.Round(v * 100)}%";
    }

    private void Next_Click(object sender, RoutedEventArgs e)
    {
        App.State.RotateNext();
        App.Rotation?.RestartCycleAfterManualSwitch();
        Refresh();
    }

    private void PauseSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: PauseSwitch_Toggled");
            return;
        }
        if (_loading) return;
        App.State.SetPaused(PauseSwitch.IsOn);
    }

    private async void AutoStartSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: AutoStartSwitch_Toggled");
            return;
        }
        if (_loading) return;
        bool applied = await StartupService.ApplyAsync(AutoStartSwitch.IsOn);
        App.State.SetAutoStart(applied);
        _loading = true;
        AutoStartSwitch.IsOn = applied;
        _loading = false;
    }

    private void ClickThroughSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: ClickThroughSwitch_Toggled");
            return;
        }
        if (_loading) return;
        App.State.SetClickThrough(ClickThroughSwitch.IsOn);
    }

    private void AnchorBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: AnchorBox_SelectionChanged");
            return;
        }
        if (_loading) return;
        if (AnchorBox.SelectedItem is ComboBoxItem { Tag: string anchor })
            App.State.SetAnchor(anchor);
    }

    private void SizeSlider_ValueChanged(object sender,
                                         Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        if (!_loaded)
        {
            Diag.Log("pre-Loaded 事件: SizeSlider_ValueChanged");
            return;
        }
        if (_loading) return;
        App.State.SetBlockSize((int)e.NewValue);
    }
}
