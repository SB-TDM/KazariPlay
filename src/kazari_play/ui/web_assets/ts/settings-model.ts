(function () {
  const defaults: SettingsHotkeyValues = {
    emergency_hide: 'Ctrl + F12',
    fullscreen_toggle: 'F11',
    mute_toggle: 'Ctrl + M',
    screenshot: 'F12',
  };

  function fmtKey(value: unknown): string {
    if (!value) return '';
    return String(value).split('+').map((part) => part.trim())
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' + ');
  }

  function parse(raw: unknown): SettingsConfig | null {
    try {
      const value = JSON.parse(String(raw || '{}')) as unknown;
      if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
      return value as SettingsConfig;
    } catch (e) {
      return null;
    }
  }

  function hotkeys(cfg: SettingsConfig): SettingsHotkeyValues {
    const hk = cfg.hotkeys || {};
    return {
      emergency_hide: fmtKey(hk.emergency_hide) || defaults.emergency_hide,
      fullscreen_toggle: fmtKey(hk.fullscreen_toggle) || defaults.fullscreen_toggle,
      mute_toggle: fmtKey(hk.mute_toggle) || defaults.mute_toggle,
      screenshot: fmtKey(hk.screenshot) || defaults.screenshot,
    };
  }

  const kit = window.SettingsKit || (window.SettingsKit = {} as SettingsKitApi);
  kit.model = { parse, fmtKey, defaults, hotkeys };
})();
