using ElementBlocks.Desktop.Helpers;
using ElementBlocks.Desktop.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace ElementBlocks.Desktop.Controls;

public sealed partial class ElementBlock : UserControl
{
    public ElementBlock() => InitializeComponent();

    /// <summary>null 表示没有任何已启用元素，方块显示占位文案而不是留白。</summary>
    public void SetElement(Element? element, TileTheme theme)
    {
        var fg = ColorHelper.Brush(theme.Foreground);
        RootBorder.Background = ColorHelper.Brush(theme.Background);
        RootBorder.BorderBrush = ColorHelper.Brush(theme.Border);
        RootBorder.BorderThickness = new Thickness(theme.BorderWidth);
        RootBorder.CornerRadius = new CornerRadius(theme.CornerRadius);

        NumberText.Foreground = fg;
        SymbolText.Foreground = fg;
        NameZhText.Foreground = fg;
        NameEnText.Foreground = fg;
        MassText.Foreground = fg;

        NumberText.FontSize = theme.FontNumber + 2;
        SymbolText.FontSize = theme.FontSymbol + 1;
        NameZhText.FontSize = theme.FontNameZh + 4;
        NameEnText.FontSize = theme.FontNameEn;
        MassText.FontSize = theme.FontMass;

        if (element is null)
        {
            NumberText.Text = "--";
            SymbolText.Text = "";
            NameZhText.Text = "—";
            NameZhText.FontSize = 34;
            NameEnText.Text = "未启用任何元素";
            MassText.Text = "请在设置中启用";
            NumberText.Foreground = fg;
            SymbolText.Foreground = fg;
            return;
        }

        NumberText.Text = element.Number.ToString();
        SymbolText.Text = element.Symbol;
        NameZhText.Text = element.NameZh;
        NameEnText.Text = element.NameEn;
        MassText.Text = element.Mass;

        // 参考图的中文周期表约定：放射性元素的原子序数与符号用红色
        var accent = ColorHelper.Brush(theme.Accent);
        NumberText.Foreground = element.Radioactive ? accent : fg;
        SymbolText.Foreground = element.Radioactive ? accent : fg;
    }
}
