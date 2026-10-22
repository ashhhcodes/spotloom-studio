"use client";

import { useEffect, useState } from "react";

const themes = ["system", "light", "dark"] as const;
type Theme = (typeof themes)[number];

export function ThemePicker() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function chooseTheme(nextTheme: Theme) {
    setTheme(nextTheme);
  }

  return (
    <fieldset className="theme-picker">
      <legend>Appearance</legend>
      <div className="theme-options" aria-label="Color theme">
        {themes.map((option) => (
          <button
            aria-pressed={theme === option}
            className="theme-option"
            key={option}
            onClick={() => chooseTheme(option)}
            type="button"
          >
            {option[0].toUpperCase() + option.slice(1)}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
