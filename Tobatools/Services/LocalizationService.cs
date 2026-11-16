using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Xml.Linq;

namespace Tobatools.Services;

/// <summary>
/// Immutable, process-wide translation catalog. Uses embedded .resw XML, not the
/// UWP current-view ResourceLoader (which requires CoreWindow/package identity).
/// Safe to read from device polling and image-processing background threads.
/// Language selection is persisted for the next launch; running jobs never change language.
/// </summary>
public sealed class LocalizationService
{
    public const string LangSystem = "system";
    public const string LangZhCN = "zh-CN";
    public const string LangEnUS = "en-US";
    public const string LangRuRU = "ru-RU";
    public static LocalizationService Instance { get; } = new();

    private readonly IReadOnlyDictionary<string, string> _strings;
    private readonly IReadOnlyDictionary<string, string> _fallback;
    public string StartupLanguageCode { get; }
    public string EffectiveLanguageCode { get; }
    public CultureInfo DisplayCulture { get; }
    public string CurrentLanguageCode => NormalizeLanguage(SettingsService.Instance.Get("appearance/language", LangSystem));
    public bool RestartRequired => CurrentLanguageCode != StartupLanguageCode;

    private LocalizationService()
    {
        StartupLanguageCode = CurrentLanguageCode;
        EffectiveLanguageCode = ResolveLanguage(StartupLanguageCode, CultureInfo.CurrentUICulture.Name);
        DisplayCulture = CultureInfo.GetCultureInfo(EffectiveLanguageCode);
        _fallback = LoadCatalog(LangZhCN);
        _strings = EffectiveLanguageCode == LangZhCN ? _fallback : LoadCatalog(EffectiveLanguageCode);
    }

    public static string NormalizeLanguage(string? code) => code switch
    {
        LangZhCN => LangZhCN,
        LangEnUS => LangEnUS,
        LangRuRU => LangRuRU,
        _ => LangSystem
    };

    public static string ResolveLanguage(string code, string systemLanguage)
    {
        if (NormalizeLanguage(code) != LangSystem) return code;
        if (systemLanguage.StartsWith("ru", StringComparison.OrdinalIgnoreCase)) return LangRuRU;
        if (systemLanguage.StartsWith("zh", StringComparison.OrdinalIgnoreCase)) return LangZhCN;
        return LangEnUS;
    }

    private static IReadOnlyDictionary<string, string> LoadCatalog(string language)
    {
        var assembly = typeof(LocalizationService).Assembly;
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var name in assembly.GetManifestResourceNames())
        {
            var path = name.Replace('\\', '/');
            var prefix = "Strings/" + language + "/";
            if (!path.StartsWith(prefix, StringComparison.Ordinal) || !path.EndsWith(".resw", StringComparison.Ordinal)) continue;
            var group = path[prefix.Length..^5];
            using var stream = assembly.GetManifestResourceStream(name)!;
            foreach (var entry in XDocument.Load(stream).Root!.Elements("data"))
            {
                var key = (string?)entry.Attribute("name") ?? throw new InvalidOperationException("Resource name missing: " + name);
                var value = (string?)entry.Element("value") ?? throw new InvalidOperationException("Resource value missing: " + key);
                result.Add(group == "Resources" ? key : group + "/" + key, value);
            }
        }
        if (result.Count == 0) throw new InvalidOperationException("Embedded translation catalog missing: " + language);
        return result;
    }

    public string Get(string key)
    {
        if (_strings.TryGetValue(key, out var text)) return text;
        Debug.WriteLine("Missing translation: " + EffectiveLanguageCode + "/" + key);
        return _fallback.TryGetValue(key, out text) ? text : "[" + key + "]";
    }

    public string Format(string key, params object?[] args) => string.Format(DisplayCulture, Get(key), args);

    /// <summary>Save only. No resource reset, page recreation, process exit or running-job interruption.</summary>
    public bool SetLanguage(string code)
    {
        code = NormalizeLanguage(code);
        if (CurrentLanguageCode == code) return false;
        SettingsService.Instance.Set("appearance/language", code);
        return true;
    }

    public void ApplySavedLanguage()
    {
        // Keep CurrentCulture unchanged: device command/number formatting must remain stable.
        CultureInfo.CurrentUICulture = DisplayCulture;
        CultureInfo.DefaultThreadCurrentUICulture = DisplayCulture;
    }
}
