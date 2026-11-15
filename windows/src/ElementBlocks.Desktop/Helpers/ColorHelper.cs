using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace ElementBlocks.Desktop.Helpers;

public static class ColorHelper
{
    public static Color Parse(string hex)
    {
        var s = hex.TrimStart('#');
        if (s.Length == 8)
            return Color.FromArgb(Convert.ToByte(s[0..2], 16), Convert.ToByte(s[2..4], 16),
                                  Convert.ToByte(s[4..6], 16), Convert.ToByte(s[6..8], 16));
        return Color.FromArgb(255, Convert.ToByte(s[0..2], 16),
                                 Convert.ToByte(s[2..4], 16), Convert.ToByte(s[4..6], 16));
    }

    public static SolidColorBrush Brush(string hex) => new(Parse(hex));
}
