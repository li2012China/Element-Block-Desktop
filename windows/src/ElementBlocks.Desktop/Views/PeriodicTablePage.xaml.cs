using ElementBlocks.Desktop.Helpers;
using ElementBlocks.Desktop.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;

namespace ElementBlocks.Desktop.Views;

/// <summary>
/// 第一页：18 列 × 7 周期 + 镧系/锕系两行，共 118 个 ToggleButton。
/// 网格坐标完全来自 shared/elements.json（row / column），WinUI3 与 GTK 用同一套数据，
/// 因此两端排版一致；这里不硬编码任何元素位置。
/// </summary>
public sealed partial class PeriodicTablePage : Page
{
    private const double CellWidth = 60;
    private const double CellHeight = 64;
    private const double HeaderWidth = 40;
    private const double HeaderHeight = 26;
    private const double SpacerHeight = 20;

    private readonly Dictionary<string, ToggleButton> _buttons = new(StringComparer.Ordinal);

    public PeriodicTablePage()
    {
        InitializeComponent();
        BuildLegend();
        BuildGrid();
        RefreshAll();
        App.State.EnabledChanged += RefreshAll;
        Unloaded += (_, _) => App.State.EnabledChanged -= RefreshAll;
    }

    private void BuildGrid()
    {
        var layout = App.State.Assets.Elements.Layout;

        TableGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(HeaderWidth) });
        for (int c = 1; c <= layout.Columns; c++)
            TableGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(CellWidth) });

        TableGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(HeaderHeight) });
        for (int r = 1; r <= 7; r++)
            TableGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(CellHeight) });
        TableGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(SpacerHeight) }); // row 8
        TableGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(CellHeight) });  // row 9
        TableGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(CellHeight) });  // row 10

        // 族 / 周期表头
        for (int c = 1; c <= layout.Columns; c++)
        {
            var label = new TextBlock
            {
                Text = layout.GroupLabels.TryGetValue(c.ToString(), out var g) ? g : c.ToString(),
                FontSize = 11, Opacity = 0.6,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
            Grid.SetRow(label, 0); Grid.SetColumn(label, c);
            TableGrid.Children.Add(label);
        }
        for (int r = 1; r <= 7; r++)
        {
            var label = new TextBlock
            {
                Text = r.ToString(), FontSize = 13, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                Opacity = 0.7,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
            Grid.SetRow(label, r); Grid.SetColumn(label, 0);
            TableGrid.Children.Add(label);
        }

        AddSeriesLabel(9, "镧系");
        AddSeriesLabel(10, "锕系");

        // f 区占位（主表第 6/7 周期第 3 族）
        foreach (var p in layout.Placeholders)
        {
            var box = new Border
            {
                Background = ColorHelper.Brush("#E8DECA"),
                BorderBrush = ColorHelper.Brush("#B23A2E"),
                BorderThickness = new Thickness(1.2),
                CornerRadius = new CornerRadius(2),
                Margin = new Thickness(2),
                Child = new StackPanel
                {
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                    Children =
                    {
                        new TextBlock { Text = p.Label, FontSize = 11, HorizontalAlignment = HorizontalAlignment.Center },
                        new TextBlock { Text = p.SubLabel, FontSize = 13, HorizontalAlignment = HorizontalAlignment.Center },
                    }
                }
            };
            Grid.SetRow(box, p.Row); Grid.SetColumn(box, p.Column);
            TableGrid.Children.Add(box);
        }

        foreach (var e in App.State.Assets.Elements.Elements)
        {
            var btn = CreateButton(e);
            Grid.SetRow(btn, e.Row);
            Grid.SetColumn(btn, e.Column);
            TableGrid.Children.Add(btn);
            _buttons[e.Symbol] = btn;
        }
    }

    private void AddSeriesLabel(int row, string text)
    {
        var label = new TextBlock
        {
            Text = text, FontSize = 12, Opacity = 0.7,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        };
        Grid.SetRow(label, row); Grid.SetColumn(label, 1);
        Grid.SetColumnSpan(label, 2);
        TableGrid.Children.Add(label);
    }

    private ToggleButton CreateButton(Element e)
    {
        var style = App.State.Assets.Style(e.Category);
        var text = ColorHelper.Brush(style.Text);
        var accent = ColorHelper.Brush(e.Radioactive ? App.State.Assets.Theme.Tile.Accent : style.Text);

        var content = new Grid { Margin = new Thickness(3, 2, 3, 2) };
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        content.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var top = new Grid();
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var num = new TextBlock { Text = e.Number.ToString(), FontSize = 10, Foreground = accent };
        var sym = new TextBlock { Text = e.Symbol, FontSize = 13, FontWeight = Microsoft.UI.Text.FontWeights.Bold,
                                  Foreground = accent, HorizontalAlignment = HorizontalAlignment.Right };
        Grid.SetColumn(num, 0); Grid.SetColumn(sym, 1);
        top.Children.Add(num); top.Children.Add(sym);
        Grid.SetRow(top, 0);

        var zh = new TextBlock
        {
            Text = e.NameZh, FontSize = 19, Foreground = text,
            FontFamily = new FontFamily("Microsoft YaHei"),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        };
        Grid.SetRow(zh, 1);

        var mass = new TextBlock { Text = e.Mass, FontSize = 9, Foreground = text, Opacity = 0.85,
                                   HorizontalAlignment = HorizontalAlignment.Center };
        Grid.SetRow(mass, 2);

        content.Children.Add(top); content.Children.Add(zh); content.Children.Add(mass);

        var btn = new ToggleButton
        {
            Content = content,
            Margin = new Thickness(2),
            Padding = new Thickness(0),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
            VerticalContentAlignment = VerticalAlignment.Stretch,
            Background = ColorHelper.Brush(style.Fill),
            BorderBrush = ColorHelper.Brush(style.Border),
            BorderThickness = new Thickness(e.Category is "transition" or "lanthanide" or "actinide" ? 1.6 : 0.8),
            CornerRadius = new CornerRadius(2),
            Tag = e.Symbol,
        };
        ToolTipService.SetToolTip(btn, e.Tooltip);
        btn.Click += (_, _) => App.State.SetEnabled(e.Symbol, btn.IsChecked == true);
        return btn;
    }

    private void BuildLegend()
    {
        foreach (var (key, style) in App.State.Assets.Theme.Categories)
        {
            var label = App.State.Assets.Elements.Elements
                .FirstOrDefault(e => e.Category == key)?.CategoryLabel ?? key;
            var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5,
                                         VerticalAlignment = VerticalAlignment.Center };
            panel.Children.Add(new Border
            {
                Width = 11, Height = 11, CornerRadius = new CornerRadius(2),
                Background = ColorHelper.Brush(style.Fill),
                BorderBrush = ColorHelper.Brush(style.Border), BorderThickness = new Thickness(1),
            });
            panel.Children.Add(new TextBlock { Text = label, FontSize = 10, Opacity = 0.7,
                                               VerticalAlignment = VerticalAlignment.Center });
            LegendPanel.Children.Add(panel);
        }
    }

    private void RefreshAll()
    {
        var theme = App.State.Assets.Theme.Tile;
        foreach (var (symbol, btn) in _buttons)
        {
            bool on = App.State.IsEnabled(symbol);
            btn.IsChecked = on;
            btn.Opacity = on ? 1.0 : theme.DisabledOpacity;
        }
    }

    private void SelectAll_Click(object sender, RoutedEventArgs e) => App.State.SetAll(true);
    private void SelectNone_Click(object sender, RoutedEventArgs e) => App.State.SetAll(false);
    private void OnlyNatural_Click(object sender, RoutedEventArgs e) => App.State.OnlyNatural();
    private void Reset_Click(object sender, RoutedEventArgs e) => App.State.ResetDefaults();
}
