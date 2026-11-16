using Microsoft.UI.Xaml.Markup;

namespace Tobatools.Services;

/// <summary>Localized XAML value, resolved once when the element is created.</summary>
[MarkupExtensionReturnType(ReturnType = typeof(string))]
public sealed class LocExtension : MarkupExtension
{
    public string Key { get; set; } = string.Empty;
    protected override object ProvideValue() => LocalizationService.Instance.Get(Key);
}
